# New Waiver Completed Handler

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)

## Purpose

This AWS Lambda function acts as a webhook receiver for new waiver completions from Smartwaiver. Its primary role is to automate the administrative task of updating a member's record in NeonCRM after they have signed a new waiver.

When a waiver is signed, this function is triggered. It parses the user's email and the signature date from the webhook payload. It then searches for a matching account in NeonCRM and, if found, updates a custom field (`WaiverDate`) with the correctly formatted date of the signature. This ensures that member records are always up-to-date with their latest waiver status.

## How It Works

The automation follows a clear, sequential process triggered by a Smartwaiver webhook.

### Components:

*   **Smartwaiver Webhook:** Configured to fire when a new waiver is completed.
*   **AWS API Gateway:** Provides the public `/waiver/new` endpoint that the Smartwaiver webhook sends requests to.
*   **AWS Lambda (This Function):** The serverless function containing the processing logic.
*   **AWS Secrets Manager:** Securely stores the NeonCRM Organization ID and API Key.
*   **NeonCRM API:** Used to search for accounts by email and update their custom fields.

### Visual Flow

```
+-------------+      +-----------------+      +---------------------+
| Smartwaiver |      | AWS API Gateway |      | AWS Lambda Function |
| (New Waiver)|      | (/waiver/new)   |      | (This Code)         |
+-------------+      +-----------------+      +---------------------+
       |                      |                       |
(1) Waiver Signed ---------> | (2) Send POST Request |                       |
       |                      |---------------------->| (3) Trigger Function  |
       |                      |                       |---------------------->[AWS Secrets Manager] (4) Get NeonCRM Secrets
       |                      |                       |
       |                      |                       |<----------------------[AWS Secrets Manager] (5) Return Secrets
       |                      |                       |
       |                      |                       | (6) Search Account --->[NeonCRM API]
       |                      |                       |<-----------------------| (7) Return Account ID
       |                      |                       |
       |                      |                       | (8) Update Account --->[NeonCRM API]
       |                      |                       |
```

### Step-by-Step Data Flow:

1.  **Waiver Signed**: A user completes and signs a waiver in Smartwaiver.
2.  **Send POST Request**: Smartwaiver automatically sends a `POST` request (webhook) with the waiver data to the `/waiver/new` endpoint on API Gateway.
3.  **Trigger Function**: The API Gateway request triggers this Lambda function.
4.  **Parse Payload**: The function parses the incoming JSON payload to extract the user's email address and the `signed_date`.
5.  **Fetch Secrets**: The function makes a secure, internal call to AWS Secrets Manager to retrieve the NeonCRM credentials.
6.  **Search NeonCRM Account**: Using the extracted email, the function makes an API call to NeonCRM to search for a matching account.
7.  **Update NeonCRM Account**: If an account is found, the function formats the signature date to `MM/DD/YYYY` and makes a `PATCH` request to the NeonCRM API to update the `WaverDate` custom field for that account.
8.  **Return Response**: The function returns a `200 OK` status to the webhook source to acknowledge receipt and successful processing. If the account is not found, it returns a `404` to indicate this. If NeonCRM rejects the update, times out or can't be reached, it returns a `502`, so the waiver date is never reported as saved when it wasn't.

Smartwaiver treats any answer outside 2xx (and no answer within 5 seconds) as not delivered: it retries the webhook every 5 minutes and gives up after five failed attempts, leaving an entry in its webhook log. Setting the same `WaiverDate` again is harmless, so a retry can't do damage. A rejection caused by the account's own data (Neon validates the whole account on an update, so an invalid date of birth elsewhere on the account fails it) fails every retry too, and needs the account fixed and the `WaiverDate` set by hand in NeonCRM.

### Logging

The function's CloudWatch logs record the Smartwaiver waiver ID (`waiver_id` in the payload) and the NeonCRM account ID, never the signer's email or name. A waiver ID that isn't a plain ID (letters, digits, `-` and `_`, up to 64 characters) is logged as `invalid`, and a missing one as `None`; neither stops the waiver from being processed. When something unexpected fails, the log names the error's type and the waiver ID, not the error's text. When NeonCRM refuses the update, an `ERROR` line gives the HTTP status and Neon's error codes and messages (at most five, each cut to 200 characters, with email addresses shown as `<email>` and phone numbers, dates and other long numbers as `<number>`), followed by `WaiverDate not saved for waiver <waiver ID> on NeonCRM account <account ID>`. A body that isn't Neon's error list is not logged; the line says `body is not JSON` or `<invalid>` instead.

## AWS Infrastructure

The core infrastructure is defined in `templates/administrative.yaml` and consists of the Lambda function and its associated IAM Role for permissions.

### Tags

| Name        | Value                                |
|-------------|--------------------------------------|
| Application | facilities-automation-hub            |
| Project     | administrative:new-waiver-completed |
| Workspace   | administrative                       |

## Configuration

This function relies on a secret stored in AWS Secrets Manager for its configuration.

### Secrets

*   **`prod/neon_token`**: The AWS Secrets Manager secret containing the NeonCRM credentials. The Lambda function expects this secret to be a JSON string with the following keys:
    *   `NEON_ORG_ID`: The organization ID for NeonCRM.
    *   `NEON_API_KEY`: The API key for authenticating with the NeonCRM API.

The name of this secret is passed to the function via the `NEON_SECRET_NAME` environment variable.

## Deployment

This function is deployed as part of the `AdministrativeStack` nested stack. See the root `Deploying.md` for more details.

## Usage

The API Gateway endpoint for this function is used to create a webhook in Smartwaiver. The webhook should be configured to trigger on the "New Waiver Received" event and send a `POST` request to the `/waiver/new` endpoint.