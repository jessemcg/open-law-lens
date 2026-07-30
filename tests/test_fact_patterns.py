from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from open_law_lens.fact_patterns import (
    FactPatternError,
    export_fact_pattern,
    extract_fact_pattern_document,
    extract_fact_pattern_text,
    extract_odt_text,
    extract_pdf_text,
)


class FactPatternTests(unittest.TestCase):
    def test_extract_odt_text_reads_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "facts.odt"
            xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body>
    <office:text>
      <text:h>Facts</text:h>
      <text:p>First paragraph.</text:p>
      <text:p>Second paragraph.</text:p>
    </office:text>
  </office:body>
</office:document-content>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("content.xml", xml)

            text = extract_odt_text(path)

            self.assertEqual(text, "Facts\n\nFirst paragraph.\n\nSecond paragraph.")

    def test_extract_odt_document_preserves_text_and_heading_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "facts.odt"
            xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:automatic-styles>
    <style:style style:name="P3" style:parent-style-name="Heading_20_3"/>
  </office:automatic-styles>
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Overview</text:h>
      <text:p>First paragraph.</text:p>
      <text:h text:outline-level="2">History</text:h>
      <text:p text:style-name="P3">Details</text:p>
      <text:p>Last paragraph.</text:p>
    </office:text>
  </office:body>
</office:document-content>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("content.xml", xml)

            document = extract_fact_pattern_document(path)

            self.assertEqual(
                document.text,
                "Overview\n\nFirst paragraph.\n\nHistory\n\nDetails\n\nLast paragraph.",
            )
            self.assertEqual(
                [(heading.level, heading.text) for heading in document.headings],
                [(1, "Overview"), (2, "History"), (3, "Details")],
            )
            self.assertEqual(
                [
                    document.text[heading.start_offset:heading.end_offset]
                    for heading in document.headings
                ],
                ["Overview", "History", "Details"],
            )

    def test_extract_pdf_text_uses_pdftotext_stdout(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout=" Page one. \n\n Page two. ", stderr="")
        with patch("open_law_lens.fact_patterns.shutil.which", return_value="/usr/bin/pdftotext"):
            with patch("open_law_lens.fact_patterns.subprocess.run", return_value=completed) as run:
                text = extract_pdf_text(Path("/tmp/facts.pdf"))

        self.assertEqual(text, "Page one.\n\nPage two.")
        run.assert_called_once()

    def test_extract_pdf_text_reports_pdftotext_failure(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="syntax error")
        with patch("open_law_lens.fact_patterns.shutil.which", return_value="/usr/bin/pdftotext"):
            with patch("open_law_lens.fact_patterns.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(FactPatternError, "syntax error"):
                    extract_pdf_text(Path("/tmp/facts.pdf"))

    def test_extract_fact_pattern_rejects_unsupported_suffix(self) -> None:
        with self.assertRaisesRegex(FactPatternError, "ODT or PDF"):
            extract_fact_pattern_text(Path("/tmp/facts.txt"))

    def test_export_fact_pattern_copies_source_and_writes_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "facts.odt"
            xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:text><text:p>Fact text.</text:p></office:text></office:body>
</office:document-content>"""
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("content.xml", xml)

            export = export_fact_pattern(source, root / "workspace" / "fact_pattern")

            self.assertTrue(export.source_copy_path.is_file())
            self.assertTrue(export.text_path.is_file())
            self.assertEqual(export.text_path.read_text(encoding="utf-8"), "Fact text.\n")


if __name__ == "__main__":
    unittest.main()
