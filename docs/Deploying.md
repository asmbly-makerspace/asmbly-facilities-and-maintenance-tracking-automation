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

## Adding a New Lambda Function

To add a new function to this project, follow these steps:

1.  **Create a New Function Folder:**
    * Inside the `/functions` directory, create a new folder for your function (e.g., `functions/my-new-function/`).

2.  **Write Your Lambda Code:**
    * Add your Python code to a file inside the new folder. By convention, this file is named `lambda_function.py`, and the main handler function is called `lambda_handler`.

3.  **Define the Function in `template.yaml`:**
    * Open the `template.yaml` file and add a new resource block for your function. You can copy and paste the structure of an existing function as a starting point.
    * Make sure to update the `CodeUri` property to point to your new folder (e.g., `CodeUri: functions/my-new-function/`).
    * Configure the function's `Properties`, including its trigger (`Events`), `Role`, `Environment` variables, and any `Layers` it needs.

4.  **Build and Deploy:**
    * Run `sam build` to package your new function.

    * Run `sam deploy` to deploy the changes. SAM will see the new function in your template and create it in AWS.
