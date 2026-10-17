"""List the routes of FacilitiesApi, as defined in template.yaml.

The deploy workflows run it after a deploy to write each route's full URL to the
run's summary, which the repository's Deployments page links to.

Example:
    python scripts/list_api_routes.py --base-url https://facilities.asmbly.org
"""

import argparse
import pathlib
import re
import sys
from typing import Any, NamedTuple

import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent / "template.yaml"

_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
# The integration URI names its function through a nested stack's output, such as
# ${CeramicsStack.Outputs.KilnDropoffViewerFunctionArn}.
_FUNCTION_OUTPUT = re.compile(r"\$\{(\w+)\.Outputs\.(\w+?)(?:Arn)?\}")


class Route(NamedTuple):
    path: str
    method: str
    stack: str
    function: str


class _CloudFormationLoader(yaml.SafeLoader):
    """A SafeLoader that reads CloudFormation short tags (!Ref, !Sub, !GetAtt, ...)."""


def _construct_short_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    value: Any
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {"Ref" if suffix == "Ref" else f"Fn::{suffix}": value}


_CloudFormationLoader.add_multi_constructor("!", _construct_short_tag)


def _integration_function(operation: dict[str, Any]) -> tuple[str, str]:
    """Returns the (nested stack, function) an operation's integration invokes."""
    uri = operation.get("x-amazon-apigateway-integration", {}).get("uri")
    sub = uri.get("Fn::Sub", "") if isinstance(uri, dict) else ""
    match = _FUNCTION_OUTPUT.search(str(sub))
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def load_routes(template: pathlib.Path = TEMPLATE) -> list[Route]:
    """Returns every path and method of FacilitiesApi, sorted by path."""
    document = yaml.load(template.read_text(), Loader=_CloudFormationLoader)
    paths = document["Resources"]["FacilitiesApi"]["Properties"]["DefinitionBody"]["paths"]
    routes = []
    for path, operations in paths.items():
        for method, operation in operations.items():
            if method in _HTTP_METHODS:
                stack, function = _integration_function(operation)
                routes.append(Route(path, method.upper(), stack, function))
    return sorted(routes, key=lambda route: (route.path.lower(), route.method))


def render_summary(routes: list[Route], base_url: str) -> str:
    """Returns a Markdown table of each route's full URL under base_url."""
    base_url = base_url.rstrip("/")
    lines = [
        "### API routes",
        "",
        f"Base URL: {base_url}",
        "",
        "Most routes take a signed request from Slack, ClickUp, a Google Form, Smartwaiver "
        "or the Dynamic DNS client, so opening them in a browser returns an error.",
        "",
        "| URL | Method | Function |",
        "| --- | --- | --- |",
    ]
    for route in routes:
        url = base_url + route.path
        lines.append(f"| [{url}]({url}) | {route.method} | `{route.function}` ({route.stack}) |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="The API's base URL, such as https://facilities.asmbly.org")
    parser.add_argument("--template", type=pathlib.Path, default=TEMPLATE, help="The SAM template to read")
    args = parser.parse_args(argv)
    sys.stdout.write(render_summary(load_routes(args.template), args.base_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
