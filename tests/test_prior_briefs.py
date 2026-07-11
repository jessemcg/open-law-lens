from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from open_law_lens.prior_briefs import (
    PriorBriefError,
    PriorBriefLibrary,
    brief_id_for_relative_path,
    document_date_from_text,
    document_type_from_name,
)


class PriorBriefLibraryTests(unittest.TestCase):
    def test_document_date_prefers_last_valid_dated_line(self) -> None:
        text = "Dated: January 2, 2025 By: /s/ Jesse\n\nDated: 03/04/2026 By: /s/ Jesse"

        self.assertEqual(document_date_from_text(text), date(2026, 3, 4))

    def test_document_type_and_stable_id_from_name(self) -> None:
        self.assertEqual(
            document_type_from_name("B353817_AOB_Joseph_A"),
            "Appellant's opening brief",
        )
        self.assertEqual(
            brief_id_for_relative_path("Folder/Example.odt"),
            brief_id_for_relative_path("folder\\example.odt"),
        )

    def test_sync_search_update_remove_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "briefs"
            source_dir.mkdir()
            first = source_dir / "B353817_AOB_Joseph_A.odt"
            second = source_dir / "E088444_PhoenixHMemo_Alejandra_M.odt"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            texts = {
                first.name: (
                    "The juvenile court abused its discretion because the Cal-ICWA "
                    "inquiry was inadequate.\n\nDated: 07/09/2026 By: /s/ Jesse"
                ),
                second.name: "No arguable issue.\n\nDated: 06/24/2026 By: /s/ Jesse",
            }
            library = PriorBriefLibrary(source_dir, root / "library.sqlite3")
            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_text",
                side_effect=lambda path: texts[path.name],
            ):
                result = library.sync()

            self.assertEqual((result.total, result.added, result.errors), (2, 2, ()))
            matches = library.search("abused discretion")
            self.assertEqual([match.title for match in matches], [first.stem])
            self.assertEqual(library.search("inquiry", sort="newest")[0].document_date, "2026-07-09")

            first.write_bytes(b"first changed")
            texts[first.name] += "\nAdditional argument."
            second.unlink()
            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_text",
                side_effect=lambda path: texts[path.name],
            ):
                result = library.sync()

            self.assertEqual((result.updated, result.removed, result.unchanged), (1, 1, 0))
            self.assertEqual(library.count(), 1)
            backup = library.backup(root / "snapshot" / "briefs.sqlite3")
            snapshot = PriorBriefLibrary(source_dir, backup)
            self.assertEqual(snapshot.count(), 1)

    def test_sync_keeps_last_good_row_after_extraction_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "briefs"
            source_dir.mkdir()
            brief = source_dir / "B353817_AOB_Joseph_A.odt"
            brief.write_bytes(b"one")
            library = PriorBriefLibrary(source_dir, root / "library.sqlite3")
            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_text",
                return_value="First text.\nDated: 07/09/2026 By: /s/ Jesse",
            ):
                library.sync()
            brief.write_bytes(b"two")

            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_text",
                side_effect=PriorBriefError("broken"),
            ):
                result = library.sync()

            self.assertEqual(result.errors, ("broken",))
            self.assertEqual(library.count(), 1)


if __name__ == "__main__":
    unittest.main()
