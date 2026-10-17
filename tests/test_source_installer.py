"""Public lifecycle tests: temporary HOME/XDG/Git, no native provisioning or Pi calls."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oll_maintenance", ROOT / "scripts/open_law_lens_maintenance.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class InstallerSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="oll-install-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home space '$literal%`"; self.home.mkdir(mode=0o700)
        env = dict(os.environ, HOME=str(self.home))
        for key in tuple(env):
            if key.startswith(("XDG_", "OPEN_LAW_LENS_", "PI_", "UV_")):
                env.pop(key)
        self.environment = self.enterContext(patch.dict(os.environ, env, clear=True))
        mask = os.umask(0o077); self.addCleanup(os.umask, mask)
        self.paths = m.layout(self.home / "Open Law Lens source")
        self.data = {"schema": 1, "installation_id": "a" * 32, "phase": "complete",
                     "paths": {k: str(p) for k, p in self.paths.items()}, "created": [], "files": {},
                     "tool_versions": {}, "introduced_packages": [], "package_family": "apt", "config_created": False}
        self.args = argparse.Namespace(source_dir=str(self.paths['source']), dry_run=False, resume=False, repair=False)
        self.removal = argparse.Namespace(dry_run=False, purge=False, cleanup_packages=False)

    def fixture_install(self):
        repo = self.root / "remote"; repo.mkdir()
        for name in ("pyproject.toml", "uv.lock", "open-law-lens-icon.svg", "open-law-lens-icon-symbolic.svg", "open-law-lens-icon.png"):
            shutil.copyfile(ROOT / name, repo / name)
        shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        (repo / ".pi").mkdir(); shutil.copyfile(ROOT / ".pi/SYSTEM.md", repo / ".pi/SYSTEM.md")
        for argv in (["init", "-q", "--initial-branch=main"], ["add", "."],
                     ["-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"]):
            subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
        self.enterContext(patch.object(m, 'REPOSITORY', str(repo)))
        self.enterContext(patch.object(m, 'detect_platform', return_value='apt'))
        self.enterContext(patch.object(m, 'approve'))
        self.enterContext(patch.object(m, 'native_meets', return_value=True))
        self.enterContext(patch.object(m, 'active_processes', return_value=[]))
        self.enterContext(patch.object(m, 'refresh_caches'))
        self.enterContext(patch.object(m.Packages, 'snapshot', return_value={'git', 'curl'}))
        self.enterContext(patch.object(m.Packages, 'missing', return_value=[]))
        self.enterContext(patch.object(m.Packages, 'install'))
        self.enterContext(patch.object(m, 'verify_environment', return_value={}))
        self.enterContext(patch.object(m, 'discover_pi', return_value=[]))
        self.enterContext(patch.object(m, 'continue_pi_install', return_value=False))
        self.calls = []
        original = m.execute
        def execute(command, **kwargs):
            self.calls.append(command)
            if command[0] in {'git', 'desktop-file-validate'}:
                return original(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, '', '')
        self.execute_fixture = execute
        self.enterContext(patch.object(m, 'execute', side_effect=execute))
        def sync(paths, data, save, dev=False):
            m.say('CHECK', '5/8 uv and managed Python'); m.say('CHECK', '6/8 Locked editable Python dependencies')
            for name in ('environment', 'python', 'tools', 'cache'):
                if not paths[name].exists():
                    paths[name].mkdir(parents=True)
                    m.marker(paths[name], data['installation_id'], paths['source'])
                    data['created'].append(name)
            save()
        self.enterContext(patch.object(m, 'synchronize', side_effect=sync))
        return repo

    def install_quietly(self):
        with contextlib.redirect_stdout(io.StringIO()) as stream:
            result = m.install(self.args)
        return result, stream.getvalue()

    def receipt(self):
        return m.private_json(self.paths['state'] / 'receipt.json')


class PlatformTests(unittest.TestCase):
    def test_supported_platforms(self):
        for release, family in [({'ID': 'ubuntu', 'VERSION_ID': '24.04'}, 'apt'),
                                ({'ID': 'ubuntu', 'VERSION_ID': '26.04'}, 'apt'),
                                ({'ID': 'linuxmint', 'ID_LIKE': 'ubuntu debian', 'UBUNTU_CODENAME': 'noble'}, 'apt'),
                                ({'ID': 'fedora', 'VERSION_ID': '43'}, 'dnf'),
                                ({'ID': 'fedora', 'VERSION_ID': '44'}, 'dnf')]:
            for arch in ('x86_64', 'aarch64'):
                with self.subTest(release=release, arch=arch):
                    self.assertEqual(m.detect_platform(release, arch, False), family)

    def test_rejections(self):
        for release, arch, immutable in [({'ID': 'ubuntu', 'VERSION_ID': '22.04'}, 'x86_64', False),
            ({'ID': 'ubuntu', 'VERSION_ID': '22.04', 'UBUNTU_CODENAME': 'noble'}, 'x86_64', False),
            ({'ID': 'fedora', 'VERSION_ID': '44'}, 'armv7', False),
            ({'ID': 'fedora', 'VERSION_ID': '44'}, 'x86_64', True),
            ({'ID': 'fedora', 'VARIANT_ID': 'silverblue', 'VERSION_ID': '44'}, 'x86_64', False),
            ({'ID': 'debian', 'VERSION_ID': '13'}, 'x86_64', False)]:
            with self.subTest(release=release), self.assertRaises(m.MaintenanceError):
                m.detect_platform(release, arch, immutable)

    def test_packages_include_build_and_application_tools(self):
        self.assertTrue({'libffi-dev', 'libgirepository-2.0-dev', 'libcairo2-dev', 'pandoc', 'poppler-utils', 'wl-clipboard', 'xclip'}.issubset(m.PACKAGES['apt']))
        self.assertTrue({'cairo-devel', 'cairo-gobject-devel', 'glib2-devel', 'libffi-devel', 'vte291-gtk4'}.issubset(m.PACKAGES['dnf']))

    def test_package_transactions_fail_closed(self):
        for family, output in [('apt', 'Remv desktop [1.0]'), ('dnf', 'Removing:\n desktop x86_64 1.0\nTransaction Summary'), ('dnf', 'Error: No match for argument')]:
            def execute(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, 'Candidate: 1.0' if argv[0] == 'apt-cache' else output, '')
            with self.subTest(family=family), patch.object(m, 'execute', side_effect=execute), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(m.MaintenanceError):
                m.Packages(family).preview(['git'])
        with patch.object(m, 'execute', return_value=subprocess.CompletedProcess([], 0, 'Candidate: (none)', '')), self.assertRaises(m.MaintenanceError):
            m.Packages('apt').preview(['git'])

    def test_native_enter_approval_and_no_autoremove(self):
        with patch.object(m.Packages, 'preview'), patch.object(m, 'approve') as approval, patch.object(m, 'execute') as run:
            m.Packages('apt').install(['git'])
        self.assertEqual(approval.call_args.args[-1], '')
        self.assertEqual(run.call_args.args[0], ['sudo', 'apt-get', 'install', 'git'])


class OwnershipTests(InstallerSandbox):
    def test_installer_subdirectories_not_research_roots(self):
        for name in ('state', 'cache', 'maintenance'):
            self.assertEqual(self.paths[name].name, 'installer')
        self.assertEqual(self.paths['config'], self.home / '.config/open-law-lens')
        self.assertEqual(self.paths['environment'], self.home / '.local/share/uv/project-envs/OpenLawLens')

    def test_unsafe_roots_and_symlinks(self):
        link = self.home / 'link'; link.symlink_to(self.root, target_is_directory=True)
        for path in (Path('/'), self.home, self.home / '.local', link / 'checkout'):
            with self.subTest(path=path), self.assertRaises(m.MaintenanceError): m.layout(path)
        with patch.dict(os.environ, XDG_DATA_HOME='/tmp'), self.assertRaises(m.MaintenanceError): m.layout(self.paths['source'])

    def test_private_receipts_reject_malformed_permissions_and_hardlinks(self):
        receipt = self.paths['state'] / 'receipt.json'
        m.atomic_json(receipt, self.data)
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(m.private_json(receipt), self.data)
        for key, value in [('schema', 9), ('phase', 'pi'), ('created', ['alien']), ('files', {'command': 'bad'}), ('paths', {})]:
            with self.subTest(key=key), self.assertRaises(m.MaintenanceError):
                m.validate_receipt(dict(self.data, **{key: value}), self.paths)
        receipt.chmod(0o644)
        with self.assertRaises(m.MaintenanceError): m.private_json(receipt)
        receipt.chmod(0o600); os.link(receipt, receipt.with_suffix('.linked'))
        with self.assertRaises(m.MaintenanceError): m.atomic_json(receipt, self.data)

    def test_concurrent_and_unsafe_locks(self):
        with m.lock(self.paths['state']):
            with self.assertRaises(m.MaintenanceError):
                with m.lock(self.paths['state']): pass
        lock = self.paths['state'] / 'maintenance.lock'; lock.write_text('foreign')
        with self.assertRaises(m.MaintenanceError):
            with m.lock(self.paths['state']): pass

    def test_atomic_publication_intent_is_resumable(self):
        target = self.paths['command']
        m.owned_file('command', target, b'first', self.data, lambda: None)
        original = m.os.replace
        with patch.object(m.os, 'replace', side_effect=OSError('interrupted')), self.assertRaises(OSError):
            m.owned_file('command', target, b'next', self.data, lambda: None)
        self.assertEqual(target.read_bytes(), b'first')
        self.assertFalse(list(target.parent.glob('.open-law-lens-*')))
        m.owned_file('command', target, b'next', self.data, lambda: None)
        self.assertEqual(target.read_bytes(), b'next')

    def test_modified_and_unowned_collisions(self):
        for key in ('command', 'uninstall_command', 'desktop', 'svg', 'symbolic', 'png'):
            with self.subTest(key=key):
                target = self.paths[key]; target.parent.mkdir(parents=True, exist_ok=True); target.write_text('unowned')
                with self.assertRaises(m.MaintenanceError): m.owned_file(key, target, b'owned', self.data, lambda: None)
                target.unlink(); m.owned_file(key, target, b'owned', self.data, lambda: None)
                target.write_text('modified')
                with self.assertRaises(m.MaintenanceError): m.owned_file(key, target, b'repair', self.data, lambda: None)

    def test_source_and_dependency_binding(self):
        source = self.paths['source']; source.mkdir()
        (source / 'pyproject.toml').write_text('project'); (source / 'uv.lock').write_text('locked')
        environment = self.paths['environment']; environment.mkdir(parents=True)
        m.marker(environment, self.data['installation_id'], source)
        m.atomic_json(environment / 'open-law-lens-env.json', {'fingerprint': 'stale'})
        with self.assertRaisesRegex(m.MaintenanceError, 'Dependencies changed'): m.verify_environment(self.paths)
        m.marker(environment, self.data['installation_id'], source / 'foreign')
        with self.assertRaisesRegex(m.MaintenanceError, 'another checkout'): m.verify_environment(self.paths)

    def test_locked_sync_explicit_runtime_and_no_checkout_venv(self):
        source = self.paths['source']; source.mkdir()
        (source / 'pyproject.toml').write_text('project'); (source / 'uv.lock').write_text('locked')
        with patch.dict(os.environ, UV_PROJECT_ENVIRONMENT='/foreign', VIRTUAL_ENV='/foreign', UV_PYTHON='3.12'), patch.object(m, 'locate_uv', return_value='/uv'), patch.object(m, 'execute') as run, patch.object(m, 'verify_environment'), contextlib.redirect_stdout(io.StringIO()):
            m.synchronize(self.paths, self.data, lambda: None)
            m.synchronize(self.paths, self.data, lambda: None)
            m.validate_receipt(self.data, self.paths)
        sync = next(call for call in run.call_args_list if 'sync' in call.args[0])
        self.assertIn('--locked', sync.args[0]); self.assertIn('--managed-python', sync.args[0])
        self.assertEqual(sync.kwargs['env']['UV_PROJECT_ENVIRONMENT'], str(self.paths['environment']))
        self.assertNotIn('VIRTUAL_ENV', sync.kwargs['env']); self.assertNotIn('UV_PYTHON', sync.kwargs['env'])
        self.assertFalse((source / '.venv').exists())
        self.assertTrue(any('--record' in c.args[0] for c in run.call_args_list))


class LifecycleTests(InstallerSandbox):
    def test_install_repair_and_normal_removal_preserve_durable_data(self):
        self.fixture_install()
        durable = []
        for relative in ('.config/open-law-lens/config.json', '.local/share/open-law-lens/library/a.sqlite3',
                         '.local/share/open-law-lens/research/answer.json', '.local/share/open-law-lens/prior_briefs/brief.odt',
                         '.local/state/open-law-lens/agent-workspaces/session.jsonl', '.pi/agent/auth.json', 'external/document.pdf'):
            path = self.home / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('synthetic retained'); durable.append(path)
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertEqual(self.receipt()['phase'], 'complete')
        self.assertFalse((self.paths['source'] / 'config.json').exists())
        changed = self.paths['source'] / 'edited.txt'; changed.write_text('local edit')
        self.args.repair = True; self.calls.clear()
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertEqual(changed.read_text(), 'local edit')
        self.assertFalse(any(set(c) & {'clone', 'fetch', 'reset', 'clean', 'stash'} for c in self.calls))
        self.removal.dry_run = True
        with contextlib.redirect_stdout(io.StringIO()): m.uninstall(self.removal)
        self.assertTrue(self.paths['command'].exists())
        self.removal.dry_run = False
        with contextlib.redirect_stdout(io.StringIO()): m.uninstall(self.removal)
        self.assertFalse(self.paths['environment'].exists()); self.assertTrue(changed.exists())
        for path in durable: self.assertEqual(path.read_text(), 'synthetic retained')

    def test_clone_failure_remains_removable_and_resumable(self):
        self.fixture_install()
        def failed(command, **kwargs):
            if command[:2] == ['git', 'clone']: raise m.MaintenanceError('synthetic download failure')
            return self.execute_fixture(command, **kwargs)
        with patch.object(m, 'execute', side_effect=failed), self.assertRaises(m.MaintenanceError): self.install_quietly()
        self.assertFalse(self.paths['source'].exists()); self.assertTrue(self.paths['uninstall_command'].exists())
        self.assertTrue(self.paths['maintenance'].exists())
        self.args.resume = True
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertEqual(self.receipt()['phase'], 'complete')

    def test_dependency_failure_then_resume_preserves_source(self):
        self.fixture_install()
        with patch.object(m, 'synchronize', side_effect=m.MaintenanceError('build failed')), self.assertRaises(m.MaintenanceError): self.install_quietly()
        self.assertEqual(self.receipt()['phase'], 'environment')
        edited = self.paths['source'] / 'edit'; edited.write_text('keep')
        self.args.resume = True; self.args.source_dir = None
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertEqual(edited.read_text(), 'keep')

    def test_purge_eligible_source_and_maintenance_only(self):
        self.fixture_install(); self.install_quietly()
        self.removal.purge = True
        with contextlib.redirect_stdout(io.StringIO()): m.uninstall(self.removal)
        self.assertFalse(self.paths['source'].exists()); self.assertFalse(self.paths['state'].exists())
        self.assertTrue(self.paths['state'].parent.is_dir())
        self.assertTrue(self.paths['maintenance'].parent.is_dir())

    def test_purge_refuses_runtime_legal_documents_and_unowned_files(self):
        self.fixture_install(); self.install_quietly(); self.removal.purge = True
        for relative in ('library/a.sqlite3', 'research/answer.json', 'prior_briefs/brief.odt', 'session.jsonl', 'record.pdf', 'config.json'):
            path = self.paths['source'] / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('synthetic')
            with self.subTest(relative=relative), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(m.MaintenanceError, 'never purge'):
                m.uninstall(self.removal)
            path.unlink()
            if path.parent != self.paths['source']: path.parent.rmdir()
        foreign = self.paths['maintenance'] / 'foreign'; foreign.write_text('keep')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(m.MaintenanceError, 'Unowned maintenance'): m.uninstall(self.removal)
        self.assertEqual(foreign.read_text(), 'keep')

    def test_existing_maintained_environment_and_launchers_not_adopted(self):
        self.fixture_install()
        for key in ('environment', 'command', 'desktop'):
            path = self.paths[key]
            if key == 'environment': path.mkdir(parents=True); sentinel = path / 'private'
            else: path.parent.mkdir(parents=True, exist_ok=True); sentinel = path
            sentinel.write_text('maintained')
            with self.subTest(key=key), self.assertRaisesRegex(m.MaintenanceError, 'Unowned destination'): self.install_quietly()
            self.assertEqual(sentinel.read_text(), 'maintained')
            sentinel.unlink()
            if key == 'environment': path.rmdir()

    def test_root_and_active_process_guards(self):
        with patch.object(m.os, 'getuid', return_value=0), self.assertRaisesRegex(m.MaintenanceError, 'not root'): m.install(self.args)
        self.fixture_install(); self.install_quietly()
        with patch.object(m, 'active_processes', return_value=[123]), self.assertRaisesRegex(m.MaintenanceError, 'Close Open Law Lens'): m.uninstall(self.removal)

    def test_completion_precedes_any_optional_work_and_survives_all_failures(self):
        self.fixture_install()
        for failure in (OSError('network'), KeyboardInterrupt(), ValueError('discovery')):
            self.args.repair = (self.paths['state'] / 'receipt.json').exists()
            output = io.StringIO()
            def offer(*args):
                self.assertEqual(self.receipt()['phase'], 'complete')
                self.assertIn(m.INSTALL_SUCCESS, output.getvalue())
                self.assertTrue(self.paths['command'].exists())
                raise failure
            with self.subTest(failure=failure), patch.object(m, 'offer_pi_install', side_effect=offer), contextlib.redirect_stdout(output):
                self.assertEqual(m.install(self.args), 0)
            self.assertEqual(self.receipt()['phase'], 'complete')
            self.assertIn('remains installed', output.getvalue())

    def test_real_desktop_exec_preserves_metacharacter_path_and_app_argument(self):
        import time
        import gi
        gi.require_version('Gio', '2.0')
        from gi.repository import Gio
        self.fixture_install(); self.install_quietly()
        record = self.root / 'desktop-argv.json'
        # Replace only this synthetic launcher with a recorder to exercise GIO's
        # real Desktop Entry escaping, without launching the app or provisioning.
        self.paths['command'].write_text('#!/usr/bin/python3\nimport json,sys\nfrom pathlib import Path\n'
                                         f'Path({str(record)!r}).write_text(json.dumps(sys.argv))\n')
        info = Gio.DesktopAppInfo.new_from_filename(str(self.paths['desktop']))
        self.assertIsNotNone(info)
        self.assertTrue(info.launch([], None))
        deadline = time.monotonic() + 3
        while not record.exists() and time.monotonic() < deadline: time.sleep(0.02)
        self.assertEqual(json.loads(record.read_text()), [str(self.paths['command']), 'app'])

    def test_desktop_phase_launch_check_is_allowed_but_earlier_phases_block(self):
        self.fixture_install(); self.install_quietly()
        args = argparse.Namespace(operation='check', project=str(self.paths['source']), arguments=[])
        data = self.receipt()
        for phase in ('native', 'source', 'environment', 'uninstalled'):
            data['phase'] = phase; m.atomic_json(self.paths['state'] / 'receipt.json', data)
            with self.subTest(phase=phase), self.assertRaises(m.MaintenanceError): m.run_environment(args)
        data['phase'] = 'desktop'; m.atomic_json(self.paths['state'] / 'receipt.json', data)
        with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(m.run_environment(args), 0)

    def test_env_run_direct_no_provision_and_overrides_preserved(self):
        self.fixture_install(); self.install_quietly()
        binary = self.paths['environment'] / 'bin/open-law-lens'; binary.parent.mkdir(parents=True); binary.write_text('#!/bin/sh\n'); binary.chmod(0o755)
        cwd = Path.cwd(); self.addCleanup(os.chdir, cwd)
        with patch.dict(os.environ, OPEN_LAW_LENS_LIBRARY_DB='/explicit/library', VIRTUAL_ENV='/wrong'), patch.object(m.os, 'execve', side_effect=SystemExit(0)) as run, patch.object(m, 'synchronize', side_effect=AssertionError('launch provisioned')):
            with self.assertRaises(SystemExit): m.run_environment(argparse.Namespace(operation='run', project=str(self.paths['source']), arguments=['open-law-lens', 'app', 'space argument']))
        executable, argv, env = run.call_args.args
        self.assertEqual(executable, binary); self.assertEqual(argv[-1], 'space argument')
        self.assertEqual(env['OPEN_LAW_LENS_STORAGE'], 'standalone'); self.assertEqual(env['OPEN_LAW_LENS_LIBRARY_DB'], '/explicit/library')
        self.assertNotIn('VIRTUAL_ENV', env); self.assertEqual(env['UV_NO_SYNC'], '1')


if __name__ == '__main__': unittest.main()
