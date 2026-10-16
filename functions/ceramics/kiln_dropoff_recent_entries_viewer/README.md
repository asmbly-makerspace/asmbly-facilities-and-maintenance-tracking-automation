# Kiln Drop Off Recent Entries Viewer

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Resources](#aws-resources)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Usage](#usage)
- [Testing](#testing)

## Purpose

### Endstate

Kiln-Ops would like to simplify their record keeping practice for themselves and their users by having users use a QR code to scan a QR code, complete a form to drop off their piece, then write a unique identifier on a slip for their piece. The kiln staff can then easily load all of the pieces into the kiln and use the associated slips to digitally log which pieces are in the kiln. Afterwards, the slips will be discarded, and through digital records ClickUp can automatically email members that their piece is completed.

### Problem

ClickUp Forms when submitted show a completely static page and there’s no way to have a unique identifier.

### End Result

ClickUp Forms allow for a Redirect URL. Using this, once a member completes the form they will be redirected to a page that will show the names and IDs of recent drop offs. In case there is any delay in ClickUp creating the entry and it being available in the redirect URL, the user can refresh the page to see their ID. When it is available, the ID will be hand written on a slip for them to use. (Future this could be printed)

### Solution by This Lambda

Enable users to get an ID of their kiln drop off submission so they can transfer that to a paper receipt.

## How It Works

This diagram illustrates the secure, server-side workflow for displaying recent ClickUp tasks after a form submission. This architecture avoids exposing API keys.

### Components:

-   **User's Browser:** The end-user's web browser.
-   **ClickUp Form:** The native form where the user submits their entry.
-   **AWS API Gateway:** A managed service that provides a public URL (endpoint) for our application.
-   **AWS Lambda:** A serverless function that contains the Python logic.
-   **AWS Secrets Manager:** Holds the ClickUp API token (secret `clickup/api/token`, key `CLICKUP_API_TOKEN`).
-   **AWS Systems Manager Parameter Store:** Holds the drop-off list ID (parameter `/<stage>/config/clickup/ceramics/dropOffRequests`, key `list_id`).
-   **ClickUp API:** The official API for accessing ClickUp data.

### Visual Flow

```
+---------------+      +----------------+      +-----------------+      +---------------------+
| User's        |      | ClickUp        |      | AWS API Gateway |      | AWS Lambda Function |
| Browser       |      | Form           |      | (Public URL)    |      | (Your Code)         |
+---------------+      +----------------+      +-----------------+      +---------------------+
|                     |                      |                       |
(1) Submit Form ------------->|                      |                       |
|                     |                      |                       |
(2) Redirect Browser -------->|--------------------->|                       |
|                     |                      |                       |
|                     |             (3) Trigger Function ----------->|
|                     |                      |                       |
|                     |                      |                       | (4) Get list ID and token
|                     |                      |                       |---------------------->[SSM Parameter Store, Secrets Manager]
|                     |                      |                       |                      |
|                     |                      |                       |<----------------------| (5) Return list ID and token
|                     |                      |                       |
|                     |                      |                       | (6) Request Tasks
|                     |                      |                       |---------------------->[ClickUp API]
|                     |                      |                       |                      |
|                     |                      |                       |<----------------------| (7) Return Task Data
|                     |                      |                       |
|                     |             (8) Return HTML Page   |
|<--------------------------------------------|<-----------------------|
|                     |                      |                       |
(9) Display Page              |                      |                       |
|                     |                      |                       |
```

### Step-by-Step Data Flow:

1.  **Kiln DropOff Form Submission**
    * **Source:** User's Browser
    * **Destination:** ClickUp Kiln Drop Off Form
    * **Action:** The user fills out the form and clicks "Submit".

2.  **HTTP Redirect**
    * **Source:** ClickUp Form
    * **Destination:** AWS API Gateway
    * **Action:** ClickUp instructs the user's browser to navigate to the AWS API Gateway URL. No task data is sent here.

3.  **Trigger Lambda Function**
    * **Source:** AWS API Gateway
    * **Destination:** AWS Lambda
    * **Action:** The incoming request to the API Gateway endpoint automatically triggers your Lambda function to run.

4.  **Fetch the list ID and the API token**
    * **Source:** AWS Lambda
    * **Destination:** SSM Parameter Store, then AWS Secrets Manager
    * **Action:** The function reads the drop-off list ID from the SSM parameter `/<stage>/config/clickup/ceramics/dropOffRequests` (key `list_id`), then the ClickUp API token from Secrets Manager. Secrets Manager holds only the token.

5.  **Return the list ID and the token**
    * **Source:** SSM Parameter Store and AWS Secrets Manager
    * **Destination:** AWS Lambda
    * **Action:** The values are passed back to the running function. If the token is empty, the function stops here and shows the error page.

6.  **Request Tasks from ClickUp API**
    * **Source:** AWS Lambda
    * **Destination:** ClickUp API
    * **Action:** The Lambda function makes a server-to-server API request to api.clickup.com, using the fetched secrets for authentication. This call is not subject to CORS rules.

7.  **Return Task Data**
    * **Source:** ClickUp API
    * **Destination:** AWS Lambda
    * **Action:** The ClickUp API returns a JSON object containing all tasks created in the last 24 hours.

8.  **Generate and Return HTML**
    * **Source:** AWS Lambda
    * **Destination:** AWS API Gateway
    * **Action:** The function processes the JSON data, constructs a complete HTML document on the fly, and returns it as the response. Each drop-off's name and ID are HTML-escaped, so text typed into the form shows as text and never runs as code. A drop-off with no custom ID shows its ClickUp task ID.

9.  **Display Page**
    * **Source:** AWS API Gateway
    * **Destination:** User's Browser
    * **Action:** The API Gateway forwards the HTML response to the user's browser, which then renders the final page showing the list of recent submissions.

### Errors and security headers

- If anything goes wrong (a missing environment variable, an empty token, an SSM, Secrets Manager or ClickUp error), the page says only "Could not retrieve the list of submissions." The details go to the log group `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-<stage>`, never to the page.
- Every response, the list and the error page alike, is sent with these headers:
  - `Content-Type: text/html; charset=utf-8`
  - `X-Content-Type-Options: nosniff`
  - `Cache-Control: no-store`, so Refresh always fetches a fresh list
  - `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; font-src https://asmbly.org; img-src https://asmbly.org; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. The page runs no script, uses one inline style block, and loads its fonts and logos from https://asmbly.org. It can't be shown inside a frame. If you add an image, font or script from another site, add that site to the policy in `lambda_function.py`.
- The Refresh button is a plain link back to the same page, so it works without script.

## AWS Resources

Tags in AWS will be:

| Name        | Value                        |
|-------------|------------------------------|
| Project     | ceramics:kiln-dropoff-viewer |

### Permissions

The function's role (`KilnDropoffViewerLambdaRole` in `templates/ceramics.yaml`) can do
three things and nothing else:

- Write log streams and log events to its own log group,
  `/asmbly/lambda/KilnDropoffRecentEntriesViewerFunction-<stage>`.
- Read the `clickup/api/token` secret from Secrets Manager.
- Read the `/<stage>/config/clickup/ceramics/dropOffRequests` parameter from SSM.

The role can't create log groups. CloudFormation creates this one. If someone deletes it
by hand, the function keeps working but its logs are lost until the log group exists
again under the same name. A normal deploy won't bring it back, because CloudFormation
doesn't notice a resource deleted outside it. An admin has to recreate the log group
with that name and a 30-day retention.

`tests/test_templates.py` fails if this role, or any other application role, is given
an IAM action or a logs grant on a wildcard resource.

## Configuration

The template `templates/ceramics.yaml` sets two environment variables:

| Variable | Value | What it is |
| --- | --- | --- |
| `SECRET_NAME` | `clickup/api/token` | The Secrets Manager secret that holds the ClickUp API token under the key `CLICKUP_API_TOKEN` |
| `CLICKUP_CERAMICS_CONFIG_PARAMETER_NAME` | `/<stage>/config/clickup/ceramics/dropOffRequests` | The SSM parameter with the drop-off list ID under the key `list_id` |

The list ID itself lives in `configs/clickup_ceramics_dropOffRequests.json`; the template turns that file into the SSM parameter. To point the page at another ClickUp list, change the JSON file and deploy.


## Deployment

The deployment process is managed and specified in the [Deployment Instructions](/docs/Deploying.md).

## Usage

The URL is in the ClickUp form in Ceramics -> Drop Off Requests -> Kiln Drop Off Form -> Settings -> Redirect URL.

## Testing

From the repository root:

```bash
.venv/bin/python -m pytest functions/ceramics/kiln_dropoff_recent_entries_viewer
```

The tests mock SSM, Secrets Manager and ClickUp, so they need no AWS access. After a deploy to stage, open `<stage API URL>/KilnOpsDropoffRecentEntriesViewer` and check that the list loads, Refresh reloads it, and the browser console shows no Content-Security-Policy violations. Stage has no custom domain, so `<stage API URL>` is the `FacilitiesApiUrl` output of the stage stack, `AsmblyFacilitiesMaintTrackingStack-stage`, which looks like `https://<api-id>.execute-api.us-east-2.amazonaws.com/stage`. Find it in the AWS console under CloudFormation, that stack, the **Outputs** tab. (In prod the page is `https://facilities.asmbly.org/KilnOpsDropoffRecentEntriesViewer`.)

The asmbly.org fonts already fail with a CORS error because asmbly.org sends no `Access-Control-Allow-Origin` header; that is not a CSP problem.
