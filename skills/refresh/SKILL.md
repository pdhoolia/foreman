---
name: refresh
description: Regenerate the control room's state.json (and review.json when a review round is open) from the project's files and print the publish parameters. Use after every dispatch, PR change, merge or new decision record.
argument-hint: [own track slug ...]
---

# Refresh the control room

Arguments: `$ARGUMENTS`, the slugs of the tracks this session owns. A program session
or a first publish passes none. Run from the project's root. `<out>` is a folder in
your scratchpad; it never goes into git.

1. **Keep the other tracks.** When you name tracks, you write only those. Save the
   published state first: Artifact tool, action `read`, `url` = `control_room_url`
   from `foreman.json`, `path` = `state.json`; copy the saved file to
   `<out>/live-state.json`. Every other track is then kept as published, so a refresh
   from your unmerged branch does not undo another coordinator's publish.
2. Run:
   `bash "${CLAUDE_PLUGIN_ROOT}/scripts/control-room-refresh.sh" <out> $ARGUMENTS`
3. Publish exactly what it prints, with the Artifact tool. On the first publish it
   prints `capabilities` (`db`, `user`, `sample`) and `icon`; later publishes leave
   them out, and the artifact keeps them. After the first publish, put the link in
   `foreman.json` as `control_room_url` and commit it.
4. **A review round.** Make the review file first:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" review --spec <spec.json> --out <out>/review.json`.
   The refresh then publishes it. To end the round, publish once with
   `"review.json": null` in `files`.
5. The artifact service refuses a publish as stale when someone published after your
   last read: read it again (step 1), rerun, publish again.

6. **A pull request event** (the page shows a merge or a ready mark without a
   republish): never type the document by hand. Build it:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/control_room.py" event pr <number> <open|ready|merged|closed> --title "<title>" --url <url>`
   and write exactly what it prints with the ArtifactData tool (`set`, its
   `collection`, `doc_id` and `data`).

Never edit the page, `state.json` or a store document by hand. Change the files they are
made from, or build the document with the script.
