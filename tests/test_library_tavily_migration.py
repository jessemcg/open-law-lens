from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from open_law_lens.library import TAVILY_OPINIONS_MIGRATED_KEY, CaseLibrary


def _tavily_opinion(opinion_id: str, cluster_id: str, page: int) -> dict:
    return {
        "id": opinion_id,
        "cluster_id": cluster_id,
        "type": "010combined",
        "plain_text": f"[*{page}] Substantial official opinion text for testing migration." * 30,
        "source_type": "user_imported_official_text",
        "source_provider": "external_web",
        "retrieval_provider": "tavily",
        "retrieval_mode": "direct",
    }


def _courtlistener_cluster() -> dict:
    return {
        "id": "123",
        "case_name": "In re A.",
        "official_citation": "11 Cal.5th 614",
        "citations": [{"volume": "11", "reporter": "Cal.5th", "page": "614"}],
        "source_type": "courtlistener",
    }


def _external_cluster() -> dict:
    return {
        "id": "external-abc",
        "case_name": "External v. Case",
        "official_citation": "22 Cal.App.5th 100",
        "citations": [{"volume": "22", "reporter": "Cal.App.5th", "page": "100"}],
        "source_type": "user_imported_external_case",
    }


def _insert_case(conn, cluster: dict, opinion_ids: list[str]) -> None:
    conn.execute(
        """
        INSERT INTO cases(cluster_id, title, citation_text, cluster_json, opinion_ids_json, added_at, last_accessed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cluster["id"],
            cluster["case_name"],
            cluster["official_citation"],
            json.dumps(cluster),
            json.dumps(opinion_ids),
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )


def _insert_opinion(conn, opinion: dict) -> None:
    conn.execute(
        """
        INSERT INTO opinions(opinion_id, cluster_id, opinion_json, display_text, source_field, added_at, last_accessed)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opinion["id"],
            opinion["cluster_id"],
            json.dumps(opinion),
            opinion["plain_text"],
            "plain_text",
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO page_markers(opinion_id, marker_index, page_label, marker_text, start_offset, end_offset, source_field)
        VALUES (?, 0, '1', '[*1]', 0, 4, 'plain_text')
        """,
        (opinion["id"],),
    )


class TavilyMigrationTests(unittest.TestCase):
    def _library_with_tavily_opinions(self, temp_dir: str) -> CaseLibrary:
        library = CaseLibrary(Path(temp_dir) / "lib.sqlite3")
        library.ensure()

        cl_cluster = _courtlistener_cluster()
        ext_cluster = _external_cluster()
        cl_opinion = _tavily_opinion("opin-cl", cl_cluster["id"], 614)
        ext_opinion = _tavily_opinion("opin-ext", ext_cluster["id"], 100)

        with library.connection() as conn:
            _insert_case(conn, cl_cluster, ["opin-cl"])
            _insert_case(conn, ext_cluster, ["opin-ext"])
            _insert_opinion(conn, cl_opinion)
            _insert_opinion(conn, ext_opinion)
            conn.execute(
                """
                INSERT INTO lookup_results(normalized_citation, result_json, added_at, last_accessed)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "11 cal.5th 614",
                    json.dumps([{"status": 200, "clusters": [cl_cluster, ext_cluster]}]),
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            conn.execute(
                """
                INSERT INTO research_sets(set_id, name, normalized_name, created_at, updated_at, last_accessed)
                VALUES (1, 'Set', 'set', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO research_set_items(set_id, item_type, authority_id, title, citation, payload_json, position, agent_selected, added_at)
                VALUES (1, 'case', 'external-abc', 'External v. Case', '22 Cal.App.5th 100', ?, 0, 0, '2026-01-01T00:00:00+00:00')
                """,
                (json.dumps(ext_cluster),),
            )

        # Reset the migration key so a subsequent ensure() re-runs it.
        with library.connection() as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (TAVILY_OPINIONS_MIGRATED_KEY,))
        return library

    def test_migration_deletes_tavily_opinions_and_empty_external_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = self._library_with_tavily_opinions(temp_dir)
            backups_before = set(Path(temp_dir).glob("lib.backup-*"))

            library.ensure()  # triggers the migration again

            # Tavily opinions and their markers are gone.
            self.assertIsNone(library.read_opinion("opin-cl"))
            self.assertIsNone(library.read_opinion("opin-ext"))

            # The CourtListener-backed cluster is preserved, with its opinion list emptied.
            cl = library.read_cluster("123")
            self.assertIsNotNone(cl)
            cl_ids = library.read_case_opinion_ids("123")
            self.assertEqual(cl_ids, [])

            # The Tavily-only external cluster is fully deleted.
            self.assertIsNone(library.read_cluster("external-abc"))
            entries = {entry["cluster_id"] for entry in library.list_case_entries()}
            self.assertNotIn("external-abc", entries)

            # A research-set item referencing the deleted external case is removed.
            with library.connection() as conn:
                item = conn.execute(
                    "SELECT 1 FROM research_set_items WHERE authority_id = ?", ("external-abc",)
                ).fetchone()
            self.assertIsNone(item)

            # A backup was created.
            backups_after = set(Path(temp_dir).glob("lib.backup-*"))
            self.assertTrue(backups_after - backups_before)

            # Idempotent: a further ensure() makes no additional deletions.
            before = {entry["cluster_id"] for entry in library.list_case_entries()}
            library.ensure()
            after = {entry["cluster_id"] for entry in library.list_case_entries()}
            self.assertEqual(before, after)

    def test_migration_is_noop_when_no_tavily_opinions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "lib.sqlite3")
            library.ensure()
            backups_before = set(Path(temp_dir).glob("lib.backup-*"))
            library.ensure()
            backups_after = set(Path(temp_dir).glob("lib.backup-*"))
            self.assertEqual(backups_before, backups_after)


if __name__ == "__main__":
    unittest.main()
