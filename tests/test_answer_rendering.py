from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import patch

from gi.repository import GLib

from open_law_lens.agent import CaseTextSource
from open_law_lens.answer_rendering import PreparedAnswer, prepare_answer
from open_law_lens.app import Gdk, Gtk, OpenLawLensWindow, _AgentAnswerTextFormatter


def pump_until(predicate, timeout=3):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.001)
    assert predicate(), 'main-loop completion timed out'


class CompletionWindow:
    _poll_agent_answer = OpenLawLensWindow._poll_agent_answer
    _agent_answer_prepared = OpenLawLensWindow._agent_answer_prepared
    _finish_agent_answer_work = OpenLawLensWindow._finish_agent_answer_work
    _stop_agent_answer_polling = OpenLawLensWindow._stop_agent_answer_polling

    def __init__(self, root):
        self._agent_workspace_path = root
        self._agent_session_log_path = root / 'session.jsonl'
        self._agent_last_answer_text = ''
        self._agent_active = False
        self._agent_failure_visible = False
        self._agent_mode = 'general'
        self._case_agent_text_sources = []
        self._agent_answer_poll_id = None
        self._agent_answer_generation = 0
        self._agent_answer_render_id = None
        self._agent_answer_turn_count = 0
        self.views = []
        self.statuses = []
        self.applied = []
        self.main_thread = threading.get_ident()

    def _set_composer_idle(self):
        self.assert_main()

    def assert_main(self):
        assert threading.get_ident() == self.main_thread

    def _sync_agent_subviews(self):
        self.assert_main()

    def _set_agent_subview(self, name):
        self.assert_main()
        self.views.append(name)

    def _set_status(self, text):
        self.assert_main()
        self.statuses.append(text)

    def _agent_answer_render_steps(self, plan):
        for i in range(40):
            self.assert_main()
            assert self._agent_answer_finishing
            self.applied.append(i)
            time.sleep(0.001)
            yield


class AnswerRenderingTests(unittest.TestCase):
    def test_worker_does_not_block_main_loop_and_spinner_lasts_through_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            entered, release = threading.Event(), threading.Event()
            calls = []

            def extract(path):
                calls.append(threading.get_ident())
                entered.set()
                release.wait(2)
                return '# Synthetic Final Answer\n*Ready to read*\n\nBody.'

            beats = []
            timer = GLib.timeout_add(5, lambda: (beats.append(time.monotonic()), True)[1])
            try:
                with patch('open_law_lens.app.extract_latest_pi_final_answer_from_jsonl', side_effect=extract):
                    started = time.monotonic()
                    self.assertFalse(window._poll_agent_answer())
                    self.assertLess(time.monotonic() - started, 0.1)
                    self.assertTrue(entered.wait(1))
                    pump_until(lambda: len(beats) >= 6)
                    self.assertTrue(window._agent_answer_finishing)
                    self.assertEqual(window.applied, [])
                    release.set()
                    pump_until(lambda: bool(window._agent_last_answer_text) and not window._agent_answer_working)
                self.assertNotEqual(calls[0], window.main_thread)
                self.assertEqual(len(window.applied), 40)
                self.assertFalse(window._agent_answer_finishing)
                self.assertIn('answer', window.views)
                self.assertGreater(len(beats), 8)
            finally:
                release.set()
                GLib.source_remove(timer)
                window._stop_agent_answer_polling()

    def test_exit_during_poll_rechecks_final_record_without_parallel_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_active = True
            targets = []
            with patch('open_law_lens.app.threading.Thread') as thread:
                thread.side_effect = lambda **kw: SimpleNamespace(start=lambda: targets.append(kw['target']))
                window._poll_agent_answer()
                window._poll_agent_answer()
                self.assertEqual(len(targets), 1)
                window._agent_active = False
                window._poll_agent_answer()
                self.assertTrue(window._agent_answer_recheck)
                window._agent_answer_prepared(0, window._agent_session_log_path, '', 0, None, None)
                self.assertEqual(len(targets), 2)
                self.assertTrue(window._agent_answer_working)
                window._agent_answer_prepared(0, window._agent_session_log_path, '', 0, None, None)
                self.assertFalse(window._agent_answer_working)
                self.assertFalse(window._agent_answer_finishing)
                self.assertTrue(window._agent_failure_visible)
                self.assertTrue(window.statuses)

    def test_stale_worker_and_render_results_cannot_publish_after_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            window = CompletionWindow(Path(directory))
            window._agent_answer_working = True
            window._agent_answer_prepared(0, window._agent_session_log_path, 'obsolete', 0, PreparedAnswer('obsolete', ()), None)
            window._stop_agent_answer_polling()
            window._agent_answer_prepared(0, Path('/obsolete'), 'obsolete', 0, PreparedAnswer('obsolete', ()), None)
            for _ in range(10):
                GLib.MainContext.default().iteration(False)
            self.assertEqual(window._agent_last_answer_text, '')
            self.assertEqual(window.applied, [])
            self.assertIsNone(window._agent_session_log_path)
            self.assertFalse(window._agent_answer_finishing)

    def test_worker_error_and_render_error_release_busy_state(self):
        for error in ('read failed', None):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                window = CompletionWindow(Path(directory))
                window._agent_answer_working = True
                def broken(plan):
                    raise ValueError('synthetic render failure')
                    yield
                window._agent_answer_render_steps = broken
                window._agent_answer_prepared(0, window._agent_session_log_path, 'text', 0,
                                              PreparedAnswer('text', ()), error)
                pump_until(lambda: not window._agent_answer_working)
                self.assertFalse(window._agent_answer_finishing)
                self.assertTrue(window._agent_failure_visible)
                self.assertEqual(window._agent_last_answer_text, '')
                self.assertTrue(window.statuses)

    def test_batched_gtk_render_matches_existing_text_and_navigation(self):
        def window(mode, sources):
            obj = SimpleNamespace(_agent_answer_buffer=Gtk.TextBuffer(),
                                  _agent_mode=mode, _case_agent_text_sources=sources)
            for name in ('_agent_link_lookup', '_agent_citation_link_lookup',
                         '_agent_statute_link_lookup', '_agent_rule_link_lookup',
                         '_agent_external_url_link_lookup', '_agent_search_link_lookup',
                         '_agent_search_action_link_lookup'):
                setattr(obj, name, {})
            for name in ('_agent_link_tags', '_agent_search_next_link_tags', '_agent_search_highlight_tags'):
                setattr(obj, name, [])
            color = Gdk.RGBA()
            color.parse('#4488aa')
            obj._resolve_agent_quote_color = lambda: color
            obj._queue_agent_answer_height_update = lambda: None
            for name in ('_render_inline_markdown', '_render_markdown_text', '_map_offset',
                         '_apply_agent_markdown_spans', '_apply_agent_prior_brief_title_links',
                         '_apply_agent_citation_italics', '_apply_agent_citation_links',
                         '_apply_agent_statute_links', '_apply_agent_rule_links',
                         '_apply_agent_external_url_links'):
                setattr(obj, name, MethodType(getattr(OpenLawLensWindow, name), obj))
            obj._external_url_links = OpenLawLensWindow._external_url_links
            return obj

        source = CaseTextSource('', '', 'Synthetic Opening', '', '', 'children who witnessed the threats',
                               authority_type='prior_brief', prior_brief_id='a' * 64)
        text = ('# Synthetic Answer\n*Qualified result*\n\n'
                f'[Synthetic Opening](open-law-lens://prior-brief/{source.prior_brief_id}) '
                'argues “children who witnessed the threats”.\n\n'
                '***In re Caden C.* (2021) 11 Cal.5th 614**, 636; '
                'Welf. & Inst. Code, §§ 300, 361.5; Cal. Rules of Court, rules 8.1115 and 5.112.1. '
                '**Gov. Code § 815.6**; Probate Code § 100; Health and Safety Code § 1200. '
                'https://example.invalid/source')
        for mode in ('brief', 'case', 'general', 'appeal'):
            with self.subTest(mode=mode):
                old, new = window(mode, [source]), window(mode, [source])
                OpenLawLensWindow._render_agent_answer(old, text)
                plan = prepare_answer(text, mode, [source], _AgentAnswerTextFormatter().format,
                                      OpenLawLensWindow._external_url_links)
                list(OpenLawLensWindow._agent_answer_render_steps(new, plan))
                def rendered(w):
                    b = w._agent_answer_buffer
                    return b.get_text(b.get_start_iter(), b.get_end_iter(), True)
                self.assertEqual(rendered(old), rendered(new))
                self.assertNotIn('*', rendered(new))
                for obj in (old, new):
                    buffer = obj._agent_answer_buffer
                    for phrase in ('In re Caden C.', '11 Cal.5th 614'):
                        tags = buffer.get_iter_at_offset(rendered(obj).index(phrase)).get_tags()
                        weighted = [tag for tag in tags if tag.get_property('weight-set')]
                        effective = max(weighted, key=lambda tag: tag.get_priority())
                        self.assertEqual(effective.get_property('weight'), 700)
                    self.assertEqual(len(obj._agent_statute_link_lookup), 5)
                    self.assertEqual(len(obj._agent_rule_link_lookup), 2)
                    if mode in ('general', 'appeal'):
                        self.assertTrue(obj._agent_citation_link_lookup)
                    else:
                        self.assertFalse(obj._agent_citation_link_lookup)
                for name in ('_agent_link_lookup', '_agent_citation_link_lookup',
                             '_agent_statute_link_lookup', '_agent_rule_link_lookup',
                             '_agent_external_url_link_lookup'):
                    self.assertEqual(sorted(map(repr, getattr(old, name).values())),
                                     sorted(map(repr, getattr(new, name).values())))
                # Compare the tagged text, not just the link identities.
                for name in ('_agent_link_lookup', '_agent_citation_link_lookup',
                             '_agent_statute_link_lookup', '_agent_rule_link_lookup'):
                    def ranges(w):
                        b = w._agent_answer_buffer
                        return sorted((repr(target), ''.join(rendered(w)[i] for i in range(b.get_char_count())
                                      if tag in b.get_iter_at_offset(i).get_tags()))
                                      for tag, target in getattr(w, name).items())
                    self.assertEqual(ranges(old), ranges(new))

    def test_nested_emphasis_shared_reader_and_source_offsets(self):
        formatter = _AgentAnswerTextFormatter()
        citation = 'In re Caden C. (2021) 11 Cal.5th 614'
        text = f'Résumé: ***In re Caden C.* (2021) 11 Cal.5th 614**; **next**.'
        rendered, spans, offsets = formatter._render_markdown_text(text)
        self.assertEqual(rendered, f'Résumé: {citation}; next.')
        self.assertIn((8, 8 + len(citation), 'bold'), spans)
        self.assertIn((8, 8 + len('In re Caden C.'), 'italic'), spans)
        self.assertEqual(offsets, sorted(offsets))
        for phrase in ('In re Caden C.', '(2021)', '11 Cal.5th 614', 'next'):
            self.assertEqual(offsets[text.index(phrase)], rendered.index(phrase))
            self.assertEqual(offsets[text.index(phrase) + len(phrase)],
                             rendered.index(phrase) + len(phrase))
        buffer = Gtk.TextBuffer()
        buffer.set_text(rendered)
        reader = SimpleNamespace(reader_buffer=buffer)
        OpenLawLensWindow._apply_reader_markdown_spans(reader, spans)
        for phrase in ('In re Caden C.', '11 Cal.5th 614'):
            tags = buffer.get_iter_at_offset(rendered.index(phrase)).get_tags()
            self.assertTrue(any(tag.get_property('weight') == 700 for tag in tags))

    def test_nested_emphasis_and_prior_brief_links(self):
        formatter = _AgentAnswerTextFormatter()
        for markup, expected in (
            ('***both***', 'both'),
            ('**before *inside* after**', 'before inside after'),
            ('**first** and **second**', 'first and second'),
            ('unmatched **', 'unmatched **'),
        ):
            with self.subTest(markup=markup):
                rendered, _, _ = formatter._render_markdown_text(markup)
                self.assertEqual(rendered, expected)
        target = 'a' * 64
        markup = f'**[*Brief*](open-law-lens://prior-brief/{target}) and *case***'
        rendered, spans, _ = formatter._render_markdown_text(markup)
        self.assertEqual(rendered, 'Brief and case')
        self.assertIn((0, 5, f'prior_brief:{target}'), spans)
        self.assertIn((0, 5, 'italic'), spans)
        self.assertIn((0, 14, 'bold'), spans)

    def test_quoted_declaration_cannot_become_default_after_delimiters_removed(self):
        declaration = 'All statutory references are to the Welfare and Institutions Code.'
        for quoted in (f'“{declaration}”', f'> {declaration}', f'"{declaration}"'):
            plan = prepare_answer(quoted + '\n\nsection 300', 'general', [],
                                  _AgentAnswerTextFormatter().format,
                                  OpenLawLensWindow._external_url_links)
            self.assertFalse([s for s in plan.styles if s.kind == 'statute'])
        plan = prepare_answer('All statutory references are to the **Welfare and Institutions Code**.\n\nsection 300',
                              'general', [], _AgentAnswerTextFormatter().format,
                              OpenLawLensWindow._external_url_links)
        self.assertEqual(len([s for s in plan.styles if s.kind == 'statute']), 1)

    def test_prepared_quotes_links_and_unicode_offsets(self):
        source = CaseTextSource('', '', 'Synthetic Opening', '', '',
            'Résumé: children who witnessed the threats qualify.',
            authority_type='prior_brief', prior_brief_id='a' * 64)
        text = ('# Synthetic Child Inclusion\n*Qualified advocacy*\n\n'
                f'[Synthetic Opening](open-law-lens://prior-brief/{source.prior_brief_id}) '
                'argues “children who witnessed the threats”.')
        plan = prepare_answer(text, 'brief', [source], _AgentAnswerTextFormatter().format,
                              OpenLawLensWindow._external_url_links)
        quote = next(s for s in plan.styles if s.kind == 'quote')
        self.assertEqual(plan.text[quote.start:quote.end], 'children who witnessed the threats')
        self.assertEqual(quote.target.prior_brief_id, source.prior_brief_id)
        self.assertTrue(any(s.kind == 'title' for s in plan.styles))
        self.assertNotIn('“', plan.text)
        self.assertNotIn('open-law-lens://', plan.text)
