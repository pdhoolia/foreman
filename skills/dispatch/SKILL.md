---
name: dispatch
description: Turn a task file into a developer brief and start the developer session, with its own checkout, branch and pull request rules. Use when a track coordinator hands a planned task to a developer.
argument-hint: <path to the task file>
---

# Dispatch a task to a developer

Argument: `$ARGUMENTS`, the task file (`docs/tracks/<slug>/tasks/<ID>-<name>.md`).

1. **Check it is ready.** Its `State` is `planned`. Every task it depends on is done or
   has its interface PR open. Its owned paths do not overlap a running task's. The
   owner has said go for this wave. If one fails, stop and say which.
2. **Pick the branch** by the rule in "Branches and pull requests" in
   `${CLAUDE_PLUGIN_ROOT}/README.md`. One branch and one checkout per developer: a git worktree
   (`git worktree add ../<repo>-<ID> -b <branch> origin/main`) or a fresh cloud
   checkout. Two writers never share one.
3. **Record the dispatch** in the task file: `State: active`, `Owner / run label`
   (model, effort, where it runs), `Branch`, `Updated`. Commit it on the track's branch
   and run the `refresh` skill, so the control room shows the task as active.
4. **Write the brief** for the developer. Keep it short; the task file is the brief.
   - The task file's path, and "read it first, then the files it links".
   - The checkout path and the branch.
   - The rules: own only the paths the task file names, and follow "Branches and pull
     requests" in the plugin's README (defaults, stops, the PR's shape).
   - The PR stays a draft until the ready gate lets it through: the ready gate hook
     ("Hooks" in the README) refuses the ready mark until `scripts/check.sh` has passed
     on the head, the task file proposes `done`, and this session's review pass has
     posted its verdict comment for that head. Do not repeat that rule in words.
   - Who to report to when done or blocked: this session.
5. **Start the developer** with the `developer` agent (`foreman:developer`) or a new
   session, given the brief. Do not do the task's work yourself.
   **Name it** `task <ID>: <short title> (developer)`, for example
   `task B01: search variants (developer)`. In a new terminal, start it with
   `claude --name "<that name>"`. With the Agent tool, use the same text as the agent's
   description. A review pass started as its own session is named `review #<PR> (reviewer)`.
