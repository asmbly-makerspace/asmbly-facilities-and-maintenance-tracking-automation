# How to Contribute & Deploy to Asmbly Facilities, Maintenance, and Tracking Automation

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [CI/CD Infrastructure (The Deployer Role)](#cicd-infrastructure-the-deployer-role)
- [One-Time Admin Setup: Class Photo Upload](#one-time-admin-setup-class-photo-upload)
- [Automated Production Deployment (via GitHub Actions)](#automated-production-deployment-via-github-actions)
- [Manual Deployment (for Dev & Stage)](#manual-deployment-for-dev--stage)

## Prerequisites

You'll need the following installed and configured on your machine:

1.  **AWS CLI:** [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
2.  **AWS SAM CLI:** [Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
3.  **Docker:** Required by SAM for building and local testing. [Get Docker](https://www.docker.com/products/docker-desktop/)

## Architecture Overview

This project uses a **multi-stack architecture**. The root `template.yaml` file acts as a container for several nested stacks, each representing a logical part of the application (e.g., `CeramicsStack`, `PurchaseRequestStack`).

Each nested stack is defined in its own template file within the `/templates` directory. This structure helps organize resources and allows for independent deployments of different parts of the application.

`template.yaml` reads these shared SSM parameters (us-east-2) whenever any stage deploys; they are created by hand, not by a stack, and a missing one fails the deploy: `/config/route53/asmbly/hosted-zone-id`, and the staff sign-in pool's `/config/cognito/staff/user-pool-id`, `/config/cognito/staff/auth-domain` and `/config/cognito/staff/class-photo-app-client-id` (the pool is owned by AsmblyMCPs).

## CI/CD Infrastructure (The Deployer Role)

Before the application can be deployed, the **deployer itself** must exist. This infrastructure is defined in `template-cicd.yaml`.

* **What it is:** This template defines the `GitHub-OIDC-facilities-automation-deploy` role and its exact, least-privilege IAM policy. This is the role that GitHub Actions assumes to deploy the main application.
* **Why it's separate:** It separates the "application" (`template.yaml`) from the "deployer" (`template-cicd.yaml`). This is a critical security practice.

### What the Deployer Role Can Do

The account is shared with other Asmbly projects, so the role is locked down to this project:

* **Who can assume it:** only the two deploy jobs, identified by their GitHub environment. The trust policy accepts exactly these OIDC subjects (with audience `sts.amazonaws.com`):
    * `repo:asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation:environment:stage` (`deploy-staging.yml`, `stage` branch)
    * `repo:asmbly-makerspace/asmbly-facilities-and-maintenance-tracking-automation:environment:prod` (`deploy.yml`, `main` branch)

    Workflows on other branches, and jobs without one of these `environment:` values, cannot get credentials. The subject names the environment, not the branch, so the `stage` and `prod` GitHub environments must be limited to their branch (**Settings → Environments → Deployment branches and tags**).
* **What it can touch:** only the `AsmblyFacilitiesMaintTrackingStack-stage` and `-prod` stacks (and their nested stacks) and the resources they create, listed **by name** in the policies. Dev is deployed by hand and is not covered. There are five managed policies, all attached to the role:

    | Logical ID (`template-cicd.yaml`) | Policy name | What it covers |
    | --- | --- | --- |
    | `GitHubDeployPolicy` | `GitHub-OIDC-facilities-automation-deploy-policy` | Resources shared by both stages: generated IAM role names, the FacilitiesApi REST APIs, the `facilities.asmbly.org` domain, certificate and DNS records, reads of the shared `/config/...` SSM parameters the templates resolve, and a read-only `cognito-idp:DescribeUserPool` on the staff sign-in pool behind the API's Cognito authorizer. |
    | `GitHubDeployPolicystage` / `GitHubDeployPolicyprod` | `GitHub-OIDC-facilities-automation-deploy-{stage,prod}-policy` | Per stage: the stage's CloudFormation stacks, SAM artifacts, Lambda functions and layers, and log groups. |
    | `GitHubDeployPolicystageData` / `GitHubDeployPolicyprodData` | `GitHub-OIDC-facilities-automation-deploy-{stage,prod}-data-policy` | Per stage: the stage's DynamoDB tables, SSM parameters and EventBridge rules. |

    The stage and prod policies are identical apart from the stage name, except that only `GitHubDeployPolicyprodData` has the `class-photo-class-list-refresh-prod` rule (stage has no such rule).
* **Size limit:** IAM caps each managed policy at **6,144 characters**, not counting whitespace, and refuses a bigger one only when the admin deploys this stack (`Cannot exceed quota for PolicySize: 6144`, `ServiceLimitExceeded`; the stack rolls back). That is why each stage has two policies. `tests/test_templates.py` renders every policy in `template-cicd.yaml` with realistic values and fails when one is over 5,800 characters, so the `test` check catches it first. When it fails, move a cohesive group of statements into a new policy with a new logical ID and name, and add it to the role's `ManagedPolicyArns`. Don't rename an existing policy or change its `Description` (see step 4 below).

### How to Manage the Deployer Role

This stack (`AsmblyFacilitiesMaintTrackingStack-cicd`) is **NEVER** deployed by GitHub Actions. It is **ONLY** deployed manually from your local machine using administrator credentials.

**You will touch this file when a deployment fails with a permissions error.** Because permissions are granted per resource name, this includes **adding a new named resource** (a new Lambda function, log group, SSM parameter, table, rule, and so on), not just a new kind of resource.

For example, if you add a function `FooFunction-${Stage}` with a log group `/asmbly/lambda/FooFunction-${Stage}`, add both names to **both** `GitHubDeployPolicystage` and `GitHubDeployPolicyprod`. A new DynamoDB table, SSM parameter or EventBridge rule goes in **both** `GitHubDeployPolicystageData` and `GitHubDeployPolicyprodData` instead. If you add an SQS queue and the `prod` deploy fails with `is not authorized to perform: sqs:CreateQueue`, add `sqs:CreateQueue` scoped to that queue's ARN. Never use `Resource: "*"` unless the action does not support resource-level permissions.

1.  **Edit `template-cicd.yaml`.**
2.  **Look up the REST API IDs.** Each is the physical ID of the stack's `FacilitiesApi` resource (run it once for `-stage` and once for `-prod`):
    ```bash
    aws cloudformation describe-stack-resource --stack-name AsmblyFacilitiesMaintTrackingStack-stage --region us-east-2 \
      --logical-resource-id FacilitiesApi --query StackResourceDetail.PhysicalResourceId --output text
    ```
    The same ID is the host prefix of the stack's `FacilitiesApiUrl` output (`https://<id>.execute-api.us-east-2.amazonaws.com/<stage>`).
3.  **Check the shared SSM parameters exist.** The template reads `/config/route53/asmbly/hosted-zone-id` and `/config/cognito/staff/user-pool-id` (the staff sign-in pool's ID, owned by AsmblyMCPs) when it deploys; a missing one fails the deploy.
4.  **Deploy the CICD stack** from your local machine:
    ```bash
    sam deploy --template-file template-cicd.yaml --stack-name AsmblyFacilitiesMaintTrackingStack-cicd \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND --region us-east-2 \
      --parameter-overrides StageRestApiId=<stage id> ProdRestApiId=<prod id>
    ```
    Add `--no-execute-changeset` first to preview the changes, and check that nothing shows `Replacement: True` (for example, changing a managed policy's `Description` replaces it, which fails because the policy has a fixed name). A new policy shows as `Add` and the role and the existing policies as `Modify`, which is expected.
    `CAPABILITY_AUTO_EXPAND` is required because the template uses the `AWS::LanguageExtensions` and SAM transforms.
5.  **Re-run** the failed GitHub Actions job.

If the FacilitiesApi REST API is ever replaced (new ID), or a stack is created from scratch, redeploy this stack with the new ID first; the role cannot create new REST APIs.

## One-Time Admin Setup: Class Photo Upload

The [Class Photo Upload](README.md#classes) service (`ClassPhotoUploadPageFunction`, `ClassPhotoUploadApiFunction`) needs four things that live outside this repository. An admin does them once, **in this order**, before the change that adds the service reaches `stage`: steps 1 and 2 must exist before the deploy role is redeployed (step 4), and the `stage` deploy fails until all four are done. Everything is in us-east-2. The names below are the exact names the templates and the code read; don't change them.

| What | Exact name | Read by |
| --- | --- | --- |
| Cognito app client | `class-photo-upload`, in the staff sign-in pool (AsmblyMCPs) | The page's sign-in; its ID is the ID token's `aud` the API function checks |
| SSM parameter (String) | `/config/cognito/staff/user-pool-id` | `template.yaml` (`StaffUserPoolId`, the `StaffCognitoAuthorizer`) and `template-cicd.yaml` |
| SSM parameter (String) | `/config/cognito/staff/auth-domain` | `template.yaml` (`StaffAuthDomain`) → `STAFF_AUTH_DOMAIN` |
| SSM parameter (String) | `/config/cognito/staff/class-photo-app-client-id` | `template.yaml` (`ClassPhotoAppClientId`) → `CLASS_PHOTO_APP_CLIENT_ID` |
| GitHub App | `Asmbly Class Photos Upload` (slug `asmbly-class-photos-upload`), owned by `asmbly-makerspace`, installed on `asmbly-classes` only | The API function, through `common.github_app` |
| Secrets Manager secret | `github/class-photo-upload-app` | `template.yaml` (`ClassPhotoGitHubAppSecretName`) → `GITHUB_APP_SECRET_NAME` |
| Deploy role stack | `AsmblyFacilitiesMaintTrackingStack-cicd` | GitHub Actions |

Both stages share the app client, the three `/config/cognito/staff/*` parameters, the App and the secret. Stage is a dry run: it asks GitHub for a read-only token and opens nothing.

### Step 1: The Cognito app client and the `/config/cognito/staff/*` parameters

The staff sign-in pool belongs to the AsmblyMCPs project. If that project defines its app clients in its own template, add the client there instead of in the console, so its stack doesn't drift.

1.  **Find the stage page address.** It is the stage stack's `FacilitiesApiUrl` output plus `/class-photo-upload`:
    ```bash
    aws cloudformation describe-stacks --stack-name AsmblyFacilitiesMaintTrackingStack-stage --region us-east-2 \
      --query "Stacks[0].Outputs[?OutputKey=='FacilitiesApiUrl'].OutputValue" --output text
    ```
    This prints `https://<stage id>.execute-api.us-east-2.amazonaws.com/stage`, so the stage page is `https://<stage id>.execute-api.us-east-2.amazonaws.com/stage/class-photo-upload`. The prod page is `https://facilities.asmbly.org/class-photo-upload`.
2.  **Create the app client.** In the AWS console (us-east-2): **Amazon Cognito → User pools →** the staff pool **→ App clients → Create app client**:
    * Application type: **Public client** (single-page application). **No client secret.**
    * App client name: `class-photo-upload`.
    * Allowed callback URLs: both page addresses from step 1.
    * Allowed sign-out URLs: the same two addresses.
    * Identity provider: **Cognito user pool**.
    * OAuth 2.0 grant type: **Authorization code grant** only (the page uses PKCE).
    * OpenID Connect scopes: **openid**.
3.  **Note three values:**
    * the pool's **User pool ID** (for example `us-east-2_AbCdEf123`), on the pool's overview;
    * the new client's **Client ID**, on its page;
    * the pool's hosted sign-in **domain**, under the pool's **Domain** settings, as a host name only: no `https://` and no trailing `/` (for example `asmbly-staff.auth.us-east-2.amazoncognito.com`). The template refuses any other form.
4.  **Create the three SSM parameters.** They are plain `String` parameters (the templates can't read a `SecureString` this way). Skip any that already exist with the right value:
    ```bash
    aws ssm put-parameter --region us-east-2 --type String \
      --name /config/cognito/staff/user-pool-id --value '<user pool id>'
    aws ssm put-parameter --region us-east-2 --type String \
      --name /config/cognito/staff/auth-domain --value '<domain host, no https://>'
    aws ssm put-parameter --region us-east-2 --type String \
      --name /config/cognito/staff/class-photo-app-client-id --value '<client id>'
    ```
    To change one later, add `--overwrite` and redeploy the application (the value is read at deploy time).

If the stage `FacilitiesApi` is ever replaced (new ID), add its new page address to the app client's callback and sign-out URLs.

### Step 2: The GitHub App "Asmbly Class Photos Upload"

A GitHub **organization owner** of `asmbly-makerspace` does this.

1.  **Create the App.** On GitHub: **`asmbly-makerspace` organization → Settings → Developer settings → GitHub Apps → New GitHub App** (`https://github.com/organizations/asmbly-makerspace/settings/apps/new`):
    * GitHub App name: `Asmbly Class Photos Upload`.
    * Homepage URL: `https://facilities.asmbly.org/class-photo-upload`.
    * Callback URL, "Request user authorization (OAuth) during installation", "Setup URL": leave empty and unchecked.
    * **Webhook:** uncheck **Active**.
    * **Repository permissions:** **Contents: Read and write**, **Pull requests: Read and write**, **Metadata: Read-only** (GitHub selects it by itself). Leave every other repository permission at **No access**.
    * **Organization permissions** and **Account permissions:** none.
    * **Where can this GitHub App be installed?** **Only on this account.**
    * Click **Create GitHub App**.
2.  **Note the App ID.** It is under **About** on the App's settings page (`https://github.com/organizations/asmbly-makerspace/settings/apps/asmbly-class-photos-upload`).
3.  **Generate the private key.** On the same page, under **Private keys**, click **Generate a private key**. The browser downloads a `.pem` file (for example `asmbly-class-photos-upload.<date>.private-key.pem`). Keep it only until step 3 is done.
4.  **Install it on `asmbly-classes` only.** In the App's settings, **Install App → Install** next to `asmbly-makerspace`, choose **Only select repositories**, pick **`asmbly-classes`**, and click **Install**.
5.  **Note the installation ID.** After installing, GitHub opens the installation's settings page, `https://github.com/organizations/asmbly-makerspace/settings/installations/<installation id>`. The number at the end of that address is the installation ID. (Later: **organization Settings → GitHub Apps → Asmbly Class Photos Upload → Configure** opens the same page.)

The function never needs more than this: every request asks for a token limited to `asmbly-classes` and to the permissions it needs (read-only on stage).

### Step 3: The Secrets Manager secret `github/class-photo-upload-app`

The secret is a JSON object with exactly three keys, and all three values must be **strings** (a number for `app_id` or `installation_id` is refused, and a submission answers 500 with the missing key's name in the log):

```json
{
  "app_id": "1234567",
  "installation_id": "87654321",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----\n"
}
```

`private_key` is the whole `.pem` file, with its line breaks written as `\n`. This command builds the JSON with the right escaping (it needs `jq`); run it from the folder that holds the `.pem`, with your values in place of the examples:

```bash
aws secretsmanager create-secret --region us-east-2 --name github/class-photo-upload-app \
  --description "Asmbly Class Photos Upload GitHub App credentials (class photo upload)" \
  --secret-string "$(jq -n --arg app_id 1234567 --arg installation_id 87654321 \
    --rawfile private_key ./asmbly-class-photos-upload.<date>.private-key.pem \
    '{app_id: $app_id, installation_id: $installation_id, private_key: $private_key}')"
```

Then delete the local `.pem`. Check the secret's keys without printing the key:

```bash
aws secretsmanager get-secret-value --region us-east-2 --secret-id github/class-photo-upload-app \
  --query SecretString --output text | jq 'keys'
```

It should print `["app_id", "installation_id", "private_key"]`.

To rotate the key: generate a new one on the App's page, store it with the same `jq` command but `aws secretsmanager put-secret-value --region us-east-2 --secret-id github/class-photo-upload-app --secret-string "$(...)"`, then delete the old key on GitHub. The function reads the secret on every submission, so no redeploy is needed.

### Step 4: Redeploy the deploy role

The change adds `ClassPhotoUploadApiFunction-{stage,prod}`, `ClassPhotoUploadPageFunction-{stage,prod}`, their log groups `/asmbly/lambda/ClassPhotoUpload{Api,Page}Function-{stage,prod}`, the SSM parameters `/{stage,prod}/config/class-photo-upload`, reads of the three `/config/cognito/staff/*` parameters, and `cognito-idp:DescribeUserPool` on the staff pool to `template-cicd.yaml`. The role must have them before the `stage` deploy runs.

1.  Check that step 1's parameters exist (the deploy role's template reads `/config/cognito/staff/user-pool-id` itself):
    ```bash
    aws ssm get-parameters --region us-east-2 --query "{found: Parameters[].Name, missing: InvalidParameters}" \
      --names /config/route53/asmbly/hosted-zone-id /config/cognito/staff/user-pool-id \
        /config/cognito/staff/auth-domain /config/cognito/staff/class-photo-app-client-id
    ```
    `missing` must be empty.
2.  From the branch that holds the change, follow [How to Manage the Deployer Role](#how-to-manage-the-deployer-role), steps 2 to 4: look up both REST API IDs, preview with `--no-execute-changeset`, check nothing shows `Replacement: True`, then deploy `AsmblyFacilitiesMaintTrackingStack-cicd`.
3.  Merge the pull request to `stage`, or re-run its failed deploy. After the `stage` deploy, open the stage page address from step 1, sign in, and submit a photo: the answer says "Dry run" and nothing is opened on `asmbly-classes`.

The class list cache (epic #114) later added the DynamoDB table `ClassPhotoClassListCache-{stage,prod}` to both deploy policies (with the `Describe…`, `GetResourcePolicy` and `ListTagsOfResource` reads CloudFormation's table handler makes, on that table only), and the EventBridge rule `class-photo-class-list-refresh-prod` (with its tagging and `ListTargetsByRule`) to the prod policy only, because stage has no scheduled refresh. Redeploy the role as in item 2 before that change reaches `stage`. Nothing else needs setting up: the cache fills itself on the first visit.

To stop new pull requests at once (for example if the key leaks), suspend the App or uninstall it from `asmbly-classes`, then rotate the key as in step 3.

## Automated Production Deployment (via GitHub Actions)

The `prod` environment is deployed automatically. **Any push or merge to the `main` branch will trigger the `Deploy Production Pipeline` workflow** (`.github/workflows/deploy.yml`).

The `stage` environment is deployed the same way: **any push or merge to the `stage` branch triggers the `Deploy Staging Pipeline` workflow** (`.github/workflows/deploy-staging.yml`).

Both workflows authenticate with AWS by assuming the `GitHub-OIDC-facilities-automation-deploy` role (which is managed by our `template-cicd.yaml` stack).

You should not need to deploy to `prod` manually.

### The Deployment Pipeline

Each workflow has one job, **Deploy to AWS**:

* It builds the SAM application inside a Docker container that mimics the Lambda environment.
* It deploys all the AWS resources defined in the templates to its environment.
* It reads the API's URL from the stack outputs.

Slack, ClickUp and the other services call the permanent `https://facilities.asmbly.org` address, so nothing has to be updated after a prod deploy. (`scripts/update_slack_manifest.py` is no longer run by a workflow.)

## Manual Deployment (for Dev & Stage)

Before deploying manually, you must build the project from the **root directory**. The `sam build` command processes all templates (root and nested) and prepares the code and dependencies for deployment.

```bash
sam build
```

This command only needs to be run once, even if you plan to deploy individual stacks.

### Manual Deployment Workflow

This project is configured to deploy to multiple stages (e.g., `dev`, `stage`, `prod`). The deployment process uses the AWS SAM CLI.

The `samconfig.toml` file is pre-configured for `dev`, `stage`, and `prod` environments. The `--config-env` flag selects the appropriate configuration for deployment, including the target AWS account and region.

### Environment Strategy

Each environment serves a specific purpose in our development lifecycle. `stage` and `prod` are deployed by the workflows when their branches change, so manual deployments are for `dev`.

* **`dev` (Development)**
    * **Purpose:** The `dev` environment is for active development and rapid iteration.
    * **Expectations:** This environment is considered fragile and may be unstable due to frequent deployments of work-in-progress features. Deploy here often.

* **`stage` (Staging)**
    * **Purpose:** `stage` is a pre-production environment that mirrors `prod` as closely as possible. It is used to verify that features are working correctly and to conduct final testing before a production release.
    * **Expectations:** This environment should be stable. It is deployed from the `stage` branch, so a change reaches it when its pull request merges, which should only happen when the feature is complete and has passed all tests.

* **`prod` (Production)**
    * **Purpose:** This is the live environment used by end-users.
    * **Expectations:** Deployments to `prod` are the most critical. Code should only be deployed to production after it has been thoroughly verified in `stage`, all automated tests are passing, and manual workflow tests have been completed. **Do not deploy to `prod` if there is any risk of breaking existing functionality.**

### Deploying All Stacks Manually

To deploy the entire application, including all nested stacks, run the `sam deploy` command from the root directory without specifying a stack.

**Deploy all stacks to the `dev` environment:**
```bash
sam deploy --config-env dev
```

### Deploying a Sindle Stack

To deploy only a specific part of the application (e.g., after making a change to a single function), you can target its logical stack ID. This is much faster than deploying the entire application.

To do this, append the **logical ID** of the stack (as defined in the root `template.yaml`) to the `sam deploy` command.

**Example: Deploy only the `CeramicsStack` to the `dev` environment:**
```bash
sam deploy --config-env dev CeramicsStack
```

**Example: Deploy only the `PurchaseRequestStack` to the `prod` environment:**
```bash
sam deploy --config-env prod PurchaseRequestStack
```

> **Important:** Always run `sam deploy` from the root of the project, regardless of whether you are deploying the entire application or a single stack.

SAM will show you the changes to be made and ask for confirmation before applying them to your AWS account.