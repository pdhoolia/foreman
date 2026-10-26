"""The hooks in hooks/, each run as Claude Code runs it: one JSON payload on stdin, then the
exit code (2 blocks the call, its stderr is the reason) and any context printed on stdout.

Every payload, link and project here is invented (Pantry Notes, a made-up recipe app). The
ready gate, the refresh and the shape checks run in a scratch git repository; `gh` is a
stub, so no test reaches GitHub.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'hooks'
CHECK = ROOT / 'scripts/check.sh'

FOREMAN = {'title': 'Pantry Notes Control Room', 'checks': 'scripts/checks.sh', 'jargon': ['upsert', 'idempotent'],
           'branch_prefixes': ['bot'], 'tracks': [{'slug': 'shelves', 'lanes': [{'key': 'S', 'name': 'shelves'}]}]}

PLAN = """# Shelves

- State: active
- Coordinator: the shelves track session
- Done when: a cook can sort the pantry by shelf
- Budget: one developer session
- Updated: 2026-03-01

## Tasks and dependencies

| ID / task file | Deliverable | Depends on | Owned paths/interfaces | Assigned branch |
| --- | --- | --- | --- | --- |
| [S01: shelf model](tasks/S01-shelf-model.md) | shelves | this plan open | `app/shelf.py` | `alice/shelf-model` |
"""

TASK = """# S01 — Shelf model

- State: {state}
- Track: [shelves](../plan.md)
- Issue / PR: not created
- Owner / run label: unassigned
- Branch: `alice/shelf-model`
- Updated: 2026-03-01

## Handoff and memory

- Blocker: none.
"""

SESSION = 'https://claude.ai/code/session_pantry42'
CODEX = 'https://chatgpt.com/codex/tasks/pantry-7'


def env(extra_path=None):
    e = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    e.update({'GIT_AUTHOR_NAME': 'Alice', 'GIT_AUTHOR_EMAIL': '7+alice@users.noreply.github.com',
              'GIT_COMMITTER_NAME': 'Alice', 'GIT_COMMITTER_EMAIL': '7+alice@users.noreply.github.com'})
    if extra_path:
        e['PATH'] = f'{extra_path}{os.pathsep}{e["PATH"]}'
    return e


def hook(name, payload, cwd='.', path=None):
    run = ['bash'] if name.endswith('.sh') else [sys.executable]
    r = subprocess.run([*run, str(HOOKS / name)], input=json.dumps(payload), cwd=cwd, env=env(path),
                       capture_output=True, text=True, timeout=120)
    return r


def context_of(r):
    return json.loads(r.stdout)['hookSpecificOutput']['additionalContext'] if r.stdout.strip() else ''


def bash(command, cwd='.'):
    return {'hook_event_name': 'PreToolUse', 'cwd': str(cwd), 'tool_name': 'Bash', 'tool_input': {'command': command}}


class ScratchRepo(unittest.TestCase):
    """A Pantry Notes checkout on branch alice/shelf-model, with a bare origin whose main is the first commit."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.repo = self.d / 'pantry'
        self.write({'foreman.json': json.dumps(FOREMAN), 'docs/tracks/shelves/plan.md': PLAN,
                    'scripts/checks.sh': 'test ! -f fail-checks\n'})
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', '7+alice@users.noreply.github.com')
        self.commit('Start the pantry')
        self.git('init', '-q', '--bare', str(self.d / 'origin.git'), cwd=self.d)
        self.git('remote', 'add', 'origin', str(self.d / 'origin.git'))
        self.git('push', '-q', 'origin', 'main')
        self.git('checkout', '-q', '-b', 'alice/shelf-model')
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='active')})
        self.commit('Dispatch the shelf model')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, cwd=None):
        r = subprocess.run(['git', *args], cwd=cwd or self.repo, env=env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def write(self, files):
        for path, text in files.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text, encoding='utf-8')

    def commit(self, message):
        self.git('add', '-A')
        self.git('-c', 'commit.gpgsign=false', 'commit', '-q', '-m', message)

    def check(self):
        return subprocess.run(['bash', str(CHECK)], cwd=self.repo, env=env(), capture_output=True, text=True)

    def push(self):
        self.git('push', '-q', '-u', 'origin', 'HEAD')

    def gh_stub(self):
        """A gh that answers a pull request read with self.d/pr-head ("<sha> <branch>"), lists no open
        pull requests, and fails every call while self.d/gh-fails exists."""
        self.bin = self.d / 'bin'
        self.bin.mkdir(exist_ok=True)
        (self.bin / 'gh').write_text(f'#!/bin/sh\n[ -f "{self.d}/gh-fails" ] && {{ echo "HTTP 403" >&2; exit 1; }}\n'
                                     f'case "$*" in *pulls/[0-9]*) cat "{self.d}/pr-head";; esac\n', encoding='utf-8')
        (self.bin / 'gh').chmod(0o755)

    def pr_head(self, branch='alice/shelf-model'):
        """Point the stub's pull request at the current tip of `branch`."""
        (self.d / 'pr-head').write_text(f"{self.git('rev-parse', branch)} {branch}\n", encoding='utf-8')


class StoreShapeTests(unittest.TestCase):
    def store(self, **tool_input):
        return hook('store_shape.py', {'hook_event_name': 'PreToolUse', 'tool_name': 'ArtifactData',
                                       'tool_input': {'url': 'https://example.com/room', **tool_input}})

    def test_denies_the_hand_typed_event_and_passes_the_documented_one(self):
        r = self.store(action='set', collection='events', doc_id='pr-7', data={'number': 7, 'kind': 'merged', 'at': '2026-03-01T10:00:00Z'})
        self.assertEqual(r.returncode, 2)
        for field in ("unknown field 'kind'", "unknown field 'at'", "missing field 'state'", "missing field 'updated'"):
            self.assertIn(field, r.stderr)
        r = self.store(action='set', collection='events', doc_id='pr-7',
                       data={'number': 7, 'state': 'merged', 'updated': '2026-03-01T10:00:00Z', 'url': 'https://example.com/pull/7'})
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_batch_checks_every_entry(self):
        good = {'op': 'set', 'collection': 'answers', 'doc_id': 'shelf-order', 'data': {'choice': 'by-aisle', 'updated': '2026-03-01T10:00:00Z'}}
        bad = {'op': 'set', 'collection': 'labels', 'doc_id': 'item-3', 'data': {'goal': 'bake', 'when': 'today'}}
        self.assertEqual(self.store(action='batch', writes=[good]).returncode, 0)
        r = self.store(action='batch', writes=[good, bad])
        self.assertEqual(r.returncode, 2)
        self.assertIn('labels/item-3', r.stderr)
        self.assertNotIn('answers/shelf-order', r.stderr)

    def test_update_may_leave_fields_out_but_not_add_unknown_ones(self):
        self.assertEqual(self.store(action='update', collection='answers', doc_id='shelf-order', data={'note': 'ask again'}).returncode, 0)
        r = self.store(action='update', collection='answers', doc_id='shelf-order', data={'chosen': 'by-aisle'})
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown field 'chosen'", r.stderr)
        self.assertNotIn('missing field', r.stderr)

    def test_a_document_in_a_file_is_checked(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'q.json').write_text(json.dumps({'title': 'Shelf order?'}), encoding='utf-8')
            r = hook('store_shape.py', {'cwd': d, 'tool_name': 'ArtifactData',
                                        'tool_input': {'action': 'set', 'collection': 'questions', 'doc_id': 'shelf-order', 'file_path': 'q.json'}})
            self.assertEqual(r.returncode, 2)
            self.assertIn("missing field 'options'", r.stderr)

    def test_update_may_not_delete_a_required_field(self):
        r = self.store(action='update', collection='events', doc_id='pr-3', data={'state': {'__delete__': True}})
        self.assertEqual(r.returncode, 2)
        self.assertIn("deletes required field 'state'", r.stderr)
        self.assertEqual(self.store(action='update', collection='events', doc_id='pr-3', data={'title': {'__delete__': True}}).returncode, 0)

    def test_update_of_recommended_alone_is_checked_against_its_own_options_only(self):
        self.assertEqual(self.store(action='update', collection='questions', doc_id='shelf-order', data={'recommended': 'by-aisle'}).returncode, 0)
        r = self.store(action='update', collection='questions', doc_id='shelf-order',
                       data={'recommended': 'by-colour', 'options': [{'id': 'by-aisle', 'label': 'By aisle'}]})
        self.assertEqual(r.returncode, 2)
        self.assertIn("field 'recommended' must be option-id", r.stderr)

    def test_str_replace_only_on_plain_text_fields(self):
        edit = {'action': 'str_replace', 'old_str': 'a', 'new_str': 'b'}
        self.assertEqual(self.store(**edit, collection='questions', doc_id='shelf-order', field='body').returncode, 0)
        for collection, doc_id, field in (('events', 'pr-3', 'state'), ('answers', 'shelf-order', 'updated'), ('labels', 'item-3', 'colour')):
            with self.subTest(field=field):
                r = self.store(**edit, collection=collection, doc_id=doc_id, field=field)
                self.assertEqual(r.returncode, 2)
                self.assertIn('str_replace may only change a plain text field', r.stderr)

    def test_a_batch_without_a_list_of_writes_is_denied(self):
        r = self.store(action='batch', writes={'op': 'set'})
        self.assertEqual(r.returncode, 2)
        self.assertIn('must be a list', r.stderr)

    def test_a_crash_denies_instead_of_letting_the_write_through(self):
        r = hook('store_shape.py', {'tool_name': 'ArtifactData', 'tool_input': 'not an object'})
        self.assertEqual(r.returncode, 2)
        self.assertIn('hook failed (AttributeError', r.stderr)

    def test_reads_deletes_and_other_collections_pass(self):
        self.assertEqual(self.store(action='get', collection='events', doc_id='pr-7').returncode, 0)
        self.assertEqual(self.store(action='delete', collection='events', doc_id='pr-7').returncode, 0)
        self.assertEqual(self.store(action='set', collection='notes', doc_id='n1', data={'anything': 1}).returncode, 0)


class ReadyGateTests(ScratchRepo):
    def setUp(self):
        super().setUp()
        self.gh_stub()
        self.push()
        self.pr_head()

    def ready(self, payload=None):
        return hook('ready_gate.py', payload or bash('gh pr ready 12', self.repo), path=self.bin)

    def test_denies_without_marker_or_completion_and_passes_with_both(self):
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('the checks have not passed', r.stderr)
        self.assertIn("docs/tracks/shelves/tasks/S01-shelf-model.md has State 'active'", r.stderr)
        self.assertEqual(self.check().returncode, 0)
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertNotIn('the checks have not passed', r.stderr)
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')
        self.push()
        self.pr_head()
        r = self.ready()  # the marker was for the previous head
        self.assertEqual(r.returncode, 2)
        self.assertIn('the checks have not passed', r.stderr)
        self.assertNotIn('has State', r.stderr)
        self.assertEqual(self.check().returncode, 0)
        self.assertEqual(self.ready().returncode, 0)

    def test_checks_the_pull_request_being_marked_not_the_checkout(self):
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')
        self.assertEqual(self.check().returncode, 0)
        self.push()
        self.pr_head()
        self.git('checkout', '-q', 'main')  # main has no marker and no task file
        self.assertEqual(self.ready().returncode, 0)
        mcp = {'cwd': str(self.repo), 'tool_name': 'mcp__github__update_pull_request', 'tool_input': {'pullNumber': 12, 'draft': False}}
        self.assertEqual(self.ready(mcp).returncode, 0)
        create = {'cwd': str(self.repo), 'tool_name': 'mcp__github__create_pull_request',
                  'tool_input': {'head': 'alice/shelf-model', 'base': 'main', 'title': 'Add shelves'}}
        self.assertEqual(self.ready(create).returncode, 0)
        (self.d / 'pr-head').write_text(f"{self.git('rev-parse', 'main')} alice/shelf-model\n", encoding='utf-8')
        r = self.ready()  # GitHub's head is another commit: its marker is missing
        self.assertEqual(r.returncode, 2)
        self.assertIn('the checks have not passed', r.stderr)

    def test_a_head_it_cannot_find_denies(self):
        (self.d / 'gh-fails').write_text('', encoding='utf-8')
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('cannot read pull request #12', r.stderr)
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')  # not pushed
        r = self.ready(bash('gh pr create --title "Add shelves" --body "Shelves."', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn('is not pushed', r.stderr)
        self.assertEqual(self.check().returncode, 0)
        self.push()
        self.assertEqual(self.ready(bash('gh pr create --title "Add shelves" --body "Shelves."', self.repo)).returncode, 0)

    def test_check_script_marks_only_a_clean_passing_head(self):
        self.write({'fail-checks': ''})
        self.git('add', 'fail-checks')
        self.assertNotEqual(self.check().returncode, 0)  # tracked change not committed
        self.commit('Make the checks fail')
        self.assertNotEqual(self.check().returncode, 0)
        self.push()
        self.pr_head()
        self.assertEqual(self.ready().returncode, 2)

    def test_which_calls_mark_ready(self):
        cases = [(bash('gh pr create --title "Add shelves" --body "Shelves."', self.repo), 2),
                 (bash('gh pr create --draft --title "Add shelves" --body "Shelves."', self.repo), 0),
                 (bash('gh pr ready 12 --undo', self.repo), 0),
                 (bash('gh pr view 12', self.repo), 0),
                 ({'cwd': str(self.repo), 'tool_name': 'mcp__github__create_pull_request', 'tool_input': {'title': 'Add shelves'}}, 2),
                 ({'cwd': str(self.repo), 'tool_name': 'mcp__github__create_pull_request', 'tool_input': {'draft': True}}, 0),
                 ({'cwd': str(self.repo), 'tool_name': 'mcp__github__update_pull_request', 'tool_input': {'pullNumber': 12, 'draft': False}}, 2),
                 ({'cwd': str(self.repo), 'tool_name': 'mcp__github__update_pull_request', 'tool_input': {'pullNumber': 12, 'title': 'x'}}, 0)]
        for payload, code in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.ready(payload).returncode, code)

    def test_without_the_checks_key_only_the_task_file_counts(self):
        self.write({'foreman.json': json.dumps({'title': 'Pantry Notes Control Room'}),
                    'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='review')})
        self.commit('Propose the shelf model for review')
        self.push()
        self.pr_head()
        self.assertEqual(self.ready().returncode, 0)
        (self.repo / 'foreman.json').unlink()
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='active')})
        self.commit('Leave foreman')
        self.assertEqual(self.ready().returncode, 0)  # not a foreman project: no gate

    def test_an_unreadable_foreman_json_denies(self):
        self.write({'foreman.json': '{"checks": '})
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('foreman.json cannot be read', r.stderr)


class RefreshAfterPrTests(ScratchRepo):
    def setUp(self):
        super().setUp()
        self.gh_stub()
        self.out = self.repo / '.git/foreman/control-room'
        subprocess.run(['bash', str(ROOT / 'scripts/control-room-refresh.sh'), str(self.out), '--all'],
                       cwd=self.repo, env=env(self.bin), check=True, capture_output=True)
        (self.out / 'state.json').rename(self.out / 'live-state.json')

    def post(self, payload, response=None):
        payload = dict(payload, hook_event_name='PostToolUse', tool_response=response or {})
        r = hook('refresh_after_pr.py', payload, path=self.bin)
        self.assertEqual(r.returncode, 0, r.stderr)
        return context_of(r)

    def test_refreshes_own_tracks_into_the_git_directory(self):
        text = self.post(bash('gh pr create --draft --title "Add shelves" --body "Shelves."', self.repo))
        self.assertIn('Control room refresh (tracks shelves)', text)
        self.assertIn(f'file_path:    {self.out}/index.html', text)
        self.assertNotIn('Merged', text)
        state = json.loads((self.out / 'state.json').read_text(encoding='utf-8'))
        self.assertEqual([t['state'] for t in state['tasks'] if t['id'] == 'S01'], ['active'])

    def test_main_and_uncommitted_edits_own_no_track(self):
        self.git('checkout', '-q', 'main')
        self.assertIn('(no own track)', self.post(bash('gh pr edit 12 --title "Shelves"', self.repo)))
        self.git('checkout', '-q', '-b', 'alice/typo')
        self.write({'docs/tracks/shelves/plan.md': PLAN + '\nA note.\n'})  # not committed
        self.assertIn('(no own track)', self.post(bash('gh pr edit 12 --title "Shelves"', self.repo)))

    def test_a_confirmed_merge_prints_the_event_and_rebases_open_prs(self):
        text = self.post({'cwd': str(self.repo), 'tool_name': 'mcp__github__merge_pull_request', 'tool_input': {'pullNumber': 12}},
                         {'merged': True, 'message': 'Pull Request successfully merged'})
        event = json.loads(text.split('(set):\n\n')[1].split('\n\n')[0])
        self.assertEqual((event['collection'], event['doc_id'], event['data']['state']), ('events', 'pr-12', 'merged'))
        self.assertIn('on main: 0, rebased: 0, conflicts: 0', text)
        text = self.post(bash('gh pr merge 12 --squash', self.repo), {'stdout': '', 'stderr': '✓ Squashed and merged pull request #12 (Add shelves)'})
        self.assertIn('"doc_id": "pr-12"', text)

    def test_an_auto_merge_or_an_unconfirmed_one_is_not_a_merge(self):
        text = self.post(bash('gh pr merge 12 --auto --squash', self.repo),
                         {'stdout': '', 'stderr': '✓ Pull request #12 will be automatically merged via squash when all requirements are met'})
        self.assertIn('Control room refresh', text)
        self.assertNotIn('Merged', text)
        self.assertNotIn('rebased:', text)
        text = self.post(bash('gh pr merge 12', self.repo), {'stdout': '', 'stderr': 'X Pull request #12 is not mergeable'})
        self.assertIn('not confirmed', text)
        self.assertNotIn('rebased:', text)

    def test_other_commands_and_other_projects_are_left_alone(self):
        self.assertEqual(self.post(bash('gh pr view 12', self.repo)), '')
        (self.repo / 'foreman.json').unlink()
        self.assertEqual(self.post(bash('gh pr merge 12', self.repo)), '')


class BranchNameTests(ScratchRepo):
    def test_denies_commit_and_push_on_a_harness_branch(self):
        self.git('branch', '-m', 'claude/shelf-model')
        for cmd in ('git commit -m "Add shelves"', 'git -C . push -u origin HEAD', 'make && git commit -am x'):
            with self.subTest(cmd=cmd):
                r = hook('branch_name.py', bash(cmd, self.repo))
                self.assertEqual(r.returncode, 2)
                self.assertIn('git branch -m alice/shelf-model', r.stderr)
        self.assertEqual(hook('branch_name.py', bash('git log --grep push', self.repo)).returncode, 0)
        r = hook('branch_name.py', {'hook_event_name': 'SessionStart', 'cwd': str(self.repo), 'source': 'startup'})
        self.assertIn('git branch -m alice/shelf-model', context_of(r))

    def test_checks_the_git_dash_c_directory(self):
        self.git('branch', '-m', 'claude/shelf-model')
        r = hook('branch_name.py', bash('git -C pantry commit -m x', self.d))  # the session's folder is not a repository
        self.assertEqual(r.returncode, 2)
        self.assertIn("'claude/shelf-model'", r.stderr)

    def test_push_destinations_and_the_built_in_prefixes(self):
        for cmd in ('git push origin HEAD:claude/x', 'git push -u origin +alice/shelf-model:refs/heads/codex/y'):
            with self.subTest(cmd=cmd):
                r = hook('branch_name.py', bash(cmd, self.repo))
                self.assertEqual(r.returncode, 2)
                self.assertIn('a harness prefix', r.stderr)
        for cmd in ('git push origin HEAD:alice/x', 'git push -u origin alice/shelf-model', 'git push'):
            with self.subTest(cmd=cmd):
                self.assertEqual(hook('branch_name.py', bash(cmd, self.repo)).returncode, 0)
        for prefix in ('cursor', 'copilot'):
            self.git('branch', '-m', f'{prefix}/shelf-model')
            self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 2)

    def test_an_unreadable_foreman_json_warns_instead_of_going_quiet(self):
        self.write({'foreman.json': '{"tracks": ['})
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertEqual(r.returncode, 0)
        self.assertIn('foreman.json cannot be read', context_of(r))

    def test_listed_prefixes_and_a_good_branch(self):
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 0)
        self.git('branch', '-m', 'bot/shelf-model')
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 2)
        (self.repo / 'foreman.json').unlink()
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 0)


class TaskShapeTests(ScratchRepo):
    def staged(self, path, text):
        self.write({path: text})
        self.git('add', path)
        return hook('task_shape.py', bash('git commit -m "Update the shelves"', self.repo))

    def test_task_file_lines_and_state(self):
        path = 'docs/tracks/shelves/tasks/S01-shelf-model.md'
        r = self.staged(path, TASK.format(state='active').replace('- Updated: 2026-03-01\n', ''))
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"{path}: no '- Updated:' line", r.stderr)
        r = self.staged(path, TASK.format(state='finished'))
        self.assertEqual(r.returncode, 2)
        self.assertIn("state 'finished' is not one of", r.stderr)
        self.assertEqual(self.staged(path, TASK.format(state='review')).returncode, 0)

    def test_commit_all_and_named_paths_are_checked_from_the_working_tree(self):
        path = 'docs/tracks/shelves/tasks/S01-shelf-model.md'
        self.write({path: TASK.format(state='active').replace('- Updated: 2026-03-01\n', '')})  # not staged
        self.assertEqual(hook('task_shape.py', bash('git commit -m "Update the shelves"', self.repo)).returncode, 0)
        for cmd in ('git commit -am "Update the shelves"', 'git commit --all -m x', f'git commit -m x {path}',
                    'git commit -m x -- docs/tracks/shelves/tasks', 'git -C pantry commit -am x'):
            with self.subTest(cmd=cmd):
                r = hook('task_shape.py', bash(cmd, self.d if '-C' in cmd else self.repo))
                self.assertEqual(r.returncode, 2)
                self.assertIn(f"{path}: no '- Updated:' line", r.stderr)
        self.assertEqual(hook('task_shape.py', bash('git commit -m x docs/tracks/shelves/plan.md', self.repo)).returncode, 0)

    def test_plan_head_lines(self):
        r = self.staged('docs/tracks/shelves/plan.md', PLAN.replace('- Budget: one developer session\n', ''))
        self.assertEqual(r.returncode, 2)
        self.assertIn("docs/tracks/shelves/plan.md: no '- Budget:' line", r.stderr)
        self.git('reset', '-q')
        self.assertEqual(self.staged('docs/tracks/_templates/plan.md', '# Template\n').returncode, 0)
        self.assertEqual(self.staged('docs/tracks/shelves/plan.md', PLAN).returncode, 0)
        self.assertEqual(hook('task_shape.py', bash('git status', self.repo)).returncode, 0)


class PlainLanguageTests(ScratchRepo):
    LONG = 'This sentence goes on ' + 'and on ' * 20 + 'until it ends.'

    def test_warns_on_jargon_and_long_sentences_without_blocking(self):
        r = hook('plain_language.py', bash(f'gh pr create --title "Add shelves" --body "We upsert each shelf. {self.LONG}"', self.repo))
        self.assertEqual(r.returncode, 0)
        text = context_of(r)
        self.assertIn("jargon: 'upsert'", text)
        self.assertIn('47 words', text)
        r = hook('plain_language.py', {'cwd': str(self.repo), 'tool_name': 'mcp__github__add_issue_comment',
                                       'tool_input': {'issue_number': 3, 'body': 'The step is idempotent.'}})
        self.assertIn("jargon: 'idempotent'", context_of(r))

    def test_a_crash_is_reported_as_context(self):
        r = hook('plain_language.py', {'cwd': str(self.repo), 'tool_name': 'Bash', 'tool_input': 'not an object'})
        self.assertEqual(r.returncode, 0)
        self.assertIn('hook failed (AttributeError', context_of(r))

    def test_plain_text_and_other_commands_pass_quietly(self):
        for payload in (bash('gh pr create --title "Add shelves" --body "Sort the pantry by shelf. It is short."', self.repo),
                        bash(f'echo "{self.LONG}"', self.repo),
                        bash('gh pr comment 3 --body "See `idempotent_upsert()` in app/upsert.py."', self.repo)):
            with self.subTest(payload=payload):
                r = hook('plain_language.py', payload)
                self.assertEqual((r.returncode, r.stdout), (0, ''))


class SessionLinkTests(unittest.TestCase):
    """The cases of the guards this plugin took over, with invented links."""

    FOOTERS = [SESSION, CODEX, 'Co-Authored-By: Claude <noreply@example.com>', 'Generated with Codex',
               '🤖 Generated with [Claude Code](https://example.com)']

    def test_mcp_writes(self):
        for text in self.FOOTERS:
            with self.subTest(text=text):
                self.assertEqual(hook('session-link-mcp.sh', {'tool_input': {'body': f'Shelves.\n\n---\n{text}'}}).returncode, 2)
        self.assertEqual(hook('session-link-mcp.sh', {'tool_input': {'body': 'A useful change. Co-authored-by: Bob <bob@example.com>'}}).returncode, 0)

    def test_gh_writes_only(self):
        for text in self.FOOTERS:
            with self.subTest(text=text):
                self.assertEqual(hook('session-link-gh.sh', bash(f"gh pr create --body 'Shelves. {text}'")).returncode, 2)
                self.assertEqual(hook('session-link-gh.sh', bash(f"gh api repos/o/r/issues/3/comments -f body='{text}'")).returncode, 2)
                self.assertEqual(hook('session-link-gh.sh', bash(f"printf '%s' '{text}'")).returncode, 0)
        self.assertEqual(hook('session-link-gh.sh', bash("gh pr create --body 'A useful change'")).returncode, 0)


    def test_a_missing_patterns_file_denies(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('session-link-gh.sh', 'session-link-mcp.sh'):
                shutil.copy(HOOKS / name, d)
            r = subprocess.run(['bash', f'{d}/session-link-gh.sh'], input=json.dumps(bash("gh pr create --body 'Shelves.'")),
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertIn('cannot read', r.stderr)
            r = subprocess.run(['bash', f'{d}/session-link-mcp.sh'], input='{"tool_input": {"body": "Shelves."}}', capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)


class WiringTests(unittest.TestCase):
    def test_every_hook_script_is_wired(self):
        wired = json.dumps(json.loads((HOOKS / 'hooks.json').read_text(encoding='utf-8')))
        scripts = {p.name for p in HOOKS.iterdir() if p.suffix in ('.py', '.sh') and p.name != 'common.py'}
        self.assertEqual({s for s in scripts if s in wired}, scripts)
        self.assertEqual(len(scripts), 8)


if __name__ == '__main__':
    unittest.main()
