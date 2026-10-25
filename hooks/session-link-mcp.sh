#!/usr/bin/env bash
# PreToolUse guard: block a GitHub MCP write (create or update a pull request or an issue,
# add a comment, submit a review, ...) whose payload carries a link to an agent session or
# an agent attribution footer ("Branches and pull requests" in the plugin's README).
#
# Why a harness hook and not git: these writes go through the GitHub MCP tools, which git
# hooks never see. The matcher in hooks/hooks.json scopes it to the write-verb tools
# (mcp__github__(create|update|add|submit|push|merge|delete)_*), so searching the whole
# tool-call payload for the forbidden text is enough and safe.
#
# Deny, don't strip: a PreToolUse hook cannot reliably rewrite MCP tool input, so it exits
# 2 to block the call and feeds the reason back to the agent, which resubmits a clean body.
payload="$(cat)"
here="$(cd "$(dirname "$0")" && pwd)"

if printf '%s' "$payload" | grep -qiE -f "$here/session-link.patterns"; then
  echo "Blocked: this GitHub write (pull request, issue, comment or review) carries a link to an agent session or an agent footer (a Co-authored-by line or 'Generated with ...'). Resubmit without them." >&2
  exit 2
fi
exit 0
