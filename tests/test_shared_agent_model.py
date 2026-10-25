"""Shared configuration -> authorization -> final VTE environment, no Pi calls."""
from dataclasses import replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from open_law_lens import app as ui
from open_law_lens.config import AppConfig, AGENT_PROFILE_KEYS, PiAgentProfile, load_config
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog

WORKFLOWS = (('general', 'law'), ('case', 'research_cache'), ('brief', 'prior_briefs'),
             ('appeal', 'assess_argument'), ('general', 'subsequent_treatment'))


class InlineThread:
    def __init__(self, *, target, **kwargs): self.target = target
    def start(self): self.target()


class SharedAgentModelTests(unittest.TestCase):
    def test_conflicting_legacy_profiles_feed_same_final_launch_for_all_workflows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'agent_runtime_profiles': {
                key: {'provider': key, 'model': key + '-model', 'thinking': 'high'}
                for key in AGENT_PROFILE_KEYS}}))
            config = load_config(path)
        self.assertEqual(config.agent_runtime_profile, PiAgentProfile('law', 'law-model', 'high'))
        for selection in (config, replace(config, agent_runtime_profile=None)):
            for mode, key in WORKFLOWS:
                with self.subTest(selection=selection.agent_runtime_profile, workflow=key):
                    parent = SimpleNamespace(client=SimpleNamespace(), _agent_followup_generation=0,
                        _agent_followup_entry=None, _agent_terminal=Mock(),
                        **{name: Mock() for name in ('_stop_agent', '_stop_agent_answer_polling',
                            '_clear_agent_answer', '_set_status', '_set_agent_subview',
                            '_start_agent_answer_polling', '_refresh_agent_followup_state', '_on_agent_spawned')})
                    parent._agent_request_generation = 1
                    parent._agent_request_current = lambda request: True
                    context = ui._AGENT_REQUEST.set(ui.AgentRequest(1, selection, 'synthetic-token', selection.agent_runtime_profile, None))
                    self.addCleanup(ui._AGENT_REQUEST.reset, context)
                    with patch.object(ui, 'load_config', return_value=selection), \
                         patch.object(ui, 'find_pi_executable', return_value='/fake/pi'), \
                         patch.object(ui, 'find_pi_node_executable', return_value=''), \
                         patch.object(ui, 'create_followup_runtime', side_effect=OSError('synthetic unavailable')), \
                         patch.object(ui, '_apply_terminal_theme'), \
                         patch.object(ui, 'Vte', SimpleNamespace(PtyFlags=SimpleNamespace(DEFAULT=0))), \
                         patch.dict(os.environ, dict.fromkeys(ui.PI_SELECTION_ENV_KEYS, 'stale-parent')):
                        ui.OpenLawLensWindow._launch_agent_with_prompt_ready(
                            parent, Path('/synthetic/prompt'), Path('/synthetic/workspace'), mode, profile_key=key)
                    call = parent._agent_terminal.spawn_async.call_args
                    self.assertIsNotNone(call)
                    env = dict(item.split('=', 1) for item in call.args[3])
                    self.assertEqual(env['OPEN_LAW_LENS_AGENT_MODE'], mode)
                    self.assertEqual(env['OPEN_LAW_LENS_AGENT_PROFILE_KEY'], key)
                    if selection.agent_runtime_profile is None:
                        self.assertFalse(set(ui.PI_SELECTION_ENV_KEYS) & env.keys())
                    else:
                        self.assertEqual([env[name] for name in ui.PI_SELECTION_ENV_KEYS], ['law', 'law-model', 'high'])

    def test_standalone_selection_changes_during_catalog_check_are_rejected(self):
        model = PiModel('chosen', 'available', 'Synthetic')
        catalog = PiRuntimeCatalog((model,), model, 'medium')
        original = AppConfig(agent_runtime_profile=PiAgentProfile('chosen', 'available', 'high'))
        changed = replace(original, agent_runtime_profile=PiAgentProfile('other', 'available', 'high'))
        for mode, key in WORKFLOWS:
            effort_changed = replace(original, agent_runtime_profile=PiAgentProfile('chosen', 'available', 'low'))
            for final, expected in ((original, 'launch'), (changed, 'Settings changed'),
                                    (effort_changed, 'Settings changed'),
                                    (replace(original, agent_runtime_profile=None), 'Settings changed')):
                with self.subTest(workflow=key, expected=expected):
                    parent = SimpleNamespace(_set_status=Mock(), _launch_agent_with_prompt_ready=Mock(),
                                             _agent_terminal=object())
                    parent._agent_request_current = ui.OpenLawLensWindow._agent_request_current.__get__(parent)
                    continuation = lambda: parent._launch_agent_with_prompt_ready(
                        Path('/synthetic/prompt'), Path('/synthetic/workspace'), mode, key)
                    with patch.object(ui, 'standalone', return_value=True), \
                         patch.object(ui, 'load_config', side_effect=[original, final]), \
                         patch.object(ui, 'courtlistener_token', return_value='synthetic-token'), \
                         patch.object(ui.task_prerequisites, 'cheap_check', return_value=ui.task_prerequisites.Result()), \
                         patch.object(ui.task_prerequisites.pi_runtime, 'available_pi_runtime_catalog', return_value=catalog), \
                         patch.object(ui.threading, 'Thread', InlineThread), \
                         patch.object(ui.GLib, 'idle_add', side_effect=lambda callback: callback()):
                        ui.OpenLawLensWindow._begin_agent_request(parent, True, continuation)
                    if expected == 'launch':
                        self.assertEqual(parent._launch_agent_with_prompt_ready.call_args.args[-1], key)
                    else:
                        parent._launch_agent_with_prompt_ready.assert_not_called()
                        self.assertIn(expected, parent._set_status.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
