---
name: review
description: Run the review pass on a developer's pull request before it reaches the owner. Read-only; findings go back to the developer; decides whether the PR may be marked ready.
argument-hint: <pull request number or URL>
---

# Review a pull request

Argument: `$ARGUMENTS`, the pull request. You do not write to the PR's branch. For a
change to recovery, contracts or shared state, run this as a separate session with the
`reviewer` agent (`foreman:reviewer`).

1. Read the task file the PR delivers, then the diff:
   `gh pr view $ARGUMENTS --json title,body,headRefName,files` and `gh pr diff $ARGUMENTS`.
2. Check, and note each failure with its file and line:
   - Every acceptance item of the task file is met, with evidence in the PR body.
   - The diff stays inside the task's owned paths.
   - The checks the PR names ran on this revision, and they passed. A check that could
     not run is named, never counted as a pass.
   - The task file proposes `done` and its Evidence section is filled.
   - Defaults taken are marked "default taken, owner may overrule".
   - The PR body and the commits use plain words; no agent co-author line, no
     "generated with" footer, no session link.
   - Nothing private is in the diff: no data, transcripts, credentials or local paths.
3. Run the project's checks on the PR's head yourself when you can.
4. Send the findings to the developer, numbered, most serious first, each with what
   would fix it. A finding is a fact about the diff, not a taste.
5. **Ready gate.** The PR may be marked ready only when no finding is left that blocks
   it. Then put it in the owner's digest: one line on what to check. Run `refresh`.
