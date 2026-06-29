from __future__ import annotations

import unittest

from open_law_lens.library import opinion_display_text
from open_law_lens.quality import official_pagination_quality


class QualityTests(unittest.TestCase):
    def test_official_citation_with_matching_markers_is_eligible(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
        }
        display = opinion_display_text({"plain_text": "[*25]Opening.\n\n[*26]Next page."})

        quality = official_pagination_quality(cluster, [display])

        self.assertTrue(quality.eligible)
        self.assertEqual(quality.official_citation, "10 Cal.App.5th 25")

    def test_official_citation_without_markers_is_ineligible(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
        }
        display = opinion_display_text({"plain_text": "Opening without page markers."})

        quality = official_pagination_quality(cluster, [display])

        self.assertFalse(quality.eligible)
        self.assertIn("No embedded", quality.reason)

    def test_unofficial_reporter_is_ineligible(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "99", "reporter": "Cal. Rptr. 3d", "page": "25"}],
        }
        display = opinion_display_text({"plain_text": "[*25]Opening."})

        quality = official_pagination_quality(cluster, [display])

        self.assertFalse(quality.eligible)

    def test_far_marker_series_is_ineligible(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "Example v. State",
            "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
        }
        display = opinion_display_text({"plain_text": "[*200]Opening.\n\n[*201]Next page."})

        quality = official_pagination_quality(cluster, [display])

        self.assertFalse(quality.eligible)
        self.assertIn("too far", quality.reason)

    def test_official_series_may_start_after_introductory_reporter_pages(self) -> None:
        cluster = {
            "id": 42,
            "case_name": "In re Caden C.",
            "citations": [
                {"volume": "11", "reporter": "Cal.5th", "page": "614"},
                {"volume": "278", "reporter": "Cal.Rptr.3d", "page": "872"},
                {"volume": "486", "reporter": "P.3d", "page": "1096"},
            ],
        }
        display = opinion_display_text(
            {
                "plain_text": (
                    "11 Cal.5th 614 (2021)\n"
                    "278 Cal.Rptr.3d 872\n"
                    "486 P.3d 1096\n\n"
                    "*625 OPINION\n\n"
                    "Text.\n\n"
                    "*626 More text.\n\n"
                    "*627 More text."
                )
            }
        )

        quality = official_pagination_quality(cluster, [display])

        self.assertTrue(quality.eligible)
        self.assertEqual(quality.official_citation, "11 Cal.5th 614")


if __name__ == "__main__":
    unittest.main()
