---
phase_id: 5
title: API function, routes and Cognito authorizer
epic: 73
implements: [104, 105, 106, 107, 108, 109]
depends_on: [2, 4]
domain: [lambda, infra]
estimated_size: L
---

# Phase 5: API function, routes and Cognito authorizer

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md` (all of "Rules"), `docs/Deploying.md` ("CI/CD Infrastructure (The
  Deployer Role)").
- The hand-offs of phases 1–4.
- `functions/networking/dynamic_dns_update/lambda_function.py` and its tests: the
  pattern for a handler that checks its caller, reads a secret through `common.aws`,
  and never returns an error's text.
- `templates/networking.yaml` (function, explicit log group, exact-ARN policies, tags)
  and `templates/purchase_request.yaml` (`AWS::SSM::Parameter` built from
  `configs/*.json` with `AWS::Include`); `templates/facilities.yaml` for
  `DRY_RUN: !If [IsProd, 'false', 'true']`.
- `template.yaml`: `Parameters` (`AsmblyHostedZoneId` is the SSM-typed pattern),
  `FacilitiesApi` (`MethodSettings`, `DefinitionBody.paths`), the nested stacks, the
  invoke permissions.
- `template-cicd.yaml`: `AllowSSMParameterRead`, and in both `GitHubDeployPolicystage`
  and `GitHubDeployPolicyprod`: `AllowLambdaFunctionManagement`,
  `AllowCloudWatchLogsManagement`, `AllowSSMParameterWrite`.
- `tests/test_templates.py` (its checks apply to the new template automatically).
- AWS docs: "Integrate a REST API with an Amazon Cognito user pool" (OpenAPI
  `x-amazon-apigateway-authorizer` of type `cognito_user_pools`, `providerARNs`; the
  client sends the ID token in `Authorization`; claims arrive in
  `requestContext.authorizer.claims`); `AWS::ApiGateway::Stage MethodSetting`
  (`ResourcePath` encodes `/` as `~1`).

## Goal

Two authenticated routes exist on the stage and prod APIs and work end to end:
`GET /class-photo-upload/classes` returns the class list from Neon, and
`POST /class-photo-upload/submit` checks the photo and the class, then opens or updates
the pull request (prod) or reports what it would do (stage, dry run). A request without
a valid staff ID token for this app client changes nothing. The page itself comes in
phase 6; until then the routes can be exercised with a token from the Cognito hosted UI.

## Files to create

- `functions/classes/class_photo_upload_api/lambda_function.py`: the handler.
- `functions/classes/class_photo_upload_api/requirements.txt`: `PyJWT[crypto]==<the
  version pinned in requirements-dev.txt by phase 3>`.
- `functions/classes/class_photo_upload_api/README.md`: what it does, routes, environment
  variables, secrets and their JSON keys, dry run, responses, how to undo a pull request.
- `functions/classes/class_photo_upload_api/tests/test_lambda_function.py`.
- `functions/classes/class_photo_upload_api/tests/fixtures/api_event_classes.json` and
  `api_event_submit.json`: API Gateway proxy events with
  `requestContext.authorizer.claims` (`sub`, `aud`, `token_use`, `cognito:username`;
  fake values) and no real token.
- `templates/classes.yaml`: the nested stack.
- `configs/class_photo_upload.json`.

## Files to modify

- `template.yaml`: three parameters, the authorizer, two paths, throttling, the
  `ClassesStack`, one invoke permission.
- `template-cicd.yaml`: the names below, in both stage and prod policies, and the shared
  SSM read.
- `tests/test_templates.py`: one test for the authorizer on the new routes.

## Implementation details

### infra: `configs/class_photo_upload.json`

```json
{
  "repo_owner": "asmbly-makerspace",
  "repo_name": "asmbly-classes",
  "base_branch": "main",
  "images_dir": "app/src/lib/images",
  "branch_prefix": "class-photo/",
  "image_extensions": ["avif", "gif", "heif", "jpeg", "jpg", "png", "tiff", "webp"]
}
```

`RepoConfig.from_dict` (phase 4) maps `repo_owner` → `owner`, `repo_name` → `repo`; use
these key names in both places.

### infra: `templates/classes.yaml`

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform:
  - AWS::LanguageExtensions
  - AWS::Serverless-2016-10-31
Description: Class photo upload page and its API.

Parameters:
  Stage:
    Type: String
  CommonLayerARN:
    Type: String
  RequestsLayerARN:
    Type: String
  NeonSecretName:
    Type: String
  ClassPhotoGitHubAppSecretName:
    Type: String
  ClassPhotoAppClientId:
    Type: String

Conditions:
  IsProd: !Equals [!Ref Stage, 'prod']

Resources:
  ClassPhotoUploadConfigParameter:
    Type: AWS::SSM::Parameter
    Properties:
      Name: !Sub "/${Stage}/config/class-photo-upload"
      Type: String
      Description: "asmbly-classes coordinates for the class photo upload. Managed by templates/classes.yaml."
      Value:
        Fn::ToJsonString:
          Fn::Transform:
            Name: 'AWS::Include'
            Parameters:
              Location: ../configs/class_photo_upload.json
      Tags:
        Project: classes:class-photo-upload

  ClassPhotoUploadApiLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub "/asmbly/lambda/ClassPhotoUploadApiFunction-${Stage}"
      RetentionInDays: 14
      Tags:
        - Key: Project
          Value: classes:class-photo-upload

  ClassPhotoUploadApiFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: !Sub "ClassPhotoUploadApiFunction-${Stage}"
      Description: "Lists classes from Neon and turns a checked class photo into a pull request on asmbly-classes (dry run outside prod)."
      CodeUri: ../functions/classes/class_photo_upload_api/
      Handler: lambda_function.lambda_handler
      Runtime: python3.12
      Timeout: 25
      MemorySize: 256
      ReservedConcurrentExecutions: 3
      LoggingConfig:
        LogGroup: !Ref ClassPhotoUploadApiLogGroup
      Layers:
        - !Ref CommonLayerARN
        - !Ref RequestsLayerARN
      Environment:
        Variables:
          STAGE: !Ref Stage
          NEON_SECRET_NAME: !Ref NeonSecretName
          GITHUB_APP_SECRET_NAME: !Ref ClassPhotoGitHubAppSecretName
          CLASS_PHOTO_CONFIG_PARAM_NAME: !Ref ClassPhotoUploadConfigParameter
          CLASS_PHOTO_APP_CLIENT_ID: !Ref ClassPhotoAppClientId
          CLASS_PHOTO_DRY_RUN: !If [IsProd, 'false', 'true']
      Policies:
        - Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action: ssm:GetParameter
              Resource: !Sub 'arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter${ClassPhotoUploadConfigParameter}'
            - Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource:
                - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:${NeonSecretName}-*'
                - !Sub 'arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:${ClassPhotoGitHubAppSecretName}-*'
      Tags:
        Project: classes:class-photo-upload

Outputs:
  ClassPhotoUploadApiFunctionArn:
    Description: "ARN of the class photo upload API function"
    Value: !GetAtt ClassPhotoUploadApiFunction.Arn
```

(`!Ref` on an `AWS::SSM::Parameter` returns its name with the leading `/`, hence
`parameter${...}` without a slash, as elsewhere in this repository.)

### infra: `template.yaml`

Parameters (after `DdnsSecretName`):

```yaml
  StaffUserPoolId:
    Type: 'AWS::SSM::Parameter::Value<String>'
    Default: /config/cognito/staff/user-pool-id
    Description: ID of Asmbly's staff sign-in user pool (managed by AsmblyMCPs). Fetched from SSM.
  ClassPhotoAppClientId:
    Type: 'AWS::SSM::Parameter::Value<String>'
    Default: /config/cognito/staff/class-photo-app-client-id
    Description: The staff pool's app client for the class photo upload page. Fetched from SSM.
  ClassPhotoGitHubAppSecretName:
    Type: String
    Default: "github/class-photo-upload-app"
    Description: Secrets Manager secret with the class photo GitHub App's app_id, installation_id and private_key.
```

`FacilitiesApi` → `MethodSettings`, add:

```yaml
        - ResourcePath: "/~1class-photo-upload~1submit"
          HttpMethod: POST
          ThrottlingRateLimit: 1
          ThrottlingBurstLimit: 5
```

`FacilitiesApi` → `DefinitionBody`, add a `components` key beside `paths`:

```yaml
        components:
          securitySchemes:
            StaffCognitoAuthorizer:
              type: apiKey
              name: Authorization
              in: header
              x-amazon-apigateway-authtype: cognito_user_pools
              x-amazon-apigateway-authorizer:
                type: cognito_user_pools
                providerARNs:
                  - Fn::Sub: "arn:aws:cognito-idp:${AWS::Region}:${AWS::AccountId}:userpool/${StaffUserPoolId}"
```

and under `paths`:

```yaml
          /class-photo-upload/classes:
            get:
              security:
                - StaffCognitoAuthorizer: []
              x-amazon-apigateway-integration:
                httpMethod: POST
                type: aws_proxy
                uri:
                  Fn::Sub: "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ClassesStack.Outputs.ClassPhotoUploadApiFunctionArn}/invocations"
              responses: {}
          /class-photo-upload/submit:
            post:
              security:
                - StaffCognitoAuthorizer: []
              x-amazon-apigateway-integration:
                httpMethod: POST
                type: aws_proxy
                uri:
                  Fn::Sub: "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${ClassesStack.Outputs.ClassPhotoUploadApiFunctionArn}/invocations"
              responses: {}
```

Nested stack (after `NetworkingStack`):

```yaml
  ClassesStack:
    Type: AWS::Serverless::Application
    Properties:
      Location: ./templates/classes.yaml
      Parameters:
        Stage: !Ref Stage
        CommonLayerARN: !Ref CommonLayer
        RequestsLayerARN: !Ref RequestsLambdaLayer
        NeonSecretName: !Ref NeonSecretName
        ClassPhotoGitHubAppSecretName: !Ref ClassPhotoGitHubAppSecretName
        ClassPhotoAppClientId: !Ref ClassPhotoAppClientId
      Tags:
        Application: facilities-automation-hub
        Workspace: classes
        Stage: !Ref Stage
```

Invoke permission, scoped to this feature's paths:

```yaml
  ClassPhotoUploadApiInvokePermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !GetAtt ClassesStack.Outputs.ClassPhotoUploadApiFunctionArn
      Action: lambda:InvokeFunction
      Principal: apigateway.amazonaws.com
      SourceArn: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${FacilitiesApi}/*/*/class-photo-upload/*"
```

### infra: `template-cicd.yaml`

Shared statement `AllowSSMParameterRead` (CloudFormation resolves SSM-typed parameters
with the deployer's credentials): turn `Resource` into a list and add

```yaml
              - !Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/user-pool-id"
              - !Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/config/cognito/staff/class-photo-app-client-id"
```

`GitHubDeployPolicystage`:

- `AllowLambdaFunctionManagement`:
  `!Sub "arn:aws:lambda:${AWS::Region}:${AWS::AccountId}:function:ClassPhotoUploadApiFunction-stage"`
- `AllowCloudWatchLogsManagement`:
  `!Sub "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/asmbly/lambda/ClassPhotoUploadApiFunction-stage*"`
- `AllowSSMParameterWrite`:
  `!Sub "arn:aws:ssm:${AWS::Region}:${AWS::AccountId}:parameter/stage/config/class-photo-upload"`

`GitHubDeployPolicyprod`: the same three with `-prod` and `/prod/`.

The nested stack's name starts with `AsmblyFacilitiesMaintTrackingStack-<stage>-`, already
covered by `AllowCloudFormationStackOperations`; its generated role starts with
`FacilitiesRoleNamePrefix`, already covered. **Prep must confirm** (read-only, against AWS
docs or a stage dry deploy log) whether creating a `COGNITO_USER_POOLS` authorizer needs
any `cognito-idp:` permission on the deployer; if it does, add that one action on the
exact pool ARN (`arn:aws:cognito-idp:${AWS::Region}:${AWS::AccountId}:userpool/${StaffUserPoolId}`,
with `StaffUserPoolId` as an SSM-typed parameter of the cicd template), never `*`.

### lambda: `lambda_function.py`

```python
GENERIC_ERROR = "Something went wrong on our side. Try again later."
NEON_ERROR = "Couldn't load the class list. Try again in a minute."
GITHUB_ERROR = "Couldn't open the pull request. Try again in a minute."
CONFLICT_ERROR = "Someone else just submitted a photo for this class. Try again."
FORBIDDEN_ERROR = "You're not allowed to use this page."
NOT_IN_LIST_ERROR = "Pick a class from the list."
BAD_REQUEST_ERROR = "The photo didn't arrive whole. Choose it again and submit."
REQUIRED_ENV = ("NEON_SECRET_NAME", "GITHUB_APP_SECRET_NAME", "CLASS_PHOTO_CONFIG_PARAM_NAME",
                "CLASS_PHOTO_APP_CLIENT_ID")

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]: ...
```

Flow:

1. **Environment.** Any of `REQUIRED_ENV` missing → `logger.error("Missing environment
   variable %s", name)`, 500 `GENERIC_ERROR`. `dry_run = os.environ.get("CLASS_PHOTO_DRY_RUN",
   "true").strip().lower() != "false"` (anything but `false` is a dry run).
2. **Caller.** API Gateway's authorizer already answered 401 to a missing, expired or
   foreign-pool token. Then `claims = event["requestContext"]["authorizer"]["claims"]`;
   require `claims["aud"] == CLASS_PHOTO_APP_CLIENT_ID` (compared with
   `hmac.compare_digest`), `claims["token_use"] == "id"`, and non-empty `sub` and
   `cognito:username`. Otherwise 403 `FORBIDDEN_ERROR`, log `"Rejected caller: %s"` with the
   reason (`audience`, `token_use`, `claims`), never the claims' values. Nothing else runs.
3. **Route** by `(event["httpMethod"], event["resource"])`:
   `("GET", "/class-photo-upload/classes")` → classes; `("POST",
   "/class-photo-upload/submit")` → submit; else 404 `{"error": "Not found."}`.
4. **Classes.** Neon credentials: `aws.get_secret(NEON_SECRET_NAME, "NEON_ORG_ID")` and
   `"NEON_API_KEY"` (the keys the waiver function uses) → `NeonCRM(org_id, api_key)` →
   `class_names.fetch_classes(neon, datetime.now(timezone.utc).date())`. A failure reading
   the secret or `NeonCRMError` → log the error class, 502 `NEON_ERROR`. Answer 200:
   ```json
   {"dry_run": true,
    "classes": [{"name": "...", "file_name": "....jpg", "problem": null, "warning": null}]}
   ```
   `problem` is `file_name_problem(name)`; `warning` is the collision warning.
5. **Submit.**
   1. Body: `event["body"]`, base64-decoded first when `isBase64Encoded`; JSON object with
      string `class_name` (1–200 characters) and string `photo_base64`. Invalid JSON, a
      missing or wrong-typed field → 400 `BAD_REQUEST_ERROR` (or, for the class, 400
      `NOT_IN_LIST_ERROR`).
   2. If `len(photo_base64) > 4 * ceil(MAX_PHOTO_BYTES / 3) + 16` → 400 with the size
      message for the length it implies, without decoding. Else
      `base64.b64decode(photo_base64, validate=True)`; `binascii.Error` → 400
      `BAD_REQUEST_ERROR`.
   3. `photo_checks.check_photo(data)` → message → 400 `{"error": message}`. Nothing else
      runs (no Neon, no GitHub).
   4. Class list from Neon as in step 4 (502 `NEON_ERROR` on failure). `class_name` not in
      the list → 400 `NOT_IN_LIST_ERROR`. `file_name_problem(class_name)` → 400 with that
      message.
   5. Configuration: `RepoConfig.from_dict(aws.get_json_parameter(CLASS_PHOTO_CONFIG_PARAM_NAME))`;
      App secret: `aws.get_secret_json(GITHUB_APP_SECRET_NAME)` with string keys `app_id`,
      `installation_id`, `private_key`. Any failure or missing key → log the key name or
      error class, 500 `GENERIC_ERROR`.
   6. `token = github_app.installation_token(app_id, installation_id, private_key,
      config.repo, permissions)`, with `permissions = {"contents": "read",
      "pull_requests": "read"}` when `dry_run`, else `{"contents": "write",
      "pull_requests": "write"}`. `repo = GitHubRepo(token, config.owner, config.repo,
      config.branch_prefix)`.
   7. `plan = submission.plan_submission(repo, config, class_name, classes, username)`;
      `result = submission.dry_run_result(plan)` when `dry_run`, else
      `submission.apply_submission(repo, config, plan, base64.b64encode(data).decode("ascii"), username)`.
   8. `GitHubError` → 502 `GITHUB_ERROR`; `SubmissionConflict` → 409 `CONFLICT_ERROR`.
   9. 200:
      ```json
      {"dry_run": false, "action": "opened",
       "pull_request": {"number": 12, "url": "https://github.com/asmbly-makerspace/asmbly-classes/pull/12"},
       "file_path": "app/src/lib/images/....jpg", "replaces_existing": true,
       "removed_paths": ["..."], "title": "...", "body": "...", "warnings": ["..."]}
      ```
6. **Responses** are JSON with `Content-Type: application/json; charset=utf-8` and
   `Cache-Control: no-store`. No response carries exception text.
7. **Logs:** route, `sub`, class name, the kind of check that failed (`size`, `not_jpeg`,
   `ratio`, `location`, ...), action, pull request number, branch. Never the username, the
   `Authorization` header, the body, the photo, the token or the key.

Type hints on every function; lazy logging; only the imports used; helper modules
imported as modules (`from common import aws, github_app` and `from . import ...` or
absolute `functions.classes.class_photo_upload_api...` imports. No existing function
imports a sibling module: under Lambda the handler is the top-level `lambda_function`,
so `from . import class_names` fails there, and under pytest a bare `import class_names`
fails. Settle it (a relative import with an absolute fallback, or a `conftest.py`
`sys.path` entry) and test it; see phase 1's Hand-off). Call `search_events` with a
`timeout` and page limit that keep the Neon search well inside API Gateway's 29 s.

## Tests

`tests/test_lambda_function.py` (patch where used:
`functions.classes.class_photo_upload_api.lambda_function.aws`, `.NeonCRM`,
`.github_app`, `.submission` as needed; real `photo_checks` and `class_names`; images
from `jpeg_builder`):

- `test_missing_env_returns_500` (parametrized over `REQUIRED_ENV`), body has no
  variable value.
- `test_wrong_audience_returns_403_and_calls_nothing`, `test_access_token_returns_403`,
  `test_missing_claims_returns_403`: no secret read, no Neon, no GitHub.
- `test_unknown_route_returns_404`.
- `test_classes_returns_names_problems_and_warnings`: Neon mock returns events incl.
  `"AC/DC Basics w/ X"`, `"A-B Basics"`, `"A B Basics"`; asserts the payload and
  `dry_run`.
- `test_classes_neon_failure_returns_502_without_details` (`NeonCRMError("events/search
  failed (status 500)")`): exact `NEON_ERROR`, "500" not in body.
- `test_classes_secret_failure_returns_502`.
- `test_submit_invalid_json_400`, `test_submit_missing_fields_400`,
  `test_submit_bad_base64_400`, `test_submit_base64_encoded_event_body`.
- `test_submit_oversized_refused_before_decode`: a 6 MB string gets the size message and
  `b64decode` is never called (patch and assert).
- `test_submit_bad_photo_400_and_nothing_called` (parametrized: PNG, 4:3, portrait,
  orientation 6, EXIF GPS, XMP GPS): the phase 2 message; Neon and GitHub mocks not
  called.
- `test_submit_class_not_in_list_400`, `test_submit_forbidden_character_400`.
- `test_submit_prod_opens_pull_request`: `CLASS_PHOTO_DRY_RUN=false`;
  `installation_token` called with `repository="asmbly-classes"` and write permissions;
  `apply_submission` called with the re-encoded photo and username; 200 with `action:
  "opened"` and the URL.
- `test_submit_prod_repeat_returns_updated`.
- `test_submit_dry_run_uses_read_only_token_and_never_applies`: `CLASS_PHOTO_DRY_RUN=true`;
  permissions read-only; `apply_submission` not called; `dry_run: true`, `action:
  "would_open"`, the plan's file path, removed paths, title and body.
- `test_dry_run_is_default` (env unset, `""`, `"TRUE"`, `"no"`): all dry runs.
- `test_submit_github_error_502_without_details`, `test_submit_conflict_409`.
- `test_github_secret_missing_key_500`: the log names `private_key`; the body is
  `GENERIC_ERROR`.
- `test_logs_hold_no_username_token_or_photo` (caplog over a full prod submission): the
  username, a marker inside the fake key, the fake token and a slice of the base64 are
  absent.

`tests/test_templates.py`:

- `test_class_photo_data_routes_require_the_staff_authorizer`: in `template.yaml`, both
  `/class-photo-upload/classes` (get) and `/class-photo-upload/submit` (post) have
  `security: [{StaffCognitoAuthorizer: []}]`, and the scheme's type is
  `cognito_user_pools`.

## Acceptance criteria

1. `template.yaml` routes `GET /class-photo-upload/classes` and `POST
   /class-photo-upload/submit` to `ClassPhotoUploadApiFunction-${Stage}`, both behind
   `StaffCognitoAuthorizer` on the staff pool. (#104 AC3)
2. A token for another app client or an access token gets 403 and nothing runs; no token
   gets 401 from API Gateway. (#104 AC3)
3. The class list answers names, file names, problems and warnings; a Neon failure
   answers 502 "Couldn't load the class list. Try again in a minute." with no details.
   (#104 AC2, AC4, AC6)
4. A failing photo answers 400 with phase 2's message and nothing reaches Neon or
   GitHub. (#105 AC6, #106 AC4)
5. On prod the submit opens or updates the pull request (phase 4); on stage
   (`CLASS_PHOTO_DRY_RUN` is `'true'` unless `Stage` is `prod`) it returns the plan, with a
   read-only installation token. (#107, #108, #109 AC1–AC4)
6. GitHub failures answer 502 with the plain message; a lost race answers 409. (#107 AC7)
7. The function reads only `/${Stage}/config/class-photo-upload`, the Neon secret and
   `github/class-photo-upload-app` (exact ARNs); its log group is
   `/asmbly/lambda/ClassPhotoUploadApiFunction-${Stage}` with 14-day retention; it has the
   `Project` tag.
8. Both deploy-role policies list the function, its log group and its SSM parameter; the
   shared read lists the two Cognito parameters.
9. `pytest`, `cfn-lint`, `sam validate` and `sam build` pass.

## Verification

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

(`sam build` here builds without a container and pip-installs `PyJWT[crypto]` for the
function; the deploy workflows use `--use-container`.)

On stage, after the admin actions 1–3 and the deploy:

- `curl -i <stage FacilitiesApiUrl>/class-photo-upload/classes` → 401.
- Sign in through the hosted UI for the app client (or wait for phase 6's page), then
  `curl -H "Authorization: <id token>" <stage URL>/class-photo-upload/classes` → 200 with
  `dry_run: true` and the classes.
- POST a small 3:2 JPEG for a class → 200, `dry_run: true`, `action: would_open` (or
  `would_update`), the file name and removals; nothing appears on `asmbly-classes`.
- `aws logs tail /asmbly/lambda/ClassPhotoUploadApiFunction-stage` shows `sub`s and class
  names, no usernames or tokens.

## Admin actions

- README admin actions 1 and 2, **before this reaches `stage`**: the
  `/config/cognito/staff/user-pool-id` and `/config/cognito/staff/class-photo-app-client-id`
  SSM parameters, and the deploy-role redeploy
  (`AsmblyFacilitiesMaintTrackingStack-cicd`, docs/Deploying.md "CI/CD Infrastructure
  (The Deployer Role)"). Without them the stage deploy fails.
- README admin actions 3–5 before stage testing (app client; GitHub App and its secret
  `github/class-photo-upload-app`). Without the secret, a submit answers 500 and logs
  the reason.

## Hand-off

- Routes: `GET /class-photo-upload/classes`, `POST /class-photo-upload/submit`, with the
  request and response shapes above; `Authorization: <Cognito ID token>`.
- `templates/classes.yaml` exists with `IsProd`, the parameters above and the output
  `ClassPhotoUploadApiFunctionArn`; `template.yaml` passes
  `ClassPhotoAppClientId` into it.
- The error strings in `lambda_function.py`, for the page to show as given.
