#!/usr/bin/env python3
"""PreToolUse on the store-writing tool (ArtifactData, or an MCP tool of that name): deny a
write to questions, answers, labels or events that does not match scripts/store-schema.json.

`set` and every `set` of a `batch` must be a whole document. `update` merges fields, so a
field it leaves out is not missing, but every field it names must be known and of the
right type, and it may not delete a required field. `str_replace` may only change a plain
text field. Reads, deletes and writes to other collections pass untouched.
"""
import json
import sys
from pathlib import Path

from common import SCRIPTS, deny, run

sys.path.insert(0, str(SCRIPTS))
from control_room import STORE_SCHEMA, check_doc  # noqa: E402

COLLECTIONS = {k for k in STORE_SCHEMA if k != "about"}
DELETE = {"__delete__": True}


def problems(write: dict, cwd: str) -> str | None:
    op, collection = write.get("op"), write.get("collection")
    if collection not in COLLECTIONS:
        return None
    name = f"{collection}/{write.get('doc_id')}"
    fields = STORE_SCHEMA[collection]["fields"]
    if op == "str_replace":
        f = fields.get(write.get("field"))
        if not f or f["type"] != "string" or "enum" in f:
            return f"{name}: str_replace may only change a plain text field ({', '.join(k for k, v in fields.items() if v['type'] == 'string' and 'enum' not in v)}), not {write.get('field')!r}; use set or update"
        return None
    if op not in ("set", "update"):
        return None
    data = write.get("data")
    if data is None and write.get("file_path"):
        try:
            data = json.loads((Path(cwd) / write["file_path"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # the tool reports a file it cannot read
    if not isinstance(data, dict):
        return f"{name}: the document must be a JSON object"
    errors = []
    if op == "update":
        deleted = [k for k, v in data.items() if v == DELETE]
        errors += [f"- deletes required field {k!r}" for k in deleted if fields.get(k, {}).get("required")]
        data = {k: v for k, v in data.items() if k not in deleted}
    try:
        check_doc(collection, str(write.get("doc_id")), data)
    except SystemExit as e:
        lines = str(e).splitlines()[1:]
        if op == "update":
            # A partial update: a field left out is not missing, and `recommended` is checked
            # against the stored options only when the update brings its own.
            lines = [l for l in lines if not l.startswith("- missing field ")
                     and not ("options" not in data and l.startswith("- field 'recommended' must be option-id"))]
        errors += lines
    return f"{name} is not a valid store document:\n" + "\n".join(errors) if errors else None


def main(p):
    ti = p.get("tool_input") or {}
    action = ti.get("action")
    if action == "batch":
        writes = ti.get("writes")
        if not isinstance(writes, list):
            deny("Blocked: a batch's `writes` must be a list of writes.")
    else:
        writes = [dict(ti, op=action)]
    found = [e for e in (problems(w, p.get("cwd") or ".") if isinstance(w, dict) else "a batch entry is not an object"
                         for w in writes) if e]
    if found:
        deny("Blocked: a store document does not match scripts/store-schema.json in the foreman plugin.\n"
             + "\n".join(found)
             + "\nBuild the document with control_room.py card or control_room.py event and write exactly what it prints.")


if __name__ == "__main__":
    run(main, blocking=True)
