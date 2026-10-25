#!/usr/bin/env python3
"""PreToolUse on the store-writing tool (ArtifactData, or an MCP tool of that name): deny a
write to questions, answers, labels or events that does not match scripts/store-schema.json.

`set` and every `set` of a `batch` must be a whole document. `update` merges fields, so a
field it leaves out is not missing, but every field it names must be known and of the
right type. Reads, deletes and writes to other collections pass untouched.
"""
import json
import sys
from pathlib import Path

from common import SCRIPTS, deny, payload

sys.path.insert(0, str(SCRIPTS))
from control_room import STORE_SCHEMA, check_doc  # noqa: E402

COLLECTIONS = {k for k in STORE_SCHEMA if k != "about"}
MISSING = "- missing field "


def problems(write: dict, cwd: str) -> str | None:
    op, collection = write.get("op"), write.get("collection")
    if op not in ("set", "update") or collection not in COLLECTIONS:
        return None
    data = write.get("data")
    if data is None and write.get("file_path"):
        try:
            data = json.loads((Path(cwd) / write["file_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # the tool reports a file it cannot read
    if not isinstance(data, dict):
        return f"{collection}/{write.get('doc_id')}: the document must be a JSON object"
    if op == "update":
        data = {k: v for k, v in data.items() if v != {"__delete__": True}}
    try:
        check_doc(collection, str(write.get("doc_id")), data)
    except SystemExit as e:
        lines = str(e).splitlines()
        if op == "update":
            lines = [l for l in lines if not l.startswith(MISSING)]
        if len(lines) > 1:
            return "\n".join(lines)
    return None


def main():
    p = payload()
    ti = p.get("tool_input") or {}
    action = ti.get("action")
    writes = ti.get("writes") or [] if action == "batch" else [dict(ti, op=action)]
    found = [e for e in (problems(w, p.get("cwd") or ".") for w in writes if isinstance(w, dict)) if e]
    if found:
        deny("Blocked: a store document does not match scripts/store-schema.json in the foreman plugin.\n"
             + "\n".join(found)
             + "\nBuild the document with control_room.py card or control_room.py event and write exactly what it prints.")


if __name__ == "__main__":
    main()
