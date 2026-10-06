"""Cold completion must not put library I/O on the GTK thread."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from open_law_lens.app import OpenLawLensWindow as Window
from open_law_lens.case_suggestions import make_statute_suggestion


class CompletionResponsivenessTests(TestCase):
    def test_qualified_statute_and_rule_do_not_load_or_resolve_index(self):
        window = SimpleNamespace(
            _case_suggestions=[],
            _refresh_case_suggestion_index=Mock(side_effect=AssertionError('sync I/O')),
            _refresh_case_suggestion_index_async=Mock(),
        )
        for text in ['WIC 300', 'Welf. & Inst. Code, § 224.2', 'CRC 5.481']:
            self.assertEqual(Window._lookup_text_from_entry(window, text), text)
        window._refresh_case_suggestion_index.assert_not_called()
        window._refresh_case_suggestion_index_async.assert_not_called()

    def test_unresolved_entry_only_requests_async_refresh(self):
        window = SimpleNamespace(
            _case_suggestions=[],
            _refresh_case_suggestion_index=Mock(side_effect=AssertionError('sync I/O')),
            _refresh_case_suggestion_index_async=Mock(),
        )
        self.assertEqual(Window._lookup_text_from_entry(window, 'Example Case'), 'Example Case')
        window._refresh_case_suggestion_index_async.assert_called_once()
        window._refresh_case_suggestion_index.assert_not_called()

    def test_focus_in_inner_text_child_counts_as_entry_focus(self):
        entry = object()
        child = SimpleNamespace(get_parent=lambda: entry)
        window = SimpleNamespace(citation_entry=entry, get_focus=lambda: child)
        self.assertTrue(Window._citation_entry_has_focus(window))
        window.get_focus = lambda: SimpleNamespace(get_parent=lambda: None)
        self.assertFalse(Window._citation_entry_has_focus(window))

    def test_partial_suggestions_work_before_library_finishes(self):
        suggestion = make_statute_suggestion('WIC 300')
        window = SimpleNamespace(
            _case_suggestions=[], _case_suggestions_loaded=False,
            _case_suggestion_refresh_pending=True,
            _citation_entry_has_focus=lambda: True,
            citation_entry=SimpleNamespace(get_text=lambda: 'WIC 300'),
            _show_case_completion=Mock(),
        )
        Window._publish_concordance_suggestions(window, [suggestion])
        window._show_case_completion.assert_called_once_with([suggestion])
        self.assertFalse(window._case_suggestions_loaded)
        self.assertTrue(window._case_suggestion_refresh_pending)

    def test_edits_keep_showing_partial_results_during_pending_refresh(self):
        suggestion = make_statute_suggestion('WIC 300')
        window = SimpleNamespace(
            _case_completion_changing=False, _case_suggestions_loaded=False,
            _case_suggestions=[suggestion], _refresh_case_suggestion_index_async=Mock(),
            citation_entry=SimpleNamespace(get_text=lambda: 'WIC 300'),
            _show_case_completion=Mock(),
        )
        Window._on_citation_entry_changed(window, None)
        window._show_case_completion.assert_called_once_with([suggestion])

    def test_worker_queues_concordance_before_expensive_library_scan(self):
        suggestion = make_statute_suggestion('WIC 300')
        window = SimpleNamespace(
            client=SimpleNamespace(library=object()),
            _publish_concordance_suggestions=Mock(),
        )
        with patch('open_law_lens.app.concordance_file_path', return_value=Path('/tmp/synthetic')), \
             patch('open_law_lens.app.load_concordance_case_suggestions', return_value=[]), \
             patch('open_law_lens.app.load_concordance_statute_suggestions', return_value=[suggestion]), \
             patch('open_law_lens.app.load_concordance_rule_suggestions', return_value=[]), \
             patch('open_law_lens.app.GLib.idle_add') as idle, \
             patch('open_law_lens.app.case_suggestions_from_library') as library:
            def scan(_library):
                idle.assert_called_once_with(window._publish_concordance_suggestions, [suggestion])
                return []
            library.side_effect = scan
            self.assertEqual(Window._load_case_suggestion_index(window), [suggestion])

    def test_finish_publishes_for_child_focus(self):
        suggestion = make_statute_suggestion('WIC 300')
        window = SimpleNamespace(
            _case_suggestions=[], _case_suggestions_loaded=False,
            _case_suggestion_refresh_pending=True,
            _citation_entry_has_focus=lambda: True,
            citation_entry=SimpleNamespace(get_text=lambda: 'WIC 300'),
            _show_case_completion=Mock(),
        )
        Window._finish_case_suggestion_index_refresh(window, [suggestion])
        self.assertTrue(window._case_suggestions_loaded)
        self.assertFalse(window._case_suggestion_refresh_pending)
        window._show_case_completion.assert_called_once_with([suggestion])
