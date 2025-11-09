# Facilities Slack Problem Report Reaction Webhook

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)

## Purpose

This script is an automated bot designed to bridge the gap between team communication in Slack and task management in ClickUp for facility problem reports. Its primary purpose is to allow facilities team members to update the status of problem reports from within Slack using an emoji reaction, which then automatically updates the corresponding task in ClickUp.

The ultimate goal of this tool is to streamline the problem report lifecycle, improve tracking of issues, and save valuable time.

## How It Works

The bot functions as a serverless AWS Lambda function that is triggered by a Slack `reaction_added` event.

### Components:

*   **Slack Event Subscription:** A custom subscription in Slack that listens for `reaction_added` events.
*   **AWS API Gateway:** Provides a public URL (endpoint) that Slack sends requests to.
*   **AWS Lambda:** A serverless function that contains the Python logic to process the request.
*   **AWS Secrets Manager:** A secure storage service for the ClickUp and Slack API tokens.
*   **ClickUp API:** The official API for updating tasks.
*   **Slack API:** The official API for fetching message history and sending messages back to the user.

### Visual Flow

```
+---------------+      +-----------------+      +---------------------+      +-----------------------+
| User's Slack  |      | AWS API Gateway |      | AWS Lambda Function |      | AWS Secrets Manager   |
| (Adds React)  |      | (Public URL)    |      | (Your Code)         |      | (API Keys)            |
+---------------+      +-----------------+      +---------------------+      +-----------------------+
        |                      |                       |                              |
(1) Add Reaction  -----------> | (2) Send POST Request |                       |                              |
        |                      |---------------------->| (3) Trigger Function  |                              |
        |                      |                       |---------------------->| (4) Get Secrets        |
        |                      |                       |<----------------------| (5) Return Secrets     |
        |                      |                       |                              |
        |                      |                       | (6) Get Slack Message ----> [Slack API]
        |                      |                       |<------------------------| (7) Return Message     |
        |                      |                       |                              |
        |                      |                       | (8) Update ClickUp Task ---> [ClickUp API]
        |                      |                       |                              |
        |                      |                       |<--------------------------| (9) Return Task Data   |
        |                      |                       |                              |
        |                      |                       | (10) Post Confirmation Msg -> [Slack API]
        |                      |                       |                              |
|<-----------------------------------------------------| (11) Display Confirmation|                              |
        |                      |                       |                              |
```

### Step-by-Step Data Flow:

1.  **Add Reaction**
    *   **Source:** User in Slack
    *   **Action:** The user adds a specific emoji reaction (e.g., `:eyes:`) to a message containing a ClickUp task link for a problem report. The mapping of emojis to statuses is defined in a configuration file.

2.  **Send POST Request**
    *   **Source:** Slack
    *   **Destination:** AWS API Gateway
    *   **Action:** Slack sends a POST request containing the event details (including the reaction emoji) to the API Gateway endpoint.

3.  **Trigger Lambda Function**
    *   **Source:** AWS API Gateway
    *   **Destination:** AWS Lambda
    *   **Action:** The incoming request to the API Gateway endpoint automatically triggers the Lambda function.

4.  **Fetch Secrets & Config**
    *   **Source:** AWS Lambda
    *   **Destination:** AWS Secrets Manager
    *   **Action:** The function makes a secure, internal call to retrieve the ClickUp and Slack API tokens. It also loads the emoji-to-status mapping from the `configs/reactions_problem_report.json` file packaged with the function.

5.  **Get Slack Message & Update ClickUp Task**
    *   **Source:** AWS Lambda
    *   **Destination:** Slack API & ClickUp API
    *   **Action:** The function fetches the content of the message that was reacted to, finds the ClickUp task URL, and uses the reaction emoji to determine the new status from its configuration. It then makes a server-to-server API request to ClickUp to update the task status accordingly.

6.  **Post Confirmation Message**
    *   **Source:** AWS Lambda
    *   **Destination:** Slack API
    *   **Action:** The function sends a formatted message back to the user in Slack, confirming that the task has been updated.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, secrets in Secrets Manager, an API Gateway endpoint, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name      | Value                           |
|-----------|---------------------------------|
| Project   | slack-reaction-problem-report |
| Workspace | facilities                      |

## Configuration

Configuration for the function is managed in two places: environment variables and a JSON configuration file.

### Environment Variables

Core settings are managed via environment variables within the AWS Lambda function's configuration section. This allows for easy updates to things like the ClickUp List ID or bot name without changing the code.

### Reaction to Status Mapping

The mapping between Slack emoji reactions and the corresponding ClickUp task statuses is defined in the `configs/reactions_problem_report.json` file. This file is bundled with the Lambda function during deployment.

This approach allows for easy modification of which emoji triggers which status change without altering the Python code.

**Example `configs/reactions_problem_report.json`:**
```json
{
  "eyes": "investigating",
  "white_check_mark": "resolved",
  "no_entry_sign": "won't fix"
}
```

## Testing

This function includes a suite of unit tests to ensure its logic is correct. The tests mock external dependencies (like AWS, ClickUp, and Slack APIs) so they can be run locally without needing credentials or making real API calls.

## Deployment

The deployment process is managed and specified in the Deployment Instructions.

## Usage

The URL is used in the Maintenance Slack App in Event Subscriptions.