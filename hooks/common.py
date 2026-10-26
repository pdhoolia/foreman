"""What the plugin's Python hooks share: reading Claude Code's hook payload, the project's
foreman.json, git, and the two ways a hook answers (deny, or add context).

A hook reads one JSON object on stdin (`cwd`, `hook_event_name`, `tool_name`,
`tool_input`, and for PostToolUse `tool_response`). It denies with exit 2 and the reason
on stderr, which Claude Code feeds back to the agent. It adds context by printing
`hookSpecificOutput.additionalContext` and exiting 0. Any other exit lets the call go on,
so `run` turns a crash of a blocking hook into a denial, and of a warning hook into context.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"


class BadConfig(Exception):
    """foreman.json exists but cannot be read."""


def run(main, blocking: bool) -> None:
    """Run a hook's main(payload). A blocking hook denies on an unexpected error; a warning
    hook, and any hook that meets an unreadable foreman.json, says so as context."""
    try:
        p = json.load(sys.stdin)
    except ValueError:
        p = {}
    event = p.get("hook_event_name") or "PreToolUse"
    name = Path(sys.argv[0]).name
    try:
        main(p)
    except BadConfig as e:
        context(event, f"Warning from the foreman plugin's {name} hook: {e}. The hook did not check this call.")
    except Exception as e:  # noqa: BLE001: a crashed hook must not let the action through silently
        if blocking:
            deny(f"Blocked: the foreman plugin's {name} hook failed ({type(e).__name__}: {e}). Fix the cause or report it.")
        context(event, f"Warning: the foreman plugin's {name} hook failed ({type(e).__name__}: {e}).")


def git(cwd, *args) -> str | None:
    """The output of a git command run in `cwd`, or None when it fails."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def project(p: dict, cwd=None) -> tuple[Path, dict] | None:
    """The checkout's root and its foreman.json, or None when this is not a foreman project.
    Raises BadConfig when foreman.json is there but is not a JSON object."""
    root = git(cwd or p.get("cwd") or ".", "rev-parse", "--show-toplevel")
    if not root or not (Path(root) / "foreman.json").is_file():
        return None
    try:
        conf = json.loads((Path(root) / "foreman.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BadConfig(f"foreman.json cannot be read ({e})") from e
    if not isinstance(conf, dict):
        raise BadConfig("foreman.json cannot be read (it is not a JSON object)")
    return Path(root), conf


def git_common_dir(root) -> Path:
    """The repository's git directory, shared by all its worktrees."""
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def bash_command(p: dict) -> str:
    return (p.get("tool_input") or {}).get("command") or "" if p.get("tool_name") == "Bash" else ""


def runs(command: str, tool: str, verbs: str) -> re.Match | None:
    """Whether a shell command runs `tool <verb>`, for example git commit or gh pr create.
    Global options between the tool and the verb (git -C dir commit) are skipped."""
    return re.search(rf"(?:^|[\s;&|(`]){tool}(?:\s+-\S+(?:\s+[^-\s]\S*)?)*?\s+({verbs})(?=\s|$|[;&|)])", command)


def words_after(command: str, m: re.Match) -> list[str]:
    """The arguments after the matched verb, up to the end of that simple command."""
    rest = re.split(r"\s(?:&&|\|\||[;|&])\s|[;\n]", command[m.end():])[0]
    try:
        return shlex.split(rest)
    except ValueError:
        return rest.split()


def git_dir_arg(m: re.Match, cwd) -> str:
    """Where a matched git command runs: its -C directory, else `cwd`."""
    c = re.search(r"\s-C\s+(\S+)", m.group(0))
    if not c:
        return cwd
    d = Path(c.group(1).strip("'\""))
    return str(d if d.is_absolute() else Path(cwd) / d)


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
