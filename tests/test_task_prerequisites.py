"""Synthetic task boundaries: never starts Pi or contacts CourtListener."""
from dataclasses import replace
from pathlib import Path
import io
import json
import os
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from open_law_lens import app as ui, task_prerequisites as tasks
from open_law_lens.config import AppConfig, PiAgentProfile
from open_law_lens.pi_runtime import (
    PiModel, PiRuntimeCatalog, PiExecutableMissing, PiStartError, PiRuntimeError,
)

REQUIRE_EXECUTABLE = tasks.pi_runtime.require_pi_executable
MODEL = PiModel('synthetic', 'model', 'Synthetic')
CATALOG = PiRuntimeCatalog((MODEL,), MODEL, 'medium')


class Window:
    """Non-GTK owner exercising the actual request and callback machinery."""
    _agent_terminal = object()
    for_name = ('_begin_agent_request', '_agent_request_current', '_agent_worker',
                '_agent_prepare_idle', '_launch_agent_with_prompt', '_on_agent_launch',
                '_start_custom_appeal_issue_assessment', 'start_appeal_issue_assessment',
                '_start_later_treatment_agent')
    def __init__(self):
        for name in self.for_name:
            setattr(self, name, getattr(ui.OpenLawLensWindow, name).__get__(self))
        self._set_status = Mock()
        self._prepare_agent_question = Mock()
        self._launch_agent_with_prompt_ready = Mock()
        self._appeal_fact_pattern_path = Mock(side_effect=AssertionError('no source validation'))
        self._write_prompt_file = Mock(side_effect=AssertionError('no prompt'))
        self._create_agent_workspace = Mock(side_effect=AssertionError('no workspace'))
        self._start_brief_phrase_search = Mock()
        self.agent_question_entry = Mock()
        self.agent_question_entry.get_text.return_value = 'Question?'
        self._selected_agent_mode = ui.AGENT_MODE_GENERAL
        self.answer = 'Existing answer'
        self.session = object()
        self.followup = 'Existing follow-up'


class DeferredThread:
    jobs = []
    def __init__(self, *, target, args=(), **kwargs):
        self.job = lambda: target(*args)
    def start(self):
        self.jobs.append(self.job)


class TaskPrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig()
        self.token = 'synthetic-token'
        self.callbacks = []
        DeferredThread.jobs = []
        for target, options in (
            ('open_law_lens.app.load_config', {'side_effect': lambda: self.config}),
            ('open_law_lens.app.courtlistener_token', {'side_effect': lambda: self.token}),
            ('open_law_lens.app.Vte', {'new': object()}),
            ('open_law_lens.app.threading.Thread', {'new': DeferredThread}),
            ('open_law_lens.app.GLib.idle_add', {'side_effect': lambda cb: self.callbacks.append(cb)}),
            ('open_law_lens.pi_runtime.require_pi_executable', {'return_value': '/fake/pi'}),
            ('open_law_lens.pi_runtime.available_pi_runtime_catalog', {'return_value': CATALOG}),
        ):
            p = patch(target, **options)
            value = p.start()
            self.addCleanup(p.stop)
            if target.endswith('available_pi_runtime_catalog'):
                self.catalog = value
        self.window = Window()

    def drain(self):
        while DeferredThread.jobs:
            DeferredThread.jobs.pop(0)()
        while self.callbacks:
            self.callbacks.pop(0)()

    def test_real_executable_validation_and_malformed_catalog(self):
        from open_law_lens import pi_runtime
        # Undo only this test's synthetic cheap discovery boundary.
        with patch.object(pi_runtime, 'find_pi_executable', return_value='/missing/pi'), \
             patch.object(pi_runtime, '_executable_path', return_value=None):
            for override, error in (('', PiExecutableMissing), ('/missing/pi', PiStartError)):
                with patch.dict(os.environ, {'OPEN_LAW_LENS_PI_BIN': override}), self.assertRaises(error):
                    # setUp patches the public function, so exercise its original
                    # implementation via the class-independent saved reference.
                    REQUIRE_EXECUTABLE()
        with patch.object(pi_runtime, '_pi_rpc_command', return_value=['synthetic']), \
             patch.object(pi_runtime, '_pi_rpc_response', return_value={
                 'success': True, 'data': {'models': [{'provider': '', 'id': 'bad'}]}}):
            with self.assertRaises(PiRuntimeError):
                pi_runtime.available_pi_models()

    def test_defaults_saved_fonts_opaque_values_and_read_only_loading(self):
        from open_law_lens.config import load_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            self.assertEqual(load_config(path).reader_font_family, 'Linux Libertine O')
            self.assertFalse(path.exists())
            for fields, font, size in (
                ({}, 'Linux Libertine O', 14),
                ({'reader_font_family': 'invalid', 'reader_font_size_pt': 'bad'}, 'Linux Libertine O', 14),
                ({'reader_font_family': 'Noto Serif', 'reader_font_size_pt': 11}, 'Noto Serif', 11),
            ):
                raw = json.dumps({**fields, 'opaque-extra': {'keep': ['literal']}}).encode()
                path.write_bytes(raw)
                loaded = load_config(path)
                self.assertEqual((loaded.reader_font_family, loaded.reader_font_size_pt), (font, size))
                self.assertEqual(path.read_bytes(), raw)

    def test_effective_token_precedence_and_whitespace(self):
        from open_law_lens import config
        with patch.object(config, 'load_config', return_value=AppConfig(courtlistener_token='saved-token')):
            for environment, expected in (('', 'saved-token'), ('   ', 'saved-token'), (' env-token ', 'env-token')):
                with patch.dict(os.environ, {'COURTLISTENER_TOKEN': environment}):
                    self.assertEqual(config.courtlistener_token(), expected)

    def test_missing_authentication_is_typed_not_invalid_credentials_or_network(self):
        from open_law_lens.client import CourtListenerClient, CourtListenerError, CourtListenerAuthenticationRequired
        for token, status, body, missing in (
            ('', 401, {}, True),
            ('', 403, {'detail': 'Authentication credentials were not provided.'}, True),
            ('expired', 401, {'detail': 'Invalid token.'}, False),
            ('', 403, {'detail': 'Permission denied.'}, False),
        ):
            client = CourtListenerClient(cache=Mock(), library=Mock(), token=token)
            error = HTTPError('https://example.test', status, 'synthetic', {}, io.BytesIO(json.dumps(body).encode()))
            with patch('open_law_lens.client.urlopen', side_effect=error):
                with self.assertRaises(CourtListenerError) as caught:
                    client._request_json(Request('https://example.test'))
            self.assertEqual(isinstance(caught.exception, CourtListenerAuthenticationRequired), missing)
            if missing:
                self.assertEqual(str(caught.exception), tasks.MESSAGES[tasks.Reason.TOKEN])
        with patch('open_law_lens.client.urlopen', side_effect=URLError('offline')):
            with self.assertRaises(CourtListenerError) as caught:
                client._request_json(Request('https://example.test'))
            self.assertNotIsInstance(caught.exception, CourtListenerAuthenticationRequired)

    def test_lookup_keeps_browser_fallback_and_only_labels_typed_missing_auth(self):
        from open_law_lens.client import CourtListenerError, CourtListenerAuthenticationRequired
        parent = SimpleNamespace(client=Mock(), _scholar_lookup_query=Mock(return_value='1 Cal.5th 1'),
                                 _fallback_lookup_to_scholar=Mock(return_value=False))
        for error, missing in ((CourtListenerAuthenticationRequired('synthetic'), True),
                               (CourtListenerError('Invalid credentials', status=401), False),
                               (CourtListenerError('Network failure'), False)):
            parent.client.lookup_citation.side_effect = error
            payload = ui.OpenLawLensWindow._lookup_worker_result(parent, '1 Cal.5th 1', cache_generation=3)
            self.assertEqual(payload[:3], ('fallback', '1 Cal.5th 1', 3))
            ui.OpenLawLensWindow._finish_lookup_worker_result(parent, payload)
            self.assertEqual(parent._fallback_lookup_to_scholar.call_args.kwargs,
                             {'missing_authentication': True} if missing else {})

    def test_classifications_and_priority(self):
        for token in ('', ' ', '\t\n'):
            with self.subTest(token=token):
                result = tasks.cheap_check(research=True, token=token, terminal=False, launcher=False)
                self.assertEqual(result.reason, tasks.Reason.TOKEN)
        for exception, reason in ((PiExecutableMissing(), tasks.Reason.PI_MISSING),
                                  (PiStartError(), tasks.Reason.PI_START)):
            with patch('open_law_lens.pi_runtime.require_pi_executable', side_effect=exception):
                self.assertEqual(tasks.cheap_check(research=False, token='', terminal=False,
                                                   launcher=False).reason, reason)
        self.assertEqual(tasks.cheap_check(research=False, token='', terminal=False,
                                          launcher=False).reason, tasks.Reason.TERMINAL)
        self.assertEqual(tasks.cheap_check(research=False, token='', terminal=True,
                                          launcher=False).reason, tasks.Reason.LAUNCHER)

    def test_model_classifications(self):
        for error, reason in ((PiStartError(), tasks.Reason.PI_START),
                              (PiRuntimeError('timeout/private output'), tasks.Reason.CATALOG),
                              (ValueError('malformed/private output'), tasks.Reason.CATALOG),
                              (OSError('query failed'), tasks.Reason.CATALOG)):
            self.catalog.side_effect = error
            self.assertEqual(tasks.model_check(None).reason, reason)
            self.assertNotIn('private', tasks.model_check(None).message)
        self.catalog.side_effect = None
        for catalog, profile, reason in (
            (PiRuntimeCatalog((), None, 'medium'), None, tasks.Reason.MODELS_EMPTY),
            (PiRuntimeCatalog((MODEL,), None, 'medium'), None, tasks.Reason.MODEL),
            (CATALOG, PiAgentProfile('stale', 'model', ''), tasks.Reason.MODEL),
            (CATALOG, None, None),
            (CATALOG, PiAgentProfile('synthetic', 'model', ''), None),
        ):
            self.catalog.return_value = catalog
            self.assertEqual(tasks.model_check(profile).reason, reason)

    def test_all_workflows_both_modes_block_before_preparation(self):
        w = self.window
        for standalone in (False, True):
            for mode in (ui.AGENT_MODE_GENERAL, ui.AGENT_MODE_CASE, ui.AGENT_MODE_BRIEF,
                         ui.AGENT_MODE_APPEAL, 'treatment'):
                with self.subTest(standalone=standalone, mode=mode), patch.object(ui, 'standalone', return_value=standalone):
                    self.token = ''
                    self.catalog.return_value = PiRuntimeCatalog((), None, 'medium')
                    w._selected_agent_mode = mode
                    original_session = w.session
                    if mode == 'treatment':
                        w._start_later_treatment_agent({}, '1', '1 Cal.5th 1')
                    else:
                        w._on_agent_launch(None)
                    self.drain()
                    expected = tasks.Reason.MODELS_EMPTY if mode in (ui.AGENT_MODE_CASE, ui.AGENT_MODE_BRIEF) else tasks.Reason.TOKEN
                    self.assertEqual(w._set_status.call_args.args[0], tasks.MESSAGES[expected])
                    self.assertEqual(w.answer, 'Existing answer')
                    self.assertIs(w.session, original_session)
                    self.assertEqual(w.followup, 'Existing follow-up')
                    self.assertEqual(w.agent_question_entry.get_text(), 'Question?')
        w._prepare_agent_question.assert_not_called()
        w._appeal_fact_pattern_path.assert_not_called()
        w._write_prompt_file.assert_not_called()
        w._create_agent_workspace.assert_not_called()

    def test_shared_case_question_entry_token_gate(self):
        self.token = ' '
        self.assertFalse(self.window.start_appeal_issue_assessment('Issue', Path('/synthetic/facts')))
        self.catalog.assert_not_called()
        self.window._create_agent_workspace.assert_not_called()

    def test_blank_and_local_search_never_check_dependencies(self):
        w = self.window
        w.agent_question_entry.get_text.return_value = ' '
        w._on_agent_launch(None)
        self.assertFalse(DeferredThread.jobs)
        w.agent_question_entry.get_text.return_value = 'exact phrase'
        w._selected_agent_mode = ui.QUERY_MODE_BRIEF_SEARCH
        w._on_agent_launch(None)
        w._start_brief_phrase_search.assert_called_once_with('exact phrase')
        self.catalog.assert_not_called()

    def test_corrected_settings_retry_and_inherited_default(self):
        w = self.window
        self.token = ''
        w._on_agent_launch(None)
        self.token = 'synthetic-token'
        w._on_agent_launch(None)
        self.drain()
        w._prepare_agent_question.assert_called_once_with(ui.AGENT_MODE_GENERAL, 'Question?')
        self.catalog.assert_called_once()

    def test_newer_request_close_and_settings_reject_stale_callbacks(self):
        for invalidate in ('newer', 'close', 'model', 'token'):
            with self.subTest(invalidate=invalidate):
                w = Window()
                w._on_agent_launch(None)
                if invalidate == 'newer':
                    w.agent_question_entry.get_text.return_value = 'New question'
                    w._on_agent_launch(None)
                elif invalidate == 'close':
                    w._agent_requests_closed = True
                elif invalidate == 'model':
                    self.config = replace(self.config, agent_runtime_profile=PiAgentProfile('other', 'model', 'low'))
                else:
                    self.token += '-changed'
                self.drain()
                if invalidate == 'newer':
                    w._prepare_agent_question.assert_called_once_with(ui.AGENT_MODE_GENERAL, 'New question')
                else:
                    w._prepare_agent_question.assert_not_called()

    def test_deferred_parent_close_does_not_disable_future_requests(self):
        w = self.window
        w.get_application = Mock()
        w._on_agent_launch(None)
        with patch.object(ui, 'close_settings_before_parent', return_value=True):
            self.assertTrue(ui.OpenLawLensWindow._on_window_close_request(w, w))
        self.assertFalse(getattr(w, '_agent_requests_closed', False))
        w._on_agent_launch(None)
        self.drain()
        w._prepare_agent_question.assert_called_once()

    def test_preparation_callback_and_final_launch_keep_original_generation(self):
        w = self.window
        queued = Mock()
        def continuation():
            worker = w._agent_worker(lambda: w._agent_prepare_idle(queued))
            worker()
            self.request = ui._AGENT_REQUEST.get()
        w._begin_agent_request(False, continuation)
        DeferredThread.jobs.pop()()
        self.callbacks.pop(0)()
        w._agent_request_generation += 1
        self.drain()
        queued.assert_not_called()
        context = ui._AGENT_REQUEST.set(self.request)
        try:
            w._launch_agent_with_prompt(Path('/prompt'), Path('/workspace'), 'general')
        finally:
            ui._AGENT_REQUEST.reset(context)
        w._launch_agent_with_prompt_ready.assert_not_called()
        self.catalog.assert_called_once()


if __name__ == '__main__':
    unittest.main()
