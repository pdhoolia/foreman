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
2. **Pick the branch:** `<git-handle>/<short-kebab-description>`, never an agent
   prefix such as `claude/`. One branch and one checkout per developer: a git worktree
   (`git worktree add ../<repo>-<ID> -b <branch> origin/main`) or a fresh cloud
   checkout. Two writers never share one.
3. **Record the dispatch** in the task file: `State: active`, `Owner / run label`
   (model, effort, where it runs), `Branch`, `Updated`. Commit it on the track's branch
   and run the `refresh` skill, so the control room shows the task as active.
4. **Write the brief** for the developer. Keep it short; the task file is the brief.
   - The task file's path, and "read it first, then the files it links".
   - The checkout path and the branch.
   - The rules: own only the paths the task file names; take the recommended default
     on a small question and mark it in the PR as "default taken, owner may
     overrule"; stop and report on a scope change, a privacy risk or anything
     outward-facing.
   - The PR rules: one PR against `main`, opened as a draft; marked ready only when the
     project's checks pass; the body says the problem, what changes, how it was tested
     (every check that ran, and any that could not), what is not done; the task file's
     state proposed as `done` in the same PR; plain words; no agent co-author line, no
     "generated with" footer, no session link.
   - Who to report to when done or blocked: this session.
5. **Start the developer** with the `developer` agent (`foreman:developer`) or a new
   session, given the brief. Do not do the task's work yourself.
