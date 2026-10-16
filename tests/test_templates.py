"""Checks on the SAM templates that cfn-lint doesn't make."""
import pathlib
import re
from typing import Any, Iterator

import pytest
import yaml

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


# The application's templates. template-cicd.yaml is left out on purpose: it defines
# the deploy role, which has to create and change IAM roles to deploy the stacks.
APP_TEMPLATES = sorted([ROOT / "template.yaml", *(ROOT / "templates").glob("*.yaml")])

# Policies attached by name rather than written out as statements. Anything else in
# ManagedPolicyArns or used as a SAM policy template fails the IAM test, because the
# test can't see what such a policy grants.
ALLOWED_ATTACHED_POLICIES = {
    # ApiGatewayCloudWatchRole in template.yaml: API Gateway's own logging role.
    "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs",
    # The SAM policy template on SlackSlashReorderFunction, scoped to its state table.
    "DynamoDBCrudPolicy",
}

LAMBDA_LOG_ACTIONS = {"logs:createlogstream", "logs:putlogevents"}


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


def _load(template: pathlib.Path) -> dict[str, Any]:
    return yaml.load(template.read_text(), Loader=_CloudFormationLoader)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _get_att(value: Any) -> tuple[str, ...] | None:
    """("Resource", "Attribute") for a GetAtt, in either its "A.B" or [A, B] form."""
    if not isinstance(value, dict) or set(value) != {"Fn::GetAtt"}:
        return None
    target = value["Fn::GetAtt"]
    return tuple(target.split(".", 1)) if isinstance(target, str) else tuple(target)


def _policy_statements(template: pathlib.Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """(resource name, statement) for every permission statement the template writes out."""
    for name, resource in _load(template).get("Resources", {}).items():
        kind = resource.get("Type")
        properties = resource.get("Properties", {})
        documents: list[Any] = []
        if kind == "AWS::IAM::Role":
            documents = [policy.get("PolicyDocument", {}) for policy in properties.get("Policies", [])]
        elif kind in ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy", "AWS::IAM::RolePolicy"):
            documents = [properties.get("PolicyDocument", {})]
        elif kind == "AWS::Serverless::Function":
            documents = [
                policy
                for policy in _as_list(properties.get("Policies"))
                if isinstance(policy, dict) and "Statement" in policy
            ]
        for document in documents:
            for statement in _as_list(document.get("Statement")):
                yield name, statement


def _attached_policies(template: pathlib.Path) -> Iterator[tuple[str, str]]:
    """(resource name, policy) for every policy attached by ARN or by SAM template name."""
    for name, resource in _load(template).get("Resources", {}).items():
        properties = resource.get("Properties", {})
        for arn in _as_list(properties.get("ManagedPolicyArns")):
            yield name, str(arn)
        if resource.get("Type") == "AWS::Serverless::Function":
            for policy in _as_list(properties.get("Policies")):
                if isinstance(policy, str):
                    yield name, policy
                elif isinstance(policy, dict) and "Statement" not in policy:
                    yield from ((name, key) for key in policy)


def _actions(statement: dict[str, Any]) -> list[str]:
    return [str(action).lower() for action in _as_list(statement.get("Action"))]


@pytest.mark.parametrize("template", APP_TEMPLATES, ids=lambda path: path.name)
def test_no_application_role_can_change_iam(template: pathlib.Path) -> None:
    # No function calls IAM. A grant such as iam:CreateRole on role/* lets whoever
    # controls the function create roles, a step toward taking over the account.
    statements = list(_policy_statements(template))
    problems = [
        f"{template.name}: {name} grants {action}"
        for name, statement in statements
        for action in _actions(statement)
        if action == "*" or action.startswith("iam:")
    ]
    problems += [
        f"{template.name}: {name} uses {key}"
        for name, statement in statements
        for key in ("NotAction", "NotResource")
        if key in statement
    ]
    problems += [
        f"{template.name}: {name} attaches {policy}, which this test can't inspect"
        for name, policy in _attached_policies(template)
        if policy not in ALLOWED_ATTACHED_POLICIES
    ]
    assert problems == []


@pytest.mark.parametrize("template", APP_TEMPLATES, ids=lambda path: path.name)
def test_no_application_role_writes_logs_by_wildcard(template: pathlib.Path) -> None:
    # The only logs resource allowed is "!GetAtt <LogGroup>.Arn" for a log group in the
    # same template. Any string or Sub, such as "arn:aws:logs:*:*:*" or
    # "...:log-group:*", can name more than one log group, so it fails.
    resources = _load(template).get("Resources", {})
    log_groups = {name for name, resource in resources.items() if resource.get("Type") == "AWS::Logs::LogGroup"}
    problems = [
        f"{template.name}: {name} grants logs on {resource}"
        for name, statement in _policy_statements(template)
        if any(action.startswith("logs:") for action in _actions(statement))
        for resource in _as_list(statement.get("Resource"))
        if not ((target := _get_att(resource)) and len(target) == 2 and target[0] in log_groups and target[1] == "Arn")
    ]
    assert problems == []


def _is_lambda_role(resource: dict[str, Any]) -> bool:
    document = resource.get("Properties", {}).get("AssumeRolePolicyDocument", {})
    return any(
        "lambda.amazonaws.com" in _as_list(statement.get("Principal", {}).get("Service"))
        for statement in _as_list(document.get("Statement"))
    )


@pytest.mark.parametrize("template", APP_TEMPLATES, ids=lambda path: path.name)
def test_each_lambda_role_writes_only_to_its_functions_log_group(template: pathlib.Path) -> None:
    # Each hand-written Lambda role serves one function, which logs to the log group
    # CloudFormation creates for it. The role needs to write streams there and nowhere
    # else; it must not create log groups or write to another function's.
    resources = _load(template).get("Resources", {})
    statements = list(_policy_statements(template))
    roles = [
        name
        for name, resource in resources.items()
        if resource.get("Type") == "AWS::IAM::Role" and _is_lambda_role(resource)
    ]
    problems = []
    for role in roles:
        functions = [
            resource
            for resource in resources.values()
            if resource.get("Type") == "AWS::Serverless::Function"
            and _get_att(resource.get("Properties", {}).get("Role")) == (role, "Arn")
        ]
        if len(functions) != 1:
            problems.append(f"{role} is used by {len(functions)} functions, expected 1")
            continue
        log_group = functions[0]["Properties"].get("LoggingConfig", {}).get("LogGroup")
        if not (isinstance(log_group, dict) and set(log_group) == {"Ref"}):
            problems.append(f"{role}'s function has no LoggingConfig LogGroup: !Ref <LogGroup>")
            continue
        log_statements = [
            statement
            for name, statement in statements
            if name == role and any(action.startswith("logs:") for action in _actions(statement))
        ]
        if len(log_statements) != 1:
            problems.append(f"{role} has {len(log_statements)} logs statements, expected 1")
            continue
        statement = log_statements[0]
        if set(_actions(statement)) != LAMBDA_LOG_ACTIONS:
            problems.append(f"{role} grants {sorted(_actions(statement))}")
        targets = [_get_att(resource) for resource in _as_list(statement.get("Resource"))]
        if targets != [(log_group["Ref"], "Arn")]:
            problems.append(f"{role} writes logs to {statement.get('Resource')}, not {log_group['Ref']}")
    assert problems == []


@pytest.mark.parametrize("template", APP_TEMPLATES, ids=lambda path: path.name)
def test_secret_arns_end_with_hyphen_star(template: pathlib.Path) -> None:
    # Secrets Manager appends "-" and six random characters to a secret's ARN.
    # "name-*" matches that secret only; "name*" also matches "name2", "name-old", ...
    problems = []
    for name, statement in _policy_statements(template):
        if not any(action.startswith("secretsmanager:") for action in _actions(statement)):
            continue
        for resource in _as_list(statement.get("Resource")):
            if isinstance(resource, dict) and set(resource) == {"Fn::Sub"}:
                resource = resource["Fn::Sub"]
            if not isinstance(resource, str):
                problems.append(f"{template.name}: {name} has a secret resource this test can't read: {resource}")
            elif not resource.endswith("-*"):
                problems.append(f"{template.name}: {name} grants {resource}")
    assert problems == []
