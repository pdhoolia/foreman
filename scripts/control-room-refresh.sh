#!/usr/bin/env bash
# Refresh the control room's files in one step, then print what the coordinator publishes.
#   control-room-refresh.sh <out-dir> [own-track-slug ...]
#   control-room-refresh.sh <out-dir> --all
# Run it from inside the project's checkout. Fetches the open pull requests, regenerates
# <out-dir>/state.json and writes <out-dir>/index.html only when the page source changed.
# The state is a merge, not a replacement. Save the published state.json as
# <out-dir>/live-state.json first (the refresh skill says how). Then only the named tracks
# come from this checkout and every other track is kept as published. With no track
# named, the session owns none: every published track is kept, and only the pull
# requests, records and lanes come from here (the program session's refresh). --all
# takes every track from this checkout: only for the first publish, or to recover a
# broken published state. A review round's <out-dir>/review.json is made separately
# (control_room.py review) and is published once; a later publish that leaves it out
# keeps it. The control room's URL comes from foreman.json (control_room_url) or
# CONTROL_ROOM_URL.
set -euo pipefail
usage="usage: control-room-refresh.sh <out-dir> [own-track-slug ...] | <out-dir> --all"
out="${1:?$usage}"
shift
all=0
for a in "$@"; do [ "$a" = "--all" ] && all=1; done
if [ "$all" = "1" ] && [ "$#" -gt 1 ]; then echo "--all takes no track names; $usage" >&2; exit 1; fi
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git rev-parse --show-toplevel)"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
url="${CONTROL_ROOM_URL:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("control_room_url") or "")' "$root/foreman.json" 2>/dev/null || true)}"
live=()
if [ "$all" = "0" ]; then
  [ -f "$out/live-state.json" ] || { echo "save the published state.json as $out/live-state.json first, or pass --all for a first publish" >&2; exit 1; }
  live=(--live "$out/live-state.json")
  [ "$#" -eq 0 ] || live+=(--own "$@")
fi
prs="$(mktemp -t control-room-prs.XXXXXX)"
trap 'rm -f "$prs"' EXIT
# The pull request list is worth having, not worth stopping for.
pr_args=()
if (cd "$root" && bash "$here/open-prs.sh") > "$prs"; then
  pr_args=(--prs "$prs")
else
  echo "warning: no pull request list (gh missing or the call failed); the page keeps only live pull request events" >&2
fi
python3 "$here/control_room.py" state --root "$root" --out "$out/state.json" ${pr_args[@]+"${pr_args[@]}"} ${live[@]+"${live[@]}"}
python3 "$here/control_room.py" page --root "$root" --out "$out/index.html"

files="{\"state.json\": \"$out/state.json\""
if [ -f "$out/review.json" ]; then files="$files, \"review.json\": \"$out/review.json\""; fi
files="$files}"
echo
echo "Publish with the Artifact tool:"
echo "  file_path:    $out/index.html"
echo "  files:        $files"
if [ -n "$url" ]; then
  echo "  url:          $url"
  echo "  (leave capabilities out: the artifact keeps db, user and sample)"
else
  echo "  capabilities: {\"db\": {}, \"user\": {}, \"sample\": {}}   (first publish only)"
  echo "  icon:         dashboard                                  (first publish only)"
fi
