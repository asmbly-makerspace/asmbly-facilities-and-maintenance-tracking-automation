# How to Contribute & Deploy to Asmbly Facilities, Maintenance, and Tracking Automation

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Building the Project](#building-the-project)
- [Deployment Workflow](#deployment-workflow)

## Prerequisites

You'll need the following installed and configured on your machine:

1.  **AWS CLI:** [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
2.  **AWS SAM CLI:** [Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
3.  **Docker:** Required by SAM for building and local testing. [Get Docker](https://www.docker.com/products/docker-desktop/)

## Architecture Overview

This project uses a **multi-stack architecture**. The root `template.yaml` file acts as a container for several nested stacks, each representing a logical part of the application (e.g., `CeramicsStack`, `PurchaseRequestStack`).

Each nested stack is defined in its own template file within the `/templates` directory. This structure helps organize resources and allows for independent deployments of different parts of the application.

The logical IDs for the stacks are defined in the root `template.yaml` file:
*   `FacilitiesStack`
*   `PurchaseRequestStack`
*   `CeramicsStack`
*   `ProblemReportStack`

## Building the Project

Before deploying, you must build the project from the **root directory**. The `sam build` command processes all templates (root and nested) and prepares the code and dependencies for deployment.

```bash
sam build
```

This command only needs to be run once, even if you plan to deploy individual stacks.

## Deployment Workflow

This project is configured to deploy to multiple stages (e.g., `dev`, `stage`, `prod`). The deployment process uses the AWS SAM CLI.

The `samconfig.toml` file is pre-configured for `dev`, `stage`, and `prod` environments. The `--config-env` flag selects the appropriate configuration for deployment, including the target AWS account and region.

### Environment Strategy

Each environment serves a specific purpose in our development lifecycle.

*   **`dev` (Development)**
    *   **Purpose:** The `dev` environment is for active development and rapid iteration.
    *   **Expectations:** This environment is considered fragile and may be unstable due to frequent deployments of work-in-progress features. Deploy here often.

*   **`stage` (Staging)**
    *   **Purpose:** `stage` is a pre-production environment that mirrors `prod` as closely as possible. It is used to verify that features are working correctly and to conduct final testing before a production release.
    *   **Expectations:** This environment should be stable. Deployments to `stage` should only happen when a feature is complete and has passed all local tests.

*   **`prod` (Production)**
    *   **Purpose:** This is the live environment used by end-users.
    *   **Expectations:** Deployments to `prod` are the most critical. Code should only be deployed to production after it has been thoroughly verified in `stage`, all automated tests are passing, and manual workflow tests have been completed. **Do not deploy to `prod` if there is any risk of breaking existing functionality.**

### Deploying All Stacks

To deploy the entire application, including all nested stacks, run the `sam deploy` command from the root directory without specifying a stack.

**Deploy all stacks to the `dev` environment:**
```bash
sam deploy --config-env dev
```

### Deploying a Single Stack

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
