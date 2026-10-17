"""Checks that .github/dependabot.yml matches the requirements files in the repository."""

import pathlib
import subprocess
from typing import Any

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".github" / "dependabot.yml"


def _updates(ecosystem: str | None = None) -> list[dict[str, Any]]:
    updates = yaml.safe_load(CONFIG.read_text())["updates"]
    return [update for update in updates if ecosystem in (None, update["package-ecosystem"])]


def _requirements_directories() -> set[str]:
    """Returns each directory, written "/" or "/functions/area/name", with a tracked requirements file.

    Dependabot's pip updater reads every .txt or .in file whose name contains
    "requirements" in each directory it is given.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    return {
        "/" + "/".join(path.parent.parts)
        for path in map(pathlib.PurePosixPath, filter(None, tracked))
        if "requirements" in path.name and path.suffix in (".txt", ".in")
    }


def _pip_directories() -> set[str]:
    return {
        "/" + directory.strip("/")
        for update in _updates("pip")
        for directory in update.get("directories") or [update["directory"]]
    }


def test_every_requirements_file_is_in_a_pip_update() -> None:
    missing = _requirements_directories() - _pip_directories()

    assert missing == set(), "add these directories to the pip update in .github/dependabot.yml"


def test_every_pip_directory_has_a_requirements_file() -> None:
    stale = _pip_directories() - _requirements_directories()

    assert stale == set(), (
        "these pip directories in .github/dependabot.yml hold no requirements file for "
        "Dependabot to update; remove them (a glob isn't expanded here: list each directory)"
    )


def test_every_update_targets_stage() -> None:
    # A Dependabot pull request to main would reach prod without passing through stage.
    branches = {update.get("target-branch") for update in _updates()}

    assert branches == {"stage"}, "every Dependabot update needs target-branch: stage"
