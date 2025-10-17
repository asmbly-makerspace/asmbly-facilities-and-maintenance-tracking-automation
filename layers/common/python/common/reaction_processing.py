import re
from . import aws, clickup
from slack_sdk import WebClient

def process_base_reaction(event_body, reaction_to_status, slack_secret_name, clickup_secret_name):
    """
    Handles the core logic shared by all reaction handlers.
    - Fetches secrets
    - Gets Slack message history
    - Parses ClickUp task ID
    - Updates ClickUp task status
    Returns a dictionary with results for further processing.
    """
    slack_event = event_body.get("event", {})
    reaction = slack_event.get("reaction")

    if reaction not in reaction_to_status:
        # Return a simple status if the reaction is irrelevant
        return {"status": "ignored", "reason": f"Irrelevant reaction: {reaction}"}

    # Fetch secrets and APIs
    slack_bot_token = aws.get_secret(slack_secret_name, "SLACK_MAINTENANCE_BOT_TOKEN")
    clickup_api_token = aws.get_secret(clickup_secret_name, "CLICKUP_API_TOKEN")
    slack_client = WebClient(token=slack_bot_token)

    # Get Slack message history
    item = slack_event.get("item", {})
    history = slack_client.conversations_history(
        channel=item.get("channel"), latest=item.get("ts"), inclusive=True, limit=1
    )

    if not history.get("messages"):
        raise RuntimeError("Could not find message from reaction event.")

    message_text = history["messages"][0].get("text", "")
    match = re.search(r"https://app\.clickup\.com/t/(\w+)", message_text)

    if not match:
        return {"status": "ignored", "reason": "No ClickUp task URL found in the message."}

    task_id = match.group(1)
    new_status_name = reaction_to_status[reaction]

    # Update ClickUp task
    payload = {"status": new_status_name}
    clickup.update_task(clickup_api_token, task_id, payload)

    # Return useful data for any specific logic that follows
    return {
        "status": "success",
        "task_id": task_id,
        "new_status": new_status_name,
        "reaction": reaction,
        "message_text": message_text
    }