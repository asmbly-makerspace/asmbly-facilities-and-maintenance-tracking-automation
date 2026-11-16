# Manual QA: Safe exception text

Acceptance steps for `feature/safe-exception-text`, by story, so each check maps back to
#142, #143, #144 and #145 (epic #141; the pull request also closes #95 and #83).

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`.

> Automated checks already passed on the branch (integration gate): pytest 1831 passed
> (8 subtests), cfn-lint no errors (4 W3005 warnings in `template.yaml` at lines 582, 592
> and 605, the same on `origin/stage`), sam validate pass, sam build pass. Nothing was
> skipped. These steps cover what a person should see in Slack, ClickUp, Neon and
> CloudWatch.

## Prerequisites

- **Admin actions: none.** The checkpoint lists no admin actions. This work changes no
  template, no deploy role (`template-cicd.yaml`) and no `configs/` file, so the normal
  stage deploy is all it needs.
- The stage API address:

  ```bash
  export AWS_PROFILE=asmbly
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  ```

- AWS credentials for account 110104886034 (us-east-2) that can read CloudWatch Logs and
  invoke the stage functions named below. Steps 7, 8 and 9 use `aws lambda invoke`: it
  runs the function and changes nothing in AWS. You also need `jq`. Run every command
  from the repository root, because the payloads are built from the functions' test
  fixtures.
- **Stage talks to the same vendors as prod.** The stage functions use the same Slack bot
  (`slack-maintenancebot-token`), the same channel IDs (`configs/router_config.json` and
  `SLACK_CHANNEL_ID`), the same ClickUp token (`clickup/api/token`), the same Neon secret
  (`prod/neon_token`) and the same Discourse bot. So the steps use made-up task IDs, a
  made-up email and a timestamp that has no message, and nothing real changes. Steps 11
  and 12 change real records and are marked **optional**.
- Access to:
  - Slack, with permission to post in the problem-report channel (`C063LH7MB45`) and the
    purchase-request channel (`C026YVA7TK3`);
  - for step 11, a Neon test account; for step 12, the ClickUp Purchase Requests list
    (`901310302436`);
  - the log groups `/asmbly/lambda/NewPurchaseRequestReceivedFunction-stage`,
    `/asmbly/lambda/ProblemReport-ReactionFunction-stage`,
    `/asmbly/lambda/PurchaseRequest-ReactionFunction-stage`,
    `/asmbly/lambda/facilities-slack-event-router-stage`,
    `/asmbly/lambda/PMReminderBotFunction-stage` and
    `/asmbly/lambda/NewWaiverCompletedFunction-stage`.
- To read a log group (records take a few seconds to arrive):

  ```bash
  aws logs tail /asmbly/lambda/<Function>-stage --region us-east-2 --since 10m
  ```

  Records written through `logging` start with `[INFO]`, `[WARNING]` or `[ERROR]`. A line
  with no level is a plain `print`. Each step's "must not" check pipes the same command
  through `grep`, and prints `CLEAN` when nothing forbidden is there.
- None of these routes checks its caller, before or after this change (this work adds no
  caller check). So the requests below carry no Slack signature, ClickUp signature or
  secret.

Third-party webhooks (Slack's Event Subscriptions, `/reorder` and Interactivity, ClickUp,
Smartwaiver) point at prod, so the webhook steps below send the request by hand with
`curl`. Don't react in Slack or run `/reorder` for these checks: that runs prod's code
and can change real tasks.

---

## #142: ClickUp failures are logged without vendor bodies or personal data (phase 1)

1. Send the new-purchase-request webhook for a ClickUp task that doesn't exist (the
   fixture with its task ID replaced):

   ```bash
   jq '.payload.id = "qa142missing"' \
     functions/purchase_request/new_purchase_request_received/tests/fixtures/clickup_payload.json \
     | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/purchase-request/new" \
         -H 'Content-Type: application/json' -d @-
   ```

   **Expect:** `HTTP 500` with the body
   `"An error occurred while processing the purchase request."` and no ClickUp text
   (#143). Nothing is posted in Slack. In
   `/asmbly/lambda/NewPurchaseRequestReceivedFunction-stage`:
   - `[ERROR] ClickUp GET task/qa142missing failed with HTTP <status> <reason> (ECODE=<code>)`.
     ClickUp picks the status (401 or 404) and the code (or `None`).
   - `[ERROR] Failed to process purchase request for task 'qa142missing'`, with a
     traceback whose last line is
     `ValueError: ClickUp API HTTP Error: <status> <reason> - GET task/qa142missing (ECODE=<code>)`.
   - The traceback holds that one exception only: no
     `During handling of the above exception` and no `requests.exceptions.HTTPError`.

   It must not contain ClickUp's answer or the request URL:

   ```bash
   aws logs tail /asmbly/lambda/NewPurchaseRequestReceivedFunction-stage --region us-east-2 --since 10m \
     | grep -E 'Details:|Response body:|"err"|api\.clickup\.com|During handling|HTTPError' || echo CLEAN
   ```

2. Send the same webhook with a task ID that isn't a plain ID (it carries a query string):

   ```bash
   jq '.payload.id = "qa142odd?x=1"' \
     functions/purchase_request/new_purchase_request_received/tests/fixtures/clickup_payload.json \
     | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/purchase-request/new" \
         -H 'Content-Type: application/json' -d @-
   ```

   **Expect:** the same `HTTP 500` and body as step 1. The ClickUp lines name the path as
   `<invalid>`: `[ERROR] ClickUp GET <invalid> failed with HTTP <status> <reason> (ECODE=<code>)`,
   and the traceback ends with
   `ValueError: ClickUp API HTTP Error: <status> <reason> - GET <invalid> (ECODE=<code>)`.
   The handler's own line, `Failed to process purchase request for task 'qa142odd?x=1'`,
   repeats the ID the caller sent; that is expected. Must not:

   ```bash
   aws logs tail /asmbly/lambda/NewPurchaseRequestReceivedFunction-stage --region us-east-2 --since 10m \
     | grep -E 'task/qa142odd|api\.clickup\.com|Details:|Response body:|"err"' || echo CLEAN
   ```

3. In Slack, post this as a new message (not a thread reply) in the problem-report
   channel (`C063LH7MB45`), and again in the purchase-request channel (`C026YVA7TK3`). The
   ClickUp link is made up:

   ```text
   QA test for safe-exception-text, please ignore and don't react: https://app.clickup.com/t/qa142fake
   ```

   For each message, use **Copy link** and turn the link's last part into a Slack
   timestamp:

   ```bash
   LINK='https://asmbly-makerspace.slack.com/archives/C063LH7MB45/p1760700000123456'  # paste yours
   P=${LINK##*/p}; P=${P%%\?*}; echo "${P:0:10}.${P:10}"   # prints 1760700000.123456
   ```

   Set `PR_TS` to the problem-report message's timestamp and `PU_TS` to the
   purchase-request message's. Don't react to either message in Slack: prod's code would
   handle the reaction.

   **Expect:** two messages, two timestamps of the form `1760700000.123456`.

4. Send a `loading` reaction on the problem-report message to the stage router. The
   envelope is the one in
   `functions/problem_report/slack_reaction_webhook/tests/test_slack_reaction_webhook.py`,
   with the real channel, your timestamp, and a reaction from
   `configs/reactions_problem_report.json`:

   ```bash
   jq -n --arg ts "$PR_TS" '{token: "qa-verification-token", team_id: "TQA0000000",
     event_id: "EvQA142PR", type: "event_callback",
     event: {type: "reaction_added", reaction: "loading", user: "UQA0000000",
             item: {type: "message", channel: "C063LH7MB45", ts: $ts}}}' \
     | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/slack/events" \
         -H 'Content-Type: application/json' -d @-
   ```

   **Expect:** `HTTP 200` with `"Request forwarded successfully."`, and
   `/asmbly/lambda/facilities-slack-event-router-stage` shows
   `Invoking target Lambda: ...:function:ProblemReport-ReactionFunction-stage`. In
   `/asmbly/lambda/ProblemReport-ReactionFunction-stage`, in this order:
   - `[INFO] Received event: type=reaction_added reaction=loading channel=C063LH7MB45 ts=<PR_TS> event_id=EvQA142PR`
     (IDs only, not the whole event);
   - `[INFO] Base processing result: status=success task_id=qa142fake reaction=loading reason=None`;
   - `[INFO] Updating ClickUp task qa142fake to status 'in progress'`;
   - `[ERROR] ClickUp PUT task/qa142fake failed with HTTP <status> <reason> (ECODE=<code>)`;
   - one `[ERROR] Unexpected error processing reaction for event 'EvQA142PR'`, with a
     traceback whose last line is
     `ValueError: ClickUp API HTTP Error: <status> <reason> - PUT task/qa142fake (ECODE=<code>)`.

   No ClickUp task changes, and nothing is posted on Discourse (the run stops at the
   ClickUp error). The log must not contain the verification token, the team ID, the
   message text, or ClickUp's answer:

   ```bash
   aws logs tail /asmbly/lambda/ProblemReport-ReactionFunction-stage --region us-east-2 --since 10m \
     | grep -E 'qa-verification-token|TQA0000000|please ignore|Details:|Response body:|"err"|api\.clickup\.com|During handling|HTTPError' \
     || echo CLEAN
   ```

5. Send the same reaction on the purchase-request message (a reaction from
   `configs/reactions_purchase_request.json`):

   ```bash
   jq -n --arg ts "$PU_TS" '{token: "qa-verification-token", team_id: "TQA0000000",
     event_id: "EvQA142PU", type: "event_callback",
     event: {type: "reaction_added", reaction: "loading", user: "UQA0000000",
             item: {type: "message", channel: "C026YVA7TK3", ts: $ts}}}' \
     | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/slack/events" \
         -H 'Content-Type: application/json' -d @-
   ```

   **Expect:** `HTTP 200` with `"Request forwarded successfully."`. In
   `/asmbly/lambda/PurchaseRequest-ReactionFunction-stage`:
   - `[INFO] Received event: type=reaction_added reaction=loading channel=C026YVA7TK3 ts=<PU_TS> event_id=EvQA142PU`;
   - `[ERROR] ClickUp PUT task/qa142fake failed with HTTP <status> <reason> (ECODE=<code>)`;
   - one `[ERROR] Unexpected error processing reaction for event 'EvQA142PU'`, with a
     traceback whose last line is
     `ValueError: ClickUp API HTTP Error: <status> <reason> - PUT task/qa142fake (ECODE=<code>)`;
   - no `Processing result:` line (it is written only after a successful update).

   Must not (prints `CLEAN`):

   ```bash
   aws logs tail /asmbly/lambda/PurchaseRequest-ReactionFunction-stage --region us-east-2 --since 10m \
     | grep -E 'qa-verification-token|TQA0000000|please ignore|Details:|Response body:|"err"|api\.clickup\.com|During handling|HTTPError' \
     || echo CLEAN
   ```

   Then delete both test messages from Slack.

## #143: Error replies and the /reorder error screen show a plain message (phase 2)

Steps 1 and 2 already check `/purchase-request/new`'s reply when ClickUp fails.

6. Send `/purchase-request/new` a body that isn't JSON:

   ```bash
   curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/purchase-request/new" \
     -H 'Content-Type: application/json' -d 'this is not json'
   ```

   **Expect:** `HTTP 500` with `"An error occurred while processing the purchase request."`,
   and not the parser's message (`Expecting value: ...`). Nothing is posted in Slack. In
   `/asmbly/lambda/NewPurchaseRequestReceivedFunction-stage`:
   `[ERROR] Failed to process purchase request for task None`, with a traceback ending in
   `json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)`.

7. Invoke the purchase-request reaction function directly, so you can read its reply (the
   router invokes it asynchronously and never shows the reply). The reaction is on a
   timestamp with no message (`1000000000.000100` is September 2001, before the channel
   existed), so the function fails before it touches ClickUp:

   ```bash
   aws lambda invoke --function-name PurchaseRequest-ReactionFunction-stage --region us-east-2 \
     --cli-binary-format raw-in-base64-out \
     --payload "$(jq -nc '{token: "qa-verification-token", team_id: "TQA0000000",
       event_id: "EvQA143PU", type: "event_callback",
       event: {type: "reaction_added", reaction: "loading", user: "UQA0000000",
               item: {type: "message", channel: "C026YVA7TK3", ts: "1000000000.000100"}}}')" \
     /tmp/qa-143-pu.json && cat /tmp/qa-143-pu.json; echo
   ```

   **Expect:** the CLI prints `"StatusCode": 200` (the function ran), and the reply is
   `{"statusCode": 500, "body": "\"Internal server error.\""}`, with no `RuntimeError` and
   no `Could not find message`. In `/asmbly/lambda/PurchaseRequest-ReactionFunction-stage`:
   `[ERROR] Unexpected error processing reaction for event 'EvQA143PU'`, with a traceback
   ending in `RuntimeError: Could not find message from reaction event.` Nothing changes in
   ClickUp.

8. The same for the problem-report reaction function:

   ```bash
   aws lambda invoke --function-name ProblemReport-ReactionFunction-stage --region us-east-2 \
     --cli-binary-format raw-in-base64-out \
     --payload "$(jq -nc '{token: "qa-verification-token", team_id: "TQA0000000",
       event_id: "EvQA143PR", type: "event_callback",
       event: {type: "reaction_added", reaction: "loading", user: "UQA0000000",
               item: {type: "message", channel: "C063LH7MB45", ts: "1000000000.000100"}}}')" \
     /tmp/qa-143-pr.json && cat /tmp/qa-143-pr.json; echo
   ```

   **Expect:** `{"statusCode": 500, "body": "\"Internal server error.\""}`. In
   `/asmbly/lambda/ProblemReport-ReactionFunction-stage`:
   `[ERROR] Unexpected error processing reaction for event 'EvQA143PR'`, with a traceback
   ending in `RuntimeError: Could not find message from reaction event.` Nothing changes
   in ClickUp or on Discourse.

You can't trigger the `/reorder` error modals or the PM reminder's failure reply
(`"Error: the PM reminder run failed."`) on stage. Slack's `/reorder` points at prod, and
both need a broken secret or ClickUp token. The automated tests cover them
(`test_slack_slash_reorder_lambda_function.py`, `test_pm_bot_reminder_lambda_function.py`),
and the modal texts are in `functions/purchase_request/slack_slash_reorder/README.md`.

## #144: Neon, Discourse and handler logs carry no member emails or vendor bodies (phase 3)

9. Check a PM reminder run on stage. Either read the first scheduled run after the deploy
   (Saturdays 04:30 UTC, rule `pm-reminder-bot-schedule-stage`), or start a run by hand.
   Stage has `DRY_RUN=true`, so the run reads ClickUp and posts nothing to Slack. A run
   can take up to three minutes, because it waits a second or two per task:

   ```bash
   aws lambda invoke --function-name PMReminderBotFunction-stage --region us-east-2 \
     --cli-binary-format raw-in-base64-out --payload '{}' --cli-read-timeout 200 \
     /tmp/qa-144-pm.json && cat /tmp/qa-144-pm.json; echo
   ```

   **Expect:** `{"statusCode": 200, "body": "\"Successfully processed <n> tasks.\""}`, or
   `"No tasks to process."` when no task is due. Nothing is posted in Slack. In
   `/asmbly/lambda/PMReminderBotFunction-stage`, these `[INFO]` records:
   `PM reminder run started`, `Found <n> overdue tasks.`, `Found <n> upcoming tasks.`,
   `Attempting to send message to Slack channel: #<channel>` for each task, and last
   `PM reminder run finished: <n> tasks processed`. With no tasks due, the last line is
   `No tasks found meeting the criteria. Exiting successfully.` instead. The dry-run
   preview still appears as plain lines with no level (`--- DRY RUN MODE ---`,
   `Would send to channel: ...`, `Message: ...`). That comes from stage's `DRY_RUN` and is
   expected. The old banners must be gone (for a scheduled run, set `--since` far enough
   back to reach it, for example `--since 3d`):

   ```bash
   aws logs tail /asmbly/lambda/PMReminderBotFunction-stage --region us-east-2 --since 15m \
     | grep -E -- '--- HANDLER STARTED ---|--- HANDLER FINISHED SUCCESSFULLY ---|--- FATAL ERROR' || echo CLEAN
   ```

10. Send the waiver webhook with an email that matches no Neon account. The payload uses
    the fixture's `signed_date`, a made-up email and a made-up waiver ID:

    ```bash
    jq --arg email "qa-no-such-member-$(date +%s)@example.com" \
      '{email: $email, signed_date, waiver_id: "qa144notfound"}' \
      functions/administrative/new_waiver_completed/tests/fixtures/new_waiver_received.json \
      | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/waiver/new" \
          -H 'Content-Type: application/json' -d @-
    ```

    **Expect:** `HTTP 404`. The body echoes the email you sent
    (`"Account not found for email: ..."`). That reply comes from the waiver function,
    which this work doesn't change. Nothing changes in Neon. In
    `/asmbly/lambda/NewWaiverCompletedFunction-stage`:
    `[INFO] Updating NeonCRM waiver date for waiver qa144notfound to 11/08/2025`, then
    `[WARNING] No NeonCRM account matches the searched email`, then
    `[INFO] Clean exit: No NeonCRM account found for waiver qa144notfound. No update performed.`
    and `Webhook processing completed with status code: 404`. If Neon's search fails
    instead, the line is
    `[ERROR] Error searching for NeonCRM account: <ErrorClass> (status <code or no response>)`
    with no Neon body. The reply is still 404 in that case, because a failed search counts
    as "no account" (known; listed in the briefing). The email must not appear in the log:

    ```bash
    aws logs tail /asmbly/lambda/NewWaiverCompletedFunction-stage --region us-east-2 --since 10m \
      | grep -E 'qa-no-such-member|@example\.com' || echo CLEAN
    ```

11. **Optional, changes a Neon test account:** repeat step 10 with the email of a Neon
    test account that the team keeps for testing. This sets that account's waiver-date
    custom field (ID `179`) to 11/08/2025.

    ```bash
    NEON_TEST_EMAIL='...'   # the test account's Email 1
    jq --arg email "$NEON_TEST_EMAIL" '{email: $email, signed_date, waiver_id: "qa144update"}' \
      functions/administrative/new_waiver_completed/tests/fixtures/new_waiver_received.json \
      | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/waiver/new" \
          -H 'Content-Type: application/json' -d @-
    ```

    **Expect:** `HTTP 200`. The body echoes the email, which is the same unchanged reply
    as step 10. In Neon, the test account's waiver date reads 11/08/2025. In
    `/asmbly/lambda/NewWaiverCompletedFunction-stage`:
    `[INFO] Found NeonCRM account ID: <id>`,
    `[INFO] Waiver qa144update matches NeonCRM account <id>`, then
    `[INFO] Updated custom field 179 for NeonCRM account <id>`. If the update fails, the
    line is `[ERROR] Error updating NeonCRM account <id>: <ErrorClass> (status <code>)`
    with no Neon body, and the reply is still 200 (#99, out of scope). So check the Neon
    record, not the status code. The email must not appear in the log:

    ```bash
    aws logs tail /asmbly/lambda/NewWaiverCompletedFunction-stage --region us-east-2 --since 10m \
      | grep -F "$NEON_TEST_EMAIL" || echo CLEAN
    ```

12. **Optional, posts in the purchase-request channel and changes a ClickUp task:** the
    new-purchase-request success path. Create a task named `QA test: safe-exception-text`
    in the ClickUp Purchase Requests list. Prod's ClickUp webhook posts it in
    `C026YVA7TK3` as usual. Copy the task's ID (the end of its URL,
    `https://app.clickup.com/t/<id>`), then send stage the same webhook:

    ```bash
    TASK_ID='...'   # the test task's ID
    jq --arg id "$TASK_ID" '.payload.id = $id | .payload.name = "QA test: safe-exception-text"
        | .payload.text_content = "QA test, please ignore"' \
      functions/purchase_request/new_purchase_request_received/tests/fixtures/clickup_payload.json \
      | curl -s -w '\nHTTP %{http_code}\n' -X POST "$STAGE_API_URL/purchase-request/new" \
          -H 'Content-Type: application/json' -d @-
    ```

    **Expect:** `HTTP 200` with `"Successfully processed purchase request."`. A second
    Purchase Bot post appears in `C026YVA7TK3` ("New purchase request received",
    "Item Requested: QA test: safe-exception-text"). The task's Slack post URL field
    (`slack_post_field_id` in `configs/clickup_facilities_purchaseRequests.json`) now
    links to that second post. In `/asmbly/lambda/NewPurchaseRequestReceivedFunction-stage`,
    these `[INFO]` records name the task in quotes:
    `Generated Slack permalink for task '<id>': https://asmbly-makerspace.slack.com/archives/C026YVA7TK3/p...`,
    `Attempting to set custom field 5bfc5aac-d5cd-44d5-ac27-71016046e63c on task '<id>'.`,
    then `Successfully updated task '<id>' with Slack post URL.` No line dumps ClickUp's
    answer (it holds names and emails):

    ```bash
    aws logs tail /asmbly/lambda/NewPurchaseRequestReceivedFunction-stage --region us-east-2 --since 10m \
      | grep -E 'Received response from ClickUp|"custom_fields"|"email"' || echo CLEAN
    ```

    Then delete both Slack posts and the test task.

You can't trigger Discourse's failure lines (`Discourse <METHOD> <path> failed ...`) on
stage without changing a real ClickUp task and posting on the live forum.
`layers/common/python/tests/test_discourse.py` covers them.

## #145: A hung ClickUp, Slack or Neon call fails within 8 seconds (phase 3)

No visible surface: a person can't make ClickUp, Slack or Neon hang on demand, so the
automated tests cover the 8-second limit. Steps 1, 4, 9 and 10 make the same calls with
the limit in place, and must still end as described there.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
