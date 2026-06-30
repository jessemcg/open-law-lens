from __future__ import annotations

import unittest

from open_law_lens.app import OpenLawLensWindow, build_case_reader_payload
from open_law_lens.citation_links import CitedCaseLink
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


if __name__ == "__main__":
    unittest.main()
