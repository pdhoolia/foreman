"""What the plugin's Python hooks share: reading Claude Code's hook payload, the project's
foreman.json, git, and the two ways a hook answers (deny, or add context).

A hook reads one JSON object on stdin (`cwd`, `hook_event_name`, `tool_name`,
`tool_input`, and for PostToolUse `tool_response`). It denies with exit 2 and the reason
on stderr, which Claude Code feeds back to the agent. It adds context by printing
`hookSpecificOutput.additionalContext` and exiting 0. Any other exit lets the call go on.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"


def payload() -> dict:
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def git(cwd, *args) -> str | None:
    """The output of a git command run in `cwd`, or None when it fails."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def project(p: dict) -> tuple[Path, dict] | None:
    """The checkout's root and its foreman.json, or None when this is not a foreman project."""
    root = git(p.get("cwd") or ".", "rev-parse", "--show-toplevel")
    if not root or not (Path(root) / "foreman.json").is_file():
        return None
    try:
        return Path(root), json.loads((Path(root) / "foreman.json").read_text(encoding="utf-8"))
    except ValueError:
        return None


def bash_command(p: dict) -> str:
    return (p.get("tool_input") or {}).get("command") or "" if p.get("tool_name") == "Bash" else ""


def runs(command: str, tool: str, verbs: str) -> re.Match | None:
    """Whether a shell command runs `tool <verb>`, for example git commit or gh pr create.
    Global options between the tool and the verb (git -C dir commit) are skipped."""
    return re.search(rf"(?:^|[\s;&|(`]){tool}(?:\s+-\S+(?:\s+[^-\s]\S*)?)*?\s+({verbs})(?=\s|$|[;&|)])", command)


def deny(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def context(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}))
    sys.exit(0)


def handle(cwd) -> str:
    """The git handle: the <id>+<handle>@users.noreply.github.com email, else user.name."""
    email = git(cwd, "config", "user.email") or ""
    if email.endswith("@users.noreply.github.com"):
        return email.split("@")[0].split("+")[-1]
    return git(cwd, "config", "user.name") or "<your-git-handle>"
