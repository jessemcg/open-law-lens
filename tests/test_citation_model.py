from __future__ import annotations

import unittest

from open_law_lens.citation_model import (
    is_official_reporter,
    official_citation_from_cluster,
    official_citation_parts_from_cluster,
    official_citation_parts_from_text,
)
from open_law_lens.external_import import normalize_official_citation


class OfficialCitationModelTests(unittest.TestCase):
    def test_accepts_numeric_official_reporter_citation(self) -> None:
        cluster = {
            "citations": [
                {"volume": 42, "reporter": "Cal.App.5th", "page": 100}
            ]
        }

        self.assertEqual(official_citation_from_cluster(cluster), "42 Cal.App.5th 100")

    def test_rejects_slip_opinion_reporter_placeholders(self) -> None:
        cluster = {
            "citations": [
                {"volume": "___", "reporter": "Cal.App.5th", "page": "___"}
            ]
        }

        self.assertEqual(official_citation_from_cluster(cluster), "")

    def test_accepts_united_states_supreme_court_reporter(self) -> None:
        cluster = {
            "citations": [
                {"volume": "499", "reporter": "U.S.", "page": "279"},
                {"volume": "111", "reporter": "S. Ct.", "page": "1246"},
            ]
        }

        self.assertEqual(official_citation_from_cluster(cluster), "499 U.S. 279")
        self.assertEqual(
            official_citation_parts_from_cluster(cluster), ("499", "U.S.", "279")
        )

    def test_normalizes_loose_united_states_reporter_spacing(self) -> None:
        for value in ("499 U.S. 279", "499 U. S. 279", "499 US 279"):
            self.assertEqual(
                official_citation_parts_from_text(value), ("499", "U.S.", "279")
            )

    def test_normalizes_california_style_supreme_court_citation_text(self) -> None:
        self.assertEqual(
            normalize_official_citation("Arizona v. Fulminante (1991) 499 U.S. 279"),
            "499 U.S. 279",
        )
        self.assertEqual(normalize_official_citation("499 U. S. 279"), "499 U.S. 279")

    def test_is_official_reporter(self) -> None:
        self.assertTrue(is_official_reporter("U.S."))
        self.assertTrue(is_official_reporter("Cal.App.5th"))
        self.assertFalse(is_official_reporter("S. Ct."))
        self.assertFalse(is_official_reporter("Cal.Rptr.3d"))


if __name__ == "__main__":
    unittest.main()
