from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.config import (
    AGENT_PROFILE_KEYS, AppConfig, DEFAULT_APPEAL_ISSUE_LABELS,
    DEFAULT_APPEAL_ISSUE_PRESETS, DEFAULT_BARE_STATUTE_LAW_CODE,
    DEFAULT_LINKED_TEXT_COLOR, DEFAULT_READER_FONT_FAMILY,
    DEFAULT_READER_FONT_SIZE_PT, DEFAULT_SEARCH_MATCH_COLOR,
    LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS, PiAgentProfile,
    READER_FONT_FAMILY_OPTIONS, RETIRED_PROMPT_KEYS, load_config, save_config,
)


class ConfigTests(unittest.TestCase):
    def test_missing_and_invalid_configs_have_safe_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for content in (None, 'invalid {', '[]', 'null'):
                if content is not None:
                    path.write_text(content)
                config = load_config(path)
                self.assertEqual(config, AppConfig())
                self.assertEqual(config.retired_prompt_settings, {})
                if content is None:
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(path.read_text(), content)
        self.assertEqual(AppConfig().reader_font_size_pt, DEFAULT_READER_FONT_SIZE_PT)
        self.assertEqual(AppConfig().default_bare_statute_law_code, DEFAULT_BARE_STATUTE_LAW_CODE)

    def test_retired_prompts_are_lossless_opaque_read_only_compatibility(self):
        values = (
            ' \nCustom {missing} {unbalanced /skill:ignored "é"\t ',
            None, 17, ['not', 'a template'], {'nested': ['{question}', False]}, '',
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            # Exercise each key with every JSON shape; both treatment aliases coexist.
            for offset in range(len(values)):
                retired = {key: values[(index + offset) % len(values)]
                           for index, key in enumerate(RETIRED_PROMPT_KEYS)}
                raw = {**retired, 'courtlistener_token': ' synthetic ',
                       'agent_runtime_profiles_version': 2,
                       'agent_runtime_profiles': {key: {
                           'provider': 'test', 'model': key, 'thinking': 'high',
                       } for key in AGENT_PROFILE_KEYS}}
                path.write_text(json.dumps(raw, ensure_ascii=False, indent=3) + '\n')
                before = path.read_bytes()
                config = load_config(path)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(config.retired_prompt_settings, retired)
                self.assertNotIn('retired_prompt_settings', repr(config))
                save_config(replace(config, reader_font_size_pt=19), path)
                saved = json.loads(path.read_text())
                self.assertEqual({key: saved[key] for key in RETIRED_PROMPT_KEYS}, retired)
                self.assertEqual(load_config(path).agent_runtime_profile, config.agent_runtime_profile)
                self.assertEqual(saved['agent_runtime_profiles'], raw['agent_runtime_profiles'])
                self.assertEqual(load_config(path).reader_font_size_pt, 19)
                self.assertEqual(load_config(path).retired_prompt_settings, retired)

    def test_absent_retired_keys_stay_absent_on_explicit_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for keys in ((), RETIRED_PROMPT_KEYS[:1], RETIRED_PROMPT_KEYS[-1:], RETIRED_PROMPT_KEYS[-2:]):
                retired = {key: '  uv run open-law-lens {broken  ' for key in keys}
                path.write_text(json.dumps(retired))
                save_config(load_config(path), path)
                raw = json.loads(path.read_text())
                self.assertEqual({key: raw[key] for key in RETIRED_PROMPT_KEYS if key in raw}, retired)
            save_config(AppConfig(), path)
            self.assertFalse(set(RETIRED_PROMPT_KEYS) & json.loads(path.read_text()).keys())

    def test_save_and_load_active_preferences_and_shared_profile(self):
        profile = PiAgentProfile('test-provider', 'model', 'max')
        original = AppConfig(
            courtlistener_token=' token-value ', concordance_file_path=' /tmp/file.sdi ',
            prior_briefs_folder=' /tmp/prior briefs α ',
            agent_runtime_profile=profile, reader_font_size_pt=14,
            reader_font_family='Caladea', search_match_color='#12AB34',
            linked_text_color='#AA4433', default_bare_statute_law_code='FAM',
            appeal_issue_presets=[' One ', 'Two', 'One'], appeal_issue_labels=[' First ', 'Second'],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            save_config(original, path)
            loaded = load_config(path)
            self.assertEqual(loaded.courtlistener_token, 'token-value')
            self.assertEqual(loaded.concordance_file_path, '/tmp/file.sdi')
            self.assertEqual(loaded.prior_briefs_folder, '/tmp/prior briefs α')
            self.assertEqual(loaded.agent_runtime_profile, profile)
            self.assertEqual(loaded.reader_font_size_pt, 14)
            self.assertEqual(loaded.reader_font_family, 'Caladea')
            self.assertEqual(loaded.search_match_color, '#12ab34')
            self.assertEqual(loaded.linked_text_color, '#aa4433')
            self.assertEqual(loaded.default_bare_statute_law_code, 'FAM')
            self.assertEqual(loaded.appeal_issue_presets, ['One', 'Two'])
            self.assertEqual(loaded.appeal_issue_labels, ['First', 'Second'])
            self.assertNotIn('agent_runtime_profiles_version', json.loads(path.read_text()))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_shared_selection_precedence_read_only_and_lossless_save(self):
        law = {'provider': 'x', 'model': 'law-model', 'thinking': 'high'}
        shared = {'provider': 'shared', 'model': 'chosen', 'thinking': 'low'}
        invalid = (None, {}, [], False, 7, 'bad', {'provider': 7, 'model': 'x', 'thinking': 'high'},
                   {'provider': '', 'model': 'x', 'thinking': 'high'},
                   {'provider': 'x', 'model': 'y', 'thinking': 'bad'})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for version in ('absent', None, 1, 2, 3, {'opaque': True}):
                for selection in ('absent', shared, *invalid):
                    with self.subTest(version=version, selection=selection):
                        legacy = {key: {'provider': key, 'model': key, 'thinking': 'medium'}
                                  for key in AGENT_PROFILE_KEYS}
                        legacy['law'] = law
                        legacy['unknown'] = ['preserve', None]
                        raw = {'agent_runtime_profiles': legacy, 'unknown_setting': {'keep': True}}
                        if version != 'absent':
                            raw['agent_runtime_profiles_version'] = version
                        if selection != 'absent':
                            raw['agent_runtime_profile'] = selection
                        path.write_text(json.dumps(raw, indent=3))
                        before = path.read_bytes()
                        loaded = load_config(path)
                        self.assertEqual(path.read_bytes(), before)
                        expected = law if selection == 'absent' else shared if selection == shared else None
                        self.assertEqual(loaded.agent_runtime_profile, PiAgentProfile(**expected) if expected else None)
                        save_config(loaded, path)
                        saved = json.loads(path.read_text())
                        self.assertEqual(saved['agent_runtime_profile'], expected)
                        self.assertEqual(saved['agent_runtime_profiles'], legacy)
                        self.assertEqual(saved['unknown_setting'], raw['unknown_setting'])
                        self.assertEqual('agent_runtime_profiles_version' in saved, version != 'absent')
                        if version != 'absent':
                            self.assertEqual(saved['agent_runtime_profiles_version'], version)
                        self.assertEqual(load_config(path).agent_runtime_profile, loaded.agent_runtime_profile)

    def test_missing_invalid_law_never_selects_another_workflow(self):
        other = {'provider': 'other', 'model': 'never', 'thinking': 'high'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for legacy in (None, [], 'bad', {}, {'research_cache': other},
                           {'law': None, 'prior_briefs': other}, {'law': {}, 'subsequent_treatment': other}):
                raw = {'agent_runtime_profiles': legacy}
                path.write_text(json.dumps(raw))
                loaded = load_config(path)
                self.assertIsNone(loaded.agent_runtime_profile)
                save_config(loaded, path)
                self.assertEqual(json.loads(path.read_text())['agent_runtime_profiles'], legacy)
            path.write_text('{}')
            save_config(load_config(path), path)
            self.assertNotIn('agent_runtime_profiles', json.loads(path.read_text()))

    def test_retired_reasoning_flags_are_not_reactivated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({f'{prefix}_xhigh_reasoning': True for prefix in
                ('general_agent', 'case_agent', 'brief_agent', 'appeal_issue', 'later_treatment')}))
            config = load_config(path)
            save_config(config, path)
            self.assertIsNone(config.agent_runtime_profile)
            self.assertTrue(all(value is True for key, value in json.loads(path.read_text()).items()
                                if 'xhigh_reasoning' in key))

    def test_colors_reject_non_hex_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for value in ('red; background: black', None, 1, '#abc', '#12345678'):
                path.write_text(json.dumps({'search_match_color': value, 'linked_text_color': value}))
                loaded = load_config(path)
                self.assertEqual(loaded.search_match_color, DEFAULT_SEARCH_MATCH_COLOR)
                self.assertEqual(loaded.linked_text_color, DEFAULT_LINKED_TEXT_COLOR)

    def test_font_preferences_and_retired_bare_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for value, expected in ((2, 8), (100, 48), ('14', 14), ('invalid', 11), (None, 11)):
                path.write_text(json.dumps({'reader_font_size_pt': value, 'default_bare_statute_law_code': 'invalid'}))
                self.assertEqual(load_config(path).reader_font_size_pt, expected)
                self.assertEqual(load_config(path).default_bare_statute_law_code, 'WIC')
            for old, expected in (('Georgia', 'Caladea'), ('Merriweather', 'Bitstream Charter'),
                                  ('Source Sans 3', 'Lato'), ('invalid', DEFAULT_READER_FONT_FAMILY)):
                path.write_text(json.dumps({'reader_font_family': old}))
                self.assertEqual(load_config(path).reader_font_family, expected)
            for name, css in READER_FONT_FAMILY_OPTIONS:
                save_config(AppConfig(reader_font_family=name), path)
                self.assertEqual(load_config(path).reader_font_family, name)
                self.assertTrue(css)
            self.assertIn('Century Schoolbook', dict(READER_FONT_FAMILY_OPTIONS))

    def test_inert_presets_keep_existing_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for old, expected in LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS.items():
                path.write_text(json.dumps({'appeal_issue_presets': [old, 'Custom question?'],
                                           'appeal_issue_labels': ['old label', 'custom']}))
                loaded = load_config(path)
                self.assertEqual(loaded.appeal_issue_presets, [expected, 'Custom question?'])
                self.assertEqual(loaded.appeal_issue_labels, ['old label', 'custom'])
            for value in (None, [], [' ', '']):
                path.write_text(json.dumps({'appeal_issue_presets': value}))
                self.assertEqual(load_config(path).appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))
            path.write_text(json.dumps({'appeal_issue_presets': ['Custom question?']}))
            self.assertEqual(load_config(path).appeal_issue_labels, [''])
            path.write_text('{}')
            self.assertEqual(load_config(path).appeal_issue_labels, list(DEFAULT_APPEAL_ISSUE_LABELS))
            self.assertTrue(all(value.endswith('?') for value in DEFAULT_APPEAL_ISSUE_PRESETS))

    def test_prior_briefs_folder_load_is_read_only_and_rejects_non_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for value in (None, 7, [], {}, False):
                path.write_text(json.dumps({'prior_briefs_folder': value}))
                before = path.read_bytes()
                self.assertEqual(load_config(path).prior_briefs_folder, '')
                self.assertEqual(path.read_bytes(), before)
            path.write_text('{}')
            self.assertEqual(load_config(path).prior_briefs_folder, '')
            self.assertEqual(path.read_text(), '{}')

    def test_environment_concordance_path_overrides_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'concordance_file_path': '/tmp/stored'}))
            with patch.dict(os.environ, {'OPEN_LAW_LENS_CONCORDANCE_FILE': '/tmp/override'}):
                self.assertEqual(load_config(path).concordance_file_path, '/tmp/override')


if __name__ == '__main__':
    unittest.main()
