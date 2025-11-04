# Slack Event Subscriptions Router

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Deployment](#deployment)

## Purpose

This Lambda function acts as a centralized router for incoming Slack events. Its primary purpose is to receive all `reaction_added` events from a single Slack Event Subscription endpoint and intelligently forward them to the appropriate downstream service based on the channel where the event occurred.

This architecture simplifies the Slack App configuration by requiring only one URL for all reaction-based event subscriptions, making the system more scalable and easier to manage.

## How It Works

The router is a serverless AWS Lambda function triggered by an API Gateway endpoint.

### Components:

*   **Slack Event Subscription:** A single subscription in the Slack App that listens for `reaction_added` events and sends them to one URL.
*   **AWS API Gateway:** Provides the public `/slack/events` endpoint that Slack sends requests to.
*   **AWS Lambda (This Function):** The serverless function containing the routing logic.
*   **AWS SSM Parameter Store:** Securely stores the router's configuration, which maps Slack Channel IDs to the ARNs of the target Lambda functions.

### Visual Flow

```
+--------------+      +-----------------+      +---------------------+      +---------------------+
| User's Slack |      | AWS API Gateway |      |  Slack Event Router |      | AWS SSM Parameter   |
| (Adds React) |      | (/slack/events) |      |  (Lambda Function)  |      | (Channel ID Config) |
+--------------+      +-----------------+      +---------------------+      +---------------------+
       |                      |                        |                             |
(1) Add Reaction ----------->| (2) Send POST Request  |                             |
       |                     |----------------------->| (3) Trigger Router      |                             |
       |                     |                        |----------------------->| (4) Get Config        |
       |                     |                        |<-----------------------| (5) Return Config     |
       |                     |                        |                             |
       |                     |                        | (6) Determine Target & Invoke...
       |                     |                        |
       |                     +------------------------+-------------------------+
       |                     |                                                  |
       |                     v                                                  v
       |      +--------------------------------+      +----------------------------------+
       |      | Purchase Request Reaction Func |      | Problem Report Reaction Func   |
       |      | (Lambda)                       |      | (Lambda)                         |
       |      +--------------------------------+      +----------------------------------+
       |                     |                                                  |
       |      (7a) Process Purchase Request...        (7b) Process Problem Report...
```

### Step-by-Step Data Flow:

1.  **Add Reaction:** A user adds an emoji reaction to a message in a monitored Slack channel (e.g., `#purchase-requests` or `#problem-reports`).
2.  **Send POST Request:** Slack sends a POST request with the event payload to the single `/slack/events` endpoint on the AWS API Gateway.
3.  **Trigger Router Function:** The API Gateway request triggers this router Lambda function.
4.  **Fetch Configuration:** The router fetches its configuration from an SSM Parameter. This configuration contains a JSON object mapping channel IDs to the ARNs of the target Lambda functions.
5.  **Determine Target:** The function inspects the event payload to find the `channel_id` where the reaction occurred. It uses this ID to look up the corresponding target Lambda ARN from its configuration.
6.  **Invoke Target Function:** The router makes an asynchronous `invoke` call to the target Lambda function (e.g., `PurchaseRequestReactionFunction` or `ProblemReportReactionFunction`), passing the original event payload for processing.

## AWS Infrastructure

The core infrastructure is defined in `templates/routers.yaml` and consists of the Lambda function and its associated IAM Role for permissions.

### Tags

| Name      | Value                         |
|-----------|-------------------------------|
| Project   | facilities-slack-event-router |
| Workspace | facilities                    |

## Configuration

The router's configuration is managed in a single SSM Parameter, which is created from the `configs/router_config.json` file during deployment. This file defines which channels route to which functions.

**Example `configs/router_config.json`:**
```json
{
  "purchase_request_channel_id": "C026YVA7TK3",
  "problem_report_channel_id": "C063LH7MB45"
}
```

The name of the SSM parameter itself is passed to the Lambda function via the `ROUTER_CONFIG_PARAMETER_NAME` environment variable.

## Deployment

This function is deployed as part of the main SAM application. See the root `Deploying.md` for more details.