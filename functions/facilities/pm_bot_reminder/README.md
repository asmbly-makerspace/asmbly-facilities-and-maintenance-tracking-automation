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
    * **Action:** The function makes a secure, internal call to retrieve the ClickUp and Slack API tokens.

3.  **Fetch Tasks from ClickUp**
    * **Source:** AWS Lambda
    * **Destination:** ClickUp API
    * **Action:** The Lambda function makes two server-to-server API requests to ClickUp to get all tasks that are either overdue or due in the upcoming week.

4.  **Process Tasks**
    * **Source:** AWS Lambda
    * **Destination:** AWS Lambda
    * **Action:** The script processes the list of tasks, extracting key details like the task name, description, and the designated Slack channel from a custom field.

5.  **Send Slack Notifications**
    * **Source:** AWS Lambda
    * **Destination:** Slack API
    * **Action:** The function sends formatted messages for each task to the appropriate Slack channels. It can also send a general "starter message" and post detailed descriptions in threaded replies.

## AWS Infrastructure

The core infrastructure consists of an IAM Role, two secrets in Secrets Manager, and the Lambda function itself. All related resources are tagged for cost allocation and organization.

### Tags

| Name      | Value           |
|-----------|-----------------|
| Project   | pm-reminder-bot |
| Workspace | facilities      |

## Configuration

All settings are managed via environment variables within the AWS Lambda function's configuration section. This allows for easy updates to things like the ClickUp List ID, bot name, or optional features without changing the code.


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