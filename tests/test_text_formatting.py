from __future__ import annotations

import unittest

from open_law_lens.text_formatting import normalize_malformed_quote_stacks, smart_quote_display_text


class TextFormattingTests(unittest.TestCase):
    def test_smart_quote_display_text_converts_double_quotes(self) -> None:
        self.assertEqual(
            smart_quote_display_text('"quoted text"'),
            "\u201cquoted text\u201d",
        )

    def test_smart_quote_display_text_converts_word_apostrophes(self) -> None:
        self.assertEqual(
            smart_quote_display_text("don't disturb the parent's rights"),
            "don\u2019t disturb the parent\u2019s rights",
        )

    def test_smart_quote_display_text_converts_single_quoted_text(self) -> None:
        self.assertEqual(
            smart_quote_display_text("'quoted phrase'"),
            "\u2018quoted phrase\u2019",
        )

    def test_smart_quote_display_text_converts_backtick_opening_single_quote(self) -> None:
        text = "protect a child `from the substantial risk of harm or illness from it.' [Citations.]"

        self.assertEqual(
            smart_quote_display_text(text),
            "protect a child \u2018from the substantial risk of harm or illness from it.\u2019 [Citations.]",
        )

    def test_smart_quote_display_text_handles_nested_quotes(self) -> None:
        self.assertEqual(
            smart_quote_display_text('"The parent said, \'yes.\'"'),
            "\u201cThe parent said, \u2018yes.\u2019\u201d",
        )

    def test_smart_quote_display_text_handles_adjacent_nested_quotes(self) -> None:
        normalized = normalize_malformed_quote_stacks('The court said "\'disappears\'" on appeal.')

        self.assertEqual(
            smart_quote_display_text(normalized),
            "The court said \u201cdisappears\u201d on appeal.",
        )

    def test_normalize_malformed_quote_stacks_collapses_duplicate_quote_marks(self) -> None:
        text = 'proof "`"disappears"\'" on appeal'
        normalized = normalize_malformed_quote_stacks(text)

        self.assertEqual(normalized, 'proof "`disappears\'" on appeal')
        self.assertEqual(
            smart_quote_display_text(normalized),
            "proof \u201c\u2018disappears\u2019\u201d on appeal",
        )

    def test_normalize_malformed_quote_stacks_collapses_curly_duplicate_quote_marks(self) -> None:
        text = "proof \u201d\u2018\u201ddisappears\u201d\u2019\u201d on appeal"

        self.assertEqual(
            smart_quote_display_text(normalize_malformed_quote_stacks(text)),
            "proof \u201c\u2018disappears\u2019\u201d on appeal",
        )

    def test_normalize_malformed_quote_stacks_collapses_nested_wrappers(self) -> None:
        text = (
            'argued that the Court of Appeal "\'must apply the same standard '
            'in determining whether "substantial evidence" supports the judgment.\'"'
        )
        normalized = normalize_malformed_quote_stacks(text)

        self.assertEqual(
            normalized,
            (
                'argued that the Court of Appeal "must apply the same standard '
                "in determining whether `substantial evidence' supports the judgment.\""
            ),
        )
        self.assertEqual(
            smart_quote_display_text(normalized),
            (
                "argued that the Court of Appeal \u201cmust apply the same standard "
                "in determining whether \u2018substantial evidence\u2019 supports the judgment.\u201d"
            ),
        )

    def test_normalize_malformed_quote_stacks_collapses_curly_nested_wrappers(self) -> None:
        text = (
            "observed that \u201c\u2018The \u201cclear and convincing\u201d standard "
            "is for the trial court.\u2019\u201d"
        )

        self.assertEqual(
            smart_quote_display_text(normalize_malformed_quote_stacks(text)),
            (
                "observed that \u201cThe \u2018clear and convincing\u2019 standard "
                "is for the trial court.\u201d"
            ),
        )

    def test_normalize_malformed_quote_stacks_collapses_long_legal_quote_stack(self) -> None:
        text = (
            'observed that, contrary to O.B.\'s position, "\'The "clear and convincing" standard '
            'is for the trial court. [Citations.] "\'The sufficiency of evidence is primarily a '
            'question for the trial court.\' [Citations.]" [Citation.] Thus, "the clear and '
            'convincing test disappears."\'" (Id., at pp. 633-634.)'
        )

        self.assertEqual(
            smart_quote_display_text(normalize_malformed_quote_stacks(text)),
            (
                "observed that, contrary to O.B.\u2019s position, \u201cThe \u2018clear and convincing\u2019 "
                "standard is for the trial court. [Citations.] \u2018The sufficiency of evidence "
                "is primarily a question for the trial court. [Citations.]\u2019 [Citation.] Thus, "
                "\u2018the clear and convincing test disappears.\u2019\u201d (Id., at pp. 633-634.)"
            ),
        )

    def test_smart_quote_display_text_opens_after_prose_word(self) -> None:
        self.assertEqual(
            smart_quote_display_text('The court must not remove custody "unless it finds evidence."'),
            "The court must not remove custody \u201cunless it finds evidence.\u201d",
        )

    def test_smart_quote_display_text_opens_bracketed_quote_after_prose_word(self) -> None:
        self.assertEqual(
            smart_quote_display_text('The circumstance where "[t]here is danger."'),
            "The circumstance where \u201c[t]here is danger.\u201d",
        )

    def test_smart_quote_display_text_preserves_numeric_measure_marks(self) -> None:
        self.assertEqual(smart_quote_display_text('The child was 5\' 8" tall.'), 'The child was 5\' 8" tall.')

    def test_smart_quote_display_text_preserves_length(self) -> None:
        text = '"The child didn\'t object," counsel said.'

        self.assertEqual(len(smart_quote_display_text(text)), len(text))


if __name__ == "__main__":
    unittest.main()
