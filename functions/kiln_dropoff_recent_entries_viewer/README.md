# Kiln Drop Off Recent Entries Viewer

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Resources](#aws-resources)
- [Configuration](#configuration)
- [Deployment](#deployment)

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
-   **AWS Lambda:** A serverless function that contains the Python/Node.js logic.
-   **AWS Secrets Manager:** A secure storage service for the ClickUp API Token and List ID.
-   **ClickUp API:** The official API for accessing ClickUp data.

### Visual Flow


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
|                     |                      |                       | (4) Get Secrets
|                     |                      |                       |---------------------->[AWS Secrets Manager]
|                     |                      |                       |                      |
|                     |                      |                       |<----------------------| (5) Return Secrets
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

4.  **Fetch Secrets**
    * **Source:** AWS Lambda
    * **Destination:** AWS Secrets Manager
    * **Action:** The function makes a secure, internal call within your AWS environment to retrieve the ClickUp API Token and List ID.

5.  **Return Secrets**
    * **Source:** AWS Secrets Manager
    * **Destination:** AWS Lambda
    * **Action:** The secrets are securely passed back to the running function.

6.  **Request Tasks from ClickUp API**
    * **Source:** AWS Lambda
    * **Destination:** ClickUp API
    * **Action:** The Lambda function makes a server-to-server API request to api.clickup.com, using the fetched secrets for authentication. This call is not subject to CORS rules.

7.  **Return Task Data**
    * **Source:** ClickUp API
    * **Destination:** AWS Lambda
    * **Action:** The ClickUp API returns a JSON object containing the 10 most recent tasks.

8.  **Generate and Return HTML**
    * **Source:** AWS Lambda
    * **Destination:** AWS API Gateway
    * **Action:** The function processes the JSON data, constructs a complete HTML document on the fly, and returns it as the response.

9.  **Display Page**
    * **Source:** AWS API Gateway
    * **Destination:** User's Browser
    * **Action:** The API Gateway forwards the HTML response to the user's browser, which then renders the final page showing the list of recent submissions.

## AWS Resources

Tags in AWS will be:

| Name    | Value                  |
| ------- | ---------------------- |
| Project | kilnops-dropoff-viewer |

## Configuration

All settings are managed via environment variables within the AWS Lambda function's configuration section. This allows for easy updates to things like the ClickUp List ID, bot name, or optional features without changing the code.


## Deployment

The deployment process is managed and specified in the [Deployment Instructions](docs/Deploying.md).