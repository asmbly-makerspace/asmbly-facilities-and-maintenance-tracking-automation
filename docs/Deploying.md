# How to Contribute & Deploy to Asmbly Facilities, Maintenance, and Tracking Automation

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Workflow](#deployment-workflow)


## Prerequisites

You'll need the following installed and configured on your machine:

1.  **AWS CLI:** [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
2.  **AWS SAM CLI:** [Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
3.  **Docker:** Required by SAM for building and local testing. [Get Docker](https://www.docker.com/products/docker-desktop/)

## Deployment Workflow

This project is configured to deploy to multiple stages (e.g., `dev`, `stage`, `prod`). The deployment process uses the AWS SAM CLI.

1.  **Make Code Changes:** Edit the Python code for a function inside the `/functions` directory.

2.  **Update Template (if needed):** If you are changing any infrastructure (e.g., adding an environment variable), edit the `template.yaml` file.

3.  **Build the Project:** From the root directory, run the build command. This packages your code and dependencies.
    ```bash
    sam build
    ```

4.  **Deploy to AWS:** Deploy the application to the desired environment using the `--config-env` flag. This command reads the deployment settings from the `samconfig.toml` file.

    The `samconfig.toml` file is pre-configured for `dev`, `stage`, and `prod` environments, each with a unique stack name to ensure they are deployed as separate, isolated applications.

    **Deploy to the `dev` environment:**
    ```bash
    sam deploy --config-env dev
    ```

    **Deploy to the `stage` environment:**
    ```bash
    sam deploy --config-env stage
    ```

    **Deploy to the `prod` environment:**
    ```bash
    sam deploy --config-env prod
    ```

    SAM will show you the changes to be made and ask for confirmation before applying them to your AWS account.
