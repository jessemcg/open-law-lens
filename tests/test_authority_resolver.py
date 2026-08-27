from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_law_lens.authority_resolver import (
    detect_authority_candidates,
    extract_case,
    extract_case_by_cluster_id,
    first_authority_candidate,
)


class AuthorityResolverTests(unittest.TestCase):
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

        with patch("open_law_lens.authority_resolver._case_suggestions", return_value=[]):
            result = extract_case("123 Cal.App.5th 456", client=client)

        client.lookup_citation.assert_called_once_with("123 Cal.App.5th 456", refresh=False)
        self.assertFalse(result.ok)
        self.assertTrue(any("Google Scholar recovery is next" in w for w in result.warnings))

    def test_no_cluster_reports_no_baseline_and_browser_recovery_next(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with patch("open_law_lens.authority_resolver._case_suggestions", return_value=[]):
            result = extract_case("In re Example", client=client)

        self.assertFalse(result.ok)
        self.assertEqual(result.text, "")
        self.assertTrue(any("Google Scholar recovery is next" in w for w in result.warnings))
        self.assertTrue(result.error)
        # Neither Tavily nor a direct HTTP Scholar search may be reached.
        client.library.upsert_cluster.assert_not_called()
        client.cache.upsert_cluster.assert_not_called()

    def test_ambiguous_case_suggestion_falls_through_to_direct_lookup(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with (
            patch("open_law_lens.authority_resolver.resolve_case_lookup_text", return_value=None),
            patch("open_law_lens.authority_resolver._case_suggestions", return_value=[object(), object()]),
        ):
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
                    "id": 5810948,
                    "case_name": "Moss v. Moss",
                    "case_name_short": "Moss",
                    "case_name_full": (
                        "Estate of ROBERT CLINTON MOSS, SR., BARRY D. MOSS, "
                        "Contestant and v. LORRAINE BERGERON MOSS, as etc., and"
                    ),
                    "date_filed": "2012-03-20",
                    "citations": [
                        {"volume": "204", "reporter": "Cal.App.4th", "page": "521"}
                    ],
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

        result = extract_case_by_cluster_id(
            "5810948",
            client=client,  # type: ignore[arg-type]
        )

        self.assertEqual(client.fetch_urls, ["/api/rest/v4/clusters/5810948/"])
        self.assertEqual(result.source, "Library")
        self.assertEqual(result.title, "Estate of Moss")
        self.assertEqual(result.citation, "Estate of Moss (2012) 204 Cal.App.4th 521")


if __name__ == "__main__":
    unittest.main()
