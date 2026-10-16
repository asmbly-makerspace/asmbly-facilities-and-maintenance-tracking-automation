## Summary

<!-- 1-3 sentences: what changed and why. For a change to a service, say how it is
     triggered (webhook, Slack command or reaction, schedule, async invoke). -->

## Closes

<!-- The issues this pull request delivers, one per line: Closes #12
     Use "Refs #12" when this pull request doesn't finish the issue.
     "n/a: <reason>" for a chore with no issue. -->

## Risk

<!-- "none", or list each of these that applies:
     - New or renamed AWS resources. Their names must be in template-cicd.yaml, and an
       admin must redeploy that stack BEFORE this merges, or the stage deploy fails.
     - IAM changes, new secrets or SSM parameters (who creates them, and when).
     - A new public route, and how it checks its caller.
     - Settings outside AWS to change: the Slack app, ClickUp webhooks, Smartwaiver,
       the Google Apps Script. -->

none

## Test plan

- [ ] `python -m pytest`
- [ ] `cfn-lint template.yaml templates/*.yaml template-cicd.yaml` and `sam validate --region us-east-2` (if a template changed)
- [ ] `sam build` (if a template, a layer, or requirements changed)
- [ ] On the stage stack after merge: <what to send or click, and what should happen>
