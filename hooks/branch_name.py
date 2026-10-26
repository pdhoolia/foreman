#!/usr/bin/env python3
"""A branch named by a harness (claude/, codex/, deepseek/, cursor/, copilot/, or a prefix
foreman.json lists under branch_prefixes) breaks the branch rule in the plugin's README.

PreToolUse on Bash: deny `git commit` and `git push` on such a branch, and a push whose
destination is such a branch (git push origin HEAD:claude/x), with the rename command.
SessionStart: print the same warning, so the agent renames before it starts.
"""
from common import bash_command, context, deny, git, git_dir_arg, handle, project, run, runs, words, words_after

PREFIXES = ["claude/", "codex/", "deepseek/", "cursor/", "copilot/"]


def harness_prefix(branch: str, conf: dict) -> str | None:
    prefixes = PREFIXES + [x if x.endswith("/") else x + "/" for x in words(conf, "branch_prefixes")]
    return next((x for x in prefixes if branch.startswith(x)), None)


def warning(root, conf, branch: str) -> str | None:
    prefix = harness_prefix(branch, conf)
    if not prefix:
        return None
    new = f"{handle(root)}/{branch[len(prefix):] or 'short-kebab-description'}"
    return (f"The branch {branch!r} has the harness prefix {prefix!r}, which the branch rule forbids "
            f"(<git-handle>/<short-kebab-description>). Rename it before you commit, and push that branch "
            f"instead: git branch -m {new}")


def push_destinations(args: list[str]) -> list[str]:
    """The branches a `git push <remote> <refspec>...` writes to. A deletion (--delete, -d,
    :<branch>) writes nothing: it is how a harness branch is cleaned up after the rename."""
    if {"--delete", "-d"} & set(args):
        return []
    VALUE = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
    positional, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in VALUE:
            skip = True
        elif not a.startswith("-"):
            positional.append(a)
    dests = []
    for spec in positional[1:]:
        if spec.lstrip("+").startswith(":"):
            continue
        dst = spec.lstrip("+").split(":")[-1]
        dests.append(dst.removeprefix("refs/heads/"))
    return [d for d in dests if d and d != "HEAD"]


def main(p):
    if p.get("hook_event_name") == "SessionStart":
        found = project(p)
        if found:
            text = warning(*found, git(found[0], "branch", "--show-current") or "")
            if text:
                context("SessionStart", text)
        return
    cmd = bash_command(p)
    m = runs(cmd, "git", "commit|push")
    if not m:
        return
    found = project(p, git_dir_arg(m, p.get("cwd") or "."))
    if not found:
        return
    root, conf = found
    branch = git(root, "branch", "--show-current") or ""
    text = warning(root, conf, branch)
    if not text and m.group(1) == "push":
        bad = [d for d in push_destinations(words_after(cmd, m)) if harness_prefix(d, conf)]
        if bad:
            text = (f"This push writes to {', '.join(repr(d) for d in bad)}, a branch with a harness prefix, which the "
                    f"branch rule forbids. Push to {handle(root)}/<short-kebab-description> instead.")
    if text:
        deny("Blocked: " + text)


if __name__ == "__main__":
    run(main, blocking=True)
