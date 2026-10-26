#!/usr/bin/env python3
"""PostToolUse after a pull request write (gh pr create|ready|edit|merge|close, or a GitHub
MCP create_pull_request, update_pull_request or merge_pull_request): refresh the control
room's files and tell the agent what to publish, since a hook cannot publish.

The session owns the tracks of foreman.json whose folder under docs/tracks/ this branch's
commits change (origin/main...HEAD); on main, or with none changed, it owns none (the
program session's refresh). The files go to <git dir>/foreman/control-room, one folder per
repository, where the refresh skill saves the published state. After a merge call, it asks
GitHub whether the pull request is merged (gh prints nothing when its output is not a
terminal, and gh pr merge --auto only queues a merge). When it is, the hook also prints the
pull request event to write to the store and runs scripts/rebase-open-prs.sh, so every open
pull request is back on main; a conflict goes back to that pull request's developer.
"""
import re
import subprocess
import sys
from pathlib import Path

from common import SCRIPTS, bash_command, context, git, git_common_dir, project, run, runs, words_after

TAIL = 3000


def pr_write(p: dict) -> tuple[bool, str, str | None] | None:
    """Whether this call wrote a pull request: whether it was a merge call, the number when
    known, and the repository ("owner/repo") when the call names one."""
    tool, ti = p.get("tool_name") or "", p.get("tool_input") or {}
    if re.search(r"__(create|update|merge)_pull_request$", tool):
        repo = f"{ti['owner']}/{ti['repo']}" if ti.get("owner") and ti.get("repo") else None
        return tool.endswith("__merge_pull_request"), str(ti.get("pullNumber") or "<number>"), repo
    cmd = bash_command(p)
    m = runs(cmd, "gh", r"pr\s+(?:create|ready|edit|merge|close)")
    if not m:
        return None
    args = words_after(cmd, m)
    n = next((x.group(1) for a in args if (x := re.fullmatch(r"(?:\S*/pull/)?(\d+)/?", a))), "<number>")
    repo = next((b for a, b in zip(args, args[1:]) if a in ("-R", "--repo")), None)
    return m.group(1).endswith("merge"), n, repo


def gh_api(root: Path, endpoint: str, jq: str) -> str:
    try:
        r = subprocess.run(["gh", "api", endpoint, "--jq", jq], cwd=root, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def merged_number(root: Path, number: str, repo: str | None) -> str | None:
    """The pull request's number when GitHub says it is merged. Without a number, the
    pull request of the checked-out branch."""
    api = repo or "{owner}/{repo}"
    if not number.isdigit():
        owner = repo.split("/")[0] if repo else "{owner}"
        number = gh_api(root, f"repos/{api}/pulls?head={owner}:{git(root, 'branch', '--show-current')}&state=closed", ".[0].number // empty")
    return number if number.isdigit() and gh_api(root, f"repos/{api}/pulls/{number}", ".merged") == "true" else None


def capture(cmd: list[str], root: Path) -> str:
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return f"{' '.join(cmd)}: timed out"
    out = (r.stdout + r.stderr).strip()
    return (out[-TAIL:] if len(out) > TAIL else out) + ("" if r.returncode == 0 else f"\n(exit {r.returncode})")


def main(p):
    write = pr_write(p)
    found = project(p) if write else None
    if not found:
        return
    merging, number, repo = write
    root, conf = found
    slugs = [t["slug"] for t in conf.get("tracks") or [] if isinstance(t, dict) and t.get("slug")]
    branch = git(root, "branch", "--show-current")
    changed = "" if branch in (None, "", "main") else git(root, "diff", "--name-only", "origin/main...HEAD") or ""
    own = [s for s in slugs if any(f.startswith(f"docs/tracks/{s}/") for f in changed.splitlines())]
    out = git_common_dir(root) / "foreman/control-room"
    parts = [f"Control room refresh ({'tracks ' + ' '.join(own) if own else 'no own track'}), files in {out}:",
             capture(["bash", str(SCRIPTS / "control-room-refresh.sh"), str(out), *own], root),
             "Publish what it prints with the Artifact tool. If it asks for live-state.json, follow the refresh skill: "
             "save the published state.json there and run it again."]
    merged = merging and merged_number(root, number, repo)
    if merging and not merged:
        parts.append("GitHub does not show the pull request as merged (yet), so the post-merge step did not run. "
                     "When it merges, write the event with control_room.py event pr <number> merged and run scripts/rebase-open-prs.sh.")
    elif merged:
        parts += ["Merged: write this pull request event to the store with ArtifactData (set):",
                  capture([sys.executable, str(SCRIPTS / "control_room.py"), "event", "pr", merged, "merged"], root),
                  "Open pull requests brought back onto main (send each CONFLICT to its developer):",
                  capture(["bash", str(SCRIPTS / "rebase-open-prs.sh")], root)]
    context("PostToolUse", "\n\n".join(parts))


if __name__ == "__main__":
    run(main, blocking=False)
