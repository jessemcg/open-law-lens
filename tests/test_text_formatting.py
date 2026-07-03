from __future__ import annotations

import unittest

from open_law_lens.text_formatting import smart_quote_display_text


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
