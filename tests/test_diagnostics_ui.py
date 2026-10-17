"""Exercise async result ownership without opening a window or touching settings."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from open_law_lens import diagnostics_ui as ui


class DiagnosticsUITests(unittest.TestCase):
    def window(self):
        return SimpleNamespace(_generation=0, _report={"old": True}, text=Mock())

    def run_refresh(self, window, probe, callbacks):
        def thread(*, target, daemon):
            return SimpleNamespace(start=target)
        with patch.object(ui.threading, "Thread", side_effect=thread), \
             patch.object(ui.GLib, "idle_add", side_effect=callbacks.append), \
             patch.object(ui, "report", side_effect=probe), \
             patch.object(ui, "format_report", return_value="synthetic result"):
            ui.SetupWindow.refresh(window)

    def test_probe_failure_is_visible_and_redacted_and_cannot_copy_old_report(self):
        window = self.window()
        callbacks = []
        def fail(**kwargs):
            self.assertIsNone(window._report)
            raise RuntimeError("synthetic-private-token-and-document-path")
        self.run_refresh(window, fail, callbacks)
        callbacks[0]()
        self.assertIsNone(window._report)
        message = window.text.get_buffer().set_text.call_args.args[0]
        self.assertIn("Diagnostics could not complete", message)
        self.assertNotIn("synthetic-private", message)

    def test_closed_or_superseded_window_ignores_results(self):
        window = self.window()
        callbacks = []
        self.run_refresh(window, lambda **kw: {"new": True}, callbacks)
        before = window.text.get_buffer().set_text.call_count
        ui.SetupWindow._on_close(window)
        callbacks[0]()
        self.assertIsNone(window._report)
        self.assertEqual(window.text.get_buffer().set_text.call_count, before)

    def test_success_publishes_current_report(self):
        window = self.window()
        callbacks = []
        self.run_refresh(window, lambda **kw: {"new": True}, callbacks)
        callbacks[0]()
        self.assertEqual(window._report, {"new": True})
        self.assertTrue(window.text.get_buffer().set_text.call_args.args[0].endswith("synthetic result"))
