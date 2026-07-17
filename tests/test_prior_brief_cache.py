from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary


def _brief_payload() -> dict[str, object]:
    return {
        "brief_id": "a" * 64,
        "relative_path": "B353817_AOB_Joseph_A.odt",
        "source_path": "/archive/B353817_AOB_Joseph_A.odt",
        "title": "B353817_AOB_Joseph_A",
        "case_number": "B353817",
        "document_type": "Appellant's opening brief",
        "document_date": "2026-07-09",
        "date_source": "document_signature",
        "text": "The juvenile court abused its discretion.",
        "sha256": "b" * 64,
        "file_size": 123,
        "file_mtime_ns": 456,
        "indexed_at": "2026-07-11T00:00:00+00:00",
        "heading_spans": [
            {"level": 1, "start_offset": 0, "end_offset": 12},
        ],
    }


class PriorBriefCacheTests(unittest.TestCase):
    def test_prior_brief_requires_explicit_upsert_and_can_be_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            self.assertEqual(cache.list_prior_brief_entries(), [])

            brief_id = cache.upsert_prior_brief(_brief_payload())
            cache.set_prior_brief_agent_selected(brief_id, True)

            self.assertEqual(brief_id, "a" * 64)
            self.assertEqual(len(cache.selected_prior_brief_entries()), 1)
            self.assertEqual(cache.read_prior_brief(brief_id)["text"], _brief_payload()["text"])

    def test_metadata_refresh_can_avoid_dirtying_active_research_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            with patch.object(cache, "mark_active_research_set_dirty") as mark_dirty:
                brief_id = cache.upsert_prior_brief(
                    _brief_payload(),
                    mark_dirty=False,
                )

            self.assertEqual(brief_id, "a" * 64)
            mark_dirty.assert_not_called()
            self.assertEqual(
                cache.read_prior_brief(brief_id)["heading_spans"],
                _brief_payload()["heading_spans"],
            )

    def test_research_set_round_trips_prior_brief_snapshot_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache = JsonCache(root / "cache")
            cache.ensure()
            brief_id = cache.upsert_prior_brief(_brief_payload())
            cache.set_prior_brief_agent_selected(brief_id, True)
            library = CaseLibrary(root / "library.sqlite3")
            library.ensure()

            saved = library.save_research_set("Brief set", cache)
            cache.clear()
            loaded = library.load_research_set_into_cache(saved.set_id, cache)

            self.assertEqual(loaded.prior_brief_count, 1)
            self.assertEqual(cache.read_prior_brief(brief_id)["title"], "B353817_AOB_Joseph_A")
            self.assertEqual(
                cache.read_prior_brief(brief_id)["heading_spans"],
                _brief_payload()["heading_spans"],
            )
            self.assertTrue(cache.is_prior_brief_agent_selected(brief_id))

    def test_clear_cache_preserves_no_external_brief_archive_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            brief_id = cache.upsert_prior_brief(_brief_payload())

            cache.clear()

            self.assertIsNone(cache.read_prior_brief(brief_id))


if __name__ == "__main__":
    unittest.main()
