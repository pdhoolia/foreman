#!/usr/bin/env python3
"""PreToolUse: deny marking a pull request ready (gh pr ready, gh pr create without
--draft, a GitHub MCP create_pull_request or update_pull_request with draft false) unless

1. the project's checks passed on the current head: scripts/check.sh runs foreman.json's
   `checks` command and, on success, leaves a marker for that commit under the git
   directory; and
2. the branch's task file (the one whose `- Branch:` names this branch) proposes
   completion: `- State: done` or `review`.

A project whose foreman.json names no `checks` skips the first test; a branch that no
task file names skips the second. The head is the checkout's HEAD, where the agent works,
and the task file is read as committed there.
"""
import re
import shlex
from pathlib import Path

from common import PLUGIN, bash_command, deny, git, payload, project, runs
from task_shape import TASK

CHECK = PLUGIN / "scripts/check.sh"
BRANCH = re.compile(r"^- Branch:[^`\n]*`([^`]+)`", re.M)
STATE = re.compile(r"^- State:\s*([a-z]+)", re.M | re.I)


def marks_ready(p: dict) -> bool:
    tool, ti = p.get("tool_name") or "", p.get("tool_input") or {}
    if tool.endswith("__create_pull_request"):
        return ti.get("draft") is not True
    if tool.endswith("__update_pull_request"):
        return ti.get("draft") is False
    cmd = bash_command(p)
    if runs(cmd, "gh", r"pr\s+ready"):
        return "--undo" not in cmd
    if runs(cmd, "gh", r"pr\s+create"):
        try:
            words = shlex.split(cmd)
        except ValueError:
            words = cmd.split()
        return not ({"--draft", "-d"} & set(words))
    return False


def task_file(root: Path, branch: str) -> tuple[str, str] | None:
    """The committed task file that names this branch: its path and its text at HEAD."""
    for path in (git(root, "ls-tree", "-r", "--name-only", "HEAD", "docs/tracks") or "").splitlines():
        if TASK.fullmatch(path):
            text = git(root, "show", f"HEAD:{path}") or ""
            m = BRANCH.search(text)
            if m and m.group(1) == branch:
                return path, text
    return None


def main():
    p = payload()
    if not marks_ready(p):
        return
    found = project(p)
    if not found:
        return
    root, conf = found
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "branch", "--show-current") or ""
    missing = []
    if conf.get("checks") and head:
        marker = Path(git(root, "rev-parse", "--absolute-git-dir")) / "foreman/checks" / head
        if not marker.is_file():
            missing.append(f"the checks have not passed on the head {head[:12]}: run "
                           f"bash {shlex.quote(str(CHECK))} (it runs {conf['checks']!r} and marks the commit when they pass)")
    task = task_file(root, branch)
    if task:
        m = STATE.search(task[1])
        state = m.group(1).lower() if m else "none"
        if state not in ("done", "review"):
            missing.append(f"the task file {task[0]} has State {state!r} at the head: "
                           f"propose completion with '- State: done' (or review) and fill its Evidence")
    if missing:
        deny("Blocked: this marks a pull request ready, and the ready gate is not met.\n- " + "\n- ".join(missing)
             + "\nOpen it as a draft until both hold.")


if __name__ == "__main__":
    main()
