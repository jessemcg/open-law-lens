from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from open_law_lens.cache import JsonCache
from open_law_lens.slip_opinions import (
    SlipOpinionError,
    case_number_from_cluster,
    fetch_slip_opinion,
    is_recent_published_california_case,
    slip_metadata_from_text,
    slip_opinion_pdf_path,
    slip_opinion_url,
    slip_text_display_from_pages,
)


class SlipOpinionTests(unittest.TestCase):
    def test_slip_opinion_url_normalizes_case_number(self) -> None:
        self.assertEqual(
            slip_opinion_url("a173218"),
            "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
        )

    def test_case_number_from_cluster_reads_nested_docket(self) -> None:
        cluster = {
            "docket": {
                "docket_number": "A173218",
                "court": {"id": "calctapp1d"},
            }
        }

        self.assertEqual(case_number_from_cluster(cluster), "A173218")

    def test_recent_published_california_case_requires_status_court_and_age(self) -> None:
        cluster = {
            "precedential_status": "Published",
            "date_filed": "2026-06-01",
            "docket": {"court": {"id": "calctapp1d"}},
        }

        self.assertTrue(
            is_recent_published_california_case(
                cluster,
                max_age_days=120,
                today=date(2026, 7, 7),
            )
        )

        unpublished = {**cluster, "precedential_status": "Unpublished"}
        self.assertFalse(
            is_recent_published_california_case(
                unpublished,
                max_age_days=120,
                today=date(2026, 7, 7),
            )
        )

    def test_default_recent_window_includes_four_month_old_published_case(self) -> None:
        cluster = {
            "precedential_status": "Published",
            "date_filed": "2026-03-06",
            "docket": {"court": {"id": "calctapp1d"}},
        }

        self.assertTrue(
            is_recent_published_california_case(
                cluster,
                today=date(2026, 7, 7),
            )
        )

    def test_slip_text_display_inserts_page_markers(self) -> None:
        display = slip_text_display_from_pages([" First page.\n", "Second page.\n"])

        self.assertIn("[Slip opn. p. 1]\nFirst page.", display.text)
        self.assertIn("[Slip opn. p. 2]\nSecond page.", display.text)
        self.assertEqual([marker.page_label for marker in display.page_markers], ["1", "2"])
        self.assertEqual(display.page_markers[0].marker_text, "[Slip opn. p. 1]")

    def test_slip_text_display_preserves_paragraphs_and_drops_printed_page_numbers(self) -> None:
        display = slip_text_display_from_pages(
            [
                "BACKGROUND\n\n  First paragraph wraps\n  onto another line.\n\nII.\n\n  Second paragraph.\n",
                "2\n  Continued paragraph on second page.\n",
            ]
        )

        self.assertIn("BACKGROUND\n\nFirst paragraph wraps onto another line.", display.text)
        self.assertIn("II.\n\nSecond paragraph.", display.text)
        self.assertIn("[Slip opn. p. 2]\nContinued paragraph on second page.", display.text)
        self.assertNotIn("\n2\n", display.text)

    def test_slip_metadata_from_text_extracts_filed_date_and_caption(self) -> None:
        metadata = slip_metadata_from_text(
            "[Slip opn. p. 1]\n"
            "Filed 3/6/26\n\n"
            "CERTIFIED FOR PUBLICATION\n\n"
            "In re L.G., a Person Coming Under the Juvenile Court Law.\n"
        )

        self.assertEqual(
            metadata,
            {
                "date_filed": "2026-03-06",
                "case_name": "In re L.G.",
                "case_name_short": "In re L.G.",
            },
        )

    def test_fetch_slip_opinion_reuses_cached_pdf_and_pdftotext(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            pdf_path = slip_opinion_pdf_path(cache, "A173218")
            pdf_path.write_bytes(b"%PDF cached")

            completed = Mock()
            completed.returncode = 0
            completed.stdout = "First page.\fSecond page."
            completed.stderr = ""
            with (
                patch("open_law_lens.slip_opinions.shutil.which", return_value="/usr/bin/pdftotext"),
                patch("open_law_lens.slip_opinions.subprocess.run", return_value=completed) as run_mock,
                patch("open_law_lens.slip_opinions.urlopen") as urlopen_mock,
            ):
                result = fetch_slip_opinion("A173218", cache)

        urlopen_mock.assert_not_called()
        run_mock.assert_called_once()
        self.assertEqual(result.case_number, "A173218")
        self.assertEqual(result.page_count, 2)

    def test_fetch_slip_opinion_requires_pdftotext(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            slip_opinion_pdf_path(cache, "A173218").write_bytes(b"%PDF cached")
            with patch("open_law_lens.slip_opinions.shutil.which", return_value=None):
                with self.assertRaisesRegex(SlipOpinionError, "pdftotext"):
                    fetch_slip_opinion("A173218", cache)
