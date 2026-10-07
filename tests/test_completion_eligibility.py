import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from open_law_lens.agent import PiSessionSnapshotCache
from open_law_lens.app import OpenLawLensWindow
from test_answer_rendering import CompletionWindow, pump_until
from test_session_snapshot import entry


class CompletionEligibilityTests(unittest.TestCase):
    def test_failed_followup_keeps_previous_answer_unsaveable_and_retry_restores(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            path = window._agent_session_log_path
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertTrue(window._agent_answer_eligible)
            self.assertEqual(window._agent_answer_turn_count, 1)
            for reason in ('aborted', 'error', 'length', 'deferred', 'future', None):
                with self.subTest(reason=reason):
                    path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop') +
                                    entry('user', 'q2') + entry('assistant', 'a2', reason, text='PARTIAL'))
                    window._poll_agent_answer()
                    pump_until(lambda: not window._agent_answer_working)
                    self.assertFalse(window._agent_answer_eligible)
                    self.assertEqual(window._agent_last_answer_text, 'same answer')
                    self.assertEqual(window.views[-1], 'session')
                    window.client = SimpleNamespace(cache=Mock())
                    OpenLawLensWindow._on_save_agent_answer_clicked(window, None)
                    window.client.cache.save_agent_answer.assert_not_called()
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop') +
                            entry('user', 'q2') + entry('assistant', 'a2', 'error') +
                            entry('assistant', 'a3', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertTrue(window._agent_answer_eligible)
            self.assertFalse(window._agent_failure_visible)
            self.assertEqual(window._agent_answer_turn_count, 2)
            self.assertEqual(window.views[-1], 'answer')
            window._stop_agent_answer_polling()

    def test_preparing_previous_output_and_cached_failure_exit_stop_spinner(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            window.composer_busy = False
            window._set_composer_idle = lambda: setattr(window, 'composer_busy', True)
            window._set_status = lambda text: setattr(window, 'composer_busy', False)
            path = window._agent_session_log_path
            # Poll missed the earlier stop before a failed follow-up was logged.
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop') +
                            entry('user', 'q2') + entry('assistant', 'a2', 'error'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(window._agent_last_answer_text, 'same answer')
            self.assertFalse(window._agent_answer_eligible)
            self.assertFalse(window.composer_busy)
            window._agent_active = False
            window._poll_agent_answer()  # Unchanged cache, but process just ended.
            pump_until(lambda: not window._agent_answer_working)
            self.assertFalse(window._agent_answer_finishing)
            self.assertFalse(window.composer_busy)
            self.assertFalse(window._agent_answer_eligible)

    def test_truncated_log_resets_turn_count_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            path = window._agent_session_log_path
            first = entry('user', 'q1') + entry('assistant', 'a1', 'stop')
            path.write_text(first + entry('user', 'q2') + entry('assistant', 'a2', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(window._agent_answer_turn_count, 2)
            window._agent_waiting_after_turn = 2
            path.write_text(first)
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(window._agent_answer_turn_count, 1)
            self.assertTrue(window._agent_answer_eligible)
            window._agent_waiting_after_turn = 1
            with path.open('a') as handle:
                handle.write(entry('user', 'q3') + entry('assistant', 'a3', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(window._agent_answer_turn_count, 2)
            self.assertTrue(window._agent_answer_eligible)

    def test_unchanged_polls_preserve_answer_session_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            path = window._agent_session_log_path
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            window._set_agent_subview('session')
            view_count = len(window.views)
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(len(window.views), view_count)
            with path.open('a') as handle:
                handle.write(entry('user', 'q2') + entry('assistant', 'a2', 'error'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            window._set_agent_subview('answer')  # Explicitly view previous output.
            view_count = len(window.views)
            status_count = len(window.statuses)
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertEqual(len(window.views), view_count)
            self.assertEqual(len(window.statuses), status_count)

    def test_save_callback_refuses_log_change_before_next_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            path = window._agent_session_log_path
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertTrue(window._agent_answer_eligible)
            with path.open('a') as handle:
                handle.write(entry('user', 'q2'))
            window.client = SimpleNamespace(cache=Mock())
            OpenLawLensWindow._on_save_agent_answer_clicked(window, None)
            self.assertFalse(window._agent_answer_eligible)
            window.client.cache.save_agent_answer.assert_not_called()

    def test_accepted_followup_waits_for_new_turn_not_cached_success(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            path = window._agent_session_log_path
            path.write_text(entry('user', 'q1') + entry('assistant', 'a1', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            window._agent_waiting_after_turn = 1
            window._agent_answer_eligible = False
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertFalse(window._agent_answer_eligible)
            with path.open('a') as handle:
                handle.write(entry('user', 'q2') + entry('assistant', 'a2', 'stop'))
            window._poll_agent_answer()
            pump_until(lambda: not window._agent_answer_working)
            self.assertTrue(window._agent_answer_eligible)
            self.assertEqual(window._agent_answer_turn_count, 2)
