# Contributing to Asmbly Facilities, Maintenance, and Tracking Automation

We're excited that you're interested in contributing! Your help is appreciated and will improve the project for everyone. This document provides guidelines to help make the contribution process easy and effective for everyone involved.

Following these guidelines helps maintain the quality of the project and respects the time of the developers reviewing your work.

## Table of Contents

- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Adding a New Lambda Function](#adding-a-new-lambda-function)

---

## How to Contribute

Our collaboration model is built on a clear development workflow. Before you begin, please take a moment to review our [**Branching Strategy**](Branching%20Strategy.md), as it outlines the core process we follow.

### The Contribution Workflow

1.  **Fork the Repository:**
    Start by forking the main repository to your own GitHub account.

2.  **Create a New Branch:**
    On your fork, create a new branch from the `main` branch. Please follow the branch naming conventions outlined in our strategy document.

    * For a new feature: `feature/your-feature-name`
    * For a bug fix: `fix/the-bug-you-are-fixing`
    * For documentation or other chores: `chore/update-readme`

    ```bash
    # From your local clone of your fork
    git checkout main
    git pull origin main
    git checkout -b feature/my-cool-new-automation
    ```

3.  **Make Your Changes:**
    Write your code, update documentation, or make any other necessary changes. If your changes affect the infrastructure (e.g., adding a new Lambda function, changing environment variables), remember that **all such changes must be made in the `template.yaml` file.**

4.  **Commit Your Work:**
    Commit your changes with clear and descriptive commit messages. A good commit message explains the "what" and "why" of your change.

    ```bash
    git add .
    git commit -m "feat: Add new function to monitor kiln temperatures"
    ```

5.  **Open a Pull Request (PR):**
    When your changes are ready, push your branch to your fork and open a Pull Request to the `main` branch of the main repository.

    A great Pull Request includes:
    * A clear, descriptive title.
    * A summary of the changes and why they are being made.
    * A link to any relevant issues (e.g., `Closes #123`).

6.  **Code Review:**
    Once your PR is submitted, it will be reviewed by at least one other collaborator. Be open to feedback and be prepared to make adjustments to your code based on the review. This process ensures we maintain a high standard of quality and consistency.

---

## Development Setup

To work on this project locally, you will need the following tools installed:

* [AWS CLI](https://aws.amazon.com/cli/)
* [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
* [Docker](https://www.docker.com/products/docker-desktop/)

For a guide on how to build and deploy the application, please see our [**Deploying.md**](Deploying.md) file.

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
    * Checkout [Deploying.md](Deploying.md) for details.