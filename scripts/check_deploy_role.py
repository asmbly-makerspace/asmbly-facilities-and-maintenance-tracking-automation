"""
Dry run for the GitHub OIDC deploy role in template-cicd.yaml.

Checks the role's trust policy and permissions without deploying anything:

* Trust: every deploy workflow's OIDC subject is trusted, and nothing else.
* Permissions: every call a stage or prod deploy makes is allowed, and a set
  of calls against other projects' resources is denied.

Offline mode (no AWS credentials) predicts resource names from the templates
and evaluates the policies locally. Online mode (the default) uses read-only
AWS calls: it lists the real stack resources, evaluates the policies with the
IAM policy simulator, validates them with IAM Access Analyzer, and compares
them with the actions the role has actually used (IAM last accessed).

Usage:
    python scripts/check_deploy_role.py --offline
    python scripts/check_deploy_role.py            # needs read-only admin creds

Requires PyYAML, plus boto3 for online mode.
"""
import argparse
import copy
import fnmatch
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

logger = logging.getLogger("check_deploy_role")

ROOT = Path(__file__).resolve().parent.parent
REGION = "us-east-2"
ACCOUNT_ID = "110104886034"
STACK_PREFIX = "AsmblyFacilitiesMaintTrackingStack"
DEPLOY_ROLE_NAME = "GitHub-OIDC-facilities-automation-deploy"
CI_STAGES = ["stage", "prod"]
OIDC_SUB_KEY = "token.actions.githubusercontent.com:sub"
PLACEHOLDER_API_IDS = {"stage": "stageapi00", "prod": "prodapi000"}
PLACEHOLDER_ZONE_ID = "Z0000000000000EXAMPLE"


# --------------------------------------------------------------------------
# Template loading and rendering
# --------------------------------------------------------------------------
class CfnLoader(yaml.SafeLoader):
    """YAML loader that keeps CloudFormation short-form tags as Fn:: maps."""


def _construct_tag(loader: CfnLoader, suffix: str, node: yaml.Node) -> Dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if suffix == "Ref":
        return {"Ref": value}
    if suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {f"Fn::{suffix}": value}


CfnLoader.add_multi_constructor("!", _construct_tag)


def load_template(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=CfnLoader)


def _replace_identifier(obj: Any, ident: str, value: str) -> Any:
    """Replaces ${ident} and &{ident} the way Fn::ForEach does."""
    if isinstance(obj, str):
        return obj.replace("${%s}" % ident, value).replace("&{%s}" % ident, value)
    if isinstance(obj, list):
        return [_replace_identifier(item, ident, value) for item in obj]
    if isinstance(obj, dict):
        if obj == {"Ref": ident}:
            return value
        return {
            _replace_identifier(k, ident, value): _replace_identifier(v, ident, value)
            for k, v in obj.items()
        }
    return obj


def expand_foreach(resources: Dict[str, Any]) -> Dict[str, Any]:
    expanded: Dict[str, Any] = {}
    for key, value in resources.items():
        if not key.startswith("Fn::ForEach::"):
            expanded[key] = value
            continue
        ident, collection, fragment = value
        for item in collection:
            for frag_key, frag_value in fragment.items():
                new_key = _replace_identifier(frag_key, ident, item)
                expanded[new_key] = _replace_identifier(copy.deepcopy(frag_value), ident, item)
    return expanded


def resolve(obj: Any, params: Dict[str, Any], refs: Dict[str, str]) -> Any:
    """Resolves Ref and Fn::Sub against parameters and logical-ID placeholders."""
    if isinstance(obj, list):
        return [resolve(item, params, refs) for item in obj]
    if not isinstance(obj, dict):
        return obj
    if set(obj) == {"Ref"}:
        name = obj["Ref"]
        if name in params:
            return params[name]
        return refs.get(name, "<ref:%s>" % name)
    if set(obj) == {"Fn::Sub"}:
        template = obj["Fn::Sub"]
        local: Dict[str, Any] = {}
        if isinstance(template, list):
            template, local = template[0], resolve(template[1], params, refs)

        def _sub(match: "re.Match[str]") -> str:
            name = match.group(1)
            if name in local:
                return str(local[name])
            if name in params:
                return str(params[name])
            return refs.get(name, match.group(0))

        return re.sub(r"\$\{([^}!]+)\}", _sub, template)
    return {k: resolve(v, params, refs) for k, v in obj.items()}


def pseudo_params() -> Dict[str, str]:
    return {"AWS::Region": REGION, "AWS::AccountId": ACCOUNT_ID, "AWS::Partition": "aws"}


def render_cicd(overrides: Dict[str, str]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Returns (identity policy documents, trust policy, parameter values)."""
    template = load_template(ROOT / "template-cicd.yaml")
    params: Dict[str, Any] = pseudo_params()
    for name, spec in template.get("Parameters", {}).items():
        if "Default" in spec:
            params[name] = spec["Default"]
    params.update(overrides)
    resources = expand_foreach(template["Resources"])
    role = next(r for r in resources.values() if r["Type"] == "AWS::IAM::Role")
    trust = resolve(role["Properties"]["AssumeRolePolicyDocument"], params, {})
    policies = []
    for ref in role["Properties"]["ManagedPolicyArns"]:
        logical_id = ref["Ref"] if isinstance(ref, dict) else ref
        if logical_id not in resources:
            raise ValueError("Role references unknown policy %s" % logical_id)
        doc = resolve(resources[logical_id]["Properties"]["PolicyDocument"], params, {})
        policies.append({"name": logical_id, "document": doc})
    return policies, trust, params


# --------------------------------------------------------------------------
# Resource inventory: what a deploy touches
# --------------------------------------------------------------------------
NAME_PROPERTIES = {
    "AWS::Serverless::Function": "FunctionName",
    "AWS::Lambda::Function": "FunctionName",
    "AWS::Logs::LogGroup": "LogGroupName",
    "AWS::SSM::Parameter": "Name",
    "AWS::DynamoDB::Table": "TableName",
    "AWS::Events::Rule": "Name",
    "AWS::Serverless::LayerVersion": "LayerName",
    "AWS::CertificateManager::Certificate": "DomainName",
    "AWS::ApiGatewayV2::DomainName": "DomainName",
    "AWS::Route53::RecordSet": "Name",
}


@dataclass
class Item:
    """One resource a deploy creates or updates."""

    stage: str
    stack: str
    logical_id: str
    type: str
    name: str
    props: Dict[str, Any] = field(default_factory=dict)


def _condition_holds(template: Dict[str, Any], condition: Optional[str], stage: str) -> bool:
    if not condition:
        return True
    expr = template.get("Conditions", {}).get(condition, {})
    equals = expr.get("Fn::Equals")
    if equals and isinstance(equals, list):
        values = [stage if v == {"Ref": "Stage"} else v for v in equals]
        return values[0] == values[1]
    return True


def predicted_inventory(stage: str, role_prefix: str, api_id: str) -> List[Item]:
    """Predicts physical names from the templates (offline mode)."""
    params = dict(pseudo_params(), Stage=stage)
    root_stack = "%s-%s" % (STACK_PREFIX, stage)
    items: List[Item] = []
    root = load_template(ROOT / "template.yaml")
    templates: List[Tuple[str, Dict[str, Any]]] = [(root_stack, root)]
    for logical_id, res in root["Resources"].items():
        if res["Type"] != "AWS::Serverless::Application":
            continue
        nested_name = "%s-%s-EXAMPLE123456" % (root_stack, logical_id)
        items.append(Item(stage, root_stack, logical_id, res["Type"], nested_name))
        location = res["Properties"]["Location"]
        templates.append((nested_name, load_template((ROOT / location).resolve())))

    for stack_name, template in templates:
        for logical_id, res in template.get("Resources", {}).items():
            if not isinstance(res, dict) or "Type" not in res:
                continue
            if not _condition_holds(template, res.get("Condition"), stage):
                continue
            rtype, props = res["Type"], res.get("Properties", {}) or {}
            if rtype == "AWS::Serverless::Application":
                continue
            name = ""
            if rtype in NAME_PROPERTIES and NAME_PROPERTIES[rtype] in props:
                name = str(resolve(props[NAME_PROPERTIES[rtype]], params, {}))
            elif rtype == "AWS::IAM::Role":
                name = "%s-%s-EXAMPLE1234" % (role_prefix, logical_id[:16])
            elif rtype == "AWS::Serverless::Api":
                name = api_id
            items.append(Item(stage, stack_name, logical_id, rtype, name, props))
            if rtype == "AWS::Serverless::Function" and "Role" not in props:
                role_name = "%s-%sRole-EXAMPLE1234" % (role_prefix, logical_id[:12])
                implicit = {"ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"]}
                items.append(Item(stage, stack_name, logical_id + "Role", "AWS::IAM::Role",
                                  role_name, implicit))
    return items


def live_inventory(session: Any, stage: str) -> Tuple[List[Item], Optional[str]]:
    """Lists the real resources of a deployed stack and its nested stacks."""
    cfn = session.client("cloudformation", region_name=REGION)
    root_stack = "%s-%s" % (STACK_PREFIX, stage)
    items: List[Item] = []
    api_id: Optional[str] = None
    pending = [root_stack]
    while pending:
        stack = pending.pop()
        try:
            paginator = cfn.get_paginator("list_stack_resources")
            for page in paginator.paginate(StackName=stack):
                for res in page["StackResourceSummaries"]:
                    rtype = res["ResourceType"]
                    physical = res.get("PhysicalResourceId", "")
                    if rtype == "AWS::CloudFormation::Stack":
                        pending.append(physical)
                        physical = physical.split("/")[1] if "/" in physical else physical
                    if rtype == "AWS::ApiGateway::RestApi" and stack == root_stack:
                        api_id = physical
                    items.append(Item(stage, stack, res["LogicalResourceId"], rtype, physical))
        except Exception:  # pylint: disable=broad-except
            logger.exception("Could not list resources of stack %s", stack)
            raise
    return items, api_id


# --------------------------------------------------------------------------
# Expected calls
# --------------------------------------------------------------------------
@dataclass
class Check:
    """A set of actions on one resource, expected to be allowed or denied."""

    label: str
    actions: List[str]
    resource: str
    expect_allowed: bool
    context: Dict[str, Any] = field(default_factory=dict)


def arn(service: str, resource: str, region: str = REGION, account: str = ACCOUNT_ID) -> str:
    return "arn:aws:%s:%s:%s:%s" % (service, region, account, resource)


def _log_group_arns(name: str) -> List[str]:
    return [arn("logs", "log-group:%s" % name), arn("logs", "log-group:%s:*" % name)]


def checks_for_item(item: Item, params: Dict[str, Any]) -> List[Check]:
    """Maps a resource to the API calls CloudFormation makes for it."""
    label = "%s %s (%s)" % (item.stage, item.logical_id, item.type)
    t, n = item.type, item.name
    out: List[Check] = []
    if t in ("AWS::Serverless::Function", "AWS::Lambda::Function"):
        actions = ["lambda:CreateFunction", "lambda:UpdateFunctionCode",
                   "lambda:UpdateFunctionConfiguration", "lambda:GetFunction",
                   "lambda:DeleteFunction", "lambda:TagResource", "lambda:AddPermission",
                   "lambda:RemovePermission"]
        if "ReservedConcurrentExecutions" in item.props or not item.props:
            actions += ["lambda:PutFunctionConcurrency", "lambda:DeleteFunctionConcurrency"]
        out.append(Check(label, actions, arn("lambda", "function:%s" % n), True))
    elif t == "AWS::Logs::LogGroup":
        for resource in _log_group_arns(n):
            out.append(Check(label, ["logs:CreateLogGroup", "logs:PutRetentionPolicy",
                                     "logs:DeleteLogGroup", "logs:TagLogGroup"], resource, True))
    elif t == "AWS::SSM::Parameter":
        out.append(Check(label, ["ssm:PutParameter", "ssm:AddTagsToResource",
                                 "ssm:GetParameters", "ssm:DeleteParameter"],
                         arn("ssm", "parameter/%s" % n.lstrip("/")), True))
    elif t == "AWS::DynamoDB::Table":
        out.append(Check(label, ["dynamodb:CreateTable", "dynamodb:DescribeTable",
                                 "dynamodb:UpdateTable", "dynamodb:UpdateTimeToLive",
                                 "dynamodb:DescribeTimeToLive", "dynamodb:TagResource",
                                 "dynamodb:DeleteTable"],
                         arn("dynamodb", "table/%s" % n), True))
    elif t == "AWS::Events::Rule":
        out.append(Check(label, ["events:PutRule", "events:DescribeRule", "events:PutTargets",
                                 "events:RemoveTargets", "events:DeleteRule"],
                         arn("events", "rule/%s" % n), True))
    elif t in ("AWS::Serverless::LayerVersion", "AWS::Lambda::LayerVersion"):
        layer = n.split(":layer:")[-1].split(":")[0] if n.startswith("arn:") else n
        out.append(Check(label, ["lambda:PublishLayerVersion"],
                         arn("lambda", "layer:%s" % layer), True))
        out.append(Check(label, ["lambda:GetLayerVersion", "lambda:DeleteLayerVersion"],
                         arn("lambda", "layer:%s:1" % layer), True))
    elif t == "AWS::IAM::Role":
        role_arn = "arn:aws:iam::%s:role/%s" % (ACCOUNT_ID, n)
        out.append(Check(label, ["iam:CreateRole", "iam:GetRole", "iam:TagRole",
                                 "iam:PutRolePolicy", "iam:DeleteRolePolicy",
                                 "iam:DetachRolePolicy", "iam:DeleteRole"], role_arn, True))
        for policy_arn in item.props.get("ManagedPolicyArns", []):
            out.append(Check(label, ["iam:AttachRolePolicy"], role_arn, True,
                             {"iam:PolicyARN": policy_arn}))
        service = "apigateway.amazonaws.com" if "ApiGateway" in item.logical_id else "lambda.amazonaws.com"
        out.append(Check(label, ["iam:PassRole"], role_arn, True,
                         {"iam:PassedToService": service}))
    elif t in ("AWS::Serverless::Application", "AWS::CloudFormation::Stack"):
        out.append(Check(label, ["cloudformation:CreateStack", "cloudformation:UpdateStack",
                                 "cloudformation:DescribeStacks", "cloudformation:DeleteStack",
                                 "cloudformation:DescribeStackEvents"],
                         arn("cloudformation", "stack/%s/00000000-example" % n), True))
    elif t in ("AWS::Serverless::Api", "AWS::ApiGateway::RestApi"):
        verbs = ["apigateway:GET", "apigateway:PUT", "apigateway:PATCH",
                 "apigateway:POST", "apigateway:DELETE"]
        for path in ("/restapis/%s" % n, "/restapis/%s/deployments" % n,
                     "/restapis/%s/deployments/abc123" % n,
                     "/restapis/%s/stages/%s" % (n, item.stage)):
            out.append(Check(label, verbs, "arn:aws:apigateway:%s::%s" % (REGION, path), True))
    elif t == "AWS::ApiGateway::Account":
        out.append(Check(label, ["apigateway:GET", "apigateway:PATCH"],
                         "arn:aws:apigateway:%s::/account" % REGION, True))
    elif t == "AWS::CertificateManager::Certificate":
        domain = params["FacilitiesDomainName"]
        cert = arn("acm", "certificate/00000000-example")
        out.append(Check(label, ["acm:DescribeCertificate"], cert, True))
        out.append(Check(label, ["acm:RequestCertificate"], "*", True,
                         {"acm:DomainNames": [domain]}))
        out.append(Check(label, ["acm:DeleteCertificate", "acm:AddTagsToCertificate"], cert, True,
                         {"aws:ResourceTag/Application": "facilities-automation-hub"}))
        out.append(Check(label + " validation record", ["route53:ChangeResourceRecordSets"],
                         "arn:aws:route53:::hostedzone/%s" % params["AsmblyHostedZoneId"], True,
                         {"route53:ChangeResourceRecordSetsNormalizedRecordNames":
                          ["_0123456789abcdef.%s" % domain],
                          "route53:ChangeResourceRecordSetsRecordTypes": ["CNAME"]}))
    elif t == "AWS::ApiGatewayV2::DomainName":
        domain = params["FacilitiesDomainName"]
        out.append(Check(label, ["apigateway:GET", "apigateway:PATCH", "apigateway:POST",
                                 "apigateway:DELETE"],
                         "arn:aws:apigateway:%s::/domainnames/%s" % (REGION, domain), True))
    elif t == "AWS::ApiGatewayV2::ApiMapping":
        domain = params["FacilitiesDomainName"]
        out.append(Check(label, ["apigateway:GET", "apigateway:PATCH", "apigateway:POST",
                                 "apigateway:DELETE"],
                         "arn:aws:apigateway:%s::/domainnames/%s/apimappings/abc123" % (REGION, domain),
                         True))
    elif t == "AWS::Route53::RecordSet":
        zone = "arn:aws:route53:::hostedzone/%s" % params["AsmblyHostedZoneId"]
        record = params["FacilitiesDomainName"]
        out.append(Check(label, ["route53:ChangeResourceRecordSets"], zone, True,
                         {"route53:ChangeResourceRecordSetsNormalizedRecordNames": [record],
                          "route53:ChangeResourceRecordSetsRecordTypes": ["A"]}))
        out.append(Check(label, ["route53:GetHostedZone"], zone, True))
        out.append(Check(label, ["route53:GetChange"], "arn:aws:route53:::change/C0EXAMPLE", True))
    return out


def sam_cli_checks(stage: str, params: Dict[str, Any]) -> List[Check]:
    """Calls made by `sam deploy` and the workflow itself, outside the templates."""
    root = "%s-%s" % (STACK_PREFIX, stage)
    bucket = params["SamArtifactBucket"]
    label = "%s sam deploy" % stage
    return [
        Check(label, ["cloudformation:DescribeStacks"],
              arn("cloudformation", "stack/aws-sam-cli-managed-default/00000000-example"), True),
        Check(label, ["cloudformation:DescribeStacks", "cloudformation:CreateChangeSet",
                      "cloudformation:DescribeChangeSet", "cloudformation:ExecuteChangeSet",
                      "cloudformation:DeleteChangeSet", "cloudformation:DescribeStackEvents"],
              arn("cloudformation", "stack/%s/00000000-example" % root), True),
        Check(label, ["cloudformation:CreateChangeSet"],
              "arn:aws:cloudformation:%s:aws:transform/Serverless-2016-10-31" % REGION, True),
        Check(label, ["cloudformation:CreateChangeSet"],
              "arn:aws:cloudformation:%s:aws:transform/LanguageExtensions" % REGION, True),
        Check(label, ["cloudformation:CreateChangeSet"],
              "arn:aws:cloudformation:%s:aws:transform/Include" % REGION, True),
        Check(label, ["s3:PutObject", "s3:GetObject"],
              "arn:aws:s3:::%s/%s/0123456789abcdef.template" % (bucket, root), True),
        Check(label, ["s3:ListBucket", "s3:GetBucketLocation"], "arn:aws:s3:::%s" % bucket, True),
        Check(label, ["ssm:GetParameters"],
              arn("ssm", "parameter/config/route53/asmbly/hosted-zone-id"), True),
        Check(label, ["logs:DescribeLogGroups"], "*", True),
    ]


def negative_checks(params: Dict[str, Any]) -> List[Check]:
    """Calls against other projects' resources, which must be denied."""
    prefix = params["FacilitiesRoleNamePrefix"]
    zone = "arn:aws:route53:::hostedzone/%s" % params["AsmblyHostedZoneId"]
    bucket = params["SamArtifactBucket"]
    own_role = "arn:aws:iam::%s:role/%s-SomeFunctionRole-EXAMPLE" % (ACCOUNT_ID, prefix)
    cfn_write = ["cloudformation:UpdateStack", "cloudformation:CreateChangeSet",
                 "cloudformation:ExecuteChangeSet", "cloudformation:DeleteStack"]
    return [
        Check("deny: the -cicd stack (own permissions)", cfn_write,
              arn("cloudformation", "stack/%s-cicd/00000000-example" % STACK_PREFIX), False),
        Check("deny: the dev stack", cfn_write,
              arn("cloudformation", "stack/%s-dev/00000000-example" % STACK_PREFIX), False),
        Check("deny: another project's stack", cfn_write,
              arn("cloudformation", "stack/NeonIntegrationsStack-prod/00000000-example"), False),
        Check("deny: another project's function", ["lambda:UpdateFunctionCode",
                                                   "lambda:UpdateFunctionConfiguration"],
              arn("lambda", "function:NeonIntegrationsFunction-prod"), False),
        Check("deny: a dev facilities function", ["lambda:UpdateFunctionCode"],
              arn("lambda", "function:PMReminderBotFunction-dev"), False),
        Check("deny: another project's role", ["iam:PutRolePolicy", "iam:AttachRolePolicy",
                                               "iam:DeleteRole"],
              "arn:aws:iam::%s:role/NeonIntegrations-ExecutionRole" % ACCOUNT_ID, False,
              {"iam:PolicyARN": "arn:aws:iam::aws:policy/AdministratorAccess"}),
        Check("deny: pass another project's role", ["iam:PassRole"],
              "arn:aws:iam::%s:role/NeonIntegrations-ExecutionRole" % ACCOUNT_ID, False,
              {"iam:PassedToService": "lambda.amazonaws.com"}),
        Check("deny: attach AdministratorAccess to a facilities role", ["iam:AttachRolePolicy"],
              own_role, False, {"iam:PolicyARN": "arn:aws:iam::aws:policy/AdministratorAccess"}),
        Check("deny: pass a facilities role to EC2", ["iam:PassRole"], own_role, False,
              {"iam:PassedToService": "ec2.amazonaws.com"}),
        Check("deny: edit the deploy role itself", ["iam:UpdateAssumeRolePolicy",
                                                    "iam:PutRolePolicy", "iam:AttachRolePolicy"],
              "arn:aws:iam::%s:role/%s" % (ACCOUNT_ID, DEPLOY_ROLE_NAME), False,
              {"iam:PolicyARN": "arn:aws:iam::aws:policy/AdministratorAccess"}),
        Check("deny: new version of the deploy policy", ["iam:CreatePolicyVersion"],
              "arn:aws:iam::%s:policy/GitHub-OIDC-facilities-automation-deploy-policy" % ACCOUNT_ID,
              False),
        Check("deny: another REST API", ["apigateway:PUT", "apigateway:PATCH", "apigateway:DELETE"],
              "arn:aws:apigateway:%s::/restapis/otherapi00" % REGION, False),
        Check("deny: create a new REST API", ["apigateway:POST"],
              "arn:aws:apigateway:%s::/restapis" % REGION, False),
        Check("deny: another asmbly.org record", ["route53:ChangeResourceRecordSets"], zone, False,
              {"route53:ChangeResourceRecordSetsNormalizedRecordNames": ["www.asmbly.org"],
               "route53:ChangeResourceRecordSetsRecordTypes": ["A"]}),
        Check("deny: facilities record batched with another record",
              ["route53:ChangeResourceRecordSets"], zone, False,
              {"route53:ChangeResourceRecordSetsNormalizedRecordNames":
               [params["FacilitiesDomainName"], "shop.asmbly.org"],
               "route53:ChangeResourceRecordSetsRecordTypes": ["A"]}),
        Check("deny: MX record on the facilities name", ["route53:ChangeResourceRecordSets"], zone,
              False, {"route53:ChangeResourceRecordSetsNormalizedRecordNames":
                      [params["FacilitiesDomainName"]],
                      "route53:ChangeResourceRecordSetsRecordTypes": ["MX"]}),
        Check("deny: certificate for another domain", ["acm:RequestCertificate"], "*", False,
              {"acm:DomainNames": ["www.asmbly.org"]}),
        Check("deny: delete an untagged certificate", ["acm:DeleteCertificate"],
              arn("acm", "certificate/11111111-other"), False),
        Check("deny: another project's SSM parameter", ["ssm:PutParameter", "ssm:DeleteParameter"],
              arn("ssm", "parameter/prod/neon/config"), False),
        Check("deny: another project's log group", ["logs:DeleteLogGroup"],
              arn("logs", "log-group:/asmbly/lambda/NeonIntegrationsFunction-prod:*"), False),
        Check("deny: another project's table", ["dynamodb:DeleteTable"],
              arn("dynamodb", "table/NeonIntegrationsTable-prod"), False),
        Check("deny: another project's SAM artifacts", ["s3:PutObject"],
              "arn:aws:s3:::%s/NeonIntegrationsStack-prod/abc" % bucket, False),
    ]


# --------------------------------------------------------------------------
# Local policy evaluation (offline approximation of the IAM simulator)
# --------------------------------------------------------------------------
def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else [value]


def _match(operator: str, policy_values: List[str], actual: str) -> bool:
    base = operator.replace("IfExists", "")
    if base in ("StringEquals", "ArnEquals"):
        return actual in policy_values
    if base in ("StringLike", "ArnLike"):
        return any(fnmatch.fnmatchcase(actual, p) for p in policy_values)
    raise ValueError("Unsupported condition operator %s" % operator)


def _conditions_hold(conditions: Dict[str, Any], context: Dict[str, Any]) -> bool:
    for operator, keys in conditions.items():
        for key, policy_value in keys.items():
            policy_values = [str(v) for v in _as_list(policy_value)]
            present = key in context
            if operator == "Null":
                if (policy_values[0].lower() == "true") == present:
                    return False
                continue
            if operator.startswith("ForAllValues:"):
                if not present:
                    continue
                inner = operator.split(":", 1)[1]
                if not all(_match(inner, policy_values, v) for v in _as_list(context[key])):
                    return False
                continue
            if not present or isinstance(context[key], list):
                return False
            if not _match(operator, policy_values, context[key]):
                return False
    return True


def local_allowed(policies: List[Dict[str, Any]], action: str, resource: str,
                  context: Dict[str, Any]) -> bool:
    for policy in policies:
        for stmt in policy["document"]["Statement"]:
            if stmt.get("Effect") != "Allow":
                continue
            if not any(fnmatch.fnmatchcase(action.lower(), a.lower())
                       for a in _as_list(stmt["Action"])):
                continue
            if not any(fnmatch.fnmatchcase(resource, r) for r in _as_list(stmt["Resource"])):
                continue
            if _conditions_hold(stmt.get("Condition", {}), context):
                return True
    return False


# --------------------------------------------------------------------------
# Online checks (read-only AWS calls)
# --------------------------------------------------------------------------
def _context_entries(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = []
    for key, value in context.items():
        if isinstance(value, list):
            entries.append({"ContextKeyName": key, "ContextKeyValues": value,
                            "ContextKeyType": "stringList"})
        else:
            key_type = "arn" if str(value).startswith("arn:") else "string"
            entries.append({"ContextKeyName": key, "ContextKeyValues": [value],
                            "ContextKeyType": key_type})
    return entries


def simulator_allowed(iam: Any, policies: List[Dict[str, Any]], check: Check) -> Dict[str, bool]:
    docs = [json.dumps(p["document"]) for p in policies]
    kwargs: Dict[str, Any] = {"PolicyInputList": docs, "ActionNames": check.actions,
                              "ContextEntries": _context_entries(check.context)}
    if check.resource != "*":
        kwargs["ResourceArns"] = [check.resource]
    for attempt in range(4):
        try:
            response = iam.simulate_custom_policy(**kwargs)
            return {r["EvalActionName"]: r["EvalDecision"] == "allowed"
                    for r in response["EvaluationResults"]}
        except Exception as exc:  # pylint: disable=broad-except
            if "Throttling" in str(exc) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            logger.error("Simulator call failed for %s: %s", check.label, exc)
            raise
    return {}


def validate_with_access_analyzer(session: Any, policies: List[Dict[str, Any]]) -> int:
    analyzer = session.client("accessanalyzer", region_name=REGION)
    problems = 0
    for policy in policies:
        try:
            findings = analyzer.validate_policy(policyDocument=json.dumps(policy["document"]),
                                                policyType="IDENTITY_POLICY")["findings"]
        except Exception:  # pylint: disable=broad-except
            logger.exception("Access Analyzer validation failed for %s", policy["name"])
            return problems + 1
        for finding in findings:
            level = finding["findingType"]
            print("  [%s] %s: %s" % (level, policy["name"], finding["findingDetails"]))
            if level in ("ERROR", "SECURITY_WARNING"):
                problems += 1
    return problems


def actions_used_by_role(session: Any) -> List[str]:
    """Actions the current deploy role has used, from IAM last accessed data."""
    iam = session.client("iam")
    role_arn = "arn:aws:iam::%s:role/%s" % (ACCOUNT_ID, DEPLOY_ROLE_NAME)
    try:
        job = iam.generate_service_last_accessed_details(Arn=role_arn, Granularity="ACTION_LEVEL")
        for _ in range(30):
            details = iam.get_service_last_accessed_details(JobId=job["JobId"])
            if details["JobStatus"] != "IN_PROGRESS":
                break
            time.sleep(2)
    except Exception:  # pylint: disable=broad-except
        logger.exception("Could not read last accessed data for %s", role_arn)
        return []
    used = []
    for service in details.get("ServicesLastAccessed", []):
        for tracked in service.get("TrackedActionsLastAccessed", []) or []:
            if tracked.get("LastAccessedTime"):
                used.append("%s:%s" % (service["ServiceNamespace"], tracked["ActionName"]))
    return sorted(used)


# --------------------------------------------------------------------------
# Trust policy check
# --------------------------------------------------------------------------
def check_trust(trust: Dict[str, Any], params: Dict[str, Any]) -> int:
    """Compares trusted OIDC subjects with what the deploy workflows send."""
    repo = "%s/%s" % (params["GitHubOrg"], params["GitHubRepo"])
    expected = set()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_name, job in (data.get("jobs") or {}).items():
            uses_role = any("role-to-assume" in (step.get("with") or {})
                            for step in job.get("steps", []))
            if not uses_role:
                continue
            env = job.get("environment")
            env_name = env.get("name") if isinstance(env, dict) else env
            if env_name:
                expected.add("repo:%s:environment:%s" % (repo, env_name))
            else:
                branches = (data.get(True) or data.get("on") or {}).get("push", {}).get("branches", [])
                expected.update("repo:%s:ref:refs/heads/%s" % (repo, b) for b in branches)
            logger.debug("Workflow %s job %s assumes the role", workflow.name, job_name)

    problems = 0
    for stmt in trust["Statement"]:
        conditions = stmt.get("Condition", {})
        if any(OIDC_SUB_KEY in keys for op, keys in conditions.items() if op != "StringEquals"):
            print("  FAIL: the sub claim is matched with a non-exact operator")
            problems += 1
        trusted = set(_as_list(conditions.get("StringEquals", {}).get(OIDC_SUB_KEY, [])))
        aud = conditions.get("StringEquals", {}).get("token.actions.githubusercontent.com:aud")
        if aud != "sts.amazonaws.com":
            print("  FAIL: aud is %r, expected 'sts.amazonaws.com'" % aud)
            problems += 1
        for sub in sorted(expected - trusted):
            print("  FAIL: a deploy workflow sends %s, which is not trusted" % sub)
            problems += 1
        for sub in sorted(trusted - expected):
            print("  FAIL: %s is trusted but no deploy workflow sends it" % sub)
            problems += 1
        for sub in sorted(trusted & expected):
            print("  ok    trusted: %s" % sub)
        if any("*" in s or "?" in s for s in trusted):
            print("  FAIL: a trusted subject contains a wildcard")
            problems += 1
    return problems


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def run_checks(checks: Iterable[Check], evaluate: Any) -> int:
    failures = 0
    for check in checks:
        results = evaluate(check)
        for action in check.actions:
            allowed = results[action]
            if allowed != check.expect_allowed:
                failures += 1
                verdict = "allowed" if allowed else "DENIED"
                print("  FAIL: %s -> %s on %s (%s)" % (check.label, action, check.resource, verdict))
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true",
                        help="No AWS calls: predict names from the templates, evaluate locally.")
    parser.add_argument("--profile", help="AWS profile for online mode.")
    parser.add_argument("--role-prefix", help="Override FacilitiesRoleNamePrefix.")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    session = None
    overrides: Dict[str, str] = {}
    live: Dict[str, List[Item]] = {}

    if args.offline:
        overrides.update(StageRestApiId=PLACEHOLDER_API_IDS["stage"],
                         ProdRestApiId=PLACEHOLDER_API_IDS["prod"],
                         AsmblyHostedZoneId=PLACEHOLDER_ZONE_ID)
    else:
        import boto3  # pylint: disable=import-outside-toplevel
        session = boto3.Session(profile_name=args.profile, region_name=REGION)
        identity = session.client("sts").get_caller_identity()
        if identity["Account"] != ACCOUNT_ID:
            print("Credentials are for account %s, expected %s" % (identity["Account"], ACCOUNT_ID))
            return 2
        print("Using %s" % identity["Arn"])
        ssm = session.client("ssm", region_name=REGION)
        overrides["AsmblyHostedZoneId"] = ssm.get_parameter(
            Name="/config/route53/asmbly/hosted-zone-id")["Parameter"]["Value"]
        for stage in CI_STAGES:
            items, api_id = live_inventory(session, stage)
            live[stage] = items
            if not api_id:
                print("Could not find the FacilitiesApi REST API in the %s stack" % stage)
                return 2
            overrides["%sRestApiId" % stage.capitalize()] = api_id
            print("%s REST API id: %s" % (stage, api_id))
    if args.role_prefix:
        overrides["FacilitiesRoleNamePrefix"] = args.role_prefix

    policies, trust, params = render_cicd(overrides)
    failures = 0

    print("\n== Policy size (limit 6144 characters per managed policy)")
    for policy in policies:
        size = len(json.dumps(policy["document"], separators=(",", ":")))
        status = "ok  " if size <= 6144 else "FAIL"
        failures += size > 6144
        print("  %s  %-28s %5d" % (status, policy["name"], size))

    print("\n== Trust policy")
    failures += check_trust(trust, params)

    print("\n== Resource: \"*\" statements")
    for policy in policies:
        for stmt in policy["document"]["Statement"]:
            if "*" in _as_list(stmt["Resource"]):
                print("  %s/%s: %s" % (policy["name"], stmt.get("Sid"),
                                       ", ".join(_as_list(stmt["Action"]))))

    checks: List[Check] = []
    prefix = params["FacilitiesRoleNamePrefix"]
    for stage in CI_STAGES:
        api_id = params["%sRestApiId" % stage.capitalize()]
        items = live.get(stage) or predicted_inventory(stage, prefix, api_id)
        for item in items:
            if item.type == "AWS::IAM::Role" and not item.name.startswith(prefix):
                print("  FAIL: role %s does not start with %s" % (item.name, prefix))
                failures += 1
            checks.extend(checks_for_item(item, params))
        checks.extend(sam_cli_checks(stage, params))
    checks.extend(negative_checks(params))

    allowed_checks = sum(len(c.actions) for c in checks if c.expect_allowed)
    denied_checks = sum(len(c.actions) for c in checks if not c.expect_allowed)
    mode = "local evaluator" if args.offline else "IAM policy simulator"
    print("\n== Deploy calls (%d expected allowed, %d expected denied; %s)"
          % (allowed_checks, denied_checks, mode))
    if args.offline:
        def evaluate(check: Check) -> Dict[str, bool]:
            return {a: local_allowed(policies, a, check.resource, check.context)
                    for a in check.actions}
    else:
        iam = session.client("iam")

        def evaluate(check: Check) -> Dict[str, bool]:
            return simulator_allowed(iam, policies, check)
    call_failures = run_checks(checks, evaluate)
    failures += call_failures
    if not call_failures:
        print("  ok    every deploy call is allowed and every other-project call is denied")

    if not args.offline:
        print("\n== IAM Access Analyzer validation")
        failures += validate_with_access_analyzer(session, policies)

        print("\n== Actions the current role has used (IAM last accessed)")
        for action in actions_used_by_role(session):
            known = any(fnmatch.fnmatchcase(action.lower(), a.lower())
                        for p in policies for s in p["document"]["Statement"]
                        for a in _as_list(s["Action"]))
            print("  %s  %s" % ("ok  " if known else "MISSING", action))
            failures += not known

    print("\n%s: %d problem(s)" % ("PASS" if not failures else "FAIL", failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
