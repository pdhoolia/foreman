---
name: pm-handoff
description: Before a coordinator session stops, write the track plan's "Handoff and memory" section so the next session can start from the files alone, then refresh the control room.
argument-hint: <track slug>
---

# Hand a track over to the next session

Argument: `$ARGUMENTS`, the track's slug. Run from the project's root.

1. Write the section's body to `<scratch>/handoff.md`, as bullets:
   - `- Current result:` what exists, what is pushed, what is still local.
   - `- Decisions/findings:` facts with their evidence; defaults taken.
   - `- Blocker:` none, or what is needed and from whom.
   - `- Next action:` the exact next step: a command, a file, a dispatch.
   - `- First steps for the next session:` run `/foreman:pm-start track <slug>`, then
     what to check first.
   No transcript, no private data, no session links.
2. Write it into the plan; this also sets the plan's `Updated` line to today:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" handoff --root . --track $ARGUMENTS --text <scratch>/handoff.md`
3. Commit the plan on the branch you are allowed to push, and push it when authorized.
   A handoff that exists only in this checkout is not a handoff.
4. Run the `refresh` skill for this track and publish what it prints.
