from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from open_law_lens.authority_resolver import (
    detect_authority_candidates,
    extract_case,
    extract_case_by_cluster_id,
    first_authority_candidate,
)
from open_law_lens.authority_passages import build_authority_passages
from open_law_lens.library import CaseLibrary


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


SH_OPINION_TEXT = "\n\n".join(
    [
        "82 Cal.App.5th 166 (2022)",
        "In re S.H., a Person Coming Under the Juvenile Court Law.",
        "[*170] Reasoning on page 170 continues here.",
        "[*171] Reasoning on page 171 continues here.",
        "[*172] As In re I.F. explained, the presumption applies here.",
    ]
)
SH_SOURCE_URL = "https://scholar.google.com/scholar_case?case=863c24eb9e52f74a"


class DurableReconciliationTests(unittest.TestCase):
    """extract-case --cluster-id reuses a validated durable official copy.

    The uncited CourtListener cluster 7856391-style request reconciles against
    the imported, officially paginated In re S.H. library case by exact
    canonical title plus filing year; the requested CourtListener ID stays in
    ``resolved_input`` while ``identifier`` names the durable case.
    """

    DURABLE_ID = "external-863c24eb9e52f74a"
    SH_SOURCE_URL = "https://scholar.google.com/scholar_case?case=863c24eb9e52f74a"

    def _client(self, temp_dir: str) -> MagicMock:
        client = MagicMock()
        library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
        library.ensure()
        client.library = library
        client.last_resource_source = "CourtListener API"
        client.last_opinion_source = ""
        client.fetch_url.return_value = {
            "id": 7856391,
            "case_name": "In re S.H., a Person Coming Under the Juvenile Court Law.",
            "date_filed": "2022-05-31",
            "citations": [],
        }
        return client

    @staticmethod
    def _store_durable_sh(library: CaseLibrary, *, cluster_source_url: str = "") -> None:
        cluster = {
            "id": "external-863c24eb9e52f74a",
            "case_name": "In re S.H.",
            "case_name_short": "In re S.H.",
            "case_name_full": "In re S.H.",
            "date_filed": "2022",
            "official_citation": "82 Cal.App.5th 166",
            "citations": [
                {"volume": "82", "reporter": "Cal.App.5th", "page": "166"}
            ],
            "source_url": cluster_source_url or SH_SOURCE_URL,
        }
        library.upsert_cluster(dict(cluster))
        library.upsert_opinion(
            {
                "id": "official-import-external-sh-1",
                "cluster_id": "external-863c24eb9e52f74a",
                "plain_text": SH_OPINION_TEXT,
                "source_url": cluster_source_url or SH_SOURCE_URL,
            },
            cluster=dict(cluster),
        )

    def test_cluster_id_returns_durable_sh_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self._client(temp_dir)
            self._store_durable_sh(client.library)

            result = extract_case_by_cluster_id("7856391", client=client)

            self.assertTrue(result.ok)
            self.assertEqual(result.source, "Library")
            self.assertEqual(result.title, "In re S.H.")
            self.assertEqual(result.citation, "82 Cal.App.5th 166")
            # The requested CourtListener ID stays auditable while the durable
            # case identity is selected.
            self.assertEqual(result.resolved_input, "7856391")
            self.assertEqual(result.identifier, self.DURABLE_ID)
            self.assertEqual(result.source_url, self.SH_SOURCE_URL)
            self.assertTrue(result.official_pagination)
            self.assertEqual(result.pagination_marker_count, 3)
            self.assertTrue(result.ok)
            self.assertEqual(result.text, SH_OPINION_TEXT)
            self.assertFalse(
                any("Scholar recovery" in warning for warning in result.warnings)
            )

    def test_requested_and_durable_ids_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self._client(temp_dir)
            self._store_durable_sh(client.library)

            result = extract_case_by_cluster_id("7856391", client=client)

            self.assertEqual(result.resolved_input, "7856391")
            self.assertNotEqual(result.resolved_input, result.identifier)
            self.assertNotIn("7856391", result.identifier)

    def test_refresh_bypasses_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self._client(temp_dir)
            self._store_durable_sh(client.library)
            client.fetch_cluster_opinions.return_value = []
            client.last_opinion_source = ""
            client.reader_opinions.side_effect = lambda opinions: opinions
            display = MagicMock()
            display.text = "Fresh CourtListener text"
            display.page_markers = []
            client.opinion_display.return_value = display

            result = extract_case_by_cluster_id("7856391", client=client, refresh=True)

            # The requested CourtListener identity is kept; the durable case is
            # not consulted.
            self.assertEqual(result.identifier, "7856391")
            self.assertNotEqual(result.source, "Library")

    def test_no_durable_match_keeps_courtlistener_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self._client(temp_dir)
            # A stored case with a different title never reconciles.
            other = dict(_durable_cluster_dict())
            other["id"] = "external-othercase0001"
            other["case_name"] = "In re Other Case"
            other["case_name_short"] = "In re Other Case"
            other["case_name_full"] = "In re Other Case"
            client.library.upsert_cluster(dict(other))
            client.library.upsert_opinion(
                {
                    "id": "op-other-1",
                    "cluster_id": "external-othercase0001",
                    "plain_text": SH_OPINION_TEXT,
                    "source_url": self.SH_SOURCE_URL,
                },
                cluster=dict(other),
            )
            client.fetch_cluster_opinions.return_value = []
            client.reader_opinions.side_effect = lambda opinions: opinions
            client.opinion_display.side_effect = lambda opinion: _display_for(opinion)
            client.fetch_cluster_slip_opinion.side_effect = RuntimeError("none")

            result = extract_case_by_cluster_id("7856391", client=client)

            self.assertEqual(result.identifier, "7856391")
            self.assertEqual(result.source, "CourtListener API")
            self.assertFalse(result.official_pagination)
            self.assertTrue(
                any(
                    "Google Scholar" in warning
                    for warning in result.warnings
                )
            )

    def test_durable_result_passes_through_find_formatting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = self._client(temp_dir)
            self._store_durable_sh(client.library)

            result = extract_case_by_cluster_id("7856391", client=client)
            payload = build_authority_passages(result, ["In re I.F."])

            self.assertNotIn("text", payload)
            self.assertEqual(payload["match_count"], 1)
            self.assertEqual(payload["citation"], "82 Cal.App.5th 166")
            self.assertIn("In re I.F.", payload["passages"][0]["text"])


def _durable_cluster_dict() -> dict[str, object]:
    return {
        "id": "external-863c24eb9e52f74a",
        "case_name": "In re S.H.",
        "case_name_short": "In re S.H.",
        "case_name_full": "In re S.H.",
        "date_filed": "2022",
        "official_citation": "82 Cal.App.5th 166",
        "citations": [{"volume": "82", "reporter": "Cal.App.5th", "page": "166"}],
        "source_url": SH_SOURCE_URL,
    }


def _display_for(opinion: dict[str, object]) -> Any:
    from open_law_lens.library import opinion_display_text

    return opinion_display_text({"plain_text": str(opinion.get("plain_text") or "")})


if __name__ == "__main__":
    unittest.main()
