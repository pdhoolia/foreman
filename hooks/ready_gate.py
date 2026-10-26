#!/usr/bin/env python3
"""PreToolUse: deny marking a pull request ready (gh pr ready, gh pr create without
--draft, a GitHub MCP create_pull_request or update_pull_request with draft false) unless,
for the commit at the head of that pull request,

1. the project's checks passed: scripts/check.sh runs foreman.json's `checks` command and,
   on success, leaves a marker for that commit under the git directory; and
2. the branch's task file (the one whose `- Branch:` names the pull request's branch)
   proposes completion at that commit: `- State: done` or `review`.

The head is read from GitHub for a pull request named by number (gh api), and is the
pushed branch for a new one: the checkout's HEAD must then be pushed (equal to @{u}).
A project whose foreman.json names no `checks` skips the first test; a branch that no
task file names skips the second. An unreadable foreman.json, or a head that cannot be
found, denies.
"""
import re
import shlex
import subprocess
from pathlib import Path

from common import PLUGIN, BadConfig, bash_command, deny, git, git_common_dir, project, run, runs, words_after
from task_shape import TASK

CHECK = PLUGIN / "scripts/check.sh"
BRANCH = re.compile(r"^- Branch:[^`\n]*`([^`]+)`", re.M)
STATE = re.compile(r"^- State:\s*([a-z]+)", re.M | re.I)


class NoHead(Exception):
    """The commit being marked ready cannot be found."""


def marked(p: dict) -> tuple[str, str | None, str | None] | None:
    """(how, pull request number, branch) when this call marks a pull request ready, else None.
    `how` is "number" when the number names it, else "branch"."""
    tool, ti = p.get("tool_name") or "", p.get("tool_input") or {}
    if tool.endswith("__create_pull_request"):
        return None if ti.get("draft") is True else ("branch", None, str(ti.get("head") or "").split(":")[-1] or None)
    if tool.endswith("__update_pull_request"):
        return ("number", str(ti.get("pullNumber")), None) if ti.get("draft") is False else None
    cmd = bash_command(p)
    m = runs(cmd, "gh", r"pr\s+(?:ready|create)")
    if not m:
        return None
    args = words_after(cmd, m)
    if m.group(1).endswith("ready"):
        if "--undo" in args:
            return None
        target = next((a for a in args if not a.startswith("-")), None)
        n = re.fullmatch(r"(?:\S*/pull/)?(\d+)/?", target or "")
        return ("number", n.group(1), None) if n else ("branch", None, target)
    if {"--draft", "-d"} & set(args):
        return None
    head = next((b for a, b in zip(args, args[1:]) if a in ("--head", "-H")), None)
    return "branch", None, head.split(":")[-1] if head else None


def head_of(root: Path, how: str, number: str | None, branch: str | None) -> tuple[str, str]:
    """The commit and branch at the head of the pull request being marked."""
    if how == "number":
        r = subprocess.run(["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{number}", "--jq", '.head.sha + " " + .head.ref'],
                           cwd=root, capture_output=True, text=True, timeout=60)
        parts = r.stdout.split()
        if r.returncode != 0 or len(parts) != 2:
            raise NoHead(f"cannot read pull request #{number} from GitHub ({(r.stderr or r.stdout).strip()[:200]})")
        sha, branch = parts
    elif branch and branch != git(root, "branch", "--show-current"):
        sha = git(root, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}")
        if not sha:
            raise NoHead(f"the branch {branch!r} is not on origin; push it first")
    else:
        branch = git(root, "branch", "--show-current") or ""
        sha, upstream = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "-q", "--verify", "@{u}")
        if not upstream or sha != upstream:
            raise NoHead(f"the head of {branch!r} is not pushed (HEAD differs from its upstream); push it first")
    if git(root, "cat-file", "-e", f"{sha}^{{commit}}") is None:
        git(root, "fetch", "-q", "origin", branch)
        if git(root, "cat-file", "-e", f"{sha}^{{commit}}") is None:
            raise NoHead(f"the commit {sha[:12]} of {branch!r} is not in this checkout; fetch it first")
    return sha, branch


def task_file(root: Path, sha: str, branch: str) -> tuple[str, str] | None:
    """The task file that names this branch, at that commit: its path and its text."""
    for path in (git(root, "ls-tree", "-r", "--name-only", sha, "docs/tracks") or "").splitlines():
        if TASK.fullmatch(path):
            text = git(root, "show", f"{sha}:{path}") or ""
            m = BRANCH.search(text)
            if m and m.group(1) == branch:
                return path, text
    return None


def main(p):
    target = marked(p)
    if not target:
        return
    try:
        found = project(p)
    except BadConfig as e:
        deny(f"Blocked: {e}, so the ready gate cannot run. Fix foreman.json first.")
    if not found:
        return
    root, conf = found
    try:
        sha, branch = head_of(root, *target)
    except NoHead as e:
        deny(f"Blocked: this marks a pull request ready, and {e}.")
    missing = []
    if conf.get("checks") and not (git_common_dir(root) / "foreman/checks" / sha).is_file():
        missing.append(f"the checks have not passed on {sha[:12]}, the head of {branch!r}: check that commit out and run "
                       f"bash {shlex.quote(str(CHECK))} (it runs {conf['checks']!r} and marks the commit when they pass)")
    task = task_file(root, sha, branch)
    if task:
        m = STATE.search(task[1])
        state = m.group(1).lower() if m else "none"
        if state not in ("done", "review"):
            missing.append(f"the task file {task[0]} has State {state!r} at {sha[:12]}: "
                           f"propose completion with '- State: done' (or review) and fill its Evidence")
    if missing:
        deny("Blocked: this marks a pull request ready, and the ready gate is not met.\n- " + "\n- ".join(missing)
             + "\nKeep it a draft until both hold.")


if __name__ == "__main__":
    run(main, blocking=True)
