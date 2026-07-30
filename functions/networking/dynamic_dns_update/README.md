# Dynamic DNS Update

## Table of Contents
- [Purpose](#purpose)
- [How It Works](#how-it-works)
- [AWS Infrastructure](#aws-infrastructure)
- [Configuration](#configuration)
- [UDM Configuration](#udm-configuration)
- [Testing](#testing)
- [Deployment](#deployment)

## Purpose

This Lambda function lets a UniFi Dream Machine (UDM) keep one or more Route53
DNS records pointed at its current public IP address, using the router's
built-in Dynamic DNS (DynDNS2 protocol) client. No custom software runs on
the router.

## How It Works

The function is triggered by a `GET /nic/update` request sent directly by the
UDM's DDNS client, proxied through the shared `FacilitiesApi` REST API.

### Components:

*   **UDM DDNS Client:** Built-in client that detects IP changes and calls
    out using the standard DynDNS2 protocol (HTTPS GET with Basic Auth).
*   **AWS API Gateway (`FacilitiesApi`):** Provides the public `/nic/update`
    endpoint, throttled independently from the API's other routes.
*   **AWS Lambda (This Function):** Validates the Basic Auth credentials and
    the requested hostname(s), then upserts the Route53 record(s).
*   **AWS Secrets Manager:** Stores the shared username/password and the list
    of hostnames the credential is allowed to update.
*   **Amazon Route53:** Target hosted zone for the `A` record updates.

### Visual Flow

```
+---------------+      +-----------------+      +---------------------+      +-----------------------+
| UDM DDNS      |      | AWS API Gateway |      | AWS Lambda Function |      | AWS Secrets Manager   |
| Client        |      | (/nic/update)   |      | (This Function)     |      | (Router Credential)   |
+---------------+      +-----------------+      +---------------------+      +-----------------------+
        |                      |                       |                              |
(1) IP Change Detected -----> | (2) Send GET Request  |                              |
        |                      |---------------------->| (3) Trigger Function  |                              |
        |                      |                       |---------------------->| (4) Get Credential      |
        |                      |                       |<----------------------| (5) Return Credential   |
        |                      |                       |                              |
        |                      |                       | (6) Verify Auth & Hostnames |
        |                      |                       |                              |
        |                      |                       | (7) UPSERT A Record(s) ----> [Route53]
        |                      |                       |<--------------------------------|
        |                      |                       |                              |
|<-----------------------------------------------------| (8) Return DynDNS2 Response  |
```

### Step-by-Step Data Flow:

1. **IP Change Detected:** The UDM's built-in DDNS client detects that its
   public IP has changed (or runs on its normal periodic interval).
2. **Send GET Request:** The UDM sends a `GET /nic/update?hostname=...&myip=...`
   request with a Basic Auth header to the `FacilitiesApi` endpoint.
3. **Trigger Function:** API Gateway proxies the request to this Lambda.
4. **Fetch Credential:** The function retrieves the `username`, `password`,
   and `allowed_hostnames` values from the configured Secrets Manager secret.
5. **Verify Auth:** The supplied username/password are compared to the
   secret's values using `hmac.compare_digest` (constant-time comparison).
6. **Verify Hostnames:** The `hostname` query parameter (a comma-separated
   list, per the DynDNS2 multi-hostname convention) is checked against
   `allowed_hostnames`. If any requested hostname isn't allowed, the entire
   request is rejected (`nohost`) rather than partially applied.
7. **Update Route53:** For each allowed hostname, the function calls
   `route53:ChangeResourceRecordSets` to UPSERT an `A` record pointing at
   `myip`. This call is idempotent, so no IP-change cache is needed.
8. **Return Response:** A DynDNS2-style response code is returned per
   hostname, newline-separated (e.g. `good 1.2.3.4`, `badauth`, `nohost`,
   `dnserr`).

## AWS Infrastructure

The core infrastructure is defined in `templates/networking.yaml` and
consists of the Lambda function and its associated IAM Role. The
`/nic/update` route, its dedicated throttling `MethodSettings`, and the
Lambda invoke permission are defined in the root `template.yaml` alongside
the other `FacilitiesApi` routes.

### Tags

| Name        | Value                       |
|-------------|-----------------------------|
| Application | facilities-automation-hub   |
| Project     | networking:dynamic-dns      |
| Workspace   | facilities                  |

## Configuration

The function reads its configuration from environment variables:

| Variable          | Description                                                        |
|-------------------|---------------------------------------------------------------------|
| `DDNS_SECRET_NAME` | Name of the Secrets Manager secret holding the router credential.   |
| `HOSTED_ZONE_ID`   | The Route53 Hosted Zone ID to update.                              |

The Secrets Manager secret (`ddns/router-credential`, or scoped per-stage)
must contain:

```json
{
  "username": "...",
  "password": "...",
  "allowed_hostnames": ["shop.asmbly.org", "vpn.asmbly.org"]
}
```

**Keep `allowed_hostnames` in sync with the `DdnsHostnames` CloudFormation
parameter** (the IAM-level allowlist) — see `templates/networking.yaml`. A
mismatch fails safe: Route53 rejects the update with `AccessDenied` rather
than allowing an unauthorized record change.

## UDM Configuration

Configure the UDM's Dynamic DNS client (Settings → Internet → Dynamic DNS)
with:

| Field     | Value                                                        |
|-----------|---------------------------------------------------------------|
| Service   | `custom`                                                       |
| Hostname  | `shop.asmbly.org,vpn.asmbly.org` (comma-separated)             |
| Username  | Value of `username` in the Secrets Manager secret              |
| Password  | Value of `password` in the Secrets Manager secret              |
| Server    | The `FacilitiesApi` invoke URL, e.g. `<api-id>.execute-api.<region>.amazonaws.com/nic/update` |

## Testing

Unit tests live in `tests/test_lambda_function.py` and run with `pytest`, per
[Running Tests](../../../docs/CONTRIBUTING.md#running-tests).

## Deployment

This function is deployed as part of the main SAM application. See the root
`Deploying.md` for more details.
