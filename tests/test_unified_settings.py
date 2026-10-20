"""Synthetic native Settings session baseline/close checks; no services."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from open_law_lens import app as ui


class UnifiedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ui.Gtk.init_check():
            raise unittest.SkipTest("GTK display unavailable")
        ui.Adw.init()
        cls.app = ui.Adw.Application(application_id="org.synthetic.OpenLawLens.SettingsTests")
        cls.app.register(None)

    def test_stale_native_draft_reopens_against_saved_settings_without_writing(self):
        import json
        from pathlib import Path
        import tempfile
        from open_law_lens.config import load_config, save_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'courtlistener_token':'saved', 'agent_runtime_profile':
                {'provider':'fireworks','model':'old','thinking':'high'}}))
            path.chmod(0o600)
            parent = SimpleNamespace(get_application=lambda: self.app, reload_settings=Mock(),
                                     _appeal_fact_pattern_path_override=None)
            with patch.object(ui, 'load_config', side_effect=lambda: load_config(path)), \
                 patch.object(ui, 'save_config', side_effect=lambda config: save_config(config, path)), \
                 patch.object(ui.SettingsWindow, '_load_pi_models'), \
                 patch.object(ui.SettingsWindow, '_refresh_appeal_fact_pattern_entry'):
                old = ui.SettingsWindow(parent); self.addCleanup(old.destroy)
                old.token_row.set_text('retained draft')
                baseline = old._session.baseline
                path.write_text(json.dumps({'courtlistener_token':'published', 'agent_runtime_profile':
                    {'provider':'fireworks','model':'published','thinking':'high'}}))
                published = path.read_bytes()
                old._on_save_clicked(None)
                self.assertEqual(old.token_row.get_text(), 'retained draft')
                self.assertEqual(old._session.baseline, baseline)
                self.assertIn('stale_settings', old.status_label.get_text())
                fresh = ui.SettingsWindow(parent); self.addCleanup(fresh.destroy)
                self.assertEqual(fresh.token_row.get_text(), 'published')
                self.assertEqual(fresh._original_pi_profile.model, 'published')
                self.assertEqual(path.read_bytes(), published)
                self.assertEqual(old._session.baseline, baseline)

    def test_save_open_repeat_failed_baseline_and_immediate_exception(self):
        config = ui.AppConfig(courtlistener_token="synthetic")
        parent = SimpleNamespace(get_application=lambda: self.app, reload_settings=Mock(),
                                 _appeal_fact_pattern_path_override=None)
        with patch.object(ui, "load_config", return_value=config), \
             patch.object(ui.SettingsWindow, "_load_pi_models"), \
             patch.object(ui.SettingsWindow, "_refresh_appeal_fact_pattern_entry"):
            w = ui.SettingsWindow(parent)
            self.addCleanup(w.destroy)
            w.present()
            self.assertEqual(list(w.settings_categories), ["General", "Display", "Highlights", "Agent Model"])
            self.assertIsInstance(w.token_row, ui.Adw.PasswordEntryRow)
            controls = w.pi_model_row.get_parent()
            self.assertIsInstance(controls, ui.Gtk.ListBox)
            self.assertIs(w.pi_thinking_row.get_parent(), controls)
            self.assertEqual(controls.get_selection_mode(), ui.Gtk.SelectionMode.NONE)
            self.assertTrue(controls.has_css_class("boxed-list"))
            self.assertIs(controls.get_row_at_index(0), w.pi_model_row)
            self.assertIs(controls.get_row_at_index(1), w.pi_thinking_row)
            self.assertIsNone(controls.get_row_at_index(2))
            # Immediate session-only action is outside the persistent draft.
            parent._appeal_fact_pattern_path_override = "synthetic-session-only"
            self.assertEqual(w._draft_snapshot(), w._session.baseline)
            w.token_row.set_text("edited synthetic token")
            baseline = w._session.baseline
            with patch.object(ui, "save_config", side_effect=OSError("synthetic failure")):
                w._on_save_clicked(None)
            self.assertEqual(w._session.baseline, baseline)
            self.assertIn("Unable to save", w.status_label.get_text())
            with patch.object(ui, "save_config") as save:
                w._on_save_clicked(None)
                self.assertTrue(w.get_visible())
                self.assertEqual(w._session.baseline, w._draft_snapshot())
                w.reader_font_size_row.set_value(18)
                w._on_save_clicked(None)
                self.assertEqual(save.call_count, 2)
            parent.reload_settings.side_effect = RuntimeError("synthetic display failure")
            w.token_row.set_text("saved despite display refresh failure")
            with patch.object(ui, "save_config"):
                w._on_save_clicked(None)
            self.assertEqual(w._session.baseline, w._draft_snapshot())
            self.assertIn("saved, but", w.status_label.get_text())
            w.token_row.set_text("unsaved")
            self.assertTrue(w._on_settings_close_request())
            self.assertFalse(w._pi_model_closed)
            w._session.dialog.response("keep")
            self.assertTrue(w.get_visible())
