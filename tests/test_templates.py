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
