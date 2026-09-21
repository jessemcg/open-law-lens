"""Display-only regression for padding present in CourtListener citation HTML."""
import unittest

from open_law_lens.app import build_case_reader_payload
from open_law_lens.library import (
    DisplayText, PageMarker, normalize_display_parenthesis_spacing, opinion_display_text,
)
from open_law_lens.opinion_formatting import DisplayStyleSpan


class ParenthesisSpacingTests(unittest.TestCase):
    def test_upstream_html_padding_not_link_tag_spacing(self):
        raw = ('<p>See ( <i>People v. Example</i> (2018) '
               '<a href="/opinion/1/">24 Cal.App.5th 596</a>), '
               'and ( Health &amp; Saf. Code, § 11359).</p>')
        opinion = {'html_with_citations': raw}
        display = opinion_display_text(opinion)
        self.assertIn('(People v. Example', display.text)
        self.assertIn('(Health & Saf. Code', display.text)
        self.assertEqual(opinion['html_with_citations'], raw)
        payload = build_case_reader_payload({}, [display])
        self.assertEqual(len(payload.cited_links), 2)
        for link in payload.cited_links:
            self.assertEqual(payload.text[link.start_offset - 1], '(')

    def test_existing_display_anchors_and_combined_opinions_are_translated(self):
        text = 'Résumé (  [*600]People v. Example (2018) 24 Cal.App.5th 596).\n\nHEADING'
        start = text.index('[*600]')
        heading = text.index('HEADING')
        original = DisplayText(text, 'html_with_citations',
                               [PageMarker('600', '[*600]', start, start + 6, 'html_with_citations')],
                               [DisplayStyleSpan('heading', heading, len(text))])
        normalized = normalize_display_parenthesis_spacing(original)
        self.assertEqual(original.text, text)
        self.assertEqual(normalized, normalize_display_parenthesis_spacing(normalized))
        self.assertIn('([*600]People', normalized.text)
        for marker in normalized.page_markers:
            self.assertEqual(normalized.text[marker.start_offset:marker.end_offset], marker.marker_text)
        span = normalized.style_spans[0]
        self.assertEqual(normalized.text[span.start_offset:span.end_offset], 'HEADING')
        payload = build_case_reader_payload({}, [original, DisplayText('( WIC § 300)', '', [], [])])
        self.assertEqual(payload.text[payload.cited_links[-1].start_offset:payload.cited_links[-1].end_offset], 'WIC § 300')
        self.assertNotIn('( ', payload.text)

    def test_line_breaks_and_empty_fields_are_not_collapsed(self):
        text = '(\nIndented text) and (   )'
        self.assertEqual(normalize_display_parenthesis_spacing(DisplayText(text, '', [], [])).text, text)


if __name__ == '__main__':
    unittest.main()
