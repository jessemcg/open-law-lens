from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.case_suggestions import (
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    matching_case_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from open_law_lens.library import CaseLibrary


class CaseSuggestionTests(unittest.TestCase):
    def test_load_concordance_skips_slip_and_placeholder_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Concordance_File.sdi"
            path.write_text(
                "\n".join(
                    [
                        "In re John M.;In re John M. (2006) 141 Cal.App.4th 1564;Cases",
                        "In re John M. supra;In re John M. (2006) 141 Cal. App. 4th 1564;Cases",
                        "In re Recent;In re Recent, slip opn. S123456;Cases",
                        "In re Pending;In re Pending (2026) ___ Cal.App.5th ___;Cases",
                        "In re Unofficial;In re Unofficial (1990) 795 P.2d 1244;Cases",
                        "Some Statute;Welf. & Inst. Code, section 300;Statutes",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            suggestions = load_concordance_case_suggestions(path)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].label, "In re John M. (2006) 141 Cal.App.4th 1564")
        self.assertEqual(suggestions[0].lookup_text, "141 Cal.App.4th 1564")
        self.assertEqual(suggestions[0].source, "Concordance")

    def test_matches_case_names_and_reporter_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Concordance_File.sdi"
            path.write_text(
                "In re Malinda S.;In re Malinda S. (1990) 51 Cal.3d 368;Cases\n",
                encoding="utf-8",
            )
            suggestions = load_concordance_case_suggestions(path)

        self.assertEqual(matching_case_suggestions("malinda", suggestions)[0].display_name, "In re Malinda S.")
        self.assertEqual(matching_case_suggestions("51 Cal 3d", suggestions)[0].lookup_text, "51 Cal.3d 368")
        self.assertEqual(resolve_case_lookup_text("In re Malinda S.", suggestions), "51 Cal.3d 368")
        self.assertEqual(resolve_case_lookup_text("In re Malinda S. (1990) 51 Cal.3d 368", suggestions), "51 Cal.3d 368")

    def test_ambiguous_case_name_does_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Concordance_File.sdi"
            path.write_text(
                "\n".join(
                    [
                        "In re A.;In re A. (2001) 1 Cal.App.4th 100;Cases",
                        "In re A.;In re A. (2002) 2 Cal.App.4th 200;Cases",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            suggestions = load_concordance_case_suggestions(path)

        self.assertIsNone(resolve_case_lookup_text("In re A.", suggestions))

    def test_library_cases_become_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 123,
                    "case_name": "Example v. State",
                    "date_filed": "2024-02-01",
                    "citations": [
                        {"volume": "10", "reporter": "Cal.App.5th", "page": "25"},
                    ],
                }
            )
            library.upsert_opinion(
                {
                    "id": 10,
                    "cluster_id": 123,
                    "plain_text": "[*25]Example begins.\n\n[*26]Example continues.",
                }
            )
            library.update_case_opinion_ids("123", ["10"])

            suggestions = case_suggestions_from_library(library)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].display_name, "Example v. State")
        self.assertEqual(suggestions[0].label, "Example v. State (2024) 10 Cal.App.5th 25")
        self.assertEqual(suggestions[0].lookup_text, "10 Cal.App.5th 25")
        self.assertEqual(suggestions[0].cluster_id, "123")
        self.assertEqual(resolve_case_lookup_text("Example v. State", suggestions), "10 Cal.App.5th 25")

    def test_library_cases_skip_unofficial_reporter_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 123,
                    "case_name": "Example v. State",
                    "date_filed": "2024-02-01",
                    "citations": [
                        {"volume": "795", "reporter": "P.2d", "page": "1244"},
                    ],
                }
            )

            suggestions = case_suggestions_from_library(library)

        self.assertEqual(suggestions, [])

    def test_merge_dedupes_concordance_and_library_official_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "Concordance_File.sdi"
            path.write_text(
                "In re Malinda S.;In re Malinda S. (1990) 51 Cal. 3d 368;Cases\n",
                encoding="utf-8",
            )
            concordance = load_concordance_case_suggestions(path)
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 123,
                    "case_name": "In Re Malinda S.",
                    "case_name_short": "In Re Malinda S.",
                    "date_filed": "1990-08-30",
                    "citations": [
                        {"volume": "51", "reporter": "Cal.3d", "page": "368"},
                    ],
                }
            )
            library.upsert_opinion(
                {
                    "id": 10,
                    "cluster_id": 123,
                    "plain_text": "[*368]The case begins.\n\n[*369]The case continues.",
                }
            )
            library.update_case_opinion_ids("123", ["10"])
            library_suggestions = case_suggestions_from_library(library)

            suggestions = merge_case_suggestions(concordance, library_suggestions)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].label, "In re Malinda S. (1990) 51 Cal.3d 368")
        self.assertEqual(suggestions[0].lookup_text, "51 Cal.3d 368")


if __name__ == "__main__":
    unittest.main()
