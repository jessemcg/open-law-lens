from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.cache import (
    JsonCache,
    PROJECT_CACHE_DIR,
    citation_cache_key,
    cluster_id_from_cluster,
    cache_root,
    normalize_citation,
    resource_id_from_url,
)


class CacheTests(unittest.TestCase):
    def test_normalize_citation_collapses_spaces(self) -> None:
        self.assertEqual(normalize_citation("  576   U.S.   644  "), "576 U.S. 644")

    def test_citation_cache_key_is_case_insensitive(self) -> None:
        self.assertEqual(citation_cache_key("576 U.S. 644"), citation_cache_key("576 u.s. 644"))

    def test_resource_id_from_url(self) -> None:
        self.assertEqual(
            resource_id_from_url("https://www.courtlistener.com/api/rest/v4/opinions/9969234/"),
            "9969234",
        )

    def test_cache_root_defaults_to_project_cache(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cache_root(), PROJECT_CACHE_DIR)

    def test_cluster_id_from_cluster_prefers_id(self) -> None:
        self.assertEqual(cluster_id_from_cluster({"id": 123, "resource_uri": "/clusters/456/"}), "123")

    def test_cluster_id_from_cluster_uses_resource_url(self) -> None:
        self.assertEqual(cluster_id_from_cluster({"resource_uri": "/api/rest/v4/clusters/456/"}), "456")

    def test_json_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_lookup("576 U.S. 644", [{"status": 200}])
            self.assertEqual(cache.read_lookup("576 U.S. 644"), [{"status": 200}])

    def test_upsert_cluster_writes_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
            }
            self.assertEqual(cache.upsert_cluster(cluster), "42")
            self.assertEqual(cache.read_cached_cluster("42"), cluster)
            entries = cache.list_case_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["title"], "Example v. State")
            self.assertEqual(entries[0]["citation_text"], "1 Cal. 2")

    def test_case_entries_sort_newest_added_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_case_index(
                {
                    "1": {
                        "cluster_id": "1",
                        "title": "Zeta v. State",
                        "citation_text": "1 Cal. 1",
                        "added_at": "2026-06-01T12:00:00+00:00",
                    },
                    "2": {
                        "cluster_id": "2",
                        "title": "Alpha v. State",
                        "citation_text": "2 Cal. 2",
                        "added_at": "2026-06-02T12:00:00+00:00",
                    },
                    "3": {
                        "cluster_id": "3",
                        "title": "Missing Date v. State",
                        "citation_text": "3 Cal. 3",
                    },
                }
            )

            self.assertEqual(
                [entry["cluster_id"] for entry in cache.list_case_entries()],
                ["2", "1", "3"],
            )

    def test_case_entries_sort_same_added_time_by_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            added_at = "2026-06-01T12:00:00+00:00"
            cache.write_case_index(
                {
                    "1": {
                        "cluster_id": "1",
                        "title": "Zeta v. State",
                        "citation_text": "1 Cal. 1",
                        "added_at": added_at,
                    },
                    "2": {
                        "cluster_id": "2",
                        "title": "Alpha v. State",
                        "citation_text": "2 Cal. 2",
                        "added_at": added_at,
                    },
                }
            )

            self.assertEqual(
                [entry["cluster_id"] for entry in cache.list_case_entries()],
                ["2", "1"],
            )

    def test_reupsert_preserves_added_at_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_case_index(
                {
                    "1": {
                        "cluster_id": "1",
                        "title": "First v. State",
                        "citation_text": "1 Cal. 1",
                        "added_at": "2026-06-01T12:00:00+00:00",
                        "last_accessed": "2026-06-01T12:00:00+00:00",
                    },
                    "2": {
                        "cluster_id": "2",
                        "title": "Second v. State",
                        "citation_text": "2 Cal. 2",
                        "added_at": "2026-06-02T12:00:00+00:00",
                        "last_accessed": "2026-06-02T12:00:00+00:00",
                    },
                }
            )

            cache.upsert_cluster({"id": 1, "case_name": "First v. State"})

            entries = cache.list_case_entries()
            self.assertEqual([entry["cluster_id"] for entry in entries], ["2", "1"])
            self.assertEqual(entries[1]["added_at"], "2026-06-01T12:00:00+00:00")
            self.assertNotEqual(entries[1]["last_accessed"], entries[1]["added_at"])

    def test_update_case_opinions_merges_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {"id": 42, "case_name": "Example v. State"}
            cache.update_case_opinions(cluster, ["10", "11"])
            cache.update_case_opinions(cluster, ["11", "12"])
            self.assertEqual(cache.list_case_entries()[0]["opinion_ids"], ["10", "11", "12"])

    def test_agent_selected_persists_in_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {"id": 42, "case_name": "Example v. State"}
            cache.upsert_cluster(cluster)
            cache.set_agent_selected("42", True)
            cache.upsert_cluster(cluster)
            self.assertTrue(cache.is_agent_selected("42"))
            self.assertEqual(cache.selected_case_entries()[0]["cluster_id"], "42")

    def test_remove_case_removes_index_cluster_and_unshared_opinions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {"id": 42, "case_name": "Example v. State"}
            cache.update_case_opinions(cluster, ["10", "11"])
            cache.write_resource("opinions", "10", {"id": 10})
            cache.write_resource("opinions", "11", {"id": 11})

            self.assertTrue(cache.remove_case("42"))

            self.assertEqual(cache.list_case_entries(), [])
            self.assertIsNone(cache.read_cached_cluster("42"))
            self.assertFalse(cache.opinion_path("10").exists())
            self.assertFalse(cache.opinion_path("11").exists())

    def test_remove_case_preserves_shared_opinions_and_lookup_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_lookup("1 Cal. 2", [{"status": 200}])
            cache.update_case_opinions({"id": 42, "case_name": "First"}, ["10", "11"])
            cache.update_case_opinions({"id": 43, "case_name": "Second"}, ["11", "12"])
            cache.write_resource("opinions", "10", {"id": 10})
            cache.write_resource("opinions", "11", {"id": 11})
            cache.write_resource("opinions", "12", {"id": 12})

            self.assertTrue(cache.remove_case("42"))

            self.assertEqual([entry["cluster_id"] for entry in cache.list_case_entries()], ["43"])
            self.assertFalse(cache.opinion_path("10").exists())
            self.assertTrue(cache.opinion_path("11").exists())
            self.assertTrue(cache.opinion_path("12").exists())
            self.assertEqual(cache.read_lookup("1 Cal. 2"), [{"status": 200}])

    def test_remove_case_returns_false_for_missing_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))

            self.assertFalse(cache.remove_case("missing"))

    def test_clear_removes_resources_and_recreates_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_lookup("576 U.S. 644", [{"status": 200}])
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            cache.write_resource("opinions", "10", {"id": 10})
            cache.clear()
            self.assertEqual(cache.list_lookups(), [])
            self.assertEqual(cache.list_case_entries(), [])
            self.assertFalse(cache.selected_case_entries())
            self.assertTrue((Path(temp_dir) / "lookups").is_dir())
            self.assertTrue((Path(temp_dir) / "clusters").is_dir())
            self.assertTrue((Path(temp_dir) / "opinions").is_dir())


if __name__ == "__main__":
    unittest.main()
