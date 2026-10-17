"""Standalone native runtime ownership/integrity; temporary HOME, no network/desktop."""
import contextlib
import io
import os
from pathlib import Path
from unittest.mock import patch

from test_source_installer import InstallerSandbox, m


class NativeComputerUseTests(InstallerSandbox):
    def prepare(self):
        self.fixture_install()
        m.synchronize(self.paths, self.data, lambda: None)

    def provision(self):
        with contextlib.redirect_stdout(io.StringIO()):
            m.provision_computer_use(self.paths, self.data, lambda: None)

    def test_release_assets_pinned_for_both_architectures(self):
        for arch in ('x86_64', 'aarch64'):
            assets = m.computer_use_assets(arch)
            self.assertEqual(set(assets), set(m.COMPUTER_USE_FILES))
            for key, (url, sha) in assets.items():
                self.assertEqual(url, f'https://github.com/agent-sh/computer-use-linux/releases/download/v0.7.18/{m.COMPUTER_USE_FILES[key]}-{arch}-unknown-linux-gnu')
                self.assertRegex(sha, r'^[0-9a-f]{64}$')
        with self.assertRaises(m.MaintenanceError): m.computer_use_assets('armv7')

    def test_three_verified_native_files_receipted_and_repair_does_not_download_again(self):
        self.prepare(); self.provision()
        m.validate_receipt(self.data, self.paths)
        for key in m.COMPUTER_USE_FILES:
            target = m.owned_target(key, self.paths)
            self.assertEqual(target.read_bytes(), self.asset_bytes[key])
            self.assertTrue(os.access(target, os.X_OK))
            self.assertEqual(self.data['files'][key], m.digest(target))
        self.assertEqual(self.data['tool_versions']['computer_use_linux'], '0.7.18')
        self.calls.clear(); self.provision()
        self.assertFalse(any(c[0] == 'curl' for c in self.calls))
        self.assertFalse((self.home / '.pi').exists())
        self.assertFalse(any('node' == Path(c[0]).name for c in self.calls))

    def test_repair_of_prior_receipt_adds_native_runtime_without_touching_source(self):
        self.fixture_install()
        # Schema-1 receipts before this feature did not own these native files.
        with patch.object(m, 'provision_computer_use'): self.install_quietly()
        self.assertFalse(set(m.COMPUTER_USE_FILES) & set(self.receipt()['files']))
        edit = self.paths['source'] / 'user-edit'; edit.write_text('keep')
        self.args.repair = True; self.calls.clear()
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertTrue(set(m.COMPUTER_USE_FILES) <= set(self.receipt()['files']))
        self.assertEqual(edit.read_text(), 'keep')
        self.assertFalse(any(set(c) & {'clone', 'fetch', 'reset', 'clean'} for c in self.calls))

    def test_resume_reconciles_prior_publication_hash_without_download(self):
        self.prepare(); self.provision()
        actual = self.data['files']['computer_use']
        self.data['files']['computer_use'] = 'c' * 64
        self.data['previous_files'] = {'computer_use': actual}
        self.calls.clear(); self.provision()
        self.assertEqual(self.data['files']['computer_use'], actual)
        self.assertFalse(any(c[0] == 'curl' for c in self.calls))
        m.validate_receipt(self.data, self.paths)

    def test_checksum_failure_publishes_and_executes_nothing(self):
        self.prepare()
        def corrupt(command, **kwargs):
            result = self.execute_fixture(command, **kwargs)
            if command[0] == 'curl':
                Path(command[command.index('--output') + 1]).write_bytes(b'\x7fELF corrupted')
            return result
        with patch.object(m, 'execute', side_effect=corrupt), self.assertRaisesRegex(m.MaintenanceError, 'SHA256'):
            self.provision()
        self.assertEqual(self.data['files'], {})
        self.assertFalse(any(m.owned_target(k, self.paths).exists() for k in m.COMPUTER_USE_FILES))
        self.assertFalse(any(c[-1] == '--help' for c in self.calls))
        for c in self.calls:
            if c[0] == 'curl': self.assertFalse(Path(c[c.index('--output') + 1]).exists())

    def test_partial_download_failure_retains_environment_phase_and_resumes(self):
        self.fixture_install()
        def fail(command, **kwargs):
            result = self.execute_fixture(command, **kwargs)
            if command[0] == 'curl': raise m.MaintenanceError('partial download')
            return result
        with patch.object(m, 'execute', side_effect=fail), self.assertRaises(m.MaintenanceError):
            self.install_quietly()
        self.assertEqual(self.receipt()['phase'], 'environment')
        self.assertFalse(any(m.owned_target(k, self.paths).exists() for k in m.COMPUTER_USE_FILES))
        self.args.resume = True
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertEqual(self.receipt()['phase'], 'complete')

    def test_matching_digest_but_non_native_payload_rejected(self):
        import hashlib
        self.prepare()
        body = b'#!/bin/sh\necho never-execute\n'
        for key in self.asset_bytes: self.asset_bytes[key] = body
        with patch.object(m, 'computer_use_assets', return_value={key: (f'https://fixture.invalid/{key}', hashlib.sha256(body).hexdigest()) for key in m.COMPUTER_USE_FILES}), self.assertRaisesRegex(m.MaintenanceError, 'native ELF'):
            self.provision()
        self.assertEqual(self.data['files'], {})

    def test_unowned_symlink_and_hardlink_collisions_rejected_before_download(self):
        self.prepare()
        target = m.owned_target('computer_use', self.paths)
        target.parent.mkdir(parents=True)
        external = self.home / 'retained'; external.write_bytes(b'external')
        for kind in ('file', 'symlink', 'hardlink'):
            if kind == 'file': target.write_bytes(b'unowned')
            elif kind == 'symlink': target.symlink_to(external)
            else: os.link(external, target)
            self.calls.clear()
            with self.subTest(kind=kind), self.assertRaises(m.MaintenanceError): self.provision()
            self.assertFalse(self.calls)
            target.unlink()
            self.assertEqual(external.read_bytes(), b'external')

    def test_modified_native_file_blocks_repair_and_uninstall_without_deletion(self):
        self.fixture_install(); self.install_quietly()
        target = m.owned_target('computer_use_indicator', self.paths)
        target.write_bytes(b'user modification')
        self.args.repair = True
        with self.assertRaises(m.MaintenanceError): self.install_quietly()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(m.MaintenanceError):
            m.uninstall(self.removal)
        self.assertEqual(target.read_bytes(), b'user modification')
        self.assertTrue(self.paths['environment'].exists())

    def test_uninstall_removes_native_files_but_preserves_shared_agent_packages(self):
        self.fixture_install()
        foreign = self.home / '.pi/agent/npm/node_modules/foreign/package.json'
        foreign.parent.mkdir(parents=True); foreign.write_text('synthetic unchanged')
        self.install_quietly()
        with contextlib.redirect_stdout(io.StringIO()): m.uninstall(self.removal)
        self.assertFalse(self.paths['tools'].exists())
        self.assertEqual(foreign.read_text(), 'synthetic unchanged')

    def test_native_help_failure_is_resumable_and_never_marks_complete(self):
        self.fixture_install()
        def fail(command, **kwargs):
            result = self.execute_fixture(command, **kwargs)
            if command[0] == str(m.owned_target('computer_use', self.paths)):
                raise m.MaintenanceError('native runtime cannot launch')
            return result
        with patch.object(m, 'execute', side_effect=fail), self.assertRaises(m.MaintenanceError):
            self.install_quietly()
        self.assertEqual(self.receipt()['phase'], 'environment')
        self.args.resume = True; self.calls.clear()
        self.assertEqual(self.install_quietly()[0], 0)
        self.assertFalse(any(c[0] == 'curl' for c in self.calls))
