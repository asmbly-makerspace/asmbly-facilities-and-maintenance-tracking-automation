"""Checks on the SAM templates that cfn-lint doesn't make."""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES = sorted(
    [ROOT / "template.yaml", ROOT / "template-cicd.yaml", *(ROOT / "templates").glob("*.yaml")]
)

# A name in braces with no "$" in front, such as "{FacilitiesApi}" where
# "${FacilitiesApi}" was meant. CloudFormation leaves it in the string as literal text,
# and cfn-lint accepts it. "${!Name}" (a literal "${Name}") doesn't match. Sub has no
# way to escape a literal "{name}"; if a template ever needs one, build that string
# with !Join instead.
UNSUBSTITUTED = re.compile(r"(?<!\$)\{[A-Za-z][A-Za-z0-9]*(?:(?:\.|::)[A-Za-z0-9]+)*\}")


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda path: path.name)
def test_every_name_in_a_sub_string_has_a_dollar(template: pathlib.Path) -> None:
    # Every Sub string in these templates fits on one line, so checking line by line
    # sees all of them.
    problems = [
        f"{template.name}:{number}: {line.strip()}"
        for number, line in enumerate(template.read_text().splitlines(), start=1)
        if ("!Sub" in line or "Fn::Sub" in line) and UNSUBSTITUTED.search(line)
    ]
    assert problems == []


ROUTER_TEMPLATE = ROOT / "templates" / "routers.yaml"
ROUTER_FUNCTION = "  SlackEventSubscriptionsRouterFunction:"
# A property line of the function, six spaces in: "      MemorySize: 512".
ROUTER_SIZE_PROPERTY = re.compile(r"^\s{6}(MemorySize|Timeout):\s*(\d+)\s*$")


def test_slack_event_router_has_memory_for_its_three_second_deadline() -> None:
    # Slack gives up on an event after 3 seconds. At SAM's default 128 MB a cold start
    # can't fetch the router's config and invoke its target in that time.
    lines = ROUTER_TEMPLATE.read_text().splitlines()
    start = lines.index(ROUTER_FUNCTION)
    end = next(
        (
            number
            for number in range(start + 1, len(lines))
            if re.match(r"^ {0,2}\S", lines[number])
        ),
        len(lines),
    )
    properties = {
        match.group(1): int(match.group(2))
        for line in lines[start + 1:end]
        if (match := ROUTER_SIZE_PROPERTY.match(line))
    }
    assert properties.get("MemorySize", 0) >= 512
    assert properties.get("Timeout") == 3
