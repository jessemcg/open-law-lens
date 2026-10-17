"""Real local PTYs and fake downloads; never contact a repository or provision."""
import contextlib
import io
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_source_installer import ROOT, InstallerSandbox, m


def terminal_process(command, env, replies=(), timeout=10):
    pid, master = pty.fork()
    if pid == 0:
        os.execve('/bin/bash', ['/bin/bash', '-c', command], env)
    output = b''; pending = list(replies); deadline = time.monotonic() + timeout
    status = None
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                try: chunk = os.read(master, 65536)
                except OSError: break
                if not chunk: break
                output += chunk
            if pending and pending[0][0].encode() in output:
                _, response = pending.pop(0); os.write(master, response)
            waited, value = os.waitpid(pid, os.WNOHANG)
            if waited:
                status = value
                # Drain terminal output after exit.
                while select.select([master], [], [], 0.05)[0]:
                    try: output += os.read(master, 65536)
                    except OSError: break
                break
        else:
            raise AssertionError(f'Terminal timed out: {output.decode(errors="replace")}')
    finally:
        os.close(master)
        if status is None:
            waited, status = os.waitpid(pid, os.WNOHANG)
            if not waited:
                os.kill(pid, signal.SIGKILL); _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), output.decode(errors='replace')


class TerminalTests(InstallerSandbox):
    def test_presentation_plain_styled_ascii_and_truthful_progress(self):
        class Terminal(io.StringIO):
            encoding = 'utf-8'
            def isatty(self): return True
        with patch.dict(os.environ, TERM='xterm-256color'):
            t = Terminal()
            for i in range(1, 9):
                self.assertIn(f'{i-1}/8 stages passed', m.status_text('CHECK', f'{i}/8 Stage', t))
            self.assertIn('8/8 stages passed', m.status_text('OK', m.INSTALL_SUCCESS, t))
            self.assertNotIn('stages passed', m.status_text('FAIL', 'Stopped', t))
            t.encoding = 'ascii'; m.status_text('CHECK', '3/8 Native', t).encode('ascii')
            for env in ({'NO_COLOR': ''}, {'TERM': 'dumb'}):
                with patch.dict(os.environ, env): self.assertEqual(m.status_text('OK', 'Ready', t), '[OK] Ready')
            self.assertEqual(m.status_text('OK', 'Ready', io.StringIO()), '[OK] Ready')

    def test_real_controlling_terminal_enter_exact_skip_eof_interrupt(self):
        module = str(ROOT / 'scripts/open_law_lens_maintenance.py')
        for function, response, expected in [('approve', b'\n', 0), ('approve', b'x\n', 1),
            ('optional', b'\n', 0), ('optional', b'skip\n', 2), ('optional', b'\x04', 1), ('optional', b'\x03', -2)]:
            code = f"import runpy; m=runpy.run_path({module!r}); "
            code += "m['approve']('Synthetic path approval','')" if function == 'approve' else "raise SystemExit(0 if m['continue_pi_install']() else 2)"
            command = shlex.join([sys.executable, '-c', code])
            status, output = terminal_process(command, dict(os.environ, TERM='xterm-256color'), [('Press Enter', response)])
            with self.subTest(function=function, response=response):
                # Unhandled SIGINT is Python exit 130 on some versions, -SIGINT on others.
                self.assertIn(status, (expected, 130) if response == b'\x03' else (expected,))
                self.assertIn('Press Enter', output)

    def test_full_synthetic_terminal_lifecycle_pi_and_package_offers(self):
        command = shlex.join([sys.executable, '-B', str(ROOT / 'tests/preview_source_install.py')])
        replies = [('Press Enter to continue', b'\n'), ('Install the previewed native', b'\n'),
                   ('Press Enter to install Pi,', b'\n'), ('Press Enter to install pi-web-access,', b'\n'),
                   ('Press Enter to install @agent-sh/computer-use-linux,', b'\n'),
                   ('Synthetic preview finished.', b'\n')]
        status, text = terminal_process(command, dict(os.environ, TERM='xterm-256color'), replies)
        self.assertEqual(status, 0, text)
        self.assertIn('SYNTHETIC ACCEPTANCE: application phase=complete', text)
        success = text.index(m.INSTALL_SUCCESS)
        for offer in ('Press Enter to install Pi,', 'Press Enter to install pi-web-access,', 'Press Enter to install @agent-sh/computer-use-linux,'):
            self.assertLess(success, text.index(offer))
        self.assertIn('8/8 stages passed', text)
        self.assertIn('0.0.0-synthetic', text)

    def test_short_command_template_and_readme_agree(self):
        command = subprocess.check_output([sys.executable, str(ROOT / 'scripts/print-install-command.py')], text=True).strip()
        self.assertEqual(command, 'curl -fsSL https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh | bash')
        self.assertIn(command, (ROOT / 'README.md').read_text())
        self.assertEqual((ROOT / 'scripts/install-bootstrap.sh').read_bytes(), (ROOT / 'scripts/download-bootstrap.sh.in').read_bytes())
        self.assertLessEqual(len((ROOT / 'README.md').read_text().splitlines()), 110)
        self.assertIn('GNU GENERAL PUBLIC LICENSE', (ROOT / 'LICENSE').read_text())
        self.assertIn('Version 3, 29 June 2007', (ROOT / 'LICENSE').read_text())

    def test_current_readme_and_detailed_document_local_links(self):
        import re
        for relative in ('README.md', 'docs/source-install.md', 'docs/user-guide.md', 'docs/development.md', 'docs/source-install-validation.md', 'docs/portability.md'):
            document = ROOT / relative
            for target in re.findall(r'\]\(([^)]+)\)', document.read_text()):
                if '://' in target or target.startswith('#'): continue
                target = target.split('#', 1)[0]
                with self.subTest(document=relative, target=target):
                    self.assertTrue((document.parent / target).exists())

    def test_download_first_failure_partial_args_and_cleanup(self):
        for downloader in ('curl', 'wget'):
            for download_status, child_status in ((7, 0), (0, 0), (0, 17)):
                with self.subTest(downloader=downloader, download=download_status):
                    binary = self.home / downloader
                    binary.write_text(f'''#!{sys.executable}
import os,sys
from pathlib import Path
args=sys.argv[1:]; p=Path(args[args.index({'-o' if downloader == 'curl' else '-O'!r})+1])
Path(os.environ['RECORD']).write_text(str(p))
p.write_text('printf "%s\\\\n" "$@" > "$EXECUTED"\\nexit {child_status}\\n')
sys.exit({download_status})
'''); binary.chmod(0o755)
                    record = self.home / 'record'; executed = self.home / 'executed'; executed.unlink(missing_ok=True)
                    command = subprocess.check_output([sys.executable, str(ROOT / 'scripts/print-install-command.py'), '--download-first', '--downloader', downloader], text=True).strip()
                    env = dict(os.environ, PATH=str(self.home)+':/usr/bin:/bin', RECORD=str(record), EXECUTED=str(executed), TMPDIR=str(self.home))
                    result = subprocess.run(['/bin/bash', '-c', command + ' --source-dir "synthetic space"'], env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, download_status or child_status, result.stderr)
                    self.assertFalse(Path(record.read_text()).exists())
                    self.assertEqual(executed.exists(), not bool(download_status))
                    if executed.exists(): self.assertEqual(executed.read_text().splitlines(), ['--source-dir', 'synthetic space'])

    def test_real_piped_bootstrap_hands_off_tty_and_never_executes_failed_download(self):
        for failure in (False, True):
            marker = self.home / 'executed'; marker.unlink(missing_ok=True)
            curl = self.home / 'curl'
            curl.write_text(f'''#!{sys.executable}
import os,sys
from pathlib import Path
a=sys.argv[1:]; p=Path(a[a.index('-o')+1])
p.write_text(''' + repr('''#!/bin/bash
read -r value </dev/tty
printf '%s\\n' "$@" > "$EXECUTED"
[ -t 0 ] && [ "$value" = approved ] || exit 9
exit 17
''') + f''')
sys.exit({22 if failure else 0})
'''); curl.chmod(0o755)
            env = dict(os.environ, PATH=str(self.home)+':/usr/bin:/bin', EXECUTED=str(marker))
            # The script really comes through a pipe, not a normal script file stdin.
            command = f"/bin/cat {shlex.quote(str(ROOT / 'scripts/install-bootstrap.sh'))} | bash -s -- --source-dir 'synthetic source'"
            status, text = terminal_process(command, env, [('Starting Open Law Lens setup.', b'approved\n')] if not failure else [])
            self.assertEqual(status, 22 if failure else 17, text)
            self.assertEqual(marker.exists(), not failure)
            if marker.exists(): self.assertEqual(marker.read_text().splitlines(), ['--source-dir', 'synthetic source'])


class OptionalPiTests(InstallerSandbox):
    def test_existing_pi_no_reinstall_no_package_updates(self):
        agent = self.home / '.pi/agent'; env = m.desktop_environment(self.paths, {'pi_agent_dir': str(agent)})
        for name in ('pi-web-access', '@agent-sh/computer-use-linux'):
            path = agent / 'npm/node_modules' / name; path.mkdir(parents=True)
            (path / 'package.json').write_text(json.dumps({'name': name, 'version': '1.2.3'}))
        with patch.object(m, 'discover_pi', return_value=['/fixture/pi']), patch.object(m, 'continue_pi_install', side_effect=AssertionError('Existing installation prompted')), patch.object(m, 'install_optional_pi', side_effect=AssertionError('Reinstalled Pi')), contextlib.redirect_stdout(io.StringIO()):
            m.offer_pi_install(self.paths, self.data, lambda: None, env)
        self.assertEqual(self.data['optional_setup']['pi'], 'existing')
        self.assertEqual(self.data['optional_setup']['pi-web-access']['version'], '1.2.3')

    def test_package_fixture_argv_neutral_cwd_user_scope_and_complete_receipt(self):
        agent = self.home / '.pi/agent'; env = m.desktop_environment(self.paths, {'pi_agent_dir': str(agent)})
        pi = self.home / 'pi'; record = self.home / 'record'
        pi.write_text(f'''#!{sys.executable}
import os,sys,json
from pathlib import Path
with Path({str(record)!r}).open('a') as f: f.write(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd()}})+'\\n')
'''); pi.chmod(0o755)
        master, slave = os.openpty(); self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        original_open = open
        def open_tty(path, *args, **kwargs):
            return os.fdopen(os.dup(slave), 'r+b', buffering=0) if path == '/dev/tty' else original_open(path, *args, **kwargs)
        with patch.object(m, 'discover_pi', side_effect=[[], [str(pi)]]), patch.object(m, 'continue_pi_install', return_value=True), patch.object(m, 'install_optional_pi') as install, patch('builtins.open', side_effect=open_tty), contextlib.redirect_stdout(io.StringIO()):
            m.offer_pi_install(self.paths, self.data, lambda: self.assertEqual(self.data['phase'], 'complete'), env)
        install.assert_called_once()
        records = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual([r['args'] for r in records], [['install', 'npm:pi-web-access'], ['install', 'npm:@agent-sh/computer-use-linux']])
        self.assertTrue(all(r['cwd'] != str(self.paths['source']) and not Path(r['cwd']).exists() for r in records))
        self.assertEqual(self.data['phase'], 'complete')

    def test_skips_cancellation_discovery_and_package_failure_keep_complete(self):
        env = m.desktop_environment(self.paths, {})
        for error in (KeyboardInterrupt(), OSError('network'), ValueError('discovery')):
            with self.subTest(error=error), patch.object(m, 'discover_pi', side_effect=error), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(type(error)):
                m.offer_pi_install(self.paths, self.data, lambda: None, env)
            self.assertEqual(self.data['phase'], 'complete')
        with patch.object(m, 'discover_pi', return_value=[]), patch.object(m, 'continue_pi_install', return_value=False), patch.object(m, 'install_optional_pi') as install, contextlib.redirect_stdout(io.StringIO()):
            m.offer_pi_install(self.paths, self.data, lambda: None, env)
        install.assert_not_called()

    def test_package_failure_continues_to_next_offer_without_downgrading_app(self):
        env = m.desktop_environment(self.paths, {})
        master, slave = os.openpty(); self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        original_open = open
        def open_tty(path, *args, **kwargs):
            return os.fdopen(os.dup(slave), 'r+b', buffering=0) if path == '/dev/tty' else original_open(path, *args, **kwargs)
        outcomes = [subprocess.CalledProcessError(7, 'fixture'), subprocess.CompletedProcess([], 0)]
        with patch.object(m, 'discover_pi', return_value=['/fixture/pi']), patch.object(m, 'continue_pi_install', return_value=True), patch('builtins.open', side_effect=open_tty), patch.object(m.subprocess, 'run', side_effect=outcomes), contextlib.redirect_stdout(io.StringIO()):
            m.offer_pi_install(self.paths, self.data, lambda: None, env)
        self.assertEqual(self.data['phase'], 'complete')
        self.assertEqual(self.data['optional_setup']['pi-web-access']['status'], 'failed')
        self.assertEqual(self.data['optional_setup']['@agent-sh/computer-use-linux']['status'], 'not discovered')

    def test_configured_custom_packages_are_retained(self):
        agent = self.home / '.pi/agent'; agent.mkdir(parents=True)
        (agent / 'settings.json').write_text(json.dumps({'packages': [{'source': 'npm:pi-web-access@1.0.0', 'extensions': []}]}))
        self.assertEqual(m.package_version(agent, 'pi-web-access'), 'configured (retained)')
        git = agent / 'git/github.com/synthetic/computer-use-custom'; git.mkdir(parents=True)
        (git / 'package.json').write_text(json.dumps({'name': '@agent-sh/computer-use-linux', 'version': '0.4.9-custom'}))
        self.assertEqual(m.package_version(agent, '@agent-sh/computer-use-linux'), '0.4.9-custom')

    def test_failed_official_download_is_not_executed(self):
        with patch.object(m, 'execute', side_effect=m.MaintenanceError('failed partial download')), patch.object(m.subprocess, 'run') as run, self.assertRaises(m.MaintenanceError):
            m.install_optional_pi({})
        run.assert_not_called()


if __name__ == '__main__': unittest.main()
