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

### On your machine

Add this repository as a plugin marketplace, then install the plugin. From a shell:

```bash
claude plugin marketplace add pdhoolia/foreman
claude plugin install foreman@foreman
```

Inside a Claude Code session, the same two steps are
`/plugin marketplace add pdhoolia/foreman` and `/plugin install foreman@foreman`.
From a local checkout instead: `claude plugin marketplace add ./path/to/foreman`, then
the same install line. To try it for one session without installing:
`claude --plugin-dir ./path/to/foreman`.

The skills are then named `/foreman:<skill>`, for example `/foreman:pm-start`.

### For the team

Commit these two keys in the project's `.claude/settings.json`. Claude Code then offers
the plugin to everyone who opens the project and trusts the folder. `ref` pins the
marketplace to a branch or tag; the plugin has no release tag yet, so it is `main`.

```json
{
  "extraKnownMarketplaces": {
    "foreman": {"source": {"source": "github", "repo": "pdhoolia/foreman", "ref": "main"}}
  },
  "enabledPlugins": {"foreman@foreman": true}
}
```

### In a cloud session

A cloud session (Claude Code on the web) does not load a plugin that only the
repository's settings enable. Install it at user scope in the cloud environment's setup
script, which runs before the session starts. A setup script that fails stops the
session from starting, so each line ends with `|| true`:

```bash
claude plugin marketplace add pdhoolia/foreman || true
claude plugin install foreman@foreman --scope user || true
```

### Where the installed plugin lives

Inside a session, hooks and skills name the plugin's folder `${CLAUDE_PLUGIN_ROOT}`.
Outside a session that variable is not set: the installed copy is at
`~/.claude/plugins/cache/foreman/foreman/<version>/` (`<version>` is the `version` in
`.claude-plugin/plugin.json`, for example `0.1.0`). The steps below call that folder
`<plugin>`.

## Set up a project

1. Add `foreman.json` at the project's root (shape below).
2. Copy the templates you need from `<plugin>/templates/`: `program.md` and `sdlc.md` to
   `docs/`, `plan.md` and `task.md` to `docs/tracks/_templates/`, `record.md` to
   `docs/inputs/_template/`.
3. Write the first track plan at `docs/tracks/<slug>/plan.md`.
4. Make the first control room files. From the project's root, inside or outside a
   session:

   ```bash
   bash <plugin>/scripts/control-room-refresh.sh \
     "$(git rev-parse --path-format=absolute --git-common-dir)/foreman/control-room" --all
   ```

   `--all` is for the first publish only. Every later refresh merges into the published
   page, so it first needs the published `state.json` saved as `live-state.json` in that
   folder; without it the script stops with "save the published state.json ... first".
   Saving it and publishing both use Claude's Artifact tool, so they happen inside a
   session (the `refresh` skill does both). See "The control room".

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
  "commit_authors": ["Alice <12345+alice@users.noreply.github.com>"],
  "tracks": [
    {"slug": "bench", "lanes": [
      {"key": "A", "name": "search bench", "work": "score search ideas offline",
       "where": "local", "model": "the model and effort this lane runs on"}
    ]}
  ],
  "lanes": [
    {"key": "PM", "name": "program", "work": "ties the tracks together"}
  ]
}
```

- `title`: the page's name. Without it: "<repository name> Control Room".
- `control_room_url`: the published page. The refresh prints it as the publish target.
- `tracks`: the lanes of each track. A lane's key is a task ID prefix: task `A01` goes
  to lane `A`, `CS01` to lane `CS` or else `C`. A track with no lanes listed shows as
  one row of its own.
- `lanes`: lanes outside any track, for example the program session's. Same shape as a
  track's lanes; the page shows them with no plan link.
- `checks`: the project's checks, a script path (run with bash) or a shell command,
  for example `"scripts/local-checks.sh"`. `scripts/check.sh` runs it for the ready
  gate. Without it, the ready gate checks only the task file.
- `jargon`: words the plain-language hook warns about, for example `["upsert"]`.
  Without it, the hook warns only on long sentences.
- `branch_prefixes`: more harness prefixes to refuse, besides `claude/`, `codex/`,
  `deepseek/`, `cursor/` and `copilot/`, for example `["bot"]`. The commit author hook
  refuses the same names as an author's name.
- `program`: the program session's brief, when it is not `docs/program.md`. A code span
  in that file that starts with "Coordinate the <slug> track" is the first prompt of each
  track coordinator, with `<slug>` filled in. Without one, the plugin's own line is used.
- `commit_authors`: who may author a commit, as `Name <email>` strings. With exactly one
  entry, every session sets it as the author at start. Without the key, only the agent
  names and domains are refused.

## Roles

| Role | Does | Never |
| --- | --- | --- |
| Owner | Sets priorities. Decides through the control room. Merges. Overrules any default. | |
| Track coordinator | Owns one track's `plan.md` and task files. Dispatches its tasks, reviews its PRs before the owner sees them, asks the owner through cards, refreshes the control room. | Edits another track's files or the program files. |
| Program session | Owns `docs/program.md` and `docs/sdlc.md`. Watches merges, brings open PRs back onto `main` after each merge, records answered rounds, settles conflicts between tracks. | Does task work. |
| Developer | Delivers one task in its own checkout and branch, in one PR that proposes the task `done`. | Changes paths its task file does not own. |
| Reviewer | Reads a PR against its task file and sends findings to the developer. Posts the review verdict as a PR comment. | Writes to the PR's branch. |
| Scribe | Writes records (decision rounds, handoffs, plain-words lines) from given facts. | Edits code. |

A coordinator holds no state outside the repository and the control room's store. Any
session can take its role over from the files.

**Every session has a name**: its intent, then its role. With several windows open, the
name says which session does what.

| Session | Name | Set by |
| --- | --- | --- |
| Program session | `program: <title> (PM)`, the `title` from `foreman.json` | `/rename` in the session (`pm-start`) |
| Track coordinator | `<slug> (PM)` | `claude --name` (`coordinators`) |
| Developer | `task <ID>: <short title> (developer)` | `claude --name`, or the Agent tool's description (`dispatch`) |
| Review pass in its own session | `review #<PR> (reviewer)` | `claude --name` |

**A track coordinator is its own Claude Code session**, never a subagent of the program
session or of another coordinator. A subagent acts as the session that started it. Its
review verdicts and ready marks then count as self-approval and are refused, every
finished PR falls back to the owner's click, its permission prompts go to the other
session, and the control room looks out of step with what that session says. The
`coordinators` skill starts each coordinator in a new terminal. When it cannot, it says
so and prints the prompt the owner pastes into a new session.

**No shortcut that changes who does what.** A session that cannot do a step as written
here says so and asks the owner. It does not swap in a shortcut that changes who does the
work, who reviews it, or where permission is asked. In the owner's words: "do not
automatically default to taking a shortcut which then has other side-effects".

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

- `- State:` `planned`, `active`, `blocked`, `review`, `done`, `accepted` or `dropped`.
  The first word counts. `accepted` is an older word for `done`.
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
- The author of every commit is the owner's identity, never an agent's. The committer
  may be the platform's signing identity (in a cloud session, `Claude
  <noreply@anthropic.com>`): that is what makes GitHub show the commit Verified, since
  the signing key is known under that account. A commit made through the GitHub MCP
  tools takes the signed-in account, so only a local `git commit` is guarded.
- One PR per task, against `main`, opened as a draft and marked ready only when the
  project's checks pass on its head, its task file proposes `done`, and the
  coordinator's review pass has posted its verdict for that head (a comment on the PR
  whose first line is `foreman review: ready <full head sha>`). A push after the review
  needs a new verdict. No session reviews its own PR. A coordinator's own PR (a plan or
  record change) is reviewed by the program session, and the program session's by a
  coordinator or the owner; the reviewer posts the verdict comment the same way. The
  body says the problem, what changes, how it was tested (every check that ran, and any that
  could not), and what is not done.
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
| `review <PR>` | the review pass, its verdict comment and the ready gate |
| `inputs ask \| review \| record` | ask the owner, read the answers back, record the round |
| `refresh [own track slugs]` | regenerate the control room's files and print the publish parameters |
| `coordinators [track slugs]` | start each active track's coordinator as its own session in a new terminal, or say why not and print the prompts to paste |

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
   `state.json` to `<git dir>/foreman/control-room/` and prints the publish parameters.
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
Claude Code's own `attribution` and `includeCoAuthoredBy` settings shape commit message
text, not git's author, so no hook reads them.

| Hook | When | What it does | How to satisfy it |
| --- | --- | --- | --- |
| `store_shape.py` | before an ArtifactData write | Blocks a `set`, `update` or `batch` write to `questions`, `answers`, `labels` or `events` that does not match `scripts/store-schema.json`, and names the wrong or missing fields. An `update` may leave fields out but not delete a required one; `str_replace` may change only a plain text field. | Build the document with `control_room.py card` or `event` and write what it prints. |
| `ready_gate.py` | before `gh pr ready`, `gh pr create` without `--draft`, or a GitHub MCP create or update of a pull request with draft false | Blocks the ready mark unless, for the pull request's head commit, the checks passed, its branch's task file says `State: done` or `review`, and a comment on the pull request carries the review verdict `foreman review: ready <full head sha>` as its first line. A new pull request has no comment yet, so it must be opened as a draft. | Commit and push, run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh"`, propose `done` in the task file, and ask the coordinator for the review pass. Or open the pull request as a draft. |
| `refresh_after_pr.py` | after `gh pr create\|ready\|edit\|merge\|close` or a GitHub MCP pull request write | Runs the control room refresh into `<git dir>/foreman/control-room/` (owning the `tracks` this branch's commits change; none on `main`) and tells the agent what to publish. After a merge GitHub confirms (`gh api .../pulls/<n> --jq .merged`; `--auto` only queues one), it also prints the pull request event to write, and runs `scripts/rebase-open-prs.sh`. It owns only tracks listed in `foreman.json`. A track listed nowhere there stays as published; refresh it by hand with the `refresh` skill. | Nothing to satisfy. Publish what it prints; send each conflict it lists to that pull request's developer. |
| `branch_name.py` | at session start, and before `git commit` or `git push` | Warns at start, then blocks a commit or push on a branch with a harness prefix (`claude/`, `codex/`, `deepseek/`, `cursor/`, `copilot/`, or one in `branch_prefixes`; in any case, so `Claude/` too), and a push to such a branch (`git push origin HEAD:claude/x`). Deleting such a branch (`git push origin --delete claude/x`) passes. | Rename with the `git branch -m` command it prints. It suggests your git handle in lower case, or `<your-git-handle>` when that handle is itself a harness name. |
| `commit_author.py` | at session start, and before `git commit` | At start, with exactly one entry in `commit_authors`, sets `user.name` and `user.email` in the checkout from it, and in a cloud session (`CLAUDE_CODE_REMOTE`) keeps the committer `Claude <noreply@anthropic.com>` through `CLAUDE_ENV_FILE`; with no entry or several, prints the `git config` commands instead. Before a commit, blocks when the author git will use (`git var GIT_AUTHOR_IDENT`, then `--author`) has a harness name (`claude`, `codex`, `deepseek`, `cursor`, `copilot`, or one in `branch_prefixes`) or an email at an agent maker's domain, or is not in `commit_authors` when that list exists. The committer is not checked. | Set the author with `git config user.name` and `user.email`, or add the author to `commit_authors`. |
| `task_shape.py` | before `git commit` | Blocks a commit whose task file lacks `State`, `Track`, `Issue / PR`, `Branch` or `Updated`, or has an unknown state word; or whose plan lacks `Coordinator`, `Done when` or `Budget`. It checks what the commit takes: the staged files, and with `-a` or named paths, the working tree. `docs/tracks/_templates/` is skipped, and so is every plan and task file of a track whose plan says `complete`, `accepted` or `dropped`. | Add the line it names. |
| `plain_language.py` | before a `gh` or GitHub MCP write of a pull request, issue or comment body | Warns, never blocks, on a `jargon` word or a sentence over 35 words. | Rewrite the words or the sentence it prints. |
| `session-link-gh.sh`, `session-link-mcp.sh` | before a `gh` write, and before a GitHub MCP write | Blocks text that carries a link to an agent session, a `Co-authored-by:` line for an agent, or a "Generated with" footer for one. Blocks every write when its patterns file is missing. | Remove it and send again. |

`scripts/check.sh` runs the `checks` command at the checkout's root. It refuses to run
with uncommitted changes to tracked files. When the checks pass, it leaves a marker for
the head commit at `<git dir>/foreman/checks/<commit>`. `<git dir>` is the git directory
all of the repository's worktrees share. A new commit needs a new run.

The ready gate asks GitHub for the commit being marked. For a pull request named by number
(`gh pr ready 12`, an MCP update), it reads the head with `gh api`. For one named by
branch (`gh pr ready`, `gh pr ready <branch>`), it reads the branch's head with
`git ls-remote` and finds the open pull request's number with `gh api`; when that branch
is checked out, the checkout's head must be the same commit. A repository named in the
call (`owner` and `repo` on an MCP write, `-R` on gh) is the one asked. It reads the task
file at that commit. The task file check looks only at
`docs/tracks/*/tasks/*.md` files whose `- Branch:` names the pull request's branch; a
branch no task file names is not checked. The verdict is read from the pull request's
issue comments (`gh api repos/{owner}/{repo}/issues/<n>/comments`); only a comment whose
first line is exactly `foreman review: ready <full head sha>` counts. A head it cannot
find, comments it cannot read, or a `foreman.json` it cannot read, blocks the ready mark.

A hook that crashes does not let the action through: a blocking hook blocks with the
error, and a warning hook prints it. Hook input that is not a JSON object counts as an
error. When `foreman.json` cannot be read, each hook that reads it says so instead of
going quiet; the ready gate blocks. A `jargon`, `branch_prefixes` or `commit_authors` that
is not a list of strings is ignored, with a warning.

## Layout and tests

```text
.claude-plugin/   plugin.json, marketplace.json
skills/           the seven skills
agents/           developer, reviewer, scribe
scripts/          control_room.py, store-schema.json, control-room/ (the page), control-room-refresh.sh, open-prs.sh, rebase-open-prs.sh, check.sh
templates/        plan, task, record, sample review spec, program, sdlc
hooks/            hooks.json and the hook scripts
tests/            the generator's, the page's and the hooks' tests on invented fixtures
```

Run `python3 -m pytest` from the repository's root. The tests use only invented
fixtures: a made-up recipe app called Pantry Notes. When `claude` is installed, a test
also runs `claude plugin validate .`.
