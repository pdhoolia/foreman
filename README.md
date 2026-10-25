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
They call GitHub's REST API through `gh api` (`scripts/open-prs.sh`), which works where
gh's GraphQL calls such as `gh pr list` are refused. Without `gh`, a refresh still runs
and warns that it has no pull request list.
The page's tests also use `node` when it is installed.

### foreman.json

```json
{
  "title": "Pantry Notes Control Room",
  "control_room_url": "<the control room's link, after the first publish>",
  "checks": "scripts/local-checks.sh",
  "jargon": ["upsert", "idempotent"],
  "branch_prefixes": ["bot"],
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
- `checks`: the project's checks, a script path (run with bash) or a shell command,
  for example `"scripts/local-checks.sh"`. `scripts/check.sh` runs it for the ready
  gate. Without it, the ready gate checks only the task file.
- `jargon`: words the plain-language hook warns about, for example `["upsert"]`.
  Without it, the hook warns only on long sentences.
- `branch_prefixes`: more harness prefixes to refuse, besides `claude/`, `codex/` and
  `deepseek/`, for example `["bot"]`.

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
- `- Owner:` who sets priorities and merges (the template has it; the tools do not read it).

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
- `- Track:` a link to the track's plan.
- `- Issue / PR:` a link, or "not created".
- `- Owner / run label:` who runs the task: the model, the effort and where it runs, or
  "unassigned".
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
- The same PR fills the task file's Evidence and Handoff sections and proposes its
  `State: done`.
- Run the project's checks before every push. A check that cannot run is named in the
  PR, never counted as a pass.
- A developer takes the recommended default on a small question and marks it in the
  PR as "default taken, owner may overrule". It stops for a scope change, a privacy
  risk or anything outward-facing.
- No agent co-author line, no "generated with" footer and no link to an agent's session
  in any commit, PR or comment. After writing a PR or a comment, read it back and remove
  any such line a platform added.

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
| `events/pr-<n>` | a pull request watcher | `{number, title, url, state: open\|ready\|merged\|closed, updated}` |
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

1. Run the `refresh` skill with `--all`. It writes `index.html` and
   `state.json` to a folder in your scratchpad and prints the publish parameters.
2. **First publish**, with the Artifact tool: `file_path` the printed `index.html`,
   `files` `{"state.json": ...}`, `capabilities` `{"db": {}, "user": {}, "sample": {}}`
   and `icon` `dashboard`. The first publish needs all three: `db` holds the store,
   `sample` runs the Review tab's assistant, and `user` is declared with them.
3. Put the returned link in `foreman.json` as `control_room_url` and commit it.
4. Write the open decision cards into the store as `questions/<id>`, each built with
   `control_room.py card` as the `inputs` skill says.
5. **Every later publish:** run `refresh` and publish what it prints, with `url` set
   and without `capabilities`. The artifact keeps the ones it has.

### Several coordinators, one page

Each coordinator works from its own branch, so a state file made from one checkout
does not see another coordinator's unmerged changes. So a publish is a merge, not a
replacement. Each track's entries in `state.json` (its plan, its tasks, its findings
rows and its plain-words lines) are that track's manifest. Every refresh first saves
the published `state.json`, then:

- `refresh <slug> ...` (a track coordinator) takes the named tracks from the checkout
  and keeps every other track as published.
- `refresh` with no track (the program session, after a merge) owns none: it keeps
  every track as published and takes only the pull requests, the records and the lanes
  from the checkout.
- `refresh --all` takes every track from the checkout. It is only for the first
  publish, and for recovering a published state that is broken.

A track only in the checkout is added, since it replaces nothing. The refresh refuses a
saved state that is not a `control-room-state/v1` file with tracks, and a track name
with no folder under `docs/tracks/`.

Records (`docs/inputs/`) and lanes (`foreman.json`) are written by the program session
on `main`. So a coordinator merges `origin/main` into its branch before it refreshes.
When two sessions publish at the same moment, the artifact service refuses the later
publish as stale; that session saves the published state again and repeats.

### Privacy

`state.json` carries repository text and aggregates only. Review items are private:
they go into `review.json`, published beside the page and never committed. The page
sends an item's opening turns to the in-page assistant only when the owner asks for a
suggestion.

## Hooks

`hooks/hooks.json` wires the rules above so that they run on their own. A hook that
blocks tells the agent what is missing; the agent fixes it and tries again. Outside a
project with a `foreman.json`, only the store check and the two session-link guards run.

| Hook | When | What it does | How to satisfy it |
| --- | --- | --- | --- |
| `store_shape.py` | before an ArtifactData write | Blocks a `set`, `update` or `batch` write to `questions`, `answers`, `labels` or `events` that does not match `scripts/store-schema.json`, and names the wrong or missing fields. An `update` may leave fields out. | Build the document with `control_room.py card` or `event` and write what it prints. |
| `ready_gate.py` | before `gh pr ready`, `gh pr create` without `--draft`, or a GitHub MCP create or update of a pull request with draft false | Blocks the ready mark unless the checks passed on the head and the branch's task file says `State: done` or `review`. | Commit, run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh"`, and propose `done` in the task file. Or open the pull request as a draft. |
| `refresh_after_pr.py` | after `gh pr create\|ready\|edit\|merge\|close` or a GitHub MCP pull request write | Runs the control room refresh (owning the `tracks` this branch changes) and tells the agent what to publish. After a merge it also prints the pull request event to write, and runs `scripts/rebase-open-prs.sh`. | Nothing to satisfy. Publish what it prints; send each conflict it lists to that pull request's developer. |
| `branch_name.py` | at session start, and before `git commit` or `git push` | Warns at start, then blocks a commit or push on a branch with a harness prefix (`claude/`, `codex/`, `deepseek/`, or one in `branch_prefixes`). | Rename with the `git branch -m` command it prints. |
| `task_shape.py` | before `git commit` | Blocks a commit whose staged task file lacks `State`, `Track`, `Issue / PR`, `Branch` or `Updated`, or has an unknown state word; or whose staged plan lacks `Coordinator`, `Done when` or `Budget`. `docs/tracks/_templates/` is skipped. | Add the line it names. |
| `plain_language.py` | before a `gh` or GitHub MCP write of a pull request, issue or comment body | Warns, never blocks, on a `jargon` word or a sentence over 35 words. | Rewrite the words or the sentence it prints. |
| `session-link-gh.sh`, `session-link-mcp.sh` | before a `gh` write, and before a GitHub MCP write | Blocks text that carries a link to an agent session, a `Co-authored-by:` line for an agent, or a "Generated with" footer for one. | Remove it and send again. |

`scripts/check.sh` runs the `checks` command at the checkout's root. It refuses to run
with uncommitted changes to tracked files. When the checks pass, it leaves a marker for
the head commit at `<git dir>/foreman/checks/<commit>`. A new commit needs a new run.

The ready gate reads the checkout's head and the task file as committed there. The task
file check looks only at `docs/tracks/*/tasks/*.md` files whose `- Branch:` names the
current branch; a branch no task file names is not checked. The task shape check sees
what is staged when `git commit` starts, so files a `git commit -a` would add are not
checked.

## Layout and tests

```text
.claude-plugin/   plugin.json, marketplace.json
skills/           the six skills
agents/           developer, reviewer, scribe
scripts/          control_room.py, store-schema.json, control-room/ (the page), control-room-refresh.sh, open-prs.sh, rebase-open-prs.sh, check.sh
templates/        plan, task, record, sample review spec, program, sdlc
hooks/            hooks.json and the hook scripts
tests/            the generator's, the page's and the hooks' tests on invented fixtures
```

Run `python3 -m pytest` from the repository's root. The tests use only invented
fixtures: a made-up recipe app called Pantry Notes. When `claude` is installed, a test
also runs `claude plugin validate .`.
