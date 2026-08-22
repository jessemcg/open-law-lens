from __future__ import annotations

import unittest

from open_law_lens.authority_passages import (
    MAX_MATCHES_PER_QUERY,
    MAX_MERGED_PASSAGES,
    MAX_PASSAGE_CHARS,
    build_authority_passages,
)
from open_law_lens.authority_resolver import AuthorityResult


def _result(text: str, **overrides) -> AuthorityResult:
    defaults = dict(
        ok=True,
        authority_type="case",
        input="28 Cal.4th 56",
        resolved_input="28 Cal.4th 56",
        source="Library",
        title="People v. Example",
        citation="28 Cal.4th 56",
        identifier="1",
        text=text,
        official_pagination=True,
        pagination_marker_count=3,
    )
    defaults.update(overrides)
    return AuthorityResult(**defaults)


class AuthorityPassagesTests(unittest.TestCase):
    def test_omits_full_text_and_preserves_metadata(self) -> None:
        result = _result("The presumed father need not be the biological father.")
        payload = build_authority_passages(result, ["presumed father"])

        self.assertNotIn("text", payload)
        self.assertTrue(payload["text_omitted"])
        self.assertEqual(payload["citation"], "28 Cal.4th 56")
        self.assertEqual(payload["source"], "Library")
        self.assertEqual(payload["text_length"], len(result.text))
        self.assertTrue(payload["official_pagination"])
        self.assertEqual(payload["pagination_marker_count"], 3)
        self.assertIn("passages", payload)

    def test_matches_are_case_insensitive_with_whitespace_normalization(self) -> None:
        text = "The presumed   father may  rebut.\n\nA different presumed\nfather appears."
        result = _result(text)
        payload = build_authority_passages(result, ["PRESUMED  FATHER"])

        self.assertEqual(payload["unmatched_queries"], [])
        self.assertGreaterEqual(payload["match_count"], 1)
        # Every match's source slice normalizes back to the query terms.
        for passage in payload["passages"]:
            for match in passage["matches"]:
                slice_text = text[match["start_offset"] : match["end_offset"]]
                self.assertEqual(" ".join(slice_text.split()).casefold(), "presumed father")

    def test_exact_source_slice_offsets(self) -> None:
        text = "This opinion holds that presumed father status is rebuttable."
        needle = "presumed father"
        expected_start = text.index(needle)
        expected_end = expected_start + len(needle)
        result = _result(text)
        payload = build_authority_passages(result, [needle])

        self.assertEqual(payload["match_count"], 1)
        match = payload["passages"][0]["matches"][0]
        self.assertEqual(match["start_offset"], expected_start)
        self.assertEqual(match["end_offset"], expected_end)
        self.assertEqual(text[expected_start:expected_end], needle)

    def test_page_marker_metadata_is_nearest_preceding(self) -> None:
        text = "[*56] The presumed father discussion continues here."
        result = _result(text)
        payload = build_authority_passages(result, ["presumed father"])

        self.assertEqual(len(payload["passages"]), 1)
        self.assertEqual(payload["passages"][0]["page"], "56")

    def test_no_matches_is_successful_with_empty_passages(self) -> None:
        result = _result("No such language appears here.")
        payload = build_authority_passages(result, ["totally absent"])

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["passages"], [])
        self.assertEqual(payload["unmatched_queries"], ["totally absent"])
        self.assertEqual(payload["match_count"], 0)
        self.assertFalse(payload["truncated"])

    def test_limits_two_matches_per_query_and_reports_truncation(self) -> None:
        text = (
            "presumed father one. presumed father two. presumed father three. "
            "presumed father four."
        )
        result = _result(text)
        payload = build_authority_passages(result, ["presumed father"])

        total_matches = sum(len(p["matches"]) for p in payload["passages"])
        self.assertLessEqual(total_matches, MAX_MATCHES_PER_QUERY)
        self.assertTrue(payload["truncated"])

    def test_merges_overlapping_windows_into_single_passage(self) -> None:
        # Two matches close together must collapse into one passage, not two.
        text = "A presumed father and a presumed father are discussed together."
        result = _result(text)
        payload = build_authority_passages(result, ["presumed father"])

        self.assertEqual(len(payload["passages"]), 1)
        self.assertEqual(payload["match_count"], 2)
        self.assertFalse(payload["truncated"])
        # All matches fall within their enclosing passage windows.
        passage = payload["passages"][0]
        for match in passage["matches"]:
            self.assertTrue(match["start_offset"] >= passage["start_offset"])
            self.assertTrue(match["end_offset"] <= passage["end_offset"])

    def test_merges_six_passage_cap(self) -> None:
        # Spread far-apart unique matches so windows do not merge, then confirm
        # the number of passages never exceeds the configured maximum.
        filler = "x" * 2100
        parts = [
            "alpha topic one",
            "alpha topic two",
            "alpha topic three",
            "alpha topic four",
            "alpha topic five",
            "alpha topic six",
            "alpha topic seven",
            "alpha topic eight",
        ]
        text = filler.join(parts)
        result = _result(text)
        payload = build_authority_passages(result, ["alpha topic"])

        self.assertLessEqual(len(payload["passages"]), MAX_MERGED_PASSAGES)
        self.assertTrue(payload["truncated"])
        for passage in payload["passages"]:
            self.assertLessEqual(len(passage["text"]), MAX_PASSAGE_CHARS)

    def test_unmatched_queries_reported_distinctly(self) -> None:
        text = "presumed father appears but nothing else."
        result = _result(text)
        payload = build_authority_passages(
            result, ["presumed father", "no such phrase"]
        )

        self.assertEqual(payload["unmatched_queries"], ["no such phrase"])
        self.assertGreaterEqual(payload["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
