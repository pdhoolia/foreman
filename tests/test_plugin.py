"""The plugin as a whole: its manifest and components, a scratch project run end to end,
and a check that nothing from another project's private material is in this repository.

The scratch project is invented (a garden planner); `gh` is replaced by a stub that
prints a fixed pull request list, so no test reaches GitHub.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/control_room.py'
REFRESH = ROOT / 'scripts/control-room-refresh.sh'
CHECK = ROOT / 'scripts/control-room/check.cjs'
NODE = shutil.which('node')
CLAUDE = shutil.which('claude')
SKILLS = {'pm-start', 'pm-handoff', 'dispatch', 'review', 'inputs', 'refresh'}

PLAN = """# Garden planner

- State: active
- Coordinator: the garden track session
- Done when: a gardener can plan one bed on a phone
- Budget: two developer sessions, one review round each
- Updated: 2026-02-01

## Goal and boundaries

Plan which plants go in which bed, and when to sow them.

More words that the brief does not need.

## Tasks and dependencies

| ID / task file | Deliverable | Depends on | Owned paths/interfaces | Assigned branch |
| --- | --- | --- | --- | --- |
| [G01: bed model](tasks/G01-bed-model.md) | a bed with rows | this plan open | `app/bed.py` | `alice/bed-model` |
| G02: sowing calendar | when to sow each plant | G01 merged | `app/sow.py` | unassigned |

## Closure

Not started.
"""

TASK = """# G01 — Bed model

- State: active
- Track: [garden](../plan.md)
- Issue / PR: not created
- Branch: `alice/bed-model`
- Updated: 2026-02-01

## Handoff and memory

- Blocker: none.
- Next action: add rows to the bed.
"""

PLAIN = """# In plain words

| Task | In plain words |
| --- | --- |
| G01 | A bed that knows its rows. |
"""

RECORD = """# 2026-02-01: the first garden decisions

- Asked on: 2026-02-01
- Acted on in: the garden plan

## Questions and answers

### bed-shape: Should beds be square only?

Square beds are simpler.

| Option | What it means |
| --- | --- |
| Square | Simple. |
| Any shape | Harder. |

- Recommended: square, because it is simpler.
- **Owner chose:** square. Note: none.
- What happened next: G01 models square beds.
"""

PRS = [{'number': 3, 'title': 'Add the bed model', 'headRefName': 'alice/bed-model', 'isDraft': True,
        'url': 'https://github.com/example/garden/pull/3', 'updatedAt': '2026-02-01T10:00:00Z'},
       {'number': 4, 'title': 'Fix a typo', 'headRefName': 'bob/typo', 'isDraft': False,
        'url': 'https://github.com/example/garden/pull/4', 'updatedAt': '2026-02-01T10:00:00Z'}]

STORE = {'questions': [{'id': 'row-width', 'task': 'G01', 'title': 'How wide is a row?', 'options': []},
                       {'id': 'bed-shape', 'task': 'G01', 'title': 'Should beds be square only?', 'options': []},
                       {'id': 'colours', 'task': 'G02', 'title': 'Which colours?', 'options': []}],
         'answers': {'bed-shape': {'choice': 'square'}, 'colours': {'choice': 'green'}}}


def scratch_project(d: Path) -> Path:
    """A git checkout with one invented track: two tasks, one record, one plain-words table."""
    proj = d / 'garden'
    for path, text in {
        'foreman.json': json.dumps({'title': 'Garden Control Room', 'control_room_url': 'https://example.com/room',
                                    'tracks': [{'slug': 'garden', 'lanes': [{'key': 'G', 'name': 'garden', 'model': 'Model Z'}]}]}),
        'docs/tracks/garden/plan.md': PLAN,
        'docs/tracks/garden/tasks/G01-bed-model.md': TASK,
        'docs/tracks/plain-words.md': PLAIN,
        'docs/inputs/2026-02-01-first.md': RECORD,
        'docs/program.md': '# Program plan\n',
    }.items():
        (proj / path).parent.mkdir(parents=True, exist_ok=True)
        (proj / path).write_text(text, encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    subprocess.run(['git', 'init', '-q', str(proj)], check=True, env=env)
    bin_dir = d / 'bin'
    bin_dir.mkdir()
    (d / 'prs.json').write_text(json.dumps(PRS), encoding='utf-8')
    (bin_dir / 'gh').write_text(f'#!/bin/sh\ncat "{d / "prs.json"}"\n', encoding='utf-8')
    (bin_dir / 'gh').chmod(0o755)
    return proj


def run(cmd, cwd, d):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env['PATH'] = f"{d / 'bin'}{os.pathsep}{env['PATH']}"
    env.pop('CONTROL_ROOM_URL', None)
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)


class ScratchProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.proj = scratch_project(self.d)
        self.out = self.d / 'out'

    def tearDown(self):
        self.tmp.cleanup()

    def refresh(self, *own):
        r = run(['bash', str(REFRESH), str(self.out), *own], self.proj, self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout, json.loads((self.out / 'state.json').read_text(encoding='utf-8'))

    def test_refresh_end_to_end(self):
        printed, state = self.refresh()
        self.assertIn('url:          https://example.com/room', printed)
        self.assertEqual([(l['key'], l['model'], l['tasks']) for l in state['lanes']], [('G', 'Model Z', ['task-G01', 'task-G02'])])
        tasks = {t['anchor']: t for t in state['tasks']}
        self.assertEqual((tasks['task-G01']['state'], tasks['task-G01']['branch']), ('active', 'alice/bed-model'))
        self.assertEqual(tasks['task-G02']['deps'], ['task-G01'])
        self.assertEqual([p['task'] for p in state['prs']], ['task-G01', None])
        self.assertEqual(state['records'][0]['questions'][0]['choice'], 'square')
        track = state['tracks'][0]
        self.assertEqual((track['coordinator'], track['done_when'], track['budget']),
                         ('the garden track session', 'a gardener can plan one bed on a phone', 'two developer sessions, one review round each'))
        page = (self.out / 'index.html').read_text(encoding='utf-8')
        self.assertTrue(page.startswith('<title>Garden Control Room</title>'))
        if NODE:
            r = subprocess.run([NODE, str(CHECK), str(self.out / 'state.json'), '-', '-'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            tabs = json.loads(r.stdout)['tabs']
            for line in ('<dt>Coordinator</dt><dd>the garden track session</dd>',
                         '<dt>Done when</dt><dd>a gardener can plan one bed on a phone</dd>',
                         '<dt>Budget</dt><dd>two developer sessions, one review round each</dd>',
                         'id="task-G01"', 'id="task-G02"', 'A bed that knows its rows.'):
                self.assertIn(line, tabs['lanes'])
            self.assertIn('id="rec-bed-shape"', tabs['records'])

    def test_refresh_keeps_the_tracks_it_does_not_own(self):
        _, state = self.refresh()
        state['tracks'].append({'slug': 'compost', 'title': 'Compost', 'path': 'docs/tracks/compost/plan.md', 'state': 'active',
                                'updated': None, 'done': False, 'coordinator': '', 'done_when': '', 'budget': '', 'tasks': ['task-K01']})
        state['tasks'].append(dict(state['tasks'][0], id='K01', anchor='task-K01', track='compost', depends_on=[], branch=None))
        (self.out / 'live-state.json').write_text(json.dumps(state), encoding='utf-8')
        _, merged = self.refresh('garden')
        self.assertEqual({t['track'] for t in merged['tasks']}, {'garden', 'compost'})
        (self.out / 'live-state.json').unlink()
        r = run(['bash', str(REFRESH), str(self.out), 'garden'], self.proj, self.d)
        self.assertNotEqual(r.returncode, 0)  # naming a track without the published state is refused

    def test_track_brief(self):
        (self.d / 'store.json').write_text(json.dumps(STORE), encoding='utf-8')
        r = run([sys.executable, '-I', str(SCRIPT), 'brief', 'track', 'garden', '--root', '.',
                 '--prs', str(self.d / 'prs.json'), '--store', str(self.d / 'store.json')], self.proj, self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = r.stdout
        self.assertIn('Read first: docs/program.md, docs/tracks/garden/plan.md, docs/tracks/garden/tasks/G01-bed-model.md', b)
        self.assertIn('- Goal: Plan which plants go in which bed, and when to sow them.', b)
        self.assertIn('- Done when: a gardener can plan one bed on a phone', b)
        self.assertIn('- Budget: two developer sessions, one review round each', b)
        self.assertIn('- G01 bed model: active, branch `alice/bed-model`. Next: add rows to the bed.', b)
        self.assertIn('- G02 waits for G01', b)
        self.assertIn('- #3 Add the bed model (draft)', b)
        self.assertNotIn('#4', b)
        self.assertIn('- row-width: How wide is a row? (for G01)', b)
        self.assertNotIn('bed-shape', b)  # answered
        self.assertIn('## Next action\n- none written; read the plan', b)

    def test_program_brief(self):
        (self.d / 'store.json').write_text(json.dumps(STORE), encoding='utf-8')
        r = run([sys.executable, '-I', str(SCRIPT), 'brief', 'program', '--root', '.',
                 '--prs', str(self.d / 'prs.json'), '--store', str(self.d / 'store.json')], self.proj, self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        b = r.stdout
        self.assertIn('- garden (active): 1 active, 1 planned; coordinator: the garden track session', b)
        self.assertIn('; unanswered cards: 1\n', b)
        self.assertIn('- garden G02 waits for G01', b)
        self.assertIn('- #4 Fix a typo', b)
        self.assertIn('## Answered, not yet recorded under docs/inputs/\n- colours\n', b)  # bed-shape has its record
        self.assertIn('rebase-open-prs.sh', b)

    def test_brief_without_prs_or_store_says_so(self):
        r = run([sys.executable, '-I', str(SCRIPT), 'brief', 'track', 'garden', '--root', '.'], self.proj, self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('- not read: pass --prs', r.stdout)
        self.assertIn('- not read: pass --store', r.stdout)

    def test_handoff_writes_the_section_and_refreshes(self):
        text = self.d / 'handoff.md'
        text.write_text('- Current result: G01 pushed.\n- Next action: dispatch G02.\n', encoding='utf-8')
        for _ in range(2):  # the second run replaces the section instead of adding another
            r = run([sys.executable, '-I', str(SCRIPT), 'handoff', '--root', '.', '--track', 'garden', '--text', str(text)], self.proj, self.d)
            self.assertEqual(r.returncode, 0, r.stderr)
        plan = (self.proj / 'docs/tracks/garden/plan.md').read_text(encoding='utf-8')
        self.assertEqual(plan.count('## Handoff and memory'), 1)
        self.assertLess(plan.index('## Handoff and memory'), plan.index('## Closure'))
        self.assertNotIn('- Updated: 2026-02-01', plan)
        self.assertRegex(plan, r'- Updated: \d{4}-\d{2}-\d{2}\n')
        r = run([sys.executable, '-I', str(SCRIPT), 'brief', 'track', 'garden', '--root', '.'], self.proj, self.d)
        self.assertIn('## Next action\n- dispatch G02.', r.stdout)
        _, state = self.refresh()
        self.assertNotEqual(state['tracks'][0]['updated'], '2026-02-01')


class ManifestTests(unittest.TestCase):
    def test_manifest_and_components(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['name'], manifest['version']), ('foreman', '0.1.0'))
        self.assertTrue(manifest['description'] and manifest['author']['name'])
        market = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
        self.assertEqual([(p['name'], p['source']) for p in market['plugins']], [('foreman', './')])
        self.assertEqual(json.loads((ROOT / 'hooks/hooks.json').read_text(encoding='utf-8'))['hooks'], {})
        skills = {p.parent.name for p in (ROOT / 'skills').glob('*/SKILL.md')}
        self.assertEqual(skills, SKILLS)
        for name in SKILLS:
            head = (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
            self.assertIn(f'name: {name}\n', head)
            self.assertIn('description: ', head)
        self.assertEqual({p.stem for p in (ROOT / 'agents').glob('*.md')}, {'developer', 'reviewer', 'scribe'})
        for name in ('plan.md', 'task.md', 'record.md', 'sample-spec.json', 'program.md', 'sdlc.md'):
            self.assertTrue((ROOT / 'templates' / name).is_file(), name)

    @unittest.skipUnless(CLAUDE, 'the claude CLI is not installed')
    def test_claude_plugin_validate(self):
        r = subprocess.run([CLAUDE, 'plugin', 'validate', str(ROOT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('Validation passed', r.stdout)


class NoProjectStringsTests(unittest.TestCase):
    """Nothing from the first consuming project. The words are split, and the artifact
    ids are kept as hashes, so that this file does not carry them either."""

    WORDS = ['str' + 'ata', 'pdh' + 'oolia', 'claude.ai' + '/artifact']
    ID_HASHES = {
        '6f5195e71e06fcc2c1e57e523dd02746b0efc0f0a8ffa8f874e25f608365551c',
        'c503f3a163b4d16deaea8f4abc2372a3b911367fb2b4070fc3789709a619e71e',
        '4fbbfc345bd23b562144e2bd8c084c9ca83b135304e9e33dd01e1a30b98336d8',
    }

    def test_no_hit_outside_the_readme_install_example(self):
        hits = []
        for path in sorted(ROOT.rglob('*')):
            rel = path.relative_to(ROOT)
            if not path.is_file() or rel.parts[0] == '.git' or '__pycache__' in rel.parts or '.pytest_cache' in rel.parts:
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            if str(rel) == 'README.md':  # the generic install example may name the repository
                text = re.sub(r'^## Install\n.*?(?=^## )', '', text, flags=re.M | re.S)
            low = text.lower()
            hits += [f'{rel}: {w}' for w in self.WORDS if w in low]
            hits += [f'{rel}: an artifact id' for tok in set(re.findall(r'[A-Za-z0-9]{22}', text))
                     if hashlib.sha256(tok.encode()).hexdigest() in self.ID_HASHES]
        self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
