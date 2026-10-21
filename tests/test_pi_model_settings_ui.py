from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace, MethodType
from unittest.mock import patch

from open_law_lens.app import SettingsWindow
from open_law_lens.config import PiAgentProfile
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog


class FakeComboRow:
    def __init__(self):
        self.selected = 0
        self.model = None
        self.sensitive = False
        self.subtitle = ''

    def get_selected(self): return self.selected
    def set_selected(self, value): self.selected = value
    def set_model(self, value): self.model = value
    def set_sensitive(self, value): self.sensitive = value
    def set_subtitle(self, value): self.subtitle = value


def model_window(original=None):
    window = SimpleNamespace(
        _pi_model_closed=False, _pi_model_generation=1, _pi_model_applying=False,
        _pi_profiles_ready=False, _pi_runtime_catalog=None,
        pi_model_row=FakeComboRow(), pi_thinking_row=FakeComboRow(),
        _pi_model_options=[], _pi_thinking_options=[],
        _original_pi_profile=original, _pending_pi_profile=original,
        pi_model_refresh_button=FakeComboRow(),
    )
    for name in ('_selected_pi_model', '_selected_pi_thinking', '_selected_pi_profile',
                 '_pi_model_is_available', '_populate_pi_thinking_row', '_update_pi_model_subtitle'):
        setattr(window, name, MethodType(getattr(SettingsWindow, name), window))
    return window


class PiModelSettingsUiTests(unittest.TestCase):
    def setUp(self):
        self.full = PiModel('synthetic', 'full', 'Full', supported_thinking_levels=('off', 'low', 'high', 'max'))
        self.fast = PiModel('synthetic', 'fast', 'Fast', supported_thinking_levels=('off', 'low', 'high'))
        self.plain = PiModel('synthetic', 'plain', 'Plain', supported_thinking_levels=('off',))
        self.catalog = PiRuntimeCatalog((self.full, self.fast, self.plain), self.full, 'high')
        strings = patch('open_law_lens.app.Gtk.StringList.new', side_effect=list)
        strings.start()
        self.addCleanup(strings.stop)

    def finish(self, window, desired=None, catalog='default', error=''):
        self.assertFalse(SettingsWindow._finish_pi_model_load(
            window, 1, self.catalog if catalog == 'default' else catalog, error, desired))

    def test_single_pair_no_workflow_rendering_or_duplicate_heading(self):
        source = inspect.getsource(SettingsWindow._build_agent_model_settings_page)
        self.assertEqual(source.count('Adw.ComboRow('), 2)
        self.assertIn('title="Thinking Effort"', source)
        self.assertNotIn('AGENT_PROFILE', source)
        self.assertNotIn('PreferencesGroup', source)
        self.assertNotIn('label="Agent Model"', source)

    def test_layout_has_only_one_app_scroller_and_no_prompt_editors(self):
        source = inspect.getsource(SettingsWindow)
        for retired in ('Gtk.Stack', 'Gtk.Paned', '_settings_page_keys',
                        '_build_prompt_editor', 'prompt_buffer', 'navigation-sidebar'):
            self.assertNotIn(retired, source)
        self.assertEqual(source.count('= Gtk.ScrolledWindow()'), 1)
        self.assertIn('Gtk.Button(label="Save")', source)
        self.assertIn('retired_prompt_settings=previous_config.retired_prompt_settings', source)
        self.assertNotIn('set_expanded(True)', source)

    def test_categories_share_one_boxed_preferences_group(self):
        source = inspect.getsource(SettingsWindow.__init__)
        self.assertEqual(source.count('Adw.PreferencesGroup()'), 1)
        self.assertEqual(source.count('root.append(categories_group)'), 1)
        loop = source.split('for title, subtitle in', 1)[1].split('general = self.settings_categories', 1)[0]
        self.assertIn('categories_group.add(category)', loop)
        self.assertNotIn('Adw.PreferencesGroup()', loop)
        self.assertIn('One model and thinking effort for all Agent tasks', loop)

    def test_defaults_inherit_effective_effort(self):
        window = model_window()
        self.finish(window)
        self.assertIsNone(window._selected_pi_profile())
        self.assertEqual(window._selected_pi_thinking(), '')
        self.assertIn('High', window.pi_thinking_row.model[0])
        self.assertFalse(window.pi_thinking_row.sensitive)

    def test_catalog_adjustment_alone_preserves_saved_effort(self):
        profile = PiAgentProfile(self.plain.provider, self.plain.model_id, 'high')
        window = model_window(profile)
        self.finish(window, profile)
        self.assertEqual(window._selected_pi_thinking(), 'off')
        self.assertEqual(window._selected_pi_profile(), profile)

    def test_model_only_selection_keeps_reasoning_inherited(self):
        window = model_window()
        self.finish(window)
        window.pi_model_row.set_selected(1)
        SettingsWindow._on_pi_model_selected(window, None, None)
        self.assertEqual(window._selected_pi_profile(), PiAgentProfile('synthetic', 'full', ''))

    def test_explicit_supported_unsupported_and_nonreasoning(self):
        for model, requested, expected in ((self.full, 'max', 'max'),
                                           (self.fast, 'max', 'high'),
                                           (self.plain, 'high', 'off')):
            with self.subTest(model=model.model_id):
                window = model_window()
                self.finish(window, PiAgentProfile(model.provider, model.model_id, requested))
                self.assertEqual(window._selected_pi_model(), model)
                self.assertEqual(window._selected_pi_thinking(), expected)
                self.assertTrue(window.pi_thinking_row.sensitive)
                if requested != expected:
                    self.assertIn('unsupported', window.pi_thinking_row.subtitle)

    def test_unavailable_model_preserved_and_can_choose_defaults(self):
        profile = PiAgentProfile('missing', 'retired', 'xhigh')
        window = model_window(profile)
        self.finish(window, profile)
        self.assertEqual(window._selected_pi_profile(), profile)
        self.assertIn('configured; unavailable', window.pi_model_row.model[1])
        self.assertFalse(window.pi_thinking_row.sensitive)
        self.assertTrue(window.pi_model_row.sensitive)

    def test_failure_retains_unsaved_selection_and_recovery(self):
        saved = PiAgentProfile('synthetic', 'full', 'max')
        draft = PiAgentProfile('synthetic', 'fast', 'low')
        window = model_window(saved)
        self.finish(window, draft, catalog=None, error='Synthetic failure')
        self.assertEqual(window._pending_pi_profile, draft)
        self.assertEqual(window._original_pi_profile, saved)
        self.assertEqual(window._selected_pi_profile(), draft)
        self.assertFalse(window._pi_profiles_ready)
        self.assertIn('Synthetic failure', window.pi_model_row.subtitle)
        self.finish(window, draft)
        self.assertEqual(window._selected_pi_profile(), draft)
        self.assertTrue(window._pi_profiles_ready)

    def test_close_and_stale_generation_ignore_callbacks(self):
        window = model_window()
        self.assertFalse(SettingsWindow._finish_pi_model_load(window, 0, self.catalog, '', None))
        self.assertFalse(window.pi_model_refresh_button.sensitive)
        SettingsWindow._on_settings_close_request(window)
        self.assertTrue(window._pi_model_closed)
        self.finish(window)
        self.assertFalse(window.pi_model_refresh_button.sensitive)
        SettingsWindow._on_pi_model_selected(window, None, None)
        SettingsWindow._on_pi_thinking_selected(window, None, None)
        self.assertIsNone(window.pi_model_row.model)


if __name__ == '__main__':
    unittest.main()
