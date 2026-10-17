# How to Contribute & Deploy to Asmbly Facilities, Maintenance, and Tracking Automation

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [CI/CD Infrastructure (The Deployer Role)](#cicd-infrastructure-the-deployer-role)
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
* **What it can touch:** only the `AsmblyFacilitiesMaintTrackingStack-stage` and `-prod` stacks (and their nested stacks) and the resources they create, listed **by name** in the policy. Dev is deployed by hand and is not covered. There are three managed policies:
    * `GitHubDeployPolicy`: resources shared by both stages (generated IAM role names, the FacilitiesApi REST APIs, the `facilities.asmbly.org` domain, certificate and DNS records, reads of the shared `/config/...` SSM parameters the templates resolve, and a read-only `cognito-idp:DescribeUserPool` on the staff sign-in pool behind the API's Cognito authorizer).
    * `GitHubDeployPolicystage` / `GitHubDeployPolicyprod`: one per stage, identical apart from the stage name (Lambda functions and layers, log groups, SSM parameters, DynamoDB table, EventBridge rule, SAM artifacts).

### How to Manage the Deployer Role

This stack (`AsmblyFacilitiesMaintTrackingStack-cicd`) is **NEVER** deployed by GitHub Actions. It is **ONLY** deployed manually from your local machine using administrator credentials.

**You will touch this file when a deployment fails with a permissions error.** Because permissions are granted per resource name, this includes **adding a new named resource** (a new Lambda function, log group, SSM parameter, table, rule, and so on), not just a new kind of resource.

For example, if you add a function `FooFunction-${Stage}` with a log group `/asmbly/lambda/FooFunction-${Stage}`, add both names to **both** `GitHubDeployPolicystage` and `GitHubDeployPolicyprod`. If you add an SQS queue and the `prod` deploy fails with `is not authorized to perform: sqs:CreateQueue`, add `sqs:CreateQueue` scoped to that queue's ARN. Never use `Resource: "*"` unless the action does not support resource-level permissions.

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
    Add `--no-execute-changeset` first to preview the changes, and check that nothing shows `Replacement: True` (for example, changing a managed policy's `Description` replaces it, which fails because the policy has a fixed name).
    `CAPABILITY_AUTO_EXPAND` is required because the template uses the `AWS::LanguageExtensions` and SAM transforms.
5.  **Re-run** the failed GitHub Actions job.

If the FacilitiesApi REST API is ever replaced (new ID), or a stack is created from scratch, redeploy this stack with the new ID first; the role cannot create new REST APIs.

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