#!/usr/bin/env python3
"""PreToolUse: warn, never block, when a pull request, issue or comment body carries a word
from foreman.json's `jargon` list or a sentence longer than 35 words ("Plain words" in the
plugin's README). Covers gh pr create|edit|comment, gh issue create|comment and the GitHub
MCP writes that carry a body. Code, links and file paths are left out of the count.
"""
import re
import shlex
from pathlib import Path

from common import bash_command, context, project, run, runs

LONG = 35


def gh_body(cmd: str, cwd: str) -> str:
    try:
        words = shlex.split(cmd)
    except ValueError:
        return ""
    parts = []
    for flag, value in zip(words, words[1:]):
        if flag in ("--body", "-b", "--title", "-t"):
            parts.append(value)
        elif flag in ("--body-file", "-F") and value != "-":
            try:
                parts.append((Path(cwd) / value).read_text(encoding="utf-8"))
            except OSError:
                pass
    for w in words:
        if w.startswith(("--body=", "--title=")):
            parts.append(w.split("=", 1)[1])
    return "\n\n".join(parts)


def body(p: dict) -> str:
    cmd = bash_command(p)
    if cmd:
        if runs(cmd, "gh", r"pr\s+(?:create|edit|comment)|issue\s+(?:create|comment)"):
            return gh_body(cmd, p.get("cwd") or ".")
        return ""
    ti = p.get("tool_input") or {}
    return "\n\n".join(ti[k] for k in ("title", "body") if isinstance(ti.get(k), str))


def notes(text: str, jargon: list[str]) -> list[str]:
    text = re.sub(r"```.*?```|`[^`\n]*`|https?://\S+|\S+/\S+", " ", text, flags=re.S)
    found = [f"jargon: {w!r}" for w in jargon if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I)]
    for block in re.split(r"\n\s*\n|\n(?=\s*(?:[-*#|>]|\d+\.))", text):
        for sentence in re.split(r"(?<=[.!?])\s+", " ".join(block.split())):
            if len(sentence.split()) > LONG:
                found.append(f"{len(sentence.split())} words: {sentence!r}")
    return found


def main(p):
    text = body(p)
    found = project(p) if text else None
    if not found:
        return
    jargon = [w for w in found[1].get("jargon") or [] if isinstance(w, str) and w]
    lines = notes(text, jargon)
    if lines:
        context("PreToolUse", f"Plain words: this text may be hard to follow. Consider rewriting before or after it is posted "
                              f"(short sentences of at most {LONG} words, common words):\n- " + "\n- ".join(lines))


if __name__ == "__main__":
    run(main, blocking=False)
