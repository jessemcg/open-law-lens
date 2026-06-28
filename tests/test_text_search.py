from __future__ import annotations

import unittest

from open_law_lens.text_search import literal_match_ranges


class TextSearchTests(unittest.TestCase):
    def test_literal_match_ranges_are_case_insensitive(self) -> None:
        self.assertEqual(
            literal_match_ranges("Alpha beta ALPHA", "alpha"),
            [(0, 5), (11, 16)],
        )

    def test_literal_match_ranges_are_non_overlapping(self) -> None:
        self.assertEqual(literal_match_ranges("aaaa", "aa"), [(0, 2), (2, 4)])

    def test_literal_match_ranges_ignores_empty_query(self) -> None:
        self.assertEqual(literal_match_ranges("Alpha", ""), [])
        self.assertEqual(literal_match_ranges("Alpha", "  "), [])


if __name__ == "__main__":
    unittest.main()
