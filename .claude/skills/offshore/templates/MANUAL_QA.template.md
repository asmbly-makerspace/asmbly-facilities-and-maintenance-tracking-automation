# Manual QA: <plan title>

Acceptance steps for `feature/<plan-name>`, by story, so each check maps back to
#<N>, #<N>, ...

Run them on the **stage stack**, after the pull request merges to `stage` and the
"Deploy Staging Pipeline" run is green, and before `/promote`.

> Automated checks already passed on the branch: pytest <N passed>, cfn-lint
> <clean | findings already on stage>, sam validate <pass>, sam build <pass>. Anything
> skipped is named here instead of given a result. These steps cover what a person
> should see happen in Slack, ClickUp, Neon or a browser.

## Prerequisites

<!-- Only what these stories need. -->
- The admin actions from the briefing that come before testing, done.
- The stage API address:

  ```bash
  API_ID=$(aws cloudformation describe-stack-resource \
    --stack-name AsmblyFacilitiesMaintTrackingStack-stage --logical-resource-id FacilitiesApi \
    --region us-east-2 --query StackResourceDetail.PhysicalResourceId --output text)
  STAGE_API_URL="https://$API_ID.execute-api.us-east-2.amazonaws.com/stage"
  ```

- Access to: <the Slack channel(s), the ClickUp list(s), Neon, the CloudWatch log groups
  `/asmbly/lambda/<Function>-stage`>.
- Test data: <e.g. a ClickUp task in <list> you can change, a Neon test account>.

Third-party webhooks (Slack, ClickUp, Smartwaiver, Google Apps Script) point at prod, so
the webhook steps below send the request by hand with `curl`.

---

## #<N>: <story title> (phases <…>)

1. <Action, with a copy-pasteable command where there is one.>

   ```bash
   curl -s -X POST "$STAGE_API_URL/<path>" \
     -H 'Content-Type: application/json' \
     -d @functions/<area>/<name>/tests/fixtures/<payload>.json
   ```

   **Expect:** <the response code and body>, <the Slack message in #<channel> that says
   ...>, <the ClickUp field <name> set to ...>.
2. <The failure a person can cause: a bad payload, a missing or wrong credential.>
   **Expect:** <status and body; nothing posted; a log line in
   `/asmbly/lambda/<Function>-stage` without the payload's personal details>.

## #<N>: <story title> (phases <…>)

3. <Action.> **Expect:** <result>.

<!--
One section per story. Number steps continuously across the document so a person can
say "step 7 failed". A story with nothing a person can observe gets one line:
"No visible surface: covered by the automated tests."
-->

---

## Automated checks (optional, to run them again locally)

```bash
python -m pytest
cfn-lint template.yaml templates/*.yaml template-cicd.yaml
sam validate --region us-east-2
sam build
```
