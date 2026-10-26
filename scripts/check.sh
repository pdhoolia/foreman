#!/usr/bin/env bash
# Run the project's checks and, when they pass, mark the commit for the ready gate.
#   check.sh
# Run it from inside the project's checkout. The command is foreman.json's "checks": a
# script path (run with bash) or a shell command. The checks run on a commit, so tracked
# files must have no uncommitted change. On success the marker
# <git dir>/foreman/checks/<head commit> is written, in the git directory all worktrees
# share; the ready gate hook (hooks/ready_gate.py) looks for it before a pull request is
# marked ready.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
cmd="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("checks") or "")' foreman.json 2>/dev/null || true)"
[ -n "$cmd" ] || { echo "foreman.json names no checks command (\"checks\")" >&2; exit 1; }
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "commit or stash your changes first: the checks are marked against a commit" >&2
  exit 1
fi
head="$(git rev-parse HEAD)"
if [ -f "$cmd" ]; then bash "$cmd"; else bash -c "$cmd"; fi
marks="$(git rev-parse --path-format=absolute --git-common-dir)/foreman/checks"
mkdir -p "$marks"
date -u +%Y-%m-%dT%H:%M:%SZ > "$marks/$head"
echo "checks passed on $head"
