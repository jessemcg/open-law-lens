from __future__ import annotations

import unittest
from unittest.mock import patch

from open_law_lens.app import OpenLawLensApp, OpenLawLensWindow, build_case_reader_payload
from open_law_lens.citation_links import CitedCaseLink
from open_law_lens.config import AppConfig
from open_law_lens.library import DisplayText, PageMarker


class AppReaderPayloadTests(unittest.TestCase):
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

    def test_reader_and_agent_citation_links_use_shared_lookup_path(self) -> None:
        class DummyWindow:
            def __init__(self) -> None:
                self.opened: list[str] = []

            def _start_lookup(self, citation: str) -> None:
                self.opened.append(citation)

            def _open_citation_lookup_link(self, link: CitedCaseLink) -> None:
                OpenLawLensWindow._open_citation_lookup_link(self, link)  # type: ignore[arg-type]

        window = DummyWindow()
        link = CitedCaseLink(start_offset=0, end_offset=25, lookup_text="11 Cal.5th 614")

        OpenLawLensWindow._open_cited_case_link(window, link)  # type: ignore[arg-type]
        OpenLawLensWindow._open_agent_cited_case_link(window, link)  # type: ignore[arg-type]

        self.assertEqual(window.opened, ["11 Cal.5th 614", "11 Cal.5th 614"])

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


if __name__ == "__main__":
    unittest.main()
