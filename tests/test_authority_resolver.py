from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_law_lens.authority_resolver import (
    detect_authority_candidates,
    extract_case,
    first_authority_candidate,
)


class AuthorityResolverTests(unittest.TestCase):
    def test_detects_first_authority_by_text_position(self) -> None:
        candidates = detect_authority_candidates(
            "See 13 Cal.4th 952 and Welf. & Inst. Code, § 300."
        )

        self.assertEqual(candidates[0].authority_type, "case")
        self.assertEqual(candidates[0].text, "13 Cal.4th 952")

    def test_whole_input_statute_precedes_case_fallback(self) -> None:
        candidate = first_authority_candidate("Welf. & Inst. Code, § 300")

        self.assertEqual(candidate.authority_type, "statute")

    def test_case_not_in_concordance_still_uses_direct_lookup(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with (
            patch("open_law_lens.authority_resolver._case_suggestions", return_value=[]),
            patch("open_law_lens.authority_resolver._extract_case_from_scholar") as scholar,
        ):
            scholar.return_value.ok = False
            scholar.return_value.input = ""
            scholar.return_value.warnings = []
            result = extract_case("123 Cal.App.5th 456", client=client)

        client.lookup_citation.assert_called_once_with("123 Cal.App.5th 456", refresh=False)
        self.assertFalse(result.ok)

    def test_ambiguous_case_suggestion_falls_through_to_direct_lookup(self) -> None:
        client = MagicMock()
        client.lookup_citation.return_value = [{"status": 200, "clusters": []}]
        client.clusters_from_lookup.return_value = []

        with (
            patch("open_law_lens.authority_resolver.resolve_case_lookup_text", return_value=None),
            patch("open_law_lens.authority_resolver._case_suggestions", return_value=[object(), object()]),
            patch("open_law_lens.authority_resolver._extract_case_from_scholar") as scholar,
        ):
            scholar.return_value.ok = False
            scholar.return_value.input = ""
            scholar.return_value.warnings = []
            extract_case("In re Example", client=client)

        client.lookup_citation.assert_called_once_with("In re Example", refresh=False)


if __name__ == "__main__":
    unittest.main()
