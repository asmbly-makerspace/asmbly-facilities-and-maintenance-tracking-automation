# Facilities Slack Purchase Reorder

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)

## Purpose

This script is an automated bot designed to bridge the gap between team communication in Slack and purchasing tasks in ClickUp. Its primary purpose is to allow facilities team members to quickly create purchase/reorder requests from within Slack, which then automatically become tasks in ClickUp.

The ultimate goal of this tool is to streamline the purchasing process, improve tracking of requests, and save valuable time.

## How It Works

The bot functions as a serverless AWS Lambda function that is triggered by a Slack slash command.

### Components:

*   **Slack Slash Command:** A custom command in Slack that users can invoke.
*   **AWS API Gateway:** Provides a public URL (endpoint) that Slack sends requests to.
*   **AWS Lambda:** A serverless function that contains the Python logic to process the request.
*   **AWS Secrets Manager:** A secure storage service for the ClickUp and Slack API tokens.
*   **ClickUp API:** The official API for creating tasks.
*   **Slack API:** The official API for opening modals and sending messages back to the user.

### Visual Flow

```
+---------------+      +-----------------+      +---------------------+      +-----------------------+
| User's Slack  |      | AWS API Gateway |      | AWS Lambda Function |      | AWS Secrets Manager   |
|               |      | (Public URL)    |      | (Your Code)         |      | (API Keys)            |
+---------------+      +-----------------+      +---------------------+      +-----------------------+
        |                      |                       |                              |
(1) Invoke Slash Command ----> | (2) Send POST Request |                       |                              |
        |                      |---------------------->| (3) Trigger Function  |                              |
        |                      |                       |---------------------->| (4) Get Secrets        |
        |                      |                       |<----------------------| (5) Return Secrets     |
        |                      |                       |                              |
        |                      |                       | (6) Create ClickUp Task ----> [ClickUp API]
        |                      |                       |                              |
        |                      |                       |<--------------------------| (7) Return Task Data   |
        |                      |                       |                              |
        |                      |                       | (8) Post Confirmation Msg -> [Slack API]
        |                      |                       |                              |
|<-----------------------------------------------------| (9) Display Confirmation |                              |
        |                      |                       |                              |
```

### Step-by-Step Data Flow:

1.  **Invoke Slash Command**
    *   **Source:** User in Slack
    *   **Action:** The user types a slash command (e.g., `/reorder`) in a Slack channel.

2.  **Send POST Request**
    *   **Source:** Slack
    *   **Destination:** AWS API Gateway
    *   **Action:** Slack sends a POST request containing the command details to the API Gateway endpoint.

3.  **Trigger Lambda Function**
    *   **Source:** AWS API Gateway
    *   **Destination:** AWS Lambda
    *   **Action:** The incoming request to the API Gateway endpoint automatically triggers the Lambda function.

4.  **Fetch Secrets**
    *   **Source:** AWS Lambda
    *   **Destination:** AWS Secrets Manager
    *   **Action:** The function makes a secure, internal call to retrieve the ClickUp and Slack API tokens.

5.  **Create ClickUp Task**
    *   **Source:** AWS Lambda
    *   **Destination:** ClickUp API
    *   **Action:** The Lambda function makes a server-to-server API request to ClickUp to create a new task with the details from the Slack command.

6.  **Post Confirmation Message**
    *   **Source:** AWS Lambda
    *   **Destination:** Slack API
    *   **Action:** The function sends a formatted message back to the user in Slack, confirming that the task has been created and providing a link to it.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, secrets in Secrets Manager, an API Gateway endpoint, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name      | Value                      |
|-----------|----------------------------|
| Project   | facilities-purchase-reorder |
| Workspace | facilities                 |

## Configuration

All settings are managed via environment variables within the AWS Lambda function's configuration section. This allows for easy updates to things like the ClickUp List ID or bot name without changing the code.

## Testing

This function includes a suite of unit tests to ensure its logic is correct. The tests mock external dependencies (like AWS, ClickUp, and Slack APIs) so they can be run locally without needing credentials or making real API calls.

### Running Tests Locally

1.  **Navigate to the function directory:**
    ```bash
    cd functions/facilities_slack_purchase_reorder
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Install test dependencies:**
    ```bash
    pip install -r requirements-dev.txt
    ```

4.  **Run the tests using pytest:**
    ```bash
    pytest
    ```

    You should see output indicating that the tests have passed.

## Deployment

The deployment process is managed and specified in the [Deployment Instructions](/docs/Deploying.md).

## Usage

The URL is used in the Maintenance Slack App in Interactivity and in the `/reorder` slash command. 