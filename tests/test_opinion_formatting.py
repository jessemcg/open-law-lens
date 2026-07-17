from __future__ import annotations

import unittest

from open_law_lens.opinion_formatting import (
    DisplayStyleSpan,
    infer_opinion_heading_spans,
)


BODY = (
    "The juvenile court considered the entire record and made the findings "
    "required by the governing statute."
)


class OpinionFormattingTests(unittest.TestCase):
    def styled_text(self, text: str, semantic_spans=()) -> list[str]:
        spans = infer_opinion_heading_spans(text, semantic_spans)
        return [text[span.start_offset:span.end_offset] for span in spans]

    def test_infers_canonical_legal_headings(self) -> None:
        text = (
            f"INTRODUCTION\n\n{BODY}\n\n"
            f"Factual and Procedural Background\n\n{BODY}\n\n"
            f"DISPOSITION\n\n{BODY}"
        )

        self.assertEqual(
            self.styled_text(text),
            ["INTRODUCTION", "Factual and Procedural Background", "DISPOSITION"],
        )

    def test_infers_reviewed_legal_vocabulary_only_with_heading_presentation(self) -> None:
        text = (
            f"Petition, Detention, and Disposition\n\n{BODY}\n\n"
            f"Relevant Law and Standard of Review\n\n{BODY}\n\n"
            f"The Sibling Relationship Exception\n\n{BODY}"
        )

        self.assertEqual(
            self.styled_text(text),
            [
                "Petition, Detention, and Disposition",
                "Relevant Law and Standard of Review",
                "The Sibling Relationship Exception",
            ],
        )

    def test_does_not_infer_unanchored_title_case_phrases(self) -> None:
        text = f"Events Preceding Melody's Death\n\n{BODY}"

        self.assertEqual(self.styled_text(text), [])

    def test_requires_substantive_body_context(self) -> None:
        text = "BACKGROUND\n\nDISPOSITION"

        self.assertEqual(self.styled_text(text), [])

    def test_infers_only_coherent_roman_outline_siblings(self) -> None:
        text = (
            f"I. FACTUAL BACKGROUND\n\n{BODY}\n\n"
            f"II. DISCUSSION\n\n{BODY}\n\n"
            f"IV. DISPOSITION\n\n{BODY}"
        )

        self.assertEqual(
            self.styled_text(text),
            ["I. FACTUAL BACKGROUND", "II. DISCUSSION"],
        )

    def test_infers_coherent_letter_and_numbered_outline_siblings(self) -> None:
        text = (
            f"A. Governing Law\n\n{BODY}\n\n"
            f"B. Application of the Law\n\n{BODY}\n\n"
            f"1. The Statutory Framework\n\n{BODY}\n\n"
            f"2. Application to This Case\n\n{BODY}"
        )

        self.assertEqual(
            self.styled_text(text),
            [
                "A. Governing Law",
                "B. Application of the Law",
                "1. The Statutory Framework",
                "2. Application to This Case",
            ],
        )

    def test_matches_main_outline_siblings_across_nested_subheadings(self) -> None:
        text = (
            f"I. BACKGROUND\n\nA. Petition\n\n{BODY}\n\n"
            f"B. Detention\n\n{BODY}\n\nII. DISCUSSION\n\n{BODY}"
        )

        self.assertEqual(
            self.styled_text(text),
            ["I. BACKGROUND", "A. Petition", "B. Detention", "II. DISCUSSION"],
        )

    def test_infers_coherent_bare_roman_outline_but_not_notes_numbers(self) -> None:
        text = (
            f"I\n\n{BODY}\n\nII\n\n{BODY}\n\n"
            f"NOTES\n\n1\n\n{BODY}\n\n2\n\n{BODY}"
        )

        self.assertEqual(self.styled_text(text), ["I", "II"])

    def test_does_not_infer_bare_number_sequences_without_notes_label(self) -> None:
        text = f"1\n\n{BODY}\n\n2\n\n{BODY}\n\n3\n\n{BODY}"

        self.assertEqual(self.styled_text(text), [])

    def test_rejects_caption_citation_court_docket_and_counsel_metadata(self) -> None:
        candidates = [
            "51 Cal.3d 368 (1990)",
            "IN THE SUPREME COURT OF CALIFORNIA",
            "Docket No. S014775.",
            "STEVEN A., Plaintiff and Respondent,",
            "COUNSEL",
            "Alys Briggs, under appointment by the Supreme Court, for Appellant",
        ]
        text = "\n\n".join(f"{candidate}\n\n{BODY}" for candidate in candidates)

        self.assertEqual(self.styled_text(text), [])

    def test_rejects_judge_signatures_and_publication_notices(self) -> None:
        candidates = [
            "BAXTER, J.",
            "WILLHITE, Acting P.J.—",
            "Kremer, P. J., and O'Rourke, J., concurred.",
            "CERTIFIED FOR PUBLICATION",
            "NOT TO BE PUBLISHED IN THE OFFICIAL REPORTS",
        ]
        text = "\n\n".join(f"{candidate}\n\n{BODY}" for candidate in candidates)

        self.assertEqual(self.styled_text(text), [])

    def test_rejects_quoted_capitals_and_sentence_prose(self) -> None:
        text = (
            f'\u201cA. Yes, sir.\u201d\n\n{BODY}\n\n'
            f"This appeal concerns only Sofia.\n\n{BODY}\n\n"
            f"The agency filed a timely notice of appeal.\n\n{BODY}"
        )

        self.assertEqual(self.styled_text(text), [])

    def test_keeps_valid_semantic_spans_and_ignores_invalid_ranges(self) -> None:
        text = "Semantic Heading\n\nShort body."
        semantic = [
            DisplayStyleSpan("heading", 0, len("Semantic Heading")),
            DisplayStyleSpan("heading", -1, 2),
            DisplayStyleSpan("heading", 3, len(text) + 1),
            DisplayStyleSpan("heading", 4, 4),
        ]

        spans = infer_opinion_heading_spans(text, semantic)

        self.assertEqual(spans, [DisplayStyleSpan("heading", 0, 16)])

    def test_semantic_span_does_not_override_metadata_rejection(self) -> None:
        text = f"NOTES\n\n{BODY}"
        semantic = [DisplayStyleSpan("heading", 0, len("NOTES"))]

        self.assertEqual(infer_opinion_heading_spans(text, semantic), [])

    def test_semantic_and_inferred_spans_exclude_leading_page_marker(self) -> None:
        text = f"[*821] OPINION\n\n{BODY}\n\n[*822] DISCUSSION\n\n{BODY}"
        semantic = [DisplayStyleSpan("heading", 0, len("[*821] OPINION"))]

        spans = infer_opinion_heading_spans(text, semantic)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["OPINION", "DISCUSSION"],
        )

    def test_semantic_span_wins_over_overlapping_inference(self) -> None:
        text = f"DISCUSSION\n\n{BODY}"
        semantic = [DisplayStyleSpan("semantic-heading", 0, len("DISCUSSION"))]

        self.assertEqual(infer_opinion_heading_spans(text, semantic), semantic)

    def test_single_giant_pre_style_paragraph_gets_no_inferred_spans(self) -> None:
        text = "INTRODUCTION " + ("flattened opinion body " * 100)

        self.assertEqual(infer_opinion_heading_spans(text), [])


if __name__ == "__main__":
    unittest.main()
