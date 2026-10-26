---
name: coordinators
description: Start the track coordinators, each as its own Claude Code session in a new terminal; when that cannot work, say so and print the prompts for the owner to paste. Use in the program session, after `pm-start program`.
argument-hint: "[track slug ...]"
---

# Start the track coordinators

Arguments: `$ARGUMENTS` (optional: only these track slugs). Run from the project's root.

A track coordinator is its own Claude Code session. **Never start one with the Agent tool,
a forked session or any other subagent of this session.** A subagent acts as this session:
its review verdicts and ready marks count as self-approval and are refused, its
permission prompts come to this session, and every message between coordinators passes
through here. If this skill cannot start a session, the owner starts it by hand.

1. Run the starter (add `--track <slug> ...` when `$ARGUMENTS` names tracks):
   `python3 "${CLAUDE_PLUGIN_ROOT}/skills/coordinators/start.py" --root .`
   For each active track with a next action, it opens a new terminal that runs `claude`
   at the project's root with the track's prompt as the first message: a new tmux window
   when this session runs inside tmux, else on macOS a new Terminal window (iTerm2 when
   that is the terminal in use) through `osascript`. macOS may ask the owner once to let
   the terminal be controlled.
2. Show the owner the starter's output exactly as printed. It is one line per session
   started, and, for any it could not start, one line that says why and the prompt for
   each, to paste into a new Claude Code session in this repository.
3. If the Bash call is refused, or the starter cannot run, do not try another way. Run
   `FOREMAN_TERMINAL=none python3 "${CLAUDE_PLUGIN_ROOT}/skills/coordinators/start.py" --root .`,
   which only prints, and show the owner its output. If that fails too, give the owner the
   lines under "Coordinators to start" in the `pm-start program` brief.
4. Then stop. Do not do a coordinator's work in this session while it waits to start.

`FOREMAN_TERMINAL` picks the way to open a terminal: `tmux`, `terminal`, `iterm`, or
`none` to print the prompts only. The prompt is the line the project's program file gives
(a code span that starts with "Coordinate the <slug> track"), else the plugin's own line,
then at most two sentences of the track's next action. The rule behind this skill is in
the README's "Roles": `${CLAUDE_PLUGIN_ROOT}/README.md`.
