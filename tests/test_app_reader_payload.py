from __future__ import annotations

import tempfile
import unittest
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from open_law_lens.app import (
    SCHOLAR_FALLBACK_NOTICE_ONLY,
    SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
    Gtk,
    OpenLawLensApp,
    OpenLawLensWindow,
    appeal_issue_menu_label,
    build_agent_launch_env,
    build_case_reader_payload,
)
from open_law_lens.cache import JsonCache
from open_law_lens.citation_links import CitedCaseLink
from open_law_lens.client import FormattedCitation
from open_law_lens.config import AppConfig
from open_law_lens.fact_patterns import FactPatternExport
from open_law_lens.library import DisplayText, PageMarker
from open_law_lens.web_import import ExtractedWebpage


class AppReaderPayloadTests(unittest.TestCase):
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
        self.assertEqual(env["OPEN_LAW_LENS_CACHE_DIR"], "/tmp/open-law-lens-cache")
        self.assertEqual(
            env["OPEN_LAW_LENS_LIBRARY_DB"],
            "/tmp/open-law-lens-library/library.sqlite3",
        )

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

    def test_appeal_issue_prompt_includes_issue_fact_pattern_and_cli_guidance(self) -> None:
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
        self.assertIn("/tmp/workspace/fact_pattern/facts_extracted.txt", prompt)
        self.assertIn("uv run open-law-lens case-search", prompt)
        self.assertIn("Rating: Strong, Medium, Weak, or Frivolous", prompt)

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
                self.launches: list[tuple[Path, Path, str]] = []

            def _launch_agent_with_prompt(
                self,
                prompt_path: Path,
                workspace: Path,
                mode: str,
            ) -> None:
                self.launches.append((prompt_path, workspace, mode))

        window = DummyWindow()

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
            [(Path("/tmp/prompt.txt"), Path("/tmp/workspace"), "appeal")],
        )

    def test_appeal_issue_menu_label_uses_first_nonblank_line_and_truncates(self) -> None:
        self.assertEqual(
            appeal_issue_menu_label("\n  First issue line.  \nSecond line."),
            "First issue line.",
        )
        self.assertEqual(appeal_issue_menu_label("", max_length=12), "Untitled issue")
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

    def test_appeal_issue_menu_includes_custom_claim_action(self) -> None:
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

        window = DummyWindow()
        window._appeal_issue_menu_button = Gtk.MenuButton()

        with patch("open_law_lens.app.load_config", return_value=AppConfig(appeal_issue_presets=["Issue one"])):
            OpenLawLensWindow._refresh_appeal_issue_menu(window)  # type: ignore[arg-type]

        popover = window._appeal_issue_menu_button.get_popover()
        self.assertIsNotNone(popover)
        assert popover is not None
        self.assertEqual(labels(popover), ["Custom claim...", "Issue one", "Edit appeal issues..."])

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
        self.assertEqual(window.statuses, ["Enter an issue to assess."])

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
            ) -> None:
                self.auto_find_calls.append(
                    {
                        "query": query,
                        "fallback_mode": fallback_mode,
                        "auto_import": auto_import,
                    }
                )

            def _update_reader_selection_pinpoint_button(self) -> None:
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
                }
            ],
        )

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

    def test_reader_and_agent_citation_links_use_shared_lookup_path(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.opened: list[str] = []
                self.links: list[CitedCaseLink | None] = []

            def _start_lookup(self, citation: str, *, link: CitedCaseLink | None = None) -> None:
                self.opened.append(citation)
                self.links.append(link)

            def _open_citation_lookup_link(self, link: CitedCaseLink) -> None:
                OpenLawLensWindow._open_citation_lookup_link(self, link)  # type: ignore[arg-type]

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
        self.assertEqual(window.links, [link, link])

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

    def test_apply_statute_lookup_opens_fetched_result_without_sidebar_relookup(self) -> None:
        class DummyClient:
            last_lookup_source = "LegInfo"

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
        class DummyClient:
            last_lookup_source = "California Courts"

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

    def test_research_cache_clear_action_lives_in_sidebar_header_not_menu(self) -> None:
        class DummyWindow:
            pass

        header = OpenLawLensWindow._build_research_cache_header(DummyWindow())  # type: ignore[arg-type]
        heading = header.get_first_child()
        clear_button = header.get_last_child()

        self.assertEqual(heading.get_text(), "Research Cache")
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

    def test_helper_case_button_does_not_require_selection(self) -> None:
        class DummyButton:
            def __init__(self) -> None:
                self.visible = False
                self.sensitive = False

            def set_visible(self, value: bool) -> None:
                self.visible = value

            def set_sensitive(self, value: bool) -> None:
                self.sensitive = value

        class DummyWindow:
            def __init__(self) -> None:
                self.reader_selection_pinpoint_button = DummyButton()
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

        window = DummyWindow()

        OpenLawLensWindow._update_reader_selection_pinpoint_button(window)  # type: ignore[arg-type]
        self.assertTrue(window.reader_helper_case_button.visible)
        self.assertTrue(window.reader_helper_case_button.sensitive)

        window._reader_has_official_pagination = True
        OpenLawLensWindow._update_reader_selection_pinpoint_button(window)  # type: ignore[arg-type]

        self.assertFalse(window.reader_helper_case_button.visible)
        self.assertFalse(window.reader_helper_case_button.sensitive)

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
            ) -> None:
                self.launches.append((prompt_path, workspace, mode))

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
            [(Path("/tmp/helper-prompt.txt"), Path("/tmp/helper-workspace"), "general")],
        )

    def test_case_clipboard_text_strips_reader_page_markers(self) -> None:
        text = OpenLawLensWindow._clipboard_selected_authority_text(
            "First page [*631] second page.",
            strip_page_markers=True,
        )

        self.assertEqual(text, "First page second page.")

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

    def test_copy_reader_selection_pinpoint_warns_without_selection(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.statuses: list[str] = []

            def _reader_selection_bounds(self) -> None:
                return None

            def _set_status(self, text: str) -> None:
                self.statuses.append(text)

        window = DummyWindow()

        OpenLawLensWindow._on_copy_reader_selection_pinpoint_clicked(  # type: ignore[arg-type]
            window,
            object(),
        )

        self.assertEqual(
            window.statuses,
            ["Select case, statute, or rule text before copying a pinpoint citation."],
        )

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
