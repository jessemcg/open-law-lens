from __future__ import annotations

import unittest

from open_law_lens import scholar_search


class ScholarSearchUrlTests(unittest.TestCase):
    def test_builds_case_law_scoped_url(self) -> None:
        url = scholar_search.build_scholar_search_url("11 Cal.5th 614")
        self.assertIn("as_sdt=6,33", url)
        self.assertIn("q=11+Cal.5th+614", url)

    def test_collapses_whitespace_and_encodes(self) -> None:
        url = scholar_search.build_scholar_search_url("In   re  Caden")
        self.assertIn("q=In+re+Caden", url)
        self.assertNotIn("In+++re", url)

    def test_rejects_empty_query(self) -> None:
        with self.assertRaises(scholar_search.ScholarSearchError):
            scholar_search.build_scholar_search_url("   ")

    def test_accepts_a_plain_case_query(self) -> None:
        url = scholar_search.build_scholar_search_url("In re Caden C.")
        self.assertIn("q=In+re+Caden+C.", url)


if __name__ == "__main__":
    unittest.main()
