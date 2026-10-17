"""The page's script, run by node in page_script_harness.mjs (plan class-photo-loading, Decision 12).

Each scenario runs page.html's own <script> against a fake DOM, a fake clock and scripted
server answers. Without node the tests are skipped on a developer's machine and fail in
CI (GitHub sets CI=true), so CI can't pass by skipping them.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from functions.classes.class_photo_upload_api.tests.jpeg_builder import make_jpeg

HARNESS = Path(__file__).parent / "page_script_harness.mjs"
SCENARIOS = [
    "classes_busy_while_loading",
    "classes_still_loading_after_5s",
    "classes_failure_shows_try_again",
    "classes_no_answer_shows_try_again",
    "classes_try_again_reloads_in_place",
    "classes_loaded_shows_time",
    "classes_stale_list_says_out_of_date",
    "submit_disables_controls_and_shows_steps",
    "submit_dry_run_waiting_step",
    "submit_double_click_sends_once",
    "submit_failure_keeps_class_and_photo",
    "submit_gateway_timeout_is_unconfirmed",
    "submit_network_error_is_unconfirmed",
    "submit_timeout_on_dry_run_says_nothing_opened",
    "submit_failure_before_sending_is_network_error",
    "submit_slow_upload_keeps_waiting",
    "submit_server_says_nothing_changed",
    "submit_success_shows_result",
    "classes_401_signs_in_again",
    "submit_401_signs_in_again",
    "classes_refresh_button_shown_after_load",
    "classes_refresh_reloads_from_neon",
    "classes_refresh_too_soon_says_so",
    "classes_refresh_failed_keeps_list",
    "classes_refresh_keeps_chosen_class",
    "submit_disables_refresh",
]
TIMEOUT_SECONDS = 60


@pytest.fixture(scope="module")
def node() -> str:
    path = shutil.which("node")
    if path is None:
        if os.environ.get("CI"):
            pytest.fail("node is required in CI for the page script tests")
        pytest.skip("node is not installed")
    return path


@pytest.fixture(scope="module")
def photo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("page_script") / "photo.jpg"
    path.write_bytes(make_jpeg(1500, 1000))
    return path


def _run(node: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [node, str(HARNESS), *arguments], capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False
    )


def test_harness_lists_exactly_these_scenarios(node: str) -> None:
    result = _run(node, "--list")

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_page_script_scenario(node: str, photo: Path, scenario: str) -> None:
    result = _run(node, scenario, str(photo))

    assert result.returncode == 0, f"{scenario} failed:\n{result.stdout}\n{result.stderr}"
