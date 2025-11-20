# Asmbly Facilities, Maintenance, and Tracking Automation Hub

This repository contains serverless AWS Lambda functions that automate various tasks for Asmbly Makerspace. All infrastructure is managed as code using the AWS Serverless Application Model (SAM).

## Table of Contents

- [What's in this Repository?](#whats-in-this-repository)
- [Core Architecture: API Gateway & Custom Domain](#core-architecture-api-gateway--custom-domain)
- [Core Services](#core-services)
- [How It's Managed (The Important Part!)](#how-its-managed-the-important-part)
- [Supporting Documentation](#supporting-documentation)
- [Repository Structure Overview](#repository-structure-overview)

## What's in this Repository?

This repository contains several independent services that automate various tasks for Asmbly. Each service is implemented as a serverless AWS Lambda function and managed via the AWS Serverless Application Model (SAM).

## Core Architecture: API Gateway & Custom Domain

This project uses a single **AWS API Gateway** (`FacilitiesApi` in `template.yaml`) to manage and route all incoming HTTP requests to the correct Lambda functions.

### Custom Domain (Managed by Code)

While API Gateway provides a temporary `.execute-api` URL for development, the production environment uses a stable, permanent custom domain:

**`https://facilities.asmbly.org`**

This entire setup is **managed as code in the root `template.yaml` file** and is only created when deploying to the `prod` environment.

1.  **ACM Certificate (`FacilitiesCertificate`):** An AWS Certificate Manager (ACM) resource provides the free SSL/TLS certificate.
2.  **API Gateway Custom Domain (`FacilitiesApiCustomDomain`):** This resource links the certificate to API Gateway.
3.  **Route 53 Alias (`FacilitiesDnsRecord`):** An `A` record in the `asmbly.org` hosted zone points the "pretty" URL to the API Gateway.
4.  **API Mapping (`FacilitiesApiMapping`):** This resource connects the custom domain to the `prod` stage of your `FacilitiesApi`.

This IaC (Infrastructure as Code) approach makes the production environment robust, self-healing, and easy to replicate.

#### Why This Is Important

1.  **Stable Endpoint:** All third-party webhooks (from Slack, ClickUp, Smartwaiver, etc.) are pointed to this single, permanent URL (e.g., `https://facilities.asmbly.org/slack/events`).
2.  **Simplified Deployments:** This setup makes the deployment pipeline much more reliable. We no longer need the GitHub Action to dynamically update webhook URLs on every deployment. The custom URL never changes.

## Core Services

The project is organized into several functional areas, with a core infrastructure service for routing Slack events.

#### Infrastructure

These services provide core functionality used by other parts of the system.
* **Slack Event Router** (`SlackEventSubscriptionsRouterFunction`)
    * **What it does:** Acts as the single entry point for all Slack `reaction_added` events. It inspects the event and forwards it to the correct handler function based on the channel where the reaction occurred.
    * **How it's triggered:** An HTTP `POST` from a Slack Event Subscription.
    * **Webhook URL:** `https://facilities.asmbly.org/slack/events`
    * **Config Location:** Slack Bot - Maintenance Bot -> Event Subscriptions

#### Ceramics

* **Kiln Drop-Off Viewer** (`KilnOpsDropoffRecentEntriesViewer`)
    * **What it does:** Creates a public web page that displays recent Kiln Drop Off entries. This lets members see their confirmation of submitting a kiln form easily.
    * **How it's triggered:** An HTTP `GET` request.
    * **Webhook URL:** `https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer`
    * **Config Location:** This URL is used as the "Redirect URL" in the ClickUp Form settings for "Ceramics - Drop Off Requests".

#### Administrative

These services automate administrative tasks, such as member data synchronization.
* **New Waiver Completed Handler** (`NewWaiverCompletedFunction`)
    * **What it does:** Receives a webhook from Smartwaiver when a new waiver is signed. It parses the member's email and signature date, then updates the `WaverDate` custom field in the corresponding NeonCRM account.
    * **How it's triggered:** An HTTP `POST` from a Smartwaiver webhook.
    * **Webhook URL:** `https://facilities.asmbly.org/waiver/new`
    * **Config Location:** "new waiver signed" at `https://app.cleverwaiver.com/v2profile/webhook`

#### Facilities & Maintenance

These services automate tasks related to facilities management, problem reporting, and purchasing.
* **PM Reminder Bot** (`PMReminderBot`)
    * **What it does:** Automatically fetches upcoming and overdue maintenance tasks from ClickUp and posts them as weekly reminders in the relevant Slack channels.
    * **How it's triggered:** A scheduled cron job (via Amazon EventBridge), defined in `facilities.yaml`.
* **Slack Purchase Reorder & Interaction Handler** (`FacilitiesSlackPurchaseReorderFunction`)
    * **What it does:** Handles the `/reorder` slash command to open a modal for creating purchase requests in ClickUp. It also processes interactions within that modal, like submissions.
    * **How it's triggered:** An HTTP `POST` from a Slack slash command. This single endpoint handles both the initial command and subsequent user interactions.
    * **Webhook URL:** `https://facilities.asmbly.org/SlackSlashReorder`
    * **Config Location:** Slack Bot - Maintenance Bot -> Slash Commands (`/reorder`) and Interactivity & Shortcuts.
* **Problem Report Reaction Handler** (`FacilitiesSlackProblemReportReactionWebhook`)
    * **What it does:** Allows facilities team members to update the status of a problem report task in ClickUp by adding an emoji reaction (e.g., `:eyes:`, `:white_check_mark:`) to a Slack message that contains the task link.
    * **How it's triggered:** Asynchronously invoked by the **Slack Event Router** when a reaction is added in a monitored channel.
* **Purchase Request Reaction Handler** (`FacilitiesSlackPurchaseReactionWebhook`)
    * **What it does:** Allows facilities team members to update the status of a purchase request task in ClickUp by adding an emoji reaction (e.g., `:truck:`, `:house:`) to a Slack message that contains the task link.
    * **How it's triggered:** Asynchronously invoked by the **Slack Event Router** when a reaction is added in a monitored channel.
* **New Purchase Request Handler** (`NewPurchaseRequestReceivedFunction`)
    * **What it does:** Listens for new purchase request tasks created in ClickUp. It then posts a detailed notification to a Slack channel and updates the original ClickUp task with a permalink to the Slack message.
    * **How it's triggered:** An HTTP `POST` from a ClickUp webhook.
    * **Webhook URL:** `https://facilities.asmbly.org/purchase-request/new`
    * **Config Location:** ClickUp Webhooks (Facilities - Purchase Requests) -> Automations -> "New Purchase Request" Webhook.
* **New Problem Report Handler** (`NewProblemReportRequestReceivedFunction`)
    * **What it does:** Receives a webhook from a Google Form when a new problem report is submitted. It creates a task in ClickUp, posts a notification to Slack, and optionally creates a Discourse forum topic. It then updates the ClickUp task with links to the Slack and Discourse posts.
    * **How it's triggered:** An HTTP `POST` from a Google Apps Script attached to the Problem Report Google Form.
    * **Webhook URL:** `https://facilities.asmbly.org/problem-report/new`
    * **Config Location:** The webhook URL is [configured in the Google Apps Script](https://script.google.com/u/0/home/projects/1q-X-Z0WM41Lb0WtnkTN6yyhYcazQH22ksNKD7cCwL76FSbqXsLzlR7q1/edit) attached to the "Problem Report" Google Form.

## How It's Managed (The Important Part!)

This project uses the **AWS Serverless Application Model (SAM)**. This means:

* **`template.yaml` is the boss.** This single file is the source of truth. It defines every piece of the cloud infrastructure: the Lambda functions, the API Gateway, the scheduled triggers, IAM roles, environment variables, the custom domain, the SSL certificate, and the DNS records.
* **Do not make changes in the AWS Console.** Any manual changes made directly in the AWS console (like changing an environment variable or a Route 53 record) will be **overwritten and destroyed** the next time the production pipeline runs.
* **All changes must go through the `.yaml` template files.** To change a function's timeout, add a new API path, or modify a trigger, you must edit the appropriate `.yaml` file and redeploy.

## Supporting Documentation

- **CONTRIBUTING.md** - How to contribute to the hub and add new functions.
- **Deploying.md** - How to deploy to the hub.

## Repository Structure Overview

* `template.yaml`: Defines all AWS resources. **Start here to understand the architecture.**
* `/templates`: Contains the nested SAM templates for each service (facilities, ceramics, etc.).
* `/functions`: Contains a separate folder for each Lambda function's Python code.
* `/layers`: Holds shared code or dependencies. Currently used for the `requests` Python library.