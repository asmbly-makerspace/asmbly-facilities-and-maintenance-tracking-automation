import os
import sys
import json
import requests

def update_slack_manifest(api_url, app_id, config_token):
    """
    Fetches, updates, and pushes a Slack app manifest.
    """
    # Prepare the authorization header required for all Slack API calls.
    headers = {"Authorization": f"Bearer {config_token}"}
    # Construct the full URL for Slack's Event Subscriptions. This is where Slack will send events.
    event_subscription_url = f"{api_url}/slack/events"
    print(f"New Event Subscription URL: {event_subscription_url}")

    # 1. Fetch the current manifest
    print("Fetching current Slack app manifest...")
    try:
        # Use the apps.manifest.export method to get the current app configuration.
        export_url = f"https://slack.com/api/apps.manifest.export?app_id={app_id}"
        response = requests.get(export_url, headers=headers)
        # Raise an exception for bad status codes (4xx or 5xx).
        response.raise_for_status()
        export_data = response.json()

        if not export_data.get("ok"):
            print(f"::error::Failed to fetch Slack manifest: {export_data.get('error', 'Unknown error')}")
            sys.exit(1)

        manifest = export_data["manifest"]
        print("Successfully fetched manifest.")

    except requests.exceptions.RequestException as e:
        # Handle network-level errors during the API call.
        print(f"::error::HTTP request failed while fetching manifest: {e}")
        sys.exit(1)

    # 2. Update the manifest JSON
    print("Updating manifest with new request_url...")
    try:
        manifest["features"]["event_subscriptions"]["request_url"] = event_subscription_url
    except KeyError:
        # This error occurs if the manifest doesn't have event subscriptions enabled.
        print("::error::Could not find 'features.event_subscriptions.request_url' in the manifest.")
        sys.exit(1)

    # 3. Push the updated manifest
    print("Pushing updated manifest to Slack...")
    try:
        update_url = "https://slack.com/api/apps.manifest.update"
        # The manifest must be provided as a JSON-encoded string in the payload.
        payload = {"app_id": app_id, "manifest": json.dumps(manifest)}
        response = requests.post(update_url, headers=headers, json=payload)
        # Raise an exception for bad status codes.
        response.raise_for_status()
        update_data = response.json()

        if not update_data.get("ok"):
            print(f"::error::Failed to update Slack manifest: {update_data.get('error', 'Unknown error')}")
            print(f"Response: {update_data}")
            sys.exit(1)

        print("Slack manifest updated successfully!")

    except requests.exceptions.RequestException as e:
        print(f"::error::HTTP request failed while updating manifest: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # This script is designed to be run in a CI/CD environment (like GitHub Actions),
    # where configuration is passed via environment variables.
    slack_app_id = os.environ["SLACK_MAINTENANCE_BOT_APP_ID"]
    slack_token = os.environ["SLACK_APP_CONFIG_TOKEN"]
    # The API Gateway URL is passed directly from the previous workflow job.
    api_gateway_url = os.environ["FACILITIES_API_URL"]

    # If the URL was provided, proceed to update the Slack manifest.
    if api_gateway_url:
        update_slack_manifest(api_gateway_url, slack_app_id, slack_token)
    else:
        print("::error::FACILITIES_API_URL environment variable not set or empty.")
        sys.exit(1)