#!/usr/bin/env python3
"""PreToolUse on Bash `git commit`: deny a commit whose task file or plan lacks the
head lines the tools read ("Task file bullets" and "Plan head lines" in the plugin's README).

It checks what the commit takes: the staged files, and with `-a` or named paths, those
files as they are in the working tree. A plan or task file of a finished track (its plan
says `complete`, `accepted` or `dropped`) is history and is not checked.
"""
import re

from common import bash_command, deny, git, git_dir_arg, project, run, runs, words_after

TASK = re.compile(r"docs/tracks/(?!_templates/)[^/]+/tasks/[^/]+\.md")
PLAN = re.compile(r"docs/tracks/(?!_templates/)[^/]+/plan\.md")
TASK_LINES = ["State", "Track", "Issue / PR", "Branch", "Updated"]
PLAN_LINES = ["Coordinator", "Done when", "Budget"]
STATES = {"planned", "active", "blocked", "review", "done", "accepted", "dropped"}
FINISHED = {"complete", "accepted", "dropped"}


def head(text: str) -> dict:
    """The `- Name: value` bullets before the first `##` heading."""
    lines = {}
    for line in text.split("\n## ")[0].splitlines():
        m = re.match(r"- ([^:]+):\s*(.*)", line)
        if m:
            lines.setdefault(m.group(1).strip(), m.group(2).strip())
    return lines


def state(lines: dict) -> str:
    return (re.findall(r"[a-z]+", lines.get("State", "").lower()) or [""])[0]


def problems(path: str, text: str) -> list[str]:
    lines = head(text)
    if PLAN.fullmatch(path):
        return [f"{path}: no '- {k}:' line in the head" for k in PLAN_LINES if k not in lines]
    found = [f"{path}: no '- {k}:' line in the head" for k in TASK_LINES if k not in lines]
    if "State" in lines:
        word = state(lines)
        if word not in STATES:
            found.append(f"{path}: state {word!r} is not one of {', '.join(sorted(STATES))}")
    return found


def commit_args(args: list[str]) -> tuple[bool, list[str]]:
    """Whether a `git commit` takes every tracked change (-a), and the paths it names."""
    VALUE = {"-m", "-F", "-c", "-C", "-t", "--author", "--date", "--file", "--message", "--template", "--fixup",
             "--squash", "--trailer", "--cleanup", "--reuse-message", "--reedit-message", "--pathspec-from-file"}
    every, paths, skip, dashdash = False, [], False, False
    for a in args:
        if skip:
            skip = False
        elif a == "--" and not dashdash:
            dashdash = True
        elif dashdash or not a.startswith("-"):
            paths.append(a)
        elif a == "--all":
            every = True
        elif a in VALUE:
            skip = True
        elif not a.startswith("--"):
            for j, ch in enumerate(a[1:]):
                every = every or ch == "a"
                if ch in "mFcCt":  # the rest of the cluster, or the next word, is the value
                    skip = j == len(a) - 2
                    break
    return every, paths


def main(p):
    cmd = bash_command(p)
    m = runs(cmd, "git", "commit")
    if not m:
        return
    where = git_dir_arg(m, p.get("cwd") or ".")
    found = project(p, where)
    if not found:
        return
    root = found[0]
    every, paths = commit_args(words_after(cmd, m))
    files = {path: git(root, "show", f":{path}") or ""
             for path in (git(root, "diff", "--cached", "--name-only", "--diff-filter=d") or "").splitlines()}
    # What the commit takes from the working tree replaces what is staged.
    tree = (git(root, "diff", "--name-only", "--diff-filter=d") or "").splitlines() if every else []
    if paths:
        tree += (git(where, "ls-files", "--full-name", "--", *paths) or "").splitlines()
    for path in tree:
        if (root / path).is_file():
            files[path] = (root / path).read_text(encoding="utf-8", errors="replace")
    errors = []
    for path, text in sorted(files.items()):
        if TASK.fullmatch(path) or PLAN.fullmatch(path):
            plan = "/".join(path.split("/")[:3]) + "/plan.md"
            plan_text = files[plan] if plan in files else git(root, "show", f":{plan}") or ""
            if state(head(plan_text)) not in FINISHED:
                errors += problems(path, text)
    if errors:
        deny("Blocked: a task file or plan in this commit lacks a line the tools read.\n- " + "\n- ".join(errors)
             + "\nAdd the missing lines (the templates under docs/tracks/_templates/ show them) and commit again.")


if __name__ == "__main__":
    run(main, blocking=True)
