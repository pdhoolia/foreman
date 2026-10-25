---
name: inputs
description: Ask the owner through the control room (a decision card or a review round), read the answers back from the page's store, and record the round under docs/inputs/. Use instead of asking the owner in chat.
argument-hint: ask | review | record
---

# Owner inputs through the control room

Argument: `$ARGUMENTS` (`ask`, `review` or `record`). The control room is
`control_room_url` in `foreman.json`. Write for a reader who does not know the code.

## ask: a decision card

1. Never type a store document by hand. Build the card with the script, which checks
   it against `${CLAUDE_PLUGIN_ROOT}/scripts/store-schema.json`:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" card --id <id> --task <task ID> --order <n> --title "<title>" --body "<body>" --option <id> "<label>" "<detail>" --option ... --recommended <option id> --why "<two or three sentences>"`
   `<id>` uses letters, digits and `. _ ~ -`. If it prints an error, fix the arguments.
   Write exactly what it prints with the ArtifactData tool: `set`, with its
   `collection`, `doc_id` and `data`.
2. Tell the owner in one line, with the card's link: `<control room>#q-<id>`.

## review: items to label or judge

1. Start from `${CLAUDE_PLUGIN_ROOT}/templates/sample-spec.json`. Keep each item to what
   the owner needs to see: a title, a line of context, the opening turns, tags. Never a
   whole transcript or tool arguments.
2. Run the `refresh` skill after making `review.json` as it says. The spec and
   `review.json` stay in your scratchpad; they never go into git.

## record: read the answers and write the round

1. Read `answers/<id>` (`{choice, note, updated}`) and `labels/<item id>`
   (`{goal, said, updated}`) with ArtifactData.
2. Write `docs/inputs/<yyyy-mm-dd>-<slug>.md` from
   `${CLAUDE_PLUGIN_ROOT}/templates/record.md`. Keep its headings and bullets: the
   question id after `###` is the card's id, which links the decided card to its record.
   A review round records counts only, never the items or the labels.
3. Act on each answer in the plan, task or decision that needed it.
4. Commit, then run `refresh`.
