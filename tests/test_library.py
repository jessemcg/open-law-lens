from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary, opinion_display_text


class LibraryTests(unittest.TestCase):
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

    def test_upsert_lookup_preserves_raw_lookup_json(self) -> None:
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
                            "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                        }
                    ],
                }
            ]

            library.upsert_lookup("1 Cal. 2", lookup)

            self.assertEqual(library.read_lookup("1   Cal. 2"), lookup)

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


if __name__ == "__main__":
    unittest.main()
