#!/usr/bin/env python3
"""PostToolUse after a pull request write (gh pr create|ready|edit|merge|close, or a GitHub
MCP create_pull_request, update_pull_request or merge_pull_request): refresh the control
room's files and tell the agent what to publish, since a hook cannot publish.

The session owns the tracks of foreman.json whose folder under docs/tracks/ this branch
changes against origin/main; on main, or with none changed, it owns none (the program
session's refresh). The files go to <scratchpad>/control-room, where the refresh skill
saves the published state. After a merge it also prints the pull request event to write
to the store and runs scripts/rebase-open-prs.sh, so every open pull request is back on
main; a conflict goes back to that pull request's developer.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from common import SCRIPTS, bash_command, context, git, payload, project, runs

TAIL = 3000


def pr_write(p: dict) -> tuple[bool, str] | None:
    """Whether this call wrote a pull request, whether it merged one, and its number when known."""
    tool, ti = p.get("tool_name") or "", p.get("tool_input") or {}
    if re.search(r"__(create|update|merge)_pull_request$", tool):
        return tool.endswith("__merge_pull_request"), str(ti.get("pullNumber") or "<number>")
    m = runs(bash_command(p), "gh", r"pr\s+(?:create|ready|edit|merge|close)")
    if not m:
        return None
    rest = bash_command(p)[m.end():]
    n = re.match(r"\s+(?:\S*/pull/)?(\d+)\b", rest)
    return "merge" in m.group(1), n.group(1) if n else "<number>"


def run(cmd: list[str], root: Path) -> str:
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return f"{' '.join(cmd)}: timed out"
    out = (r.stdout + r.stderr).strip()
    return (out[-TAIL:] if len(out) > TAIL else out) + ("" if r.returncode == 0 else f"\n(exit {r.returncode})")


def main():
    p = payload()
    write = pr_write(p)
    found = project(p) if write else None
    if not found:
        return
    merged, number = write
    root, conf = found
    slugs = [t["slug"] for t in conf.get("tracks") or [] if isinstance(t, dict) and t.get("slug")]
    base = git(root, "merge-base", "HEAD", "origin/main")
    own = [s for s in slugs if base and git(root, "diff", "--quiet", base, "--", f"docs/tracks/{s}/") is None]
    out = Path(p.get("scratchpad_dir") or tempfile.gettempdir()) / "control-room"
    parts = [f"Control room refresh ({'tracks ' + ' '.join(own) if own else 'no own track'}), files in {out}:",
             run(["bash", str(SCRIPTS / "control-room-refresh.sh"), str(out), *own], root),
             "Publish what it prints with the Artifact tool. If it asks for live-state.json, follow the refresh skill: "
             "save the published state.json there and run it again."]
    if merged:
        parts += [f"Merged: write this pull request event to the store with ArtifactData (set):",
                  run([sys.executable, str(SCRIPTS / "control_room.py"), "event", "pr", number, "merged"], root)
                  if number.isdigit() else "control_room.py event pr <number> merged (the number was not in the command)",
                  "Open pull requests brought back onto main (send each CONFLICT to its developer):",
                  run(["bash", str(SCRIPTS / "rebase-open-prs.sh")], root)]
    context("PostToolUse", "\n\n".join(parts))


if __name__ == "__main__":
    main()
