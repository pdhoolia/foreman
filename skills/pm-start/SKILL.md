---
name: pm-start
description: Build a coordinator's starting brief from the project's files. Use first in a track coordinator session (`track <slug>`) or in the program session (`program`).
argument-hint: track <slug> | program
---

# Start a coordination session

Arguments: `$ARGUMENTS` (`track <slug>` or `program`). Run every command from the
project's root. Keep scratch files in your scratchpad, never in the repository.

1. Fetch the open pull requests:
   `gh pr list --state open --limit 200 --json number,title,headRefName,isDraft,url,updatedAt > <scratch>/prs.json`
2. Read the control room's store. The artifact is `control_room_url` in `foreman.json`.
   With the ArtifactData tool, list the `questions` and the `answers` collections and
   write them to `<scratch>/store.json` as
   `{"questions": [{"id": "<doc id>", ...fields}], "answers": {"<doc id>": {...fields}}}`.
   No control room yet: skip this step and leave `--store` out below.
3. Print the brief:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" brief $ARGUMENTS --root . --prs <scratch>/prs.json --store <scratch>/store.json`
4. Read every file on the brief's "Read first" line before you act.
5. Then act on the brief:
   - **Track coordinator.** You own this track's `plan.md` and task files, nothing else.
     Next work: the brief's "Next action". Dispatch with the `dispatch` skill, review
     with `review`, ask the owner with `inputs`, publish with `refresh`.
   - **Program session.** Do only what "Only the program session does" lists. Record
     every answered round under "Answered, not yet recorded" with the `inputs` skill.
6. A line that says "missing from the plan head" is a gap: add the `Coordinator`,
   `Done when` or `Budget` line to the plan (track) or ask the track's coordinator to
   (program).

The conventions behind every line of the brief are in the plugin's README:
`${CLAUDE_PLUGIN_ROOT}/README.md`.
