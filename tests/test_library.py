from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary, opinion_display_text


B_D_TEXT = """110 Cal.App.5th 1132 (2025)

B.D., Petitioner,

v.

THE SUPERIOR COURT OF CONTRA COSTA COUNTY, Respondent;

No. A172485.

OPINION
"""


class LibraryTests(unittest.TestCase):
    def test_ensure_drops_legacy_statute_and_rule_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "library.sqlite3"
            library = CaseLibrary(db_path)
            library.ensure()
            with library.connection() as conn:
                conn.executescript(
                    """
                    CREATE TABLE statutes (statute_id TEXT PRIMARY KEY);
                    CREATE TABLE statute_aliases (normalized_citation TEXT PRIMARY KEY);
                    CREATE TABLE rules (rule_id TEXT PRIMARY KEY);
                    CREATE TABLE rule_aliases (normalized_citation TEXT PRIMARY KEY);
                    INSERT INTO statutes(statute_id) VALUES ('WIC:300');
                    INSERT INTO rules(rule_id) VALUES ('CRC:8.11');
                    """
                )

            library.ensure()

            with library.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table'
                    AND name IN ('statutes', 'statute_aliases', 'rules', 'rule_aliases')
                    """
                ).fetchall()
            self.assertEqual(rows, [])

            library.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            self.assertEqual(library.list_case_entries()[0]["cluster_id"], "42")

    def test_upsert_cluster_and_lookup_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
            }
            library.upsert_cluster(cluster)

            result = library.read_lookup("1 Cal. 2")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0]["clusters"][0]["case_name"], "Example v. State")

    def test_library_case_index_uses_extracted_in_re_initial_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 5607709,
                    "case_name": "Vlasta Z. v. San Bernardino County Welfare Department",
                    "case_name_full": "In re B. G., Persons Coming Under the Juvenile Court Law.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "In re B.G.")

    def test_ensure_refreshes_legacy_case_titles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {
                "id": 42,
                "case_name": (
                    "In re Michael V.. Persons Coming Under the Juvenile Court Law. "
                    "Los Angeles County Department OF Children And Family Services"
                ),
            }
            with library.connection() as conn:
                conn.execute("DELETE FROM meta WHERE key = ?", ("case_titles_normalized_v1",))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cases(
                        cluster_id, title, citation_text, cluster_json, opinion_ids_json, added_at, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "42",
                        "In re Michael V.. Persons Coming Under the Juvenile Court Law.",
                        "",
                        json.dumps(cluster),
                        "[]",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )

            library.ensure()

            self.assertEqual(library.list_case_entries()[0]["title"], "In re Michael V.")

    def test_ensure_repairs_reporter_only_imported_superior_court_writ_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
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
            library.upsert_cluster(cluster)
            library.upsert_opinion(opinion)
            library.update_case_opinion_ids("external-110", ["official-import-external-110"])
            library.upsert_lookup("110 Cal.App.5th 1132", [{"status": 200, "clusters": [cluster]}])
            with library.connection() as conn:
                conn.execute(
                    "DELETE FROM meta WHERE key = ?",
                    ("reporter_only_imported_names_normalized_v1",),
                )

            library.ensure()

            repaired = library.read_cluster("external-110")
            assert repaired is not None
            self.assertEqual(repaired["case_name"], "B.D. v. Superior Court")
            self.assertEqual(library.list_case_entries()[0]["title"], "B.D. v. Superior Court")
            lookup = library.read_lookup("110 Cal.App.5th 1132")
            assert lookup is not None
            self.assertEqual(lookup[0]["clusters"][0]["case_name"], "B.D. v. Superior Court")

    def test_json_cache_case_index_uses_extracted_in_re_initial_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 5608115,
                    "case_name": "Kings County Human Services Agency v. J.C.",
                    "case_name_full": "In re K.C., a Person Coming Under the Juvenile Court Law.",
                    "case_name_short": "J.C.",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re K.C.")

    def test_research_set_saves_whole_cache_and_load_replaces_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 42,
                    "case_name": "Example v. State",
                    "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                }
            )
            cache.write_resource(
                "opinions",
                "10",
                {
                    "id": 10,
                    "cluster_id": 42,
                    "plain_text": "Example opinion text.",
                },
            )
            cache.update_case_opinions({"id": 42, "case_name": "Example v. State"}, ["10"])
            cache.set_agent_selected("42", True)
            cache.upsert_statute(
                {
                    "statute_id": "WIC:300",
                    "law_code": "WIC",
                    "section": "300",
                    "title": "Welfare and Institutions Code section 300",
                    "citation": "Welf. & Inst. Code, § 300",
                    "text": "300. A child comes within jurisdiction.",
                }
            )
            cache.upsert_rule(
                {
                    "rule_id": "CRC:8.11",
                    "rule_number": "8.11",
                    "title": "California Rules of Court, rule 8.11",
                    "citation": "Cal. Rules of Court, rule 8.11",
                    "text": "Rule 8.11. Scope.",
                }
            )
            cache.set_rule_agent_selected("CRC:8.11", True)
            cache.save_agent_answer(
                "This prior assessment should round-trip with the saved Research Set.",
                mode="appeal",
                title="Removal assessment",
            )
            answer_id = cache.list_agent_answer_entries()[0]["answer_id"]
            cache.set_agent_answer_selected(answer_id, True)

            saved = library.save_research_set("Example_research", cache)

            self.assertEqual(saved.name, "Example_research")
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["active_research_set_id"], saved.set_id)
            self.assertEqual(metadata["active_research_set_name"], "Example_research")
            self.assertFalse(metadata["dirty"])
            self.assertEqual(saved.item_count, 4)
            self.assertEqual(saved.case_count, 1)
            self.assertEqual(saved.statute_count, 1)
            self.assertEqual(saved.rule_count, 1)
            self.assertEqual(saved.agent_answer_count, 1)
            self.assertIsNotNone(library.read_opinion("10"))

            cache.clear()
            cache.upsert_cluster({"id": 99, "case_name": "Other v. State"})

            loaded = library.load_research_set_into_cache("Example_research", cache)

            self.assertEqual(loaded.set_id, saved.set_id)
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["active_research_set_id"], saved.set_id)
            self.assertEqual(metadata["active_research_set_name"], "Example_research")
            self.assertFalse(metadata["dirty"])
            self.assertEqual([entry["cluster_id"] for entry in cache.list_case_entries()], ["42"])
            self.assertEqual([entry["statute_id"] for entry in cache.list_statute_entries()], ["WIC:300"])
            self.assertEqual([entry["rule_id"] for entry in cache.list_rule_entries()], ["CRC:8.11"])
            self.assertEqual([entry["answer_id"] for entry in cache.list_agent_answer_entries()], [answer_id])
            self.assertEqual(cache.read_agent_answer(answer_id)["title"], "Removal assessment")
            self.assertTrue(cache.is_agent_selected("42"))
            self.assertTrue(cache.is_rule_agent_selected("CRC:8.11"))
            self.assertTrue(cache.is_agent_answer_selected(answer_id))

    def test_research_set_duplicate_requires_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            first = library.save_research_set("Example_research", cache)
            with self.assertRaises(ValueError):
                library.save_research_set("Example_research", cache)

            cache.upsert_cluster({"id": 43, "case_name": "Second v. State"})
            self.assertTrue(cache.active_research_set_metadata()["dirty"])
            replaced = library.save_research_set("Example_research", cache, replace=True)

            self.assertEqual(replaced.set_id, first.set_id)
            self.assertEqual(replaced.case_count, 2)
            self.assertFalse(cache.active_research_set_metadata()["dirty"])

    def test_matching_research_set_for_cache_attaches_exact_leftover_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            saved = library.save_research_set("Example_research", cache)
            cache.clear_active_research_set()

            matched = library.matching_research_set_for_cache(cache)

            self.assertIsNotNone(matched)
            assert matched is not None
            self.assertEqual(matched.set_id, saved.set_id)
            metadata = cache.active_research_set_metadata()
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata["active_research_set_id"], saved.set_id)
            self.assertFalse(metadata["dirty"])

    def test_matching_research_set_for_cache_ignores_partial_leftover_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})
            library.save_research_set("Example_research", cache)
            cache.clear_active_research_set()
            cache.upsert_cluster({"id": 43, "case_name": "Second v. State"})

            self.assertIsNone(library.matching_research_set_for_cache(cache))
            self.assertIsNone(cache.active_research_set_metadata())

    def test_research_set_round_trips_cached_slip_opinion_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 42,
                    "case_name_short": "In re L.G.",
                    "precedential_status": "Published",
                    "date_filed": "2026-03-06",
                    "docket": {"docket_number": "A173218"},
                }
            )
            slip_payload = {
                "case_number": "A173218",
                "source_url": "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
                "date_filed": "2026-03-06",
                "display": {
                    "text": "[Slip opn. p. 1]\nSlip text.",
                    "source_field": "slip_pdf",
                    "page_markers": [
                        {
                            "page_label": "1",
                            "marker_text": "[Slip opn. p. 1]",
                            "start_offset": 0,
                            "end_offset": 16,
                            "source_field": "slip_pdf",
                        }
                    ],
                },
            }
            cache.write_slip_opinion_payload("A173218", slip_payload)

            saved = library.save_research_set("Example_research", cache)
            cache.clear()
            library.load_research_set_into_cache(saved.set_id, cache)

            self.assertEqual(cache.read_slip_opinion_payload("A173218"), slip_payload)

    def test_research_sets_survive_cache_clear_and_can_be_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()
            cache = JsonCache(root / "cache")
            cache.upsert_cluster({"id": 42, "case_name": "Example v. State"})

            saved = library.save_research_set("Example_research", cache)
            cache.clear()

            self.assertEqual(library.list_research_sets()[0].set_id, saved.set_id)
            self.assertTrue(library.delete_research_set(saved.set_id))
            self.assertEqual(library.list_research_sets(), [])

    def test_library_case_index_uses_extracted_adoption_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 2607287,
                    "case_name": "Steven A. v. Rickie M.",
                    "case_name_full": (
                        "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                        "v. RICKIE M., Objector and Respondent."
                    ),
                    "case_name_short": "Kelsey S.",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "Adoption of Kelsey S.")

    def test_json_cache_case_index_uses_extracted_adoption_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 2607287,
                    "case_name": "Steven A. v. Rickie M.",
                    "case_name_full": (
                        "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                        "v. RICKIE M., Objector and Respondent."
                    ),
                    "case_name_short": "Kelsey S.",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "Adoption of Kelsey S.")

    def test_library_case_index_normalizes_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_stale_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_resource(
                "clusters",
                "6239044",
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                },
            )
            cache.write_case_index(
                {
                    "6239044": {
                        "cluster_id": "6239044",
                        "title": "In re Jesse Barber on Habeas Corpus.",
                        "citation_text": "15 Cal. App. 5th 368",
                    }
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_stale_title_from_cluster_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_resource(
                "clusters",
                "2802799",
                {
                    "id": 2802799,
                    "case_name_full": "In Re D.P., a Person Coming Under the Juvenile Court Law.",
                    "case_name_short": "In re D.P. CA6",
                },
            )
            cache.write_case_index(
                {
                    "2802799": {
                        "cluster_id": "2802799",
                        "title": "In re D.P. CA6",
                        "citation_text": "237 Cal. App. 4th 911",
                    }
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re D.P.")

    def test_upsert_lookup_canonicalizes_cluster_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
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
            expected = [
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
            ]

            library.upsert_lookup("1 Cal. 2", lookup)

            self.assertEqual(library.read_lookup("1   Cal. 2"), expected)
            self.assertIsNone(library.read_lookup("99 P.3d 100"))

    def test_upsert_lookup_does_not_store_nonofficial_lookup_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [
                                {"volume": "1", "reporter": "Cal.", "page": "2"},
                                {"volume": "99", "reporter": "P.3d", "page": "100"},
                            ],
                        }
                    ],
                }
            ]

            library.upsert_lookup("99 P.3d 100", lookup)

            self.assertIsNone(library.read_lookup("99 P.3d 100"))
            self.assertIsNotNone(library.read_lookup("1 Cal. 2"))

    def test_ensure_normalizes_legacy_clusters_to_official_citation_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            polluted = {
                "id": 42,
                "case_name": "In re Caden C.",
                "official_citation": "11 Cal.5th 614",
                "citations": [
                    {"volume": "11", "reporter": "Cal.5th", "page": "614"},
                    {"volume": "34", "reporter": "Cal.App.5th", "page": "87"},
                ],
            }
            with library.connection() as conn:
                conn.execute("DELETE FROM meta WHERE key = ?", ("official_citation_only_normalized_v2",))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO cases(
                        cluster_id, title, citation_text, cluster_json, opinion_ids_json, added_at, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "42",
                        "In re Caden C.",
                        "11 Cal.5th 614; 34 Cal.App.5th 87",
                        json.dumps(polluted),
                        "[]",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO citation_aliases(normalized_citation, cluster_id, citation_text)
                    VALUES (?, ?, ?)
                    """,
                    ("34 cal.app.5th 87", "42", "34 Cal.App.5th 87"),
                )
                for lookup_key in ("34 cal.app.5th 87", "486 p.3d 1096"):
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO lookup_results(
                            normalized_citation, result_json, added_at, last_accessed
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            lookup_key,
                            json.dumps([{"status": 200, "clusters": [polluted]}]),
                            "2026-01-01T00:00:00+00:00",
                            "2026-01-01T00:00:00+00:00",
                        ),
                    )

            library.ensure()

            cluster = library.read_cluster("42")
            self.assertIsNotNone(cluster)
            assert cluster is not None
            self.assertEqual(cluster["official_citation"], "11 Cal.5th 614")
            self.assertEqual(cluster["citations"], [{"volume": "11", "reporter": "Cal.5th", "page": "614"}])
            self.assertIsNotNone(library.read_lookup("11 Cal.5th 614"))
            self.assertIsNone(library.read_lookup("34 Cal.App.5th 87"))
            self.assertIsNone(library.read_lookup("486 P.3d 1096"))

    def test_official_pagination_audit_identifies_ineligible_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            eligible = {
                "id": 101,
                "case_name": "Eligible Case",
                "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
            }
            ineligible = {
                "id": 102,
                "case_name": "Ineligible Case",
                "citations": [{"volume": "11", "reporter": "Cal.App.5th", "page": "30"}],
            }
            library.upsert_cluster(eligible)
            library.upsert_opinion(
                {"id": 201, "cluster_id": 101, "plain_text": "[*25]Opening.\n\n[*26]Next."},
                cluster=eligible,
            )
            library.upsert_cluster(ineligible)
            library.upsert_opinion(
                {"id": 202, "cluster_id": 102, "plain_text": "No reporter page markers."},
                cluster=ineligible,
            )

            audit = library.official_pagination_audit()

            by_cluster = {candidate.cluster_id: candidate for candidate in audit}
            self.assertTrue(by_cluster["101"].eligible)
            self.assertFalse(by_cluster["102"].eligible)
            self.assertEqual(by_cluster["102"].marker_count, 0)
            self.assertIn("No embedded reporter page markers", by_cluster["102"].reason)

    def test_official_pagination_audit_keeps_combined_opinion_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {
                "id": 1176122,
                "case_name": "People v. Marsden",
                "citations": [{"volume": "2", "reporter": "Cal.3d", "page": "118"}],
            }
            library.upsert_cluster(cluster)
            library.upsert_opinion(
                {
                    "id": 9548598,
                    "cluster_id": 1176122,
                    "type": "040dissent",
                    "ordering_key": 2,
                    "plain_text": "McCOMB, J.\n\nI dissent.",
                },
                cluster=cluster,
            )
            library.upsert_opinion(
                {
                    "id": 1176122,
                    "cluster_id": 1176122,
                    "type": "010combined",
                    "plain_text": "[*118]Caption.\n\n[*120]Majority.\n\n[*134]Dissent.",
                },
                cluster=cluster,
            )
            library.upsert_opinion(
                {
                    "id": 9548597,
                    "cluster_id": 1176122,
                    "type": "020lead",
                    "ordering_key": 1,
                    "plain_text": "[*120]Majority.",
                },
                cluster=cluster,
            )

            result = library.prune_ineligible_official_pagination(create_backup=False)

            self.assertEqual(result.pruned, [])
            self.assertEqual(result.kept_count, 1)
            self.assertEqual(
                library.read_case_opinion_ids("1176122"),
                ["9548598", "1176122", "9548597"],
            )
            self.assertIsNotNone(library.read_opinion("9548598"))
            self.assertIsNotNone(library.read_opinion("1176122"))
            self.assertIsNotNone(library.read_opinion("9548597"))

    def test_prune_ineligible_official_pagination_removes_lookup_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            eligible = {
                "id": 101,
                "case_name": "Eligible Case",
                "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
            }
            ineligible = {
                "id": 102,
                "case_name": "Ineligible Case",
                "citations": [{"volume": "11", "reporter": "Cal.App.5th", "page": "30"}],
            }
            library.upsert_lookup("10 Cal.App.5th 25", [{"status": 200, "clusters": [eligible, ineligible]}])
            library.upsert_lookup("11 Cal.App.5th 30", [{"status": 200, "clusters": [ineligible]}])
            library.upsert_opinion(
                {"id": 201, "cluster_id": 101, "plain_text": "[*25]Opening.\n\n[*26]Next."},
                cluster=eligible,
            )
            library.upsert_opinion(
                {"id": 202, "cluster_id": 102, "plain_text": "No reporter page markers."},
                cluster=ineligible,
            )

            result = library.prune_ineligible_official_pagination(create_backup=False)

            self.assertIsNone(result.backup_path)
            self.assertEqual([candidate.cluster_id for candidate in result.pruned], ["102"])
            self.assertEqual(result.kept_count, 1)
            self.assertIsNotNone(library.read_cluster("101"))
            self.assertIsNotNone(library.read_opinion("201"))
            self.assertIsNone(library.read_cluster("102"))
            self.assertIsNone(library.read_opinion("202"))
            self.assertIsNone(library.read_lookup("11 Cal.App.5th 30"))
            mixed_lookup = library.read_lookup("10 Cal.App.5th 25")
            self.assertIsNotNone(mixed_lookup)
            assert mixed_lookup is not None
            self.assertEqual(
                [cluster["id"] for cluster in mixed_lookup[0]["clusters"]],
                [101],
            )

    def test_prune_ineligible_official_pagination_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            ineligible = {
                "id": 102,
                "case_name": "Ineligible Case",
                "citations": [{"volume": "11", "reporter": "Cal.App.5th", "page": "30"}],
            }
            library.upsert_cluster(ineligible)
            library.upsert_opinion(
                {"id": 202, "cluster_id": 102, "plain_text": "No reporter page markers."},
                cluster=ineligible,
            )

            result = library.prune_ineligible_official_pagination()

            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertTrue(result.backup_path.exists())
            self.assertEqual(result.backup_path.parent, Path(temp_dir))

    def test_opinion_display_text_preserves_explicit_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                '<p id="b368-1">First <page-number label="373">*373</page-number>'
                "Second</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "First [*373]Second")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "373")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*373]")

    def test_opinion_display_text_keeps_pretty_printed_inline_citation_together(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>"
                "jurisdiction is supported by substantial evidence."
                "\n  <em>\n   (In re Alexis E.\n  </em>\n"
                '  (2009) <span class="citation">'
                '<a href="/opinion/2256739/in-re-alexis-e/#451">'
                "171 Cal.App.4th 438, 451</a></span>"
                " [90 Cal.Rptr.3d 44].)"
                "</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "jurisdiction is supported by substantial evidence. "
                "(In re Alexis E. (2009) 171 Cal.App.4th 438, 451 "
                "[90 Cal.Rptr.3d 44].)"
            ),
        )

    def test_opinion_display_text_keeps_pretty_printed_star_pagination_inline(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>serious emotional\n"
                '  <span citation-index="1" class="star-pagination" label="913"> \n'
                "   *913\n"
                "   </span>\n"
                "  damage.</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "serious emotional [*913] damage.")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "913")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*913]")

    def test_opinion_display_text_normalizes_page_word_star_pagination(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": '<p>Text <span class="star-pagination">*Page 1566</span> continues.</p>',
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Text [*1566] continues.")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "1566")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*1566]")

    def test_opinion_display_text_decodes_cp1252_em_dash_control(self) -> None:
        opinion = {"id": 10, "html_with_citations": "<p>Alpha \u0097 beta.</p>"}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha \u2014 beta.")

    def test_plain_opinion_display_text_decodes_cp1252_em_dash_control(self) -> None:
        opinion = {"id": 10, "plain_text": "Alpha \u0097 beta."}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha \u2014 beta.")

    def test_plain_opinion_display_text_collapses_malformed_quote_stacks(self) -> None:
        opinion = {"id": 10, "plain_text": 'Proof "`"disappears"\'" on appeal.'}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, 'Proof "`disappears\'" on appeal.')

    def test_html_opinion_display_text_collapses_malformed_quote_stacks(self) -> None:
        opinion = {"id": 10, "html_with_citations": '<p>Proof "`"disappears"\'" on appeal.</p>'}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, 'Proof "`disappears\'" on appeal.')

    def test_opinion_display_text_translates_markers_after_quote_stack_collapse(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                'Proof "`"disappears"\'" '
                '<page-number label="373">*373</page-number> after.'
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, 'Proof "`disappears\'" [*373] after.')
        self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*373]")

    def test_opinion_display_text_translates_markers_after_nested_wrapper_collapse(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                'The court said "\'must apply "substantial evidence".\'" '
                '<page-number label="997">*997</page-number> after.'
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, 'The court said "must apply `substantial evidence\'." [*997] after.')
        self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*997]")

    def test_plain_opinion_display_text_normalizes_raw_star_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "plain_text": (
                "*513C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under *514Welfare and Institutions Code section 300.\n\n"
                "*323Once the Agency located D.R., it set a special hearing."
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "[*513]C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under [*514]Welfare and Institutions Code section 300.\n\n"
                "[*323]Once the Agency located D.R., it set a special hearing."
            ),
        )
        self.assertEqual(
            [marker.page_label for marker in display.page_markers],
            ["513", "514", "323"],
        )
        for marker in display.page_markers:
            self.assertEqual(display.text[marker.start_offset:marker.end_offset], marker.marker_text)

    def test_opinion_display_text_preserves_bracketed_star_page_markers(self) -> None:
        opinion = {"id": 10, "plain_text": "Alpha [*513] beta *514Gamma."}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha [*513] beta [*514]Gamma.")
        self.assertEqual([marker.page_label for marker in display.page_markers], ["513", "514"])
        for marker in display.page_markers:
            self.assertEqual(display.text[marker.start_offset:marker.end_offset], marker.marker_text)

    def test_html_opinion_display_text_normalizes_untagged_raw_star_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>*513C.T. and D.A. appeal the juvenile court's order.</p>"
                "<p>The Agency filed a petition under *514Welfare and Institutions Code section 300.</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "[*513]C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under [*514]Welfare and Institutions Code section 300."
            ),
        )
        self.assertEqual(
            [marker.page_label for marker in display.page_markers],
            ["513", "514"],
        )

    def test_opinion_display_text_preserves_reporter_header_lines(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                '<div><center><b><span class="citation">51 Cal.3d 368</span> '
                "(1990)</b></center>"
                '<center><b><span class="citation">795 P.2d 1244</span></b></center>'
                '<center><b><span class="citation">272 Cal. Rptr. 787</span></b></center>'
                "<center><h1>In re MALINDA S.<br>v.<br>RUSSELL S.</h1></center></div>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "51 Cal.3d 368 (1990)\n\n"
                "795 P.2d 1244\n\n"
                "272 Cal. Rptr. 787\n\n"
                "In re MALINDA S.\n\n"
                "v.\n\n"
                "RUSSELL S."
            ),
        )

    def test_opinion_display_text_does_not_infer_paragraph_page_ids(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": '<p id="b368-1">First paragraph.</p><p id="b369-2">Second.</p>',
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.page_markers, [])
        self.assertNotIn("[*368]", display.text)

    def test_opinion_storage_keeps_page_marker_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {"id": 42, "case_name": "Example v. State"}
            opinion = {
                "id": 10,
                "cluster_id": 42,
                "html_with_citations": 'Alpha <page-number label="373">*373</page-number> beta.',
            }

            library.upsert_cluster(cluster)
            library.upsert_opinion(opinion, cluster=cluster)
            display = library.read_opinion_display("10")

            self.assertIsNotNone(display)
            assert display is not None
            self.assertEqual(display.text, "Alpha [*373] beta.")
            self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*373]")

    def test_read_opinion_display_collapses_stored_quote_stacks_and_translates_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            stored_text = 'Proof "`"disappears"\'" [*373] after.'
            marker_start = stored_text.index("[*373]")
            with library.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO opinions(
                        opinion_id, cluster_id, opinion_json, display_text, source_field, added_at, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "10",
                        "42",
                        "null",
                        stored_text,
                        "plain_text",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO page_markers(
                        opinion_id, marker_index, page_label, marker_text, start_offset, end_offset, source_field
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("10", 0, "373", "[*373]", marker_start, marker_start + len("[*373]"), "plain_text"),
                )

            display = library.read_opinion_display("10")

            self.assertIsNotNone(display)
            assert display is not None
            self.assertEqual(display.text, 'Proof "`disappears\'" [*373] after.')
            self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*373]")

    def test_read_opinion_display_regenerates_from_stored_opinion_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            opinion = {
                "id": 10,
                "cluster_id": 42,
                "html_with_citations": (
                    '<p>Alpha <span class="star-pagination" label="913"> *913 </span> beta.</p>'
                ),
            }
            with library.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO opinions(
                        opinion_id, cluster_id, opinion_json, display_text, source_field, added_at, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "10",
                        "42",
                        json.dumps(opinion),
                        "stale display text",
                        "html_with_citations",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )

            display = library.read_opinion_display("10")

            self.assertIsNotNone(display)
            assert display is not None
            self.assertEqual(display.text, "Alpha [*913] beta.")
            self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*913]")


if __name__ == "__main__":
    unittest.main()
