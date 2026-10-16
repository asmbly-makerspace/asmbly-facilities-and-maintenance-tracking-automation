---
name: rigor
description: The person is telling you to stop cutting corners and do the work properly. Use only when the person runs /rigor.
argument-hint: [what was wrong, optional]
disable-model-invocation: true
---

The person is telling you to stop cutting corners and do the work properly. This is a
correction, not a request for something new.

**Why they said it:** you were hasty. You assumed instead of checking, patched a symptom
instead of finding the cause, or answered confidently without reading the code.

**What to do now:**

1. **Stop.** Don't continue what you were doing, and don't defend it.
2. **Say what you got wrong.** Re-read the code, the template, the logs or the error
   output. State what you assumed and what is actually true. If you don't know yet, say
   so and find out before going on.
3. **Trace the whole path.** Follow the request from its trigger (the webhook, the Slack
   event, the schedule) through API Gateway, the template's environment variables and
   IAM, the handler, the `common` helpers, and the outside API, and back. Read every file
   on the way. Don't skip a layer because you think you know what it does.
4. **Fix the cause, not the symptom.** If the cause is in the template and the symptom in
   the handler, fix the template. If that means changing the deploy role, the tests and
   the README too, change all of them.
5. **Verify before you answer.** Not "I think" or "it should". Read the code, grep for the
   name, run the tests and the template checks from `CLAUDE.md`. Then state facts.
6. **Go back to the task** with that rigor.

The person's additional context, if any:

$ARGUMENTS
