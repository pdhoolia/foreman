#!/usr/bin/env bash
# Print the project's open pull requests as one JSON array, in the fields the generator
# reads: number, title, headRefName, isDraft, url, updatedAt.
#   open-prs.sh > prs.json
# Run it from inside the project's checkout. It uses GitHub's REST API (`gh api`), which
# works where gh's GraphQL calls (`gh pr list`) are refused. Exits non-zero when gh is
# missing or the call fails; callers decide whether to go on without the list.
set -euo pipefail
command -v gh >/dev/null || { echo "gh is not installed" >&2; exit 1; }
gh api --paginate "repos/{owner}/{repo}/pulls?state=open&per_page=100" \
  --jq '.[] | {number, title, headRefName: .head.ref, isDraft: .draft, url: .html_url, updatedAt: .updated_at}' \
  | python3 -c 'import json, sys; print(json.dumps([json.loads(l) for l in sys.stdin if l.strip()]))'
