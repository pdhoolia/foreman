"""Starting the track coordinators: the prompts, the "Coordinators to start" section of the
program brief, and the `coordinators` skill's starter.

The project is a copy of the invented recipe app under tests/fixtures/control-room/repo,
with two active tracks that have a next action and one finished track, made a git checkout
so the starter has a place for its prompt files. `claude`, `osascript` and `tmux` are stubs
that record their arguments, so no test opens a terminal.
"""
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / 'tests/fixtures/control-room/repo'
SCRIPT = ROOT / 'scripts/control_room.py'
START = ROOT / 'skills/coordinators/start.py'

BENCH_NEXT = """
## Handoff and memory

- Blocker: none.
- Next action: review PR #7 for A01. Then dispatch B01 from the worktree
  `../pantry-B01`. After that, plan B02.
"""
BENCH = ("Coordinate the bench track. Read docs/program.md and docs/tracks/bench/plan.md, then do the plan's next step. "
         "You own only that track's plan and task files; the program session owns everything else. "
         "Refresh and publish the control room before you report anything. "
         "Next action in the plan: review PR #7 for A01. Then dispatch B01 from the worktree ../pantry-B01.")
WIDGETS = ("Coordinate the widgets track. Read docs/program.md and docs/tracks/widgets/plan.md, then do the plan's next step. "
           "You own only that track's plan and task files; the program session owns everything else. "
           "Refresh and publish the control room before you report anything. "
           "Next action in the plan: dispatch W02.")


def stub(bin_dir: Path, name: str, code: int = 0, err: str = ''):
    """A command that appends its arguments, one per line, to <bin>/<name>.calls and exits `code`."""
    log = bin_dir / f'{name}.calls'
    (bin_dir / name).write_text(
        '#!/bin/sh\n'
        f'for a in "$@"; do printf "%s\\n" "$a" >> {shlex.quote(str(log))}; done\n'
        f'printf "%s\\n" "--" >> {shlex.quote(str(log))}\n'
        + (f'echo {shlex.quote(err)} >&2\n' if err else '') + f'exit {code}\n', encoding='utf-8')
    (bin_dir / name).chmod(0o755)


def calls(bin_dir: Path, name: str) -> list[list[str]]:
    log = bin_dir / f'{name}.calls'
    if not log.is_file():
        return []
    return [c.strip('\n').split('\n') for c in log.read_text(encoding='utf-8').split('--\n') if c.strip()]


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.proj = d / 'pantry'
        shutil.copytree(REPO, self.proj)
        plan = self.proj / 'docs/tracks/bench/plan.md'
        plan.write_text(plan.read_text(encoding='utf-8').replace('\n## Closure', BENCH_NEXT + '\n## Closure'), encoding='utf-8')
        task = self.proj / 'docs/tracks/widgets/tasks/W01-list-model.md'  # W01 done: W02 is ready to dispatch
        task.write_text(task.read_text(encoding='utf-8').replace('- State: active', '- State: done'), encoding='utf-8')
        subprocess.run(['git', 'init', '-q', str(self.proj)], check=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
        self.bin = d / 'bin'
        self.bin.mkdir()
        stub(self.bin, 'claude')

    def prompt_file(self, slug):
        return self.proj.resolve() / '.git/foreman/prompts' / f'{slug}.txt'

    def typed(self, slug):
        """What the starter types: claude with the session's name, reading the prompt file."""
        return f'claude --name {shlex.quote(slug + " (PM)")} "$(cat {shlex.quote(str(self.prompt_file(slug)))})"'

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, *args, code=0, **env_over):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('GIT_') and k not in ('TMUX', 'FOREMAN_TERMINAL', 'CLAUDE_CODE_REMOTE', 'TERM_PROGRAM')}
        env['PATH'] = f'{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin'
        env.update(env_over)
        r = subprocess.run([sys.executable, '-I', *map(str, args)], cwd=self.proj, env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, code, r.stderr)
        return r.stdout if code == 0 else r.stderr

    def start(self, *args, **env):
        return self.run_py(START, '--root', '.', *args, **env)

    def test_program_brief_names_the_coordinators_to_start(self):
        b = self.run_py(SCRIPT, 'brief', 'program', '--root', '.')
        section = b.split('## Coordinators to start\n', 1)[1].split('\n\n', 1)[0].splitlines()
        self.assertIn('never a subagent of this one', section[0])
        self.assertEqual(section[1:], [f'- {BENCH}', f'- {WIDGETS}'])  # `old` is complete: no prompt
        self.assertNotIn('Coordinate the old track', b)

    def test_brief_says_none_when_no_track_has_a_next_action(self):
        b = self.run_py(SCRIPT, 'brief', 'program', '--root', str(REPO))
        self.assertIn('## Coordinators to start\n', b)
        self.assertIn('- none: no active track has a next action\n', b)

    def test_the_project_line_from_the_program_file_wins(self):
        (self.proj / 'docs/pm.md').write_text(
            '# Program\n\nPaste: `Coordinate the <slug> track. Read docs/tracks/<slug>/plan.md first.`\n', encoding='utf-8')
        cfg = self.proj / 'foreman.json'
        cfg.write_text(cfg.read_text(encoding='utf-8').replace('{\n', '{\n  "program": "docs/pm.md",\n', 1), encoding='utf-8')
        out = self.start(FOREMAN_TERMINAL='none')
        self.assertIn('\nCoordinate the bench track. Read docs/tracks/bench/plan.md first. Next action in the plan: review PR #7 for A01.', out)
        b = self.run_py(SCRIPT, 'brief', 'program', '--root', '.')
        self.assertIn('Read first: docs/pm.md, ', b)

    def test_without_a_terminal_it_says_so_in_one_line_and_prints_the_prompts(self):
        stub(self.bin, 'osascript')
        stub(self.bin, 'tmux')
        out = self.start(FOREMAN_TERMINAL='none', TMUX='/tmp/x')
        lines = out.split('\n')
        self.assertTrue(lines[0].startswith('Could not start the coordinator sessions (FOREMAN_TERMINAL is none); paste each prompt'), lines[0])
        self.assertEqual(out, f'{lines[0]}\n\n{BENCH}\n\n{WIDGETS}\n')  # nothing else
        self.assertEqual((calls(self.bin, 'osascript'), calls(self.bin, 'tmux'), calls(self.bin, 'claude')), ([], [], []))

    def test_a_cloud_session_does_not_try(self):
        stub(self.bin, 'osascript')
        out = self.start(CLAUDE_CODE_REMOTE='true')
        self.assertIn('(this is a cloud session, with no terminal to open)', out.split('\n')[0])
        self.assertEqual(calls(self.bin, 'osascript'), [])

    def test_refused_automation_prints_the_prompts(self):
        stub(self.bin, 'osascript', 1, 'execution error: Not authorised to send Apple events to Terminal. (-1743)')
        out = self.start(FOREMAN_TERMINAL='terminal')
        first, rest = out.split('\n', 1)
        self.assertEqual(first, 'Could not start the coordinator sessions (osascript said: execution error: Not authorised to send '
                                f'Apple events to Terminal. (-1743)); paste each prompt below into a new Claude Code session in {self.proj.resolve()}.')
        self.assertEqual(rest, f'\n{BENCH}\n\n{WIDGETS}\n')
        self.assertEqual(len(calls(self.bin, 'osascript')), 1)  # it stops at the first refusal

    def test_terminal_opens_one_window_per_track_running_claude_with_the_prompt(self):
        stub(self.bin, 'osascript')
        out = self.start(FOREMAN_TERMINAL='terminal')
        self.assertEqual(out, 'Started the bench coordinator in a new Terminal window.\n'
                              'Started the widgets coordinator in a new Terminal window.\n')
        made = calls(self.bin, 'osascript')
        self.assertEqual(len(made), 2)
        root = shlex.quote(str(self.proj.resolve()))
        self.assertEqual([c[-1] for c in made], [f'cd {root} && {self.typed("bench")}', f'cd {root} && {self.typed("widgets")}'])
        self.assertIn('tell application "Terminal"', made[0])
        self.assertEqual(self.prompt_file('bench').read_text(encoding='utf-8'), BENCH)
        self.assertEqual(self.prompt_file('widgets').read_text(encoding='utf-8'), WIDGETS)
        # the shell gives claude the name and the file's text, each as one argument
        out = subprocess.run(['bash', '-c', made[0][-1].replace(' claude ', ' printf "%s\\n" ', 1)], capture_output=True, text=True).stdout
        self.assertEqual(out, f'--name\nbench (PM)\n{BENCH}\n')

    def test_one_track_and_iterm(self):
        stub(self.bin, 'osascript')
        out = self.start('--track', 'widgets', TERM_PROGRAM='iTerm.app', FOREMAN_TERMINAL='iterm')
        self.assertEqual(out, 'Started the widgets coordinator in a new iTerm2 window.\n')
        made = calls(self.bin, 'osascript')
        self.assertIn('tell application "iTerm"', made[0])
        self.assertTrue(made[0][-1].endswith(self.typed('widgets')))

    def test_inside_tmux_it_opens_a_tmux_window(self):
        stub(self.bin, 'tmux')
        stub(self.bin, 'osascript')
        out = self.start('--track', 'bench', TMUX='/tmp/tmux-1/default,1,0')
        self.assertEqual(out, 'Started the bench coordinator in a new tmux window.\n')
        self.assertEqual(calls(self.bin, 'tmux'), [['new-window', '-c', str(self.proj.resolve()), '-n', 'bench', self.typed('bench')]])
        self.assertEqual(self.prompt_file('bench').read_text(encoding='utf-8'), BENCH)
        self.assertEqual(calls(self.bin, 'osascript'), [])

    def test_a_later_failure_prints_only_the_prompts_left(self):
        (self.bin / 'osascript').write_text(  # the first call opens a window, the second is refused
            f'#!/bin/sh\n[ -f {self.bin}/once ] && {{ echo "boom" >&2; exit 1; }}\ntouch {self.bin}/once\n', encoding='utf-8')
        (self.bin / 'osascript').chmod(0o755)
        out = self.start(FOREMAN_TERMINAL='terminal')
        lines = out.split('\n')
        self.assertEqual(lines[0], 'Started the bench coordinator in a new Terminal window.')
        self.assertTrue(lines[1].startswith('Could not start the coordinator session (osascript said: boom)'), lines[1])
        self.assertEqual(lines[2:], ['', WIDGETS, ''])

    def test_a_long_prompt_goes_through_a_file_and_the_typed_command_stays_short(self):
        stub(self.bin, 'osascript')
        line = BENCH.split(' Next action')[0]
        long = ' '.join(['Decision D9 reopened the bench track; plan the next step — “ü” included.'] * 60)[:4000 - len(line) - 2] + '.'
        prompt = f'{line} {long}'
        self.assertEqual(len(prompt), 4000)
        self.start('--track', 'bench', '--next', long, FOREMAN_TERMINAL='terminal')
        typed = calls(self.bin, 'osascript')[0][-1]
        self.assertLess(len(typed.encode('utf-8')), 1024)
        self.assertEqual(self.prompt_file('bench').read_bytes(), prompt.encode('utf-8'))  # byte for byte

    def test_next_prompts_a_complete_track(self):
        self.assertIn('No coordinator to start', self.start('--track', 'old', FOREMAN_TERMINAL='none'))  # complete: skipped
        out = self.start('--track', 'old', '--next', 'Decision D7 reopened this track. Plan the fix  and dispatch it.', FOREMAN_TERMINAL='none')
        self.assertEqual(out.split('\n')[2:], [
            "Coordinate the old track. Read docs/program.md and docs/tracks/old/plan.md, then do the plan's next step. "
            "You own only that track's plan and task files; the program session owns everything else. "
            "Refresh and publish the control room before you report anything. "
            "Decision D7 reopened this track. Plan the fix and dispatch it.", ''])
        stub(self.bin, 'osascript')
        self.assertEqual(self.start('--track', 'old', '--next', 'Go.', FOREMAN_TERMINAL='terminal'),
                         'Started the old coordinator in a new Terminal window.\n')
        self.assertTrue(self.prompt_file('old').read_text(encoding='utf-8').endswith('anything. Go.'))

    def test_next_needs_exactly_one_track(self):
        self.assertIn('--next needs exactly one --track', self.run_py(START, '--root', '.', '--next', 'Go.', code=2))
        self.assertIn('--next needs exactly one --track', self.run_py(START, '--root', '.', '--track', 'old', 'bench', '--next', 'Go.', code=2))
        self.assertIn("no track 'nope'", self.run_py(START, '--root', '.', '--track', 'nope', '--next', 'Go.', code=2))

    def bg_claude(self, refuse=False):
        """A claude that names --bg in its help, records each start and prints an id (or refuses --bg)."""
        log = shlex.quote(str(self.bin / 'claude.calls'))
        (self.bin / 'claude').write_text(
            '#!/bin/sh\n[ "$1" = --help ] && { echo "  --bg, --background  Start the session in the background"; exit 0; }\n'
            f'for a in "$@"; do printf "%s\\n" "$a" >> {log}; done\nprintf "%s\\n" "--" >> {log}\n'
            + ('echo "unknown option --bg" >&2; exit 1\n' if refuse else 'echo "backgrounded · 1a2b3c4d · $3"\n'), encoding='utf-8')

    def test_background_is_the_default_when_claude_has_bg(self):
        self.bg_claude()
        stub(self.bin, 'osascript')
        out = self.start('--track', 'bench')
        self.assertEqual(out, 'Started the bench coordinator in the background, id 1a2b3c4d.\n'
                              '  claude attach 1a2b3c4d   open it in a terminal\n'
                              '  claude logs 1a2b3c4d     its recent output\n')
        self.assertEqual(calls(self.bin, 'claude'), [['--bg', '--name', 'bench (PM)', BENCH]])
        self.assertEqual(calls(self.bin, 'osascript'), [])

    def test_a_refused_bg_falls_back_to_a_terminal(self):
        self.bg_claude(refuse=True)
        stub(self.bin, 'osascript')
        out = self.start('--track', 'bench')
        self.assertEqual(out, 'Started the bench coordinator in a new Terminal window.\n')
        self.assertEqual(len(calls(self.bin, 'osascript')), 1)

    def test_the_background_command_stays_short_and_names_the_prompt_file(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('foreman_start', START)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.bg_claude()
        long = ' '.join(['Decision D9 reopened the bench track; plan the next step.'] * 80)[:3600].strip() + '.'
        self.assertIn('id 1a2b3c4d', self.start('--track', 'bench', '--next', long))
        f = self.prompt_file('bench')
        self.assertEqual(calls(self.bin, 'claude')[0][-1], f.read_text(encoding='utf-8'))  # claude got the whole file
        self.assertGreater(len(f.read_text(encoding="utf-8")), 3800)
        cmd = mod.command('background', self.proj.resolve(), 'bench', f)
        self.assertEqual(cmd[:2], ['sh', '-c'])
        self.assertEqual(cmd[2], f'claude --bg --name {shlex.quote("bench (PM)")} "$(cat {shlex.quote(str(f))})"')
        self.assertLess(len(cmd[2].encode('utf-8')), 1024)  # whatever the prompt's length: it stays in the file

    def test_the_skill_never_starts_a_subagent(self):
        skill = (ROOT / 'skills/coordinators/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('Never start one with the Agent tool', skill)
        self.assertNotIn('Agent(', START.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
