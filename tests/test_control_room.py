"""The control room: state from the repository, review items, the static page and its tabs.

The fixture under tests/fixtures/control-room/ is a fictional repository (a recipe app),
so nothing private reaches a test. The page's tabs are rendered by the page's own
render.js under node (skipped when node is missing).
"""
import contextlib
import datetime as dt
import io
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/control-room'
SCRIPT = ROOT / 'scripts/control_room.py'
CHECK = ROOT / 'scripts/control-room/check.cjs'
SPEC = importlib.util.spec_from_file_location('control_room', SCRIPT)
cr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cr)

# The fictional state file was fetched "at" this time; the store's events are judged against it.
BUILT = dt.datetime(2026, 1, 3, 12, 0, tzinfo=dt.timezone.utc)
NODE = shutil.which('node')


def fixture_state():
    prs = json.loads((FIXTURE / 'prs.json').read_text(encoding='utf-8'))
    return cr.collect(FIXTURE / 'repo', prs, now=BUILT)


def ids(html):
    return set(re.findall(r'\bid="([^"]+)"', html or ''))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.state = fixture_state()
        self.tasks = {t['anchor']: t for t in self.state['tasks']}

    def test_tasks_lanes_and_models(self):
        a01 = self.tasks['task-A01']
        self.assertEqual((a01['state'], a01['lane'], a01['model']), ('review', 'A', 'Model Y, high'))
        self.assertEqual(a01['branch'], 'fiction/bench')  # the first code span, not the whole bullet
        self.assertEqual(self.tasks['task-B01']['model'], 'Model Y, medium')
        self.assertIsNone(self.tasks['task-B01']['branch'])
        self.assertEqual(self.tasks['task-B02']['deps'], ['task-B01'])
        self.assertNotIn('T01', {t['id'] for t in self.state['tasks']})  # templates are skipped
        lanes = [(l['kind'], l['key'] or l['slug'], l['tasks']) for l in self.state['lanes']]
        self.assertEqual(lanes, [
            ('lane', 'A', ['task-A01']), ('lane', 'B', ['task-B01', 'task-B02']),
            ('track', 'widgets', ['task-W01', 'task-W02', 'task-W03']),  # an active track outside every lane still shows
        ])
        self.assertEqual(self.state['lanes'][0]['plan'], 'docs/tracks/bench/plan.md')  # lanes come from foreman.json
        self.assertEqual(self.state['counts'], {'tasks': 6, 'active': 1, 'done': 0})

    def test_anchors_are_unique_and_active_tasks_keep_the_short_form(self):
        anchors = [t['anchor'] for t in self.state['tasks']]
        self.assertEqual(len(anchors), len(set(anchors)))
        self.assertEqual(self.tasks['task-W01']['track'], 'widgets')
        self.assertEqual(self.tasks['task-old-W01']['track'], 'old')
        self.assertTrue(all(re.fullmatch(r'[A-Za-z0-9_.~-]+', a) for a in anchors))

    def test_critical_path_and_plain_words(self):
        self.assertEqual(self.state['critical_path'], ['task-A01', 'task-B01', 'task-B02'])
        self.assertTrue(self.tasks['task-B01']['critical'])
        self.assertFalse(self.tasks['task-W01']['critical'])
        self.assertEqual(self.tasks['task-A01']['plain'], 'We built a bench that scores search ideas in seconds.')
        self.assertEqual(self.tasks['task-W02']['plain'], 'merge equal items')  # falls back to the deliverable
        self.assertIn({'id': 'W01', 'anchor': 'task-W01', 'text': 'A list that knows which items you need to buy.'},
                      self.state['plain_words'])

    def test_needs_and_pull_requests(self):
        self.assertEqual(self.state['needs'], [{'kind': 'decision', 'task': 'task-A01',
                                                'text': 'A01: pick the label set for the bench',
                                                'link': 'docs/tracks/bench/tasks/A01-bench.md'}])
        prs = {p['number']: p for p in self.state['prs']}
        self.assertEqual((prs[7]['state'], prs[7]['task']), ('ready', 'task-A01'))
        self.assertEqual((prs[8]['state'], prs[8]['task']), ('open', 'task-W01'))
        self.assertIsNone(prs[9]['task'])
        self.assertTrue(self.state['prs_included'])
        self.assertEqual(self.state['generated_at'], '2026-01-03T12:00:00Z')

    def test_findings_rows_words_and_readings(self):
        f = self.state['findings']
        self.assertEqual(len(f['rows']), 5)  # the non-report JSON file is skipped
        row = next(r for r in f['rows'] if r['variant'] == 'stemming' and r['set'] == 'short-queries')
        self.assertEqual((row['ari'], row['clusters'], row['abstained']), (0.2, 8, 2))
        self.assertEqual(f['methods']['stemming'], 'Cuts words to their stem first, so "tomatoes" finds "tomato".')
        self.assertEqual(f['set_words']['short-queries'], "One- and two-word searches from the app's search box.")
        self.assertEqual(f['columns']['records']['help'], 'How many searches the row stands on.')
        self.assertIn('Adjusted Rand index', f['columns']['ari']['help'])
        self.assertEqual(sorted(r['note'] for r in f['rows'] if r['set'] == 'long-queries'), ['alpha 0.25', 'alpha 0.5'])
        skills = next(r for r in f['rows'] if r['kind'] == 'skills')
        self.assertEqual((skills['candidates'], skills['support'], skills['coverage_overall']), (3, 2.5, 0.2))
        best = {(s['kind'], s['set']): s['best'] for s in f['sets']}
        self.assertEqual(best[('clustering', 'short-queries')], {'variants': ['stemming'], 'value': 0.2})
        self.assertEqual(best[('clustering', 'long-queries')]['variants'], ['stemming (alpha 0.25)', 'stemming (alpha 0.5)'])
        self.assertEqual([r['lead'] for r in f['readings']],
                         ['Stemming helps on short queries.', 'Synonyms cost more than they give.'])
        self.assertEqual(f['readings'][0]['text'], 'Plain words lose recipes with plurals; stemming finds them.')

    def test_decision_record_is_parsed(self):
        self.assertEqual(len(self.state['records']), 1)  # README.md is not a record
        rec = self.state['records'][0]
        self.assertEqual((rec['anchor'], rec['date'], rec['title']),
                         ('rec-2026-01-02-first-round', '2026-01-02', 'the first round of owner decisions'))
        self.assertEqual(rec['acted'], 'task A01 and the bench plan')
        q = rec['questions'][0]
        self.assertEqual((q['id'], q['anchor']), ('search-labels', 'rec-search-labels'))
        self.assertEqual(q['body'], 'The bench needs labels to score search ideas against.\n\nTwo kinds are available.')
        self.assertEqual(q['options'], [{'label': 'The recipe categories', 'detail': 'Free, but coarse.'},
                                        {'label': 'Hand labels', 'detail': 'Slower, but fine-grained.'}])
        self.assertEqual(q['recommended'], 'the recipe categories, because they cost nothing and the bench can start today.')
        self.assertEqual((q['choice'], q['note']), ('hand labels', 'Categories are too coarse for search.'))
        self.assertEqual(q['next'], 'task A01 adds a labelling step.')
        self.assertEqual((rec['questions'][1]['choice'], rec['questions'][1]['note']), ('yes', ''))
        self.assertEqual(rec['items']['result'], '6 labelled, 3 classes. The labels stay outside git.')

    def test_fixture_tree_is_not_read_through_the_outer_checkout(self):
        self.assertIsNone(self.state['revision'])
        self.assertIsNone(self.state['project']['repo_url'])

    def test_kind_headings_are_neutral(self):
        self.assertEqual(self.state['findings']['kinds']['clustering'], 'Grouping items by label')

    def test_live_state_keeps_the_tracks_this_session_does_not_own(self):
        # Another coordinator published widgets with W01 done; this checkout still says active.
        live = json.loads(json.dumps(self.state))
        w01 = next(t for t in live['tasks'] if t['anchor'] == 'task-W01')
        w01['state'] = 'done'
        live['tracks'].append({'slug': 'elsewhere', 'title': 'Only on another branch', 'path': 'docs/tracks/elsewhere/plan.md',
                               'state': 'active', 'updated': None, 'done': False, 'coordinator': '', 'done_when': '',
                               'budget': '', 'tasks': ['task-E01']})
        live['tasks'].append(dict(w01, id='E01', anchor='task-E01', track='elsewhere', state='active', depends_on=[]))
        bench = next(t for t in live['tasks'] if t['anchor'] == 'task-A01')
        bench['state'] = 'dropped'  # the published copy of the owned track is ignored
        state = cr.collect(FIXTURE / 'repo', None, now=BUILT, live=live, own={'bench'})
        tasks = {t['anchor']: t for t in state['tasks']}
        self.assertEqual(tasks['task-W01']['state'], 'done')
        self.assertEqual(tasks['task-E01']['track'], 'elsewhere')
        self.assertEqual(tasks['task-A01']['state'], 'review')
        self.assertEqual(tasks['task-W02']['deps'], ['task-W01'])  # dependencies survive the round trip
        self.assertEqual(tasks['task-A01']['plain'], 'We built a bench that scores search ideas in seconds.')


class ReviewTests(unittest.TestCase):
    def test_review_keeps_only_the_shown_fields(self):
        data = cr.review(json.loads((FIXTURE / 'review-spec.json').read_text(encoding='utf-8')))
        self.assertEqual(data['format'], 'control-room-review/v1')
        self.assertEqual([r['id'] for r in data['rows']], ['q-01', 'q-02', 'q-03'])
        self.assertNotIn('private_note', data['rows'][1])
        self.assertEqual(data['field'], 'What was this search for?')

    def test_review_refuses_unsafe_or_repeated_ids(self):
        with self.assertRaises(SystemExit):
            cr.review({'field': 'f', 'rows': [{'id': 'a b'}]})
        with self.assertRaises(SystemExit):
            cr.review({'field': 'f', 'rows': [{'id': 'a'}, {'id': 'a'}]})
        with self.assertRaises(SystemExit):
            cr.review({'rows': []})


class StoreDocumentTests(unittest.TestCase):
    """Store documents are built by the script and checked against scripts/store-schema.json."""

    def cli(self, *a):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *a], capture_output=True, text=True)

    def test_event_pr_prints_the_documented_shape(self):
        r = self.cli('event', 'pr', '12', 'merged', '--title', 'Add the list model',
                     '--url', 'https://github.com/example/pantry-notes/pull/12', '--updated', '2026-01-03T13:00:00Z')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {'collection': 'events', 'doc_id': 'pr-12', 'data': {
            'number': 12, 'state': 'merged', 'updated': '2026-01-03T13:00:00Z', 'title': 'Add the list model',
            'url': 'https://github.com/example/pantry-notes/pull/12'}})

    def test_event_pr_refuses_wrong_field_names_and_values(self):
        r = self.cli('event', 'pr', '12', 'merged', '--at', '2026-01-03T13:00:00Z')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('unrecognized arguments: --at', r.stderr)
        r = self.cli('event', 'pr', '12', 'gone')
        self.assertIn("invalid choice: 'gone'", r.stderr)
        r = self.cli('event', 'pr', '12', 'ready', '--updated', 'yesterday')
        self.assertIn("field 'updated' must be time", r.stderr)
        # The hand-typed document that once showed merged PRs as open drafts.
        with self.assertRaises(SystemExit) as e:
            cr.check_doc('events', 'pr-12', {'number': 12, 'kind': 'merged', 'at': '2026-01-03T13:00:00Z'})
        for words in ("unknown field 'kind'", "unknown field 'at'", "missing field 'state'", "missing field 'updated'"):
            self.assertIn(words, str(e.exception))
        with self.assertRaises(SystemExit):
            cr.check_doc('events', 'pr-13', {'number': 12, 'state': 'open', 'updated': '2026-01-03T13:00:00Z'})

    def test_card_builds_a_question_the_page_renders(self):
        r = self.cli('card', '--id', 'search-scope', '--task', 'A01', '--order', '1', '--title', 'Should search also look inside the steps?',
                     '--body', 'Today search reads titles and ingredients.', '--option', 'titles', 'Titles and ingredients only', 'Fast and precise.',
                     '--option', 'steps', 'Steps too', 'Finds more, with more noise.', '--recommended', 'titles', '--why', 'Most searches name a dish.')
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual((doc['collection'], doc['doc_id']), ('questions', 'search-scope'))
        self.assertEqual(doc['data']['options'], [{'id': 'titles', 'label': 'Titles and ingredients only', 'detail': 'Fast and precise.'},
                                                  {'id': 'steps', 'label': 'Steps too', 'detail': 'Finds more, with more noise.'}])
        fixture = json.loads((FIXTURE / 'store.json').read_text(encoding='utf-8'))
        self.assertEqual({k: v for k, v in doc['data'].items() if k != 'body' and k != 'why'},
                         {k: v for k, v in fixture['questions'][0].items() if k not in ('id', 'body', 'why')})
        r = self.cli('card', '--id', 'bad id', '--title', 'T', '--body', 'B', '--option', 'a', 'A', '--recommended', 'b')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("id 'bad id' does not match", r.stderr)
        self.assertIn("field 'recommended' must be option-id", r.stderr)

    def test_answers_and_labels_have_a_schema_too(self):
        cr.check_doc('answers', 'search-scope', {'choice': 'titles', 'note': '', 'updated': '2026-01-03T14:00:00Z'})
        cr.check_doc('labels', 'q-01', {'goal': 'find-dish', 'updated': '2026-01-03T09:00:00Z'})
        with self.assertRaises(SystemExit):
            cr.check_doc('labels', 'q-01', {'label': 'find-dish', 'updated': '2026-01-03T09:00:00Z'})


class PageTests(unittest.TestCase):
    def test_page_is_static_and_loads_its_data_by_fetch(self):
        page = cr.page('Pantry <Notes> Control Room')
        self.assertTrue(page.startswith('<title>Pantry &lt;Notes&gt; Control Room</title>'))
        self.assertIn('<meta name="claude:viewport-fit-sides" content="cover">', page)
        for text in ("fetch('state.json'", "fetch('review.json'", 'prefers-color-scheme: dark', ':root[data-theme="dark"]',
                     'env(safe-area-inset-left, 0px)', 'prefers-reduced-motion', "window.claude.use('db')"):
            self.assertIn(text, page)
        for tab in ('needs', 'lanes', 'findings', 'review', 'records'):
            self.assertIn(f'<section class="panel" id="{tab}"', page)
            self.assertIn(f'href="#{tab}"', page)
        self.assertEqual(page.count('<script'), 1)  # one inline script, no data script
        self.assertEqual(page.count('</script>'), 1)
        self.assertNotIn('{{', page)
        self.assertNotIn('text-transform: uppercase', page)
        self.assertLess(len(page.encode()), 200_000)

    def test_cli_writes_files_and_leaves_an_unchanged_page_alone(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            run = lambda *a: subprocess.run([sys.executable, '-I', str(SCRIPT), *a], capture_output=True, text=True)
            r = run('state', '--root', str(FIXTURE / 'repo'), '--prs', str(FIXTURE / 'prs.json'), '--out', str(out / 'state.json'))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run('state', '--root', str(FIXTURE / 'repo'), '--own', 'bench', '--out', str(out / 'state.json'))
            self.assertNotEqual(r.returncode, 0)  # --own without --live would drop the other tracks
            self.assertEqual(json.loads((out / 'state.json').read_text())['format'], 'control-room-state/v1')
            r = run('review', '--spec', str(FIXTURE / 'review-spec.json'), '--out', str(out / 'review.json'))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run('page', '--root', str(FIXTURE / 'repo'), '--out', str(out / 'index.html'))
            self.assertEqual(json.loads(r.stdout), {'title': 'Pantry Notes Control Room', 'changed': True}, r.stderr)
            r = run('page', '--root', str(FIXTURE / 'repo'), '--out', str(out / 'index.html'))
            self.assertEqual(json.loads(r.stdout)['changed'], False)

    def test_scripts_parse(self):
        for name in ('control-room-refresh.sh', 'rebase-open-prs.sh'):
            r = subprocess.run(['bash', '-n', str(ROOT / 'scripts' / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


@unittest.skipUnless(NODE, 'node is not installed')
class RenderTests(unittest.TestCase):
    """Every tab rendered by the page's own code from the fixture state, review and store."""

    ROUTES = '#needs,#lanes,#findings,#review,#records,#q-search-scope,#q-search-labels,#item-q-02,#task-W01,#task-old-W01,#rec-phone-first,#pr-8,#nonsense'

    def render(self, review=True, store='store.json', state=None):
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / 'state.json'
            sp.write_text(json.dumps(state or fixture_state()), encoding='utf-8')
            rp = '-'
            if review:
                rp = Path(d) / 'review.json'
                rp.write_text(json.dumps(cr.review(json.loads((FIXTURE / 'review-spec.json').read_text(encoding='utf-8')))), encoding='utf-8')
            store_path = str(FIXTURE / store) if store else '-'
            r = subprocess.run([NODE, str(CHECK), str(sp), str(rp), store_path], capture_output=True, text=True,
                               env={'ROUTES': self.ROUTES, 'PATH': '/usr/bin:/bin'})
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)

    def test_scripts_parse(self):
        for name in ('render.js', 'app.js', 'check.cjs'):
            r = subprocess.run([NODE, '--check', str(ROOT / 'scripts/control-room' / name)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_tab_and_anchor(self):
        out = self.render()
        tabs = out['tabs']
        state = fixture_state()
        self.assertTrue(all(tabs[t] for t in ('needs', 'lanes', 'findings', 'review', 'records')))
        # Needs you: open decisions only; the answered one is under Records.
        self.assertIn('q-search-scope', ids(tabs['needs']))
        self.assertIn('q-escape-check', ids(tabs['needs']))  # a note without a choice keeps the card open
        self.assertNotIn('q-search-labels', ids(tabs['needs']))
        self.assertIn('q-search-labels', ids(tabs['records']))
        # One list: a recorded decision shows its recorded choice inside its round; nothing waits unrecorded.
        self.assertIn('<span class="chose">Recorded: ', tabs['records'])
        self.assertIn('rec-search-labels', ids(tabs['records']))
        self.assertNotIn('rec-pending', ids(tabs['records']))
        self.assertIn('PM recommends', tabs['needs'])
        # A card for a bare task ID that repeats in a finished track links to the active task.
        self.assertIn('Decision for <a href="#task-W01">W01</a>', tabs['needs'])
        # Lanes: every task card, active or finished, has its anchor; the plain words ride on the card.
        self.assertEqual({t['anchor'] for t in state['tasks']} - ids(tabs['lanes']), set())
        self.assertIn('We built a bench that scores search ideas in seconds.', tabs['lanes'])
        self.assertEqual(tabs['lanes'].count('class="card critical'), 3)
        self.assertIn('lane-widgets', ids(tabs['lanes']))
        # The track's goal lines from its plan head show on the lane that links the plan.
        self.assertIn('<dt>Done when</dt><dd>the search ships behind a switch and the owner has tried it</dd>', tabs['lanes'])
        self.assertEqual(next(t for t in state['tracks'] if t['slug'] == 'bench')['budget'], 'two developer sessions, two review rounds each')
        # Findings: method words, column words and the reading lines.
        self.assertIn('Cuts words to their stem first', tabs['findings'])
        self.assertIn('How many searches the row stands on.', tabs['findings'])
        self.assertIn('Stemming helps on short queries.', tabs['findings'])
        self.assertIn('<b>stemming (alpha 0.25)</b> and <b>stemming (alpha 0.5)</b>, tied,', tabs['findings'])
        # Review and Records anchors.
        self.assertTrue({'item-q-01', 'item-q-02', 'item-q-03'} <= ids(tabs['review']))
        self.assertTrue({'rec-2026-01-02-first-round', 'rec-search-labels', 'rec-phone-first'} <= ids(tabs['records']))
        self.assertIn('task-W01', tabs['records'])  # plain words link back to the card
        routes = out['routes']
        self.assertEqual(routes['#q-search-scope'], {'tab': 'needs', 'target': 'q-search-scope'})
        self.assertEqual(routes['#q-search-labels'], {'tab': 'records', 'target': 'q-search-labels'})
        self.assertEqual(routes['#item-q-02'], {'tab': 'review', 'target': 'item-q-02'})
        self.assertEqual(routes['#task-old-W01'], {'tab': 'lanes', 'target': 'task-old-W01'})
        self.assertEqual(routes['#rec-phone-first'], {'tab': 'records', 'target': 'rec-phone-first'})
        self.assertEqual(routes['#pr-8'], {'tab': 'needs', 'target': 'pr-8'})
        for tab in ('needs', 'lanes', 'findings', 'review', 'records'):
            self.assertEqual(routes['#' + tab], {'tab': tab})
        self.assertIsNone(routes['#nonsense'])

    def test_no_id_repeats_across_the_page(self):
        tabs = self.render()['tabs']
        page = re.sub(r'<script>.*</script>', '', cr.page('Trial Control Room'), flags=re.S)  # the page's own markup
        found = re.findall(r'\bid="([^"]+)"', page + ''.join(tabs[t] for t in tabs))
        repeated = sorted({i for i in found if found.count(i) > 1})
        self.assertEqual(repeated, [])

    def test_review_tab_hides_without_review_json(self):
        out = self.render(review=False)
        self.assertIsNone(out['tabs']['review'])
        self.assertEqual(out['routes']['#review'], {'tab': 'needs'})
        self.assertEqual(out['routes']['#item-q-02'], {'tab': 'needs'})

    def test_live_pull_requests(self):
        out = self.render()
        prs = {p['number']: p for p in out['prs']}
        self.assertIn(7, prs)  # its merged event is older than the state file, so the state file wins
        self.assertEqual(prs[8]['state'], 'ready')  # a newer ready event
        self.assertNotIn(9, prs)  # a newer merged event removes the row without a republish
        self.assertEqual(prs[10]['state'], 'open')  # a new draft only the watcher knows about
        self.assertNotIn('url', {k for k, v in prs[11].items() if v})  # a non-https link is dropped
        self.assertNotIn('pr-9', ids(out['tabs']['needs']))
        self.assertIn('pr-8', ids(out['tabs']['needs']))
        # 2 open decisions, PRs 7, 8 and 11 ready, 1 task note.
        self.assertEqual(out['count'], 2 + 3 + 1)

    def test_saved_decision_leaves_needs_you(self):
        store = json.loads((FIXTURE / 'store.json').read_text(encoding='utf-8'))
        store['answers']['search-scope'] = {'choice': 'titles', 'note': '', 'updated': '2026-01-03T14:00:00Z'}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'store.json'
            p.write_text(json.dumps(store), encoding='utf-8')
            out = self.render(store=str(p))
        self.assertNotIn('q-search-scope', ids(out['tabs']['needs']))
        self.assertIn('q-search-scope', ids(out['tabs']['records']))
        self.assertIn('You chose <b>Titles and ingredients only</b>', out['tabs']['records'])

    def test_store_text_is_escaped(self):
        needs = self.render()['tabs']['needs']
        self.assertNotIn('<img src=x', needs)
        self.assertNotIn('<script>alert', needs)
        self.assertNotIn('<b>bold</b>', needs)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', needs)
        self.assertNotIn('" onfocus="', needs)

    def test_without_the_store(self):
        out = self.render(store=None)
        self.assertIn('cannot reach', out['tabs']['needs'])
        self.assertEqual(out['count'], 2 + 1)  # PRs 7 and 9 ready, 1 task note; no decisions


if __name__ == '__main__':
    unittest.main()
