#!/usr/bin/env bash
# Refresh the control room's files in one step, then print what the coordinator publishes.
#   control-room-refresh.sh <out-dir> [own-track-slug ...]
# Run it from inside the project's checkout. Fetches the open pull requests, regenerates
# <out-dir>/state.json from the checkout, and writes <out-dir>/index.html only when the
# page source changed. With track slugs, it keeps every other track as the published
# state has it: save the published state.json as <out-dir>/live-state.json first (the
# refresh skill says how). Without slugs, every track comes from this checkout. A review
# round's <out-dir>/review.json is made separately (control_room.py review) and is
# published once; a later publish that leaves it out keeps it. The control room's URL
# comes from foreman.json (control_room_url) or CONTROL_ROOM_URL.
set -euo pipefail
out="${1:?usage: control-room-refresh.sh <out-dir> [own-track-slug ...]}"
shift
here="$(cd "$(dirname "$0")" && pwd)"
root="$(git rev-parse --show-toplevel)"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
url="${CONTROL_ROOM_URL:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("control_room_url") or "")' "$root/foreman.json" 2>/dev/null || true)}"
live=()
if [ "$#" -gt 0 ]; then
  [ -f "$out/live-state.json" ] || { echo "save the published state.json as $out/live-state.json first" >&2; exit 1; }
  live=(--live "$out/live-state.json" --own "$@")
fi
prs="$(mktemp -t control-room-prs.XXXXXX)"
trap 'rm -f "$prs"' EXIT
# Run in the repository so gh picks its remote, and ask for more than the default 30.
(cd "$root" && gh pr list --state open --limit 200 --json number,title,headRefName,isDraft,url,updatedAt) > "$prs"
python3 "$here/control_room.py" state --root "$root" --prs "$prs" --out "$out/state.json" ${live[@]+"${live[@]}"}
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
