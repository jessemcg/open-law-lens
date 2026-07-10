from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_law_lens.authority_resolver import (
    _extract_case_from_scholar,
    detect_authority_candidates,
    extract_case,
    extract_case_by_cluster_id,
    first_authority_candidate,
)
from open_law_lens.scholar_search import ScholarSearchResult
from open_law_lens.web_import import ExtractedWebpage


class AuthorityResolverTests(unittest.TestCase):
    def test_scholar_fallback_rejects_mismatched_official_citation_before_writes(self) -> None:
        client = MagicMock()
        with (
            patch(
                "open_law_lens.authority_resolver.search_first_case_direct",
                return_value=ScholarSearchResult("https://example.test/wrong", "People v. Carter"),
            ),
            patch(
                "open_law_lens.authority_resolver.extract_webpage_text",
                return_value=ExtractedWebpage(
                    "https://example.test/wrong",
                    "People v. Carter",
                    "97 Cal.App.5th 960 (2023)\nPeople v. Carter.",
                ),
            ),
        ):
            result = _extract_case_from_scholar("117 Cal.App.5th 379", client=client)

        self.assertFalse(result.ok)
        self.assertIn("did not match", result.error)
        client.library.upsert_cluster.assert_not_called()
        client.cache.upsert_cluster.assert_not_called()

    def test_detects_first_authority_by_text_position(self) -> None:
        candidates = detect_authority_candidates(
            "See 13 Cal.4th 952 and Welf. & Inst. Code, § 300."
        )

        self.assertEqual(candidates[0].authority_type, "case")
        self.assertEqual(candidates[0].text, "13 Cal.4th 952")

    def test_whole_input_statute_precedes_case_fallback(self) -> None:
        candidate = first_authority_candidate("Welf. & Inst. Code, § 300")

        self.assertEqual(candidate.authority_type, "statute")

    def test_case_not_in_concordance_still_uses_direct_lookup(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with (
            patch("open_law_lens.authority_resolver._case_suggestions", return_value=[]),
            patch("open_law_lens.authority_resolver._extract_case_from_scholar") as scholar,
        ):
            scholar.return_value.ok = False
            scholar.return_value.input = ""
            scholar.return_value.warnings = []
            result = extract_case("123 Cal.App.5th 456", client=client)

        client.lookup_citation.assert_called_once_with("123 Cal.App.5th 456", refresh=False)
        self.assertFalse(result.ok)

    def test_ambiguous_case_suggestion_falls_through_to_direct_lookup(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with (
            patch("open_law_lens.authority_resolver.resolve_case_lookup_text", return_value=None),
            patch("open_law_lens.authority_resolver._case_suggestions", return_value=[object(), object()]),
            patch("open_law_lens.authority_resolver._extract_case_from_scholar") as scholar,
        ):
            scholar.return_value.ok = False
            scholar.return_value.input = ""
            scholar.return_value.warnings = []
            extract_case("In re Example", client=client)

        client.lookup_citation.assert_called_once_with("In re Example", refresh=False)

    def test_extract_case_by_cluster_id_reports_library_source(self) -> None:
        class DummyClient:
            def __init__(self) -> None:
                self.last_resource_source = ""
                self.last_opinion_source = ""
                self.fetch_urls: list[str] = []

            def fetch_url(self, url: str, *, kind: str, refresh: bool = False) -> dict[str, object]:
                self.fetch_urls.append(url)
                self.last_resource_source = "Library"
                return {
                    "id": 42,
                    "case_name": "In re Example",
                    "case_name_short": "In re Example",
                    "citations": [{"volume": "1", "reporter": "Cal.App.5th", "page": "2"}],
                    "sub_opinions": ["/api/rest/v4/opinions/10/"],
                }

            def fetch_cluster_opinions(self, cluster, *, refresh=False):  # type: ignore[no-untyped-def]
                self.last_opinion_source = "Library"
                return [{"id": 10, "plain_text": "[*2]Opinion text."}]

            def reader_opinions(self, opinions):  # type: ignore[no-untyped-def]
                return opinions

            def opinion_display(self, opinion):  # type: ignore[no-untyped-def]
                display = MagicMock()
                display.text = opinion["plain_text"]
                display.page_markers = []
                return display

        client = DummyClient()

        result = extract_case_by_cluster_id("42", client=client)  # type: ignore[arg-type]

        self.assertEqual(client.fetch_urls, ["/api/rest/v4/clusters/42/"])
        self.assertEqual(result.source, "Library")
        self.assertEqual(result.title, "In re Example")


if __name__ == "__main__":
    unittest.main()
