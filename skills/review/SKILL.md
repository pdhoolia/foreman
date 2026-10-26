---
name: review
description: Run the review pass on a developer's pull request before it reaches the owner. Writes nothing to the branch; findings go back to the developer; posts the verdict comment that lets the PR be marked ready.
argument-hint: <pull request number or URL>
---

# Review a pull request

Argument: `$ARGUMENTS`, the pull request. You do not write to the PR's branch. For a
change to recovery, contracts or shared state, run this as a separate session with the
`reviewer` agent (`foreman:reviewer`).

1. Read the task file the PR delivers, then the PR and its diff with GitHub's REST API
   (`gh pr view` is refused where GraphQL is blocked):
   `gh api "repos/{owner}/{repo}/pulls/$ARGUMENTS"` and
   `gh api -H "Accept: application/vnd.github.diff" "repos/{owner}/{repo}/pulls/$ARGUMENTS"`.
2. Check, and note each failure with its file and line:
   - Every acceptance item of the task file is met, with evidence in the PR body.
   - The diff stays inside the task's owned paths.
   - The checks the PR names ran on this revision, and they passed. A check that could
     not run is named, never counted as a pass.
   - The task file proposes `done` and its Evidence section is filled.
   - The PR and its commits follow "Branches and pull requests" and "Plain words" in
     `${CLAUDE_PLUGIN_ROOT}/README.md`.
   - Nothing private is in the diff: no data, transcripts, credentials or local paths.
3. Run the project's checks on the PR's head yourself when you can.
4. Send the findings to the developer, numbered, most serious first, each with what
   would fix it. A finding is a fact about the diff, not a taste.
5. **Ready gate.** The PR may be marked ready only when no finding is left that blocks
   it. When none does, post the verdict as a comment on the PR whose first line is
   exactly `foreman review: ready <full head sha>` (the sha you reviewed; a later push
   needs a new verdict):
   `gh api "repos/{owner}/{repo}/issues/$ARGUMENTS/comments" -f body="foreman review: ready <sha>"`.
   The ready gate hook ("Hooks" in the README) refuses the ready mark until that comment
   is there, `scripts/check.sh` has passed on the head and the task file proposes
   `done`. Then put it in the owner's digest: one line on what to check. The refresh
   hook refreshes after the ready mark; publish what it prints.
