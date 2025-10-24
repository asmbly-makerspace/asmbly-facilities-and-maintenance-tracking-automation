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
- [ ] Decide on [branch & deployment strategy](Branching%20Strategy.md)
- [ ] Use GitHub Actions for automated deployment

## What's in this Repository?

There are three primary, independent services running:

1.  **Kiln Drop-Off Viewer (`KilnOpsDropoffRecentEntriesViewer`)**
    * **What it does:** Creates a public web page that displays recent Kiln Drop Off entries. This lets members see their confirmation of submitting a kiln form easily.
    * **How it's triggered:** An HTTP `GET` request via an AWS API Gateway endpoint.

2.  **PM Reminder Bot (`PMReminderBot`)**
    * **What it does:** Automatically fetches upcoming and overdue maintenance tasks from ClickUp and posts them as weekly reminders in the relevant Slack channels.
    * **How it's triggered:** A scheduled cron job that runs every Saturday morning (via Amazon EventBridge).

3.  **Facilities Slack Purchase Reorder (`FacilitiesSlackPurchaseReorderFunction`)**
    * **What it does:** Provides a Slack command that opens a modal, allowing users to select a standard inventory item and create a purchase request for it in ClickUp.
    * **How it's triggered:** An HTTP `POST` request via an AWS API Gateway endpoint, which is configured as the endpoint for a Slack slash command.

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
