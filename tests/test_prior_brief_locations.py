from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.config import AppConfig
from open_law_lens import prior_briefs as pb
from open_law_lens.cli import main


class PriorBriefLocationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.default = self.root / 'default'
        self.first = self.root / 'First archive α'
        self.second = self.root / 'Second archive'
        for folder in (self.default, self.first, self.second):
            folder.mkdir()
        self.database = self.root / 'indexes/prior_briefs.sqlite3'
        self.stack.enter_context(patch.object(pb, 'DEFAULT_PRIOR_BRIEFS_DIR', self.default))
        self.stack.enter_context(patch.object(pb, 'DEFAULT_PRIOR_BRIEFS_DB', self.database))
        self.stack.enter_context(patch.dict(os.environ, {
            'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': '', 'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': '',
        }))
        self.config = self.stack.enter_context(patch.object(pb, 'load_config', return_value=AppConfig()))
        self.stack.enter_context(patch.object(pb, 'extract_prior_brief_document',
            side_effect=lambda path: pb.PriorBriefExtraction(path.read_text())))

    def use(self, folder):
        self.config.return_value = AppConfig(prior_briefs_folder=str(folder))
        return pb.PriorBriefLibrary.default()

    def test_default_legacy_database_and_ids_are_unchanged(self):
        library = pb.PriorBriefLibrary.default()
        self.assertEqual(library.source_dir, self.default)
        self.assertEqual(library.path, self.database)
        (self.default / 'brief.odt').write_text('Original archive')
        library.sync()
        self.assertEqual(library.list_briefs()[0].brief_id,
                         pb.brief_id_for_relative_path('brief.odt'))
        self.assertEqual(pb.prior_briefs_db_path(self.default), self.database)

    def test_folder_indexes_ids_and_contents_never_mix_and_switch_back_reuses_index(self):
        (self.first / 'brief.odt').write_text('First archive argument')
        (self.second / 'brief.odt').write_text('Second archive argument')
        first = self.use(self.first)
        first.sync()
        first_brief = first.list_briefs()[0]
        first_bytes = first.path.read_bytes()
        second = self.use(self.second)
        self.assertNotEqual(first.path, second.path)
        self.assertEqual(second.count(), 0)
        self.assertEqual(second.search('argument'), [])
        second.sync()
        second_brief = second.list_briefs()[0]
        self.assertNotEqual(first_brief.brief_id, second_brief.brief_id)
        self.assertIsNone(second.read(first_brief.brief_id))
        self.assertEqual(second_brief.text, 'Second archive argument')
        self.assertEqual(second_brief.source_path, str(self.second / 'brief.odt'))
        self.assertEqual(first.path.read_bytes(), first_bytes)
        restored = self.use(self.first)
        self.assertEqual(restored.path, first.path)
        self.assertEqual(restored.read(first_brief.brief_id).text, 'First archive argument')
        self.assertEqual((self.first / 'brief.odt').read_text(), 'First archive argument')
        self.assertEqual((self.second / 'brief.odt').read_text(), 'Second archive argument')

    def test_missing_default_folder_does_not_recreate_it_or_clear_legacy_index(self):
        library = self.use(self.default)
        document = self.default / 'brief.odt'
        document.write_text('Keep legacy index')
        library.sync()
        document.unlink()
        self.default.rmdir()
        before = library.path.read_bytes()
        with self.assertRaisesRegex(pb.PriorBriefError, 'unavailable'):
            library.sync()
        self.assertFalse(self.default.exists())
        self.assertEqual(library.path.read_bytes(), before)
        self.assertEqual(library.count(), 1)

    def test_environment_directory_and_database_overrides_win(self):
        self.config.return_value = AppConfig(prior_briefs_folder=str(self.first))
        target = self.root / 'explicit.sqlite3'
        with patch.dict(os.environ, {
            'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': str(self.second),
            'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': str(target),
        }):
            library = pb.PriorBriefLibrary.default()
            self.assertEqual(library.source_dir, self.second)
            self.assertEqual(library.path, target)
        with patch.dict(os.environ, {'HOME': str(self.root)}):
            self.config.return_value = AppConfig(prior_briefs_folder='~/First archive α')
            self.assertEqual(pb.prior_briefs_dir(), self.first)

    def test_cli_and_snapshot_use_the_same_selected_folder_without_live_rescoping(self):
        (self.first / 'brief.odt').write_text('Pinned original argument')
        library = self.use(self.first)
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(['update-brief-library']), 0)
        self.assertEqual(library.count(), 1)
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(['brief-library-db']), 0)
        self.assertEqual(output.getvalue().strip(), str(library.path))
        brief = library.list_briefs()[0]
        snapshot = library.backup(self.root / 'snapshot.sqlite3')
        self.use(self.second)
        # Embedded sessions pin both DB and workspace-only source root as before.
        with patch.dict(os.environ, {
            'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': str(snapshot),
            'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': str(self.root / 'workspace-only'),
        }):
            pinned = pb.PriorBriefLibrary.default()
            self.assertEqual(pinned.read(brief.brief_id).text, 'Pinned original argument')
            self.assertEqual(pinned.search('argument')[0].brief_id, brief.brief_id)
        self.assertEqual(self.use(self.second).count(), 0)

    def test_missing_unreadable_and_failed_scan_preserve_index_and_never_create_source(self):
        (self.first / 'brief.odt').write_text('Keep this indexed argument')
        library = self.use(self.first)
        library.sync()
        before = library.path.read_bytes()
        missing = self.root / 'missing'
        unavailable = pb.PriorBriefLibrary(missing, library.path)
        with self.assertRaisesRegex(pb.PriorBriefError, 'unavailable'):
            unavailable.sync()
        self.assertFalse(missing.exists())
        with patch.object(pb.os, 'access', return_value=False):
            with self.assertRaisesRegex(pb.PriorBriefError, 'not readable'):
                library.sync()
        def failed_walk(_path, *, onerror):
            onerror(PermissionError('Synthetic inaccessible subfolder'))
            return iter(())
        with patch.object(pb.os, 'walk', side_effect=failed_walk):
            with self.assertRaisesRegex(pb.PriorBriefError, 'Unable to scan'):
                library.sync()
        self.assertEqual(library.path.read_bytes(), before)
        self.assertEqual(library.count(), 1)


if __name__ == '__main__':
    unittest.main()
