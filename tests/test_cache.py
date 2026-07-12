from __future__ import annotations

import os
import tempfile
import threading
import time
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
from open_law_lens.reader_highlights import ReaderHighlight


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

    def test_malformed_json_is_treated_as_cache_miss(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            path = cache.lookup_path("576 U.S. 644")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")

            self.assertIsNone(cache.read_lookup("576 U.S. 644"))

    def test_write_json_replaces_atomically_without_temp_leftover(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            path = Path(temp_dir) / "metadata.json"

            cache.write_json(path, {"ok": True})

            self.assertEqual(cache.read_json(path), {"ok": True})
            self.assertEqual(list(Path(temp_dir).glob(".metadata.json.*.tmp")), [])

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

    def test_upsert_preferred_cluster_replaces_active_official_citation_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            older = {
                "id": 2282485,
                "case_name": "In Re Janet T.",
                "citations": [
                    {"volume": "93", "reporter": "Cal.App.4th", "page": "377"}
                ],
            }
            preferred = {
                "id": 5808769,
                "case_name": (
                    "Los Angeles County Department of Children & Family Services v. Tricia T."
                ),
                "case_name_full": (
                    "In re JANET T., Persons Coming Under the Juvenile Court Law."
                ),
                "citations": [
                    {"volume": "93", "reporter": "Cal.App.4th", "page": "377"}
                ],
            }
            unrelated = {
                "id": 99,
                "case_name": "Unrelated v. State",
                "citations": [
                    {"volume": "10", "reporter": "Cal.App.5th", "page": "25"}
                ],
            }
            cache.upsert_cluster(older)
            cache.upsert_cluster(unrelated)
            cache.set_agent_selected("2282485", True)
            cache.set_reader_position("case", "2282485", 120)
            cache.set_active_research_set(7, "Example", dirty=False)

            preferred_id = cache.upsert_preferred_cluster(preferred)

            self.assertEqual(preferred_id, "5808769")
            entries = {entry["cluster_id"]: entry for entry in cache.list_case_entries()}
            self.assertEqual(set(entries), {"5808769", "99"})
            self.assertTrue(entries["5808769"]["agent_selected"])
            self.assertIsNotNone(cache.read_cached_cluster("2282485"))
            self.assertEqual(cache.reader_position("case", "2282485"), 120)
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertTrue(metadata["dirty"])

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

    def test_upsert_and_selection_updates_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cluster = {"id": 42, "case_name": "Example v. State"}
            cache.upsert_cluster(cluster)
            original_read_case_index = cache.read_case_index
            upsert_read_started = threading.Event()

            def delayed_read_case_index() -> dict[str, dict[str, object]]:
                upsert_read_started.set()
                time.sleep(0.05)
                return original_read_case_index()

            def reupsert() -> None:
                with patch.object(cache, "read_case_index", delayed_read_case_index):
                    cache.upsert_cluster(cluster)

            thread = threading.Thread(target=reupsert)
            thread.start()
            self.assertTrue(upsert_read_started.wait(1))
            cache.set_agent_selected("42", True)
            thread.join(1)

            self.assertTrue(cache.is_agent_selected("42"))

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

    def test_agent_answer_title_strips_markdown_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            answer_id = cache.save_agent_answer(
                "**Assessment**\n\nThe governing law helps mother.",
                mode="appeal",
            )

            entry = cache.list_agent_answer_entries()[0]

        self.assertEqual(entry["answer_id"], answer_id)
        self.assertEqual(entry["title"], "Assessment")

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

    def test_active_research_set_metadata_marks_dirty_on_visible_cache_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_active_research_set(7, "Example_research")

            self.assertFalse(cache.active_research_set_metadata()["dirty"])

            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["active_research_set_id"], 7)
            self.assertEqual(metadata["active_research_set_name"], "Example_research")
            self.assertTrue(metadata["dirty"])

    def test_reader_positions_round_trip_without_dirtying_research_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_active_research_set(7, "Example_research")

            cache.set_reader_position("case", "42", 1234)
            cache.set_reader_position("rule", "CRC:8.11", 88)
            cache.set_reader_position("socf", "B123456_Test", 321)

            self.assertEqual(cache.reader_position("case", "42"), 1234)
            self.assertEqual(cache.reader_position("rule", "CRC:8.11"), 88)
            self.assertEqual(cache.reader_position("socf", "B123456_Test"), 321)
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertFalse(metadata["dirty"])
            self.assertEqual(
                list(Path(temp_dir).glob(".reader_positions.json.*.tmp")),
                [],
            )

    def test_current_case_context_selection_is_per_case_and_survives_cache_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))

            self.assertFalse(cache.is_current_case_context_selected("B123456_First"))
            cache.set_current_case_context_selected("B123456_First", True)
            cache.set_current_case_context_selected("B234567_Second", True)

            self.assertTrue(cache.is_current_case_context_selected("B123456_First"))
            self.assertTrue(cache.is_current_case_context_selected("B234567_Second"))
            cache.set_current_case_context_selected("B123456_First", False)
            self.assertFalse(cache.is_current_case_context_selected("B123456_First"))
            self.assertTrue(cache.is_current_case_context_selected("B234567_Second"))

            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            trash_path = cache.detach_for_clear()

            self.assertIsNotNone(trash_path)
            self.assertTrue(cache.is_current_case_context_selected("B234567_Second"))

    def test_current_case_context_selection_ignores_malformed_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.current_case_context_path().write_text("not json", encoding="utf-8")

            self.assertEqual(cache.selected_current_case_contexts(), set())

    def test_reader_positions_ignore_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_json(
                cache.reader_positions_path(),
                {
                    "version": 1,
                    "positions": {
                        "case": {"valid": 12, "negative": -1, "boolean": True},
                        "unknown": {"value": 9},
                    },
                },
            )

            self.assertEqual(cache.read_reader_positions(), {"case": {"valid": 12}})

    def test_reader_highlights_round_trip_without_dirtying_research_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_active_research_set(7, "Example_research")
            highlight = ReaderHighlight(4, 9, "alpha", "pre", "post")

            cache.set_reader_highlights("case", "42", [highlight])

            self.assertEqual(cache.reader_highlights("case", "42"), [highlight])
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertFalse(metadata["dirty"])
            self.assertEqual(
                list(Path(temp_dir).glob(".reader_highlights.json.*.tmp")),
                [],
            )

    def test_reader_highlights_ignore_invalid_entries_and_unknown_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_json(
                cache.reader_highlights_path(),
                {
                    "version": 1,
                    "highlights": {
                        "case": {
                            "42": [
                                {"start_offset": 0, "end_offset": 5, "text": "Alpha"},
                                {"start_offset": -1, "end_offset": 5, "text": "bad"},
                            ]
                        },
                        "agent_answer": {
                            "answer": [
                                {"start_offset": 0, "end_offset": 4, "text": "Nope"}
                            ]
                        },
                    },
                },
            )

            self.assertEqual(
                cache.reader_highlights("case", "42"),
                [ReaderHighlight(0, 5, "Alpha")],
            )
            self.assertEqual(cache.reader_highlights("agent_answer", "answer"), [])

    def test_removing_cache_item_removes_reader_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            cache.set_reader_position("case", "42", 1234)
            cache.set_reader_highlights(
                "case",
                "42",
                [ReaderHighlight(0, 5, "Alpha")],
            )

            self.assertTrue(cache.remove_case("42"))

            self.assertIsNone(cache.reader_position("case", "42"))
            self.assertEqual(cache.reader_highlights("case", "42"), [])

    def test_removing_statute_and_rule_removes_their_highlights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.upsert_statute({"statute_id": "WIC:300", "text": "Alpha"})
            cache.upsert_rule({"rule_id": "CRC:8.11", "text": "Beta"})
            cache.set_reader_highlights(
                "statute",
                "WIC:300",
                [ReaderHighlight(0, 5, "Alpha")],
            )
            cache.set_reader_highlights(
                "rule",
                "CRC:8.11",
                [ReaderHighlight(0, 4, "Beta")],
            )

            self.assertTrue(cache.remove_statute("WIC:300"))
            self.assertTrue(cache.remove_rule("CRC:8.11"))

            self.assertEqual(cache.reader_highlights("statute", "WIC:300"), [])
            self.assertEqual(cache.reader_highlights("rule", "CRC:8.11"), [])

    def test_dirty_tracking_can_be_suppressed_for_clean_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_active_research_set(7, "Example_research")

            with cache.suppress_dirty_tracking():
                cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertFalse(metadata["dirty"])

    def test_slip_opinion_payload_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            payload = {
                "case_number": "A173218",
                "source_url": "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                "display": {"text": "Slip text.", "page_markers": []},
            }

            cache.write_slip_opinion_payload("A173218", payload)

            self.assertEqual(cache.read_slip_opinion_payload("A173218"), payload)

    def test_slip_opinion_hydration_can_leave_active_set_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_active_research_set(7, "Example_research")
            payload = {
                "case_number": "A173218",
                "display": {"text": "Slip text.", "page_markers": []},
            }

            cache.write_slip_opinion_payload("A173218", payload, mark_dirty=False)

            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertFalse(metadata["dirty"])
            self.assertEqual(cache.read_slip_opinion_payload("A173218"), payload)

    def test_detach_for_clear_moves_resources_and_preserves_unrelated_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = JsonCache(root)
            cache.set_active_research_set(7, "Example_research")
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
            cache.set_reader_position("case", "42", 1234)
            cache.set_reader_highlights(
                "case",
                "42",
                [ReaderHighlight(0, 5, "Alpha")],
            )
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
            self.assertTrue((trash_path / "metadata.json").is_file())
            self.assertTrue((trash_path / "reader_positions.json").is_file())
            self.assertTrue((trash_path / "reader_highlights.json").is_file())
            self.assertEqual(cache.list_lookups(), [])
            self.assertEqual(cache.list_case_entries(), [])
            self.assertEqual(cache.list_agent_answer_entries(), [])
            self.assertIsNone(cache.active_research_set_metadata())
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
            cache.set_active_research_set(7, "Example_research")
            cache.set_reader_position("case", "42", 1234)
            cache.set_reader_highlights(
                "case",
                "42",
                [ReaderHighlight(0, 5, "Alpha")],
            )
            cache.clear()
            self.assertEqual(cache.list_lookups(), [])
            self.assertEqual(cache.list_case_entries(), [])
            self.assertEqual(cache.list_agent_answer_entries(), [])
            self.assertIsNone(cache.active_research_set_metadata())
            self.assertIsNone(cache.reader_position("case", "42"))
            self.assertEqual(cache.reader_highlights("case", "42"), [])
            self.assertIsNone(cache.read_agent_answer(answer_id))
            self.assertFalse(cache.selected_case_entries())
            self.assertTrue((root / "lookups").is_dir())
            self.assertTrue((root / "clusters").is_dir())
            self.assertTrue((root / "opinions").is_dir())
            self.assertTrue((root / "agent_answers").is_dir())
            self.assertEqual(list(root.glob(".clear-trash-*")), [])

    def test_clear_can_preserve_reader_state_for_research_set_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.set_reader_position("case", "42", 1234)
            highlight = ReaderHighlight(0, 5, "Alpha")
            cache.set_reader_highlights("case", "42", [highlight])
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            cache.clear(
                preserve_reader_positions=True,
                preserve_reader_highlights=True,
            )

            self.assertEqual(cache.reader_position("case", "42"), 1234)
            self.assertEqual(cache.reader_highlights("case", "42"), [highlight])
            self.assertEqual(cache.list_case_entries(), [])


if __name__ == "__main__":
    unittest.main()
