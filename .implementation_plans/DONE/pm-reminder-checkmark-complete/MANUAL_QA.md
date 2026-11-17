# Manual QA: A ✅ on a PM reminder completes its ClickUp task

Acceptance steps for `feature/pm-reminder-checkmark-complete`, by story, so each check
maps back to #162, #163, #164, #165.

Run steps 1 to 14 on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`. Steps 15 to 22 are the
**first prod check**, run after `/promote` deploys to prod.

> Automated checks already passed on the branch: pytest 2246 passed (10 subtests),
> cfn-lint pass (4 W3005 warnings in `template.yaml`, already on stage), sam validate
> pass, sam build pass. These steps cover what a person should see happen in Slack,
> ClickUp and CloudWatch.

## Stage is a dry run: read the logs, not Slack or ClickUp

On stage, `PMReminderReactionFunction-stage` runs with `DRY_RUN=true` (fail closed: only
the exact value `false` writes). It **reads** Slack and ClickUp, the same real reminders
and the same real PM Schedule list as prod, but it **writes nothing**: no ClickUp status
change, no thread reply in Slack, no ClickUp comment, nothing in its table
`PMReminderCompletions-stage`. Its outcome shows only in the CloudWatch log group
`/asmbly/lambda/PMReminderReactionFunction-stage`, for example `Dry run: would complete
task <id> ...` (the `would_complete` result). So every stage step below checks log
lines. The write paths (completion, `duplicate`, the thread reply, the ClickUp comment)
can only be seen in prod: see [First prod check](#first-prod-check).

## Prerequisites

- The admin actions from the briefing that come before testing, done:
  - **First, before this reaches stage:** redeploy `AsmblyFacilitiesMaintTrackingStack-cicd`
    by hand. It adds `PMReminderReactionFunction-{stage,prod}` and their log groups (deploy
    policies) and the table `PMReminderCompletions-{stage,prod}` (data policies; Sid
    `AllowClassListCacheTableReads` renamed `AllowTableReadsAfterCreate`). The stage deploy
    fails without it.
  - Before prod (needed for the first prod check, not for stage):
    - Supply the Slack channel IDs for 3d-printing, ceramics, electronics, lasers,
      metal-shop and textiles in `configs/router_config.json` → `pm_channels` (only
      woodshop-maintenance `C0CJAK1D725` is filled in, so stage tests use that channel).
    - Confirm the Maintenance Bot is in all 7 PM channels with `channels:history`
      (`groups:history` if private), `reactions:read`, `chat:write`,
      `chat:write.customize` and `users:read`.
    - Turn on ClickUp recurrence for Clean Metal Shop Sink (`86a8be2bc`).
  - Optional: one read-only `GET https://api.clickup.com/api/v2/task/86a8eb482` with the
    Lambda's token, to see whether `date_done` survives a recurrence reopen in v2 (decides
    whether the stale check in step 11 can fire on stage; the DynamoDB claim is the guard
    in prod either way).
  - Decide (owner, ClickUp hygiene, not code): possible duplicate tasks "Update iPad"
    (`86acdg2cu`, `86acdg066`) and "Inspect Blades" (`86a88jye1`, `86a88jxn2`).
- The stage API address:

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  ```

- Access to: Slack `#woodshop-maintenance` (`C0CJAK1D725`); the ClickUp PM Schedule list
  (`901310894771`); the CloudWatch log groups
  `/asmbly/lambda/facilities-slack-event-router-stage` (the router) and
  `/asmbly/lambda/PMReminderReactionFunction-stage` (the handler). To read them:

  ```bash
  aws logs tail /asmbly/lambda/facilities-slack-event-router-stage --since 10m --region us-east-2
  aws logs tail /asmbly/lambda/PMReminderReactionFunction-stage --since 10m --region us-east-2
  ```

- Test data:
  - A **current** PM Bot reminder in `#woodshop-maintenance` (the one posted last
    Saturday), with **your own ✅ on it**. Copy its link: the `p…` part is the message
    `ts` without its dot (`p1763100000000100` is `1763100000.000100`).
  - Your Slack member ID (profile → ⋯ → Copy member ID).
  - Add your ✅s before `/promote`. Slack sends real reaction events to the **prod**
    router; once prod routes PM channels, a ✅ completes the task for real.

Third-party webhooks (Slack) point at prod, so the steps below send the Slack event by
hand with `curl` to the stage router (`POST /slack/events`). The router doesn't check its
caller yet (#79), so no signature header is needed. Set up these helpers once, from the
repository root (they need `jq`); the payload is the handler's test fixture with the
channel, `ts`, user and reaction swapped in:

```bash
CHANNEL=C0CJAK1D725
TS=<the current reminder's ts, e.g. 1763100000.000100>
ME=<your Slack member ID>
FIXTURE=functions/facilities/pm_reminder_reaction/tests/fixtures/reaction_added_event.json

payload() {  # payload <channel> <ts> <user> [reaction]
  jq -c --arg c "$1" --arg t "$2" --arg u "$3" --arg r "${4:-white_check_mark}" \
    '.event.item.channel=$c | .event.item.ts=$t | .event.user=$u | .event.reaction=$r' "$FIXTURE"
}
post() {     # post <body>
  curl -s -X POST "$STAGE_API_URL/slack/events" -H 'Content-Type: application/json' -d "$1"; echo
}
```

---

## #162: A ✅ on a PM reminder completes its ClickUp task (phases 2, 4)

1. Send a ✅ event for the current reminder, from you, through the stage router.

   ```bash
   post "$(payload "$CHANNEL" "$TS" "$ME")"
   ```

   **Expect:**
   - Response `"Request forwarded successfully."`
   - Router log `/asmbly/lambda/facilities-slack-event-router-stage`:
     `Received Slack event: type=reaction_added channel=C0CJAK1D725 retry_num=None`, then
     `Invoking target Lambda: …PMReminderReactionFunction-stage`.
   - Handler log `/asmbly/lambda/PMReminderReactionFunction-stage`:
     `Received event: type='reaction_added' reaction='white_check_mark' channel='C0CJAK1D725' ts='<TS>' event_id='Ev1' user='<ME>'`,
     then `Dry run: would complete task <ClickUp ID from the reminder> from reminder <TS> in C0CJAK1D725 for user <ME>`.
   - ClickUp: the task's status and due date are unchanged. Slack: no new reply in the
     reminder's thread.
   - If the handler log shows `Task <id> is already closed` or a `stale` line instead,
     someone already completed the task in ClickUp; pick another current reminder.
2. Check that neither log carries the payload's secrets or text.

   ```bash
   aws logs filter-log-events --log-group-name /asmbly/lambda/facilities-slack-event-router-stage \
     --filter-pattern VERIFICATION_TOKEN_SECRET --start-time $(( ($(date +%s) - 900) * 1000 )) \
     --region us-east-2 --query 'length(events)'
   aws logs filter-log-events --log-group-name /asmbly/lambda/PMReminderReactionFunction-stage \
     --filter-pattern VERIFICATION_TOKEN_SECRET --start-time $(( ($(date +%s) - 900) * 1000 )) \
     --region us-east-2 --query 'length(events)'
   ```

   **Expect:** `0` for both. Reading the step-1 lines by eye: only IDs (event ID, channel
   ID, `ts`, task ID, Slack user ID), never the reminder's text or a person's name.

## #163: Only a current PM reminder completes a task, and only once (phases 2, 3, 4)

3. A reaction other than ✅ on the same reminder.

   ```bash
   post "$(payload "$CHANNEL" "$TS" "$ME" eyes)"
   post "$(payload "$CHANNEL" "$TS" "$ME" heavy_check_mark)"
   ```

   **Expect:** `"Request forwarded successfully."` both times (the router forwards every
   reaction in a PM channel). Handler log, twice: `Ignored event 'Ev1': not a
   white_check_mark reaction`. No `Dry run` line.
4. A ✅ event from a user whose ✅ isn't on the message (a forged event).

   ```bash
   post "$(payload "$CHANNEL" "$TS" U0NOTREAL1)"
   ```

   **Expect:** forwarded; handler log `Ignored event 'Ev1': message <TS> in C0CJAK1D725
   has no white_check_mark from U0NOTREAL1`.
5. A ✅ on a message that isn't a PM reminder. In `#woodshop-maintenance`, add your ✅ to
   a message a person posted, copy its link, and send it as `NOT_REMINDER_TS`.

   ```bash
   post "$(payload "$CHANNEL" "<NOT_REMINDER_TS>" "$ME")"
   ```

   **Expect:** handler log `Ignored event 'Ev1': message <ts> in C0CJAK1D725 is not from
   the PM Bot`. Repeat with the PM Bot's Saturday starter message (the one that explains
   `:white_check_mark:`), with your ✅ on it: **Expect** `Ignored event 'Ev1': message
   <ts> in C0CJAK1D725 is not a PM reminder` if the Maintenance Bot posted it, or the
   `is not from the PM Bot` line otherwise.
6. A ✅ on the task description in the current reminder's thread. Add your ✅ to the PM
   Bot's reply in the thread, copy that reply's link (its `p…` part is the reply's `ts`).

   ```bash
   post "$(payload "$CHANNEL" "<REPLY_TS>" "$ME")"
   ```

   **Expect:** handler log `Ignored event 'Ev1': no top-level message at <REPLY_TS> in
   C0CJAK1D725`.
7. A ✅ in a channel that isn't a PM channel.

   ```bash
   post "$(payload C0NOTPM000 "$TS" "$ME")"
   ```

   **Expect:** response `"No action taken for this reaction."`; router log `No target
   function determined for reaction in channel C0NOTPM000. This may be expected.`;
   nothing new in the handler log.
8. Bad payloads.

   ```bash
   post 'not json'
   post '{}'
   post "$(jq -c 'del(.event.item.channel)' "$FIXTURE")"
   post "$(payload "$CHANNEL" not-a-ts "$ME")"
   ```

   **Expect**, in order:
   - `"Internal server error occurred."`; router log `An unexpected error occurred.` with
     a traceback; nothing forwarded.
   - `"Event ignored."`; router log `Ignoring event that is not 'reaction_added'.`
   - `"Event ignored."`; router log `Event is missing a valid channel ID.`
   - `"Request forwarded successfully."`; handler log `Ignored event 'Ev1': missing or
     malformed message ts`.

   Every response is 200 (the router always answers Slack with 200, so Slack doesn't
   retry). No log line contains the request body.
9. Send step 1's ✅ event again (a second ✅ / a repeated event).

   ```bash
   post "$(payload "$CHANNEL" "$TS" "$ME")"
   ```

   **Expect:** `Dry run: would complete task <id> ...` again, **not** `duplicate`: stage
   never writes its table, so it can't remember step 1. `duplicate` is checked in prod
   (step 17).
10. Confirm the stage table stayed empty.

    ```bash
    aws dynamodb scan --table-name PMReminderCompletions-stage --select COUNT --region us-east-2
    ```

    **Expect:** `"Count": 0`.
11. A ✅ on an **old** reminder: in `#woodshop-maintenance`, find a reminder from an earlier
    Saturday for a task that has been completed since, add your ✅, copy its link.

    ```bash
    post "$(payload "$CHANNEL" "<OLD_TS>" "$ME")"
    ```

    **Expect** one of two, and write down which:
    - `Reminder <OLD_TS> for task <id> is older than its last completion (date_done)` (or
      `date_closed`), then `Dry run: would reply stale to <OLD_TS>`: ClickUp kept the
      completion date, so the stale check works on its own.
    - `Dry run: would complete task <id> from reminder <OLD_TS> ...`: ClickUp clears
      `date_done` on a reopened recurring task. This is the documented best-effort case;
      on stage only ClickUp's dates can catch an old reminder, because the table is empty.
      In prod the completions table catches it (step 22).
12. Optional, if a reminder exists for a task that is closed in ClickUp now (for example a
    task that doesn't repeat, or one closed by hand): add your ✅ and send it.

    ```bash
    post "$(payload "$CHANNEL" "<CLOSED_TASK_TS>" "$ME")"
    ```

    **Expect:** handler log `Task <id> is already closed`, then `Dry run: would reply
    already_closed to <CLOSED_TASK_TS>`.

## #164: The person sees in Slack whether the ✅ worked (phase 5)

13. After steps 1 to 12, open each reminder you used in `#woodshop-maintenance` and its
    thread.

    **Expect:** no new PM Bot reply anywhere (stage posts nothing).
14. Search the handler log for reply lines.

    ```bash
    aws logs filter-log-events --log-group-name /asmbly/lambda/PMReminderReactionFunction-stage \
      --filter-pattern '"would reply"' --start-time $(( ($(date +%s) - 3600) * 1000 )) \
      --region us-east-2 --query 'events[].message'
    aws logs filter-log-events --log-group-name /asmbly/lambda/PMReminderReactionFunction-stage \
      --filter-pattern '"Replied"' --start-time $(( ($(date +%s) - 3600) * 1000 )) \
      --region us-east-2 --query 'length(events)'
    ```

    **Expect:** `Dry run: would reply …` lines only for step 11 (if it was `stale`) and
    step 12 (`already_closed`); none for steps 1 and 9 (`would_complete` logs no reply
    line) or for the ignored events. `0` `Replied` lines. The real replies are checked in
    prod (steps 15, 18 and 22).

## #165: ClickUp shows who marked a PM task done from Slack (phase 6)

No visible surface on stage: the comment is posted only after a real completion, and on
stage (`DRY_RUN=true`) it is skipped without a log line. Checked in prod, step 19.

---

## First prod check

Run these on the **first real ✅ in prod**, after `/promote` deploys and the "Before
prod" admin actions above are done. These are the write paths stage can't show. Watch
`/asmbly/lambda/PMReminderReactionFunction-prod` and
`/asmbly/lambda/facilities-slack-event-router-prod`.

**Emergency stop:** set prod `DRY_RUN` to `'true'` on `PMReminderReactionFunction`
(`templates/facilities.yaml`, `Environment.Variables`) and deploy. Reactions are still
forwarded, but the handler only logs.

15. In `#woodshop-maintenance`, add a ✅ to a current reminder for work that is actually
    done.

    **Expect:** router log `Invoking target Lambda: …PMReminderReactionFunction-prod`;
    handler log `Completed task <id> from reminder <ts> in C0CJAK1D725 for user <U…>`; in
    the reminder's thread, one PM Bot reply (see step 18).
16. In ClickUp, open the task.

    **Expect:** it went to `complete` and ClickUp's recurrence brought it back as "to do"
    with its due date **moved one cycle**. This confirms that API v2 `PUT /task`
    `status=complete` reopens a recurring task with its next due date (admin action).
17. From another Slack account, add a second ✅ to the same reminder.

    **Expect:** handler log `Task <id>: duplicate for reminder <ts>`: one `Completed task`
    line and one `duplicate` line in total. The due date in ClickUp moved one cycle only.
    No second thread reply, no second ClickUp comment.
18. In Slack, open the reminder's thread.

    **Expect:** exactly one `Marked done in ClickUp. Next due <date>` (the PM Bot's own
    description reply may be there too), and `<date>` (an Austin date like `Wed Nov 25`)
    **matches the task's new due date in ClickUp**. For a recurring task whose `Frequency`
    field is unset, check it is not told `This task doesn't repeat, so it's now closed.`
19. In ClickUp, open the task's activity.

    **Expect:** exactly one comment, `Marked done from Slack by <display name> on <Austin
    time>.`, with a `Reminder:` link that opens the reminder in Slack. It shows as written
    by the owner of the ClickUp API token. `Slack user U…` in place of the name means the
    Maintenance Bot lacks `users:read`.
20. Ask the task's assignees and watchers whether ClickUp notified them of that comment.

    **Expect:** record what happened. The comment is sent with `notify_all` false, which
    only stops ClickUp notifying the token's owner; assignees and watchers may still get
    the usual comment notification.
21. **Required before relying on the feature:** check that the reopened task's `date_done`
    and `date_closed` are not later than its next reminder (a read-only `GET
    https://api.clickup.com/api/v2/task/<id>` with the Lambda's token, or the task in
    ClickUp). The completion record is safe to read:

    ```bash
    aws dynamodb get-item --table-name PMReminderCompletions-prod \
      --key '{"pk":{"S":"task#<id>"}}' --region us-east-2
    ```

    **Expect:** `date_done` / `date_closed` empty or earlier than the next reminder; the
    record has `state` `done` and `reminder_ts` = the step-15 reminder. If ClickUp stamps
    them on reopening, every later ✅ would be `stale`: stop and report.
22. Add a ✅ to **last week's** reminder for the same task, then remove it and add it again.

    **Expect:** handler log `Task <id>: stale for reminder <ts>` (or the `older than its
    last completion` line); one thread reply `Already marked done on <date>; nothing
    changed.`; the second ✅ adds no reply (`Reminder <ts> in C0CJAK1D725 already got an
    already-done reply`). No ClickUp change, no comment.

---

## Automated checks (optional, to run them again locally)

```bash
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
