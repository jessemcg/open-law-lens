from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.client import (
    CourtListenerClient,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
    html_to_text,
    normalize_case_title,
    official_california_reporter_citation,
    opinion_text,
)
from open_law_lens.library import CaseLibrary


class ClientTests(unittest.TestCase):
    def test_html_to_text_keeps_paragraph_breaks(self) -> None:
        self.assertEqual(html_to_text("<p>First</p><p>Second <b>line</b></p>"), "First\n\nSecond line")

    def test_opinion_text_prefers_html_with_citations(self) -> None:
        opinion = {
            "html_with_citations": "<p>Preferred</p>",
            "plain_text": "Fallback",
        }
        self.assertEqual(opinion_text(opinion), "Preferred")

    def test_cluster_title_and_citation_line(self) -> None:
        cluster = {
            "case_name": "Obergefell v. Hodges",
            "citations": [{"volume": 576, "reporter": "U.S.", "page": "644"}],
        }
        self.assertEqual(cluster_title(cluster), "Obergefell v. Hodges")
        self.assertEqual(cluster_citation_line(cluster), "576 U.S. 644")

    def test_cluster_short_title_prefers_case_name_short(self) -> None:
        cluster = {
            "case_name": "Los Angeles County Department of Children & Family Services v. Elizabeth D.",
            "case_name_short": "In re Emily D.",
        }

        self.assertEqual(cluster_short_title(cluster), "In re Emily D.")

    def test_case_title_normalizes_leading_in_re_only(self) -> None:
        self.assertEqual(normalize_case_title(" In Re Emily D. "), "In re Emily D.")
        self.assertEqual(normalize_case_title("IN RE Malinda S."), "In re Malinda S.")
        self.assertEqual(normalize_case_title("People v. In Re Holdings"), "People v. In Re Holdings")

    def test_cluster_title_normalizes_in_re_casing(self) -> None:
        cluster = {"case_name": "In Re Emily D.", "case_name_short": "In Re Emily D."}

        self.assertEqual(cluster_title(cluster), "In re Emily D.")
        self.assertEqual(cluster_short_title(cluster), "In re Emily D.")

    def test_cluster_short_title_falls_back_to_case_name(self) -> None:
        cluster = {"case_name": "Example v. State"}

        self.assertEqual(cluster_short_title(cluster), "Example v. State")

    def test_official_california_reporter_citation_prefers_official_reporter(self) -> None:
        cluster = {
            "citations": [
                {"volume": "795", "reporter": "P.2d", "page": "1244"},
                {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                {"volume": "272", "reporter": "Cal. Rptr.", "page": "787"},
            ],
        }

        self.assertEqual(official_california_reporter_citation(cluster), "51 Cal. 3d 368")

    def test_official_california_reporter_citation_supports_newer_appellate_reporters(self) -> None:
        for reporter in ("Cal. 4th", "Cal. 5th", "Cal.App.4th", "Cal.App.5th"):
            with self.subTest(reporter=reporter):
                cluster = {"citations": [{"volume": "1", "reporter": reporter, "page": "2"}]}
                self.assertEqual(official_california_reporter_citation(cluster), f"1 {reporter} 2")

    def test_official_california_reporter_citation_returns_empty_for_unofficial_reporter(self) -> None:
        cluster = {"citations": [{"volume": "1", "reporter": "Cal. Rptr.", "page": "2"}]}

        self.assertEqual(official_california_reporter_citation(cluster), "")

    def test_format_official_california_citation_italicizes_case_name_in_html(self) -> None:
        cluster = {
            "case_name": "Smith & Jones v. State",
            "date_filed": "2024-02-03",
            "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "2"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "Smith & Jones v. State (2024) 1 Cal. 5th 2")
        self.assertEqual(citation.html_text, "<i>Smith &amp; Jones v. State</i> (2024) 1 Cal. 5th 2")

    def test_format_official_california_citation_uses_short_name(self) -> None:
        cluster = {
            "case_name": "Los Angeles County Department of Children & Family Services v. Elizabeth D.",
            "case_name_short": "In Re Emily D.",
            "date_filed": "2015-02-17",
            "citations": [{"volume": "234", "reporter": "Cal. App. 4th", "page": "438"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Emily D. (2015) 234 Cal. App. 4th 438")
        self.assertEqual(official_california_reporter_citation(cluster), "234 Cal. App. 4th 438")

    def test_dedupe_case_clusters_prefers_cleaner_official_citation_match(self) -> None:
        duplicate_with_lexis = {
            "id": 5607930,
            "case_name": "San Diego County Department of Social Services v. Rusell S.",
            "case_name_short": "",
            "citation_count": 1,
            "citations": [
                {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                {"volume": "1990", "reporter": "Cal. LEXIS", "page": "4024"},
            ],
        }
        canonical = {
            "id": 2606148,
            "case_name": "In Re Malinda S.",
            "case_name_short": "In Re Malinda S.",
            "citation_count": 210,
            "citations": [{"volume": "51", "reporter": "Cal. 3d", "page": "368"}],
        }

        self.assertEqual(dedupe_case_clusters([duplicate_with_lexis, canonical]), [canonical])
        self.assertEqual(cluster_short_title(dedupe_case_clusters([duplicate_with_lexis, canonical])[0]), "In re Malinda S.")

    def test_dedupe_case_clusters_keeps_different_official_citations(self) -> None:
        clusters = [
            {
                "id": 1,
                "case_name_short": "First",
                "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "1"}],
            },
            {
                "id": 2,
                "case_name_short": "Second",
                "citations": [{"volume": "2", "reporter": "Cal. 5th", "page": "1"}],
            },
        ]

        self.assertEqual(dedupe_case_clusters(clusters), clusters)

    def test_dedupe_case_clusters_keeps_clusters_without_official_citations(self) -> None:
        clusters = [
            {"id": 1, "case_name_short": "First", "citations": [{"volume": "1", "reporter": "P.2d", "page": "1"}]},
            {"id": 2, "case_name_short": "Second", "citations": [{"volume": "1", "reporter": "P.2d", "page": "1"}]},
        ]

        self.assertEqual(dedupe_case_clusters(clusters), clusters)

    def test_format_official_california_citation_omits_missing_year(self) -> None:
        cluster = {
            "case_name": "Example v. State",
            "citations": [{"volume": "1", "reporter": "Cal.App.5th", "page": "2"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "Example v. State 1 Cal.App.5th 2")

    def test_lookup_uses_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cached_lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                        }
                    ],
                }
            ]
            cache.write_lookup("576 U.S. 644", cached_lookup)
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            self.assertEqual(client.lookup_citation("576   U.S. 644"), cached_lookup)
            self.assertEqual(client.last_lookup_source, "Research Cache")
            self.assertEqual(client.cached_clusters()[0]["case_name"], "Example v. State")

    def test_cached_clusters_hides_existing_duplicate_official_citation_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 5607930,
                    "case_name": "San Diego County Department of Social Services v. Rusell S.",
                    "case_name_short": "",
                    "citation_count": 1,
                    "citations": [
                        {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                        {"volume": "1990", "reporter": "Cal. LEXIS", "page": "4024"},
                    ],
                }
            )
            cache.upsert_cluster(
                {
                    "id": 2606148,
                    "case_name": "In Re Malinda S.",
                    "case_name_short": "In Re Malinda S.",
                    "citation_count": 210,
                    "citations": [{"volume": "51", "reporter": "Cal. 3d", "page": "368"}],
                }
            )
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)

            clusters = client.cached_clusters()

            self.assertEqual(len(clusters), 1)
            self.assertEqual(clusters[0]["id"], 2606148)

    def test_fetch_cluster_opinions_updates_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_resource("opinions", "10", {"id": 10, "plain_text": "Opinion text"})
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "sub_opinions": ["/api/rest/v4/opinions/10/"],
            }
            opinions = client.fetch_cluster_opinions(cluster)
            self.assertEqual(opinions, [{"id": 10, "plain_text": "Opinion text"}])
            self.assertEqual(cache.list_case_entries()[0]["opinion_ids"], ["10"])

    def test_lookup_rejects_empty_citation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=JsonCache(Path(temp_dir)), library=library)
            with self.assertRaises(ValueError):
                client.lookup_citation("   ")

    def test_lookup_uses_library_without_json_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                        }
                    ],
                }
            ]
            library.upsert_lookup("1 Cal. 2", lookup)
            client = CourtListenerClient(cache=cache, library=library)

            self.assertEqual(client.lookup_citation("1 Cal. 2"), lookup)
            self.assertEqual(client.last_lookup_source, "Library")
            self.assertEqual(client.cached_clusters()[0]["case_name"], "Example v. State")

    def test_clear_cache_hides_research_cache_and_preserves_library_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 42,
                    "case_name": "Example v. State",
                    "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                }
            )
            cache.upsert_cluster(
                {
                    "id": 42,
                    "case_name": "Example v. State",
                    "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                }
            )
            client = CourtListenerClient(cache=cache, library=library)

            cache.clear()

            self.assertEqual(client.cached_clusters(), [])
            self.assertEqual(library.saved_clusters()[0]["case_name"], "Example v. State")


if __name__ == "__main__":
    unittest.main()
