---
phase_id: 3
title: Complete once per cycle
epic: 7
implements: [163]
depends_on: [2]
domain: [lambda, infra, docs]
estimated_size: M
---

# Phase 3: Complete once per cycle

> **Status:** [ ] Pending

## Required reading

- `CLAUDE.md`; this plan's `README.md` (Decisions 6 and 7).
- Phase 2's hand-off and `functions/facilities/pm_reminder_reaction/lambda_function.py`.
- A table to copy: `ClassPhotoClassListCacheTable` in `templates/classes.yaml` (name,
  billing, tags, item-level IAM), and how
  `functions/classes/class_photo_upload_api/` tests DynamoDB with `moto`.
- The router's lazy, cached boto3 client (`_get_ssm_client` in
  `functions/routers/slack_event_subscriptions/lambda_function.py`): copy it for the
  DynamoDB resource.
- `template-cicd.yaml`, `GitHubDeployPolicystageData` and `GitHubDeployPolicyprodData`
  (`AllowDynamoDBTableManagement`, `AllowClassListCacheTableReads`).
- DynamoDB conditional writes: `UpdateItem` with `ConditionExpression`,
  `ConditionalCheckFailedException`.

## Goal

A task is completed once per maintenance cycle. Two ✅s on the same reminder, the same
event delivered twice, or a Lambda retry complete it once. A ✅ on a reminder posted
before the task's most recent completion changes nothing. A ClickUp failure leaves the
task and the record unchanged so a later ✅ can try again, and an uncertain failure (the
update may have landed) can't lead to a second completion.

## Files to create

None.

## Files to modify

- `functions/facilities/pm_reminder_reaction/lambda_function.py`: the claim around the
  ClickUp update, the dry-run read, two new outcomes.
- `functions/facilities/pm_reminder_reaction/tests/test_pm_reminder_reaction.py`: moto
  tests for each path below.
- `functions/facilities/pm_reminder_reaction/README.md`: a "Completed once" section.
- `templates/facilities.yaml`: the table, the environment variable, the IAM statement.
- `template-cicd.yaml`: the table in both data policies.
- `docs/README.md`: one sentence in the handler's entry (duplicates and old reminders
  change nothing) and the table under Config Location.

## Implementation details

### lambda: the completion record

Table `PM_COMPLETIONS_TABLE_NAME`, partition key `pk` (string). One item per task,
`pk = "task#<task_id>"`:

| Attribute | Type | Meaning |
| --- | --- | --- |
| `state` | S | `pending` while a completion is in flight, `done` after it |
| `claim_id` | S | `uuid.uuid4().hex` of the invocation holding a `pending` claim |
| `claimed_at` | N | epoch seconds of the claim |
| `reminder_ts` | S | the Slack `ts` of the reminder that was (or is being) ticked |
| `channel` | S | its channel ID |
| `due_before` | S | the task's `due_date` (ms, as ClickUp gives it) before the update; `""` if none |
| `completed_at` | N | epoch seconds when the task was completed (on `done` only) |

(Phase 5 adds a second item kind, `reply#…`, with a TTL attribute `expires_at`.)

Constants: `CLAIM_EXPIRY_SECONDS = 120` (four times the 30-second function timeout, so a
`pending` claim older than that belongs to a dead invocation). A `_now() -> int` helper
returns `int(time.time())` so tests can patch it. `reminder_epoch = Decimal(ts)`.

New environment variable `PM_COMPLETIONS_TABLE_NAME`, added to the required list (step
2 of phase 2's flow). A lazily created, cached `boto3.resource("dynamodb").Table(name)`
(`_get_table()`), reset in tests.

### lambda: the flow, after phase 2's step 8 (task valid, in the list, not closed)

8a. **ClickUp-side stale check.** If the task's `date_done` or `date_closed` (ms strings,
may be null) is later than `reminder_epoch * 1000`, the task was completed after this
reminder was posted: outcome `stale`, no claim, no update. Log
`logger.info("Reminder %s for task %s is older than its last completion", ts, task_id)`.

9. **Dry run** (replaces phase 2's step 9). `GetItem(ConsistentRead=True)` on the task's
   item, classify it with the same rules as the claim condition below (`would_complete`,
   `duplicate` or `stale`), log the outcome with the task ID, and return it. No writes.

10. **Claim.** `UpdateItem` on `task#<id>`:

    ```
    SET #state = :pending, claim_id = :claim, claimed_at = :now,
        reminder_ts = :ts, channel = :channel, due_before = :due
    ConditionExpression:
        attribute_not_exists(pk)
        OR (#state = :done AND completed_at < :reminder_epoch)
        OR (#state = :pending AND claimed_at < :expired)
    ReturnValues: ALL_OLD
    ```

    with `:expired = now - CLAIM_EXPIRY_SECONDS`. Keep the returned old item (may be
    empty) for a revert.

    - **`ConditionalCheckFailedException`:** read the item (`GetItem`,
      `ConsistentRead=True`) and classify: `state == "pending"` → `duplicate` (another
      invocation is completing it); `state == "done"` and `reminder_ts == ts` →
      `duplicate` (this reminder already completed it: a second ✅ or a redelivery);
      otherwise → `stale` (an older reminder; keep `completed_at` for phase 5's reply).
      Log `logger.info("Task %s: %s for reminder %s", task_id, outcome, ts)`. No ClickUp
      call.
    - **Any other `ClientError`:** `logger.error("Could not record completion of task
      %s: %s", task_id, error_code)` → `failed`, no ClickUp call.
    - **Took over an expired claim** (old item `state == "pending"`): if the task's
      current `due_date` differs from the old item's `due_before`, the earlier
      invocation's update landed before it died. Mark `done` with `completed_at =
      old["claimed_at"]` and `reminder_ts = old["reminder_ts"]` (conditional on our
      `claim_id`) and return `stale`. Otherwise carry on.

11. **Update ClickUp** (phase 2's step 10).
    - **Success:** `UpdateItem SET #state = :done, completed_at = :now REMOVE claim_id`,
      `ConditionExpression: claim_id = :claim`. If that condition fails, log a warning
      with the task ID (the claim expired under us; the task is still completed) and
      still return `completed`.
    - **`ValueError` from `update_task`:** it may have landed (a timeout after ClickUp
      applied it). Re-read the task with `get_task`:
      - It now has `status.type` in `CLOSED_STATUS_TYPES`, `status.status ==
        complete_status`, or a `due_date` different from `due_before`: the update landed.
        Mark `done` as on success, log `logger.warning("Task %s was completed although
        the update reported an error", task_id)`, return `completed`.
      - It is unchanged: revert the claim, conditional on `claim_id = :claim`: `PutItem`
        the old item if there was one, else `DeleteItem`. Log the failure with the task
        ID → `failed`. A later ✅ can try again.
      - The re-read fails too: leave the `pending` claim; it expires after
        `CLAIM_EXPIRY_SECONDS`, and the expired-claim check in step 10 then sees whether
        the update landed. Log with the task ID → `failed`.

Why this is enough for #163:

- Two ✅s or two deliveries: the second sees `pending` or `done` with the same
  `reminder_ts` → `duplicate`. The due date moves one cycle.
- Last week's reminder after this week's was ticked: `completed_at` ≥ last week's
  `ts` → `stale`.
- This week's reminder after last week's completion: last week's `completed_at` is
  earlier than this week's `ts` → the claim succeeds.
- Lambda retry after a timeout: the claim is still `pending` (≤ 120 s) → `duplicate`;
  later, the expired-claim check compares the due date.

Logged: task ID, `ts`, channel ID, outcome, DynamoDB error code. Never the item's
contents as a whole.

### infra: `templates/facilities.yaml`

```yaml
  # One item per PM task: whether a completion from Slack is in flight or done, and for
  # which reminder. It makes duplicate and stale check marks harmless. Phase 5 adds
  # short-lived reply markers, which expire through the TTL.
  PMReminderCompletionsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: !Sub "PMReminderCompletions-${Stage}"
      AttributeDefinitions:
        - AttributeName: pk
          AttributeType: S
      KeySchema:
        - AttributeName: pk
          KeyType: HASH
      BillingMode: PAY_PER_REQUEST
      TimeToLiveSpecification:
        AttributeName: expires_at
        Enabled: true
      Tags:
        - Key: Project
          Value: facilities:pm-reminder-reaction
```

`PMReminderReactionFunction` → `Environment.Variables`:

```yaml
          PM_COMPLETIONS_TABLE_NAME: !Ref PMReminderCompletionsTable
```

`PMReminderReactionLambdaRole` → `PMReminderReactionPolicy` → `Statement`:

```yaml
              - Effect: Allow
                Action:
                  - dynamodb:GetItem
                  - dynamodb:PutItem
                  - dynamodb:UpdateItem
                  - dynamodb:DeleteItem
                Resource: !GetAtt PMReminderCompletionsTable.Arn
```

### infra: `template-cicd.yaml`

`GitHubDeployPolicystageData`:

- `AllowDynamoDBTableManagement` → `Resource`, add
  `- !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/PMReminderCompletions-stage"`.
- `AllowClassListCacheTableReads`: CloudFormation reads these after `CreateTable` for
  any new table, so the new table needs them too. Rename the Sid to
  `AllowTableReadsAfterCreate` and make `Resource` a list of the
  `ClassPhotoClassListCache-stage` ARN and the `PMReminderCompletions-stage` ARN.

The same in `GitHubDeployPolicyprodData` with `-prod`. Both data policies are about
2,100–2,500 characters; well under budget.

### docs

- Function README: a "Completed once" section: the table, the item, the four cases
  above in plain words, the 2-minute claim expiry, and how to clear a record by hand if
  ever needed (delete the `task#<id>` item; read-only AWS commands are fine, deleting is
  an admin action).
- `docs/README.md`: in the handler's entry, "A task is completed once per reminder
  cycle: a second ✅, a repeated event or a ✅ on an older reminder changes nothing." and
  the table `PMReminderCompletions-${Stage}` (created by `templates/facilities.yaml`)
  under Config Location.

## Tests

`moto`'s `mock_aws` with a `PMReminderCompletions-test` table created in a fixture
(key `pk`); `aws`, `clickup`, `slack` patched as in phase 2; `_now` patched.

- `test_first_checkmark_claims_and_completes`: item ends `state=done`,
  `reminder_ts=ts`, `completed_at=now`, no `claim_id`; `update_task` called once.
- `test_second_checkmark_on_same_reminder_is_duplicate`: run twice (second with a
  different user) → second `duplicate`, `update_task` called once in total (#163
  criterion 1).
- `test_redelivered_event_is_duplicate`: the same body twice → one `update_task`.
- `test_in_flight_claim_is_duplicate`: a fresh `pending` item → `duplicate`, no update.
- `test_older_reminder_after_completion_is_stale`: item `done` with `completed_at` after
  the event's `ts` and another `reminder_ts` → `stale`, no update (#163 criterion 2).
- `test_newer_reminder_after_old_completion_completes`: `completed_at` before `ts` →
  `completed`.
- `test_clickup_date_done_after_reminder_is_stale`: no item, task `date_done` later than
  the reminder → `stale`, no claim written.
- `test_update_failure_reverts_claim`: `update_task` raises, re-read unchanged → `failed`;
  with no prior item the item is gone; with a prior `done` item it is restored exactly
  (#163 criterion 6).
- `test_retry_after_reverted_failure_completes_once`: failure, then the same event
  again with ClickUp working → `completed`, `update_task` succeeded once.
- `test_update_error_that_landed_counts_as_completed`: `update_task` raises, re-read
  shows a later `due_date` → `completed`, item `done`.
- `test_reread_failure_leaves_pending_claim`: both raise → `failed`, item stays
  `pending`; a second event within 120 s → `duplicate`.
- `test_expired_claim_whose_update_landed_is_stale`: `pending` item 200 s old with
  `due_before` different from the task's `due_date` → `stale`, item `done`, no update.
- `test_expired_claim_whose_update_did_not_land_completes`: same, `due_before` equal →
  `completed`.
- `test_dynamodb_error_makes_no_clickup_call`: `UpdateItem` raises a non-conditional
  `ClientError` (patched) → `failed`, no `update_task`.
- `test_dry_run_reads_but_writes_nothing`: `DRY_RUN=true` with no item →
  `would_complete`; with a `done` item for the same reminder → `duplicate`; the table
  is unchanged and `update_task` not called.
- `test_missing_table_env_var_answers_500`.

## Acceptance criteria

1. Two ✅s on one reminder, or one event delivered twice, call `update_task` once
   (#163 criterion 1).
2. A ✅ on a reminder older than the task's last recorded completion makes no ClickUp
   call (#163 criterion 2).
3. When ClickUp fails, the task is unchanged, the failure is logged with the task ID,
   the claim is reverted so a later ✅ can complete it, and a retry of the same event
   completes the task at most once (#163 criterion 6).
4. An update that reported an error but landed is recorded as a completion, not
   retried.
5. `PMReminderCompletions-${Stage}` exists, pay per request, TTL on `expires_at`, tag
   `Project`; the function can only `GetItem`, `PutItem`, `UpdateItem` and
   `DeleteItem` on it.
6. Both data policies list the table for their stage in table management and the
   after-create reads.
7. The stage dry run writes nothing to the table.

## Verification

```bash
.venv/bin/python -m pytest functions/facilities/pm_reminder_reaction tests/test_templates.py
.venv/bin/python -m pytest
.venv/bin/cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```

On stage after deploy (deploy role redeployed with the table names first):
`aws dynamodb describe-table --table-name PMReminderCompletions-stage` shows the table
with TTL on `expires_at`. Invoking the function by hand as in phase 2 logs `Dry run`
with outcome `would_complete`, and `aws dynamodb scan --table-name
PMReminderCompletions-stage --select COUNT` stays 0.

## Admin actions

Covered by README admin action 1: the deploy-role redeploy must include this phase's
table names before it reaches `stage`. If phase 2 already went through a redeploy
without them, redeploy again.

## Hand-off

_Filled in when the phase is done._ Phase 4 relies on: the handler completing a task at
most once, so it is safe to route live events. Phase 5 relies on: the outcomes
`completed`, `duplicate`, `stale` (with the record's `completed_at`), `failed`; the
table and its `expires_at` TTL; `PutItem` permission.
