# Preventative Maintenance (PM) Reminder Bot

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment](#deployment)

## Purpose

This script is an automated bot designed to bridge the gap between preventative maintenance tasks stored in ClickUp and team communication in Slack. Its primary purpose is to eliminate the manual work of checking for due tasks and reminding team members, ensuring timely follow-ups.

The ultimate goal of this tool is to automate routine project management reminders, improve team accountability, and save valuable time.


## How It Works

The bot functions as a serverless AWS Lambda function that runs on a recurring schedule, performing all actions without manual intervention.

### Components:

* **AWS Lambda:** A serverless function that contains the Python logic.
* **Amazon EventBridge (CloudWatch Events):** A scheduler that triggers the Lambda function to run at a predefined time (e.g., weekly).
* **AWS Secrets Manager:** A secure storage service for the ClickUp and Slack API tokens.
* **ClickUp API:** The official API for accessing task data.
* **Slack API:** The official API for sending messages to channels.

### Visual Flow

Of course. Here is a network flow diagram for the PM Reminder Bot, similar to your example, provided in a raw markdown format.

Markdown

## Network Flow Diagram

This diagram illustrates the secure, serverless workflow for the automated task reminder bot. The process is initiated by a schedule, not a user action, and runs entirely within the AWS and third-party API environments.

### Components:

- **Amazon EventBridge:** A serverless scheduler that triggers the function based on a cron expression.
- **AWS Lambda:** The serverless function containing the Python logic to fetch, process, and send notifications.
- **AWS Secrets Manager:** A secure storage service for the ClickUp and Slack API tokens.
- **ClickUp API:** The official API for accessing task data.
- **Slack API:** The official API for sending messages to channels.

### Visual Flow

```
+-----------------------+      +---------------------+      +-----------------------+
| Amazon EventBridge    |      | AWS Lambda Function |      | AWS Secrets Manager   |
| (Scheduled Rule)      |      | (Your Code)         |      | (API Keys)            |
+-----------------------+      +---------------------+      +-----------------------+
|                             |                             |
(1) Time Trigger --------------------->|                             |
|               (2) Get Secrets ----------->|
|                             |<--------------------------| (3) Return Secrets
|                             |
|               (4) Request Tasks ---------->[ClickUp API]
|                             |
|                             |<--------------------------| (5) Return Task Data
|                             |
|                             |
|               (6) Post Messages ---------->[Slack API]
|                             |
```


### Step-by-Step Data Flow:

1.  **Scheduled Trigger**
    * **Source:** Amazon EventBridge
    * **Destination:** AWS Lambda
    * **Action:** At the scheduled time (every Saturday morning), EventBridge automatically triggers the Lambda function to run.

2.  **Fetch Secrets**
    * **Source:** AWS Lambda
    * **Destination:** AWS Secrets Manager
    * **Action:** The function makes a secure, internal AWS API call to retrieve the ClickUp and Slack API tokens.

3.  **Fetch Tasks from ClickUp**
    * **Source:** AWS Lambda
    * **Destination:** ClickUp API
    * **Action:** The Lambda function makes two separate server-to-server API requests to ClickUp: one to get all tasks that are **overdue**, and another to get all tasks due in the **upcoming week**.

4.  **Process Tasks**
    * **Source:** AWS Lambda
    * **Destination:** AWS Lambda
    * **Action:** The script combines and processes the list of tasks, extracting key details like the task name, description, asset, and the designated Slack channel from custom fields. It then sorts the tasks to ensure a consistent posting order.

5.  **Send Slack Notifications**
    * **Source:** AWS Lambda
    * **Destination:** Slack API
    * **Action:** The function sends formatted messages for each task to the appropriate Slack channels. It can also send a general "starter message" and post detailed descriptions in threaded replies.

If the run fails, the function returns `500` with the fixed body
`"Error: the PM reminder run failed."`. Progress and errors are log records (`[INFO]`
and `[ERROR]`, a failure with its traceback) in the
`/asmbly/lambda/PMReminderBotFunction-<stage>` log group. A ClickUp or Slack request
that gets no answer gives up after 8 seconds and is handled like any other failure of that
service. On stage, where `DRY_RUN` is `true`, the Slack helper prints each message it
would have sent instead of posting it.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, two secrets in Secrets Manager, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name        | Value                       |
|-------------|-----------------------------|
| Application | facilities-automation-hub   |
| Project     | facilities:pm-reminder-bot |
| Workspace   | facilities                  |

## Configuration

Most settings are environment variables set in `templates/facilities.yaml`
(`PMReminderBotFunction`). The ClickUp list and the channel map are JSON in
`configs/clickup_cmms_pmSchedule.json`, which the template turns into the SSM parameter
`/<stage>/clickup/cmms/pmSchedule`. Change either file in a pull request and let the
deploy apply it. Don't edit the parameter in the console or with the AWS CLI: the next
deploy overwrites it.

### Environment variables

| Variable | Value | Used for |
| --- | --- | --- |
| `DRY_RUN` | `false` in prod, `true` on stage | Prints messages instead of posting them |
| `BOT_NAME`, `BOT_ICON_EMOJI` | `PM Bot`, `:hammer_and_wrench:` | Name and icon on each Slack post |
| `CLICKUP_SECRET_NAME` | `clickup/api/token` | Secrets Manager secret with the ClickUp token |
| `SLACK_MAINTENANCE_BOT_SECRET_NAME` | `slack-maintenancebot-token` | Secrets Manager secret with the Slack bot token |
| `CLICKUP_PM_SCHEDULE_CONFIG_PARAM_NAME` | `/<stage>/clickup/cmms/pmSchedule` | SSM parameter with `list_id` and `workspace_channel_map` |
| `CLICKUP_WORKSPACE_FIELD_ID_PARAM_NAME` | SSM parameter name | SSM parameter with `workspace_field_id` |
| `CLICKUP_ASSET_FIELD_ID`, `CLICKUP_FREQUENCY_FIELD_ID` | ClickUp custom field IDs | Read the asset and frequency of a task |

### Which Slack channel a reminder goes to

Each PM task's ClickUp **Workspace** value becomes a channel name: lowercased, spaces
turned into dashes (`Metal Shop` → `#metal-shop`). `workspace_channel_map` in
`configs/clickup_cmms_pmSchedule.json` sends chosen workspaces to a different channel:

```json
{
  "list_id": "901310894771",
  "complete_status": "complete",
  "workspace_channel_map": {
    "woodshop": "woodshop-maintenance"
  }
}
```

- Today woodshop reminders go to `#woodshop-maintenance`. Every other workspace posts to
  the channel named after it.
- Keys are workspace names, matched the same way (`"Metal Shop"` and `"metal-shop"` both
  work). Values are Slack channel names: lowercase letters, digits, `-` and `_`, with or
  without a leading `#`.
- To send another workspace elsewhere, add a key; to undo a mapping, remove it.
- When you map a workspace to a new channel, also add that channel's ID to
  `pm_channels` in `configs/router_config.json`; a test fails otherwise.
- `complete_status` is not read by this function. It names the ClickUp status that
  marks a PM task done, for the PM reminder ✅ handler that is being built.
- The message text still starts with the workspace name (`[OVERDUE] woodshop - …`), even
  when it posts to a mapped channel.
- If any entry is invalid (an uppercase or spaced channel name, a value that isn't
  text), the function logs `workspace_channel_map in the PM schedule config is invalid`
  and posts every workspace to its own channel. A test checks the committed file, so a
  typo fails the pull request first.

Renaming things breaks the mapping silently until the config is updated:

- **Renaming the Slack channel:** update the value. Slack refuses posts to the old name
  (`channel_not_found`).
- **Renaming the ClickUp Workspace option:** update the key, or reminders go to the
  channel named after the new option.

The Maintenance Bot must be a member of every target channel. Slack refuses a post to a
channel the bot isn't in (`not_in_channel`). The function logs that refusal but still
finishes with 200, so after a change, search the
`/asmbly/lambda/PMReminderBotFunction-prod` log group for `not_in_channel` and
`channel_not_found` after the next run (Saturday 04:30 UTC, which is Friday night in
Austin).

## Testing

This function includes a suite of unit tests to ensure its logic is correct. The tests mock external dependencies (like AWS, ClickUp, and Slack APIs) so they can be run locally without needing credentials or making real API calls.

### Running Tests Locally

1.  **Navigate to the function directory:**
    ```bash
    cd functions/pm_bot_reminder
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