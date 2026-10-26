#!/usr/bin/env python3
"""Start one track coordinator per active track as its own Claude Code session.

    python3 start.py [--root DIR] [--track SLUG ...]
    python3 start.py [--root DIR] --track SLUG --next "<one or two sentences>"

For each active track with a next action (as `control_room.py brief program` reads them),
it starts `claude --name "<slug> (PM)" "<the track's prompt>"` at the project's root: as a
background session (`claude --bg`) when this claude has it, else in a new tmux window when
this runs inside tmux, else on macOS in a new Terminal or iTerm2 window through osascript.
A background session prints a short id; `claude attach <id>` opens it in a terminal and
`claude logs <id>` shows its recent output. The prompt goes through a file,
<git common dir>/foreman/prompts/<slug>.txt, because a terminal's input line takes at most
1024 characters; the typed command only reads that file.

With --next, the one track named is prompted even when its plan is complete or has no next
action (a decision reopened it): the coordinator line, then the given sentences. When it cannot (a cloud session, no tmux and no macOS, the
terminal automation refused or failed), it prints one line that says so and then each
prompt left, for the owner to paste into a new session by hand.

FOREMAN_TERMINAL picks the way: `background`, `tmux`, `terminal`, `iterm` or `none` (print
only). Unset, it is `background` when `claude --help` names `--bg`; if that start is
refused, the rest go the terminal way.
It never starts a coordinator inside this session: a subagent would act as this session,
so its reviews would count as self-review and its permission prompts would come here.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import control_room  # noqa: E402

NAMES = {"background": "background session", "tmux": "tmux window", "terminal": "Terminal window", "iterm": "iTerm2 window"}
ITERM = ['on run argv', 'tell application "iTerm"', 'activate', 'set w to (create window with default profile)',
         'tell current session of w to write text (item 1 of argv)', 'end tell', 'end run']
TERMINAL = ['on run argv', 'tell application "Terminal"', 'activate', 'do script (item 1 of argv)', 'end tell', 'end run']


def has_bg() -> bool:
    """Whether this claude can start a background session (`claude --bg`)."""
    try:
        r = subprocess.run(["claude", "--help"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "--bg" in r.stdout


def pick(background: bool = True) -> tuple[str | None, str]:
    """The way to start a session, or None and why there is none."""
    way = os.environ.get("FOREMAN_TERMINAL", "").strip().lower()
    if way == "none":
        return None, "FOREMAN_TERMINAL is none"
    if way and way not in NAMES:
        return None, f"FOREMAN_TERMINAL {way!r} is not background, tmux, terminal, iterm or none"
    if not way and os.environ.get("CLAUDE_CODE_REMOTE"):
        return None, "this is a cloud session, with no terminal to open"
    if not shutil.which("claude"):
        return None, "the claude command is not on PATH"
    if way == "background" or (not way and background and has_bg()):
        return "background", ""
    if way == "tmux" or (not way and os.environ.get("TMUX") and shutil.which("tmux")):
        return ("tmux", "") if shutil.which("tmux") else (None, "tmux is not installed")
    if way or sys.platform == "darwin":
        if not shutil.which("osascript"):
            return None, "osascript is not available"
        return way or ("iterm" if os.environ.get("TERM_PROGRAM") == "iTerm.app" else "terminal"), ""
    return None, "no tmux session and no macOS terminal to open"


def prompt_file(root: Path, slug: str, prompt: str) -> Path | None:
    """Write the prompt to <git common dir>/foreman/prompts/<slug>.txt, outside the work tree
    so it is never committed. None when root is not a git checkout."""
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       cwd=root, capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        return None
    f = Path(r.stdout.strip()) / "foreman" / "prompts" / f"{slug}.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(prompt.encode("utf-8"))
    return f


def command(way: str, root: Path, slug: str, f: Path) -> list[str]:
    """The command that starts one session, reading its prompt from the file f."""
    run = f'claude --name {shlex.quote(slug + " (PM)")} "$(cat {shlex.quote(str(f))})"'
    if way == "background":
        return ["sh", "-c", run.replace("claude ", "claude --bg ", 1)]
    if way == "tmux":
        return ["tmux", "new-window", "-c", str(root), "-n", slug, run]
    script = ITERM if way == "iterm" else TERMINAL
    return ["osascript", *[a for s in script for a in ("-e", s)], f"cd {shlex.quote(str(root))} && {run}"]


def start(way: str, root: Path, slug: str, prompt: str) -> tuple[str, str]:
    """Start one session; return ('', what to tell the owner) when it started, else (why not, '')."""
    f = prompt_file(root, slug, prompt)
    if f is None:
        return f"{root} is not a git checkout, so there is no place for the prompt file", ""
    cmd = command(way, root, slug, f)
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{'claude' if way == 'background' else cmd[0]} did not answer ({e.__class__.__name__})", ""
    if r.returncode:
        err = (r.stderr or r.stdout).strip().splitlines()
        return f"{'claude --bg' if way == 'background' else cmd[0]} said: {err[-1] if err else 'exit ' + str(r.returncode)}", ""
    if way != "background":
        return "", f"Started the {slug} coordinator in a new {NAMES[way]}."
    m = re.search(r"\b([0-9a-f]{6,})\b", r.stdout)
    if not m:
        return "", f"Started the {slug} coordinator in the background; claude said: {r.stdout.strip() or 'nothing'}"
    return "", (f"Started the {slug} coordinator in the background, id {m.group(1)}.\n"
                f"  claude attach {m.group(1)}   open it in a terminal\n"
                f"  claude logs {m.group(1)}     its recent output")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--track", nargs="+", default=[], help="only these track slugs")
    ap.add_argument("--next", help="prompt the one --track even if complete, with these sentences as the context")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.next is not None:
        if len(args.track) != 1:
            ap.error("--next needs exactly one --track")
        if not args.next.strip():
            ap.error("--next needs one or two sentences")
        tr = next((t for t in control_room.collect(root)["tracks"] if t["slug"] == args.track[0]), None)
        if tr is None:
            ap.error(f"no track {args.track[0]!r} under docs/tracks/")
        prompts = [{"slug": tr["slug"], "prompt": control_room.coordinator_line(root, tr) + " " + " ".join(args.next.split())}]
    else:
        prompts = [p for p in control_room.coordinator_prompts(root) if not args.track or p["slug"] in args.track]
    if not prompts:
        print("No coordinator to start: no active track has a next action" + (" among " + ", ".join(args.track) if args.track else "") + ".")
        return 0
    way, why = pick()
    left = prompts
    while way and left:
        why, said = start(way, root, left[0]["slug"], left[0]["prompt"])
        if why and way == "background" and not os.environ.get("FOREMAN_TERMINAL", "").strip():
            way, _ = pick(background=False)  # --bg refused: the rest go the terminal way
            if way:
                continue
        if why:
            break
        print(said)
        left = left[1:]
    if left:
        print(f"Could not start {'the coordinator sessions' if len(left) > 1 else 'the coordinator session'} ({why}); "
              f"paste each prompt below into a new Claude Code session in {root}.")
        for p in left:
            print("\n" + p["prompt"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
