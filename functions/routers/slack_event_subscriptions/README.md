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
*   **AWS SSM Parameter Store:** Stores the router's configuration: the Slack channel IDs that are routed (the target functions' ARNs are environment variables).

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

A third target, the **PM Reminder Reaction Handler** (`PMReminderReactionFunction`,
`functions/facilities/pm_reminder_reaction/`), receives reactions in the PM channels
(`pm_channels`, below). It completes the ClickUp PM task named in a PM Bot reminder that
gets a ✅.

### Step-by-Step Data Flow:

1.  **Add Reaction:** A user adds an emoji reaction to a message in a monitored Slack channel (e.g., `#purchase-requests`, `#problem-reports`, or a PM channel such as `#woodshop-maintenance`).
2.  **Send POST Request:** Slack sends a POST request with the event payload to the single `/slack/events` endpoint on the AWS API Gateway.
3.  **Trigger Router Function:** The API Gateway request triggers this router Lambda function.
4.  **Fetch Configuration:** The router fetches its configuration from an SSM Parameter. This configuration holds the channel IDs that are routed: the purchase-request channel, the problem-report channel and the PM channels.
5.  **Determine Target:** The function inspects the event payload to find the `channel_id` where the reaction occurred. It compares this ID with `purchase_request_channel_id`, `problem_report_channel_id` and the keys of `pm_channels` in its configuration, and picks the matching target's ARN from its environment variables. A reaction in any other channel is logged and ignored.
6.  **Invoke Target Function:** The router makes an asynchronous `invoke` call to the target Lambda function (`PurchaseRequestReactionFunction`, `ProblemReportReactionFunction` or `PMReminderReactionFunction`), passing the original event payload for processing.

## AWS Infrastructure

The core infrastructure is defined in `templates/routers.yaml` and consists of the Lambda function and its associated IAM Role for permissions.

### Memory and timeout

| Setting | Value | Why |
|---------|-------|-----|
| `MemorySize` | 512 MB | Lambda gives a function CPU in proportion to its memory. At the 128 MB default, a cold start couldn't load its SSM and Lambda clients, fetch the config and invoke the target within Slack's 3-second deadline, so API Gateway answered Slack with a 502. 512 MB gives it enough CPU. |
| `Timeout` | 3 seconds | Slack gives up on an event after 3 seconds, so a longer timeout only adds cost. A call that gets stuck ends in a 502, and Slack retries the event. |

The function builds its SSM and Lambda clients on first use and keeps them for the life of the container, so warm requests reuse them. It still reads the SSM parameter on every request, so a config change applies at once.

### Logging

Each request writes one line to the log group `/asmbly/lambda/facilities-slack-event-router-<stage>`: the Slack event type, the channel ID, and the `X-Slack-Retry-Num` header (`retry_num=None` on a first delivery, `1`, `2`, ... on Slack's retries). Count the lines with a retry number to see how often Slack had to retry. The function never logs the request headers or body, which carry Slack's signature and verification token.

### Tags

| Name        | Value                       |
|-------------|-----------------------------|
| Application | facilities-automation-hub   |
| Project     | router:slack-event          |
| Workspace   | facilities                  |

## Configuration

The router's configuration is managed in a single SSM Parameter, which is created from the `configs/router_config.json` file during deployment. This file defines which channels route to which functions.

**Example `configs/router_config.json`:**
```json
{
  "purchase_request_channel_id": "C026YVA7TK3",
  "problem_report_channel_id": "C063LH7MB45",
  "pm_channels": {
    "C0CJAK1D725": "woodshop-maintenance"
  }
}
```

`pm_channels` lists the channels the PM Reminder Bot posts to, by ID (`{channel_id:
channel_name}`; the name is for people and for `tests/test_configs.py`). The router
forwards every reaction in these channels to the PM Reminder Reaction Handler, which
acts only on a ✅ on a PM Bot reminder and ignores everything else. To add or remap a PM
channel, see "Adding or remapping a PM channel" in
`functions/facilities/pm_bot_reminder/README.md`.
The list is partial: only `#woodshop-maintenance` is in it until an admin confirms the
IDs of the other PM channels (3d-printing, ceramics, electronics, lasers, metal-shop,
textiles). A reaction in a channel that isn't listed is ignored.

To stop ✅s completing PM tasks in an emergency, set the PM Reminder Reaction Handler's
`DRY_RUN` to `'true'` for prod in `templates/facilities.yaml`
(`PMReminderReactionFunction` → `Environment.Variables`) and deploy: reactions are
still forwarded, but the handler only logs what it would do. Emptying `pm_channels`
doesn't work (a test requires the list to be non-empty and to include every mapped PM
channel), and neither does removing only the router's PM branch (the seam test in
`tests/test_templates.py` requires the code to read `PM_REMINDER_LAMBDA_ARN`).

The name of the SSM parameter itself is passed to the Lambda function via the `ROUTER_CONFIG_PARAMETER_NAME` environment variable.

### Environment variables

All are set in `templates/routers.yaml`; the ARNs come from the other stacks through `template.yaml` (`RoutersStack`).

| Variable | What it is |
|----------|------------|
| `ROUTER_CONFIG_PARAMETER_NAME` | The SSM parameter that holds `configs/router_config.json` |
| `PURCHASE_REQUEST_LAMBDA_ARN` | Target for reactions in the purchase-request channel |
| `PROBLEM_REPORT_LAMBDA_ARN` | Target for reactions in the problem-report channel |
| `PM_REMINDER_LAMBDA_ARN` | Target for reactions in the `pm_channels` channels |

The function's role can invoke these three functions and nothing else. A test
(`tests/test_templates.py`, `test_router_can_invoke_every_function_it_routes_to`) fails
if a `*_LAMBDA_ARN` target isn't in the invoke permission or isn't passed from
`template.yaml`. If a target's variable is missing, reactions in its channel are
logged as an error (`<VARIABLE> environment variable not set`) and ignored.

## Deployment

This function is deployed as part of the main SAM application. See the root `Deploying.md` for more details.