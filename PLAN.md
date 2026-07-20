# Dynamic DNS → Route53 via Lambda (`networking` stack)

## Architecture

```
UDM (built-in DDNS client, DynDNS2 protocol)
  → HTTPS GET with Basic Auth
    → FacilitiesApi (existing shared REST API, throttled per-route)
      → Lambda (Python 3.12, validates auth, upserts Route53)
        → Secrets Manager (credential lookup)
        → Route53 ChangeResourceRecordSets
```

The UDM's native DDNS client handles IP change detection and calls out using
the standard DynDNS2 protocol. No custom software runs on the UDM.

This feature is implemented as a new nested stack (`NetworkingStack`,
`templates/networking.yaml`) wired into the existing root `template.yaml`,
following the project's multi-stack architecture.

## Components

### 1. API Gateway route (existing `FacilitiesApi`)

- New route on the existing shared REST API (`AWS::Serverless::Api`
  `FacilitiesApi` in the root `template.yaml`): `GET /nic/update`
  (DynDNS2 standard endpoint), added to `DefinitionBody.paths` alongside the
  other integrations, proxying to the new Lambda's ARN
  (`${NetworkingStack.Outputs.DynamicDnsUpdateFunctionArn}`).
- A dedicated `MethodSettings` entry scoped to `ResourcePath: /nic/update`,
  `HttpMethod: GET` sets `ThrottlingRateLimit: 1` and `ThrottlingBurstLimit: 10`
  so the limit applies only to this route and doesn't affect the other
  integrations already served by `FacilitiesApi`.
- No API key (UDM client doesn't support custom headers); HTTPS only
  (default for API Gateway).
- A corresponding `AWS::Lambda::Permission` (matching the pattern of the
  other `*InvokePermission` resources in the root template) grants
  `FacilitiesApi` permission to invoke the function.

Reusing the existing REST API (rather than standing up a separate HTTP API)
keeps all public routes, access logging, and throttling configuration in one
place per the project's single-API convention. The REST API's per-method
`MethodSettings` throttling gives the same abuse protection an HTTP API route
throttle would.

### 2. Lambda Function (Python 3.12)

- Location: `functions/networking/dynamic_dns_update/lambda_function.py`
  (handler: `lambda_handler`), following the standard one-function-per-folder
  layout, with its own `README.md` and `tests/` directory (pytest, per
  [Running Tests](docs/CONTRIBUTING.md#running-tests)).
- Runtime: Python 3.12 via `Globals.Function.Runtime` (boto3 included,
  minimal cold start)
- Memory: 128 MB (repo default; sufficient for this workload)
- Timeout: 10 seconds
- Reserved concurrency: **2** (hard ceiling on parallel executions)
- Layers: `CommonLayerARN` (shared `common` utilities) only; the
  `requests` layer is not needed since this function only calls AWS APIs
  via `boto3`.
- Configuration via `os.environ` (populated from the `Environment.Variables`
  block, per [The Connector](AGENTS.md#2-the-integration-engineer-the-connector)
  conventions): `DDNS_SECRET_NAME`, `HOSTED_ZONE_ID`, `STAGE`.
- Logic:
  1. Parse Basic Auth header from request
  2. Fetch the credential secret via `common.aws.get_secret(DDNS_SECRET_NAME, ...)`
     and compare the supplied username/password using `hmac.compare_digest`
     (constant-time comparison; stdlib, no new dependency)
  3. Extract `hostname` (DynDNS2 allows a comma-separated list of hostnames
     in a single update — the UDM can be configured with more than one) and
     `myip` parameters; split `hostname` on `,`
  4. Verify every requested hostname is present in the secret's
     `allowed_hostnames` list — reject the whole request (`badauth`) if any
     hostname isn't allowed, so a partial/ambiguous update never happens
  5. For each requested hostname, call `route53:ChangeResourceRecordSets`
     (UPSERT A record) unconditionally — idempotent, so no IP-change cache
     is needed
  6. Return a DynDNS2 response code per hostname, newline-separated
     (`good <ip>`, `badauth`, etc.), per the DynDNS2 multi-hostname response
     format
  - All external AWS calls wrapped in `try/except` with lazy `logger`
    calls (no f-strings in log statements), matching the repo's Python
    conventions.

### 3. Secrets Manager credential

- Secret: `ddns/router-credential` (or scoped per-stage, e.g.
  `!Sub "ddns/router-credential-${Stage}"`, consistent with the `${Stage}`
  isolation used elsewhere), created and managed the same way as the
  repo's other credentials (via the AWS Console/CLI, referenced by name —
  not defined as a CloudFormation resource, matching how `clickup/api/token`
  etc. are handled).
- JSON value: `{"username": "...", "password": "...", "allowed_hostnames": ["shop.asmbly.org", "vpn.asmbly.org"]}`.
  A single credential covers one router and lists the hostnames it's
  allowed to update, matching the DynDNS2 protocol's support for a
  comma-separated `hostname` parameter.
  Stored as plaintext (like the repo's other API tokens) — comparison happens
  via `hmac.compare_digest` in the Lambda.
- **Keep in sync with the IAM policy:** `allowed_hostnames` here is the
  application-level allowlist; the `DdnsHostnames` CloudFormation parameter
  below is the IAM-level allowlist. They must contain the same hostnames.
  If a hostname is added to the secret but not to `DdnsHostnames` (or vice
  versa), the mismatch fails safe — Route53 rejects the update with
  `AccessDenied` rather than allowing an unauthorized record change.

### 4. IAM permissions (Lambda execution)

Defined inline via the `Function`'s `Policies` property (the pattern used by
`templates/administrative.yaml` and `templates/ceramics.yaml`) rather than a
hand-rolled `AWS::IAM::Role`, so SAM continues to manage the base execution
role (CloudWatch Logs, etc.) and only the extra least-privilege statements
below are added. Route53 has no record-level ARN — the `Resource` is always
the hosted zone — but the `ChangeResourceRecordSets` condition keys restrict
which record names/types/actions the call may submit, so a compromised
credential still can't touch other subdomains in the zone:

```yaml
Parameters:
  DdnsHostnames:
    Type: CommaDelimitedList
    Description: >
      Hostnames (in the asmbly.org zone) this credential is allowed to
      update. Must stay in sync with the secret's `allowed_hostnames`.
    Default: "shop.asmbly.org.,vpn.asmbly.org."

Resources:
  DynamicDnsUpdateFunction:
    Type: AWS::Serverless::Function
    Properties:
      # ...
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action: route53:ChangeResourceRecordSets
              Resource: !Sub 'arn:aws:route53:::hostedzone/${HostedZoneId}'
              Condition:
                ForAllValues:StringEquals:
                  route53:ChangeResourceRecordSetsNormalizedRecordNames: !Ref DdnsHostnames
                  route53:ChangeResourceRecordSetsRecordTypes: ['A']
                  route53:ChangeResourceRecordSetsActions: ['UPSERT']
            - Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource:
                - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:${DdnsSecretName}-*'
```

`ForAllValues:StringEquals` accepts a list directly, so `DdnsHostnames` (a
`CommaDelimitedList` parameter, each entry supplied with its trailing dot
already normalized, e.g. `shop.asmbly.org.,vpn.asmbly.org.`) covers all
allowed hostnames for this credential without per-hostname policy
duplication. `HostedZoneId` is passed in from the root template's existing
`AsmblyHostedZoneId` SSM parameter (see below) — no new hosted-zone
parameter is introduced. `DdnsHostnames` and `DdnsSecretName` are new
nested-stack parameters, since the records being updated must live in the
`asmbly.org` zone the project already manages.

Notes:
- Record names must be normalized: lowercase, punycode, trailing dot.
- Use `ForAllValues:StringLike` with a pattern (e.g. `*.asmbly.org.`) instead
  of an explicit `DdnsHostnames` list if an open-ended set of subdomains
  should be allowed rather than a fixed, enumerated set.

### 5. CloudFormation

- **New nested stack** `templates/networking.yaml`, defining the Lambda
  function (with its inline `Policies`) and its `LogGroup` (matching the
  `LoggingConfig` pattern used elsewhere).
  Parameters: `Stage`, `CommonLayerARN`, `HostedZoneId`, `DdnsHostnames`
  (`CommaDelimitedList`), `DdnsSecretName`. Outputs: `DynamicDnsUpdateFunctionArn`.
- **Root `template.yaml` changes:**
  - Add `NetworkingStack: AWS::Serverless::Application` pointing at
    `./templates/networking.yaml`, passing `Stage`, `CommonLayerARN`,
    `AsmblyHostedZoneId` (existing parameter), and new `DdnsHostnames`
    (default `shop.asmbly.org.,vpn.asmbly.org.`) / `DdnsSecretName` (default
    `ddns/router-credential`) parameters.
  - Add the `GET /nic/update` path to `FacilitiesApi`'s `DefinitionBody`
    and the corresponding `MethodSettings` throttle entry, plus a
    `DynamicDnsUpdateInvokePermission` (`AWS::Lambda::Permission`), all
    following the existing conventions for the other integrations.
- **`template-cicd.yaml`:** the `GitHubDeployPolicy` must be extended with
  `route53:GetHostedZone` (needed at deploy-validation time), scoped to the
  zone ARN — per [Deploying.md](docs/Deploying.md#cicd-infrastructure-the-deployer-role),
  this must be deployed manually before the automated `prod` pipeline can
  create these resources.
- **Secret creation:** the secret itself is created out-of-band (via
  `scripts/add_credential.py` or the AWS Console), consistent with how
  `clickup/api/token` and the other existing secrets are provisioned — the
  template only grants read access to it.

## UDM Configuration

In UniFi Console → Settings → Internet → WAN → Dynamic DNS:

| Field | Value |
|-------|-------|
| Service | `custom` |
| Hostname | `shop.asmbly.org,vpn.asmbly.org` — a comma-separated list, per the DynDNS2 spec, to update both records pointing at this router in one call. Both are in the `asmbly.org` zone referenced by the existing `AsmblyHostedZoneId` SSM parameter, and must match the secret's `allowed_hostnames` / the stack's `DdnsHostnames` parameter. |
| Username | (chosen username) |
| Password | (chosen password) |
| Server | `<facilities-api-id>.execute-api.<region>.amazonaws.com/<stage>/nic/update` (the existing `FacilitiesApi` invoke URL — see the `FacilitiesApiUrl`/`FacilitiesProdUrl` outputs) |

The UDM will call this endpoint whenever it detects a WAN IP change, and
periodically as a keepalive (typically every 5 minutes when IP is stable,
but only after initial detection).

## Cost Projection

### Legitimate Use (steady state)

| Resource | Usage | Monthly Cost |
|----------|-------|-------------|
| FacilitiesApi (REST API, existing) | ~300 requests (10/day) | $0.001 |
| Lambda invocations | ~300 | $0.00006 |
| Lambda compute | 300 × 128MB × 100ms | $0.000005 |
| Secrets Manager secret | 1 secret + ~300 GetSecretValue calls | ~$0.40 |
| Route53 API calls | ~600 UPSERT calls (2 hostnames × every request, idempotent) | $0.0003 |
| **Total** | | **~$0.40/month** |

REST API pricing (~$3.50/million requests) is higher than an HTTP API
(~$1/million), but at this volume the difference is immaterial, and reusing
the existing `FacilitiesApi` (rather than paying for a second gateway) is
the net cheaper — and architecturally correct — choice. The Secrets Manager
secret's flat $0.40/month is the dominant cost line, consistent with the
repo's other credential secrets.

### Abuse Scenario (sustained attack, WITH throttle)

The `/nic/update` `MethodSettings` throttle limits throughput on that route
to 1 req/sec regardless of inbound volume, without affecting the gateway's
other routes.

| Resource | Usage | Daily Cost |
|----------|-------|-----------|
| FacilitiesApi (REST API) | 86,400 requests (1/sec sustained) | $0.30 |
| Lambda invocations | 86,400 | $0.02 |
| Lambda compute | 86,400 × 128MB × 50ms | $0.01 |
| Secrets Manager GetSecretValue | 86,400 calls | $0.43 |
| **Total worst-case day** | | **$0.76** |
| **Total worst-case month** | | **~$22.80** |

The `MethodSettings` throttle is the critical cost control, keeping this
worst-case scenario to $0.76/day regardless of inbound request volume.

## Abuse Mitigation (layered)

1. **Per-route `MethodSettings` throttle** (1 req/sec, burst 10, scoped to
   `GET /nic/update` only) — primary defense, rejects excess requests with
   HTTP 429 before Lambda runs
2. **Lambda reserved concurrency = 2** — hard cap on parallel executions,
   prevents runaway billing even if the throttle is misconfigured
3. **Auth validation first** — Lambda checks credentials before doing any
   Secrets Manager/Route53 work; failed auth = early return, minimal compute

## File Structure (planned)

Fits into the existing repo layout — no new top-level template or `src/`
directory:

```
├── PLAN.md                                  (this file)
├── template.yaml                            (updated: NetworkingStack, /nic/update route, MethodSettings)
├── template-cicd.yaml                       (updated: GitHubDeployPolicy gains route53:GetHostedZone)
├── templates/
│   └── networking.yaml                      (new nested stack: Lambda, LogGroup)
├── functions/
│   └── networking/
│       ├── __init__.py
│       └── dynamic_dns_update/
│           ├── __init__.py
│           ├── README.md                    (setup and UDM configuration guide)
│           ├── lambda_function.py
│           └── tests/
│               ├── __init__.py
│               └── test_lambda_function.py
└── scripts/
    └── add_credential.py                    (CLI tool to create/update the Secrets Manager secret)
```

## Deployment (planned workflow)

Follows the existing SAM-based workflow described in
[Deploying.md](docs/Deploying.md) — no raw `aws cloudformation
package`/`deploy` calls:

```bash
# One-time: extend the deployer role (manual, local admin credentials)
sam deploy --template-file template-cicd.yaml \
  --stack-name AsmblyFacilitiesMaintTrackingStack-cicd \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --region us-east-2

# One-time: create the credential secret (out-of-band, like the repo's other secrets)
python scripts/add_credential.py --stage dev --username udm \
  --hostname shop.asmbly.org --hostname vpn.asmbly.org

# When deploying, DdnsHostnames must include the same hostnames passed above
sam build
sam deploy --config-env dev \
  --parameter-overrides DdnsHostnames="shop.asmbly.org.,vpn.asmbly.org."

# prod deploys automatically via GitHub Actions on merge to main
```

