# How to Contribute & Deploy to Asmbly Facilities, Maintenance, and Tracking Automation

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Workflow](#deployment-workflow)
- [Adding a New Lambda Function](#adding-a-new-lambda-function)


## Prerequisites

You'll need the following installed and configured on your machine:

1.  **AWS CLI:** [Installation Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
2.  **AWS SAM CLI:** [Installation Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
3.  **Docker:** Required by SAM for building and local testing. [Get Docker](https://www.docker.com/products/docker-desktop/)

## Deployment Workflow

Making changes and deploying them is a straightforward process.

1.  **Make Code Changes:** Edit the Python code for a function inside the `/functions` directory.
2.  **Update Template (if needed):** If you are changing any infrastructure (e.g., adding an environment variable), edit the `template.yaml` file.
3.  **Build the Project:** From the root directory, run the build command. This packages your code and dependencies.
    ```bash
    sam build
    ```
4.  **Deploy to AWS:** Deploy the packaged application to the cloud.
    ```bash
    sam deploy
    ```
    *Note: The first time you deploy, you should use `sam deploy --guided` to walk through the initial stack setup.*
