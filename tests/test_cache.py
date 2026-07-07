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


B_D_TEXT = """110 Cal.App.5th 1132 (2025)

B.D., Petitioner,

v.

THE SUPERIOR COURT OF CONTRA COSTA COUNTY, Respondent;

No. A172485.

OPINION
"""


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

    def test_write_lookup_canonicalizes_cluster_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [
                                {"volume": 1, "reporter": "Cal.", "page": "2"},
                                {"volume": "99", "reporter": "P.3d", "page": "100"},
                            ],
                        }
                    ],
                }
            ]
            cache.write_lookup("1 Cal. 2", lookup)

            self.assertEqual(
                cache.read_lookup("1 Cal. 2"),
                [
                    {
                        "status": 200,
                        "clusters": [
                            {
                                "id": 42,
                                "case_name": "Example v. State",
                                "official_citation": "1 Cal. 2",
                                "citations": [{"volume": "1", "reporter": "Cal.", "page": "2"}],
                            }
                        ],
                    }
                ],
            )

    def test_upsert_cluster_writes_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
            }
            self.assertEqual(cache.upsert_cluster(cluster), "42")
            self.assertEqual(
                cache.read_cached_cluster("42"),
                {
                    **cluster,
                    "official_citation": "1 Cal. 2",
                    "citations": [{"volume": "1", "reporter": "Cal.", "page": "2"}],
                },
            )
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

    def test_reupsert_preserves_added_at_and_updates_loaded_order(self) -> None:
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
                        "loaded_at": "2026-06-01T12:00:00+00:00",
                        "last_accessed": "2026-06-01T12:00:00+00:00",
                    },
                    "2": {
                        "cluster_id": "2",
                        "title": "Second v. State",
                        "citation_text": "2 Cal. 2",
                        "added_at": "2026-06-02T12:00:00+00:00",
                        "loaded_at": "2026-06-02T12:00:00+00:00",
                        "last_accessed": "2026-06-02T12:00:00+00:00",
                    },
                }
            )

            with patch("open_law_lens.cache._utc_now", return_value="2026-06-03T12:00:00+00:00"):
                cache.upsert_cluster({"id": 1, "case_name": "First v. State"})

            entries = cache.list_case_entries()
            self.assertEqual([entry["cluster_id"] for entry in entries], ["1", "2"])
            self.assertEqual(entries[0]["added_at"], "2026-06-01T12:00:00+00:00")
            self.assertEqual(entries[0]["loaded_at"], "2026-06-03T12:00:00+00:00")
            self.assertEqual(entries[0]["last_accessed"], "2026-06-03T12:00:00+00:00")

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

    def test_agent_answer_cache_round_trip_selection_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            answer_id = cache.save_agent_answer(
                "The removal issue is strong.",
                mode="appeal",
            )

            self.assertTrue(answer_id)
            self.assertEqual(cache.list_agent_answer_entries()[0]["answer_id"], answer_id)
            self.assertEqual(cache.read_agent_answer(answer_id)["text"], "The removal issue is strong.")
            self.assertFalse(cache.is_agent_answer_selected(answer_id))

            cache.set_agent_answer_selected(answer_id, True)

            self.assertTrue(cache.is_agent_answer_selected(answer_id))
            self.assertEqual(cache.selected_agent_answer_entries()[0]["answer_id"], answer_id)
            self.assertTrue(cache.remove_agent_answer(answer_id))
            self.assertEqual(cache.list_agent_answer_entries(), [])
            self.assertIsNone(cache.read_agent_answer(answer_id))

    def test_agent_answer_title_uses_short_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            answer_id = cache.save_agent_answer(
                "The governing law helps mother. Section 361 required clear and convincing evidence.",
                mode="appeal",
            )

            entry = cache.list_agent_answer_entries()[0]

        self.assertEqual(entry["answer_id"], answer_id)
        self.assertEqual(entry["title"], "The governing law helps mother")
        self.assertNotIn("Section 361", entry["title"])

    def test_repair_reporter_only_imported_case_name_updates_cache_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cluster = {
                "id": "external-110",
                "case_name": "110 Cal.App.5th 1132",
                "case_name_short": "110 Cal.App.5th 1132",
                "case_name_full": "110 Cal.App.5th 1132",
                "official_citation": "110 Cal.App.5th 1132",
                "citations": [{"volume": "110", "reporter": "Cal.App.5th", "page": "1132"}],
                "source_type": "user_imported_external_case",
            }
            opinion = {
                "id": "official-import-external-110",
                "cluster_id": "external-110",
                "plain_text": B_D_TEXT,
                "source_type": "user_imported_official_text",
            }
            cache.upsert_cluster(cluster)
            cache.write_resource("opinions", "official-import-external-110", opinion)
            cache.update_case_opinions(cluster, ["official-import-external-110"])
            cache.set_agent_selected("external-110", True)
            cache.write_lookup("110 Cal.App.5th 1132", [{"status": 200, "clusters": [cluster]}])

            self.assertEqual(cache.repair_reporter_only_imported_case_names(), 1)

            repaired = cache.read_cached_cluster("external-110")
            assert repaired is not None
            self.assertEqual(repaired["case_name"], "B.D. v. Superior Court")
            entry = cache.list_case_entries()[0]
            self.assertEqual(entry["title"], "B.D. v. Superior Court")
            self.assertEqual(entry["opinion_ids"], ["official-import-external-110"])
            self.assertTrue(cache.is_agent_selected("external-110"))
            lookup = cache.read_lookup("110 Cal.App.5th 1132")
            self.assertEqual(lookup[0]["clusters"][0]["case_name"], "B.D. v. Superior Court")

    def test_statute_cache_round_trip_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            statute = {
                "statute_id": "WIC:300",
                "law_code": "WIC",
                "section": "300",
                "title": "Welfare and Institutions Code section 300",
                "citation": "Welf. & Inst. Code, § 300",
                "text": "300. A child comes within jurisdiction.",
            }

            self.assertEqual(cache.upsert_statute(statute), "WIC:300")
            cache.set_statute_agent_selected("WIC:300", True)

            self.assertEqual(cache.read_cached_statute("WIC:300"), statute)
            self.assertTrue(cache.is_statute_agent_selected("WIC:300"))
            self.assertEqual(cache.selected_statute_entries()[0]["statute_id"], "WIC:300")

    def test_statute_reupsert_preserves_added_at_and_updates_loaded_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            first = {
                "statute_id": "WIC:300",
                "law_code": "WIC",
                "section": "300",
                "title": "Welfare and Institutions Code section 300",
                "citation": "Welf. & Inst. Code, § 300",
            }
            second = {
                "statute_id": "WIC:301",
                "law_code": "WIC",
                "section": "301",
                "title": "Welfare and Institutions Code section 301",
                "citation": "Welf. & Inst. Code, § 301",
            }

            with patch(
                "open_law_lens.cache._utc_now",
                side_effect=[
                    "2026-06-01T12:00:00+00:00",
                    "2026-06-02T12:00:00+00:00",
                    "2026-06-03T12:00:00+00:00",
                ],
            ):
                cache.upsert_statute(first)
                cache.upsert_statute(second)
                cache.upsert_statute(first)

            entries = cache.list_statute_entries()
            self.assertEqual([entry["statute_id"] for entry in entries], ["WIC:300", "WIC:301"])
            self.assertEqual(entries[0]["added_at"], "2026-06-01T12:00:00+00:00")
            self.assertEqual(entries[0]["loaded_at"], "2026-06-03T12:00:00+00:00")
            loaded_at = entries[0]["loaded_at"]
            cache.set_statute_agent_selected("WIC:300", True)
            self.assertEqual(cache.read_statute_index()["WIC:300"]["loaded_at"], loaded_at)

    def test_rule_cache_round_trip_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            rule = {
                "rule_id": "CRC:8.11",
                "rule_number": "8.11",
                "rule_slug": "8_11",
                "title_slug": "eight",
                "title": "California Rules of Court, rule 8.11",
                "citation": "Cal. Rules of Court, rule 8.11",
                "text": "Rule 8.11. Scope.",
            }

            self.assertEqual(cache.upsert_rule(rule), "CRC:8.11")
            cache.set_rule_agent_selected("CRC:8.11", True)

            self.assertEqual(cache.read_cached_rule("CRC:8.11"), rule)
            self.assertTrue(cache.is_rule_agent_selected("CRC:8.11"))
            self.assertEqual(cache.selected_rule_entries()[0]["rule_id"], "CRC:8.11")

    def test_rule_reupsert_preserves_added_at_and_updates_loaded_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            first = {
                "rule_id": "CRC:8.11",
                "rule_number": "8.11",
                "title": "California Rules of Court, rule 8.11",
                "citation": "Cal. Rules of Court, rule 8.11",
            }
            second = {
                "rule_id": "CRC:8.12",
                "rule_number": "8.12",
                "title": "California Rules of Court, rule 8.12",
                "citation": "Cal. Rules of Court, rule 8.12",
            }

            with patch(
                "open_law_lens.cache._utc_now",
                side_effect=[
                    "2026-06-01T12:00:00+00:00",
                    "2026-06-02T12:00:00+00:00",
                    "2026-06-03T12:00:00+00:00",
                ],
            ):
                cache.upsert_rule(first)
                cache.upsert_rule(second)
                cache.upsert_rule(first)

            entries = cache.list_rule_entries()
            self.assertEqual([entry["rule_id"] for entry in entries], ["CRC:8.11", "CRC:8.12"])
            self.assertEqual(entries[0]["added_at"], "2026-06-01T12:00:00+00:00")
            self.assertEqual(entries[0]["loaded_at"], "2026-06-03T12:00:00+00:00")
            loaded_at = entries[0]["loaded_at"]
            cache.set_rule_agent_selected("CRC:8.11", True)
            self.assertEqual(cache.read_rule_index()["CRC:8.11"]["loaded_at"], loaded_at)

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

    def test_detach_for_clear_moves_resources_and_preserves_unrelated_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = JsonCache(root)
            cache.write_lookup("576 U.S. 644", [{"status": 200}])
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            cache.write_resource("opinions", "10", {"id": 10})
            cache.upsert_rule(
                {
                    "rule_id": "CRC:8.11",
                    "rule_number": "8.11",
                    "title": "California Rules of Court, rule 8.11",
                    "citation": "Cal. Rules of Court, rule 8.11",
                }
            )
            cache.save_agent_answer("The cached answer.")
            agent_workspace = root / "agent-workspaces" / "workspace.test"
            agent_workspace.mkdir(parents=True)
            (agent_workspace / "manifest.json").write_text("{}", encoding="utf-8")

            trash_path = cache.detach_for_clear()

            self.assertIsNotNone(trash_path)
            assert trash_path is not None
            self.assertTrue(trash_path.is_dir())
            self.assertTrue((trash_path / "lookups").is_dir())
            self.assertTrue((trash_path / "clusters" / "42.json").is_file())
            self.assertTrue((trash_path / "opinions" / "10.json").is_file())
            self.assertFalse((trash_path / "statutes").exists())
            self.assertTrue((trash_path / "rules" / "CRC_8.11.json").is_file())
            self.assertTrue((trash_path / "agent_answers").is_dir())
            self.assertTrue((trash_path / "cases_index.json").is_file())
            self.assertTrue((trash_path / "rules_index.json").is_file())
            self.assertTrue((trash_path / "agent_answers_index.json").is_file())
            self.assertEqual(cache.list_lookups(), [])
            self.assertEqual(cache.list_case_entries(), [])
            self.assertEqual(cache.list_agent_answer_entries(), [])
            self.assertFalse(cache.selected_case_entries())
            self.assertTrue((root / "lookups").is_dir())
            self.assertTrue((root / "clusters").is_dir())
            self.assertTrue((root / "opinions").is_dir())
            self.assertTrue((root / "rules").is_dir())
            self.assertTrue((root / "agent_answers").is_dir())
            self.assertTrue((agent_workspace / "manifest.json").is_file())

    def test_clear_removes_resources_and_recreates_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = JsonCache(root)
            cache.write_lookup("576 U.S. 644", [{"status": 200}])
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            cache.write_resource("opinions", "10", {"id": 10})
            answer_id = cache.save_agent_answer("The answer to save.")
            cache.clear()
            self.assertEqual(cache.list_lookups(), [])
            self.assertEqual(cache.list_case_entries(), [])
            self.assertEqual(cache.list_agent_answer_entries(), [])
            self.assertIsNone(cache.read_agent_answer(answer_id))
            self.assertFalse(cache.selected_case_entries())
            self.assertTrue((root / "lookups").is_dir())
            self.assertTrue((root / "clusters").is_dir())
            self.assertTrue((root / "opinions").is_dir())
            self.assertTrue((root / "agent_answers").is_dir())
            self.assertEqual(list(root.glob(".clear-trash-*")), [])


if __name__ == "__main__":
    unittest.main()
