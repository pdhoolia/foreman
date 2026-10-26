#!/usr/bin/env python3
"""PostToolUse after a pull request write (gh pr create|ready|edit|merge|close, or a GitHub
MCP create_pull_request, update_pull_request or merge_pull_request): refresh the control
room's files and tell the agent what to publish, since a hook cannot publish.

The session owns the tracks of foreman.json whose folder under docs/tracks/ this branch's
commits change (origin/main...HEAD); on main, or with none changed, it owns none (the
program session's refresh). The files go to <git dir>/foreman/control-room, one folder per
repository, where the refresh skill saves the published state. After a merge that the
tool's output confirms (gh pr merge --auto only queues one), it also prints the pull
request event to write to the store and runs scripts/rebase-open-prs.sh, so every open
pull request is back on main; a conflict goes back to that pull request's developer.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from common import SCRIPTS, bash_command, context, git, git_common_dir, project, run, runs, words_after

TAIL = 3000
# What gh pr merge prints after a merge, and what GitHub's merge API returns.
MERGED = re.compile(r'(?:Merged|Squashed and merged|Rebased and merged) pull request|\\?"merged\\?"\s*:\s*true|successfully merged', re.I)


def pr_write(p: dict) -> tuple[bool, str] | None:
    """Whether this call wrote a pull request: whether it asked for a merge now, and the number when known."""
    tool, ti = p.get("tool_name") or "", p.get("tool_input") or {}
    if re.search(r"__(create|update|merge)_pull_request$", tool):
        return tool.endswith("__merge_pull_request"), str(ti.get("pullNumber") or "<number>")
    cmd = bash_command(p)
    m = runs(cmd, "gh", r"pr\s+(?:create|ready|edit|merge|close)")
    if not m:
        return None
    args = words_after(cmd, m)
    n = next((x.group(1) for a in args if (x := re.fullmatch(r"(?:\S*/pull/)?(\d+)/?", a))), "<number>")
    return m.group(1).endswith("merge") and "--auto" not in args, n


def capture(cmd: list[str], root: Path) -> str:
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return f"{' '.join(cmd)}: timed out"
    out = (r.stdout + r.stderr).strip()
    return (out[-TAIL:] if len(out) > TAIL else out) + ("" if r.returncode == 0 else f"\n(exit {r.returncode})")


def main(p):
    write = pr_write(p)
    found = project(p) if write else None
    if not found:
        return
    merged, number = write
    root, conf = found
    slugs = [t["slug"] for t in conf.get("tracks") or [] if isinstance(t, dict) and t.get("slug")]
    branch = git(root, "branch", "--show-current")
    changed = "" if branch in (None, "", "main") else git(root, "diff", "--name-only", "origin/main...HEAD") or ""
    own = [s for s in slugs if any(f.startswith(f"docs/tracks/{s}/") for f in changed.splitlines())]
    out = git_common_dir(root) / "foreman/control-room"
    parts = [f"Control room refresh ({'tracks ' + ' '.join(own) if own else 'no own track'}), files in {out}:",
             capture(["bash", str(SCRIPTS / "control-room-refresh.sh"), str(out), *own], root),
             "Publish what it prints with the Artifact tool. If it asks for live-state.json, follow the refresh skill: "
             "save the published state.json there and run it again."]
    if merged and not MERGED.search(json.dumps(p.get("tool_response"))):
        parts.append("The merge is not confirmed by the tool's output, so the post-merge step did not run. "
                     "If it did merge, write the event with control_room.py event pr <number> merged and run scripts/rebase-open-prs.sh.")
    elif merged:
        parts += ["Merged: write this pull request event to the store with ArtifactData (set):",
                  capture([sys.executable, str(SCRIPTS / "control_room.py"), "event", "pr", number, "merged"], root)
                  if number.isdigit() else "control_room.py event pr <number> merged (the number was not in the command)",
                  "Open pull requests brought back onto main (send each CONFLICT to its developer):",
                  capture(["bash", str(SCRIPTS / "rebase-open-prs.sh")], root)]
    context("PostToolUse", "\n\n".join(parts))


if __name__ == "__main__":
    run(main, blocking=False)
