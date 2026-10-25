---
name: refresh
description: Regenerate the control room's state.json (and review.json when a review round is open) from the project's files and print the publish parameters. Use after every dispatch, PR change, merge or new decision record.
argument-hint: [own track slug ...] | --all
---

# Refresh the control room

Arguments: `$ARGUMENTS`. A publish is a merge, not a replacement ("Several
coordinators, one page" in `${CLAUDE_PLUGIN_ROOT}/README.md`):

- A track coordinator names the tracks it owns. Only those come from its checkout.
- The program session names none. It owns no track: every track is kept as published,
  and only the pull requests, records and lanes come from its checkout.
- `--all` takes every track from the checkout. Use it only for the first publish, or
  to recover a published state that is broken.

Run from the project's root. `<out>` is a folder in your scratchpad; it never goes
into git.

1. **Bring in `main`** (`git fetch origin main && git merge origin/main`). Records
   under `docs/inputs/` and the lanes in `foreman.json` come from your checkout, and
   the program session writes them on `main`.
2. **Save the published state** (not for `--all`): Artifact tool, action `read`,
   `url` = `control_room_url` from `foreman.json`, `path` = `state.json`; copy the
   saved file to `<out>/live-state.json`.
3. Run:
   `bash "${CLAUDE_PLUGIN_ROOT}/scripts/control-room-refresh.sh" <out> $ARGUMENTS`
4. Publish exactly what it prints, with the Artifact tool. On the first publish it
   prints `capabilities` (`db`, `user`, `sample`) and `icon`; later publishes leave
   them out, and the artifact keeps them. After the first publish, put the link in
   `foreman.json` as `control_room_url` and commit it.
5. **A review round.** Make the review file first:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" review --spec <spec.json> --out <out>/review.json`.
   The refresh then publishes it. To end the round, publish once with
   `"review.json": null` in `files`.
6. The artifact service refuses a publish as stale when someone published after your
   last read: save it again (step 2), rerun, publish again.
7. A warning that there is no pull request list (gh missing, or GitHub refused the
   call) does not stop the refresh. Publish anyway and say so.
8. **A pull request event** (the page shows a merge or a ready mark without a
   republish): never type the document by hand. Build it:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" event pr <number> <open|ready|merged|closed> --title "<title>" --url <url>`
   and write exactly what it prints with the ArtifactData tool (`set`, its
   `collection`, `doc_id` and `data`).

Never edit the page, `state.json` or a store document by hand. Change the files they are
made from, or build the document with the script.
