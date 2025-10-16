# Slack Reaction Webhook

This Lambda function acts as a webhook for reactions on Slack posts in the #purchase-requests channel. When a specific reaction is added to a message containing a ClickUp task URL, this function updates the status of that ClickUp task.

## Functionality

1.  **Receives Slack Events**: The function is triggered by HTTP POST requests from Slack's Event API, specifically for `reaction_added` events.
2.  **Parses ClickUp Task ID**: It extracts the ClickUp task ID from the message that was reacted to.
3.  **Maps Reactions to Statuses**: It maps the Slack reaction emoji to a corresponding ClickUp task status.
4.  **Updates ClickUp Task**: It uses the ClickUp API to update the status of the identified task.

### Supported Reactions and Statuses

| Reaction Emoji | ClickUp Status |
| --- | --- |
| :loading: | In Review |
| :truck: | Purchased |
| :house: | Delivered |
| :no_entry_sign: | Declined |
| :white_check_mark: | Closed |

## Deployment

The function is deployed as part of the `purchase_request` serverless application. See the main `README.md` for deployment instructions.
