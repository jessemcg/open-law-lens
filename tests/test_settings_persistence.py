"""Per-loaded-settings CAS, including a fresh reopen after a rejected draft."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.config import load_config, save_config


class SettingsPersistenceTests(unittest.TestCase):
    def test_fresh_read_does_not_bless_an_older_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{"reader_font_size_pt":11,"opaque":{"keep":true}}')
            path.chmod(0o600)
            original = load_config(path)
            old_revision = original._settings_revision.revision
            draft = replace(original, reader_font_size_pt=14)
            path.write_text('{"reader_font_size_pt":18,"opaque":{"keep":true}}')
            published = path.read_bytes()
            fresh = load_config(path)
            with self.assertRaisesRegex(OSError, 'stale_settings'):
                save_config(draft, path)
            self.assertEqual(path.read_bytes(), published)
            self.assertEqual(draft._settings_revision.revision, old_revision)
            save_config(replace(fresh, reader_font_size_pt=20), path)
            self.assertEqual(json.loads(path.read_bytes())['reader_font_size_pt'], 20)
            with self.assertRaisesRegex(OSError, 'stale_settings'):
                save_config(draft, path)

    def test_failed_publication_does_not_advance_loaded_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text('{}'); path.chmod(0o600)
            config = load_config(path)
            before = path.read_bytes(), config._settings_revision.revision
            with patch('open_law_lens._model_store.os.rename', side_effect=OSError('synthetic failure')):
                with self.assertRaisesRegex(OSError, 'synthetic failure'):
                    save_config(config, path)
            self.assertEqual((path.read_bytes(), config._settings_revision.revision), before)
            self.assertFalse(list(path.parent.glob('*.tmp')))
            save_config(config, path)
            self.assertNotEqual(config._settings_revision.revision, before[1])
