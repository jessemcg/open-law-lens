from __future__ import annotations

import tempfile
import unittest
import sqlite3
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from open_law_lens.prior_briefs import (
    PriorBrief,
    PriorBriefError,
    PriorBriefExtraction,
    PriorBriefHeading,
    PriorBriefLibrary,
    _decode_marked_plain_text,
    _mark_pandoc_headers,
    _style_only_heading_extraction,
    brief_id_for_relative_path,
    document_date_from_text,
    document_type_from_name,
)


def _extraction(text: str) -> PriorBriefExtraction:
    return PriorBriefExtraction(text=text)


class PriorBriefLibraryTests(unittest.TestCase):
    def test_heading_markers_preserve_duplicate_unicode_heading_offsets(self) -> None:
        document = {
            "blocks": [
                {"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": "Résumé"}]]},
                {
                    "t": "Div",
                    "c": [
                        ["", [], []],
                        [
                            {
                                "t": "Header",
                                "c": [2, ["", [], []], [{"t": "Str", "c": "Résumé"}]],
                            }
                        ],
                    ],
                },
            ]
        }
        levels: list[int] = []
        _mark_pandoc_headers(document, prefix="TEST", levels=levels)

        extraction = _decode_marked_plain_text(
            "TESTS0XRésuméTESTE0X\n\nBody.\n\nTESTS1X Résumé TESTE1X",
            prefix="TEST",
            levels=levels,
            source_name="brief.odt",
            strip_heading_edges=True,
        )

        self.assertEqual(extraction.text, "Résumé\n\nBody.\n\nRésumé")
        self.assertEqual([heading.level for heading in extraction.headings], [1, 2])
        self.assertEqual(
            [
                extraction.text[heading.start_offset:heading.end_offset]
                for heading in extraction.headings
            ],
            ["Résumé", "Résumé"],
        )

    def test_heading_marker_failure_is_not_silently_accepted(self) -> None:
        with self.assertRaises(PriorBriefError):
            _decode_marked_plain_text(
                "TESTS0XHeading without an end marker",
                prefix="TEST",
                levels=[1],
                source_name="brief.odt",
            )

    def test_style_only_odt_heading_fallback(self) -> None:
        content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
 <office:body><office:text>
  <text:p text:style-name="Heading_20_2">INTRODUCTION</text:p>
  <text:p>Body.</text:p>
 </office:text></office:body>
</office:document-content>"""
        styles = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
 xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
 xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0">
 <office:styles>
  <style:style style:name="Heading_20_2" style:display-name="Heading 2"
   style:family="paragraph"/>
 </office:styles>
</office:document-styles>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "brief.odt"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("content.xml", content)
                archive.writestr("styles.xml", styles)
            with patch(
                "open_law_lens.prior_briefs._run_pandoc",
                return_value="TESTS0X INTRODUCTION TESTE0X\n\nBody.",
            ):
                extraction = _style_only_heading_extraction(
                    path,
                    baseline_text="INTRODUCTION\n\nBody.",
                    prefix="TEST",
                )

        self.assertIsNotNone(extraction)
        assert extraction is not None
        self.assertEqual(extraction.headings, (PriorBriefHeading(2, 0, 12),))

    def test_prior_brief_json_round_trip_and_legacy_payload(self) -> None:
        text = "INTRODUCTION\n\nBody."
        brief = PriorBrief.from_json(
            {
                "brief_id": "a" * 64,
                "title": "Example AOB",
                "text": text,
                "heading_spans": [
                    {"level": 1, "start_offset": 0, "end_offset": 12},
                    {"level": 2, "start_offset": 999, "end_offset": 1000},
                ],
            }
        )

        self.assertEqual(
            brief.heading_spans,
            (PriorBriefHeading(1, 0, 12),),
        )
        self.assertEqual(
            PriorBrief.from_json(brief.to_json()).heading_spans,
            brief.heading_spans,
        )
        self.assertEqual(
            PriorBrief.from_json({**brief.to_json(), "heading_spans": None}).heading_spans,
            (),
        )
        compact = brief.to_json(include_text=False)
        self.assertNotIn("heading_spans", compact)
        self.assertEqual(compact["heading_count"], 1)

    def test_schema_v1_migrates_and_sync_persists_heading_spans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "briefs"
            source_dir.mkdir()
            source = source_dir / "B353817_AOB_Joseph_A.odt"
            source.write_bytes(b"brief")
            database = root / "library.sqlite3"
            with sqlite3.connect(database) as conn:
                conn.executescript(
                    """
                    CREATE TABLE briefs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        brief_id TEXT NOT NULL UNIQUE,
                        relative_path TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        case_number TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        document_date TEXT NOT NULL,
                        date_source TEXT NOT NULL,
                        text TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        file_mtime_ns INTEGER NOT NULL,
                        indexed_at TEXT NOT NULL,
                        text_version TEXT NOT NULL DEFAULT ''
                    );
                    """
                )
            library = PriorBriefLibrary(source_dir, database)
            text = "INTRODUCTION\n\nBody.\n\nDated: 07/09/2026 By: /s/ Jesse"
            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_document",
                return_value=PriorBriefExtraction(
                    text,
                    (PriorBriefHeading(1, 0, 12),),
                ),
            ):
                result = library.sync()

            self.assertEqual(result.errors, ())
            stored = library.list_briefs()[0]
            self.assertEqual(stored.heading_spans, (PriorBriefHeading(1, 0, 12),))
            with library.connection() as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(briefs)")}
            self.assertIn("heading_spans_json", columns)

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
                "open_law_lens.prior_briefs.extract_prior_brief_document",
                side_effect=lambda path: _extraction(texts[path.name]),
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
                "open_law_lens.prior_briefs.extract_prior_brief_document",
                side_effect=lambda path: _extraction(texts[path.name]),
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
                "open_law_lens.prior_briefs.extract_prior_brief_document",
                return_value=_extraction(
                    "First text.\nDated: 07/09/2026 By: /s/ Jesse"
                ),
            ):
                library.sync()
            brief.write_bytes(b"two")

            with patch(
                "open_law_lens.prior_briefs.extract_prior_brief_document",
                side_effect=PriorBriefError("broken"),
            ):
                result = library.sync()

            self.assertEqual(result.errors, ("broken",))
            self.assertEqual(library.count(), 1)


if __name__ == "__main__":
    unittest.main()
