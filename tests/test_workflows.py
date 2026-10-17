"""Checks on the GitHub Actions workflows in .github/workflows/.

Every action must run on Node.js 24, which GitHub moved its runners to when it deprecated
Node.js 20, and each deploy job must keep the OIDC sign-in the deploy role in
template-cicd.yaml trusts. Actions are pinned by major tag (`@v7`). Pinning them by
commit SHA instead would mean changing `_major` below.
"""
import pathlib
import re
from typing import Any

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])

# The first major of each action that runs on Node.js 24. A minimum, not an exact
# version, so a later bump (by Dependabot or by hand) still passes.
MIN_NODE24_MAJOR: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "aws-actions/configure-aws-credentials": 6,
    "aws-actions/setup-sam": 3,
}

# `@v7`, `@v7.0`, `@v7.0.1`.
MAJOR_TAG = re.compile(r"^v(\d+)(?:\.\d+)*$")

DEPLOY_ROLE_SUFFIX = ":role/GitHub-OIDC-facilities-automation-deploy"


def _load(workflow: pathlib.Path) -> dict[str, Any]:
    return yaml.safe_load(workflow.read_text())


def _major(ref: str) -> int | None:
    match = MAJOR_TAG.match(ref)
    return int(match.group(1)) if match else None


def _uses_problems(workflow: pathlib.Path) -> list[str]:
    """Returns one message for each `uses:` in the workflow that isn't on Node 24."""
    problems = []
    for job_id, job in _load(workflow)["jobs"].items():
        if "uses" in job:
            problems.append(f"{workflow.name} job {job_id}: reusable workflow {job['uses']} isn't checked")
        for step in job.get("steps", []):
            uses = step.get("uses")
            if uses is None:
                continue
            where = f"{workflow.name} job {job_id}: {uses}"
            action, _, ref = uses.partition("@")
            if action not in MIN_NODE24_MAJOR:
                problems.append(
                    f"{where}: unknown action; check which Node.js version it runs on and add it to MIN_NODE24_MAJOR"
                )
                continue
            major = _major(ref)
            if major is None:
                problems.append(f"{where}: pin it by major tag, such as @v{MIN_NODE24_MAJOR[action]}")
            elif major < MIN_NODE24_MAJOR[action]:
                problems.append(f"{where}: targets Node.js 20 or older; use @v{MIN_NODE24_MAJOR[action]} or later")
    return problems


def test_workflows_are_found() -> None:
    assert {"python-tests.yml", "deploy-staging.yml", "deploy.yml"} <= {path.name for path in WORKFLOWS}


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_runs_on_node_24(workflow: pathlib.Path) -> None:
    problems = _uses_problems(workflow)
    assert not problems, "\n".join(problems)


def test_the_check_reports_each_kind_of_problem(tmp_path: pathlib.Path) -> None:
    workflow = tmp_path / "example.yml"
    workflow.write_text(
        """
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v6.1.0
      - uses: aws-actions/setup-sam@0123456789abcdef0123456789abcdef01234567
      - uses: someone/new-action@v1
      - run: echo no action here
  shared:
    uses: someone/repo/.github/workflows/shared.yml@main
"""
    )

    assert _uses_problems(workflow) == [
        "example.yml job build: actions/checkout@v4: targets Node.js 20 or older; use @v5 or later",
        "example.yml job build: aws-actions/setup-sam@0123456789abcdef0123456789abcdef01234567: "
        "pin it by major tag, such as @v3",
        "example.yml job build: someone/new-action@v1: unknown action; "
        "check which Node.js version it runs on and add it to MIN_NODE24_MAJOR",
        "example.yml job shared: reusable workflow someone/repo/.github/workflows/shared.yml@main isn't checked",
    ]


@pytest.mark.parametrize(("file_name", "stage"), [("deploy-staging.yml", "stage"), ("deploy.yml", "prod")])
def test_deploy_jobs_keep_their_oidc_sign_in(file_name: str, stage: str) -> None:
    # The deploy role trusts tokens whose subject is `environment:stage` or
    # `environment:prod`, so the environment name and the token permission are the
    # sign-in. Any new credentials input should be a deliberate change.
    job = _load(WORKFLOW_DIR / file_name)["jobs"]["deploy"]

    assert job["environment"]["name"] == stage
    assert job["permissions"] == {"id-token": "write", "contents": "read"}
    credentials = [
        step for step in job["steps"] if step.get("uses", "").startswith("aws-actions/configure-aws-credentials@")
    ]
    assert len(credentials) == 1
    assert set(credentials[0]["with"]) == {"role-to-assume", "aws-region"}
    assert credentials[0]["with"]["role-to-assume"].endswith(DEPLOY_ROLE_SUFFIX)


@pytest.mark.parametrize("file_name", ["deploy-staging.yml", "deploy.yml"])
def test_list_routes_jobs_have_no_oidc_token(file_name: str) -> None:
    # The route list installs a package from PyPI, so it runs without the deploy job's
    # AWS credentials or its permission to request a token.
    job = _load(WORKFLOW_DIR / file_name)["jobs"]["list-routes"]

    assert job["permissions"] == {"contents": "read"}
    assert "environment" not in job
