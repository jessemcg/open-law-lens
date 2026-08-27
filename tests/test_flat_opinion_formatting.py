from __future__ import annotations

import re
import unittest

from open_law_lens.opinion_formatting import (
    is_flat_opinion_text,
    regroup_flat_opinion_text,
)
from open_law_lens.library import opinion_display_text


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _long_flat_text() -> str:
    body = (
        "The juvenile court sustained the allegations of the supplemental petition after "
        "a contested jurisdictional hearing, finding by clear and convincing evidence that "
        "returning the child to the parent's custody would create a substantial risk of harm "
        "to the child's physical health, safety, protection, or physical or emotional "
        "well-being, and that reasonable services had been offered or provided to the parent. "
    )
    return body * 12


class FlatOpinionRegroupTests(unittest.TestCase):
    def test_normative_text_is_preserved_modulo_whitespace(self) -> None:
        text = _long_flat_text()
        grouped = regroup_flat_opinion_text(text)
        self.assertIsNotNone(grouped)
        assert grouped is not None
        self.assertNotEqual(grouped, text)
        self.assertIn("\n\n", grouped)
        self.assertEqual(_collapse(grouped), _collapse(text))

    def test_structured_text_is_left_alone(self) -> None:
        text = "Paragraph one that is substantial enough.\n\nParagraph two is also substantial and useful here.\n\nParagraph three continues the analysis with more words for a third useful block."
        self.assertFalse(is_flat_opinion_text(text))
        self.assertIsNone(regroup_flat_opinion_text(text))

    def test_short_text_is_not_regrouped(self) -> None:
        text = "A short opinion with far fewer than twelve hundred characters total."
        self.assertFalse(is_flat_opinion_text(text))
        self.assertIsNone(regroup_flat_opinion_text(text))

    def test_heading_is_kept_as_its_own_paragraph(self) -> None:
        heading = "DISCUSSION"
        body = _long_flat_text()
        text = f"{heading}\n{body}"
        grouped = regroup_flat_opinion_text(text)
        self.assertIsNotNone(grouped)
        assert grouped is not None
        self.assertTrue(grouped.startswith("DISCUSSION\n\n"))

    def test_abbreviation_period_does_not_introduce_sentence_break(self) -> None:
        # "No. 123456" and "Cal. 5th" must survive as single tokens.
        text = _long_flat_text() + " See No. 123456; see also 11 Cal. 5th 614."
        grouped = regroup_flat_opinion_text(text)
        self.assertIsNotNone(grouped)
        assert grouped is not None
        self.assertIn("No. 123456", grouped)
        self.assertIn("11 Cal. 5th 614", grouped)


class FlatOpinionDisplayTests(unittest.TestCase):
    def test_flat_plain_text_gains_paragraphs_and_preserves_markers(self) -> None:
        body = (
            "The juvenile court sustained the petition after a contested hearing, finding "
            "clear and convincing evidence of a substantial risk to the child's well-being. "
        ) * 12
        flat = f"{body} *625 We affirm the orders. *626 The appeal is without merit. *627 Disposition affirmed."
        opinion = {"plain_text": flat}

        display = opinion_display_text(opinion)

        self.assertIn("\n\n", display.text)
        labels = [marker.page_label for marker in display.page_markers]
        self.assertEqual(labels, ["625", "626", "627"])
        # Offsets point at the embedded [*n] markers in the grouped text.
        for marker in display.page_markers:
            self.assertEqual(
                display.text[marker.start_offset:marker.end_offset],
                marker.marker_text,
            )

    def test_structured_plain_text_is_unchanged(self) -> None:
        text = (
            "First substantial paragraph with several useful words in it.\n\n"
            "Second substantial paragraph with several useful words in it.\n\n"
            "Third substantial paragraph with several useful words in it."
        )
        opinion = {"plain_text": text}
        display = opinion_display_text(opinion)
        self.assertEqual(display.text.strip(), text)

    def test_flat_text_with_heading_gains_bold_span(self) -> None:
        body = (
            "The juvenile court sustained the petition after a contested hearing, finding "
            "clear and convincing evidence of a substantial risk to the child's well-being. "
        ) * 12
        flat = f"DISCUSSION\n{body}"
        opinion = {"plain_text": flat}
        display = opinion_display_text(opinion)
        heading_spans = [span for span in display.style_spans if span.kind == "heading"]
        self.assertTrue(heading_spans)
        span = heading_spans[0]
        self.assertEqual(display.text[span.start_offset:span.end_offset], "DISCUSSION")


if __name__ == "__main__":
    unittest.main()
