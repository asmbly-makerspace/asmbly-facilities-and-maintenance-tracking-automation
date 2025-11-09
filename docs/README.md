# Asmbly Facilities, Maintenance, and Tracking Automation Hub

This repository contains serverless AWS Lambda functions that automate various tasks for Asmbly Makerspace. All infrastructure is managed as code using the AWS Serverless Application Model (SAM).

## Table of Contents
- [TODO](#todo)
- [What's in this Repository?](#whats-in-this-repository)
- [How It's Managed (The Important Part!)](#how-its-managed-the-important-part)
- [Supporting Documentation](#supporting-documentation)
- [Repository Structure Overview](#repository-structure-overview)

## TODO

- [x] Manual Deployment of each lambda for POC purposes
- [x] Approval from Asmbly IT
- [x] Prove-out client-side yaml deployment
- [x] Decide on [branch & deployment strategy](Branching%20Strategy.md)
- [x] Use GitHub Actions for automated deployment

## What's in this Repository?

This repository contains several independent services that automate various tasks for Asmbly. Each service is implemented as a serverless AWS Lambda function and managed via the AWS Serverless Application Model (SAM).

### Core Services

The project is organized into several functional areas, with a core infrastructure service for routing Slack events.

#### Infrastructure
These services provide core functionality used by other parts of the system.
*   **Slack Event Router** (`SlackEventSubscriptionsRouterFunction`)
    *   **What it does:** Acts as the single entry point for all Slack `reaction_added` events. It inspects the event and forwards it to the correct handler function based on the channel where the reaction occurred.
    *   **How it's triggered:** An HTTP `POST` from a Slack Event Subscription to the `/slack/events` API Gateway endpoint.
    *   **Webhook Location:** Slack Bot - Maintenance Bot -> Event Subscriptions -> Request URL https://api.slack.com/apps/A08S6EP1A7J/event-subscriptions

#### Ceramics
*   **Kiln Drop-Off Viewer** (`KilnOpsDropoffRecentEntriesViewer`)
    *   **What it does:** Creates a public web page that displays recent Kiln Drop Off entries. This lets members see their confirmation of submitting a kiln form easily.
    *   **How it's triggered:** An HTTP `GET` request via an AWS API Gateway endpoint.
    *   **Webhook Location:** ClickUp Form (Ceramics - Drop Off Requests) https://app.clickup.com/90131034630/v/fm/2ky3mwg6-2053 -> Settings -> Redirect URL

#### Administrative
These services automate administrative tasks, such as member data synchronization.
*   **New Waiver Completed Handler** (`NewWaiverCompletedFunction`)
    *   **What it does:** Receives a webhook from Smartwaiver when a new waiver is signed. It parses the member's email and signature date, then updates the `WaverDate` custom field in the corresponding NeonCRM account.
    *   **How it's triggered:** An HTTP `POST` from a Smartwaiver webhook to the `/waiver/new` API Gateway endpoint.
    *   **Webhook Location:** "new waiver signed" at https://app.cleverwaiver.com/v2profile/webhook

#### Facilities & Maintenance
These services automate tasks related to facilities management, problem reporting, and purchasing.
*   **PM Reminder Bot** (`PMReminderBot`)
    *   **What it does:** Automatically fetches upcoming and overdue maintenance tasks from ClickUp and posts them as weekly reminders in the relevant Slack channels.
    *   **How it's triggered:** A scheduled cron job that runs every Saturday morning (via Amazon EventBridge).
*   **Slack Purchase Reorder & Interaction Handler** (`FacilitiesSlackPurchaseReorderFunction`)
    *   **What it does:** Handles the `/reorder` slash command to open a modal for creating purchase requests in ClickUp. It also processes interactions within that modal, like submissions.
    *   **How it's triggered:** An HTTP `POST` from a Slack slash command to the `/SlackSlashReorder` API Gateway endpoint. This single endpoint handles both the initial command and subsequent user interactions (e.g., modal submissions).
    *   **Webhook Location:** Slack Bot - Maintenance Bot -> Slash Commands -> `/reorder` https://api.slack.com/apps/A08S6EP1A7J/slash-commands Also for now in Interactivity & Shortcuts https://api.slack.com/apps/A08S6EP1A7J/interactive-messages
*   **Problem Report Reaction Handler** (`FacilitiesSlackProblemReportReactionWebhook`)
    *   **What it does:** Allows facilities team members to update the status of a problem report task in ClickUp by adding an emoji reaction (e.g., `:eyes:`, `:white_check_mark:`) to a Slack message that contains the task link.
    *   **How it's triggered:** Asynchronously invoked by the **Slack Event Router** when a reaction is added in a monitored channel.
*   **Purchase Request Reaction Handler** (`FacilitiesSlackPurchaseReactionWebhook`)
    *   **What it does:** Allows facilities team members to update the status of a purchase request task in ClickUp by adding an emoji reaction (e.g., `:truck:`, `:house:`) to a Slack message that contains the task link.
    *   **How it's triggered:** Asynchronously invoked by the **Slack Event Router** when a reaction is added in a monitored channel.
*   **New Purchase Request Handler** (`NewPurchaseRequestReceivedFunction`)
    *   **What it does:** Listens for new purchase request tasks created in ClickUp. It then posts a detailed notification to a Slack channel and updates the original ClickUp task with a permalink to the Slack message.
    *   **How it's triggered:** An HTTP `POST` from a ClickUp webhook to its dedicated API Gateway endpoint.
    *   **Webhook Location:** https://app.clickup.com/90131034630/v/l/6-901310302436-1?pr=90134243830 ClickUp Webhooks (Facilities - Purchase Requests) -> Automations -> Webhooks -> New Purchase Request -> Edit -> URL

## How It's Managed (The Important Part!)

This project uses the **AWS Serverless Application Model (SAM)**. This means:

* **`template.yaml` is the boss.** This single file is the source of truth. It defines every piece of the cloud infrastructure: the Lambda functions, the API Gateway, the scheduled triggers, IAM roles, environment variables, etc.
* **Do not make changes in the AWS Console.** Any manual changes made directly in the AWS console (like changing an environment variable) will be overwritten the next time someone deploys from this repository.
* **All changes must go through the `template.yaml` file.** To change a function's timeout, add a new function, or modify a trigger, you must edit the `template.yaml` file and redeploy.

## Supporting Documentation

- **CONTRIBUTING.md** - How to contribute to the hub and add new functions.
- **Deploying.md** - How to deploy to the hub.

## Repository Structure Overview

* `template.yaml`: Defines all AWS resources. **Start here to understand the architecture.**
* `/functions`: Contains a separate folder for each Lambda function's Python code.
* `/layers`: Holds shared code or dependencies. Currently used for the `requests` Python library.
