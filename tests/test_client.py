from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.client import CourtListenerClient, cluster_citation_line, cluster_title, html_to_text, opinion_text


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
            client = CourtListenerClient(cache=cache)
            self.assertEqual(client.lookup_citation("576   U.S. 644"), cached_lookup)
            self.assertEqual(client.cached_clusters()[0]["case_name"], "Example v. State")

    def test_fetch_cluster_opinions_updates_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_resource("opinions", "10", {"id": 10, "plain_text": "Opinion text"})
            client = CourtListenerClient(cache=cache)
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
            client = CourtListenerClient(cache=JsonCache(Path(temp_dir)))
            with self.assertRaises(ValueError):
                client.lookup_citation("   ")


if __name__ == "__main__":
    unittest.main()
