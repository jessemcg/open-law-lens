"""Ordinary settings accept sync permission bits without rewriting on read.

Only synthetic temporary data is used. Kept local in each independent owner.
"""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "journal_store.py"
if not SOURCE.exists():
    SOURCE = next(ROOT.glob("*/_model_store.py"))
SPEC = importlib.util.spec_from_file_location("sync_permission_store", SOURCE)
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


class SyncPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="settings-sync-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings_dir = self.root / "shared" / "app"
        self.settings_dir.mkdir(parents=True)
        self.path = self.settings_dir / "config.json"
        self.path.write_bytes(b'{"unknown":{"keep":true},"value":1}\n')
        env = patch.dict(os.environ, XDG_STATE_HOME=str(self.root / "state"))
        env.start()
        self.addCleanup(env.stop)

    def test_synced_modes_read_without_permission_or_content_repair(self):
        for directory_mode in (0o775, 0o777):
            self.settings_dir.parent.chmod(directory_mode)
            self.settings_dir.chmod(directory_mode)
            for mode in (0o664, 0o666, 0o620, 0o602):
                with self.subTest(directory=directory_mode, file=mode):
                    self.path.chmod(mode)
                    before = self.path.stat()
                    data = self.path.read_bytes()
                    self.assertEqual(store.read_ordinary(self.path)["value"], 1)
                    after = self.path.stat()
                    self.assertEqual((before.st_ino, before.st_mode, before.st_mtime_ns),
                                     (after.st_ino, after.st_mode, after.st_mtime_ns))
                    self.assertEqual(self.path.read_bytes(), data)
                    self.assertEqual(stat.S_IMODE(self.settings_dir.stat().st_mode), directory_mode)

    def test_saves_accept_shared_settings_and_adjacent_locks(self):
        self.settings_dir.chmod(0o777)
        adjacent = self.path.with_name(".config.json.writer.lock")
        adjacent.write_bytes(b"")
        adjacent.chmod(0o666)
        for mode in (0o664, 0o666):
            self.path.chmod(mode)
            draft = store.read_ordinary(self.path)
            draft["value"] += 1
            store.save_ordinary(self.path, draft)
            self.assertEqual(store.read_ordinary(self.path)["value"], draft["value"])
            self.assertEqual(store.read_ordinary(self.path)["unknown"], {"keep": True})
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(adjacent.stat().st_mode), 0o666)

    def test_permission_only_change_does_not_invalidate_loaded_draft(self):
        draft = store.read_ordinary(self.path)
        self.path.chmod(0o666)
        draft["value"] = 2
        store.save_ordinary(self.path, draft)
        self.assertEqual(store.read_ordinary(self.path)["value"], 2)

    def test_shared_permissions_do_not_disable_writer_exclusion(self):
        self.path.chmod(0o666)
        adjacent = self.path.with_name(".config.json.writer.lock")
        adjacent.write_bytes(b"")
        adjacent.chmod(0o666)
        with store.Store(self.path) as first, first.lock():
            with store.Store(self.path) as second:
                with self.assertRaisesRegex(store.Failure, "settings_busy"):
                    with second.lock():
                        self.fail("concurrent writer accepted")

    def test_stale_save_and_sync_conflict_still_fail(self):
        self.path.chmod(0o666)
        draft = store.read_ordinary(self.path)
        self.path.write_bytes(b'{"external":true}\n')
        with self.assertRaisesRegex(store.Failure, "stale_settings"):
            store.save_ordinary(self.path, draft)
        self.assertEqual(self.path.read_bytes(), b'{"external":true}\n')
        self.path.with_name("config (conflicted copy).json").write_bytes(b"{}")
        with self.assertRaisesRegex(store.Failure, "sync_conflict"):
            store.read_ordinary(self.path)

    def test_linked_and_nonregular_settings_still_fail(self):
        target = self.path.with_name("target.json")
        self.path.rename(target)
        self.path.symlink_to(target)
        with self.assertRaises(OSError):
            store.read_ordinary(self.path)
        self.path.unlink()
        os.link(target, self.path)
        with self.assertRaisesRegex(store.Failure, "unsafe_settings_file"):
            store.read_ordinary(self.path)
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(OSError):
            store.read_ordinary(self.path)

    def test_private_recovery_files_and_directories_remain_private(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        path = private / "receipt.json"
        path.write_bytes(b"{}")
        path.chmod(0o666)
        with self.assertRaisesRegex(store.Failure, "unsafe_state_file"):
            store.private_read(path)
        path.chmod(0o600)
        private.chmod(0o777)
        with self.assertRaisesRegex(store.Failure, "unsafe_state_directory"):
            store.private_read(path)

    def test_wrong_owner_and_invalid_json_still_fail(self):
        self.path.chmod(0o666)
        with patch.object(store.os, "getuid", return_value=os.getuid() + 10000):
            with self.assertRaisesRegex(store.Failure, "unsafe_settings_directory"):
                store.read_ordinary(self.path)
        self.path.write_bytes(b'{"duplicate":1,"duplicate":2}')
        with self.assertRaisesRegex(store.Failure, "invalid_json"):
            store.read_ordinary(self.path)


if __name__ == "__main__":
    unittest.main()
