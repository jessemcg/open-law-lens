from __future__ import annotations

import unittest

from open_law_lens.citation_model import official_citation_from_cluster


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


if __name__ == "__main__":
    unittest.main()
