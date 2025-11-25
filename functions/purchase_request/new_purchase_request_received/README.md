# New Purchase Request Handler

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)

## Purpose

This AWS Lambda function acts as a webhook receiver for new tasks created in a specific ClickUp list, designated for purchase requests. Its primary role is to bridge the communication gap between ClickUp and Slack, ensuring that new requests are immediately visible to the relevant team members in a collaborative environment.

The function creates a two-way link between the ClickUp task and the Slack notification, improving visibility and traceability for all purchase requests.

## How It Works

The automation follows a clear, sequential process triggered by a ClickUp webhook.

### Components:

*   **ClickUp Webhook:** Configured on a specific list to fire on "Task Created" events.
*   **AWS API Gateway:** Provides the public endpoint that the ClickUp webhook sends requests to.
*   **AWS Lambda (This Function):** The serverless function containing the logic.
*   **AWS Secrets Manager:** Securely stores the ClickUp and Slack API tokens.
*   **ClickUp API:** Used to fetch full task details and later update the task.
*   **Slack API:** Used to post the notification message.

### Visual Flow

```
+----------------+      +-----------------+      +---------------------+
| ClickUp        |      | AWS API Gateway |      | AWS Lambda Function |
| (New Task)     |      | (Public URL)    |      | (This Code)         |
+----------------+      +-----------------+      +---------------------+
        |                      |                       |
(1) Task Created  -----------> | (2) Send POST Request |                       |
        |                      |---------------------->| (3) Trigger Function  |
        |                      |                       |---------------------->[AWS Secrets Manager] (4) Get Secrets
        |                      |                       |
        |                      |                       | (5) Get Full Task ------>[ClickUp API]
        |                      |                       |<-----------------------| (6) Return Task Details
        |                      |                       |
        |                      |                       | (7) Post Notification -->[Slack API]
        |                      |                       |<-----------------------| (8) Return Message TS
        |                      |                       |
        |                      |                       | (9) Update Task ------->[ClickUp API]
        |                      |                       |
```

### Step-by-Step Data Flow:

1.  **Webhook Trigger**: A ClickUp webhook, configured to fire on "Task Created" events, sends an HTTP POST request to this function's dedicated API Gateway endpoint.

2.  **Initial Parsing**: The function receives the webhook payload and extracts the `task_id` from it.

3.  **Fetch Full Task Details**: The initial webhook payload from ClickUp does not contain the values of custom fields in a readily usable format. To get this information, the function makes a `GET` request to the ClickUp API using the `task_id` to fetch the complete task object.

4.  **Extract Information**: It parses the full task object to extract key details, including:
    *   Task Name (the item being requested)
    *   Task Description (the purpose of the purchase)
    *   Custom Fields:
        *   Requestor Name
        *   Asset Name (if applicable)
        *   Supplier Link
        *   Workspace
        *   Item Type

5.  **Notify Slack**: The function formats the extracted details into a human-readable message and posts it to a designated Slack channel (e.g., `#purchase_request`). This provides immediate visibility to the team.

6.  **Generate Slack Permalink**: Upon successfully posting the message, the Slack API returns the message's unique timestamp (`ts`) and channel ID. The function uses this information to construct a permanent URL (permalink) that links directly to the notification message.

7.  **Update ClickUp Task**: Finally, the function makes a `PUT` request back to the ClickUp API to update the original task. It populates a specific custom field (e.g., "Slack Post URL") with the permalink generated in the previous step. This creates a two-way link, allowing anyone viewing the task in ClickUp to jump directly to the Slack conversation.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, secrets in Secrets Manager, an API Gateway endpoint, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name      | Value                          |
|-----------|--------------------------------|
| Project   | purchase-request:clickup-webhook |
| Workspace | facilities                     |

## Configuration

This function relies on several environment variables for its configuration, which are set in the `templates/purchase_request.yaml` file.

### Secrets

*   `CLICKUP_SECRET_NAME`: The name of the AWS Secrets Manager secret containing the ClickUp API token.
*   `SLACK_MAINTENANCE_BOT_SECRET_NAME`: The name of the AWS Secrets Manager secret containing the Slack Bot token.

### Slack Configuration

*   `SLACK_CHANNEL_ID`: The ID of the target Slack channel for notifications (e.g., `C012AB34CD`).
*   `SLACK_BOT_NAME`: The display name for the bot when it posts a message.
*   `SLACK_BOT_EMOJI`: The emoji icon for the bot.
*   `SLACK_WORKSPACE_URL`: The base URL of the Slack workspace, required for generating permalinks.

### ClickUp Custom Field IDs

The function needs the unique IDs for the custom fields it interacts with.

*   `ASSET_NAME_FIELD_ID`: ID for the "Asset Name" field.
*   `REQUESTOR_NAME_FIELD_ID`: ID for the "Requested By" field.
*   `SUPPLIER_LINK_FIELD_ID`: ID for the "Supplier Link" field.
*   `WORKSPACE_FIELD_ID`: ID for the "Workspace" field.
*   `ITEM_TYPE_FIELD_ID`: ID for the "Item Type" field.
*   `SLACK_POST_FIELD_ID`: ID for the "Slack Post URL" field that will be updated by the function.

## Deployment

This function is deployed as part of the `PurchaseRequestStack` nested stack. See the root `Deploying.md` for more details.

## Usage

The API Gateway endpoint for this function is used to create a webhook in ClickUp. The webhook should be configured to trigger on the "Task Created" event for the designated Purchase Requests list.