from __future__ import annotations

import tempfile
import unittest
from importlib import resources
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from open_law_lens.app import (
    AGENT_MODE_BRIEF,
    AGENT_MODE_ICONS,
    READER_CLIPBOARD_ICON,
    SCHOLAR_FALLBACK_NOTICE_ONLY,
    SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
    Gtk,
    Pango,
    LinkPressState,
    OpenLawLensApp,
    OpenLawLensWindow,
    appeal_issue_menu_label,
    build_agent_launch_env,
    build_case_reader_payload,
    strip_agent_legal_authority_backticks,
)
from open_law_lens.agent import CaseTextSource, QuoteTarget
from open_law_lens.cache import JsonCache
from open_law_lens.citation_links import CitedCaseLink
from open_law_lens.client import CourtListenerClient, FormattedCitation
from open_law_lens.config import AppConfig
from open_law_lens.current_case import CurrentCaseSocf
from open_law_lens.fact_patterns import FactPatternExport
from open_law_lens.library import CaseLibrary, DisplayText, PageMarker, ResearchSet
from open_law_lens.opinion_formatting import DisplayStyleSpan
from open_law_lens.reader_highlights import ReaderHighlight
from open_law_lens.slip_opinions import SlipOpinionResult
from open_law_lens.web_import import ExtractedWebpage


class AppReaderPayloadTests(unittest.TestCase):
    def test_prior_brief_agent_uses_bundled_library_icon(self) -> None:
        icon_ref = resources.files("open_law_lens").joinpath(
            "icons",
            "hicolor",
            "scalable",
            "actions",
            "library-symbolic.svg",
        )

        self.assertEqual(AGENT_MODE_ICONS[AGENT_MODE_BRIEF], "library-symbolic")
        self.assertTrue(icon_ref.is_file())
        self.assertIn("<svg", icon_ref.read_text(encoding="utf-8"))

    def test_window_activation_refreshes_current_case_without_reloading_reader(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.refresh_count = 0

            def is_active(self) -> bool:
                return True

            def _refresh_current_case_context(self) -> CurrentCaseSocf | None:
                self.refresh_count += 1
                return CurrentCaseSocf(
                    case_name="B123456_Test",
                    case_dir=Path("/case"),
                    path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
                )

            def _open_current_case_socf(self) -> None:
                raise AssertionError("Window activation must not reload reader text")

        window = DummyWindow()

        OpenLawLensWindow._on_window_active_changed(  # type: ignore[arg-type]
            window,
            MagicMock(),
            MagicMock(),
        )

        self.assertEqual(window.refresh_count, 1)

    def test_inactive_window_does_not_refresh_current_case(self) -> None:
        class DummyWindow:
            def is_active(self) -> bool:
                return False

            def _refresh_current_case_context(self) -> None:
                raise AssertionError("Inactive windows must not refresh current-case state")

        OpenLawLensWindow._on_window_active_changed(  # type: ignore[arg-type]
            DummyWindow(),
            MagicMock(),
            MagicMock(),
        )

    def test_current_case_row_activation_explicitly_reloads_reader(self) -> None:
        case_list = MagicMock()
        open_current_case = MagicMock()
        window = SimpleNamespace(
            case_list=case_list,
            _open_current_case_socf=open_current_case,
        )

        OpenLawLensWindow._on_current_case_context_activated(  # type: ignore[arg-type]
            window,
            MagicMock(),
            MagicMock(),
        )

        case_list.unselect_all.assert_called_once_with()
        open_current_case.assert_called_once_with()

    def test_current_case_refresh_selects_context_and_reloads_reader(self) -> None:
        case_list = MagicMock()
        current_case_list = MagicMock()
        current_case_row = object()
        open_current_case = MagicMock()
        window = SimpleNamespace(
            case_list=case_list,
            _current_case_context_list=current_case_list,
            _current_case_context_row=current_case_row,
            _open_current_case_socf=open_current_case,
        )

        OpenLawLensWindow._on_refresh_current_case_clicked(  # type: ignore[arg-type]
            window,
            MagicMock(),
        )

        case_list.unselect_all.assert_called_once_with()
        current_case_list.select_row.assert_called_once_with(current_case_row)
        open_current_case.assert_called_once_with()

    def test_reader_highlight_button_uses_bundled_icon(self) -> None:
        class DummyWindow:
            def _on_toggle_reader_highlight_clicked(self, *_args: object) -> None:
                pass

        window = DummyWindow()
        button = OpenLawLensWindow._build_reader_highlight_button(  # type: ignore[arg-type]
            window
        )
        icon_ref = resources.files("open_law_lens").joinpath(
            "icons",
            "hicolor",
            "scalable",
            "actions",
            "highlighter-symbolic.svg",
        )

        self.assertEqual(button.get_icon_name(), "highlighter-symbolic")
        self.assertFalse(button.get_sensitive())
        self.assertTrue(icon_ref.is_file())

    def test_reader_clipboard_button_uses_bundled_icon(self) -> None:
        icon_ref = resources.files("open_law_lens").joinpath(
            "icons",
            "hicolor",
            "scalable",
            "actions",
            "clipboard-symbolic.svg",
        )

        self.assertEqual(READER_CLIPBOARD_ICON, "clipboard-symbolic")
        self.assertTrue(icon_ref.is_file())

    def test_reader_highlight_button_excludes_saved_agent_answers(self) -> None:
        button = MagicMock()

        class DummyWindow:
            _reader_position_key = ("agent_answer", "answer")
            _reader_highlight_button = button
            _reader_text = "Saved answer text"

            _reader_highlight_key = OpenLawLensWindow._reader_highlight_key

            def _reader_selection_bounds(self) -> tuple[int, int, str]:
                raise AssertionError("Agent answers must not inspect highlight selection")

        OpenLawLensWindow._update_reader_highlight_button(DummyWindow())  # type: ignore[arg-type]

        button.set_sensitive.assert_called_once_with(False)
        button.set_tooltip_text.assert_called_once_with("Highlight selected text")

    def test_reader_highlight_button_offers_remove_for_selection_inside_highlight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_reader_highlights(
                "case",
                "42",
                [ReaderHighlight(0, 10, "Alpha beta")],
            )
            button = MagicMock()

            class DummyWindow:
                _reader_position_key = ("case", "42")
                _reader_highlight_button = button
                _reader_text = "Alpha beta gamma"
                client = SimpleNamespace(cache=cache)
                _reader_highlight_key = OpenLawLensWindow._reader_highlight_key

                def _reader_selection_bounds(self) -> tuple[int, int, str]:
                    return 2, 7, "pha b"

            OpenLawLensWindow._update_reader_highlight_button(  # type: ignore[arg-type]
                DummyWindow()
            )

            button.set_sensitive.assert_called_once_with(True)
            button.set_tooltip_text.assert_called_once_with("Remove highlight")

    def test_reader_highlight_action_adds_applies_and_removes_highlight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))

            class DummyWindow:
                _reader_position_key = ("case", "42")
                _reader_text = "Alpha beta gamma."
                _reader_saved_highlight_tag = object()
                client = SimpleNamespace(cache=cache)

                _reader_highlight_key = OpenLawLensWindow._reader_highlight_key
                _reader_selection_bounds = OpenLawLensWindow._reader_selection_bounds
                _apply_saved_reader_highlights = (
                    OpenLawLensWindow._apply_saved_reader_highlights
                )

                def __init__(self) -> None:
                    self.reader_buffer = Gtk.TextBuffer()
                    self.reader_buffer.set_text(self._reader_text)
                    self._reader_saved_highlight_tag = self.reader_buffer.create_tag(
                        "saved-highlight-test"
                    )
                    self.status = ""

                def _set_status(self, text: str) -> None:
                    self.status = text

            window = DummyWindow()
            window.reader_buffer.select_range(
                window.reader_buffer.get_iter_at_offset(0),
                window.reader_buffer.get_iter_at_offset(5),
            )

            OpenLawLensWindow._on_toggle_reader_highlight_clicked(  # type: ignore[arg-type]
                window,
                MagicMock(),
            )

            self.assertEqual(
                cache.reader_highlights("case", "42"),
                [ReaderHighlight(0, 5, "Alpha", "", " beta gamma.")],
            )
            self.assertIn(
                window._reader_saved_highlight_tag,
                window.reader_buffer.get_iter_at_offset(2).get_tags(),
            )
            self.assertEqual(window.status, "Highlighted selected text.")

            window.reader_buffer.select_range(
                window.reader_buffer.get_iter_at_offset(1),
                window.reader_buffer.get_iter_at_offset(4),
            )
            OpenLawLensWindow._on_toggle_reader_highlight_clicked(  # type: ignore[arg-type]
                window,
                MagicMock(),
            )

            self.assertEqual(cache.reader_highlights("case", "42"), [])
            self.assertNotIn(
                window._reader_saved_highlight_tag,
                window.reader_buffer.get_iter_at_offset(2).get_tags(),
            )
            self.assertEqual(window.status, "Removed highlight.")

    def test_capture_reader_position_saves_top_visible_text_offset(self) -> None:
        class DummyCache:
            def __init__(self) -> None:
                self.saved: tuple[str, str, int] | None = None

            def set_reader_position(self, item_type: str, authority_id: str, offset: int) -> None:
                self.saved = (item_type, authority_id, offset)

        class DummyIter:
            def get_offset(self) -> int:
                return 321

        class DummyView:
            def get_visible_rect(self) -> SimpleNamespace:
                return SimpleNamespace(x=0, y=480)

            def get_iter_at_position(self, x: int, y: int) -> tuple[bool, DummyIter, int]:
                self.coords = (x, y)
                return False, DummyIter(), 0

        cache = DummyCache()
        window = SimpleNamespace(
            _reader_position_key=("case", "42"),
            _reader_text="Long opinion text",
            reader_view=DummyView(),
            client=SimpleNamespace(cache=cache),
        )

        OpenLawLensWindow._capture_current_reader_position(window)  # type: ignore[arg-type]

        self.assertEqual(cache.saved, ("case", "42", 321))

    def test_restore_reader_position_clamps_offset_and_scrolls_to_top(self) -> None:
        class DummyBuffer:
            def get_char_count(self) -> int:
                return 100

            def get_iter_at_offset(self, offset: int) -> int:
                return offset

        class DummyView:
            def __init__(self) -> None:
                self.scrolls: list[tuple[object, ...]] = []

            def scroll_to_iter(self, *args: object) -> None:
                self.scrolls.append(args)

        window = SimpleNamespace(
            _case_load_generation=7,
            _reader_position_key=("case", "42"),
            _pending_quote_target=None,
            _reader_text="x" * 100,
            reader_buffer=DummyBuffer(),
            reader_view=DummyView(),
        )

        result = OpenLawLensWindow._restore_reader_position(  # type: ignore[arg-type]
            window,
            ("case", "42"),
            7,
            250,
        )

        self.assertFalse(result)
        self.assertEqual(window.reader_view.scrolls, [(100, 0.0, True, 0.0, 0.0)])

    def test_restore_reader_position_does_not_override_pending_quote(self) -> None:
        window = SimpleNamespace(
            _case_load_generation=7,
            _reader_position_key=("case", "42"),
            _pending_quote_target=object(),
            _reader_text="opinion text",
        )

        result = OpenLawLensWindow._restore_reader_position(  # type: ignore[arg-type]
            window,
            ("case", "42"),
            7,
            20,
        )

        self.assertFalse(result)

    def test_schedule_reader_position_restore_queues_saved_offset(self) -> None:
        restore = object()
        window = SimpleNamespace(
            _reader_position_key=("rule", "CRC:8.11"),
            _pending_quote_target=None,
            _case_load_generation=4,
            _restore_reader_position=restore,
            client=SimpleNamespace(
                cache=SimpleNamespace(
                    reader_position=lambda item_type, authority_id: (
                        77 if (item_type, authority_id) == ("rule", "CRC:8.11") else None
                    )
                )
            ),
        )

        with patch("open_law_lens.app.GLib.idle_add") as idle_add:
            OpenLawLensWindow._schedule_reader_position_restore(  # type: ignore[arg-type]
                window
            )

        idle_add.assert_called_once_with(restore, ("rule", "CRC:8.11"), 4, 77)

    def test_case_agent_render_links_only_resolved_quotes_and_keeps_delimiters(self) -> None:
        class DummyTagTable:
            def remove(self, _tag: object) -> None:
                pass

        class DummyBuffer:
            def __init__(self) -> None:
                self.text = ""
                self.tags: list[tuple[object, int, int]] = []
                self.created_props: list[dict[str, object]] = []
                self.table = DummyTagTable()

            def get_tag_table(self) -> DummyTagTable:
                return self.table

            def set_text(self, text: str) -> None:
                self.text = text

            def create_tag(self, _name: object, **_props: object) -> object:
                self.created_props.append(_props)
                return object()

            def get_iter_at_offset(self, offset: int) -> int:
                return offset

            def apply_tag(self, tag: object, start: int, end: int) -> None:
                self.tags.append((tag, start, end))

        class DummyWindow:
            def __init__(self) -> None:
                self._agent_answer_buffer = DummyBuffer()
                self._agent_link_tags: list[object] = []
                self._agent_link_lookup: dict[object, QuoteTarget] = {}
                self._agent_citation_link_lookup: dict[object, object] = {}
                self._agent_external_url_link_lookup: dict[object, object] = {}
                self._agent_search_link_lookup: dict[object, object] = {}
                self._agent_search_next_link_tags: set[object] = set()
                self._agent_search_highlight_tags: list[object] = []
                self._agent_mode = "case"
                self._case_agent_text_sources = [
                    CaseTextSource(
                        "42",
                        "10",
                        "Example",
                        "1 Cal.App.5th 2",
                        "/tmp/source",
                        "The court found active risk today.",
                    )
                ]

            def _render_markdown_text(
                self,
                text: str,
            ) -> tuple[str, list[tuple[int, int, str]], list[int]]:
                return text, [], list(range(len(text) + 1))

            def _map_offset(self, offset: int, offset_map: list[int]) -> int:
                return OpenLawLensWindow._map_offset(  # type: ignore[arg-type]
                    self,
                    offset,
                    offset_map,
                )

            def _apply_agent_markdown_spans(self, *_args: object) -> None:
                pass

            def _apply_agent_citation_italics(self, *_args: object) -> None:
                pass

            def _resolve_agent_quote_color(self) -> object:
                return object()

            def _apply_agent_external_url_links(self, *_args: object) -> None:
                pass

        window = DummyWindow()
        answer = 'The court found “active risk today.” It rejected “unmatched phrase here.”'

        OpenLawLensWindow._render_agent_answer(window, answer)  # type: ignore[arg-type]

        self.assertEqual(window._agent_answer_buffer.text, answer)
        self.assertEqual(len(window._agent_link_lookup), 1)
        self.assertEqual(len(window._agent_answer_buffer.tags), 1)
        self.assertEqual(window._agent_answer_buffer.created_props[0]["weight"], Pango.Weight.BOLD)

    def test_plain_prior_brief_title_is_automatically_linked(self) -> None:
        class DummyBuffer:
            def __init__(self) -> None:
                self.tags: list[tuple[object, int, int]] = []

            def create_tag(self, _name: object, **_props: object) -> object:
                return object()

            def get_iter_at_offset(self, offset: int) -> int:
                return offset

            def apply_tag(self, tag: object, start: int, end: int) -> None:
                self.tags.append((tag, start, end))

        brief_id = "a" * 64
        source = CaseTextSource(
            cluster_id="",
            opinion_id="",
            title="B348009_RB_Breana_R",
            citation="2026-06-08",
            text_path="/tmp/brief.odt",
            text="Brief text",
            authority_type="prior_brief",
            prior_brief_id=brief_id,
        )
        window = SimpleNamespace(
            _case_agent_text_sources=[source],
            _agent_link_tags=[],
            _agent_link_lookup={},
            _resolve_agent_quote_color=lambda: object(),
        )
        buffer = DummyBuffer()

        OpenLawLensWindow._apply_agent_prior_brief_title_links(  # type: ignore[arg-type]
            window,
            buffer,  # type: ignore[arg-type]
            "The latest is B348009_RB_Breana_R.",
        )

        self.assertEqual(len(buffer.tags), 1)
        target = next(iter(window._agent_link_lookup.values()))
        self.assertEqual(target.prior_brief_id, brief_id)

    def test_quote_target_finds_sorted_sidebar_row_by_stable_identity(self) -> None:
        class DummyRow:
            def __init__(self, authority_type: str, authority_id: str) -> None:
                self._open_law_lens_authority_type = authority_type
                self._open_law_lens_authority_id = authority_id

        class DummyList:
            def __init__(self, rows: list[DummyRow]) -> None:
                self.rows = rows

            def get_row_at_index(self, index: int) -> DummyRow | None:
                return self.rows[index] if index < len(self.rows) else None

        expected = DummyRow("case", "cluster-42")
        window = SimpleNamespace(
            case_list=DummyList(
                [
                    DummyRow("statute", "WIC:300"),
                    expected,
                    DummyRow("rule", "CRC:8.11"),
                ]
            )
        )

        row = OpenLawLensWindow._research_cache_authority_row(  # type: ignore[arg-type]
            window,
            "case",
            "cluster-42",
        )

        self.assertIs(row, expected)

    def test_open_quote_target_selects_rule_row_and_defers_highlight(self) -> None:
        class DummyRow:
            _open_law_lens_authority_type = "rule"
            _open_law_lens_authority_id = "CRC:8.11"

        class DummyList:
            def __init__(self) -> None:
                self.row = DummyRow()
                self.selected: object | None = None

            def get_row_at_index(self, index: int) -> DummyRow | None:
                return self.row if index == 0 else None

            def get_selected_row(self) -> object | None:
                return self.selected

            def select_row(self, row: object) -> None:
                self.selected = row

        class DummyWindow:
            def __init__(self) -> None:
                self.case_list = DummyList()
                self._reader_text = ""
                self._pending_quote_target = None
                self._selected_rule = None
                self._selected_statute = None
                self._selected_cluster = None
                self.status = ""

            _quote_target_authority_id = staticmethod(OpenLawLensWindow._quote_target_authority_id)

            def _research_cache_authority_row(
                self,
                authority_type: str,
                authority_id: str,
            ) -> object:
                return OpenLawLensWindow._research_cache_authority_row(  # type: ignore[arg-type]
                    self,
                    authority_type,
                    authority_id,
                )

            def _quote_target_is_selected(self, target: QuoteTarget) -> bool:
                return OpenLawLensWindow._quote_target_is_selected(  # type: ignore[arg-type]
                    self,
                    target,
                )

            def _set_status(self, message: str) -> None:
                self.status = message

        target = QuoteTarget(
            phrase="governs computing time",
            cluster_id="",
            opinion_id="",
            title="Rule 8.11",
            citation="Cal. Rules of Court, rule 8.11",
            text_path="/tmp/rule",
            offset=10,
            end_offset=32,
            authority_type="rule",
            rule_id="CRC:8.11",
        )
        window = DummyWindow()

        OpenLawLensWindow._open_quote_target(window, target)  # type: ignore[arg-type]

        self.assertIs(window._pending_quote_target, target)
        self.assertIs(window.case_list.selected, window.case_list.row)

    def test_link_release_requires_same_target_without_drag(self) -> None:
        class DummyView:
            def __init__(self, dragged: bool) -> None:
                self.dragged = dragged

            def drag_check_threshold(self, *_args: int) -> bool:
                return self.dragged

        target = object()
        press = LinkPressState(target, 10.0, 12.0)

        self.assertTrue(
            OpenLawLensWindow._link_release_is_click(
                DummyView(False),  # type: ignore[arg-type]
                press,
                target,
                1,
                11.0,
                13.0,
            )
        )
        self.assertFalse(
            OpenLawLensWindow._link_release_is_click(
                DummyView(True),  # type: ignore[arg-type]
                press,
                target,
                1,
                30.0,
                40.0,
            )
        )
        self.assertFalse(
            OpenLawLensWindow._link_release_is_click(
                DummyView(False),  # type: ignore[arg-type]
                press,
                object(),
                1,
                11.0,
                13.0,
            )
        )

    def test_strip_agent_legal_authority_backticks_preserves_commands(self) -> None:
        text = (
            "See `DKN Holdings LLC v. Faerber (2015) 61 Cal.4th 813`, "
            "`Lucido v. Superior Court (1990) 51 Cal.3d 335`, "
            "`Fam. Code, § 7612`, and `Cal. Rules of Court, rule 8.204`. "
            "Run `uv run open-law-lens extract-case \"61 Cal.4th 813\"` "
            "from `/tmp/workspace`."
        )

        cleaned = strip_agent_legal_authority_backticks(text)

        self.assertIn("DKN Holdings LLC v. Faerber (2015) 61 Cal.4th 813", cleaned)
        self.assertIn("Lucido v. Superior Court (1990) 51 Cal.3d 335", cleaned)
        self.assertIn("Fam. Code, § 7612", cleaned)
        self.assertIn("Cal. Rules of Court, rule 8.204", cleaned)
        self.assertNotIn("`DKN Holdings LLC", cleaned)
        self.assertNotIn("`Lucido", cleaned)
        self.assertNotIn("`Fam. Code", cleaned)
        self.assertNotIn("`Cal. Rules", cleaned)
        self.assertIn('`uv run open-law-lens extract-case "61 Cal.4th 813"`', cleaned)
        self.assertIn("`/tmp/workspace`", cleaned)

    def test_research_cache_case_row_text_uses_slip_placeholder_citation(self) -> None:
        cluster = {
            "case_name_short": "In re L.G.",
            "date_filed": "2026-03-06",
            "docket": {"docket_number": "A173218"},
            "precedential_status": "Published",
        }

        title, citation = OpenLawLensWindow._research_cache_case_row_text(cluster)

        self.assertEqual(title, "In re L.G.")
        self.assertEqual(citation, "(Mar. 6, 2026, A173218) ___ Cal.App.5th ___")

    def test_research_cache_case_row_text_prefers_official_reporter_citation(self) -> None:
        cluster = {
            "case_name_short": "In re L.G.",
            "date_filed": "2026-03-06",
            "docket": {"docket_number": "A173218"},
            "citations": [{"volume": "12", "reporter": "Cal.App.5th", "page": "345"}],
        }

        title, citation = OpenLawLensWindow._research_cache_case_row_text(cluster)

        self.assertEqual(title, "In re L.G.")
        self.assertEqual(citation, "(2026) 12 Cal.App.5th 345")

    def test_research_cache_case_row_text_does_not_make_unpublished_placeholder(self) -> None:
        cluster = {
            "case_name_short": "In re L.G.",
            "date_filed": "2026-03-06",
            "docket": {"docket_number": "A173218"},
            "precedential_status": "Unpublished",
        }

        title, citation = OpenLawLensWindow._research_cache_case_row_text(cluster)

        self.assertEqual(title, "In re L.G.")
        self.assertEqual(citation, "")

    def test_agent_launch_env_defaults_to_workspace_sandbox(self) -> None:
        class DummyCache:
            root = Path("/tmp/open-law-lens-cache")

        class DummyLibrary:
            path = Path("/tmp/open-law-lens-library/library.sqlite3")

        class DummyClient:
            cache = DummyCache()
            library = DummyLibrary()

        env = build_agent_launch_env(
            DummyClient(),  # type: ignore[arg-type]
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            "general",
            AppConfig(),
        )

        self.assertEqual(env["OPEN_LAW_LENS_CODEX_SANDBOX"], "workspace-write")
        self.assertEqual(env["OPEN_LAW_LENS_CODEX_APPROVAL"], "")
        self.assertEqual(env["OPEN_LAW_LENS_CACHE_DIR"], "/tmp/workspace/research-cache")
        self.assertEqual(
            env["OPEN_LAW_LENS_LIBRARY_DB"],
            "/tmp/open-law-lens-library/library.sqlite3",
        )
        self.assertNotIn("OPEN_LAW_LENS_CODEX_REASONING_EFFORT", env)

    def test_agent_launch_env_full_access_disables_approval_prompts(self) -> None:
        class DummyCache:
            root = Path("/tmp/open-law-lens-cache")

        class DummyClient:
            cache = DummyCache()
            library = None

        env = build_agent_launch_env(
            DummyClient(),  # type: ignore[arg-type]
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            "case",
            AppConfig(agent_permission_mode="full_access"),
        )

        self.assertEqual(env["OPEN_LAW_LENS_AGENT_MODE"], "case")
        self.assertEqual(env["OPEN_LAW_LENS_CODEX_SANDBOX"], "danger-full-access")
        self.assertEqual(env["OPEN_LAW_LENS_CODEX_APPROVAL"], "never")
        self.assertNotIn("OPEN_LAW_LENS_LIBRARY_DB", env)

    def test_case_agent_prompt_adds_current_case_context_to_custom_prompt(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        authority_export = SimpleNamespace(
            manifest_path=Path("/tmp/workspace/selected_authorities/manifest.json"),
            case_dir=Path("/tmp/workspace/selected_authorities"),
            case_count=2,
            authority_count=2,
        )
        fact_export = FactPatternExport(
            source_path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
            source_copy_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM.odt"),
            text_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM_extracted.txt"),
            text="Current-case facts. (CT 12.)",
        )

        with patch(
            "open_law_lens.app.load_config",
            return_value=AppConfig(case_agent_prompt_template="Custom cache prompt: {question}"),
        ):
            prompt = OpenLawLensWindow._compose_case_agent_prompt(  # type: ignore[arg-type]
                DummyWindow(),
                "Which case is most analogous?",
                authority_export,
                fact_export,
                True,
            )

        self.assertIn("Custom cache prompt: Which case is most analogous?", prompt)
        self.assertIn("within the authorized scope", prompt)
        self.assertIn("Treat it as facts, not legal authority", prompt)
        self.assertIn(str(fact_export.text_path), prompt)
        self.assertIn(str(fact_export.source_copy_path), prompt)
        self.assertIn("do not cite local paths", prompt)

    def test_general_agent_prompt_adds_socf_only_when_selected(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        fact_export = FactPatternExport(
            source_path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
            source_copy_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM.odt"),
            text_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM_extracted.txt"),
            text="Current-case facts. (CT 12.)",
        )
        with patch(
            "open_law_lens.app.load_config",
            return_value=AppConfig(general_agent_prompt_template="Custom law prompt: {question}"),
        ):
            without_context = OpenLawLensWindow._compose_general_agent_prompt(  # type: ignore[arg-type]
                DummyWindow(),
                "What law applies?",
            )
            with_context = OpenLawLensWindow._compose_general_agent_prompt(  # type: ignore[arg-type]
                DummyWindow(),
                "What law applies?",
                fact_export,
                True,
            )

        self.assertEqual(without_context, "Custom law prompt: What law applies?")
        self.assertIn(str(fact_export.text_path), with_context)
        self.assertIn("Treat it as facts, not legal authority", with_context)

    def test_case_agent_prompt_marks_socf_as_not_selected(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        authority_export = SimpleNamespace(
            manifest_path=Path("/tmp/manifest.json"),
            case_dir=Path("/tmp/selected_authorities"),
            case_count=1,
            authority_count=1,
        )
        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            prompt = OpenLawLensWindow._compose_case_agent_prompt(  # type: ignore[arg-type]
                DummyWindow(),
                "What do the authorities establish?",
                authority_export,
            )

        self.assertIn("Current-case factual context for this run:\nNot selected", prompt)
        self.assertNotIn("Extracted fact-pattern text", prompt)

    def test_general_agent_worker_exports_checked_socf(self) -> None:
        fact_export = FactPatternExport(
            source_path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
            source_copy_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM.odt"),
            text_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM_extracted.txt"),
            text="Current-case facts.",
        )
        resolved = CurrentCaseSocf(
            case_name="B123456_Test",
            case_dir=Path("/case"),
            path=fact_export.source_path,
        )

        class DummyWindow:
            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/workspace")

            def _compose_general_agent_prompt(self, *args: object) -> str:
                self.compose_args = args
                return "prompt"

            def _write_prompt_file(self, _prompt: str) -> Path:
                return Path("/tmp/prompt.txt")

            def _finish_general_agent_prepare(self, *args: object) -> bool:
                return False

            def _set_status(self, status: str) -> None:
                self.status = status

        window = DummyWindow()
        with (
            patch("open_law_lens.app.export_fact_pattern", return_value=fact_export) as export,
            patch("open_law_lens.app.GLib.idle_add") as idle_add,
        ):
            OpenLawLensWindow._prepare_general_agent_worker(  # type: ignore[arg-type]
                window,
                "What law applies?",
                resolved,
                True,
                "",
            )

        export.assert_called_once_with(
            fact_export.source_path,
            Path("/tmp/workspace/current_case_fact_pattern"),
        )
        self.assertEqual(window.compose_args[1], fact_export)
        self.assertTrue(window.compose_args[2])
        idle_add.assert_called_once_with(
            window._finish_general_agent_prepare,
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            True,
            "",
        )

    def test_current_case_socf_load_ignores_stale_results(self) -> None:
        resolved = CurrentCaseSocf(
            case_name="B123456_Test",
            case_dir=Path("/case"),
            path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
        )

        class DummyWindow:
            _case_load_generation = 3

            def __init__(self) -> None:
                self.texts: list[str] = []
                self.statuses: list[str] = []

            def _set_reader_text(self, text: str) -> None:
                self.texts.append(text)

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

        window = DummyWindow()
        stale = OpenLawLensWindow._finish_current_case_socf_load(  # type: ignore[arg-type]
            window,
            resolved,
            "Old text",
            2,
        )
        current = OpenLawLensWindow._finish_current_case_socf_load(  # type: ignore[arg-type]
            window,
            resolved,
            "Current text",
            3,
        )

        self.assertFalse(stale)
        self.assertFalse(current)
        self.assertEqual(window.texts, ["Current text"])
        self.assertEqual(window.statuses, ["Loaded the current-case SOCF for B123456_Test."])

    def test_case_agent_prompt_reports_missing_current_case_context(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        authority_export = SimpleNamespace(
            manifest_path=Path("/tmp/manifest.json"),
            case_dir=Path("/tmp/selected_authorities"),
            case_count=1,
            authority_count=1,
        )

        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            prompt = OpenLawLensWindow._compose_case_agent_prompt(  # type: ignore[arg-type]
                DummyWindow(),
                "Compare the cases.",
                authority_export,
                None,
                True,
                "SOCF ODT not found",
            )

        self.assertIn("Unavailable: SOCF ODT not found", prompt)
        self.assertIn("Do not guess about the current case", prompt)

    def test_case_agent_finish_uses_context_aware_status(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._case_agent_text_sources: list[object] = []
                self._agent_mode = "general"
                self.launches: list[dict[str, object]] = []

            def _launch_agent_with_prompt(
                self,
                prompt_path: Path,
                workspace: Path,
                mode: str,
                reasoning_effort: str = "",
                success_status: str = "",
            ) -> None:
                self.launches.append(
                    {
                        "prompt_path": prompt_path,
                        "workspace": workspace,
                        "mode": mode,
                        "reasoning_effort": reasoning_effort,
                        "success_status": success_status,
                    }
                )

        window = DummyWindow()
        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            result = OpenLawLensWindow._finish_case_agent_prepare(  # type: ignore[arg-type]
                window,
                Path("/tmp/prompt.txt"),
                Path("/tmp/workspace"),
                [],
                False,
                "Current case file not found",
            )

        self.assertFalse(result)
        self.assertEqual(window._agent_mode, "case")
        self.assertEqual(
            window.launches[0]["success_status"],
            "Started Cache Agent without selected current-case SOCF; see the session for details.",
        )

    def test_case_agent_worker_exports_current_case_socf(self) -> None:
        fact_export = FactPatternExport(
            source_path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
            source_copy_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM.odt"),
            text_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM_extracted.txt"),
            text="Current-case facts.",
        )
        authority_export = SimpleNamespace(
            authority_count=1,
            case_count=1,
            text_sources=["source"],
        )

        class DummyWindow:
            def __init__(self) -> None:
                self.client = object()
                self.compose_args: tuple[object, ...] = ()

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/workspace")

            def _compose_case_agent_prompt(self, *args: object) -> str:
                self.compose_args = args
                return "prompt"

            def _write_prompt_file(self, prompt: str) -> Path:
                self.assert_prompt = prompt
                return Path("/tmp/prompt.txt")

            def _finish_case_agent_prepare(self, *args: object) -> bool:
                return False

            def _set_status(self, status: str) -> None:
                self.status = status

        window = DummyWindow()
        with (
            patch(
                "open_law_lens.app.export_selected_authorities",
                return_value=authority_export,
            ),
            patch(
                "open_law_lens.app.export_fact_pattern",
                return_value=fact_export,
            ) as export_current_case,
            patch("open_law_lens.app.GLib.idle_add") as idle_add,
        ):
            OpenLawLensWindow._prepare_case_agent_worker(  # type: ignore[arg-type]
                window,
                "Compare the cases.",
                [{}],
                [],
                [],
                [],
                CurrentCaseSocf(
                    case_name="B123456_Test",
                    case_dir=Path("/case"),
                    path=fact_export.source_path,
                ),
                True,
            )

        export_current_case.assert_called_once_with(
            fact_export.source_path,
            Path("/tmp/workspace/current_case_fact_pattern"),
        )
        self.assertEqual(window.compose_args[2], fact_export)
        self.assertTrue(window.compose_args[3])
        self.assertEqual(window.compose_args[4], "")
        idle_add.assert_called_once_with(
            window._finish_case_agent_prepare,
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            ["source"],
            True,
            "",
        )

    def test_case_agent_worker_does_not_export_unchecked_socf(self) -> None:
        authority_export = SimpleNamespace(
            authority_count=1,
            case_count=1,
            text_sources=["source"],
        )

        class DummyWindow:
            client = object()

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/workspace")

            def _compose_case_agent_prompt(self, *args: object) -> str:
                self.compose_args = args
                return "prompt"

            def _write_prompt_file(self, _prompt: str) -> Path:
                return Path("/tmp/prompt.txt")

            def _finish_case_agent_prepare(self, *args: object) -> bool:
                return False

            def _set_status(self, status: str) -> None:
                self.status = status

        window = DummyWindow()
        with (
            patch(
                "open_law_lens.app.export_selected_authorities",
                return_value=authority_export,
            ),
            patch("open_law_lens.app.export_fact_pattern") as export_current_case,
            patch("open_law_lens.app.GLib.idle_add") as idle_add,
        ):
            OpenLawLensWindow._prepare_case_agent_worker(  # type: ignore[arg-type]
                window,
                "Explain the authorities.",
                [{}],
                [],
                [],
                [],
                CurrentCaseSocf(
                    case_name="B123456_Test",
                    case_dir=Path("/case"),
                    path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
                ),
                False,
            )

        export_current_case.assert_not_called()
        self.assertIsNone(window.compose_args[2])
        self.assertFalse(window.compose_args[3])
        idle_add.assert_called_once_with(
            window._finish_case_agent_prepare,
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            ["source"],
            False,
            "",
        )

    def test_case_agent_worker_allows_selected_socf_without_authorities(self) -> None:
        fact_export = FactPatternExport(
            source_path=Path("/case/SOCF/B123456_SOCF_JM.odt"),
            source_copy_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM.odt"),
            text_path=Path("/tmp/workspace/current_case/B123456_SOCF_JM_extracted.txt"),
            text="Current-case facts.",
        )
        authority_export = SimpleNamespace(
            authority_count=0,
            case_count=0,
            text_sources=[],
        )

        class DummyWindow:
            client = object()

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/workspace")

            def _compose_case_agent_prompt(self, *args: object) -> str:
                return "prompt"

            def _write_prompt_file(self, _prompt: str) -> Path:
                return Path("/tmp/prompt.txt")

            def _finish_case_agent_prepare(self, *args: object) -> bool:
                return False

            def _set_status(self, status: str) -> None:
                self.status = status

        window = DummyWindow()
        with (
            patch(
                "open_law_lens.app.export_selected_authorities",
                return_value=authority_export,
            ),
            patch("open_law_lens.app.export_fact_pattern", return_value=fact_export),
            patch("open_law_lens.app.GLib.idle_add") as idle_add,
        ):
            OpenLawLensWindow._prepare_case_agent_worker(  # type: ignore[arg-type]
                window,
                "Summarize the relevant facts.",
                [],
                [],
                [],
                [],
                CurrentCaseSocf(
                    case_name="B123456_Test",
                    case_dir=Path("/case"),
                    path=fact_export.source_path,
                ),
                True,
            )

        idle_add.assert_called_once_with(
            window._finish_case_agent_prepare,
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            [],
            True,
            "",
        )

    def test_agent_launch_env_passes_xhigh_reasoning_when_enabled(self) -> None:
        class DummyCache:
            root = Path("/tmp/open-law-lens-cache")

        class DummyClient:
            cache = DummyCache()
            library = None

        env = build_agent_launch_env(
            DummyClient(),  # type: ignore[arg-type]
            Path("/tmp/prompt.txt"),
            Path("/tmp/workspace"),
            "appeal",
            AppConfig(),
            "xhigh",
        )

        self.assertEqual(env["OPEN_LAW_LENS_CODEX_REASONING_EFFORT"], "xhigh")

    def test_appeal_issue_prompt_includes_argument_fact_pattern_and_cli_guidance(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        window = DummyWindow()
        export = FactPatternExport(
            source_path=Path("/case/facts.odt"),
            source_copy_path=Path("/tmp/workspace/fact_pattern/facts.odt"),
            text_path=Path("/tmp/workspace/fact_pattern/facts_extracted.txt"),
            text="Fact text.",
        )

        prompt = OpenLawLensWindow._compose_appeal_issue_agent_prompt(  # type: ignore[arg-type]
            window,
            "The court applied the wrong standard.",
            export,
        )

        self.assertIn("The court applied the wrong standard.", prompt)
        self.assertIn("Argument to assess:", prompt)
        self.assertNotIn("Issue to assess:", prompt)
        self.assertIn("/tmp/workspace/fact_pattern/facts_extracted.txt", prompt)
        self.assertIn("uv run open-law-lens case-search", prompt)
        self.assertIn(
            'extract-case "<official citation or case name>"` first',
            prompt,
        )
        self.assertIn("extract-case --cluster-id <cluster_id>` only", prompt)
        self.assertIn("Record citation format for final answers:", prompt)
        self.assertIn("Do not cite local paths", prompt)
        self.assertIn("(RT 6, 34; CT 140, 190.)", prompt)
        self.assertIn("use normal legal prose for case names", prompt)
        self.assertIn("Reserve backticks for CLI commands", prompt)
        self.assertIn("Rating: Strong, Medium, Weak, or Frivolous", prompt)
        self.assertNotIn("Use Frivolous only when", prompt)

    def test_appeal_issue_start_requires_embedded_terminal(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._agent_terminal = None
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _prepare_appeal_issue_worker(
                self,
                issue: str,
                fact_pattern_path: Path,
                workspace: Path,
            ) -> None:
                pass

        window = DummyWindow()

        with patch("open_law_lens.app.Vte", None):
            result = OpenLawLensWindow.start_appeal_issue_assessment(  # type: ignore[arg-type]
                window,
                "Issue",
                Path("/tmp/facts.odt"),
            )

        self.assertFalse(result)
        self.assertEqual(window.statuses, ["Embedded terminal is unavailable."])

    def test_appeal_issue_start_creates_workspace_and_thread(self) -> None:
        class DummyThread:
            created: list[tuple[object, tuple[object, ...]]] = []

            def __init__(self, target: object, args: tuple[object, ...], daemon: bool) -> None:
                self.target = target
                self.args = args
                self.daemon = daemon
                DummyThread.created.append((target, args))
                self.started = False

            def start(self) -> None:
                self.started = True

        class DummyWindow:
            def __init__(self) -> None:
                self._agent_terminal = object()
                self.statuses: list[str] = []

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/appeal-workspace")

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _prepare_appeal_issue_worker(
                self,
                issue: str,
                fact_pattern_path: Path,
                workspace: Path,
            ) -> None:
                pass

        window = DummyWindow()

        with patch("open_law_lens.app.Vte", object()):
            with patch("open_law_lens.app.threading.Thread", DummyThread):
                result = OpenLawLensWindow.start_appeal_issue_assessment(  # type: ignore[arg-type]
                    window,
                    "Issue",
                    Path("/tmp/facts.odt"),
                )

        self.assertTrue(result)
        self.assertEqual(window.statuses, ["Preparing appeal issue assessment..."])
        self.assertEqual(
            DummyThread.created[0][1],
            ("Issue", Path("/tmp/facts.odt"), Path("/tmp/appeal-workspace")),
        )

    def test_appeal_issue_finish_launches_appeal_mode(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._case_agent_text_sources = ["old"]
                self._agent_mode = "general"
                self.launches: list[tuple[Path, Path, str, str]] = []

            def _launch_agent_with_prompt(
                self,
                prompt_path: Path,
                workspace: Path,
                mode: str,
                reasoning_effort: str = "",
            ) -> None:
                self.launches.append((prompt_path, workspace, mode, reasoning_effort))

        window = DummyWindow()

        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            result = OpenLawLensWindow._finish_appeal_issue_prepare(  # type: ignore[arg-type]
                window,
                Path("/tmp/prompt.txt"),
                Path("/tmp/workspace"),
            )

        self.assertFalse(result)
        self.assertEqual(window._case_agent_text_sources, [])
        self.assertEqual(window._agent_mode, "appeal")
        self.assertEqual(
            window.launches,
            [(Path("/tmp/prompt.txt"), Path("/tmp/workspace"), "appeal", "")],
        )

    def test_appeal_issue_menu_label_uses_label_then_first_nonblank_line_and_truncates(self) -> None:
        self.assertEqual(
            appeal_issue_menu_label("Full argument text.", "  Short label  "),
            "Short label",
        )
        self.assertEqual(
            appeal_issue_menu_label("\n  First issue line.  \nSecond line."),
            "First issue line.",
        )
        self.assertEqual(appeal_issue_menu_label("", max_length=12), "Untitled argument")
        self.assertEqual(
            appeal_issue_menu_label("This issue description is too long", max_length=18),
            "This issue desc...",
        )

    def test_appeal_issue_button_uses_bundled_cafe_icon(self) -> None:
        class DummyWindow:
            def _refresh_appeal_issue_menu(self) -> None:
                pass

        button = OpenLawLensWindow._build_appeal_issue_menu_button(  # type: ignore[arg-type]
            DummyWindow(),
        )
        icon_ref = resources.files("open_law_lens").joinpath(
            "icons",
            "hicolor",
            "scalable",
            "actions",
            "cafe-symbolic.svg",
        )

        self.assertEqual(button.get_icon_name(), "cafe-symbolic")
        self.assertTrue(icon_ref.is_file())

    def test_appeal_issue_menu_includes_custom_argument_action(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._appeal_issue_menu_button = None

            def _on_custom_appeal_issue_clicked(self, *_args: object) -> None:
                pass

            def _on_appeal_issue_menu_item_clicked(self, *_args: object) -> None:
                pass

            def _on_appeal_issue_settings_clicked(self, *_args: object) -> None:
                pass

        def labels(widget: object) -> list[str]:
            found: list[str] = []
            child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
            while child is not None:
                if isinstance(child, Gtk.Button):
                    label = child.get_label()
                    if label:
                        found.append(label)
                else:
                    found.extend(labels(child))
                child = child.get_next_sibling()
            return found

        def button_label_xaligns(widget: object) -> list[float]:
            found: list[float] = []
            child = widget.get_first_child() if hasattr(widget, "get_first_child") else None
            while child is not None:
                if isinstance(child, Gtk.Button) and isinstance(child.get_child(), Gtk.Label):
                    found.append(child.get_child().get_xalign())
                else:
                    found.extend(button_label_xaligns(child))
                child = child.get_next_sibling()
            return found

        window = DummyWindow()
        window._appeal_issue_menu_button = Gtk.MenuButton()

        with patch(
            "open_law_lens.app.load_config",
            return_value=AppConfig(
                appeal_issue_presets=["Full argument one."],
                appeal_issue_labels=["Short one"],
            ),
        ):
            OpenLawLensWindow._refresh_appeal_issue_menu(window)  # type: ignore[arg-type]

        popover = window._appeal_issue_menu_button.get_popover()
        self.assertIsNotNone(popover)
        assert popover is not None
        self.assertEqual(
            labels(popover),
            [
                "Assess custom argument...",
                "Short one",
                "Edit appeal arguments...",
            ],
        )
        self.assertEqual(button_label_xaligns(popover), [0.0, 0.0, 0.0])

    def test_appeal_issue_by_index_uses_current_fact_pattern(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._appeal_fact_pattern_path_override = Path("/tmp/facts.odt")
                self.statuses: list[str] = []
                self.launches: list[tuple[str, Path]] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _appeal_fact_pattern_path(self) -> Path | None:
                return OpenLawLensWindow._appeal_fact_pattern_path(self)  # type: ignore[arg-type]

            def start_appeal_issue_assessment(self, issue: str, fact_pattern_path: Path) -> bool:
                self.launches.append((issue, fact_pattern_path))
                return True

        window = DummyWindow()

        with (
            patch("open_law_lens.app.load_config", return_value=AppConfig(appeal_issue_presets=["Issue one"])),
            patch.object(Path, "is_file", return_value=True),
        ):
            OpenLawLensWindow._start_appeal_issue_assessment_by_index(  # type: ignore[arg-type]
                window,
                0,
            )

        self.assertEqual(window.launches, [("Issue one", Path("/tmp/facts.odt"))])

    def test_appeal_issue_by_index_reports_missing_fact_pattern(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._appeal_fact_pattern_path_override = Path("/tmp/missing.odt")
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _appeal_fact_pattern_path(self) -> Path | None:
                return OpenLawLensWindow._appeal_fact_pattern_path(self)  # type: ignore[arg-type]

            def start_appeal_issue_assessment(self, issue: str, fact_pattern_path: Path) -> bool:
                raise AssertionError("assessment should not launch")

        window = DummyWindow()

        with (
            patch("open_law_lens.app.load_config", return_value=AppConfig(appeal_issue_presets=["Issue one"])),
            patch.object(Path, "is_file", return_value=False),
        ):
            OpenLawLensWindow._start_appeal_issue_assessment_by_index(  # type: ignore[arg-type]
                window,
                0,
            )

        self.assertEqual(window.statuses, ["Fact pattern file not found: /tmp/missing.odt"])

    def test_custom_appeal_issue_uses_current_fact_pattern(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.launches: list[tuple[str, Path]] = []

            def _appeal_fact_pattern_path(self) -> Path | None:
                return Path("/tmp/facts.odt")

            def start_appeal_issue_assessment(self, issue: str, fact_pattern_path: Path) -> bool:
                self.launches.append((issue, fact_pattern_path))
                return True

        window = DummyWindow()

        with patch.object(Path, "is_file", return_value=True):
            result = OpenLawLensWindow._start_custom_appeal_issue_assessment(  # type: ignore[arg-type]
                window,
                "  Strange one-off claim.  ",
            )

        self.assertTrue(result)
        self.assertEqual(window.launches, [("Strange one-off claim.", Path("/tmp/facts.odt"))])

    def test_custom_appeal_issue_reports_blank_issue(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _appeal_fact_pattern_path(self) -> Path | None:
                raise AssertionError("blank issue should stop before fact-pattern lookup")

        window = DummyWindow()

        result = OpenLawLensWindow._start_custom_appeal_issue_assessment(  # type: ignore[arg-type]
            window,
            "   ",
        )

        self.assertFalse(result)
        self.assertEqual(window.statuses, ["Enter an argument to assess."])

    def test_custom_appeal_issue_reports_missing_fact_pattern(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _appeal_fact_pattern_path(self) -> Path | None:
                return Path("/tmp/missing.odt")

            def start_appeal_issue_assessment(self, issue: str, fact_pattern_path: Path) -> bool:
                raise AssertionError("assessment should not launch")

        window = DummyWindow()

        with patch.object(Path, "is_file", return_value=False):
            result = OpenLawLensWindow._start_custom_appeal_issue_assessment(  # type: ignore[arg-type]
                window,
                "Issue",
            )

        self.assertFalse(result)
        self.assertEqual(window.statuses, ["Fact pattern file not found: /tmp/missing.odt"])

    def test_payload_combines_displays_and_offsets_page_markers(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "1", "reporter": "Cal.5th", "page": "1"}],
        }
        first = DisplayText(
            text="[*1] First opinion.",
            source_field="plain_text",
            page_markers=[
                PageMarker(
                    page_label="1",
                    marker_text="[*1]",
                    start_offset=0,
                    end_offset=4,
                    source_field="plain_text",
                )
            ],
            style_spans=[DisplayStyleSpan("heading", 5, 10)],
        )
        second = DisplayText(
            text="[*2] Second opinion cites Other v. Case (2020) 2 Cal.5th 10.",
            source_field="plain_text",
            page_markers=[
                PageMarker(
                    page_label="2",
                    marker_text="[*2]",
                    start_offset=0,
                    end_offset=4,
                    source_field="plain_text",
                )
            ],
            style_spans=[DisplayStyleSpan("heading", 5, 11)],
        )

        payload = build_case_reader_payload(
            cluster,
            [first, second],
            generation=7,
            opinion_source="Library",
        )

        self.assertEqual(payload.generation, 7)
        self.assertEqual(payload.cluster_id, "42")
        self.assertEqual(payload.opinion_source, "Library")
        self.assertEqual(payload.text, f"{first.text}\n\n{second.text}")
        self.assertEqual([marker.page_label for marker in payload.page_markers], ["1", "2"])
        self.assertEqual(payload.page_markers[1].start_offset, len(first.text) + 2)
        self.assertEqual(
            payload.style_spans,
            [
                DisplayStyleSpan("heading", 5, 10),
                DisplayStyleSpan("heading", len(first.text) + 7, len(first.text) + 13),
            ],
        )
        self.assertTrue(payload.quality_eligible)
        self.assertTrue(payload.italic_spans)
        self.assertEqual(payload.cited_links[0].lookup_text, "2 Cal.5th 10")

    def test_payload_uses_smart_quotes_without_shifting_offsets(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "1", "reporter": "Cal.5th", "page": "1"}],
        }
        display = DisplayText(
            text='[*2] The parent said, "I don\'t agree." See Other v. Case (2020) 2 Cal.5th 10.',
            source_field="plain_text",
            page_markers=[
                PageMarker(
                    page_label="2",
                    marker_text="[*2]",
                    start_offset=0,
                    end_offset=4,
                    source_field="plain_text",
                )
            ],
        )

        payload = build_case_reader_payload(cluster, [display])

        self.assertIn("\u201cI don\u2019t agree.\u201d", payload.text)
        self.assertEqual(len(payload.text), len(display.text))
        self.assertEqual(payload.text[payload.page_markers[0].start_offset:payload.page_markers[0].end_offset], "[*2]")
        self.assertEqual(payload.cited_links[0].lookup_text, "2 Cal.5th 10")

    def test_immediate_reader_text_applies_heading_style_spans(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.reader_buffer = Gtk.TextBuffer()
                self._reader_heading_tag = self.reader_buffer.create_tag("heading-test")
                self._reader_brief_subheading_tag = self.reader_buffer.create_tag(
                    "brief-subheading-test"
                )
                self.page_marker_tag = self.reader_buffer.create_tag("page-marker-test")
                self._reader_pagination_mode = "none"
                self._pending_quote_target = None

            def _set_reader_busy(self, _busy: bool) -> None:
                pass

            def _close_reader_find(self, *, clear_entry: bool) -> None:
                pass

            def _update_reader_clipboard_button(self) -> None:
                pass

            def _apply_reader_style_span(
                self,
                span: DisplayStyleSpan,
                text_length: int,
            ) -> None:
                OpenLawLensWindow._apply_reader_style_span(self, span, text_length)  # type: ignore[arg-type]

            def _apply_reader_markdown_spans(self, _spans: object) -> None:
                pass

            def _apply_reader_citation_italics(self, _text: str) -> None:
                pass

            def _apply_reader_citation_links(self, _text: str) -> None:
                pass

        window = DummyWindow()
        text = "INTRODUCTION\n\nBackground\n\nOpinion text."
        heading = DisplayStyleSpan("heading", 0, len("INTRODUCTION"))
        subheading_start = text.index("Background")
        subheading = DisplayStyleSpan(
            "brief-subheading",
            subheading_start,
            subheading_start + len("Background"),
        )

        OpenLawLensWindow._set_reader_text(  # type: ignore[arg-type]
            window,
            text,
            style_spans=[heading, subheading],
        )

        self.assertIn(
            window._reader_heading_tag,
            window.reader_buffer.get_iter_at_offset(2).get_tags(),
        )
        self.assertNotIn(
            window._reader_heading_tag,
            window.reader_buffer.get_iter_at_offset(len("INTRODUCTION") + 2).get_tags(),
        )
        self.assertIn(
            window._reader_brief_subheading_tag,
            window.reader_buffer.get_iter_at_offset(subheading_start + 2).get_tags(),
        )

    def test_chunked_reader_render_applies_styles_before_citation_italics(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.applied: list[DisplayStyleSpan] = []
                self.next_indexes: list[int] = []

            def _case_load_is_current(self, _generation: int, _cluster_id: str) -> bool:
                return True

            def _apply_reader_style_span(
                self,
                span: DisplayStyleSpan,
                _text_length: int,
            ) -> None:
                self.applied.append(span)

            def _apply_reader_payload_style_chunk(self, payload, index):  # type: ignore[no-untyped-def]
                return OpenLawLensWindow._apply_reader_payload_style_chunk(self, payload, index)  # type: ignore[arg-type]

            def _apply_reader_payload_italic_chunk(self, _payload, index):  # type: ignore[no-untyped-def]
                self.next_indexes.append(index)
                return False

        span = DisplayStyleSpan("heading", 0, len("DISCUSSION"))
        payload = build_case_reader_payload(
            {"id": 42, "case_name": "Example"},
            [
                DisplayText(
                    "DISCUSSION\n\nText.",
                    "plain_text",
                    [],
                    style_spans=[span],
                )
            ],
        )
        window = DummyWindow()

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda func, *args: func(*args)):
            OpenLawLensWindow._apply_reader_payload_style_chunk(  # type: ignore[arg-type]
                window,
                payload,
                0,
            )

        self.assertEqual(window.applied, [span])
        self.assertEqual(window.next_indexes, [0])

    def test_case_header_keeps_formatted_citation_on_one_line(self) -> None:
        class DummyWindow:
            pass

        cited = {
            "id": 42,
            "case_name_short": "Example v. State",
            "date_filed": "2020-06-01",
            "citations": [{"volume": "1", "reporter": "Cal.5th", "page": "1"}],
        }
        uncited = {"id": 43, "case_name": "Uncited Example"}

        self.assertEqual(
            OpenLawLensWindow._case_header_text(DummyWindow(), cited),  # type: ignore[arg-type]
            "Example v. State (2020) 1 Cal.5th 1",
        )
        self.assertEqual(
            OpenLawLensWindow._case_header_text(DummyWindow(), uncited),  # type: ignore[arg-type]
            "Uncited Example",
        )

    def test_ineligible_loaded_case_starts_scholar_with_transient_notice_mode(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_has_official_pagination = True
                self._pending_auto_scholar_cluster_id = "42"
                self._pending_auto_scholar_query = "10 Cal.App.5th 25"
                self.busy: list[tuple[bool, str]] = []
                self.statuses: list[str] = []
                self.auto_find_calls: list[dict[str, object]] = []

            def _set_reader_busy(self, busy: bool, message: str = "") -> None:
                self.busy.append((busy, message))

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _start_scholar_auto_find(
                self,
                query: str,
                *,
                fallback_mode: str,
                auto_import: bool,
                cache_generation: int | None = None,
            ) -> None:
                self.auto_find_calls.append(
                    {
                        "query": query,
                        "fallback_mode": fallback_mode,
                        "auto_import": auto_import,
                        "cache_generation": cache_generation,
                    }
                )

            def _update_reader_clipboard_button(self) -> None:
                pass

        window = DummyWindow()

        result = OpenLawLensWindow._finish_case_quality_status(  # type: ignore[arg-type]
            window,
            "42",
            False,
            "No embedded reporter page markers.",
            "Fetched",
        )

        self.assertFalse(result)
        self.assertFalse(window._reader_has_official_pagination)
        self.assertEqual(window._pending_auto_scholar_cluster_id, "")
        self.assertEqual(window._pending_auto_scholar_query, "")
        self.assertEqual(window.statuses[-1], "Searching Google Scholar for official reporter text...")
        self.assertEqual(
            window.auto_find_calls,
            [
                {
                    "query": "10 Cal.App.5th 25",
                    "fallback_mode": SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
                    "auto_import": True,
                    "cache_generation": None,
                }
            ],
        )

    def test_case_worker_uses_slip_opinion_before_scholar_fallback(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.payloads = []
                self.client = MagicMock()
                self.client.fetch_cluster_opinions.return_value = [
                    {"id": 10, "plain_text": "Unpaginated CourtListener text."}
                ]
                self.client.last_opinion_source = "Fetched"
                self.client.reader_opinions.return_value = self.client.fetch_cluster_opinions.return_value
                self.client.opinion_display.return_value = DisplayText(
                    "Unpaginated CourtListener text.",
                    "plain_text",
                    [],
                )
                self.client.fetch_cluster_slip_opinion.return_value = SlipOpinionResult(
                    case_number="A173218",
                    source_url="https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                    pdf_path=Path("/tmp/A173218.PDF"),
                    display=DisplayText(
                        "[Slip opn. p. 1]\nSlip text.",
                        "slip_pdf",
                        [PageMarker("1", "[Slip opn. p. 1]", 0, 16, "slip_pdf")],
                    ),
                    date_filed="2026-06-01",
                )

            def _start_reader_payload_render(self, payload):  # type: ignore[no-untyped-def]
                self.payloads.append(payload)
                return False

            def _apply_case_error(self, *_args):  # type: ignore[no-untyped-def]
                raise AssertionError("case error should not be used")

        window = DummyWindow()
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
            "precedential_status": "Published",
            "date_filed": "2026-06-01",
            "docket": {"docket_number": "A173218", "court": {"id": "calctapp1d"}},
        }

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda func, *args: func(*args)):
            OpenLawLensWindow._case_worker(window, cluster, 7, 8)  # type: ignore[arg-type]

        self.assertEqual(len(window.payloads), 1)
        payload = window.payloads[0]
        self.assertEqual(payload.pagination_mode, "slip")
        self.assertEqual(payload.slip_case_number, "A173218")
        self.assertIn("Slip text.", payload.text)
        window.client.fetch_cluster_slip_opinion.assert_called_once_with(
            cluster,
            force=False,
            max_age_days=180,
            populate_research_cache=False,
        )

    def test_case_worker_uses_cached_slip_payload_before_courtlistener_blob(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.write_slip_opinion_payload(
                "A173218",
                {
                    "case_number": "A173218",
                    "source_url": "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                    "date_filed": "2026-03-06",
                    "display": {
                        "text": "[Slip opn. p. 1]\nSaved slip text.",
                        "source_field": "slip_pdf",
                        "page_markers": [
                            {
                                "page_label": "1",
                                "marker_text": "[Slip opn. p. 1]",
                                "start_offset": 0,
                                "end_offset": 16,
                                "source_field": "slip_pdf",
                            }
                        ],
                    },
                },
            )

            class DummyWindow:
                def __init__(self) -> None:
                    self.payloads = []
                    self.client = MagicMock()
                    self.client.cache = cache
                    self.client.fetch_cluster_opinions.side_effect = AssertionError(
                        "CourtListener opinion blob should not be fetched"
                    )
                    self.client.fetch_cluster_slip_opinion.side_effect = AssertionError(
                        "Slip PDF should already be cached"
                    )

                def _start_reader_payload_render(self, payload):  # type: ignore[no-untyped-def]
                    self.payloads.append(payload)
                    return False

                def _apply_case_error(self, *_args):  # type: ignore[no-untyped-def]
                    raise AssertionError("case error should not be used")

            window = DummyWindow()
            cluster = {
                "id": 42,
                "case_name_short": "In re L.G.",
                "precedential_status": "Published",
                "date_filed": "2026-03-06",
                "docket": {"docket_number": "A173218", "court": {"id": "calctapp1d"}},
            }

            with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda func, *args: func(*args)):
                OpenLawLensWindow._case_worker(window, cluster, 7, 8)  # type: ignore[arg-type]

            window.client.fetch_cluster_opinions.assert_not_called()
            window.client.fetch_cluster_slip_opinion.assert_not_called()
            self.assertEqual(len(window.payloads), 1)
            payload = window.payloads[0]
            self.assertEqual(payload.pagination_mode, "slip")
            self.assertEqual(payload.opinion_source, "Research Cache")
            self.assertIn("Saved slip text.", payload.text)

    def test_forced_case_worker_uses_slip_opinion_without_courtlistener_blob_first(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.payloads = []
                self.busy: list[tuple[bool, str]] = []
                self.client = MagicMock()
                self.client.fetch_cluster_opinions.side_effect = AssertionError(
                    "forced slip lookup should not fetch CourtListener opinion text first"
                )
                self.client.fetch_cluster_slip_opinion.return_value = SlipOpinionResult(
                    case_number="A173218",
                    source_url="https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                    pdf_path=Path("/tmp/A173218.PDF"),
                    display=DisplayText(
                        "[Slip opn. p. 1]\nSlip text.",
                        "slip_pdf",
                        [PageMarker("1", "[Slip opn. p. 1]", 0, 16, "slip_pdf")],
                    ),
                    date_filed="2026-03-06",
                )

            def _set_reader_busy(self, busy: bool, message: str = "") -> None:
                self.busy.append((busy, message))

            def _start_reader_payload_render(self, payload):  # type: ignore[no-untyped-def]
                self.payloads.append(payload)
                return False

            def _apply_case_error(self, *_args):  # type: ignore[no-untyped-def]
                raise AssertionError("case error should not be used")

        window = DummyWindow()
        cluster = {
            "id": 42,
            "case_name_short": "In re L.G.",
            "precedential_status": "Published",
            "date_filed": "2026-03-06",
            "docket_number": "A173218",
            "docket": {"court": {"id": "calctapp1d"}},
        }

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda func, *args: func(*args)):
            OpenLawLensWindow._case_worker(window, cluster, 7, 8, True)  # type: ignore[arg-type]

        window.client.fetch_cluster_opinions.assert_not_called()
        window.client.fetch_cluster_slip_opinion.assert_called_once_with(
            cluster,
            force=True,
            max_age_days=180,
            populate_research_cache=False,
        )
        self.assertEqual(window.payloads[0].pagination_mode, "slip")
        self.assertEqual(
            window.busy[:2],
            [
                (True, "Downloading slip opinion PDF..."),
                (True, "Rendering slip opinion..."),
            ],
        )

    def test_start_reader_payload_render_replaces_header_with_slip_citation(self) -> None:
        class DummyBuffer:
            def __init__(self) -> None:
                self.text = ""

            def set_text(self, text: str) -> None:
                self.text = text

        class DummyWindow:
            def __init__(self) -> None:
                self.client = MagicMock()
                self.reader_buffer = DummyBuffer()
                self.headers: list[tuple[str, str]] = []
                self._research_cache_generation = 1

            def _case_load_is_current(self, _generation: int, _cluster_id: str) -> bool:
                return True

            def _close_reader_find(self, *, clear_entry: bool) -> None:
                pass

            def _set_reader_header(
                self,
                text: str,
                citation: FormattedCitation | None = None,
                cluster: dict[str, object] | None = None,
            ) -> None:
                self.headers.append((text, citation.plain_text if citation else ""))

            def _clear_reader_citation_links(self) -> None:
                pass

            def _update_reader_clipboard_button(self) -> None:
                pass

            def _insert_reader_payload_text_chunk(self, *_args: object) -> bool:
                return False

        cluster = {
            "id": 42,
            "case_name_short": "In re L.G.",
            "date_filed": "2026-03-06",
            "docket": {"docket_number": "A173218"},
        }
        payload = build_case_reader_payload(
            cluster,
            [
                DisplayText(
                    "[Slip opn. p. 1]\nSlip text.",
                    "slip_pdf",
                    [PageMarker("1", "[Slip opn. p. 1]", 0, 16, "slip_pdf")],
                )
            ],
            generation=1,
            cache_generation=1,
            pagination_mode="slip",
            slip_source_url="https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
            slip_case_number="A173218",
        )
        window = DummyWindow()

        with patch("open_law_lens.app.GLib.idle_add", return_value=None):
            OpenLawLensWindow._start_reader_payload_render(window, payload)  # type: ignore[arg-type]

        citation = "In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___"
        self.assertEqual(window.headers, [(citation, citation)])

    def test_reader_opinion_hydration_keeps_loaded_research_set_clean(self) -> None:
        class DummyBuffer:
            def set_text(self, _text: str) -> None:
                pass

        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)
                self.reader_buffer = DummyBuffer()
                self._research_cache_generation = 1

            def _case_load_is_current(self, _generation: int, _cluster_id: str) -> bool:
                return True

            def _close_reader_find(self, *, clear_entry: bool) -> None:
                pass

            def _clear_reader_citation_links(self) -> None:
                pass

            def _update_reader_clipboard_button(self) -> None:
                pass

            def _insert_reader_payload_text_chunk(self, *_args: object) -> bool:
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cluster = {"id": 42, "case_name": "Example v. State"}
            cache.upsert_cluster(cluster)
            cache.set_active_research_set(7, "Example")
            payload = build_case_reader_payload(
                cluster,
                [DisplayText("Opinion text.", "plain_text", [])],
                generation=1,
                cache_generation=1,
                opinion_ids=("10",),
            )
            window = DummyWindow(cache)

            with patch("open_law_lens.app.GLib.idle_add", return_value=None):
                OpenLawLensWindow._start_reader_payload_render(  # type: ignore[arg-type]
                    window,
                    payload,
                )

            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertFalse(metadata["dirty"])
            self.assertEqual(cache.list_case_entries()[0]["opinion_ids"], ["10"])

    def test_case_number_direct_slip_lookup_uses_pdf_metadata_for_header_citation(self) -> None:
        class EmptySearchPage:
            results: list[object] = []

        class DummyClient:
            def search_cases(self, _query: str, *, page_size: int) -> EmptySearchPage:
                return EmptySearchPage()

            def fetch_slip_opinion(self, _case_number: str) -> SlipOpinionResult:
                return SlipOpinionResult(
                    case_number="A173218",
                    source_url="https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                    pdf_path=Path("/tmp/A173218.PDF"),
                    display=DisplayText(
                        "[Slip opn. p. 1]\nFiled 3/6/26\n\nIn re L.G., a Person Coming Under the Juvenile Court Law.\n\nText.",
                        "slip_pdf",
                        [PageMarker("1", "[Slip opn. p. 1]", 0, 16, "slip_pdf")],
                    ),
                    date_filed="",
                )

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self.finished: list[dict[str, object]] = []

            def _finish_case_number_direct_slip_lookup(
                self,
                cluster: dict[str, object],
                *_args: object,
            ) -> bool:
                self.finished.append(cluster)
                return False

        window = DummyWindow()

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda func, *args: func(*args)):
            OpenLawLensWindow._case_number_lookup_worker(window, "A173218", 1, 1)  # type: ignore[arg-type]

        self.assertEqual(window.finished[0]["case_name_short"], "In re L.G.")
        self.assertEqual(window.finished[0]["date_filed"], "2026-03-06")

    def test_case_number_cluster_lookup_forces_slip_worker(self) -> None:
        class ImmediateThread:
            def __init__(self, *, target: object, args: tuple[object, ...], daemon: bool = False) -> None:
                self.target = target
                self.args = args

            def start(self) -> None:
                self.target(*self.args)  # type: ignore[misc]

        class DummyCache:
            def upsert_cluster(self, _cluster: dict[str, object]) -> str:
                return "10805052"

        class DummyClient:
            def __init__(self, cluster: dict[str, object]) -> None:
                self.cache = DummyCache()
                self._cluster = cluster

            def cached_clusters(self) -> list[dict[str, object]]:
                return [self._cluster]

        class DummyWindow:
            def __init__(self, cluster: dict[str, object]) -> None:
                self.client = DummyClient(cluster)
                self._research_cache_generation = 3
                self.sidebar_kwargs: list[dict[str, object]] = []
                self.worker_args: list[tuple[dict[str, object], int, int, bool]] = []

            def _set_sidebar_clusters(self, _clusters: list[dict[str, object]], **kwargs: object) -> None:
                self.sidebar_kwargs.append(kwargs)

            def _set_status(self, _status: str) -> None:
                pass

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                pass

            def _begin_case_load(self, _cluster: dict[str, object]) -> int:
                return 9

            def _case_worker(
                self,
                cluster: dict[str, object],
                generation: int,
                cache_generation: int,
                force_slip_opinion: bool = False,
            ) -> None:
                self.worker_args.append((cluster, generation, cache_generation, force_slip_opinion))

        cluster = {"id": 10805052, "case_name_short": "In re L.G."}
        window = DummyWindow(cluster)

        with patch("open_law_lens.app.threading.Thread", ImmediateThread):
            OpenLawLensWindow._finish_case_number_cluster_lookup(  # type: ignore[arg-type]
                window,
                cluster,
                "A173218",
                3,
            )

        self.assertTrue(window.sidebar_kwargs[0]["suppress_selection_lookup"])
        loaded_cluster, generation, cache_generation, force_slip = window.worker_args[0]
        self.assertEqual(loaded_cluster["docket_number"], "A173218")
        self.assertEqual(generation, 9)
        self.assertEqual(cache_generation, 3)
        self.assertTrue(force_slip)

    def test_transient_scholar_failure_shows_notice_without_manual_window(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.busy: list[tuple[bool, str]] = []
                self.statuses: list[str] = []
                self.notices: list[bool] = []
                self.external_windows: list[tuple[str, str]] = []

            def _set_reader_busy(self, busy: bool, message: str = "") -> None:
                self.busy.append((busy, message))

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _show_official_pagination_not_found_notice(self, *, can_view_current: bool) -> None:
                self.notices.append(can_view_current)

            def _show_external_lookup_window(self, query: str, *, initial_source_url: str = "") -> None:
                self.external_windows.append((query, initial_source_url))

        window = DummyWindow()

        OpenLawLensWindow._handle_scholar_auto_failure(  # type: ignore[arg-type]
            window,
            "10 Cal.App.5th 25",
            "Auto-Find could not complete: no case result.",
            SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
        )

        self.assertEqual(window.busy[-1], (False, ""))
        self.assertEqual(window.statuses[-1], "Transient view only: official reporter pagination was not found.")
        self.assertEqual(window.notices, [True])
        self.assertEqual(window.external_windows, [])

    def test_notice_only_scholar_failure_does_not_open_manual_window(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.statuses: list[str] = []
                self.notices: list[bool] = []
                self.external_windows: list[str] = []

            def _set_reader_busy(self, _busy: bool, _message: str = "") -> None:
                pass

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _show_official_pagination_not_found_notice(self, *, can_view_current: bool) -> None:
                self.notices.append(can_view_current)

            def _show_external_lookup_window(self, query: str, *, initial_source_url: str = "") -> None:
                del initial_source_url
                self.external_windows.append(query)

        window = DummyWindow()

        OpenLawLensWindow._handle_scholar_auto_failure(  # type: ignore[arg-type]
            window,
            "missing citation",
            "Auto-Find could not complete.",
            SCHOLAR_FALLBACK_NOTICE_ONLY,
        )

        self.assertEqual(
            window.statuses[-1],
            "A version of this case with pagination from the official reporter was not found.",
        )
        self.assertEqual(window.notices, [False])
        self.assertEqual(window.external_windows, [])

    def test_ineligible_scholar_auto_import_uses_transient_notice_mode(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.failures: list[dict[str, str]] = []

            def _default_import_official_citation(self) -> str:
                return "10 Cal.App.5th 25"

            def _default_import_case_name(self) -> str:
                return "Example v. State"

            def _save_imported_official_text(self, **_kwargs: object) -> bool:
                return False

            def _close_external_lookup_window(self) -> None:
                raise AssertionError("External lookup window should not close on failed save.")

            def _handle_scholar_auto_failure(
                self,
                query: str,
                message: str,
                fallback_mode: str,
                *,
                initial_source_url: str = "",
            ) -> None:
                self.failures.append(
                    {
                        "query": query,
                        "message": message,
                        "fallback_mode": fallback_mode,
                        "initial_source_url": initial_source_url,
                    }
                )

        window = DummyWindow()
        webpage = ExtractedWebpage(
            url="https://scholar.google.com/scholar_case?case=123",
            title="Example v. State",
            text="Different pagination text.",
        )

        result = OpenLawLensWindow._finish_scholar_auto_import(  # type: ignore[arg-type]
            window,
            "10 Cal.App.5th 25",
            webpage,
            SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
        )

        self.assertFalse(result)
        self.assertEqual(window.failures[0]["query"], "10 Cal.App.5th 25")
        self.assertEqual(window.failures[0]["fallback_mode"], SCHOLAR_FALLBACK_TRANSIENT_NOTICE)
        self.assertEqual(window.failures[0]["initial_source_url"], webpage.url)

    def test_scholar_auto_import_rejects_mismatched_official_citation(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.failures: list[dict[str, str]] = []

            def _default_import_official_citation(self) -> str:
                return ""

            def _default_import_case_name(self) -> str:
                return ""

            def _save_imported_official_text(self, **_kwargs: object) -> bool:
                raise AssertionError("Mismatched Scholar result should not be saved.")

            def _close_external_lookup_window(self) -> None:
                raise AssertionError("External lookup window should not close on failed save.")

            def _handle_scholar_auto_failure(
                self,
                query: str,
                message: str,
                fallback_mode: str,
                *,
                initial_source_url: str = "",
            ) -> None:
                self.failures.append(
                    {
                        "query": query,
                        "message": message,
                        "fallback_mode": fallback_mode,
                        "initial_source_url": initial_source_url,
                    }
                )

        window = DummyWindow()
        webpage = ExtractedWebpage(
            url="https://scholar.google.com/scholar_case?case=wrong",
            title="Wrong Case",
            text="Wrong Case (2026) 10 Cal.App.5th 25.",
        )

        result = OpenLawLensWindow._finish_scholar_auto_import(  # type: ignore[arg-type]
            window,
            "116 Cal.App.5th 53",
            webpage,
            SCHOLAR_FALLBACK_NOTICE_ONLY,
        )

        self.assertFalse(result)
        self.assertEqual(window.failures[0]["query"], "116 Cal.App.5th 53")
        self.assertIn("did not match", window.failures[0]["message"])
        self.assertEqual(window.failures[0]["initial_source_url"], webpage.url)

    def test_scholar_auto_import_allows_matching_official_citation(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.saved: list[dict[str, object]] = []
                self.closed = False

            def _default_import_official_citation(self) -> str:
                return ""

            def _default_import_case_name(self) -> str:
                return ""

            def _save_imported_official_text(self, **kwargs: object) -> bool:
                self.saved.append(kwargs)
                return True

            def _close_external_lookup_window(self) -> None:
                self.closed = True

            def _handle_scholar_auto_failure(self, *_args: object, **_kwargs: object) -> None:
                raise AssertionError("Matching Scholar result should not fail.")

        window = DummyWindow()
        webpage = ExtractedWebpage(
            url="https://scholar.google.com/scholar_case?case=3488447941400747812",
            title="In re C.L.",
            text="In re C.L. (2025) 116 Cal.App.5th 53.",
        )

        result = OpenLawLensWindow._finish_scholar_auto_import(  # type: ignore[arg-type]
            window,
            "116 Cal.App.5th 53",
            webpage,
            SCHOLAR_FALLBACK_NOTICE_ONLY,
        )

        self.assertFalse(result)
        self.assertTrue(window.closed)
        self.assertEqual(window.saved[0]["official_citation"], "116 Cal.App.5th 53")
        self.assertEqual(window.saved[0]["case_name"], "In re C.L.")

    def test_reader_and_agent_citation_links_use_shared_lookup_path(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.opened: list[str] = []
                self.links: list[CitedCaseLink | None] = []
                self.populate_values: list[bool] = []
                self._selected_agent_answer = None

            def _start_lookup(
                self,
                citation: str,
                *,
                link: CitedCaseLink | None = None,
                populate_research_cache: bool = True,
            ) -> None:
                self.opened.append(citation)
                self.links.append(link)
                self.populate_values.append(populate_research_cache)

            def _open_citation_lookup_link(
                self,
                link: CitedCaseLink,
                *,
                populate_research_cache: bool = True,
            ) -> None:
                OpenLawLensWindow._open_citation_lookup_link(  # type: ignore[arg-type]
                    self,
                    link,
                    populate_research_cache=populate_research_cache,
                )

        window = DummyWindow()
        link = CitedCaseLink(
            start_offset=0,
            end_offset=25,
            lookup_text="11 Cal.5th 614",
            case_name="In re Caden C.",
            full_text="In re Caden C. (2021) 11 Cal.5th 614",
        )

        OpenLawLensWindow._open_cited_case_link(window, link)  # type: ignore[arg-type]
        OpenLawLensWindow._open_agent_cited_case_link(window, link)  # type: ignore[arg-type]

        self.assertEqual(window.opened, ["11 Cal.5th 614", "11 Cal.5th 614"])
        self.assertEqual(window.populate_values, [True, True])
        self.assertEqual(window.links, [link, link])

        window._selected_agent_answer = {"answer_id": "saved"}
        OpenLawLensWindow._open_cited_case_link(window, link)  # type: ignore[arg-type]

        self.assertEqual(window.populate_values[-1], True)

    def test_agent_answer_external_url_links_strip_trailing_punctuation(self) -> None:
        links = OpenLawLensWindow._external_url_links(  # type: ignore[arg-type]
            "Slip: https://www4.courts.ca.gov/opinions/archive/A173218.PDF."
        )

        self.assertEqual(
            links,
            [
                (
                    6,
                    61,
                    "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                )
            ],
        )

    def test_lookup_clicked_routes_bare_case_number_to_case_number_lookup(self) -> None:
        class DummyEntry:
            def get_text(self) -> str:
                return "A173218"

        class DummyWindow:
            def __init__(self) -> None:
                self.citation_entry = DummyEntry()
                self.case_numbers: list[str] = []

            def _lookup_text_from_entry(self, text: str) -> str:
                return text

            def _start_case_number_lookup(self, case_number: str) -> None:
                self.case_numbers.append(case_number)

        window = DummyWindow()

        OpenLawLensWindow._on_lookup_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(window.case_numbers, ["A173218"])

    def test_active_research_set_label_and_save_updates_loaded_set(self) -> None:
        class DummyLabel:
            def __init__(self) -> None:
                self.text = ""
                self.visible = False

            def set_text(self, text: str) -> None:
                self.text = text

            def set_visible(self, visible: bool) -> None:
                self.visible = visible

        class DummyCache:
            def list_case_entries(self) -> list[dict[str, object]]:
                return [{"cluster_id": "42"}]

            def list_statute_entries(self) -> list[dict[str, object]]:
                return []

            def list_rule_entries(self) -> list[dict[str, object]]:
                return []

            def list_agent_answer_entries(self) -> list[dict[str, object]]:
                return []

        class DummyLibrary:
            def __init__(self) -> None:
                self.calls: list[tuple[str, bool]] = []

            def save_research_set(
                self,
                name: str,
                cache: DummyCache,
                *,
                replace: bool = False,
            ) -> ResearchSet:
                self.calls.append((name, replace))
                return ResearchSet(
                    set_id=7,
                    name=name,
                    created_at="",
                    updated_at="",
                    last_accessed="",
                    item_count=1,
                    case_count=1,
                    statute_count=0,
                    rule_count=0,
                    agent_answer_count=0,
                    items=[],
                )

        class DummyClient:
            def __init__(self) -> None:
                self.cache = DummyCache()
                self.library = DummyLibrary()

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self._active_research_set_id: int | None = None
                self._active_research_set_name = ""
                self._research_set_label = DummyLabel()
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _research_cache_authority_count(self) -> int:
                return OpenLawLensWindow._research_cache_authority_count(self)  # type: ignore[arg-type]

            def _save_research_set(self, name: str, *, replace: bool) -> None:
                OpenLawLensWindow._save_research_set(self, name, replace=replace)  # type: ignore[arg-type]

            def _set_active_research_set(self, research_set: ResearchSet | None) -> None:
                OpenLawLensWindow._set_active_research_set(self, research_set)  # type: ignore[arg-type]

        window = DummyWindow()
        research_set = ResearchSet(
            set_id=7,
            name="Dependency appeal",
            created_at="",
            updated_at="",
            last_accessed="",
            item_count=1,
            case_count=1,
            statute_count=0,
            rule_count=0,
            agent_answer_count=0,
            items=[],
        )

        OpenLawLensWindow._set_active_research_set(window, research_set)  # type: ignore[arg-type]
        OpenLawLensWindow._on_save_research_set(window, object(), None)  # type: ignore[arg-type]

        self.assertEqual(window._research_set_label.text, "Set: Dependency appeal")
        self.assertTrue(window._research_set_label.visible)
        self.assertEqual(window.client.library.calls, [("Dependency appeal", True)])
        self.assertIn("1 Research Cache item(s)", window.statuses[-1])

    def test_lookup_clusters_for_display_repairs_reporter_only_linked_case_name(self) -> None:
        window = OpenLawLensWindow.__new__(OpenLawLensWindow)
        link = CitedCaseLink(
            start_offset=0,
            end_offset=44,
            lookup_text="9 Cal.5th 989",
            case_name="Conservatorship of O.B.",
            full_text="Conservatorship of O.B. (2020) 9 Cal.5th 989",
        )
        clusters = [
            {
                "id": "external-ob",
                "case_name": "9 Cal.5th 989",
                "case_name_short": "9 Cal.5th 989",
                "case_name_full": "9 Cal.5th 989",
                "official_citation": "9 Cal.5th 989",
                "citations": [{"volume": "9", "reporter": "Cal.5th", "page": "989"}],
            }
        ]

        repaired = OpenLawLensWindow._lookup_clusters_for_display(  # type: ignore[arg-type]
            window,
            clusters,
            link,
        )

        self.assertEqual(repaired[0]["case_name"], "Conservatorship of O.B.")

    def test_default_import_case_name_uses_last_lookup_full_citation(self) -> None:
        class DummyEntry:
            def get_text(self) -> str:
                return ""

        window = OpenLawLensWindow.__new__(OpenLawLensWindow)
        window._selected_cluster = None
        window.citation_entry = DummyEntry()
        window._last_lookup_text = "Conservatorship of O.B. (2020) 9 Cal.5th 989"

        self.assertEqual(
            OpenLawLensWindow._default_import_case_name(window),  # type: ignore[arg-type]
            "Conservatorship of O.B.",
        )

    def test_open_authority_text_uses_first_detected_authority(self) -> None:
        class DummyEntry:
            def __init__(self) -> None:
                self.values: list[str] = []

            def set_text(self, text: str) -> None:
                self.values.append(text)

        class DummyWindow:
            def __init__(self) -> None:
                self.citation_entry = DummyEntry()
                self.opened_cases: list[str] = []
                self.opened_statutes: list[str] = []
                self.opened_rules: list[str] = []

            def _set_status(self, _text: str) -> None:
                pass

            def _lookup_text_from_entry(self, entry_text: str) -> str:
                return entry_text

            def _bare_statute_lookup_text(self, text: str) -> str:
                return OpenLawLensWindow._bare_statute_lookup_text(self, text)  # type: ignore[arg-type]

            def _external_lookup_text(self, lookup_text: str) -> str:
                return OpenLawLensWindow._external_lookup_text(self, lookup_text)  # type: ignore[arg-type]

            def _start_lookup(self, citation: str) -> None:
                self.opened_cases.append(citation)

            def _start_statute_lookup(self, citation: str) -> None:
                self.opened_statutes.append(citation)

            def _start_rule_lookup(self, citation: str) -> None:
                self.opened_rules.append(citation)

        window = DummyWindow()

        OpenLawLensWindow.open_authority_text(  # type: ignore[arg-type]
            window,
            "Background text. See Welf. & Inst. Code, § 300 and 13 Cal.4th 952.",
        )

        self.assertEqual(window.opened_statutes, ["Welf. & Inst. Code, § 300"])
        self.assertEqual(window.opened_cases, [])
        self.assertEqual(window.opened_rules, [])

    def test_open_authority_text_treats_bare_number_as_configured_statute(self) -> None:
        class DummyEntry:
            def set_text(self, _text: str) -> None:
                pass

        class DummyWindow:
            def __init__(self) -> None:
                self.citation_entry = DummyEntry()
                self.opened_statutes: list[str] = []

            def _start_statute_lookup(self, citation: str) -> None:
                self.opened_statutes.append(citation)

            def _bare_statute_lookup_text(self, text: str) -> str:
                return OpenLawLensWindow._bare_statute_lookup_text(self, text)  # type: ignore[arg-type]

            def _set_status(self, _text: str) -> None:
                pass

        window = DummyWindow()

        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            OpenLawLensWindow.open_authority_text(window, "300")  # type: ignore[arg-type]

        self.assertEqual(window.opened_statutes, ["Welf. & Inst. Code, § 300"])

    def test_open_authority_text_uses_configured_bare_number_statute_code(self) -> None:
        class DummyEntry:
            def set_text(self, _text: str) -> None:
                pass

        class DummyWindow:
            def __init__(self) -> None:
                self.citation_entry = DummyEntry()
                self.opened_statutes: list[str] = []

            def _start_statute_lookup(self, citation: str) -> None:
                self.opened_statutes.append(citation)

            def _bare_statute_lookup_text(self, text: str) -> str:
                return OpenLawLensWindow._bare_statute_lookup_text(self, text)  # type: ignore[arg-type]

            def _set_status(self, _text: str) -> None:
                pass

        window = DummyWindow()

        with patch(
            "open_law_lens.app.load_config",
            return_value=AppConfig(default_bare_statute_law_code="FAM"),
        ):
            OpenLawLensWindow.open_authority_text(window, "7822")  # type: ignore[arg-type]

        self.assertEqual(window.opened_statutes, ["Fam. Code, § 7822"])

    def test_selected_agent_statutes_and_rules_use_cached_text(self) -> None:
        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

            def cached_statutes(self) -> list[dict[str, object]]:
                return [
                    statute
                    for entry in self.cache.list_statute_entries()
                    if (statute := self.cache.read_cached_statute(str(entry.get("statute_id") or ""))) is not None
                ]

            def cached_rules(self) -> list[dict[str, object]]:
                return [
                    rule
                    for entry in self.cache.list_rule_entries()
                    if (rule := self.cache.read_cached_rule(str(entry.get("rule_id") or ""))) is not None
                ]

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.upsert_statute(
                {
                    "statute_id": "WIC:300",
                    "title": "Welfare and Institutions Code section 300",
                    "citation": "Welf. & Inst. Code, § 300",
                    "text": "stale statute text",
                }
            )
            cache.set_statute_agent_selected("WIC:300", True)
            cache.upsert_rule(
                {
                    "rule_id": "CRC:8.11",
                    "title": "California Rules of Court, rule 8.11",
                    "citation": "Cal. Rules of Court, rule 8.11",
                    "text": "stale rule text",
                }
            )
            cache.set_rule_agent_selected("CRC:8.11", True)
            window = DummyWindow(cache)

            statutes = OpenLawLensWindow._selected_agent_statutes(window)  # type: ignore[arg-type]
            rules = OpenLawLensWindow._selected_agent_rules(window)  # type: ignore[arg-type]

        self.assertEqual(statutes[0]["citation"], "Welf. & Inst. Code, § 300")
        self.assertEqual(statutes[0]["text"], "stale statute text")
        self.assertEqual(rules[0]["citation"], "Cal. Rules of Court, rule 8.11")
        self.assertEqual(rules[0]["text"], "stale rule text")

    def test_selected_agent_answers_use_saved_answer_text(self) -> None:
        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            answer_id = cache.save_agent_answer(
                "The removal issue is strong.",
                mode="appeal",
            )
            cache.set_agent_answer_selected(answer_id, True)
            window = DummyWindow(cache)

            answers = OpenLawLensWindow._selected_agent_answers(window)  # type: ignore[arg-type]

        self.assertEqual(answers[0]["answer_id"], answer_id)
        self.assertEqual(answers[0]["text"], "The removal issue is strong.")

    def test_save_agent_answer_click_writes_to_research_cache_only(self) -> None:
        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

            def cached_clusters(self) -> list[dict[str, object]]:
                raise AssertionError("save should preserve visible cases, not reload cache")

            def cached_statutes(self) -> list[dict[str, object]]:
                raise AssertionError("save should preserve visible statutes, not reload cache")

            def cached_rules(self) -> list[dict[str, object]]:
                raise AssertionError("save should preserve visible rules, not reload cache")

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)
                self._agent_last_answer_text = (
                    "See `In re Caden C. (2021) 11 Cal.5th 614`, "
                    "`Welf. & Inst. Code, section 300`, and "
                    "`Cal. Rules of Court, rule 8.204`."
                )
                self._agent_mode = "appeal"
                self._clusters = [{"id": "visible-case"}]
                self._statutes = [{"statute_id": "VISIBLE:300"}]
                self._rules = [{"rule_id": "VISIBLE:8.204"}]
                self.sidebar_args: tuple[object, ...] = ()
                self.sidebar_kwargs: dict[str, object] = {}
                self.statuses: list[str] = []

            def _set_sidebar_authorities(self, *args: object, **kwargs: object) -> None:
                self.sidebar_args = args
                self.sidebar_kwargs = kwargs

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.upsert_cluster({"id": "background-case", "case_name": "Background Case"})
            cache.upsert_statute(
                {
                    "statute_id": "BACKGROUND:7612",
                    "title": "Background statute",
                    "citation": "Fam. Code, § 7612",
                    "text": "Background statute text.",
                }
            )
            cache.upsert_rule(
                {
                    "rule_id": "BACKGROUND:8.204",
                    "title": "Background rule",
                    "citation": "Cal. Rules of Court, rule 8.204",
                    "text": "Background rule text.",
                }
            )
            window = DummyWindow(cache)

            OpenLawLensWindow._on_save_agent_answer_clicked(window, object())  # type: ignore[arg-type]

            entries = cache.list_agent_answer_entries()
            saved = cache.read_agent_answer(entries[0]["answer_id"])

        self.assertEqual(len(entries), 1)
        self.assertEqual(window.sidebar_args[0], [{"id": "visible-case"}])
        self.assertEqual(window.sidebar_args[1], [{"statute_id": "VISIBLE:300"}])
        self.assertEqual(window.sidebar_args[2], [{"rule_id": "VISIBLE:8.204"}])
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertNotIn("`In re Caden", saved["text"])
        self.assertNotIn("`Welf.", saved["text"])
        self.assertNotIn("`Cal. Rules", saved["text"])
        self.assertEqual(window.sidebar_kwargs["select_agent_answer_id"], entries[0]["answer_id"])
        self.assertEqual(window.statuses[-1], "Saved agent answer to Research Cache. Library preserved.")

    def test_open_agent_answer_uses_reader_text_formatting_path(self) -> None:
        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)
                self._selected_cluster = {"id": "old"}
                self._selected_statute = {"statute_id": "old"}
                self._selected_rule = {"rule_id": "old"}
                self._selected_agent_answer: dict[str, object] | None = None
                self._reader_has_official_pagination = True
                self._reader_page_markers = [object()]
                self.headers: list[str] = []
                self.reader_texts: list[str] = []
                self.reader_markdown_flags: list[bool] = []
                self.statuses: list[str] = []
                self.busy = True

            def _set_reader_busy(self, busy: bool, _message: str = "") -> None:
                self.busy = busy

            def _set_reader_header(self, text: str, *_args: object) -> None:
                self.headers.append(text)

            def _set_reader_text(
                self,
                text: str,
                *_args: object,
                apply_markdown: bool = False,
            ) -> bool:
                self.reader_texts.append(text)
                self.reader_markdown_flags.append(apply_markdown)
                return False

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            answer_id = cache.save_agent_answer(
                "See In re Caden C. (2021) 11 Cal.5th 614 and Welf. & Inst. Code, § 300.",
                mode="appeal",
                title="Saved issue",
            )
            window = DummyWindow(cache)

            OpenLawLensWindow._open_agent_answer(  # type: ignore[arg-type]
                window,
                {"answer_id": answer_id, "title": "Saved issue"},
            )

        self.assertIsNone(window._selected_cluster)
        self.assertIsNone(window._selected_statute)
        self.assertIsNone(window._selected_rule)
        self.assertEqual(window.headers, ["Saved issue"])
        self.assertEqual(
            window.reader_texts,
            ["See In re Caden C. (2021) 11 Cal.5th 614 and Welf. & Inst. Code, § 300."],
        )
        self.assertEqual(window.reader_markdown_flags, [True])
        self.assertEqual(window.statuses[-1], "Loaded saved answer: Saved issue")

    def test_reader_markdown_spans_apply_bold_to_saved_answer_text(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.reader_buffer = Gtk.TextBuffer()

            def _render_inline_markdown(
                self,
                text: str,
                base_offset: int,
            ) -> tuple[str, list[tuple[int, int, str]], list[int]]:
                return OpenLawLensWindow._render_inline_markdown(  # type: ignore[arg-type]
                    self,
                    text,
                    base_offset,
                )

        window = DummyWindow()
        rendered, spans, _offset_map = OpenLawLensWindow._render_markdown_text(  # type: ignore[arg-type]
            window,
            "- **Claim preclusion**: bars relitigation.",
        )
        window.reader_buffer.set_text(rendered)

        OpenLawLensWindow._apply_reader_markdown_spans(window, spans)  # type: ignore[arg-type]

        self.assertEqual(rendered, "- Claim preclusion: bars relitigation.")
        iter_ = window.reader_buffer.get_iter_at_offset(rendered.index("Claim"))
        tag_names = {tag.props.name for tag in iter_.get_tags()}
        self.assertIn("reader-md-bold", tag_names)

    def test_apply_statute_lookup_opens_fetched_result_without_sidebar_relookup(self) -> None:
        class DummyCache:
            def upsert_statute(self, statute: dict[str, object]) -> str:
                return str(statute["statute_id"])

        class DummyClient:
            last_lookup_source = "LegInfo"
            cache = DummyCache()

            def cached_clusters(self) -> list[dict[str, object]]:
                return []

            def cached_statutes(self) -> list[dict[str, object]]:
                return []

            def cached_rules(self) -> list[dict[str, object]]:
                return []

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self.sidebar_kwargs: dict[str, object] = {}
                self.opened: list[dict[str, object]] = []
                self.statuses: list[str] = []
                self.refreshes = 0

            def _set_sidebar_authorities(self, *args: object, **kwargs: object) -> None:
                self.sidebar_kwargs = kwargs

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                self.refreshes += int(force)

            def _open_statute_in_reader(self, statute: dict[str, object]) -> None:
                self.opened.append(statute)

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

        statute = {
            "statute_id": "WIC:300",
            "citation": "Welf. & Inst. Code, § 300",
            "text": "300. A child comes within jurisdiction.",
        }
        window = DummyWindow()

        result = OpenLawLensWindow._apply_statute_lookup_result(window, statute)  # type: ignore[arg-type]

        self.assertFalse(result)
        self.assertTrue(window.sidebar_kwargs["suppress_selection_lookup"])
        self.assertEqual(window.opened, [statute])
        self.assertEqual(window.refreshes, 1)
        self.assertEqual(window.statuses[-1], "LegInfo: opened Welf. & Inst. Code, § 300.")

    def test_apply_rule_lookup_opens_fetched_result_without_sidebar_relookup(self) -> None:
        class DummyCache:
            def upsert_rule(self, rule: dict[str, object]) -> str:
                return str(rule["rule_id"])

        class DummyClient:
            last_lookup_source = "California Courts"
            cache = DummyCache()

            def cached_clusters(self) -> list[dict[str, object]]:
                return []

            def cached_statutes(self) -> list[dict[str, object]]:
                return []

            def cached_rules(self) -> list[dict[str, object]]:
                return []

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self.sidebar_kwargs: dict[str, object] = {}
                self.opened: list[dict[str, object]] = []
                self.statuses: list[str] = []
                self.refreshes = 0

            def _set_sidebar_authorities(self, *args: object, **kwargs: object) -> None:
                self.sidebar_kwargs = kwargs

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                self.refreshes += int(force)

            def _open_rule_in_reader(self, rule: dict[str, object]) -> None:
                self.opened.append(rule)

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

        rule = {
            "rule_id": "CRC:8.11",
            "citation": "Cal. Rules of Court, rule 8.11",
            "text": "Rule 8.11. Scope.",
        }
        window = DummyWindow()

        result = OpenLawLensWindow._apply_rule_lookup_result(window, rule)  # type: ignore[arg-type]

        self.assertFalse(result)
        self.assertTrue(window.sidebar_kwargs["suppress_selection_lookup"])
        self.assertEqual(window.opened, [rule])
        self.assertEqual(window.refreshes, 1)
        self.assertEqual(window.statuses[-1], "California Courts: opened Cal. Rules of Court, rule 8.11.")

    def test_stale_statute_and_rule_results_do_not_populate_new_research_set(self) -> None:
        class DummyClient:
            def __init__(self, cache: JsonCache) -> None:
                self.cache = cache

        class DummyWindow:
            def __init__(self, cache: JsonCache) -> None:
                self.client = DummyClient(cache)
                self._research_cache_generation = 2

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            window = DummyWindow(cache)

            statute_result = OpenLawLensWindow._apply_statute_lookup_result(  # type: ignore[arg-type]
                window,
                {"statute_id": "WIC:300", "citation": "Welf. & Inst. Code, § 300"},
                1,
            )
            rule_result = OpenLawLensWindow._apply_rule_lookup_result(  # type: ignore[arg-type]
                window,
                {"rule_id": "CRC:8.11", "citation": "Cal. Rules of Court, rule 8.11"},
                1,
            )

            self.assertFalse(statute_result)
            self.assertFalse(rule_result)
            self.assertEqual(cache.list_statute_entries(), [])
            self.assertEqual(cache.list_rule_entries(), [])

    def test_stale_scholar_import_does_not_write_after_set_change(self) -> None:
        class DummyWindow:
            _research_cache_generation = 2

            def _save_imported_official_text(self, **_kwargs: object) -> bool:
                raise AssertionError("Stale Scholar result must not be saved.")

        result = OpenLawLensWindow._finish_scholar_auto_import(  # type: ignore[arg-type]
            DummyWindow(),
            "117 Cal.App.5th 379",
            ExtractedWebpage(
                "https://example.test/kg",
                "In re K.G.",
                "117 Cal.App.5th 379 (2025)\nIn re K.G.",
            ),
            SCHOLAR_FALLBACK_NOTICE_ONLY,
            1,
        )

        self.assertFalse(result)

    def test_cached_statute_row_opens_cache_without_background_refresh(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._pending_auto_scholar_cluster_id = "old"
                self._pending_auto_scholar_query = "old"
                self._last_lookup_text = ""
                self.hidden = False
                self.opened: list[dict[str, object]] = []

            def _hide_case_completion(self) -> None:
                self.hidden = True

            def _open_statute_in_reader(self, statute: dict[str, object]) -> None:
                self.opened.append(statute)

        statute = {
            "statute_id": "WIC:300",
            "citation": "Welf. & Inst. Code, § 300",
            "text": "cached text",
        }
        window = DummyWindow()

        with patch("open_law_lens.app.threading.Thread") as thread_cls:
            OpenLawLensWindow._open_cached_statute(window, statute)  # type: ignore[arg-type]

        self.assertEqual(window.opened, [statute])
        self.assertEqual(window._last_lookup_text, "Welf. & Inst. Code, § 300")
        self.assertEqual(window._pending_auto_scholar_cluster_id, "")
        self.assertEqual(window._pending_auto_scholar_query, "")
        self.assertTrue(window.hidden)
        thread_cls.assert_not_called()

    def test_cached_rule_row_opens_cache_without_background_refresh(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._pending_auto_scholar_cluster_id = "old"
                self._pending_auto_scholar_query = "old"
                self._last_lookup_text = ""
                self.hidden = False
                self.opened: list[dict[str, object]] = []

            def _hide_case_completion(self) -> None:
                self.hidden = True

            def _open_rule_in_reader(self, rule: dict[str, object]) -> None:
                self.opened.append(rule)

        rule = {
            "rule_id": "CRC:8.11",
            "citation": "Cal. Rules of Court, rule 8.11",
            "text": "cached text",
        }
        window = DummyWindow()

        with patch("open_law_lens.app.threading.Thread") as thread_cls:
            OpenLawLensWindow._open_cached_rule(window, rule)  # type: ignore[arg-type]

        self.assertEqual(window.opened, [rule])
        self.assertEqual(window._last_lookup_text, "Cal. Rules of Court, rule 8.11")
        self.assertEqual(window._pending_auto_scholar_cluster_id, "")
        self.assertEqual(window._pending_auto_scholar_query, "")
        self.assertTrue(window.hidden)
        thread_cls.assert_not_called()

    def test_stale_lookup_result_after_clear_does_not_repopulate_research_cache(self) -> None:
        class DummyList:
            def get_selected_row(self) -> object:
                return object()

            def get_row_at_index(self, _index: int) -> None:
                return None

            def select_row(self, _row: object) -> None:
                pass

        class DummyWindow:
            def __init__(self, client: CourtListenerClient) -> None:
                self.client = client
                self.case_list = DummyList()
                self._research_cache_generation = 1
                self._pending_auto_scholar_cluster_id = ""
                self._pending_auto_scholar_query = ""
                self.sidebar_snapshots: list[list[str]] = []
                self.statuses: list[str] = []
                self.refreshes = 0

            def _set_sidebar_clusters(self, clusters: list[dict[str, object]], **_kwargs: object) -> None:
                self.sidebar_snapshots.append([str(cluster.get("case_name") or "") for cluster in clusters])

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                self.refreshes += int(force)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            window = DummyWindow(client)
            stale_clusters = [
                {
                    "id": 1,
                    "case_name": "Old One",
                    "citations": [{"volume": "1", "reporter": "Cal.App.5th", "page": "1"}],
                },
                {
                    "id": 2,
                    "case_name": "Old Two",
                    "citations": [{"volume": "2", "reporter": "Cal.App.5th", "page": "2"}],
                },
            ]

            OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
                window,
                [{"status": 200, "clusters": stale_clusters}],
                stale_clusters,
                "stale",
                "old lookup",
                0,
            )

            self.assertEqual(cache.list_case_entries(), [])
            self.assertEqual(window.sidebar_snapshots, [])

            current_cluster = {
                "id": 99,
                "case_name": "New Case",
                "citations": [{"volume": "99", "reporter": "Cal.App.5th", "page": "1"}],
            }
            OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
                window,
                [{"status": 200, "clusters": [current_cluster]}],
                [current_cluster],
                "current",
                "new lookup",
                1,
            )

            self.assertEqual(
                [(entry["cluster_id"], entry["title"]) for entry in cache.list_case_entries()],
                [("99", "New Case")],
            )
            self.assertEqual(window.sidebar_snapshots[-1], ["New Case"])

    def test_lookup_result_can_open_case_without_research_cache_population(self) -> None:
        class ImmediateThread:
            def __init__(self, *, target: object, args: tuple[object, ...], daemon: bool = False) -> None:
                self.target = target
                self.args = args
                self.daemon = daemon

            def start(self) -> None:
                self.target(*self.args)  # type: ignore[misc]

        class DummyWindow:
            def __init__(self, client: CourtListenerClient) -> None:
                self.client = client
                self._research_cache_generation = 1
                self._pending_auto_scholar_cluster_id = "old"
                self._pending_auto_scholar_query = "old"
                self.loaded_clusters: list[dict[str, object]] = []
                self.worker_args: list[tuple[dict[str, object], int, int]] = []
                self.sidebar_snapshots: list[list[str]] = []
                self.statuses: list[str] = []

            def _begin_case_load(self, cluster: dict[str, object]) -> int:
                self.loaded_clusters.append(cluster)
                return 7

            def _case_worker(
                self,
                cluster: dict[str, object],
                generation: int,
                cache_generation: int,
            ) -> None:
                self.worker_args.append((cluster, generation, cache_generation))

            def _set_sidebar_clusters(self, clusters: list[dict[str, object]], **_kwargs: object) -> None:
                self.sidebar_snapshots.append([str(cluster.get("case_name") or "") for cluster in clusters])

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                pass

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            window = DummyWindow(client)
            cluster = {
                "id": 99,
                "case_name": "New Case",
                "citations": [{"volume": "99", "reporter": "Cal.App.5th", "page": "1"}],
            }

            with patch("open_law_lens.app.threading.Thread", ImmediateThread):
                OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
                    window,
                    [{"status": 200, "clusters": [cluster]}],
                    [cluster],
                    "current",
                    "new lookup",
                    1,
                    False,
                )

        self.assertEqual(cache.list_case_entries(), [])
        self.assertEqual(window.sidebar_snapshots, [])
        self.assertEqual(window.loaded_clusters, [cluster])
        self.assertEqual(window.worker_args, [(cluster, 7, -1)])
        self.assertEqual(window._pending_auto_scholar_cluster_id, "")
        self.assertEqual(window._pending_auto_scholar_query, "")

    def test_clicked_link_no_match_scholar_fallback_uses_reporter_citation(self) -> None:
        class DummyBuffer:
            def __init__(self) -> None:
                self.values: list[str] = []

            def set_text(self, value: str) -> None:
                self.values.append(value)

        class DummyWindow:
            def __init__(self) -> None:
                self.client = self
                self._research_cache_generation = 0
                self._pending_auto_scholar_cluster_id = "old"
                self._pending_auto_scholar_query = "old"
                self.reader_buffer = DummyBuffer()
                self.sidebar_snapshots: list[list[str]] = []
                self.statuses: list[str] = []
                self.busy_messages: list[str] = []
                self.scholar_queries: list[str] = []

            def cached_clusters(self) -> list[dict[str, object]]:
                return []

            def _set_reader_header(self, _text: str) -> None:
                pass

            def _set_reader_busy(self, _busy: bool, message: str = "") -> None:
                self.busy_messages.append(message)

            def _set_sidebar_clusters(self, clusters: list[dict[str, object]], **_kwargs: object) -> None:
                self.sidebar_snapshots.append([str(cluster.get("case_name") or "") for cluster in clusters])

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                pass

            def _start_scholar_auto_find(
                self,
                query: str,
                *,
                fallback_mode: str,
                auto_import: bool,
                cache_generation: int | None = None,
            ) -> None:
                del fallback_mode, auto_import, cache_generation
                self.scholar_queries.append(query)

        window = DummyWindow()

        OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
            window,
            [{"status": 404, "clusters": []}],
            [],
            "CourtListener API: no matches, status 404 (not found)",
            "In re C.L. (2025) 116 Cal.App.5th 53",
            0,
            True,
            "116 Cal.App.5th 53",
        )

        self.assertEqual(window.scholar_queries, ["116 Cal.App.5th 53"])
        self.assertEqual(window._pending_auto_scholar_cluster_id, "")
        self.assertEqual(window._pending_auto_scholar_query, "")

    def test_lookup_worker_prefers_quality_resolved_duplicate_before_display(self) -> None:
        older = {
            "id": 2282485,
            "case_name": "In Re Janet T.",
            "citations": [
                {"volume": "93", "reporter": "Cal.App.4th", "page": "377"}
            ],
        }
        preferred = {
            "id": 5808769,
            "case_name": (
                "Los Angeles County Department of Children & Family Services v. Tricia T."
            ),
            "case_name_full": "In re JANET T., Persons Coming Under the Juvenile Court Law.",
            "citations": [
                {"volume": "93", "reporter": "Cal.App.4th", "page": "377"}
            ],
        }

        class DummyClient:
            last_lookup_source = "CourtListener API"

            def __init__(self) -> None:
                self.preferred_inputs: list[list[dict[str, object]]] = []

            def lookup_citation(
                self,
                _citation: str,
                **_kwargs: object,
            ) -> list[dict[str, object]]:
                return [{"status": 300, "clusters": [older, preferred]}]

            def clusters_from_lookup(
                self,
                _result: list[dict[str, object]],
            ) -> list[dict[str, object]]:
                return [older, preferred]

            def preferred_lookup_clusters(
                self,
                clusters: list[dict[str, object]],
            ) -> list[dict[str, object]]:
                self.preferred_inputs.append(clusters)
                return [preferred]

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()

            def _lookup_clusters_for_display(
                self,
                clusters: list[dict[str, object]],
                _link: CitedCaseLink | None,
            ) -> list[dict[str, object]]:
                return clusters

            def _lookup_status_text(self, *_args: object) -> str:
                return "CourtListener API: 2 matches, 1 shown, status 300"

            def _lookup_context_text(
                self,
                citation: str,
                _link: CitedCaseLink | None,
            ) -> str:
                return citation

            def _scholar_lookup_query(
                self,
                citation: str,
                _link: CitedCaseLink | None,
            ) -> str:
                return citation

        window = DummyWindow()

        payload = OpenLawLensWindow._lookup_worker_result(  # type: ignore[arg-type]
            window,
            "93 Cal.App.4th 377",
        )

        self.assertEqual(payload[0], "success")
        self.assertEqual(payload[2], [preferred])
        self.assertEqual(window.client.preferred_inputs, [[older, preferred]])

    def test_clicked_link_cluster_match_sets_clean_pending_scholar_query(self) -> None:
        class DummyList:
            def get_selected_row(self) -> object:
                return object()

            def get_row_at_index(self, _index: int) -> None:
                return None

            def select_row(self, _row: object) -> None:
                pass

        class DummyCache:
            def __init__(self) -> None:
                self.clusters: list[dict[str, object]] = []

            def upsert_cluster(self, cluster: dict[str, object]) -> str:
                self.clusters.append(cluster)
                return str(cluster.get("id") or "")

        class DummyClient:
            def __init__(self) -> None:
                self.cache = DummyCache()

            def cached_clusters(self) -> list[dict[str, object]]:
                return self.cache.clusters

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self.case_list = DummyList()
                self._research_cache_generation = 0
                self._pending_auto_scholar_cluster_id = ""
                self._pending_auto_scholar_query = ""
                self.sidebar_snapshots: list[list[str]] = []
                self.statuses: list[str] = []

            def _set_sidebar_clusters(self, clusters: list[dict[str, object]], **_kwargs: object) -> None:
                self.sidebar_snapshots.append([str(cluster.get("case_name") or "") for cluster in clusters])

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                pass

        window = DummyWindow()
        cluster = {
            "id": "42",
            "case_name": "In re C.L.",
            "citations": [{"volume": "116", "reporter": "Cal.App.5th", "page": "53"}],
        }

        OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
            window,
            [{"status": 200, "clusters": [cluster]}],
            [cluster],
            "CourtListener API: 1 match, status 200 (exact match)",
            "In re C.L. (2025) 116 Cal.App.5th 53",
            0,
            True,
            "116 Cal.App.5th 53",
        )

        self.assertEqual(window._pending_auto_scholar_cluster_id, "42")
        self.assertEqual(window._pending_auto_scholar_query, "116 Cal.App.5th 53")

    def test_current_linked_lookup_adds_only_displayed_case_to_empty_research_cache(self) -> None:
        class DummyList:
            def get_selected_row(self) -> object:
                return object()

            def get_row_at_index(self, _index: int) -> None:
                return None

            def select_row(self, _row: object) -> None:
                pass

        class DummyWindow:
            def __init__(self, client: CourtListenerClient) -> None:
                self.client = client
                self.case_list = DummyList()
                self._research_cache_generation = 0
                self._pending_auto_scholar_cluster_id = ""
                self._pending_auto_scholar_query = ""
                self.sidebar_snapshots: list[list[str]] = []
                self.statuses: list[str] = []
                self.refreshes = 0

            def _set_sidebar_clusters(self, clusters: list[dict[str, object]], **_kwargs: object) -> None:
                self.sidebar_snapshots.append([str(cluster.get("case_name") or "") for cluster in clusters])

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
                self.refreshes += int(force)

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            window = DummyWindow(client)
            clicked_cluster = {
                "id": "external-1ae35d9d1a375146",
                "case_name": "In re M.V.",
                "citations": [{"volume": "78", "reporter": "Cal.App.5th", "page": "944"}],
            }

            OpenLawLensWindow._apply_lookup_result(  # type: ignore[arg-type]
                window,
                [{"status": 200, "clusters": [clicked_cluster]}],
                [clicked_cluster],
                "Library: 1 match, status 200 (exact match)",
                "In re M.V. (2022) 78 Cal.App.5th 944",
                0,
            )

            self.assertEqual(len(cache.list_case_entries()), 1)
            self.assertEqual(cache.list_case_entries()[0]["title"], "In re M.V.")
            self.assertEqual(window.sidebar_snapshots[-1], ["In re M.V."])

    def test_external_case_open_does_not_sync_load_suggestions(self) -> None:
        class DummyEntry:
            def set_text(self, _text: str) -> None:
                pass

        class DummyWindow:
            def __init__(self) -> None:
                self.citation_entry = DummyEntry()
                self._case_suggestions_loaded = False
                self.async_refreshes = 0
                self.opened_cases: list[str] = []

            def _set_status(self, _text: str) -> None:
                pass

            def _bare_statute_lookup_text(self, text: str) -> str:
                return OpenLawLensWindow._bare_statute_lookup_text(self, text)  # type: ignore[arg-type]

            def _external_lookup_text(self, lookup_text: str) -> str:
                return OpenLawLensWindow._external_lookup_text(self, lookup_text)  # type: ignore[arg-type]

            def _refresh_case_suggestion_index_async(self) -> None:
                self.async_refreshes += 1

            def _lookup_text_from_entry(self, _entry_text: str) -> str:
                raise AssertionError("external case open should not synchronously load suggestions")

            def _start_lookup(self, citation: str) -> None:
                self.opened_cases.append(citation)

            def _start_statute_lookup(self, _citation: str) -> None:
                raise AssertionError("case citation should not route to statute lookup")

            def _start_rule_lookup(self, _citation: str) -> None:
                raise AssertionError("case citation should not route to rule lookup")

        window = DummyWindow()

        OpenLawLensWindow.open_authority_text(  # type: ignore[arg-type]
            window,
            "See In re Caden C. (2021) 11 Cal.5th 614.",
        )

        self.assertEqual(window.async_refreshes, 1)
        self.assertEqual(window.opened_cases, ["11 Cal.5th 614"])

    def test_start_lookup_routes_bare_case_number_to_case_number_lookup(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.case_numbers: list[str] = []

            def _start_case_number_lookup(self, case_number: str) -> None:
                self.case_numbers.append(case_number)

        window = DummyWindow()

        OpenLawLensWindow._start_lookup(window, "A173218")  # type: ignore[arg-type]

        self.assertEqual(window.case_numbers, ["A173218"])

    def test_app_startup_request_uses_existing_open_authority_path(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.pending: list[str] = []

            def show_open_authority_pending(self) -> None:
                self.pending.append("pending")

            def open_authority_text(self, text: str) -> bool:
                self.pending.append(text)
                return False

        window = DummyWindow()

        with (
            patch("open_law_lens.app.pop_open_authority_request", return_value="300"),
            patch("open_law_lens.app.GLib.idle_add") as idle_add,
        ):
            OpenLawLensApp._open_startup_authority_if_requested(  # type: ignore[arg-type]
                object(),
                window,
            )

        self.assertEqual(window.pending, ["pending"])
        idle_add.assert_called_once_with(window.open_authority_text, "300")

    def test_command_line_without_open_authority_consumes_startup_request(self) -> None:
        class DummyOptions:
            def lookup_value(self, _name: str, _variant_type: object) -> None:
                return None

        class DummyCommandLine:
            def get_options_dict(self) -> DummyOptions:
                return DummyOptions()

        class DummyWindow:
            pass

        class DummyApp:
            def __init__(self) -> None:
                self.window = DummyWindow()
                self.main_window_calls = 0
                self.request_windows: list[DummyWindow] = []

            def _main_window(self) -> DummyWindow:
                self.main_window_calls += 1
                return self.window

            def _open_startup_authority_if_requested(self, window: DummyWindow) -> None:
                self.request_windows.append(window)

        app = DummyApp()

        status = OpenLawLensApp._on_command_line(  # type: ignore[arg-type]
            app,
            object(),
            DummyCommandLine(),
        )

        self.assertEqual(status, 0)
        self.assertEqual(app.main_window_calls, 1)
        self.assertEqual(app.request_windows, [app.window])

    def test_research_cache_row_content_uses_trailing_action_rail(self) -> None:
        remove_button = Gtk.Button(icon_name="user-trash-symbolic")
        check = Gtk.CheckButton()

        content = OpenLawLensWindow._build_research_cache_row_content(
            "In re Caden C.",
            "(2021) 11 Cal.5th 614",
            remove_button,
            check,
        )

        text_box = content.get_first_child()
        actions_box = text_box.get_next_sibling()
        self.assertEqual(text_box.get_first_child().get_text(), "In re Caden C.")
        self.assertEqual(
            text_box.get_last_child().get_text(),
            "(2021) 11 Cal.5th 614",
        )
        self.assertTrue(actions_box.has_css_class("cache-row-actions"))
        self.assertIs(actions_box.get_first_child(), remove_button)
        self.assertIs(actions_box.get_last_child(), check)
        self.assertTrue(remove_button.has_css_class("cache-row-remove-button"))
        self.assertTrue(check.has_css_class("neutral-agent-check"))

    def test_research_cache_section_header_is_plain_and_nonselectable(self) -> None:
        row = OpenLawLensWindow._build_research_cache_section_header(
            "Authorities",
            "authority_header",
        )

        label = row.get_child()
        self.assertEqual(label.get_text(), "Authorities")
        self.assertTrue(label.has_css_class("dim-label"))
        self.assertTrue(label.has_css_class("cache-section-label"))
        self.assertFalse(row.get_selectable())
        self.assertFalse(row.get_activatable())
        self.assertEqual(row._open_law_lens_cache_section, "authority_header")

    def test_research_cache_sort_orders_section_headers_before_items(self) -> None:
        window = OpenLawLensWindow.__new__(OpenLawLensWindow)
        sections = (
            "authority_header",
            "authority",
            "prior_brief_header",
            "prior_brief",
            "agent_answer_header",
            "agent_answer",
        )
        rows = []
        for section in sections:
            row = Gtk.ListBoxRow()
            row._open_law_lens_cache_section = section
            row._open_law_lens_cache_sort_key = ("", "", "", "", "")
            rows.append(row)

        for earlier, later in zip(rows, rows[1:]):
            self.assertLess(
                OpenLawLensWindow._sort_research_cache_rows(window, earlier, later),
                0,
            )

    def test_first_selectable_research_cache_row_skips_section_header(self) -> None:
        window = OpenLawLensWindow.__new__(OpenLawLensWindow)
        window.case_list = Gtk.ListBox()
        header = OpenLawLensWindow._build_research_cache_section_header(
            "Authorities",
            "authority_header",
        )
        item = Gtk.ListBoxRow()
        item.set_selectable(True)
        window.case_list.append(header)
        window.case_list.append(item)

        selected = OpenLawLensWindow._first_selectable_research_cache_row(window)

        self.assertIs(selected, item)

    def test_research_cache_clear_action_lives_in_sidebar_header_not_menu(self) -> None:
        class DummyWindow:
            pass

        header = OpenLawLensWindow._build_research_cache_header(DummyWindow())  # type: ignore[arg-type]
        header_row = header.get_first_child()
        heading = header_row.get_first_child()
        save_button = heading.get_next_sibling()
        research_sets_button = save_button.get_next_sibling()
        clear_button = header_row.get_last_child()
        set_label = header.get_last_child()

        self.assertEqual(heading.get_text(), "Research Cache")
        self.assertEqual(set_label.get_text(), "")
        self.assertFalse(set_label.get_visible())
        self.assertIsInstance(research_sets_button, Gtk.MenuButton)
        self.assertEqual(research_sets_button.get_tooltip_text(), "Open Research Set")
        self.assertIsNotNone(research_sets_button.get_popover())
        self.assertEqual(clear_button.get_action_name(), "win.clear_cache")
        self.assertEqual(clear_button.get_tooltip_text(), "Clear Research Cache")

        menu_button = OpenLawLensWindow._build_menu_button(DummyWindow())  # type: ignore[arg-type]
        menu = menu_button.get_menu_model()
        labels = [
            menu.get_item_attribute_value(index, "label").get_string()
            for index in range(menu.get_n_items())
        ]
        self.assertNotIn("Clear Research Cache", labels)
        self.assertNotIn("Find Official Text", labels)
        self.assertNotIn("Import Official Text", labels)

    def test_research_sets_dropdown_lists_saved_sets(self) -> None:
        research_set = ResearchSet(
            set_id=7,
            name="Dependency appeal",
            created_at="",
            updated_at="",
            last_accessed="",
            item_count=3,
            case_count=1,
            statute_count=1,
            rule_count=0,
            agent_answer_count=1,
            items=[],
        )

        class DummyLibrary:
            def list_research_sets(self) -> list[ResearchSet]:
                return [research_set]

        class DummyClient:
            def __init__(self) -> None:
                self.library = DummyLibrary()

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self._research_sets_menu_button = Gtk.MenuButton()

        window = DummyWindow()
        OpenLawLensWindow._refresh_research_sets_menu(window)  # type: ignore[arg-type]

        def first_descendant(widget: Gtk.Widget, widget_type: type[Gtk.Widget]) -> Gtk.Widget | None:
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, widget_type):
                    return child
                descendant = first_descendant(child, widget_type)
                if descendant is not None:
                    return descendant
                child = child.get_next_sibling()
            return None

        popover = window._research_sets_menu_button.get_popover()
        list_box = first_descendant(popover, Gtk.ListBox)
        self.assertIsNotNone(list_box)
        self.assertIsNone(first_descendant(popover, Gtk.ScrolledWindow))
        row = list_box.get_first_child()
        row_box = row.get_child()
        name_button = row_box.get_first_child()
        delete_button = row_box.get_last_child()

        self.assertEqual(name_button.get_label(), "Dependency appeal")
        self.assertEqual(name_button.get_tooltip_text(), "Open Research Set")
        self.assertIs(delete_button.get_prev_sibling(), name_button)
        self.assertEqual(delete_button.get_tooltip_text(), "Delete Research Set")

    def test_research_set_delete_from_dropdown_is_immediate(self) -> None:
        class DummyLibrary:
            def __init__(self) -> None:
                self.deleted: list[int] = []

            def delete_research_set(self, set_id: int) -> bool:
                self.deleted.append(set_id)
                return True

            def list_research_sets(self) -> list[ResearchSet]:
                return []

        class DummyClient:
            def __init__(self) -> None:
                self.library = DummyLibrary()

        class DummyWindow:
            def __init__(self) -> None:
                self.client = DummyClient()
                self._active_research_set_id = 7
                self._active_research_set_name = "Dependency appeal"
                self._active_research_set_dirty = False
                self._research_set_label = None
                self._research_sets_menu_button = None
                self.statuses: list[str] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _set_active_research_set(self, research_set: ResearchSet | None) -> None:
                OpenLawLensWindow._set_active_research_set(self, research_set)  # type: ignore[arg-type]

            def _refresh_research_sets_menu(self) -> None:
                OpenLawLensWindow._refresh_research_sets_menu(self)  # type: ignore[arg-type]

        window = DummyWindow()
        OpenLawLensWindow._on_delete_research_set_clicked(window, Gtk.Button(), 7)  # type: ignore[arg-type]

        self.assertEqual(window.client.library.deleted, [7])
        self.assertIsNone(window._active_research_set_id)
        self.assertEqual(window.statuses, ["Deleted Research Set."])

    def test_reader_statute_selection_pinpoint_uses_inferred_subdivision(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_text = "300. (a) First.\n(b) Second.\n(1) One.\n(2) Two."
                self._selected_statute = {
                    "law_code": "WIC",
                    "section": "300",
                    "citation": "Welf. & Inst. Code, § 300",
                }
                self._selected_rule = None

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("One"),
            window._reader_text.index("Two") + len("Two"),
        )

        self.assertEqual(citation, "Welf. & Inst. Code, § 300, subds. (b)(1)-(2)")

    def test_reader_rule_selection_pinpoint_uses_inferred_subdivision(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_text = (
                    "Rule 8.204. Briefs.\n"
                    "(a) Contents.\n"
                    "(1) Each brief must.\n"
                    "(A) State facts.\n"
                    "(B) Cite authority."
                )
                self._selected_statute = None
                self._selected_rule = {
                    "rule_number": "8.204",
                    "citation": "Cal. Rules of Court, rule 8.204",
                }

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("State facts"),
            window._reader_text.index("Cite authority") + len("Cite authority"),
        )

        self.assertEqual(citation, "Cal. Rules of Court, rule 8.204(a)(1)(A)-(B)")

    def test_reader_case_selection_pinpoint_uses_current_page(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_text = "[*631] Substantial evidence supports the finding."
                self._reader_page_markers = [
                    PageMarker("631", "[*631]", 0, 6, "plain_text"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("Substantial"),
            len(window._reader_text),
        )

        self.assertEqual(citation, "In re Caden C. (2021) 11 Cal.5th 614, 631")

    def test_reader_case_selection_slip_pinpoint_uses_case_number_and_slip_page(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Bella L. et al.",
                    "date_filed": "2026-01-20",
                    "docket": {"docket_number": "B348279"},
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_pagination_mode = "slip"
                self._reader_slip_case_number = "B348279"
                self._reader_text = "[Slip opn. p. 7]\nFirst page. [Slip opn. p. 9]\nThird page."
                self._reader_page_markers = [
                    PageMarker("7", "[Slip opn. p. 7]", 0, 16, "slip_pdf"),
                    PageMarker("9", "[Slip opn. p. 9]", 29, 45, "slip_pdf"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("First"),
            len(window._reader_text),
        )

        self.assertEqual(
            citation,
            "In re Bella L. et al. (January 20, 2026, B348279) ___ Cal.App.5th ___ slip opn. at pp. 7-9",
        )

    def test_reader_case_selection_slip_pinpoint_html_italicizes_case_name(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Bella L. et al.",
                    "date_filed": "2026-01-20",
                    "docket": {"docket_number": "B348279"},
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_pagination_mode = "slip"
                self._reader_slip_case_number = "B348279"
                self._reader_text = "[Slip opn. p. 7]\nFirst page."
                self._reader_page_markers = [
                    PageMarker("7", "[Slip opn. p. 7]", 0, 16, "slip_pdf"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_formatted_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("First"),
            len(window._reader_text),
        )

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(
            citation.html_text,
            "<i>In re Bella L. et al.</i> (January 20, 2026, B348279) "
            "___ Cal.App.5th ___ slip opn. at p. 7",
        )

    def test_copy_reader_selection_slip_pinpoint_copies_text_and_full_citation(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Bella L. et al.",
                    "date_filed": "2026-01-20",
                    "docket": {"docket_number": "B348279"},
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_pagination_mode = "slip"
                self._reader_slip_case_number = "B348279"
                self._reader_text = "[Slip opn. p. 7]\nSelected text."
                self._reader_page_markers = [
                    PageMarker("7", "[Slip opn. p. 7]", 0, 16, "slip_pdf"),
                ]
                self.copied: list[FormattedCitation] = []
                self.statuses: list[str] = []

            def _reader_selection_bounds(self) -> tuple[int, int, str]:
                start = self._reader_text.index("Selected")
                end = len(self._reader_text)
                return start, end, self._reader_text[start:end]

            def _reader_selection_pinpoint_formatted_citation(
                self,
                start_offset: int,
                end_offset: int,
            ) -> FormattedCitation | None:
                return OpenLawLensWindow._reader_selection_pinpoint_formatted_citation(  # type: ignore[arg-type]
                    self,
                    start_offset,
                    end_offset,
                )

            def _clipboard_selected_authority_text(
                self,
                text: str,
                *,
                strip_page_markers: bool = False,
            ) -> str:
                return OpenLawLensWindow._clipboard_selected_authority_text(
                    text,
                    strip_page_markers=strip_page_markers,
                )

            def _selection_pinpoint_clipboard_payload(
                self,
                selected_text: str,
                citation: FormattedCitation,
            ) -> FormattedCitation:
                return OpenLawLensWindow._selection_pinpoint_clipboard_payload(
                    selected_text,
                    citation,
                )

            def _set_formatted_clipboard(
                self,
                citation: FormattedCitation,
                _failure_message: str,
            ) -> bool:
                self.copied.append(citation)
                return True

            def _set_status(self, text: str) -> None:
                self.statuses.append(text)

        window = DummyWindow()

        OpenLawLensWindow._on_copy_reader_clipboard_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(
            window.copied[0].plain_text,
            "Selected text. (In re Bella L. et al. (January 20, 2026, B348279) "
            "___ Cal.App.5th ___ slip opn. at p. 7.)",
        )
        self.assertEqual(
            window.copied[0].html_text,
            "Selected text. (<i>In re Bella L. et al.</i> (January 20, 2026, B348279) "
            "___ Cal.App.5th ___ slip opn. at p. 7.)",
        )

    def test_reader_case_selection_pinpoint_html_italicizes_case_name(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_text = "[*631] Substantial evidence supports the finding."
                self._reader_page_markers = [
                    PageMarker("631", "[*631]", 0, 6, "plain_text"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_formatted_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("Substantial"),
            len(window._reader_text),
        )

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Caden C. (2021) 11 Cal.5th 614, 631")
        self.assertEqual(
            citation.html_text,
            "<i>In re Caden C.</i> (2021) 11 Cal.5th 614, 631",
        )

    def test_reader_case_selection_pinpoint_uses_en_dash_page_range(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_text = "[*631] First page text. [*632] Second page text."
                self._reader_page_markers = [
                    PageMarker("631", "[*631]", 0, 6, "plain_text"),
                    PageMarker("632", "[*632]", 24, 30, "plain_text"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            window._reader_text.index("First"),
            len(window._reader_text),
        )

        self.assertEqual(citation, "In re Caden C. (2021) 11 Cal.5th 614, 631–632")

    def test_reader_case_selection_before_first_marker_uses_official_first_page(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_text = "Syllabus text before markers. [*631] Opinion text."
                self._reader_page_markers = [
                    PageMarker("631", "[*631]", 30, 36, "plain_text"),
                ]

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            0,
            window._reader_text.index("markers"),
        )

        self.assertEqual(citation, "In re Caden C. (2021) 11 Cal.5th 614, 614")

    def test_reader_case_selection_without_markers_returns_empty_pinpoint(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_page_markers = []

        window = DummyWindow()

        citation = OpenLawLensWindow._reader_selection_pinpoint_citation(  # type: ignore[arg-type]
            window,
            0,
            10,
        )

        self.assertEqual(citation, "")

    def test_helper_case_available_only_for_unofficial_case_with_citation_and_text(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._reader_has_official_pagination = False
                self._reader_text = "Unpaginated text."

        window = DummyWindow()

        self.assertTrue(OpenLawLensWindow._helper_case_available(window))  # type: ignore[arg-type]
        window._reader_has_official_pagination = True
        self.assertFalse(OpenLawLensWindow._helper_case_available(window))  # type: ignore[arg-type]
        window._reader_has_official_pagination = False
        window._reader_text = ""
        self.assertFalse(OpenLawLensWindow._helper_case_available(window))  # type: ignore[arg-type]

    def test_helper_case_agent_prompt_uses_bounded_published_cli_command(self) -> None:
        class DummyWindow:
            pass

        window = DummyWindow()
        prompt = OpenLawLensWindow._compose_helper_case_agent_prompt(  # type: ignore[arg-type]
            window,
            {
                "id": 42,
                "case_name_short": "Target Case",
                "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
            },
            "42",
            "10 Cal.App.5th 25",
        )

        self.assertIn("best-published-citing-case --cluster-id 42 --json", prompt)
        self.assertIn("first-page published citing-case result", prompt)
        self.assertIn("Do not continue crawling CourtListener", prompt)
        self.assertIn("Target official citation: 10 Cal.App.5th 25", prompt)

    def test_later_treatment_agent_prompt_uses_published_citing_cases_command(self) -> None:
        class DummyWindow:
            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

        window = DummyWindow()
        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            prompt = OpenLawLensWindow._compose_later_treatment_agent_prompt(  # type: ignore[arg-type]
                window,
                {
                    "id": 42,
                    "case_name_short": "Target Case",
                    "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
                },
                "42",
                "10 Cal.App.5th 25",
            )

        self.assertIn("published-citing-cases --cluster-id 42 --limit 10 --json", prompt)
        self.assertIn("extract-case --cluster-id <cluster_id>", prompt)
        self.assertIn("Google Scholar", prompt)
        self.assertIn("citation remains uncertain", prompt)
        self.assertIn("use normal legal prose for case names and citations", prompt)
        self.assertIn("agreed with it, distinguished it, limited it", prompt)
        self.assertIn("Target official citation: 10 Cal.App.5th 25", prompt)

    def test_reader_helper_button_follows_helper_availability(self) -> None:
        class DummyButton:
            def __init__(self) -> None:
                self.visible = False
                self.sensitive = False
                self.tooltip = ""

            def set_visible(self, value: bool) -> None:
                self.visible = value

            def set_sensitive(self, value: bool) -> None:
                self.sensitive = value

            def set_tooltip_text(self, value: str) -> None:
                self.tooltip = value

        class DummyWindow:
            def __init__(self) -> None:
                self.reader_clipboard_button = DummyButton()
                self.reader_helper_case_button = DummyButton()
                self._selected_cluster = {
                    "case_name_short": "In re Caden C.",
                    "date_filed": "2021-05-27",
                    "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
                }
                self._selected_statute = None
                self._selected_rule = None
                self._reader_has_official_pagination = False
                self._reader_text = "Unpaginated text."
                self.selection: tuple[int, int, str] | None = None

            def _reader_selection_bounds(self) -> tuple[int, int, str] | None:
                return self.selection

            def _helper_case_available(self) -> bool:
                return OpenLawLensWindow._helper_case_available(self)  # type: ignore[arg-type]

            def _update_reader_helper_case_button(self) -> None:
                OpenLawLensWindow._update_reader_helper_case_button(self)  # type: ignore[arg-type]

        window = DummyWindow()

        OpenLawLensWindow._update_reader_clipboard_button(window)  # type: ignore[arg-type]
        self.assertTrue(window.reader_helper_case_button.visible)
        self.assertTrue(window.reader_helper_case_button.sensitive)

        window._reader_has_official_pagination = True
        OpenLawLensWindow._update_reader_clipboard_button(window)  # type: ignore[arg-type]

        self.assertFalse(window.reader_helper_case_button.visible)
        self.assertFalse(window.reader_helper_case_button.sensitive)

    def test_reader_clipboard_button_tracks_selection_mode(self) -> None:
        class DummyButton:
            def __init__(self) -> None:
                self.sensitive = False
                self.tooltip = ""

            def set_sensitive(self, value: bool) -> None:
                self.sensitive = value

            def set_tooltip_text(self, value: str) -> None:
                self.tooltip = value

        class DummyWindow:
            def __init__(self) -> None:
                self.reader_clipboard_button = DummyButton()
                self._reader_header_citation = FormattedCitation(
                    plain_text="In re Caden C. (2021) 11 Cal.5th 614",
                    html_text="<i>In re Caden C.</i> (2021) 11 Cal.5th 614",
                )
                self._reader_display_cluster = None
                self._selected_cluster: dict[str, object] | None = {}
                self._selected_statute = None
                self._selected_rule = None
                self.selection: tuple[int, int, str] | None = None

            def _reader_selection_bounds(self) -> tuple[int, int, str] | None:
                return self.selection

            def _update_reader_helper_case_button(self) -> None:
                pass

        window = DummyWindow()

        OpenLawLensWindow._update_reader_clipboard_button(window)  # type: ignore[arg-type]
        self.assertTrue(window.reader_clipboard_button.sensitive)
        self.assertEqual(window.reader_clipboard_button.tooltip, "Copy citation")

        window.selection = (0, 4, "Text")
        OpenLawLensWindow._update_reader_clipboard_button(window)  # type: ignore[arg-type]
        self.assertTrue(window.reader_clipboard_button.sensitive)
        self.assertEqual(
            window.reader_clipboard_button.tooltip,
            "Copy selected text with pinpoint citation",
        )

        window.selection = None
        window._reader_header_citation = None
        OpenLawLensWindow._update_reader_clipboard_button(window)  # type: ignore[arg-type]
        self.assertFalse(window.reader_clipboard_button.sensitive)

    def test_case_header_shows_subsequent_treatment_button_for_displayed_cluster(self) -> None:
        class DummyLabel:
            def __init__(self) -> None:
                self.text = ""

            def set_text(self, value: str) -> None:
                self.text = value

        class DummyButton:
            def __init__(self) -> None:
                self.visible = False
                self.sensitive = False
                self.tooltip = ""

            def set_visible(self, value: bool) -> None:
                self.visible = value

            def set_sensitive(self, value: bool) -> None:
                self.sensitive = value

            def set_tooltip_text(self, value: str) -> None:
                self.tooltip = value

        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster: dict[str, object] | None = {}
                self._reader_display_cluster: dict[str, object] | None = None
                self._selected_statute = None
                self._selected_rule = None
                self._reader_header_citation = None
                self.reader_header_label = DummyLabel()
                self.reader_clipboard_button = DummyButton()
                self.reader_subsequent_treatment_button = DummyButton()
                self.reader_helper_case_button = DummyButton()
                self.reader_header_box = DummyButton()

            def _reader_selection_bounds(self) -> None:
                return None

            def _update_reader_clipboard_button(self) -> None:
                OpenLawLensWindow._update_reader_clipboard_button(self)  # type: ignore[arg-type]

            def _helper_case_available(self) -> bool:
                return False

            def _update_reader_helper_case_button(self) -> None:
                OpenLawLensWindow._update_reader_helper_case_button(self)  # type: ignore[arg-type]

        window = DummyWindow()

        OpenLawLensWindow._set_reader_header(  # type: ignore[arg-type]
            window,
            "Displayed Case",
            cluster={},
        )

        self.assertTrue(window.reader_subsequent_treatment_button.visible)
        self.assertTrue(window.reader_subsequent_treatment_button.sensitive)
        self.assertFalse(window.reader_helper_case_button.visible)

    def test_helper_case_click_launches_general_agent_prompt(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "id": 42,
                    "case_name_short": "Target Case",
                    "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
                }
                self._agent_terminal = object()
                self._case_agent_text_sources = ["old"]
                self._agent_mode = "case"
                self.statuses: list[str] = []
                self.prompt = ""
                self.selected_modes: list[str] = []
                self.launches: list[tuple[Path, Path, str]] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _write_prompt_file(self, prompt: str) -> Path:
                self.prompt = prompt
                return Path("/tmp/helper-prompt.txt")

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/helper-workspace")

            def _set_agent_mode(self, mode: str) -> None:
                self.selected_modes.append(mode)

            def _launch_agent_with_prompt(
                self,
                prompt_path: Path,
                workspace: Path,
                mode: str,
                reasoning_effort: str = "",
            ) -> None:
                self.launches.append((prompt_path, workspace, mode, reasoning_effort))

        window = DummyWindow()

        with patch("open_law_lens.app.Vte", object()):
            OpenLawLensWindow._on_helper_case_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(window.statuses, [])
        self.assertIn("best-published-citing-case --cluster-id 42 --json", window.prompt)
        self.assertEqual(window.selected_modes, ["general"])
        self.assertEqual(window._case_agent_text_sources, [])
        self.assertEqual(window._agent_mode, "general")
        self.assertEqual(
            window.launches,
            [(Path("/tmp/helper-prompt.txt"), Path("/tmp/helper-workspace"), "general", "")],
        )

    def test_later_treatment_click_launches_general_agent_prompt(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._selected_cluster = {
                    "id": 42,
                    "case_name_short": "Target Case",
                    "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
                }
                self._agent_terminal = object()
                self._case_agent_text_sources = ["old"]
                self._agent_mode = "case"
                self.statuses: list[str] = []
                self.prompt = ""
                self.selected_modes: list[str] = []
                self.launches: list[tuple[Path, Path, str]] = []

            def _set_status(self, status: str) -> None:
                self.statuses.append(status)

            def _write_prompt_file(self, prompt: str) -> Path:
                self.prompt = prompt
                return Path("/tmp/later-prompt.txt")

            def _create_agent_workspace(self) -> Path:
                return Path("/tmp/later-workspace")

            def _set_agent_mode(self, mode: str) -> None:
                self.selected_modes.append(mode)

            def _format_agent_prompt(
                self,
                template: str,
                fallback: str,
                values: dict[str, object],
            ) -> str:
                return OpenLawLensWindow._format_agent_prompt(  # type: ignore[arg-type]
                    self,
                    template,
                    fallback,
                    values,
                )

            def _launch_agent_with_prompt(
                self,
                prompt_path: Path,
                workspace: Path,
                mode: str,
                reasoning_effort: str = "",
            ) -> None:
                self.launches.append((prompt_path, workspace, mode, reasoning_effort))

        window = DummyWindow()

        with (
            patch("open_law_lens.app.Vte", object()),
            patch("open_law_lens.app.load_config", return_value=AppConfig()),
        ):
            OpenLawLensWindow._on_later_treatment_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(window.statuses, [])
        self.assertIn("published-citing-cases --cluster-id 42 --limit 10 --json", window.prompt)
        self.assertEqual(window.selected_modes, ["general"])
        self.assertEqual(window._case_agent_text_sources, [])
        self.assertEqual(window._agent_mode, "general")
        self.assertEqual(
            window.launches,
            [(Path("/tmp/later-prompt.txt"), Path("/tmp/later-workspace"), "general", "")],
        )

    def test_case_clipboard_text_strips_reader_page_markers(self) -> None:
        text = OpenLawLensWindow._clipboard_selected_authority_text(
            "First page [*631] second page [Slip opn. p. 4] third page.",
            strip_page_markers=True,
        )

        self.assertEqual(text, "First page second page third page.")

    def test_selection_pinpoint_clipboard_payload_preserves_citation_html(self) -> None:
        payload = OpenLawLensWindow._selection_pinpoint_clipboard_payload(
            "Selected <text>",
            FormattedCitation(
                plain_text="In re Caden C. (2021) 11 Cal.5th 614, 631",
                html_text="<i>In re Caden C.</i> (2021) 11 Cal.5th 614, 631",
            ),
        )

        self.assertEqual(
            payload.plain_text,
            "Selected <text> (In re Caden C. (2021) 11 Cal.5th 614, 631.)",
        )
        self.assertEqual(
            payload.html_text,
            "Selected &lt;text&gt; (<i>In re Caden C.</i> (2021) 11 Cal.5th 614, 631.)",
        )

    def test_copy_reader_citation_uses_reader_header_citation(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_header_citation = FormattedCitation(
                    plain_text="In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___",
                    html_text="<i>In re L.G.</i> (Mar. 6, 2026, A173218) ___ Cal.App.5th ___",
                )
                self.copied: list[FormattedCitation] = []

            def _copy_formatted_citation(self, citation: FormattedCitation) -> None:
                self.copied.append(citation)

            def _reader_selection_bounds(self) -> None:
                return None

        window = DummyWindow()

        OpenLawLensWindow._on_copy_reader_clipboard_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(
            window.copied[0].plain_text,
            "In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___",
        )

    def test_copy_reader_clipboard_warns_without_citation_or_selection(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_header_citation = None
                self.statuses: list[str] = []

            def _reader_selection_bounds(self) -> None:
                return None

            def _set_status(self, text: str) -> None:
                self.statuses.append(text)

        window = DummyWindow()

        OpenLawLensWindow._on_copy_reader_clipboard_clicked(  # type: ignore[arg-type]
            window,
            object(),
        )

        self.assertEqual(
            window.statuses,
            ["No citation available to copy."],
        )

    def test_copy_reader_clipboard_does_not_fall_back_when_pinpoint_is_unavailable(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self._reader_header_citation = FormattedCitation(
                    plain_text="In re Caden C. (2021) 11 Cal.5th 614",
                    html_text="<i>In re Caden C.</i> (2021) 11 Cal.5th 614",
                )
                self.copied: list[FormattedCitation] = []
                self.statuses: list[str] = []

            def _reader_selection_bounds(self) -> tuple[int, int, str]:
                return 0, 4, "Text"

            def _reader_selection_pinpoint_formatted_citation(
                self,
                _start_offset: int,
                _end_offset: int,
            ) -> None:
                return None

            def _copy_formatted_citation(self, citation: FormattedCitation) -> None:
                self.copied.append(citation)

            def _set_status(self, text: str) -> None:
                self.statuses.append(text)

        window = DummyWindow()

        OpenLawLensWindow._on_copy_reader_clipboard_clicked(window, object())  # type: ignore[arg-type]

        self.assertEqual(window.copied, [])
        self.assertEqual(
            window.statuses,
            ["Could not determine a pinpoint citation for the selected text."],
        )

    def test_background_worker_marshals_success_to_idle(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.results: list[str] = []

        window = DummyWindow()

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda callback, *args: callback(*args)):
            OpenLawLensWindow._background_worker(  # type: ignore[arg-type]
                window,
                lambda: "done",
                lambda result: window.results.append(result),
                None,
                (Exception,),
            )

        self.assertEqual(window.results, ["done"])

    def test_background_worker_marshals_error_to_idle(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.errors: list[str] = []

            def _apply_error(self, message: str) -> bool:
                self.errors.append(message)
                return False

        window = DummyWindow()

        with patch("open_law_lens.app.GLib.idle_add", side_effect=lambda callback, *args: callback(*args)):
            OpenLawLensWindow._background_worker(  # type: ignore[arg-type]
                window,
                lambda: (_ for _ in ()).throw(ValueError("bad input")),
                None,
                None,
                (ValueError,),
            )

        self.assertEqual(window.errors, ["bad input"])

    def test_pinpoint_citation_parenthetical_places_period_inside(self) -> None:
        parenthetical = OpenLawLensWindow._pinpoint_citation_parenthetical(
            "Welf. & Inst. Code, § 388, subd. (a)(2)"
        )

        self.assertEqual(
            parenthetical,
            "(Welf. & Inst. Code, § 388, subd. (a)(2).)",
        )


if __name__ == "__main__":
    unittest.main()
