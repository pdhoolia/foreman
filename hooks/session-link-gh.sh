#!/usr/bin/env bash
# PreToolUse guard: block a `gh` write (pr create/edit/comment/review/merge, issue
# create/edit/comment, or a raw `gh api` call) whose title or body carries a link to an
# agent session or an agent attribution footer ("Branches and pull requests" in the
# plugin's README).
#
# Companion to session-link-mcp.sh: that one covers the GitHub MCP path; this one covers
# the `gh` command line.
#
# Matched on the Bash tool, so it sees every Bash call and must scope itself: it acts only
# on gh commands that write to GitHub and leaves everything else alone. A `git commit`
# carrying the link is left to the project's commit-msg hook, and routine commands that
# merely mention the link are untouched. `gh api` is included because a read never
# carries the link in its command line, while a comment posted with `-f body=...` does.
#
# Deny, don't strip: exit 2 to block the call and feed the reason back to the agent.
payload="$(cat)"
here="$(cd "$(dirname "$0")" && pwd)"
# Whether this is a gh write is decided without grep, so that a missing grep or patterns
# file blocks gh writes only, not every Bash call.
shopt -s nocasematch
write='gh[[:space:]]+(pr[[:space:]]+(create|edit|comment|review|merge)|issue[[:space:]]+(create|edit|comment)|api)([^[:alnum:]_]|$)'
[[ $payload =~ $write ]] || exit 0
# Without grep or the patterns the search fails, and a failed search would let the write
# through.
if [ ! -r "$here/session-link.patterns" ] || ! command -v grep >/dev/null 2>&1; then
  echo "Blocked: the foreman plugin's session-link guard cannot run (it needs grep and $here/session-link.patterns), so it cannot check this GitHub write. Restore them (reinstall the plugin)." >&2
  exit 2
fi

if printf '%s' "$payload" | grep -qiE -f "$here/session-link.patterns"; then
  echo "Blocked: this 'gh' write's title or body carries a link to an agent session or an agent footer (a Co-authored-by line or 'Generated with ...'). Run the command again without them." >&2
  exit 2
fi
exit 0
