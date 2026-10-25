#!/usr/bin/env python3
"""PreToolUse on Bash `git commit`: deny a commit whose staged task file or plan lacks the
head lines the tools read ("Task file bullets" and "Plan head lines" in the plugin's README).

Only what is staged when the command starts is checked: the files of a `git commit -a` or
`git commit <path>` that are not yet staged are not.
"""
import re

from common import bash_command, deny, git, payload, project, runs

TASK = re.compile(r"docs/tracks/(?!_templates/)[^/]+/tasks/[^/]+\.md")
PLAN = re.compile(r"docs/tracks/(?!_templates/)[^/]+/plan\.md")
TASK_LINES = ["State", "Track", "Issue / PR", "Branch", "Updated"]
PLAN_LINES = ["Coordinator", "Done when", "Budget"]
STATES = {"planned", "active", "blocked", "review", "done", "dropped"}


def head(text: str) -> dict:
    """The `- Name: value` bullets before the first `##` heading."""
    lines = {}
    for line in text.split("\n## ")[0].splitlines():
        m = re.match(r"- ([^:]+):\s*(.*)", line)
        if m:
            lines.setdefault(m.group(1).strip(), m.group(2).strip())
    return lines


def problems(path: str, text: str) -> list[str]:
    lines = head(text)
    if PLAN.fullmatch(path):
        return [f"{path}: no '- {k}:' line in the head" for k in PLAN_LINES if k not in lines]
    found = [f"{path}: no '- {k}:' line in the head" for k in TASK_LINES if k not in lines]
    if "State" in lines:
        word = (re.findall(r"[a-z]+", lines["State"].lower()) or [""])[0]
        if word not in STATES:
            found.append(f"{path}: state {word!r} is not one of {', '.join(sorted(STATES))}")
    return found


def main():
    p = payload()
    if not runs(bash_command(p), "git", "commit"):
        return
    found = project(p)
    if not found:
        return
    root = found[0]
    staged = (git(root, "diff", "--cached", "--name-only", "--diff-filter=d") or "").splitlines()
    errors = []
    for path in staged:
        if TASK.fullmatch(path) or PLAN.fullmatch(path):
            errors += problems(path, git(root, "show", f":{path}") or "")
    if errors:
        deny("Blocked: a staged task file or plan lacks a line the tools read.\n- " + "\n- ".join(errors)
             + "\nAdd the missing lines (the templates under docs/tracks/_templates/ show them), stage the file and commit again.")


if __name__ == "__main__":
    main()
