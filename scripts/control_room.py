#!/usr/bin/env python3
"""The control room: one private artifact for the owner, fed by files generated from the repo.

    python3 control_room.py state   --out state.json [--prs prs.json] [--root DIR]
                                    [--live live-state.json [--own SLUG ...]]
    python3 control_room.py review  --spec spec.json --out review.json
    python3 control_room.py page    --out index.html [--title NAME] [--root DIR]
    python3 control_room.py brief   track SLUG | program [--prs prs.json] [--store store.json] [--root DIR]
    python3 control_room.py handoff --track SLUG --text handoff.md [--root DIR]
    python3 control_room.py card    --id ID --title T --body B --option ID LABEL [DETAIL] ... [--task ID]
                                    [--order N] [--recommended ID] [--why TEXT]
    python3 control_room.py event   pr NUMBER open|ready|merged|closed [--title T] [--url URL] [--updated TIME]

`state` reads the consuming project (foreman.json, track plans, task files, plain words,
bench evidence, decision records under docs/inputs/) and writes one JSON file. `--prs`
takes the output of `gh pr list --state open --json number,title,headRefName,isDraft,url,updatedAt`.
`--live` keeps every track the running session does not own (`--own`; none when it is
left out) as the published state.json has it, so a coordinator working from an unmerged
branch does not undo another coordinator's publish. Without `--live`, every track comes
from the checkout: only for a first publish or a recovery. `review` turns a review spec (items for the owner to
label) into review.json. `page` writes the static page from control-room/; it embeds no
data and loads state.json and review.json with fetch() from beside itself. It rewrites
the file only when the page source changed. `brief` prints a session's starting brief;
`handoff` writes a plan's "Handoff and memory" section. `card` and `event` build a store
document (a decision card, a pull request event), check it against store-schema.json and
print the exact payload to write. The plugin's README says how it fits together.

Only repo text and aggregates reach state.json: never a transcript, a record or a path
from private data. Review items are private material and go to review.json only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "control-room"
LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
TASK_ID = re.compile(r"\b([A-Z]{1,2}\d{2}[a-z]?)\b")
SAFE_ID = re.compile(r"[A-Za-z0-9_.~-]+")
DONE_STATES = {"done", "accepted", "complete", "dropped"}

# What each findings column measures, in plain words. A table in
# docs/tracks/plain-words.md whose first header cell is "Column" overrides a line.
COLUMNS = {
    "variant": ("Method", "The method being scored. Each row is one method run on one set of items."),
    "set": ("Set", "Which items were scored. Hover a set name, when it is underlined, for what it holds."),
    "records": ("Records", "How many items the row stands on. Only labelled items count toward the scores."),
    "purity": ("Purity", "Of the groups the method made, how clean they are: 1.0 means every group holds items with one and the same label. Easy to inflate by making many tiny groups, so read it with the next two columns."),
    "inverse_purity": ("Inv. purity", "The other direction: for each label, how much of it landed in one group. 1.0 means nothing with the same label was split apart. High purity with low inverse purity means the method shatters goals into pieces."),
    "ari": ("ARI", "Adjusted Rand index: one number for how well the method's groups match the labels, corrected for luck. 1.0 is a perfect match, 0 is no better than random, below 0 is worse than random. The main score for grouping methods."),
    "coverage": ("Coverage", "For skill-finding methods: the share of items in a goal that start with the procedure the method proposed. Higher means the procedure describes more of what people actually did."),
    "coverage_overall": ("Overall coverage", "Coverage counted over every item in the set, not averaged goal by goal."),
    "candidates": ("Candidates", "How many skill candidates the method proposed."),
    "support": ("Support", "The median number of items behind one candidate."),
    "clusters": ("Clusters", "How many groups the method made, or how many goal groups it looked inside for skills."),
    "abstained": ("Abstained", "Items the method could not place at all, usually because they have no text. They are scored as one group of their own so that leaving hard ones out cannot raise the score."),
}
KIND_COLUMNS = {
    "clustering": ["variant", "set", "records", "purity", "inverse_purity", "ari", "clusters", "abstained"],
    "skills": ["variant", "set", "records", "candidates", "coverage", "coverage_overall", "support", "clusters"],
}
BEST_METRIC = {"clustering": "ari", "skills": "coverage"}
# The heading of each kind of finding. A `Kind` table in docs/tracks/plain-words.md overrides one.
KIND_NAMES = {"clustering": "Grouping items by label", "skills": "Finding repeated procedures"}


# ---------------------------------------------------------------- markdown helpers

def strip_md(text: str) -> str:
    text = LINK.sub(r"\1", text)
    return text.replace("`", "").replace("**", "").strip()


def first_link(text: str) -> str | None:
    m = LINK.search(text)
    return m.group(2) if m else None


def tables(markdown: str) -> list[list[list[str]]]:
    """Every pipe table as rows of raw cells, header first, separator row dropped."""
    out, current = [], []
    for line in markdown.splitlines() + [""]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            current.append(cells)
        elif current:
            out.append(current)
            current = []
    return out


def bullets(markdown: str) -> dict[str, str]:
    """`- Name: value` bullets (bold names too), each joined over its indented continuation lines."""
    out: dict[str, str] = {}
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"-\s+(?:\*\*)?([^:*\n]{1,40}):(?:\*\*)?\s*(.*)", line)
        if not m or m.group(1).strip() in out:
            continue
        value = [m.group(2)]
        for cont in lines[i + 1:]:
            if cont.startswith("  ") and not cont.lstrip().startswith("- "):
                value.append(cont.strip())
            else:
                break
        out[m.group(1).strip()] = " ".join(value).strip()
    return out


def section(markdown: str, heading: str, level: int = 2) -> str:
    """The text under `## heading` up to the next heading of the same or a higher level."""
    marks = "#" * level
    m = re.search(rf"^{marks}\s+{re.escape(heading)}[^\n]*\n(.*?)(?=^#{{1,{level}}}\s|\Z)", markdown, re.M | re.S)
    return m.group(1) if m else ""


def state_word(value: str | None) -> str:
    if not value:
        return "unknown"
    return re.split(r"[\s,;(]", value.strip())[0].lower()


def git(root: Path, *args: str) -> str | None:
    """A git answer about `root`, or None when `root` is not the top of a checkout (a fixture tree)."""
    # A git hook sets GIT_DIR and friends; they would point every call at the hook's checkout.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def run(*a: str) -> str:
        return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True, env=env).stdout.strip()
    try:
        if Path(run("rev-parse", "--show-toplevel")).resolve() != root.resolve():
            return None
        return run(*args)
    except (OSError, subprocess.CalledProcessError):
        return None


def project_info(root: Path) -> dict:
    """The project's name and its GitHub address, from the origin remote (any host alias)."""
    remote = git(root, "remote", "get-url", "origin") or ""
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", remote)
    slug = m.group(2) if m else root.name
    repo_url = f"https://github.com/{m.group(1)}/{m.group(2)}" if m and "github" in remote else None
    name = " ".join(w.capitalize() for w in re.split(r"[-_\s]+", slug) if w)
    return {"name": name, "repo_url": repo_url, "blob_base": repo_url + "/blob/main/" if repo_url else None}


# ---------------------------------------------------------------- repository readers

def read_config(root: Path) -> dict:
    """foreman.json at the project's root: the page title, the control room URL, the lanes per track."""
    path = root / "foreman.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_lanes(root: Path, config: dict) -> list[dict]:
    """Lanes from foreman.json: each track lists its lanes; a lane links its track's plan.
    A top-level "lanes" list holds lanes outside any track, which link no plan."""
    lanes = []
    for tr in [*(config.get("tracks") or []), {"lanes": config.get("lanes")}]:
        plan = f"docs/tracks/{tr['slug']}/plan.md" if tr.get("slug") else ""
        for lane in tr.get("lanes") or []:
            lanes.append({"key": lane["key"], "name": lane.get("name", ""), "work": lane.get("work", ""),
                          "where": lane.get("where", ""), "plan": plan if plan and (root / plan).is_file() else None,
                          "model": lane.get("model")})
    return lanes


def read_task_file(path: Path) -> dict:
    b = bullets(path.read_text(encoding="utf-8"))
    pr = b.get("Issue / PR")
    branch = b.get("Branch") or ""
    code = re.search(r"`([^`]+)`", branch)
    return {
        "state": state_word(b.get("State")), "pr": strip_md(pr) if pr and "not created" not in pr else None,
        "pr_link": first_link(pr or ""), "branch": code.group(1) if code else strip_md(branch) or None,
        "updated": b.get("Updated"), "needs_owner": b.get("Needs owner"),
    }


def read_track(plan: Path, root: Path) -> dict:
    text = plan.read_text(encoding="utf-8")
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), plan.parent.name)
    head = bullets(text.split("\n## ", 1)[0])
    track = {
        "slug": plan.parent.name, "title": title, "path": str(plan.relative_to(root)),
        "state": state_word(head.get("State")), "updated": head.get("Updated"), "tasks": [],
        "coordinator": strip_md(head.get("Coordinator", "")), "done_when": strip_md(head.get("Done when", "")),
        "budget": strip_md(head.get("Budget", "")),
    }
    track["done"] = track["state"] in DONE_STATES
    for table in tables(text):
        if not strip_md(table[0][0]).lower().startswith("id"):
            continue
        for row in table[1:]:
            if len(row) < 5:
                continue
            label = strip_md(row[0])
            m = TASK_ID.search(label)
            task = {
                "id": m.group(1) if m else label, "name": label.split(":", 1)[1].strip() if ":" in label else label,
                "deliverable": strip_md(row[1]), "track": track["slug"], "task_file": None,
                "state": "planned", "pr": None, "pr_link": None, "updated": None, "needs_owner": None,
                "branch": None if strip_md(row[4]).lower().startswith("unassigned") else strip_md(row[4]) or None,
            }
            task["depends_on"] = [d for d in TASK_ID.findall(row[2]) if d != task["id"]]
            link = first_link(row[0])
            if link:
                tf = (plan.parent / link).resolve()
                if tf.is_file():
                    task["task_file"] = str(tf.relative_to(root))
                    found = read_task_file(tf)
                    found["branch"] = found["branch"] if found["branch"] and not found["branch"].lower().startswith("unassigned") else task["branch"]
                    task.update(found)
            track["tasks"].append(task)
    return track


def read_plain_words(root: Path, kind: str) -> dict[str, str]:
    """Key -> plain-English line from the docs/tracks/plain-words.md table whose first header is `kind`."""
    path = root / "docs/tracks/plain-words.md"
    if not path.is_file():
        return {}
    out = {}
    for table in tables(path.read_text(encoding="utf-8")):
        if strip_md(table[0][0]).lower() != kind:
            continue
        for row in table[1:]:
            if len(row) >= 2 and row[1].strip():
                out[strip_md(row[0])] = strip_md(row[1])
    return out


def critical_path(tasks: list[dict]) -> list[str]:
    """The longest chain of unfinished tasks linked by `depends_on`, as anchors."""
    by_anchor = {t["anchor"]: t for t in tasks if t["state"] not in DONE_STATES}
    memo: dict[str, list[str]] = {}

    def chain(a: str, seen: frozenset) -> list[str]:
        if a in memo:
            return memo[a]
        best: list[str] = []
        for dep in by_anchor[a]["deps"]:
            if dep in by_anchor and dep not in seen:
                c = chain(dep, seen | {a})
                if len(c) > len(best):
                    best = c
        memo[a] = best + [a]
        return memo[a]

    longest: list[str] = []
    for a in by_anchor:
        c = chain(a, frozenset())
        if len(c) > len(longest):
            longest = c
    return longest if len(longest) > 1 else []


def number(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_findings(root: Path, tracks: list[dict], live: dict) -> dict:
    """Rows and reading lines from each track's evidence; a kept track's come from the published `live` findings."""
    rows, readings = [], []
    for tr in tracks:
        if tr.get("kept"):
            rows += [dict(r) for r in live.get("rows") or [] if r.get("track") == tr["slug"]]
            readings += [r for r in live.get("readings") or [] if r.get("plan") == tr["path"]]
            continue
        evidence = root / "docs/tracks" / tr["slug"] / "evidence"
        found = False
        for f in sorted(evidence.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for rep in data if isinstance(data, list) else [data]:
                if not isinstance(rep, dict) or rep.get("format") != "bench-report/v1":
                    continue
                found = True
                m = rep.get("metrics") or {}
                clusters = m.get("clusters")
                cands = m.get("candidates")
                support = m.get("support")
                rows.append({
                    "variant": rep.get("variant"), "kind": rep.get("kind"), "set": rep.get("set"),
                    "records": number(rep.get("records")), "labelled": number(rep.get("labelled")),
                    "purity": number(m.get("purity")), "inverse_purity": number(m.get("inverse_purity")),
                    "ari": number(m.get("ari")), "coverage": number(m.get("coverage")),
                    "coverage_overall": number(m.get("coverage_overall")),
                    "candidates": number(cands.get("count") if isinstance(cands, dict) else cands),
                    "support": number(support.get("median") if isinstance(support, dict) else support),
                    "clusters": number(clusters.get("count") if isinstance(clusters, dict) else clusters),
                    "abstained": number(m.get("abstained")),
                    "params": {k: v for k, v in (rep.get("params") or {}).items() if isinstance(v, (int, float, str, bool))},
                    "file": str(f.relative_to(root)), "track": tr["slug"],
                })
        if found:
            text = (root / tr["path"]).read_text(encoding="utf-8")
            for m in re.finditer(r"^- \*\*(.+?)\*\*\s*(.*?)(?=^\S|^- |\Z)", section(text, "Findings"), re.M | re.S):
                readings.append({"lead": strip_md(m.group(1)), "text": strip_md(" ".join(m.group(2).split())),
                                 "plan": tr["path"], "track": tr["title"]})
    # Rows that share a method and a set are told apart by the parameters that differ.
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["variant"], r["set"], r["kind"]), []).append(r)
    for same in groups.values():
        keys = sorted({k for r in same for k in r["params"]})
        differ = [k for k in keys if len({json.dumps(r["params"].get(k)) for r in same}) > 1] if len(same) > 1 else []
        for r in same:
            r["note"] = ", ".join(f"{k} {r['params'].get(k)}" for k in differ) or None
    sets = []
    for kind, metric in BEST_METRIC.items():
        for s in sorted({r["set"] for r in rows if r["kind"] == kind and r["set"]}):
            scored = [r for r in rows if r["kind"] == kind and r["set"] == s and r[metric] is not None]
            if scored:
                top = max(r[metric] for r in scored)
                names = [r["variant"] + (f" ({r['note']})" if r["note"] else "") for r in scored if r[metric] == top]
                sets.append({"kind": kind, "set": s, "metric": metric, "rows": len(scored),
                             "best": {"variants": sorted(names), "value": top}})
    columns = {k: {"label": label, "help": help_} for k, (label, help_) in COLUMNS.items()}
    for k, words in read_plain_words(root, "column").items():
        if k in columns:
            columns[k]["help"] = words
    kinds = dict(KIND_NAMES, **read_plain_words(root, "kind"))
    return {"rows": rows, "readings": readings, "sets": sets, "columns": columns, "kind_columns": KIND_COLUMNS, "kinds": kinds,
            "methods": read_plain_words(root, "variant"), "set_words": read_plain_words(root, "set")}


def read_records(root: Path) -> list[dict]:
    """Decision records `docs/inputs/<yyyy-mm-dd>-<slug>.md`, newest first."""
    out = []
    for f in sorted((root / "docs/inputs").glob("*.md"), reverse=True):
        m = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)\.md$", f.name)
        if not m:
            continue
        text = f.read_text(encoding="utf-8")
        h1 = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), f.stem)
        top = bullets(text.split("\n## ", 1)[0])
        rec = {
            "anchor": "rec-" + f.stem, "date": m.group(1), "file": str(f.relative_to(root)),
            "title": re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", h1),
            "asked": strip_md(top.get("Asked on", "")), "acted": strip_md(top.get("Acted on in", "")),
            "questions": [], "items": None,
        }
        for qm in re.finditer(r"^###\s+([A-Za-z0-9_.~-]+):\s*(.+?)\n(.*?)(?=^#{1,3}\s|\Z)", section(text, "Questions and answers"), re.M | re.S):
            block = qm.group(3)
            body = []
            for para in re.split(r"\n\s*\n", block):
                if para.strip() and not para.lstrip().startswith(("|", "- ")):
                    body.append(" ".join(para.split()))
            options = []
            for table in tables(block):
                if strip_md(table[0][0]).lower() == "option":
                    options = [{"label": strip_md(r[0]), "detail": strip_md(r[1]) if len(r) > 1 else ""} for r in table[1:]]
            b = bullets(block)
            chose = strip_md(b.get("Owner chose", ""))
            choice, _, note = chose.partition(" Note: ")
            note = note.strip().strip('"').strip()
            rec["questions"].append({
                "id": qm.group(1), "anchor": "rec-" + qm.group(1), "title": strip_md(qm.group(2)),
                "body": strip_md("\n\n".join(body)), "options": options,
                "recommended": strip_md(b.get("Recommended", "")), "choice": choice.strip().rstrip("."),
                "note": "" if note.lower().rstrip(".") == "none" else note, "next": strip_md(b.get("What happened next", "")),
            })
        items = section(text, "Items reviewed")
        if items.strip():
            b = bullets(items)
            rec["items"] = {"shown": strip_md(b.get("What was shown", "")), "result": strip_md(b.get("Result", "")),
                            "next": strip_md(b.get("What happened next", ""))}
        out.append(rec)
    return out


def read_prs(prs: list[dict] | None) -> list[dict]:
    out = []
    for pr in prs or []:
        out.append({"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("url"),
                    "branch": pr.get("headRefName"), "state": "open" if pr.get("isDraft") else "ready",
                    "updated": pr.get("updatedAt")})
    return sorted(out, key=lambda p: p["number"] or 0)


RAW_TASK = ("id", "name", "deliverable", "track", "task_file", "state", "pr", "pr_link", "updated", "needs_owner", "branch", "depends_on")
RAW_TRACK = ("slug", "title", "path", "state", "updated", "done", "coordinator", "done_when", "budget")


def keep_live(tracks: list[dict], live: dict, own: set[str]) -> list[dict]:
    """Every track the session does not own, as the published state has it; the owned ones from the files.

    A track only in the checkout is added: it replaces nothing that was published."""
    if not isinstance(live, dict) or live.get("format") != "control-room-state/v1" or not live.get("tracks"):
        raise SystemExit("the live state is not a published control-room-state/v1 file with tracks: "
                         "read the published state.json again, or pass --all to publish every track from this checkout")
    unknown = sorted(own - {tr["slug"] for tr in tracks})
    if unknown:
        raise SystemExit(f"no track {', '.join(unknown)} under docs/tracks/")
    by_anchor = {t["anchor"]: t for t in live.get("tasks") or []}
    lines = {p["anchor"]: p["text"] for p in live.get("plain_words") or []}
    kept = {}
    for tr in live["tracks"]:
        if tr["slug"] in own:
            continue
        tasks = []
        for a in tr.get("tasks") or []:
            t = by_anchor.get(a)
            if not t:
                continue
            # A state file from an older generator has no depends_on; its resolved deps say the same.
            deps = t["depends_on"] if "depends_on" in t else [by_anchor[d]["id"] for d in t.get("deps") or [] if d in by_anchor]
            tasks.append({k: t.get(k) for k in RAW_TASK} | {"depends_on": deps, "live_plain": t.get("plain"), "live_line": lines.get(a)})
        kept[tr["slug"]] = {k: tr.get(k) for k in RAW_TRACK} | {"tasks": tasks, "kept": True}
    out = [kept.pop(tr["slug"], tr) for tr in tracks]
    return sorted(out + list(kept.values()), key=lambda tr: tr["slug"])


def collect(root: Path, prs: list[dict] | None = None, now: dt.datetime | None = None,
            live: dict | None = None, own: set[str] | None = None) -> dict:
    root = root.resolve()
    lanes = read_lanes(root, read_config(root))
    models = {l["key"]: l["model"] for l in lanes}
    tracks = [read_track(p, root) for p in sorted((root / "docs/tracks").glob("*/plan.md")) if p.parent.name != "_templates"]
    if live is not None:
        tracks = keep_live(tracks, live, own or set())
    plain = read_plain_words(root, "task")
    lane_keys = {l["key"] for l in lanes}
    tasks = [t for tr in tracks for t in tr["tasks"]]
    lines: dict[str, str | None] = {}

    # Anchors: `task-<id>`; when an ID repeats across tracks, the task in an active track
    # keeps the short form and the others get `task-<track>-<id>`.
    seen: dict[str, int] = {}
    for t in tasks:
        seen[t["id"]] = seen.get(t["id"], 0) + 1
    taken = set()
    for t in sorted(tasks, key=lambda t: next(tr["done"] for tr in tracks if tr["slug"] == t["track"])):
        short = "task-" + re.sub(r"[^A-Za-z0-9_.~-]", "-", t["id"])
        t["anchor"] = short if short not in taken else f"task-{t['track']}-{re.sub(r'[^A-Za-z0-9_.~-]', '-', t['id'])}"
        taken.add(t["anchor"])

    done_slugs = {tr["slug"] for tr in tracks if tr["done"]}
    for t in tasks:
        same_track = {o["id"]: o["anchor"] for o in tasks if o["track"] == t["track"]}
        unique = {o["id"]: o["anchor"] for o in tasks if seen[o["id"]] == 1}
        t["deps"] = [same_track.get(d) or unique.get(d) for d in t["depends_on"] if same_track.get(d) or unique.get(d)]
        # A kept task keeps its published words; the others take this checkout's plain words.
        lines[t["anchor"]] = t.pop("live_line") if "live_line" in t else plain.get(t["id"])
        t["plain"] = (t.pop("live_plain") if "live_plain" in t else plain.get(t["id"])) or t["deliverable"]
        prefix = re.match(r"[A-Z]+", t["id"])
        t["lane"] = None
        if prefix and t["track"] not in done_slugs:
            p = prefix.group(0)
            t["lane"] = p if p in lane_keys else (p[0] if p[0] in lane_keys else None)
        t["model"] = models.get(t["lane"]) if t["lane"] else None

    active_tasks = [t for t in tasks if t["track"] not in done_slugs]
    path = critical_path(active_tasks)
    for t in tasks:
        t["critical"] = t["anchor"] in path

    pr_list = read_prs(prs)
    by_branch = {t["branch"]: t["anchor"] for t in active_tasks if t["branch"]}
    for pr in pr_list:
        pr["task"] = by_branch.get(pr["branch"])

    rows = [dict(l, kind="lane",
                 tasks=[t["anchor"] for t in active_tasks if t["lane"] == l["key"]]) for l in lanes]
    for tr in tracks:
        loose = [t["anchor"] for t in tr["tasks"] if not tr["done"] and not t["lane"]]
        if loose:
            rows.append({"kind": "track", "key": None, "slug": tr["slug"], "name": tr["title"], "work": "", "where": "",
                         "plan": tr["path"], "model": None, "tasks": loose})

    needs = []
    for t in active_tasks:
        if t["needs_owner"]:
            needs.append({"kind": "decision", "task": t["anchor"], "text": f"{t['id']}: {t['needs_owner']}", "link": t["task_file"]})
        elif t["state"] == "review":
            needs.append({"kind": "review", "task": t["anchor"], "text": f"{t['id']} proposes done and waits for review", "link": t["pr_link"] or t["task_file"]})

    now = now or dt.datetime.now(dt.timezone.utc)
    return {
        "format": "control-room-state/v1",
        "project": project_info(root),
        "revision": git(root, "rev-parse", "--short=12", "HEAD"),
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prs_included": prs is not None,
        "lanes": rows,
        "tracks": [{k: tr[k] for k in ("slug", "title", "path", "state", "updated", "done", "coordinator", "done_when", "budget")} | {"tasks": [t["anchor"] for t in tr["tasks"]]} for tr in tracks],
        "tasks": tasks,
        "critical_path": path,
        "needs": needs,
        "prs": pr_list,
        "findings": read_findings(root, tracks, (live or {}).get("findings") or {}),
        "records": read_records(root),
        "plain_words": [{"id": t["id"], "anchor": t["anchor"], "text": lines[t["anchor"]]} for t in tasks if lines[t["anchor"]] and t["track"] not in done_slugs],
        "counts": {
            "tasks": len(active_tasks),
            "active": sum(t["state"] == "active" for t in active_tasks),
            "done": sum(t["state"] in DONE_STATES for t in active_tasks),
        },
    }


# ---------------------------------------------------------------- review items

def review(spec: dict) -> dict:
    """review.json from a spec: either the items object itself or a spec with an `items` key."""
    items = spec.get("items", spec)
    rows = items.get("rows") or []
    if not items.get("field"):
        raise SystemExit("review spec needs `field`: the question asked of each item")
    ids = set()
    for r in rows:
        rid = str(r.get("id", ""))
        if not SAFE_ID.fullmatch(rid) or len(rid) > 120:
            raise SystemExit(f"review item id {rid!r} must use letters, digits and . _ ~ - only")
        if rid in ids:
            raise SystemExit(f"review item id {rid!r} repeats")
        ids.add(rid)
    keep = ("heading", "lede", "field", "placeholder", "assist")
    return {"format": "control-room-review/v1", **{k: items[k] for k in keep if items.get(k)},
            "rows": [{k: r[k] for k in ("id", "title", "meta_short", "meta", "turns", "tags") if k in r} for r in rows]}


# ---------------------------------------------------------------- store documents

STORE_SCHEMA = json.loads((HERE / "store-schema.json").read_text(encoding="utf-8"))
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")


def check_doc(collection: str, doc_id: str, data: dict) -> dict:
    """The payload to write, or SystemExit naming every way `data` breaks store-schema.json."""
    schema = STORE_SCHEMA.get(collection)
    if not isinstance(schema, dict) or collection == "about":
        raise SystemExit(f"no store collection {collection!r}")
    errors = [] if re.fullmatch(schema["id"], doc_id) else [f"id {doc_id!r} does not match {schema['id']}"]
    fields = schema["fields"]
    errors += [f"unknown field {k!r} (allowed: {', '.join(fields)})" for k in data if k not in fields]
    errors += [f"missing field {k!r}" for k, f in fields.items() if f.get("required") and k not in data]
    option_ids = [o.get("id") for o in data.get("options") or [] if isinstance(o, dict)]
    for k, v in data.items():
        f = fields.get(k)
        if not f:
            continue
        kind = f["type"]
        ok = {
            "string": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": isinstance(v, int) and not isinstance(v, bool), "time": isinstance(v, str) and bool(TIME.fullmatch(v)),
            "https": isinstance(v, str) and v.startswith("https://"), "option-id": v in option_ids,
            "options": isinstance(v, list) and len(v) > 0 and all(
                isinstance(o, dict) and set(o) <= {"id", "label", "detail"} and isinstance(o.get("id"), str)
                and SAFE_ID.fullmatch(o["id"]) and isinstance(o.get("label"), str) for o in v)
                and len(set(option_ids)) == len(v),
        }[kind]
        if ok and "enum" in f and v not in f["enum"]:
            ok, kind = False, " | ".join(f["enum"])
        if not ok:
            errors.append(f"field {k!r} must be {kind}, not {json.dumps(v)}")
    if collection == "events" and isinstance(data.get("number"), int) and doc_id != f"pr-{data['number']}":
        errors.append(f"id {doc_id!r} must be pr-{data['number']}")
    if errors:
        raise SystemExit(f"{collection}/{doc_id} is not a valid store document:\n- " + "\n- ".join(errors))
    return {"collection": collection, "doc_id": doc_id, "data": data}


def card(args) -> dict:
    options = []
    for o in args.option:
        if len(o) not in (2, 3):
            raise SystemExit("--option takes ID LABEL [DETAIL]")
        options.append(dict(zip(("id", "label", "detail"), o)))
    data = {"title": args.title, "body": args.body, "options": options}
    data.update({k: v for k, v in (("order", args.order), ("task", args.task), ("recommended", args.recommended), ("why", args.why)) if v is not None})
    return check_doc("questions", args.id, data)


def event(args) -> dict:
    data = {"number": args.number, "state": args.state,
            "updated": args.updated or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    data.update({k: v for k, v in (("title", args.title), ("url", args.url)) if v is not None})
    return check_doc("events", f"pr-{args.number}", data)


# ---------------------------------------------------------------- session brief and handoff

PROGRAM_DUTIES = [
    "watch for merges and record them (the merge watcher)",
    "after each merge, bring every open PR back onto main (scripts/rebase-open-prs.sh); send a conflict to its developer",
    "record each answered round of decisions under docs/inputs/",
    "settle conflicts between tracks (shared files, order of merges)",
]


def first_paragraph(text: str) -> str:
    return next((strip_md(" ".join(p.split())) for p in re.split(r"\n\s*\n", text) if p.strip() and not p.lstrip().startswith(("|", "-", "#"))), "")


def task_lines(root: Path, state: dict, track: dict) -> tuple[list[str], list[str]]:
    """One line per task, and the lines for what is blocked."""
    by = {t["anchor"]: t for t in state["tasks"]}
    lines, blocked = [], []
    for a in track["tasks"]:
        t = by[a]
        notes = bullets((root / t["task_file"]).read_text(encoding="utf-8")) if t["task_file"] else {}
        bits = [t["state"]] + [f"branch `{t['branch']}`"] * bool(t["branch"]) + [t["pr"]] * bool(t["pr"])
        lines.append(f"- {t['id']} {t['name']}: {', '.join(bits)}" + (f". Next: {strip_md(notes['Next action'])}" if notes.get("Next action") else ""))
        waits = [by[d]["id"] for d in t["deps"] if by[d]["state"] not in DONE_STATES]
        if t["state"] == "blocked":
            blocked.append(f"- {t['id']}: {strip_md(notes.get('Blocker', 'blocked, no Blocker line in the task file'))}")
        elif waits and t["state"] not in DONE_STATES:
            blocked.append(f"- {t['id']} waits for {', '.join(waits)}")
    return lines, blocked


def next_action(root: Path, state: dict, tr: dict) -> str | None:
    """A track's next action: the plan's Handoff "Next action", else the planned tasks whose
    dependencies are all done ("dispatch ..."), else None."""
    nxt = bullets(section((root / tr["path"]).read_text(encoding="utf-8"), "Handoff and memory")).get("Next action")
    if nxt:
        return strip_md(nxt)
    by = {t["anchor"]: t for t in state["tasks"]}
    ready = [by[a] for a in tr["tasks"] if by[a]["state"] == "planned" and all(by[d]["state"] in DONE_STATES for d in by[a]["deps"])]
    return "dispatch " + ", ".join(t["id"] + (f" (branch {t['branch']})" if t["branch"] else "") for t in ready) if ready else None


# The line that starts a track coordinator. A project may write its own in its program file
# (foreman.json "program", else docs/program.md) as a code span that starts with
# "Coordinate the <slug> track"; `<slug>` is then filled in. Otherwise this one is used.
COORDINATOR_LINE = ("Coordinate the <slug> track. Read {read}, then do the plan's next step. "
                    "You own only that track's plan and task files; the program session owns everything else. "
                    "Refresh and publish the control room before you report anything.")


def program_file(root: Path) -> str:
    return read_config(root).get("program") or "docs/program.md"


def coordinator_prompts(root: Path, state: dict | None = None) -> list[dict]:
    """One first prompt per active track that has a next action: the coordinator line with the
    track's slug, then at most two sentences of the next action."""
    root = root.resolve()
    state = state or collect(root)
    out = []
    for tr in state["tracks"]:
        nxt = None if tr["done"] else next_action(root, state, tr)
        if not nxt:
            continue
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", "Next action in the plan: " + nxt.rstrip(".") + ".")
        out.append({"slug": tr["slug"], "prompt": coordinator_line(root, tr) + " " + " ".join(sentences[:2])})
    return out


def coordinator_line(root: Path, tr: dict) -> str:
    """The line that starts a track's coordinator, with its slug filled in: the project's own
    line from its program file, else COORDINATOR_LINE."""
    program = program_file(root)
    text = (root / program).read_text(encoding="utf-8") if (root / program).is_file() else ""
    own = next(iter(re.findall(r"`(Coordinate the <slug> track[^`]*)`", text)), None)
    read = [f for f in (program, "docs/sdlc.md") if (root / f).is_file()] + [tr["path"]]
    line = own or COORDINATOR_LINE.format(read=", ".join(read[:-1]) + " and " + read[-1] if len(read) > 1 else read[0])
    return line.replace("<slug>", tr["slug"])


def open_cards(store: dict | None, task_ids: set[str] | None) -> list[dict]:
    answers = (store or {}).get("answers") or {}
    return [q for q in (store or {}).get("questions") or [] if not (answers.get(q["id"]) or {}).get("choice")
            and (task_ids is None or q.get("task") in task_ids)]


def brief(root: Path, scope: str, slug: str | None = None, prs: list[dict] | None = None, store: dict | None = None) -> str:
    """The starting brief of a track coordinator (`track`) or of the program session (`program`)."""
    root = root.resolve()
    state = collect(root, prs)
    read = [f for f in (program_file(root), "docs/sdlc.md") if (root / f).is_file()]
    active = [tr for tr in state["tracks"] if not tr["done"]]
    out = []
    if scope == "track":
        tr = next((t for t in state["tracks"] if t["slug"] == slug), None)
        if tr is None:
            raise SystemExit(f"no track {slug!r} under docs/tracks/")
        text = (root / tr["path"]).read_text(encoding="utf-8")
        lines, blocked = task_lines(root, state, tr)
        ids = {t["id"] for t in state["tasks"] if t["track"] == slug}
        mine = [p for p in state["prs"] if p["task"] in tr["tasks"]]
        nxt = next_action(root, state, tr)
        out += [f"# Brief: track {slug}, {tr['title']}", "",
                "Read first: " + ", ".join(read + [tr["path"]] + [t["task_file"] for t in state["tasks"] if t["track"] == slug and t["task_file"]]), "",
                f"- Goal: {first_paragraph(section(text, 'Goal and boundaries')) or 'no Goal and boundaries section'}",
                f"- State: {tr['state']}, updated {tr['updated'] or 'never'}",
                f"- Coordinator: {tr['coordinator'] or 'missing from the plan head'}",
                f"- Done when: {tr['done_when'] or 'missing from the plan head'}",
                f"- Budget: {tr['budget'] or 'missing from the plan head'}", "", "## Tasks", *lines, "",
                "## Blocked", *(blocked or ["- nothing"]), "",
                "## Open pull requests", *([f"- #{p['number']} {p['title']} ({'ready' if p['state'] == 'ready' else 'draft'})" for p in mine] or ["- none"] if prs is not None else ["- not read: pass --prs"]), "",
                "## Unanswered decision cards", *([f"- {q['id']}: {q.get('title', '')} (for {q.get('task')})" for q in open_cards(store, ids)] or ["- none"] if store is not None else ["- not read: pass --store"]), "",
                "## Next action", "- " + (nxt or "none written; read the plan")]
    else:
        out += ["# Brief: program", "", "Read first: " + ", ".join(read + [tr["path"] for tr in active]), "", "## Active tracks"]
        all_blocked = []
        for tr in active:
            lines, blocked = task_lines(root, state, tr)
            ids = {t["id"] for t in state["tasks"] if t["track"] == tr["slug"]}
            counts = {}
            for a in tr["tasks"]:
                st = next(t for t in state["tasks"] if t["anchor"] == a)["state"]
                counts[st] = counts.get(st, 0) + 1
            out.append(f"- {tr['slug']} ({tr['state']}): {', '.join(f'{n} {k}' for k, n in sorted(counts.items())) or 'no tasks'}; "
                       f"coordinator: {tr['coordinator'] or 'missing'}; done when: {tr['done_when'] or 'missing'}; budget: {tr['budget'] or 'missing'}"
                       + (f"; unanswered cards: {len(open_cards(store, ids))}" if store is not None else ""))
            all_blocked += [f"{b[:2]}{tr['slug']} {b[2:]}" for b in blocked]
        recorded = {q["id"] for r in state["records"] for q in r["questions"]}
        answered = [k for k, a in ((store or {}).get("answers") or {}).items() if (a or {}).get("choice") and k not in recorded]
        loose = [p for p in state["prs"] if not p["task"]]
        out += ["", "## Blocked", *(all_blocked or ["- nothing"]), "",
                "## Pull requests outside every task", *([f"- #{p['number']} {p['title']}" for p in loose] or ["- none"] if prs is not None else ["- not read: pass --prs"]), "",
                "## Answered, not yet recorded under docs/inputs/", *([f"- {a}" for a in answered] or ["- none"] if store is not None else ["- not read: pass --store"]), "",
                "## Coordinators to start",
                "Each coordinator is its own Claude Code session in this repository, never a subagent of this one. "
                "Start the ones not running with the `coordinators` skill, or paste a line into a new session.",
                *([f"- {c['prompt']}" for c in coordinator_prompts(root, state)] or ["- none: no active track has a next action"]), "",
                "## Only the program session does", *[f"- {d}" for d in PROGRAM_DUTIES]]
    return "\n".join(out) + "\n"


def handoff(root: Path, slug: str, text: str, today: dt.date | None = None) -> Path:
    """Write the plan's "Handoff and memory" section and set its Updated line to today."""
    plan = root / "docs/tracks" / slug / "plan.md"
    src = plan.read_text(encoding="utf-8")
    body = "## Handoff and memory\n\n" + text.strip() + "\n\n"
    m = re.search(r"^## Handoff and memory[^\n]*\n.*?(?=^## |\Z)", src, re.M | re.S)
    if m:
        src = src[:m.start()] + body + src[m.end():]
    elif re.search(r"^## Closure", src, re.M):
        src = re.sub(r"^## Closure", lambda _: body + "## Closure", src, count=1, flags=re.M)
    else:
        src = src.rstrip() + "\n\n" + body
    day = (today or dt.date.today()).isoformat()
    src, n = re.subn(r"^- Updated:.*$", f"- Updated: {day}", src, count=1, flags=re.M)
    if not n:
        raise SystemExit(f"{plan} has no '- Updated:' line in its head")
    plan.write_text(src.rstrip() + "\n", encoding="utf-8")
    return plan


# ---------------------------------------------------------------- page

def page(title: str) -> str:
    src = (TEMPLATE_DIR / "page.html").read_text(encoding="utf-8")
    css = (TEMPLATE_DIR / "page.css").read_text(encoding="utf-8")
    js = (TEMPLATE_DIR / "render.js").read_text(encoding="utf-8") + "\n" + (TEMPLATE_DIR / "app.js").read_text(encoding="utf-8")
    if "</script" in js.lower() or "</style" in css.lower():
        raise SystemExit("page source must not close its own script or style tag")
    return src.replace("{{TITLE}}", html.escape(title)).replace("/*{{CSS}}*/", css).replace("/*{{JS}}*/", js)


def write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("state", help="write state.json from the repository")
    s.add_argument("--root", default=".")
    s.add_argument("--out", required=True)
    s.add_argument("--prs", help="JSON from gh pr list")
    s.add_argument("--live", help="the published state.json; keeps every track not named by --own")
    s.add_argument("--own", nargs="+", default=[], help="the track slugs this session owns; none when left out")
    r = sub.add_parser("review", help="write review.json from a review spec")
    r.add_argument("--spec", required=True)
    r.add_argument("--out", required=True)
    p = sub.add_parser("page", help="write the static page")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p.add_argument("--title", help="the page name; default: foreman.json's title, else '<project> Control Room'")
    b = sub.add_parser("brief", help="print a session's starting brief")
    b.add_argument("scope", choices=["track", "program"])
    b.add_argument("slug", nargs="?")
    b.add_argument("--root", default=".")
    b.add_argument("--prs", help="JSON from gh pr list")
    b.add_argument("--store", help="the control room store: {questions: [...], answers: {...}}")
    h = sub.add_parser("handoff", help="write a plan's Handoff and memory section")
    h.add_argument("--root", default=".")
    h.add_argument("--track", required=True)
    h.add_argument("--text", required=True, help="a file with the section's body")
    c = sub.add_parser("card", help="print a decision card for the store: questions/<id>")
    c.add_argument("--id", required=True)
    c.add_argument("--title", required=True)
    c.add_argument("--body", required=True)
    c.add_argument("--option", nargs="+", action="append", required=True, metavar="ID LABEL [DETAIL]")
    c.add_argument("--task")
    c.add_argument("--order", type=int)
    c.add_argument("--recommended", help="the id of the option the coordinator would pick")
    c.add_argument("--why")
    e = sub.add_parser("event", help="print a pull request event for the store: events/pr-<n>")
    e.add_argument("kind", choices=["pr"])
    e.add_argument("number", type=int)
    e.add_argument("state", choices=STORE_SCHEMA["events"]["fields"]["state"]["enum"])
    e.add_argument("--title")
    e.add_argument("--url")
    e.add_argument("--updated", help="UTC time, YYYY-MM-DDTHH:MM:SSZ; default now")
    args = ap.parse_args(argv)
    load = lambda f: json.loads(Path(f).read_text(encoding="utf-8")) if f else None

    if args.cmd == "state":
        if args.own and not args.live:
            raise SystemExit("--own needs --live: the published state.json to keep the other tracks from")
        model = collect(Path(args.root), load(args.prs), live=load(args.live), own=set(args.own))
        Path(args.out).write_text(json.dumps(model, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"tasks": len(model["tasks"]), "lanes": len(model["lanes"]), "prs": len(model["prs"]),
                          "findings": len(model["findings"]["rows"]), "records": len(model["records"]),
                          "critical_path": model["critical_path"]}))
    elif args.cmd == "review":
        data = review(load(args.spec))
        Path(args.out).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"items": len(data["rows"]), "bytes": Path(args.out).stat().st_size}))
    elif args.cmd == "page":
        root = Path(args.root).resolve()
        title = args.title or read_config(root).get("title") or f"{project_info(root)['name']} Control Room"
        changed = write_if_changed(Path(args.out), page(title))
        print(json.dumps({"title": title, "changed": changed}))
    elif args.cmd == "brief":
        if args.scope == "track" and not args.slug:
            raise SystemExit("brief track needs the track's slug")
        sys.stdout.write(brief(Path(args.root), args.scope, args.slug, load(args.prs), load(args.store)))
    elif args.cmd in ("card", "event"):
        print(json.dumps((card if args.cmd == "card" else event)(args), ensure_ascii=False))
    elif args.cmd == "handoff":
        print(handoff(Path(args.root), args.track, Path(args.text).read_text(encoding="utf-8")))


if __name__ == "__main__":
    main(sys.argv[1:])
