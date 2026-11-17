"""Checks of committed configs/*.json files that more than one function reads."""
import json
import pathlib
import re
from typing import Any

CONFIGS = pathlib.Path(__file__).parents[1] / "configs"

SLACK_CHANNEL_ID = re.compile(r"[CG][A-Z0-9]{8,}")
SLACK_CHANNEL_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")


def _load(name: str) -> dict[str, Any]:
    return json.loads((CONFIGS / name).read_text())


def test_router_config_pm_channels_are_valid() -> None:
    config = _load("router_config.json")
    pm_channels = config["pm_channels"]

    assert isinstance(pm_channels, dict) and pm_channels
    for channel_id, channel_name in pm_channels.items():
        assert SLACK_CHANNEL_ID.fullmatch(channel_id), channel_id
        assert isinstance(channel_name, str) and SLACK_CHANNEL_NAME.fullmatch(channel_name), channel_name
    assert config["purchase_request_channel_id"] not in pm_channels
    assert config["problem_report_channel_id"] not in pm_channels


def test_every_mapped_pm_channel_is_routed() -> None:
    """
    Every channel in workspace_channel_map is a routed PM channel, so remapping a
    workspace can't silently stop its ✅s from completing tasks. Workspaces without a
    mapping post to a channel named after the workspace; those channels can't be checked
    here and are listed by hand in pm_channels.
    """
    routed = set(_load("router_config.json")["pm_channels"].values())
    mapped = _load("clickup_cmms_pmSchedule.json")["workspace_channel_map"].values()

    # The PM bot accepts a mapped channel with a leading '#' or spaces; compare bare names.
    assert {channel.strip().lstrip("#") for channel in mapped} <= routed


def test_pm_schedule_config_names_a_complete_status() -> None:
    complete_status = _load("clickup_cmms_pmSchedule.json")["complete_status"]

    assert isinstance(complete_status, str) and complete_status.strip()
