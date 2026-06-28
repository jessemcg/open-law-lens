from __future__ import annotations

import unittest

from open_law_lens.citation_links import (
    citation_italic_spans,
    cited_case_links,
    cluster_citation_texts,
)


class CitationLinkTests(unittest.TestCase):
    def test_cited_case_links_find_full_official_citations(self) -> None:
        text = (
            "The rule follows In re Alexis E. (2009) 171 Cal.App.4th 438, 451 "
            "and In re Malinda S. (1990) 51 Cal.3d 368."
        )

        links = cited_case_links(text)

        self.assertEqual(
            [link.lookup_text for link in links],
            ["171 Cal.App.4th 438", "51 Cal.3d 368"],
        )
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "In re Alexis E. (2009) 171 Cal.App.4th 438",
        )

    def test_cited_case_links_skip_excluded_current_case_citations(self) -> None:
        text = (
            "Header In re Malinda S. (1990) 51 Cal. 3d 368. "
            "Later cites In re Alexis E. (2009) 171 Cal.App.4th 438."
        )

        links = cited_case_links(text, excluded_citations=["51 Cal.3d 368"])

        self.assertEqual([link.lookup_text for link in links], ["171 Cal.App.4th 438"])

    def test_cited_case_links_ignore_reporter_only_citations(self) -> None:
        self.assertEqual(cited_case_links("The later citation is 171 Cal.App.4th 438."), [])

    def test_cited_case_links_ignore_shorthand_only_references(self) -> None:
        self.assertEqual(cited_case_links("Id. at p. 12; ibid.; supra."), [])

    def test_cited_case_links_do_not_cross_supra_separator(self) -> None:
        text = (
            "In re L. Y. L., supra, at p. 948; see County of Alameda v. "
            "Carleson (1971) 5 Cal.3d 730"
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["5 Cal.3d 730"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "County of Alameda v. Carleson (1971) 5 Cal.3d 730",
        )

    def test_cited_case_links_exclude_prefatory_signal_phrases(self) -> None:
        text = (
            "Relying on Michael M. v. Giovanna F. (1992) 5 Cal.App.4th 1272. "
            "See also Lehr v. Robertson (1983) 463 U.S. 248."
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["5 Cal.App.4th 1272", "463 U.S. 248"])
        self.assertEqual(
            [text[link.start_offset:link.end_offset] for link in links],
            [
                "Michael M. v. Giovanna F. (1992) 5 Cal.App.4th 1272",
                "Lehr v. Robertson (1983) 463 U.S. 248",
            ],
        )

    def test_cited_case_links_exclude_prefatory_decision_phrase(self) -> None:
        text = "The decision in Cesar V. v. Superior Court (2001) 91 Cal.App.4th 1023"

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["91 Cal.App.4th 1023"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Cesar V. v. Superior Court (2001) 91 Cal.App.4th 1023",
        )

    def test_cited_case_links_find_california_supreme_court_cal5th_citations(self) -> None:
        text = (
            "A Law answer may cite In re Caden C. (2021) 11 Cal.5th 614 "
            "and In re N.R. (2023) 15 Cal.5th 520."
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["11 Cal.5th 614", "15 Cal.5th 520"])
        self.assertEqual(
            [text[link.start_offset:link.end_offset] for link in links],
            [
                "In re Caden C. (2021) 11 Cal.5th 614",
                "In re N.R. (2023) 15 Cal.5th 520",
            ],
        )

    def test_citation_italic_spans_cover_case_names_in_full_citations(self) -> None:
        text = (
            "The rule follows In re Alexis E. (2009) 171 Cal.App.4th 438 "
            "and Michael M. v. Giovanna F. (1992) 5 Cal.App.4th 1272."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["In re Alexis E.", "Michael M. v. Giovanna F."],
        )

    def test_citation_italic_spans_cover_cal5th_case_names(self) -> None:
        text = "The rule follows In re Caden C. (2021) 11 Cal.5th 614."

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["In re Caden C."],
        )

    def test_citation_italic_spans_exclude_signal_phrases(self) -> None:
        text = (
            "Relying on Michael M. v. Giovanna F. (1992) 5 Cal.App.4th 1272. "
            "See also Lehr v. Robertson (1983) 463 U.S. 248."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Michael M. v. Giovanna F.", "Lehr v. Robertson"],
        )

    def test_citation_italic_spans_cover_case_names_before_supra(self) -> None:
        text = (
            "In re L. Y. L., supra, at p. 948; "
            "County of Alameda v. Carleson, supra."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["In re L. Y. L.", "supra", "County of Alameda v. Carleson", "supra"],
        )

    def test_citation_italic_spans_cover_shorthand_terms(self) -> None:
        text = "Id. at p. 12; ibid.; supra; ID at p. 14."

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Id.", "ibid.", "supra", "ID"],
        )

    def test_citation_italic_spans_ignore_reporter_only_citations(self) -> None:
        text = "The later citation is 171 Cal.App.4th 438."

        self.assertEqual(citation_italic_spans(text), [])

    def test_cluster_citation_texts_renders_lookup_citations(self) -> None:
        cluster = {
            "citations": [
                {"volume": "51", "reporter": "Cal.3d", "page": "368"},
                {"volume": "795", "reporter": "P.2d", "page": "1244"},
            ],
        }

        self.assertEqual(cluster_citation_texts(cluster), ["51 Cal.3d 368", "795 P.2d 1244"])


if __name__ == "__main__":
    unittest.main()
