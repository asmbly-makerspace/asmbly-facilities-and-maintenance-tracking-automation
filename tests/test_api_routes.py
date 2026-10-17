"""Tests for scripts/list_api_routes.py, and the route table in docs/README.md."""

import pathlib
import re

import pytest

from scripts.list_api_routes import Route, load_routes, main, render_summary

REPO = pathlib.Path(__file__).resolve().parent.parent
README = REPO / "docs" / "README.md"

_README_ROW = re.compile(r"^\| `https://facilities\.asmbly\.org(/[^`]*)` \| (\w+) \|")


def _readme_routes() -> set[tuple[str, str]]:
    """Returns the (path, method) rows of the README's API Routes table."""
    section = README.read_text().split("\n## API Routes\n", 1)[1].split("\n## ", 1)[0]
    return {(match.group(1), match.group(2)) for line in section.splitlines() if (match := _README_ROW.match(line))}


def test_load_routes_reads_every_path_and_method_with_its_function() -> None:
    routes = load_routes()

    assert Route("/slack/events", "POST", "RoutersStack", "SlackEventSubscriptionsRouterFunction") in routes
    assert Route("/nic/update", "GET", "NetworkingStack", "DynamicDnsUpdateFunction") in routes
    assert all(route.stack and route.function for route in routes), "a route's function wasn't found"
    assert routes == sorted(routes, key=lambda route: (route.path.lower(), route.method))


def test_load_routes_ignores_keys_that_are_not_methods(tmp_path: pathlib.Path) -> None:
    template = tmp_path / "template.yaml"
    template.write_text(
        """
Resources:
  FacilitiesApi:
    Properties:
      DefinitionBody:
        paths:
          /b:
            parameters: []
            post:
              x-amazon-apigateway-integration:
                uri:
                  Fn::Sub: "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${BStack.Outputs.BFunctionArn}/invocations"
          /a:
            get:
              x-amazon-apigateway-integration:
                uri: !Sub "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${AStack.Outputs.AFunctionArn}/invocations"
"""
    )

    assert load_routes(template) == [Route("/a", "GET", "AStack", "AFunction"), Route("/b", "POST", "BStack", "BFunction")]


def test_render_summary_joins_the_base_url_without_a_double_slash() -> None:
    summary = render_summary([Route("/waiver/new", "POST", "AdministrativeStack", "NewWaiverCompletedFunction")], "https://example.test/stage/")

    assert "Base URL: https://example.test/stage\n" in summary
    assert (
        "| [https://example.test/stage/waiver/new](https://example.test/stage/waiver/new) | POST "
        "| `NewWaiverCompletedFunction` (AdministrativeStack) |"
    ) in summary


def test_main_writes_a_row_for_every_route(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--base-url", "https://facilities.asmbly.org"]) == 0

    output = capsys.readouterr().out
    assert output.count("\n| [https://facilities.asmbly.org/") == len(load_routes())


def test_readme_route_table_lists_exactly_the_template_routes() -> None:
    in_template = {(route.path, route.method) for route in load_routes()}
    in_readme = _readme_routes()

    assert in_template - in_readme == set(), "add these routes to docs/README.md, API Routes"
    assert in_readme - in_template == set(), "remove these routes from docs/README.md, API Routes"
