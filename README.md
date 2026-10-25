# foreman

A Claude Code plugin for running a software project with one owner and many agent
sessions. It gives a project:

- **Plans and tasks under fixed conventions.** Each track of work has a plan file; each
  task has a task file. Every session can start from these files alone.
- **Parallel sessions.** One coordinator session per track, one developer session per
  task, a read-only reviewer pass per pull request, and a thin program session that
  ties the tracks together.
- **A control room.** One private page for the owner, made from the files. It shows
  what waits for the owner, the lanes and tasks, findings and records, and takes the
  owner's decisions.

This file is the one place where the conventions are written. Skills and agents link
here instead of repeating them.

## Install

Add this repository as a plugin marketplace, then install the plugin:

```text
/plugin marketplace add pdhoolia/foreman
/plugin install foreman@foreman
```

From a local checkout instead: `/plugin marketplace add ./path/to/foreman`, then the
same install line. To try it for one session without installing:
`claude --plugin-dir ./path/to/foreman`.

The skills are then named `/foreman:<skill>`, for example `/foreman:pm-start`.

## Set up a project

1. Add `foreman.json` at the project's root (shape below).
2. Copy the templates you need from `templates/`: `program.md` and `sdlc.md` to
   `docs/`, `plan.md` and `task.md` to `docs/tracks/_templates/`, `record.md` to
   `docs/inputs/_template/`.
3. Write the first track plan at `docs/tracks/<slug>/plan.md`.
4. Publish the control room (see "The control room").

The tools need `python3`, `git` and `gh` (signed in to the project's GitHub account).
The page's tests also use `node` when it is installed.

### foreman.json

```json
{
  "title": "Pantry Notes Control Room",
  "control_room_url": "<the control room's link, after the first publish>",
  "tracks": [
    {"slug": "bench", "lanes": [
      {"key": "A", "name": "search bench", "work": "score search ideas offline",
       "where": "local", "model": "the model and effort this lane runs on"}
    ]}
  ]
}
```

- `title`: the page's name. Without it: "<repository name> Control Room".
- `control_room_url`: the published page. The refresh prints it as the publish target.
- `tracks`: the lanes of each track. A lane's key is a task ID prefix: task `A01` goes
  to lane `A`, `CS01` to lane `CS` or else `C`. A track with no lanes listed shows as
  one row of its own.

## Roles

| Role | Does | Never |
| --- | --- | --- |
| Owner | Sets priorities. Decides through the control room. Merges. Overrules any default. | |
| Track coordinator | Owns one track's `plan.md` and task files. Dispatches its tasks, reviews its PRs before the owner sees them, asks the owner through cards, refreshes the control room. | Edits another track's files or the program files. |
| Program session | Owns `docs/program.md` and `docs/sdlc.md`. Watches merges, brings open PRs back onto `main` after each merge, records answered rounds, settles conflicts between tracks. | Does task work. |
| Developer | Delivers one task in its own checkout and branch, in one PR that proposes the task `done`. | Changes paths its task file does not own. |
| Reviewer | Reads a PR against its task file and sends findings to the developer. | Writes to the PR. |
| Scribe | Writes records (decision rounds, handoffs, plain-words lines) from given facts. | Edits code. |

A coordinator holds no state outside the repository and the control room's store. Any
session can take its role over from the files.

## The conventions

### Where things live

```text
foreman.json                           page title, control room link, lanes per track
docs/program.md                        the program session's brief (optional)
docs/sdlc.md                           this project's own rules (optional)
docs/tracks/<slug>/plan.md             a track: goal, head lines, task table, closure
docs/tracks/<slug>/tasks/<ID>-<name>.md  a task: state, handoff, evidence
docs/tracks/<slug>/evidence/           small reports, when useful
docs/tracks/plain-words.md             one plain line per task, method, set, column
docs/inputs/<yyyy-mm-dd>-<slug>.md     one record per round of owner decisions
```

`docs/tracks/_templates/` is skipped by the tools.

### Plan head lines

The bullets before the first `##` heading of a plan:

- `- State:` `draft`, `active`, `blocked`, `complete` or `dropped`. The first word
  counts. A `complete`, `done`, `accepted` or `dropped` track is folded on the page.
- `- Coordinator:` the session that owns the track.
- `- Done when:` the observable state that closes the track.
- `- Budget:` developer sessions, review rounds, owner decisions, money or compute.
  A coordinator that would go over it asks the owner first.
- `- Updated:` the date of the last change.

The page shows `Coordinator`, `Done when` and `Budget` on the track's lane.

### Task table

A plan's task table is the first table whose first header cell starts with "ID". Its
columns: ID and name, deliverable, depends on, owned paths, assigned branch. The first
cell links the task file: `[W01: list model](tasks/W01-list-model.md)`. Task IDs in the
"depends on" cell become dependencies; the longest chain of unfinished tasks is the
critical path.

### Task file bullets

- `- State:` `planned`, `active`, `blocked`, `review`, `done` or `dropped`. The first
  word counts.
- `- Issue / PR:` a link, or "not created".
- `- Branch:` the first code span is the branch, for example `` `alice/list-model` ``.
- `- Updated:` the date.
- `- Needs owner:` optional. Puts a note under the page's Needs you tab.
- Under `## Handoff and memory`: `- Current result:`, `- Decisions/findings:`,
  `- Blocker:` and `- Next action:`. The session brief reads `Blocker` and
  `Next action`.

A task is `done` only when its PR is merged. On a branch, `done` is a proposal.

### Branches and pull requests

- Branch names: `<git-handle>/<short-kebab-description>`. Never an agent prefix.
- One writer per branch and checkout.
- One PR per task, against `main`, opened as a draft and marked ready only when the
  project's checks pass. The body says the problem, what changes, how it was tested
  (every check that ran, and any that could not), and what is not done.
- A developer takes the recommended default on a small question and marks it in the
  PR as "default taken, owner may overrule". It stops for a scope change, a privacy
  risk or anything outward-facing.

### Plain words

Everything the owner reads (cards, PR bodies, records) is written so that a newcomer
can follow it: short sentences, one idea each, common words. `docs/tracks/plain-words.md`
holds tables whose first header cell names what they explain:

| First header cell | Explains |
| --- | --- |
| `Task` | a task card's hover line, and the Records tab's plain-words list |
| `Variant` | a method in the Findings tab |
| `Set` | a set in the Findings tab |
| `Column` | a findings column; replaces the built-in help |
| `Kind` | a kind of finding; replaces its heading |

### Decision records

One file per round: `docs/inputs/<yyyy-mm-dd>-<slug>.md`, from `templates/record.md`.
Keep its shape: `### <question id>: <title>`, the body, an `Option | What it means`
table, then the `Recommended:`, `**Owner chose:** <choice>. Note: <note>` and
`What happened next:` bullets. An optional `## Items reviewed` section holds counts
only. The question id is the card's id, which links a decided card to its record.

### Findings

A track may keep `bench-report/v1` JSON reports (one report or a list) under its
`evidence/` folder. Each becomes a row on the Findings tab. The plan's `## Findings`
section gives the reading lines: each bullet that starts with a bold sentence.

## Skills

| Skill | Use it to |
| --- | --- |
| `pm-start track <slug>` / `pm-start program` | build a session's brief: goal, done when, budget, each task's state, what is blocked, open PRs, unanswered cards, the next action |
| `pm-handoff <slug>` | write the plan's "Handoff and memory" section, bump `Updated`, refresh |
| `dispatch <task file>` | check a task is ready, record the dispatch, write the developer's brief |
| `review <PR>` | the read-only review pass and the ready gate |
| `inputs ask \| review \| record` | ask the owner, read the answers back, record the round |
| `refresh [own track slugs]` | regenerate the control room's files and print the publish parameters |

## The control room

One private page, published with Claude's Artifact tool. Its tabs:

| Tab | Anchor | Shows |
| --- | --- | --- |
| Needs you | `#needs` | open decision cards, PRs ready for review (drafts folded), task notes |
| Lanes | `#lanes` | lanes with task cards, the plain-words hover, the critical path, finished tracks folded |
| Findings | `#findings` | scored rows per kind, the best method per set, the reading lines |
| Review | `#review` | items to label, one at a time; hidden when no round is open |
| Records | `#records` | decisions saved on the page, the records under `docs/inputs/`, the plain-words lines |

Card anchors: `#q-<question id>`, `#task-<task id>`, `#item-<item id>`,
`#rec-<question id>`, `#pr-<number>`. A link opens the right tab at the card.

### Why the page reads files

A published page may fetch only files published beside it, so it cannot reach GitHub.
`scripts/control_room.py state` reads the checkout and writes `state.json`, which is
published beside the page. The page embeds no data. Agents never edit the page or the
state file; they edit their own plan and task files, and the coordinator refreshes.

What cannot come from git lives in the page's store:

| Store path | Written by | Shape |
| --- | --- | --- |
| `questions/<id>` | the coordinator | `{order, task, title, body, options: [{id, label, detail}], recommended, why}` |
| `answers/<id>` | the page, when the owner saves | `{choice, note, updated}` |
| `events/pr-<n>` | a pull request watcher | `{number, title, url, state: open\|ready\|merged, updated}` |
| `labels/<item id>` | the page, when the owner labels an item | `{goal, said?, updated}` |

A pull request event newer than the state file wins over it; an older one is ignored.

`scripts/store-schema.json` fixes these shapes: a field it does not list, or a missing
required one, is refused. Never type a store document by hand. Build it, and write
exactly what the script prints with the ArtifactData tool:

```bash
python3 scripts/control_room.py card --id <id> --title "<title>" --body "<body>" \
  --option <id> "<label>" "<detail>" --option ... [--task <ID>] [--order <n>] [--recommended <id>] [--why "<why>"]
python3 scripts/control_room.py event pr <number> <open|ready|merged|closed> [--title "<title>"] [--url <url>]
```

### Publish a control room for a new project

1. Run the `refresh` skill with no track names. It writes `index.html` and
   `state.json` to a folder in your scratchpad and prints the publish parameters.
2. **First publish**, with the Artifact tool: `file_path` the printed `index.html`,
   `files` `{"state.json": ...}`, `capabilities` `{"db": {}, "user": {}, "sample": {}}`
   and `icon` `dashboard`. The first publish needs all three: `db` holds the store,
   `sample` runs the Review tab's assistant, and `user` is declared with them.
3. Put the returned link in `foreman.json` as `control_room_url` and commit it.
4. Write the open decision cards into the store as `questions/<id>`.
5. **Every later publish:** run `refresh` and publish what it prints, with `url` set
   and without `capabilities`. The artifact keeps the ones it has.

### Several coordinators, one page

Each coordinator works from its own branch, so a state file made from one checkout
does not see another coordinator's unmerged changes. A coordinator therefore names the
tracks it owns: `refresh <slug>` first saves the published `state.json` and keeps every
other track as published. Only the named tracks come from the checkout. A program
session, or a first publish, names none.

### Privacy

`state.json` carries repository text and aggregates only. Review items are private:
they go into `review.json`, published beside the page and never committed. The page
sends an item's opening turns to the in-page assistant only when the owner asks for a
suggestion.

## Hooks

`hooks/hooks.json` has no entries in this version. Checks that run on their own come in
a later version.

## Layout and tests

```text
.claude-plugin/   plugin.json, marketplace.json
skills/           the six skills
agents/           developer, reviewer, scribe
scripts/          control_room.py, store-schema.json, control-room/ (the page), control-room-refresh.sh, rebase-open-prs.sh
templates/        plan, task, record, sample review spec, program, sdlc
hooks/            hooks.json
tests/            the generator's and the page's tests on invented fixtures
```

Run `python3 -m pytest` from the repository's root. The tests use only invented
fixtures: a made-up recipe app called Pantry Notes. When `claude` is installed, a test
also runs `claude plugin validate .`.
