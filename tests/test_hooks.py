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
    e.update({'GIT_AUTHOR_NAME': 'alice', 'GIT_AUTHOR_EMAIL': 'alice@example.invalid',
              'GIT_COMMITTER_NAME': 'alice', 'GIT_COMMITTER_EMAIL': 'alice@example.invalid'})
    if extra_path:
        e['PATH'] = f'{extra_path}{os.pathsep}{e["PATH"]}'
    return e


def hook(name, payload, cwd='.', path=None, extra_env=None):
    """Run a hook script with `payload` as its stdin: JSON-encoded, unless it is already a string."""
    run = ['bash'] if name.endswith('.sh') else [sys.executable]
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run([*run, str(HOOKS / name)], input=stdin, cwd=cwd, env={**env(path), **(extra_env or {})},
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
        self.git('config', 'user.email', 'alice@example.invalid')
        self.git('config', 'user.name', 'alice')
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
        """A gh that logs each call to self.d/gh-calls and answers from files: a merged question with
        self.d/pr-merged (else false), a pull request search with self.d/pr-number, a pull request read
        with self.d/pr-head ("<sha> <branch>"), a pull request's comments (their first lines) with
        self.d/pr-comments. It lists no open pull requests, and fails every call while self.d/gh-fails
        exists."""
        self.bin = self.d / 'bin'
        self.bin.mkdir(exist_ok=True)
        d = self.d
        (self.bin / 'gh').write_text(f'#!/bin/sh\necho "$*" >> "{d}/gh-calls"\n'
                                     f'[ -f "{d}/gh-fails" ] && {{ echo "HTTP 403" >&2; exit 1; }}\n'
                                     f'case "$*" in\n'
                                     f'  *.merged*) cat "{d}/pr-merged" 2>/dev/null || echo false;;\n'
                                     f'  *"pulls?head="*) cat "{d}/pr-number" 2>/dev/null || true;;\n'
                                     f'  *pulls/[0-9]*) cat "{d}/pr-head";;\n'
                                     f'  *issues/[0-9]*/comments*) cat "{d}/pr-comments" 2>/dev/null || true;;\n'
                                     f'esac\n', encoding='utf-8')
        (self.bin / 'gh').chmod(0o755)

    def pr_head(self, branch='alice/shelf-model'):
        """Point the stub's pull request at the current tip of `branch`."""
        (self.d / 'pr-head').write_text(f"{self.git('rev-parse', branch)} {branch}\n", encoding='utf-8')

    def reviewed(self, rev='HEAD'):
        """The coordinator's verdict comment for `rev`, as the stub's comment list."""
        (self.d / 'pr-comments').write_text(f"Looks fine to me.\nforeman review: ready {self.git('rev-parse', rev)}\n", encoding='utf-8')


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

    def test_unreadable_input_denies(self):
        for name in ('store_shape.py', 'ready_gate.py', 'branch_name.py', 'task_shape.py', 'commit_author.py'):
            for stdin in ('[1]', 'null', 'not json'):
                with self.subTest(name=name, stdin=stdin):
                    r = hook(name, stdin)
                    self.assertEqual(r.returncode, 2)
                    self.assertIn('cannot read its input', r.stderr)

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
        r = self.ready()  # no review verdict yet
        self.assertEqual(r.returncode, 2)
        self.assertIn('pull request #12 has no review verdict for', r.stderr)
        self.assertIn(f"foreman review: ready {self.git('rev-parse', 'HEAD')}", r.stderr)
        self.reviewed('HEAD~1')  # a verdict for another commit does not count
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('has no review verdict for', r.stderr)
        self.reviewed()
        self.assertEqual(self.ready().returncode, 0)

    def test_the_verdict_is_the_first_line_of_a_comment(self):
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')
        self.push()
        self.pr_head()
        self.assertEqual(self.check().returncode, 0)
        sha = self.git('rev-parse', 'HEAD')
        for lines, code in ((f'foreman review: ready {sha}', 0), (f'foreman review: ready {sha[:12]}', 2),
                            (f'foreman review: not ready {sha}', 2), (f'a note\nforeman review: ready {sha}', 0)):
            with self.subTest(lines=lines):
                (self.d / 'pr-comments').write_text(lines + '\n', encoding='utf-8')
                self.assertEqual(self.ready().returncode, code)
        (self.d / 'gh-fails').write_text('', encoding='utf-8')
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('cannot read', r.stderr)

    def test_checks_the_pull_request_being_marked_not_the_checkout(self):
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')
        self.assertEqual(self.check().returncode, 0)
        self.push()
        self.pr_head()
        self.reviewed()
        self.git('checkout', '-q', 'main')  # main has no marker and no task file
        self.assertEqual(self.ready().returncode, 0)
        mcp = {'cwd': str(self.repo), 'tool_name': 'mcp__github__update_pull_request', 'tool_input': {'pullNumber': 12, 'draft': False}}
        self.assertEqual(self.ready(mcp).returncode, 0)
        (self.d / 'pr-number').write_text('12\n', encoding='utf-8')
        self.assertEqual(self.ready(bash('gh pr ready alice/shelf-model', self.repo)).returncode, 0)
        (self.d / 'pr-head').write_text(f"{self.git('rev-parse', 'main')} alice/shelf-model\n", encoding='utf-8')
        r = self.ready()  # GitHub's head is another commit: its marker is missing
        self.assertEqual(r.returncode, 2)
        self.assertIn('the checks have not passed', r.stderr)

    def test_a_head_it_cannot_find_denies(self):
        (self.d / 'gh-fails').write_text('', encoding='utf-8')
        r = self.ready()
        self.assertEqual(r.returncode, 2)
        self.assertIn('cannot read pull request #12', r.stderr)
        (self.d / 'gh-fails').unlink()
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')  # not pushed
        r = self.ready(bash('gh pr ready', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not what origin has", r.stderr)
        self.assertEqual(self.check().returncode, 0)
        self.push()
        self.reviewed()
        r = self.ready(bash('gh pr ready', self.repo))  # the stub finds no pull request for the branch
        self.assertEqual(r.returncode, 2)
        self.assertIn("has no open pull request for 'alice/shelf-model'", r.stderr)
        (self.d / 'pr-number').write_text('12\n', encoding='utf-8')
        self.assertEqual(self.ready(bash('gh pr ready', self.repo)).returncode, 0)

    def test_a_new_pull_request_must_be_a_draft(self):
        for payload in (bash('gh pr create --title "Add shelves" --body "Shelves."', self.repo),
                        {'cwd': str(self.repo), 'tool_name': 'mcp__github__create_pull_request',
                         'tool_input': {'head': 'alice/shelf-model', 'base': 'main', 'title': 'Add shelves'}}):
            with self.subTest(payload=payload):
                r = self.ready(payload)
                self.assertEqual(r.returncode, 2)
                self.assertIn('open it as a draft', r.stderr)
        self.assertEqual((self.d / 'gh-calls').exists(), False)  # denied before any question to GitHub

    def test_a_new_pull_request_is_checked_against_github_not_the_last_fetch(self):
        self.write({'docs/tracks/shelves/tasks/S01-shelf-model.md': TASK.format(state='done')})
        self.commit('Propose the shelf model done')
        self.assertEqual(self.check().returncode, 0)
        self.push()
        other = self.d / 'other'  # another clone pushes a commit with no marker, State active
        self.git('clone', '-q', '-b', 'alice/shelf-model', str(self.d / 'origin.git'), str(other), cwd=self.d)
        (other / 'docs/tracks/shelves/tasks/S01-shelf-model.md').write_text(TASK.format(state='active'), encoding='utf-8')
        self.git('-c', 'commit.gpgsign=false', 'commit', '-q', '-am', 'Reopen the shelf model', cwd=other)
        self.git('push', '-q', 'origin', 'alice/shelf-model', cwd=other)
        (self.d / 'pr-number').write_text('12\n', encoding='utf-8')
        r = self.ready(bash('gh pr ready alice/shelf-model', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn("is not what origin has", r.stderr)
        self.git('checkout', '-q', 'main')
        r = self.ready(bash('gh pr ready alice/shelf-model', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn('the checks have not passed', r.stderr)
        self.assertIn("has State 'active'", r.stderr)

    def test_the_repository_named_in_the_call_is_the_one_asked(self):
        self.ready(bash('gh pr ready -R pantry/elsewhere 12', self.repo))
        self.ready({'cwd': str(self.repo), 'tool_name': 'mcp__github__update_pull_request',
                    'tool_input': {'owner': 'pantry', 'repo': 'other', 'pullNumber': 13, 'draft': False}})
        calls = (self.d / 'gh-calls').read_text(encoding='utf-8')
        self.assertIn('repos/pantry/elsewhere/pulls/12', calls)
        self.assertIn('repos/pantry/elsewhere/issues/12/comments', calls)
        self.assertIn('repos/pantry/other/pulls/13', calls)
        self.ready()
        self.assertIn('repos/{owner}/{repo}/pulls/12', (self.d / 'gh-calls').read_text(encoding='utf-8'))

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
        self.reviewed()
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

    def test_a_merge_github_confirms_prints_the_event_and_rebases_open_prs(self):
        (self.d / 'pr-merged').write_text('true\n', encoding='utf-8')
        # gh prints nothing when its output is not a terminal, as under Claude Code.
        for payload in ({'cwd': str(self.repo), 'tool_name': 'mcp__github__merge_pull_request', 'tool_input': {'pullNumber': 12}},
                        bash('gh pr merge 12 --squash', self.repo)):
            with self.subTest(payload=payload):
                text = self.post(payload, {'stdout': '', 'stderr': ''})
                event = json.loads(text.split('(set):\n\n')[1].split('\n\n')[0])
                self.assertEqual((event['collection'], event['doc_id'], event['data']['state']), ('events', 'pr-12', 'merged'))
                self.assertIn('on main: 0, rebased: 0, conflicts: 0', text)
        (self.d / 'pr-number').write_text('14\n', encoding='utf-8')  # no number: the checked-out branch's pull request
        text = self.post(bash('gh pr merge --squash', self.repo), {'stdout': '', 'stderr': ''})
        self.assertIn('"doc_id": "pr-14"', text)
        self.assertIn('pulls?head={owner}:alice/shelf-model&state=closed', (self.d / 'gh-calls').read_text(encoding='utf-8'))

    def test_an_auto_merge_or_an_unmerged_one_is_not_a_merge(self):
        for cmd in ('gh pr merge 12 --auto --squash', 'gh pr merge 12'):
            with self.subTest(cmd=cmd):
                text = self.post(bash(cmd, self.repo), {'stdout': '', 'stderr': ''})
                self.assertIn('Control room refresh', text)
                self.assertIn('GitHub does not show the pull request as merged', text)
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

    def test_deleting_a_harness_branch_passes(self):
        for cmd in ('git push origin --delete claude/shelf-model', 'git push -d origin codex/x', 'git push origin :claude/x'):
            with self.subTest(cmd=cmd):
                self.assertEqual(hook('branch_name.py', bash(cmd, self.repo)).returncode, 0)

    def test_a_wrongly_typed_branch_prefixes_is_ignored_with_a_warning(self):
        self.write({'foreman.json': json.dumps(dict(FOREMAN, branch_prefixes=5))})
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertEqual(r.returncode, 0)
        self.assertIn("'branch_prefixes' must be a list of strings", context_of(r))
        self.git('branch', '-m', 'claude/shelf-model')
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn("'branch_prefixes' must be a list of strings", r.stderr)

    def test_an_unreadable_foreman_json_warns_instead_of_going_quiet(self):
        self.write({'foreman.json': '{"tracks": ['})
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertEqual(r.returncode, 0)
        self.assertIn('foreman.json cannot be read', context_of(r))

    def test_prefix_check_ignores_case_and_the_suggestion_is_lower_case(self):
        self.git('config', 'user.name', 'Alice')
        self.git('branch', '-m', 'Claude/shelf-model')
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertEqual(r.returncode, 2)
        self.assertIn('git branch -m alice/shelf-model', r.stderr)
        self.git('config', 'user.name', 'Claude')  # a container's default git name
        r = hook('branch_name.py', bash('git commit -m x', self.repo))
        self.assertIn('git branch -m <your-git-handle>/shelf-model', r.stderr)
        self.git('branch', '-m', 'alice/Shelf-Model')
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 0)

    def test_listed_prefixes_and_a_good_branch(self):
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 0)
        self.git('branch', '-m', 'bot/shelf-model')
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 2)
        (self.repo / 'foreman.json').unlink()
        self.assertEqual(hook('branch_name.py', bash('git commit -m x', self.repo)).returncode, 0)


class CommitAuthorTests(ScratchRepo):
    AGENT = {'GIT_AUTHOR_NAME': 'Claude', 'GIT_AUTHOR_EMAIL': 'noreply@anthropic.com'}

    def commit_hook(self, cmd='git commit -m "Add shelves"', cwd=None, **extra):
        return hook('commit_author.py', bash(cmd, cwd or self.repo), extra_env=extra)

    def test_denies_an_agent_author_and_passes_the_owner(self):
        for author in (self.AGENT, {'GIT_AUTHOR_NAME': 'Codex', 'GIT_AUTHOR_EMAIL': 'codex@example.invalid'},
                       {'GIT_AUTHOR_NAME': 'copilot-swe-agent[bot]', 'GIT_AUTHOR_EMAIL': 'c@example.invalid'},
                       {'GIT_AUTHOR_NAME': 'bot', 'GIT_AUTHOR_EMAIL': 'bot@example.invalid'},  # a branch_prefixes name
                       {'GIT_AUTHOR_NAME': 'Alice', 'GIT_AUTHOR_EMAIL': 'alice@mail.anthropic.com'}):
            with self.subTest(author=author):
                r = self.commit_hook(**author)
                self.assertEqual(r.returncode, 2)
                self.assertIn('the commit rule forbids', r.stderr)
        # The owner as author with the platform as committer: what a cloud session commits.
        r = self.commit_hook(GIT_AUTHOR_NAME='alice', GIT_AUTHOR_EMAIL='12345+alice@users.noreply.github.com',
                             GIT_COMMITTER_NAME='Claude', GIT_COMMITTER_EMAIL='noreply@anthropic.com')
        self.assertEqual((r.returncode, r.stdout), (0, ''))
        self.assertEqual(self.commit_hook(GIT_AUTHOR_NAME='Claudette').returncode, 0)
        self.assertEqual(self.commit_hook('git status', **self.AGENT).returncode, 0)

    def test_the_author_on_the_command_line_wins(self):
        r = self.commit_hook('git commit -m x --author="Claude <c@example.invalid>"')
        self.assertEqual(r.returncode, 2)
        self.assertIn("starts with the harness name 'claude'", r.stderr)
        self.assertEqual(self.commit_hook('git commit --author "Bob <bob@example.invalid>" -m x', **self.AGENT).returncode, 0)
        self.assertEqual(self.commit_hook('git -C pantry commit --author=ali -m x', self.d, **self.AGENT).returncode, 0)  # alice's commits
        r = self.commit_hook('git commit --author=nobody -m x')
        self.assertEqual(r.returncode, 2)
        self.assertIn('no commit by that --author', r.stderr)

    def test_the_allow_list(self):
        self.write({'foreman.json': json.dumps(dict(FOREMAN, commit_authors=['alice <alice@example.invalid>']))})
        self.assertEqual(self.commit_hook().returncode, 0)
        r = self.commit_hook(GIT_AUTHOR_NAME='Bob', GIT_AUTHOR_EMAIL='bob@example.invalid')
        self.assertEqual(r.returncode, 2)
        self.assertIn("Bob <bob@example.invalid> is not in foreman.json's commit_authors (alice <alice@example.invalid>)", r.stderr)
        self.write({'foreman.json': json.dumps(dict(FOREMAN, commit_authors=['Claude <noreply@anthropic.com>']))})
        self.assertEqual(self.commit_hook(**self.AGENT).returncode, 2)  # the deny-list has no switch
        self.write({'foreman.json': json.dumps(dict(FOREMAN, commit_authors='alice'))})
        r = self.commit_hook()
        self.assertEqual(r.returncode, 0)
        self.assertIn("'commit_authors' must be a list of strings", context_of(r))
        (self.repo / 'foreman.json').unlink()
        self.assertEqual(self.commit_hook(**self.AGENT).returncode, 0)  # not a foreman project

    def start(self, **extra):
        """The SessionStart hook, outside a cloud session unless `extra` says otherwise."""
        e = {'CLAUDE_CODE_REMOTE': '', 'CLAUDE_ENV_FILE': '', **extra}
        return hook('commit_author.py', {'hook_event_name': 'SessionStart', 'cwd': str(self.repo), 'source': 'startup'}, extra_env=e)

    def test_session_start_sets_one_listed_author(self):
        self.write({'foreman.json': json.dumps(dict(FOREMAN, commit_authors=['alice <12345+alice@users.noreply.github.com>']))})
        env_file = self.d / 'claude-env'
        r = self.start(CLAUDE_ENV_FILE=str(env_file))  # not a cloud session: no committer export
        self.assertIn('authored as alice <12345+alice@users.noreply.github.com>', context_of(r))
        self.assertNotIn('committer', context_of(r))
        self.assertFalse(env_file.exists())
        self.assertEqual((self.git('config', 'user.name'), self.git('config', 'user.email')), ('alice', '12345+alice@users.noreply.github.com'))
        r = self.start(CLAUDE_ENV_FILE=str(env_file), CLAUDE_CODE_REMOTE='true')
        self.assertIn('The committer stays Claude <noreply@anthropic.com>', context_of(r))
        self.assertEqual(env_file.read_text(encoding='utf-8'), 'export GIT_COMMITTER_NAME=Claude\nexport GIT_COMMITTER_EMAIL=noreply@anthropic.com\n')
        e = {k: v for k, v in env().items() if not k.startswith('GIT_')}  # what the Bash tool then sees
        e.update({'GIT_COMMITTER_NAME': 'Claude', 'GIT_COMMITTER_EMAIL': 'noreply@anthropic.com'})
        self.assertEqual(subprocess.run(['git', 'var', 'GIT_AUTHOR_IDENT'], cwd=self.repo, env=e, capture_output=True, text=True).stdout.split(' <')[0], 'alice')
        self.assertEqual(subprocess.run(['git', 'var', 'GIT_COMMITTER_IDENT'], cwd=self.repo, env=e, capture_output=True, text=True).stdout.split(' <')[0], 'Claude')

    def test_session_start_without_one_author_says_the_commands(self):
        for conf in (FOREMAN, dict(FOREMAN, commit_authors=['alice <a@example.invalid>', 'bob <b@example.invalid>']),
                     dict(FOREMAN, commit_authors=['alice'])):
            with self.subTest(conf=conf):
                self.write({'foreman.json': json.dumps(conf)})
                text = context_of(self.start(CLAUDE_CODE_REMOTE='true', CLAUDE_ENV_FILE=str(self.d / 'claude-env')))
                self.assertIn('does not name exactly one commit author', text)
                self.assertIn("git config user.name '<name>' && git config user.email '<email>'", text)
        self.assertEqual(self.git('config', 'user.name'), 'alice')  # the scratch repository's own setting, untouched
        self.assertFalse((self.d / 'claude-env').exists())
        (self.repo / 'foreman.json').unlink()
        self.assertEqual(self.start().stdout, '')


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
        self.assertEqual(self.staged(path, TASK.format(state='accepted')).returncode, 0)

    def test_a_finished_track_is_history(self):
        plan = 'docs/tracks/shelves/plan.md'
        bare = PLAN.replace('- Coordinator: the shelves track session\n', '').replace('- Budget: one developer session\n', '')
        r = self.staged(plan, bare)  # an active track still needs its head lines
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"{plan}: no '- Coordinator:' line", r.stderr)
        for word in ('complete', 'accepted', 'dropped'):
            with self.subTest(state=word):
                self.assertEqual(self.staged(plan, bare.replace('State: active', f'State: {word}')).returncode, 0)
        self.commit('Close the shelves track')
        old_task = TASK.format(state='finished').replace('- Updated: 2026-03-01\n', '')
        self.assertEqual(self.staged('docs/tracks/shelves/tasks/S01-shelf-model.md', old_task).returncode, 0)

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
        r = hook('task_shape.py', bash('git commit -m "Shelves; and && more" -a', self.repo))  # separators inside quotes
        self.assertEqual(r.returncode, 2)

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

    def test_a_wrongly_typed_jargon_is_ignored_with_a_warning(self):
        self.write({'foreman.json': json.dumps(dict(FOREMAN, jargon='an'))})
        text = context_of(hook('plain_language.py', bash('gh pr create --title "Add shelves" --body "An apple a day."', self.repo)))
        self.assertIn("'jargon' must be a list of strings", text)
        self.assertNotIn("jargon: 'a'", text)

    def test_unreadable_input_is_reported_as_context(self):
        for stdin in ('[1]', 'null', 'not json'):
            with self.subTest(stdin=stdin):
                r = hook('plain_language.py', stdin)
                self.assertEqual(r.returncode, 0)
                self.assertIn('cannot read its input', context_of(r))

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


    def guard(self, script, payload, path=None):
        e = dict(os.environ, PATH=path) if path else None
        return subprocess.run([shutil.which('bash'), script], input=json.dumps(payload), capture_output=True, text=True, env=e)

    def test_a_missing_patterns_file_denies_github_writes_only(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('session-link-gh.sh', 'session-link-mcp.sh'):
                shutil.copy(HOOKS / name, d)
            r = self.guard(f'{d}/session-link-gh.sh', bash("gh pr create --body 'Shelves.'"))
            self.assertEqual(r.returncode, 2)
            self.assertIn('cannot run', r.stderr)
            self.assertEqual(self.guard(f'{d}/session-link-gh.sh', bash('ls -la')).returncode, 0)
            self.assertEqual(self.guard(f'{d}/session-link-mcp.sh', {'tool_input': {'body': 'Shelves.'}}).returncode, 2)

    def test_no_grep_denies_github_writes_only(self):
        with tempfile.TemporaryDirectory() as d:  # a PATH with the tools the guards need, except grep
            for tool in ('cat', 'dirname'):
                os.symlink(shutil.which(tool), f'{d}/{tool}')
            r = self.guard(str(HOOKS / 'session-link-gh.sh'), bash("gh pr create --body 'Shelves.'"), path=d)
            self.assertEqual(r.returncode, 2)
            self.assertIn('needs grep', r.stderr)
            self.assertEqual(self.guard(str(HOOKS / 'session-link-gh.sh'), bash('ls -la'), path=d).returncode, 0)
            self.assertEqual(self.guard(str(HOOKS / 'session-link-mcp.sh'), {'tool_input': {'body': 'Shelves.'}}, path=d).returncode, 2)


class WiringTests(unittest.TestCase):
    def test_every_hook_script_is_wired(self):
        wired = json.dumps(json.loads((HOOKS / 'hooks.json').read_text(encoding='utf-8')))
        scripts = {p.name for p in HOOKS.iterdir() if p.suffix in ('.py', '.sh') and p.name != 'common.py'}
        self.assertEqual({s for s in scripts if s in wired}, scripts)
        self.assertEqual(len(scripts), 9)


if __name__ == '__main__':
    unittest.main()
