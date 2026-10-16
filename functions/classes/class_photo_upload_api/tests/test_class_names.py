import datetime
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests_mock as requests_mock_lib
from common.neoncrm import NeonCRM, NeonCRMError

from functions.classes.class_photo_upload_api.class_names import (
    CLASS_LOOKBACK_MONTHS,
    branch_name,
    class_name_from_event_name,
    class_names_from_events,
    collision_warning,
    exact_file_name,
    fetch_classes,
    file_name_problem,
    fuzzy_collisions,
    fuzzy_key,
    lookback_start,
    neon_search_fields,
    superseded_images,
)

FIXTURES = Path(__file__).parent / "fixtures"
SITE_EXTENSIONS = ["avif", "gif", "heif", "jpeg", "jpg", "png", "tiff", "webp"]
NEON_SEARCH_URL = "https://api.neoncrm.com/v2/events/search"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


CURRENT_IMAGES: list[str] = _load("asmbly_classes_images_bdf601b.json")
PR49_IMAGES: list[dict[str, str]] = _load("asmbly_classes_pr49_images.json")


def test_fixtures_have_the_documented_sizes() -> None:
    assert len(CURRENT_IMAGES) == 131
    assert len(PR49_IMAGES) == 56


@pytest.mark.parametrize(
    "event_name, expected",
    [
        ("Intro to Forging w/ Pat", "Intro to Forging"),
        ("  Woodshop Safety  ", "Woodshop Safety"),
        ("  Bandsaw Box ", "Bandsaw Box"),
        ("Glaze w/o fear w/ Sam", "Glaze w/o fear"),
    ],
)
def test_class_name_from_event_name(event_name: str, expected: str) -> None:
    assert class_name_from_event_name(event_name) == expected


@pytest.mark.parametrize(
    "today, expected",
    [
        (datetime.date(2026, 10, 16), datetime.date(2026, 6, 16)),
        (datetime.date(2026, 6, 30), datetime.date(2026, 2, 28)),
        (datetime.date(2028, 6, 30), datetime.date(2028, 2, 29)),
        (datetime.date(2026, 2, 15), datetime.date(2025, 10, 15)),
    ],
)
def test_lookback_start(today: datetime.date, expected: datetime.date) -> None:
    assert lookback_start(today) == expected


def test_lookback_is_four_months() -> None:
    assert CLASS_LOOKBACK_MONTHS == 4


def test_neon_search_fields_uses_end_date_and_lookback() -> None:
    assert neon_search_fields(datetime.date(2026, 10, 16)) == [
        {"field": "Event End Date", "operator": "GREATER_AND_EQUAL", "value": "2026-06-16"}
    ]


def test_class_names_from_events_dedupes_and_sorts() -> None:
    events = [
        {"Event ID": "1", "Event Name": "intro to Lathe w/ A"},
        {"Event ID": "2", "Event Name": "Woodshop Safety w/ A"},
        {"Event ID": "3", "Event Name": "Woodshop Safety w/ B"},
        {"Event ID": "4", "Event Name": "Woodshop Safety"},
        {"Event ID": "5", "Event Name": "Bandsaw Box"},
        {"Event ID": "6", "Event Name": "   "},
        {"Event ID": "7", "Event Name": " w/ Somebody"},
        {"Event ID": "8", "Event Name": None},
        {"Event ID": "9"},
        "not an object",
        None,
    ]

    assert class_names_from_events(events) == ["Bandsaw Box", "intro to Lathe", "Woodshop Safety"]


def test_class_names_from_events_keeps_names_that_differ_in_case() -> None:
    events = [{"Event Name": "Intro To Lathe"}, {"Event Name": "Intro to Lathe"}]

    assert sorted(class_names_from_events(events)) == ["Intro To Lathe", "Intro to Lathe"]


def test_fetch_classes_reads_neon_once_and_returns_names() -> None:
    neon = MagicMock(spec=NeonCRM)
    neon.search_events.return_value = (
        _load("neon_events_search_page0.json")["searchResults"]
        + _load("neon_events_search_page1.json")["searchResults"]
    )

    classes = fetch_classes(neon, datetime.date(2026, 10, 16))

    assert classes == [
        "Ceramics: Glazing Workshop",
        "Intro to Forging",
        "Tormach Part 2: CNC Milling",
        "Woodshop Safety",
    ]
    neon.search_events.assert_called_once_with(
        [{"field": "Event End Date", "operator": "GREATER_AND_EQUAL", "value": "2026-06-16"}],
        ["Event ID", "Event Name"],
    )


def test_fetch_classes_reads_both_neon_pages(requests_mock: requests_mock_lib.Mocker) -> None:
    requests_mock.post(
        NEON_SEARCH_URL,
        [
            {"json": _load("neon_events_search_page0.json")},
            {"json": _load("neon_events_search_page1.json")},
        ],
    )

    classes = fetch_classes(NeonCRM("org", "key"), datetime.date(2026, 10, 16))

    assert len(classes) == 4
    assert requests_mock.call_count == 2
    assert all(r.method == "POST" for r in requests_mock.request_history)


def test_fetch_classes_propagates_neon_error() -> None:
    neon = MagicMock(spec=NeonCRM)
    neon.search_events.side_effect = NeonCRMError("events/search failed (status 500)")

    with pytest.raises(NeonCRMError):
        fetch_classes(neon, datetime.date(2026, 10, 16))


def test_fetch_classes_logs_counts_not_names(caplog: pytest.LogCaptureFixture) -> None:
    neon = MagicMock(spec=NeonCRM)
    neon.search_events.return_value = [{"Event ID": "1", "Event Name": "Secret Class w/ Pat"}]

    with caplog.at_level("INFO"):
        fetch_classes(neon, datetime.date(2026, 10, 16))

    assert "Read 1 events, 1 classes" in caplog.text
    assert "Pat" not in caplog.text


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Ceramics: Glazing Workshop", "ceramicsglazingworkshop"),
        ("Ceramics__Glazing_Workshop.jpg", "ceramicsglazingworkshop"),
        ("Tormach_Part_2_CNC Milling.jpg", "tormachpart2cncmilling"),
        ("Beginner_Handbuilding__Slabs(1).jpg", "beginnerhandbuildingslabs(1)"),
        ("A & B & C", "aandb&c"),
        ("Ver. 2: Intro", "ver"),
    ],
)
def test_fuzzy_key(name: str, expected: str) -> None:
    assert fuzzy_key(name) == expected


@pytest.mark.parametrize(
    "class_name, expected",
    [
        ("Ceramics: Glazing Workshop", "Ceramics__Glazing_Workshop.jpg"),
        ("Tormach Part 2: CNC Milling", "Tormach_Part_2__CNC_Milling.jpg"),
        ("Weaponized Plastic Bots", "Weaponized_Plastic_Bots.jpg"),
        ("Ceramics - Make a Tile Relief", "Ceramics_-_Make_a_Tile_Relief.jpg"),
        ("Two  spaces", "Two_spaces.jpg"),
    ],
)
def test_exact_file_name(class_name: str, expected: str) -> None:
    assert exact_file_name(class_name) == expected


def _class_like_names() -> list[str]:
    """The test class names, plus every fixture image's stem read as a class name."""
    names = [
        "Ceramics: Glazing Workshop",
        "Tormach Part 2: CNC Milling",
        "Weaponized Plastic Bots",
        "Ceramics - Make a Tile Relief",
        "Two  spaces",
        "Ver. 2: Intro",
        "Tea & Clay (Ages 12+)",
        "A & B & C",
    ]
    files = CURRENT_IMAGES + [entry["name"] for entry in PR49_IMAGES]
    names += [f.rsplit(".", 1)[0] for f in files]
    names += [f.rsplit(".", 1)[0].replace("__", ": ").replace("_", " ") for f in files]
    return names


@pytest.mark.parametrize("class_name", _class_like_names())
def test_exact_file_name_always_passes_fuzzy(class_name: str) -> None:
    assert fuzzy_key(exact_file_name(class_name)) == fuzzy_key(class_name)


@pytest.mark.parametrize(
    "class_name, shown",
    [
        ("AC/DC Basics", '"/"'),
        ("Back\\slash", '"\\"'),
        ("Bell\x07 Class", '"U+0007"'),
        ("Delete\x7f", '"U+007F"'),
        ("Tab\tName", '"U+0009"'),
    ],
)
def test_file_name_problem_names_the_character(class_name: str, shown: str) -> None:
    problem = file_name_problem(class_name)

    assert problem is not None
    assert f"contains {shown}, which can't be in a file name" in problem
    assert problem.endswith("Rename the class in Neon first.")


@pytest.mark.parametrize("class_name", ["", "   "])
def test_file_name_problem_refuses_an_empty_name(class_name: str) -> None:
    assert file_name_problem(class_name) == "This class has no name in Neon, so it can't have a photo."


@pytest.mark.parametrize(
    "class_name", ["Tea & Clay (Ages 12+)", "Ceramics: Glazing Workshop", "Ver. 2: Intro"]
)
def test_file_name_problem_accepts_usable_names(class_name: str) -> None:
    assert file_name_problem(class_name) is None


# The Neon class names below are assumed: the Neon names aren't in this repository,
# so each is the name the files on asmbly-classes were evidently made for.
@pytest.mark.parametrize(
    "class_name, exact, exact_exists, superseded",
    [
        (
            "Tormach Part 2: CNC Milling",
            "Tormach_Part_2__CNC_Milling.jpg",
            True,
            ["Tormach_Part_2_CNC Milling.jpg", "Tormach_Part_2__CNC Milling.jpg"],
        ),
        ("Ceramics: Glazing Workshop", "Ceramics__Glazing_Workshop.jpg", True, ["Ceramics_Glazing_Workshop.jpg"]),
        ("Forging: Make a Tool", "Forging__Make_a_Tool.jpg", True, ["Forging_Make_a_Tool.jpg"]),
        (
            "Leatherworking: Make a Belt",
            "Leatherworking__Make_a_Belt.jpg",
            True,
            ["Leatherworking_-_Make_A_Belt.jpg"],
        ),
        ("Bambulab P1S: Techniques", "Bambulab_P1S__Techniques.jpg", True, ["Bambulab_P1S___Techniques.jpg"]),
        ("Weaponized Plastic Bots", "Weaponized_Plastic_Bots.jpg", False, ["Weaponized Plastic Bots.jpg"]),
        (
            "Microcontrollers: Make a Robotic Arm",
            "Microcontrollers__Make_a_Robotic_Arm.jpg",
            False,
            ["Microcontrollers_Make_a_Robotic_Arm.jpg"],
        ),
        ("Epoxy Resin: Techniques", "Epoxy_Resin__Techniques.jpg", True, []),
        ("Beginner Handbuilding: Slabs", "Beginner_Handbuilding__Slabs.jpg", True, []),
        ("Beginner Handbuilding: Pinch and Coil", "Beginner_Handbuilding__Pinch_and_Coil.jpg", False, []),
    ],
)
def test_superseded_images_against_current_repository(
    class_name: str, exact: str, exact_exists: bool, superseded: list[str]
) -> None:
    assert exact_file_name(class_name) == exact
    assert (exact in CURRENT_IMAGES) is exact_exists
    removed = superseded_images(class_name, CURRENT_IMAGES, SITE_EXTENSIONS)
    assert removed == superseded
    never_removed = {"GabriellePierce.jpg", "SavannaHarvey.jpg", "CNCMentorPlaceholder.jpg", "NeonLogo.jpg"}
    assert not never_removed.intersection(removed)
    assert not [name for name in removed if name.endswith("Default.jpg")]


def test_pr49_names() -> None:
    names = {entry["name"] for entry in PR49_IMAGES}
    not_exact = {
        "Tormach_Part_2_CNC Milling.jpg": "Tormach Part 2: CNC Milling",
        "Beginner_Hanbuilding__Pinch and Coil.jpg": "Beginner Handbuilding: Pinch and Coil",
        "Beginner_Handbuilding__Slabs(1).jpg": "Beginner Handbuilding: Slabs",
        "Epoxy_Resin__Techniques(1).jpg": "Epoxy Resin: Techniques",
        "Forging_Make_a_Tool.jpg": "Forging: Make a Tool",
        "Microcontollers_Make_a_Robotic_Arm.jpg": "Microcontrollers: Make a Robotic Arm",
    }
    exact = {
        "Ceramics__Glazing_Workshop.jpg": "Ceramics: Glazing Workshop",
        "Forging__Make_a_Railroad_Spike_Knife.jpg": "Forging: Make a Railroad Spike Knife",
        "Leatherworking__Make_a_Set_of_Bracers.jpg": "Leatherworking: Make a Set of Bracers",
        "Woodworking__Make_a_Side_Table.jpg": "Woodworking: Make a Side Table",
    }
    assert names.issuperset(not_exact) and names.issuperset(exact)

    for file_name, class_name in not_exact.items():
        assert exact_file_name(class_name) != file_name, file_name
    for file_name, class_name in exact.items():
        assert exact_file_name(class_name) == file_name, file_name

    with_space = [name for name in names if " " in name]
    assert with_space
    for file_name in with_space:
        class_name = file_name.rsplit(".", 1)[0].replace("_", " ")
        assert exact_file_name(class_name) != file_name
        assert " " not in exact_file_name(class_name)


def test_superseded_images_respects_extensions() -> None:
    images = ["Foo_Bar.png", "Foo_Bar.txt", "Foo_Bar.JPG", "Foo__Bar.jpg", "Foo_Bar", "Other.png"]

    assert superseded_images("Foo: Bar", images, SITE_EXTENSIONS) == ["Foo_Bar.png"]


def test_superseded_images_never_includes_the_exact_file() -> None:
    images = ["Foo__Bar.jpg", "Foo_Bar.webp"]

    assert superseded_images("Foo: Bar", images, ["jpg", "webp"]) == ["Foo_Bar.webp"]


def test_fuzzy_collisions_and_warning() -> None:
    classes = ["A-B Basics", "A B Basics", "Other"]

    others = fuzzy_collisions("A B Basics", classes)

    assert others == ["A-B Basics"]
    warning = collision_warning("A B Basics", others)
    assert warning == (
        'Another class, "A-B Basics", matches the same photo on the class list. '
        "Both classes will show this photo there."
    )
    assert fuzzy_collisions("Other", classes) == []
    assert collision_warning("Other", []) is None


def test_collision_warning_names_every_colliding_class() -> None:
    classes = ["A-B Basics", "A B Basics", "A_B Basics", "AB Basics"]

    others = fuzzy_collisions("A B Basics", classes)

    assert others == ["A-B Basics", "AB Basics", "A_B Basics"]
    warning = collision_warning("A B Basics", others)
    assert warning is not None
    for other in others:
        assert f'"{other}"' in warning


def test_branch_name() -> None:
    prefix = "class-photo/"
    tormach = branch_name("Tormach Part 2: CNC Milling", prefix)

    assert tormach == branch_name("Tormach Part 2: CNC Milling", prefix)
    assert re.fullmatch(r"class-photo/tormach-part-2-cnc-milling-[0-9a-f]{8}", tormach)
    assert branch_name("A-B Basics", prefix) != branch_name("A B Basics", prefix)

    long_name = "Very Long Class Name " * 10
    long_branch = branch_name(long_name[:200], prefix)
    slug = long_branch[len(prefix) : -len("-12345678")]
    assert len(slug) <= 50
    assert not slug.endswith("-")

    for name in ["Tea & Clay (Ages 12+)", "Ceramics: Glazing Workshop", long_name, "Ünïcode Class"]:
        assert re.fullmatch(r"[a-z0-9/-]+", branch_name(name, prefix))


def test_module_logs_nothing_but_fetch_classes(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("DEBUG"):
        superseded_images("Foo: Bar", ["Foo_Bar.png"], ["png"])
        branch_name("Foo: Bar", "class-photo/")
        file_name_problem("AC/DC")
        collision_warning("A", ["B"])
    assert caplog.records == []
