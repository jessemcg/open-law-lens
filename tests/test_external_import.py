from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.case_suggestions import case_suggestions_from_library
from open_law_lens.external_import import (
    build_external_import_cluster,
    clean_imported_opinion_text,
    external_cluster_id,
    imported_citations_from_text,
    imported_case_name_from_text,
    imported_year_from_text,
    normalize_official_citation,
)
from open_law_lens.library import CaseLibrary, opinion_display_text
from open_law_lens.quality import official_pagination_quality


CADEN_TEXT = """In re Caden C., 486 P. 3d 1096 - Cal: Supreme Court 2021
Jesse
Jesse McGowan
ReadHow cited
11 Cal.5th 614 (2021)
278 Cal.Rptr.3d 872
486 P.3d 1096
In re CADEN C., a Person Coming Under the Juvenile Court Law.

625
*625 OPINION

Text.

626
*626 More text.
"""

DEZI_TEXT = """In re Dezi C., 16 Cal. 5th 1112 - Cal: Supreme Court 2024
Jesse
Jesse McGowan
16 Cal.5th 1112 (2024)
In re DEZI C. et al., Persons Coming Under the Juvenile Court Law.
LOS ANGELES COUNTY DEPARTMENT OF CHILDREN AND FAMILY SERVICES, Plaintiff and Respondent,
v.
ANGELICA A., Defendant and Appellant.
No. S275578.

1120
*1120 OPINION
"""

CLAUDIA_TEXT = """115 Cal.App.5th 76 (2025)

In re CLAUDIA R. et al., Persons Coming Under the Juvenile Court Law.

*80 OPINION

The notice requirement is at the heart of ICWA. (In re Antonio R. (2022) 76 Cal.App.5th 421, 429 [291 Cal.Rptr.3d 520].)
"""


class ExternalImportTests(unittest.TestCase):
    def test_imported_case_name_from_google_scholar_text(self) -> None:
        self.assertEqual(imported_case_name_from_text(CADEN_TEXT), "In re Caden C.")
        self.assertEqual(imported_year_from_text(CADEN_TEXT), "2021")

    def test_clean_imported_opinion_text_removes_google_scholar_account_chrome(self) -> None:
        cleaned = clean_imported_opinion_text(CADEN_TEXT)

        self.assertNotIn("Jesse\n", cleaned)
        self.assertNotIn("Jesse McGowan", cleaned)
        self.assertNotIn("ReadHow cited", cleaned)
        self.assertIn("11 Cal.5th 614 (2021)", cleaned)
        self.assertIn("In re CADEN C.", cleaned)
        self.assertIn("*625 OPINION", cleaned)

    def test_clean_imported_opinion_text_ignores_citation_in_scholar_title_line(self) -> None:
        cleaned = clean_imported_opinion_text(DEZI_TEXT)

        self.assertNotIn("Jesse\n", cleaned)
        self.assertNotIn("Jesse McGowan", cleaned)
        self.assertIn("In re Dezi C., 16 Cal. 5th 1112 - Cal: Supreme Court 2024", cleaned)
        self.assertIn("16 Cal.5th 1112 (2024)", cleaned)
        self.assertIn("In re DEZI C.", cleaned)

    def test_build_external_import_cluster_uses_official_identity(self) -> None:
        cluster = build_external_import_cluster(
            case_name="",
            official_citation="11 Cal. 5th 614",
            imported_text=CADEN_TEXT,
            source_url="https://scholar.google.com/",
        )

        self.assertEqual(cluster["id"], external_cluster_id("11 Cal.5th 614"))
        self.assertEqual(cluster["case_name"], "In re Caden C.")
        self.assertEqual(cluster["case_name_short"], "In re Caden C.")
        self.assertEqual(cluster["date_filed"], "2021")
        self.assertEqual(cluster["official_citation"], "11 Cal.5th 614")
        self.assertEqual(cluster["citations"], [{"volume": "11", "reporter": "Cal.5th", "page": "614"}])

    def test_imported_citations_ignore_body_citations(self) -> None:
        citations = imported_citations_from_text(CLAUDIA_TEXT, "115 Cal.App.5th 76")

        self.assertEqual(citations, [{"volume": "115", "reporter": "Cal.App.5th", "page": "76"}])

    def test_external_import_persists_to_library_cache_and_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            official_citation = normalize_official_citation(CADEN_TEXT)
            cluster = build_external_import_cluster(
                case_name="",
                official_citation=official_citation,
                imported_text=CADEN_TEXT,
            )
            opinion = {
                "id": f"official-import-{cluster['id']}",
                "cluster_id": cluster["id"],
                "plain_text": CADEN_TEXT,
                "source_type": "user_imported_official_text",
            }
            display = opinion_display_text(opinion)

            self.assertTrue(official_pagination_quality(cluster, [display]).eligible)
            self.assertNotIn("Jesse McGowan", display.text)
            self.assertNotIn("ReadHow cited", display.text)

            library.upsert_cluster(cluster)
            library.upsert_opinion(opinion)
            library.update_case_opinion_ids(str(cluster["id"]), [str(opinion["id"])])
            library.upsert_lookup(official_citation, [{"status": 200, "clusters": [cluster]}])
            cache.upsert_cluster(cluster)
            cache.write_resource("opinions", str(opinion["id"]), opinion)
            cache.update_case_opinions(cluster, [str(opinion["id"])])
            cache.write_lookup(official_citation, [{"status": 200, "clusters": [cluster]}])

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re Caden C.")
            self.assertEqual(library.read_lookup("11 Cal.5th 614")[0]["clusters"][0]["case_name"], "In re Caden C.")
            suggestions = case_suggestions_from_library(library)
            self.assertEqual(suggestions[0].label, "In re Caden C. (2021) 11 Cal.5th 614")
            self.assertEqual(suggestions[0].lookup_text, "11 Cal.5th 614")


if __name__ == "__main__":
    unittest.main()
