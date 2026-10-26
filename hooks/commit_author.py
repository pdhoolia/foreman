#!/usr/bin/env python3
"""The commit author is the owner's identity, never an agent's ("Branches and pull
requests" in the plugin's README). The committer is not checked: in a cloud session it
is the platform's signing identity, which is what makes the commit Verified.

PreToolUse on Bash `git commit`: deny when the author git will use (git var
GIT_AUTHOR_IDENT, then --author on the command line) looks like an agent: its name
starts with a harness name (claude, codex, deepseek, cursor, copilot, or a prefix from
foreman.json's branch_prefixes), or its email is at an agent maker's domain. When
foreman.json lists `commit_authors` ("Name <email>" strings), the author must be one of them.
SessionStart: with exactly one entry in `commit_authors`, set user.name and user.email in
the checkout from it, and in a cloud session (CLAUDE_CODE_REMOTE) keep the platform's
committer through CLAUDE_ENV_FILE. Otherwise say which git config commands to run.
"""
import os
import re
import shlex

from branch_name import PREFIXES
from common import bash_command, context, deny, git, git_dir_arg, project, run, runs, words, words_after

DOMAINS = ["anthropic.com", "openai.com", "deepseek.com", "cursor.com"]
COMMITTER = ("Claude", "noreply@anthropic.com")  # the cloud container's signing identity
IDENT = re.compile(r"^\s*(.*?)\s*<([^>]*)>")


def harness_names(conf: dict) -> list[str]:
    return [x.rstrip("/") for x in PREFIXES + words(conf, "branch_prefixes")]


def looks_like_an_agent(name: str, email: str, conf: dict) -> str | None:
    """Why this author is an agent's identity, or None."""
    first = re.split(r"[^a-z0-9]", name.lower(), maxsplit=1)[0]
    if first in [n.lower() for n in harness_names(conf)]:
        return f"the name {name!r} starts with the harness name {first!r}"
    domain = email.lower().rsplit("@", 1)[-1]
    if any(domain == d or domain.endswith("." + d) for d in DOMAINS):
        return f"the email {email!r} is at an agent maker's domain"
    return None


def author_of(where: str, args: list[str]) -> tuple[str, str]:
    """The author a `git commit` with these arguments will write, as (name, email)."""
    given = next((b for a, b in zip(args, args[1:]) if a == "--author"), None) or \
        next((a.split("=", 1)[1] for a in args if a.startswith("--author=")), None)
    if given and "<" not in given:  # a pattern: git takes the last commit by such an author
        given = git(where, "log", "-1", f"--author={given}", "--format=%an <%ae>")
        if not given:
            raise ValueError("no commit by that --author, so git will refuse it")
    ident = given or git(where, "var", "GIT_AUTHOR_IDENT")
    m = IDENT.match(ident or "")
    if not m:
        raise ValueError(f"the author {ident!r} is not 'Name <email>'")
    return m.group(1), m.group(2)


def session_start(root, conf) -> None:
    authors = words(conf, "commit_authors")
    m = IDENT.match(authors[0]) if len(authors) == 1 else None
    if not m:
        context("SessionStart", "foreman.json does not name exactly one commit author"
                + (f" (commit_authors: {', '.join(authors)})" if authors else "")
                + ". Set the author yourself before you commit: git config user.name '<name>' "
                  "&& git config user.email '<email>'")
    name, email = m.group(1), m.group(2)
    git(root, "config", "user.name", name)
    git(root, "config", "user.email", email)
    text = f"Commits in this checkout are authored as {name} <{email}> (foreman.json's commit_authors)."
    if os.environ.get("CLAUDE_CODE_REMOTE") and os.environ.get("CLAUDE_ENV_FILE"):
        with open(os.environ["CLAUDE_ENV_FILE"], "a", encoding="utf-8") as f:
            f.write(f"export GIT_COMMITTER_NAME={shlex.quote(COMMITTER[0])}\n"
                    f"export GIT_COMMITTER_EMAIL={shlex.quote(COMMITTER[1])}\n")
        text += f" The committer stays {COMMITTER[0]} <{COMMITTER[1]}>, so the signature verifies."
    context("SessionStart", text)


def main(p):
    if p.get("hook_event_name") == "SessionStart":
        found = project(p)
        if found:
            session_start(*found)
        return
    cmd = bash_command(p)
    m = runs(cmd, "git", "commit")
    if not m:
        return
    where = git_dir_arg(m, p.get("cwd") or ".")
    found = project(p, where)
    if not found:
        return
    root, conf = found
    try:
        name, email = author_of(where, words_after(cmd, m))
    except ValueError as e:
        deny(f"Blocked: this commit's author cannot be checked: {e}.")
    why = looks_like_an_agent(name, email, conf)
    allowed = words(conf, "commit_authors")
    if not why and allowed and f"{name} <{email}>" not in allowed:
        why = f"{name} <{email}> is not in foreman.json's commit_authors ({', '.join(allowed)})"
    if why:
        deny(f"Blocked: this commit would be authored by an identity the commit rule forbids: {why}. "
             f"The author must be the owner's identity: git config user.name '<name>' && git config user.email "
             f"'<email>' (the committer may stay the platform's). Then commit again.")


if __name__ == "__main__":
    run(main, blocking=True)
