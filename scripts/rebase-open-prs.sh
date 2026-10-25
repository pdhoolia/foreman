#!/usr/bin/env bash
# After a merge, bring every open pull request back onto main so none sits in conflict.
#   rebase-open-prs.sh [--dry-run]
# Run it from inside the project's checkout. For each open PR: fetch its branch, try
# `git rebase origin/main` in a temporary worktree (a squash-merged base drops out by
# itself: git skips patches already upstream), then push with --force-with-lease. A
# rebase that conflicts is aborted and reported with its files; nothing is pushed for
# it, and the coordinator sends it to the PR's developer. Exit status: 0 when every PR
# is on main, 2 when at least one conflicts. Each push runs the project's own git hooks;
# a variable the project's pre-push hook reads to skip its checks passes through.
set -euo pipefail
dry=0
for a in "$@"; do case "$a" in --dry-run) dry=1 ;; *) echo "unknown flag $a" >&2; exit 1 ;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git rev-parse --show-toplevel)"
cd "$root"
# The list comes first: without it there is nothing to rebase, so a failed call stops here.
prs="$(bash "$here/open-prs.sh" | python3 -c 'import json, sys; [print(p["number"], p["headRefName"], sep="\t") for p in json.load(sys.stdin)]')"
git fetch -q --prune origin
conflicts=0; rebased=0; clean=0
while IFS=$'\t' read -r number branch; do
  [ -n "$number" ] || continue
  # Named refspecs, so a single-branch or shallow clone sees the PR's branch too.
  git fetch -q origin "+refs/heads/main:refs/remotes/origin/main" "+refs/heads/$branch:refs/remotes/origin/$branch"
  behind=$(git rev-list --count "origin/$branch..origin/main" 2>/dev/null || echo "?")
  # A branch that has every commit of main cannot conflict with it.
  if [ "$behind" = "0" ]; then
    echo "#$number $branch: on main"; clean=$((clean+1)); continue
  fi
  echo "#$number $branch: $behind commits behind main"
  [ "$dry" = "1" ] && continue
  wt="$(mktemp -d -t rebase-pr.XXXXXX)"
  git worktree add -q --detach "$wt" "origin/$branch"
  if git -C "$wt" rebase -q origin/main >/dev/null 2>&1; then
    git -C "$wt" push -q --force-with-lease origin "HEAD:refs/heads/$branch"
    echo "#$number $branch: rebased and pushed $(git -C "$wt" rev-parse --short HEAD)"; rebased=$((rebased+1))
  else
    echo "#$number $branch: CONFLICT in: $(git -C "$wt" diff --name-only --diff-filter=U | tr '\n' ' ')"; conflicts=$((conflicts+1))
    git -C "$wt" rebase --abort >/dev/null 2>&1 || true
  fi
  git worktree remove --force "$wt"
done <<< "$prs"
echo "on main: $clean, rebased: $rebased, conflicts: $conflicts"
[ "$conflicts" = "0" ] || exit 2
