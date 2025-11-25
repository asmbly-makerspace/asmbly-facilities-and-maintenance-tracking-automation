# New Problem Report Request Received Handler

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)

## Purpose

This AWS Lambda function acts as a webhook receiver for submissions from a Google Form dedicated to reporting facilities and equipment problems. Its primary role is to automate the intake and notification process, ensuring that new problem reports are tracked in ClickUp, announced on Slack, and optionally posted on Discourse for community visibility.

The function creates a comprehensive, cross-referenced record of the problem report across multiple platforms, improving visibility, traceability, and response time.

## How It Works

The automation follows a clear, sequential process triggered by a Google Form submission.

### Components:

*   **Google Form:** The user-facing form for submitting problem reports.
*   **Google Apps Script:** A script attached to the form that sends a webhook on submission.
*   **AWS API Gateway:** Provides the public endpoint that the webhook sends requests to.
*   **AWS Lambda (This Function):** The serverless function containing the core logic.
*   **AWS Secrets Manager:** Securely stores API keys for ClickUp, Discourse, and Slack.
*   **AWS SSM Parameter Store:** Stores non-secret configuration, such as ClickUp field IDs.
*   **ClickUp API:** Used to create and later update the problem report task.
*   **Discourse API:** Used to create a new forum topic (if requested).
*   **Slack API:** Used to post a notification message to a designated channel.

### Visual Flow

```
+----------------+      +-----------------+      +---------------------+
| Google Form    |      | AWS API Gateway |      | AWS Lambda Function |
| (Submission)   |      | (Public URL)    |      | (This Code)         |
+----------------+      +-----------------+      +---------------------+
        |                      |                       |
(1) Form Submitted ----------->| (2) Send POST Request |                       |
        |                      |---------------------->| (3) Trigger Function  |
        |                      |                       |---------------------->[AWS Secrets Manager & SSM] (4) Get Config/Secrets
        |                      |                       |
        |                      |                       | (5) Create Task ------->[ClickUp API]
        |                      |                       |<----------------------| (6) Return Task Details
        |                      |                       |
        |                      |                       | (7) Create Post ------>[Discourse API] (Optional)
        |                      |                       |<----------------------| (8) Return Post URL
        |                      |                       |
        |                      |                       | (9) Post Notification -->[Slack API]
        |                      |                       |<----------------------| (10) Return Message TS
        |                      |                       |
        |                      |                       | (11) Update Task ------>[ClickUp API]
        |                      |                       |
```

### Step-by-Step Data Flow:

1.  **Webhook Trigger**: A user submits the Google Form, which triggers an attached Google Apps Script to send an HTTP POST request to this function's API Gateway endpoint.

2.  **Parse Form Data**: The function receives the raw JSON payload and parses it to extract the user's answers, including the problem summary, location, asset, contact details, and whether a Discourse post was requested.

3.  **Create Initial ClickUp Task**: It immediately creates a new task in the designated "Problem Reports" ClickUp list. The task description is pre-filled with all the report details and includes "Pending" placeholders for the Discourse and Slack links.

4.  **Create Discourse Post (Optional)**: If the user opted in, the function creates a new topic in a specified Discourse category. The post contains the problem details to allow for public discussion.

5.  **Notify Slack**: The function formats a message and posts it to a designated Slack channel (e.g., `#facilities`). This message includes all report details, a link to the new ClickUp task, and a link to the Discourse post (if created, otherwise it notes that the user opted out).

6.  **Generate Slack Permalink**: Upon success, the Slack API returns the message's timestamp (`ts`) and channel ID. The function uses this to construct a permalink to the Slack message.

7.  **Update ClickUp Task**: In the final step, the function makes a `PUT` request to the ClickUp API to update the task created in Step 3. It updates the description to replace the "Pending" placeholders with the actual permalinks for the Discourse post and Slack message. It also populates dedicated custom fields with these URLs for structured data access.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, secrets in Secrets Manager, an SSM Parameter for configuration, an API Gateway endpoint, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name        | Value                                |
|-------------|--------------------------------------|
| Application | facilities-automation-hub            |
| Project     | problem-report:new-request-received |
| Workspace   | facilities                           |

## Configuration

This function relies on several environment variables set in the `templates/problem_report.yaml` file.

### Secrets

*   `SECRETS_ARN`: The ARN of the AWS Secrets Manager secret containing a JSON object with the following keys:
    *   `CLICKUP_API_KEY`
    *   `DISCOURSE_API_KEY`
    *   `DISCOURSE_API_USERNAME`
    *   `DISCOURSE_URL`
    *   `SLACK_MAINTENANCE_BOT_TOKEN`

### Slack Configuration

*   `SLACK_CHANNEL_ID`: The ID of the target Slack channel for notifications (e.g., `C063LH7MB45`).
*   `SLACK_BOT_NAME`: The display name for the bot when it posts a message.
*   `SLACK_BOT_EMOJI`: The emoji icon for the bot.
*   `SLACK_WORKSPACE_URL`: The base URL of the Slack workspace, required for generating permalinks.

### SSM Parameter

*   `CLICKUP_PROBLEM_REPORTS_CONFIG_PARAM_NAME`: The name of the SSM Parameter that stores a JSON object with ClickUp-specific IDs:
    *   `list_id`: The ID of the ClickUp list for problem reports.
    *   `problem_type_field_id`: Custom field ID for the "Problem Type" dropdown.
    *   `contact_details_field_id`: Custom field ID for the contact information field.
    *   `discourse_post_field_id`: Custom field ID for the Discourse post URL.
    *   `slack_post_field_id`: Custom field ID for the Slack message URL.

## Deployment

This function is deployed as part of the `ProblemReportStack` nested stack. See the root `Deploying.md` for more details.

## Usage

The API Gateway endpoint for this function is used as the target for a webhook in a Google Apps Script attached to the Problem Report Google Form.
