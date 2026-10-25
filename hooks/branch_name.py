#!/usr/bin/env python3
"""A branch named by a harness (claude/, codex/, deepseek/, or a prefix foreman.json lists
under branch_prefixes) breaks the branch rule in the plugin's README.

PreToolUse on Bash: deny `git commit` and `git push` on such a branch, with the rename
command. SessionStart: print the same warning, so the agent renames before it starts.
"""
from common import bash_command, context, deny, git, handle, payload, project, runs

PREFIXES = ["claude/", "codex/", "deepseek/"]


def warning(p: dict) -> str | None:
    found = project(p)
    if not found:
        return None
    root, conf = found
    branch = git(root, "branch", "--show-current") or ""
    prefixes = PREFIXES + [x if x.endswith("/") else x + "/" for x in conf.get("branch_prefixes") or []]
    prefix = next((x for x in prefixes if branch.startswith(x)), None)
    if not prefix:
        return None
    new = f"{handle(root)}/{branch[len(prefix):] or 'short-kebab-description'}"
    return (f"The branch {branch!r} has the harness prefix {prefix!r}, which the branch rule forbids "
            f"(<git-handle>/<short-kebab-description>). Rename it before you commit, and push that branch "
            f"instead: git branch -m {new}")


def main():
    p = payload()
    if p.get("hook_event_name") == "SessionStart":
        text = warning(p)
        if text:
            context("SessionStart", text)
    elif runs(bash_command(p), "git", "commit|push"):
        text = warning(p)
        if text:
            deny("Blocked: " + text)


if __name__ == "__main__":
    main()
