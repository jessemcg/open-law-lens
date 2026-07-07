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

    def test_cited_case_links_do_not_include_preceding_sentence_words(self) -> None:
        text = (
            "We faced a somewhat similar problem in Daniels v. Department "
            "of Motor Vehicles (1983) 33 Cal.3d 532"
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["33 Cal.3d 532"])
        self.assertEqual([link.case_name for link in links], ["Daniels v. Department of Motor Vehicles"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Daniels v. Department of Motor Vehicles (1983) 33 Cal.3d 532",
        )

    def test_cited_case_links_do_not_include_narrative_citation_verb(self) -> None:
        text = "The court cited Daniels v. Department of Motor Vehicles (1983) 33 Cal.3d 532."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["33 Cal.3d 532"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Daniels v. Department of Motor Vehicles (1983) 33 Cal.3d 532",
        )

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

    def test_cited_case_links_exclude_narrative_intro_phrase(self) -> None:
        text = (
            "As the California Supreme Court explained in MacPherson v. MacPherson "
            "(1939) 13 Cal.2d 271 [89 P.2d 382]."
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["13 Cal.2d 271"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "MacPherson v. MacPherson (1939) 13 Cal.2d 271",
        )

    def test_cited_case_links_find_adversarial_parenthetical_case_names(self) -> None:
        text = "The rule follows People v. Superior Court (Romero) (1996) 13 Cal.4th 497."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["13 Cal.4th 497"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "People v. Superior Court (Romero) (1996) 13 Cal.4th 497",
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

    def test_cited_case_links_find_published_slip_placeholder_citations(self) -> None:
        text = "The answer cites In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["A173218"])
        self.assertEqual([link.case_name for link in links], ["In re L.G."])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___",
        )

    def test_cited_case_links_find_adoption_of_case_names(self) -> None:
        text = (
            "The term comes from Adoption of Kelsey S. (1992) 1 Cal.4th 816. "
            "Later shorthand cites Kelsey S., 1 Cal.4th at pp. 849-850."
        )

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["1 Cal.4th 816"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Adoption of Kelsey S. (1992) 1 Cal.4th 816",
        )

    def test_cited_case_links_find_estate_case_names(self) -> None:
        text = "The rule follows Estate of Teed (1952) 112 Cal.App.2d 638."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["112 Cal.App.2d 638"])
        self.assertEqual([link.case_name for link in links], ["Estate of Teed"])
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Estate of Teed (1952) 112 Cal.App.2d 638",
        )

    def test_cited_case_links_find_conservatorship_case_names(self) -> None:
        text = "The court cited Conservatorship of O.B. (2020) 9 Cal.5th 989."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["9 Cal.5th 989"])
        self.assertEqual([link.case_name for link in links], ["Conservatorship of O.B."])
        self.assertEqual(
            [link.full_text for link in links],
            ["Conservatorship of O.B. (2020) 9 Cal.5th 989"],
        )
        self.assertEqual(
            text[links[0].start_offset:links[0].end_offset],
            "Conservatorship of O.B. (2020) 9 Cal.5th 989",
        )

    def test_cited_case_links_normalize_conservatorship_person_caption(self) -> None:
        text = "The court cited Conservatorship of the Person of O.B. (2020) 9 Cal.5th 989."

        links = cited_case_links(text)

        self.assertEqual([link.lookup_text for link in links], ["9 Cal.5th 989"])
        self.assertEqual([link.case_name for link in links], ["Conservatorship of O.B."])

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

    def test_citation_italic_spans_cover_slip_placeholder_case_names(self) -> None:
        text = "The answer cites In re L.G. (Mar. 6, 2026, A173218) ___ Cal.App.5th ___."

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["In re L.G."],
        )

    def test_citation_italic_spans_cover_conservatorship_case_names(self) -> None:
        text = "The court cited Conservatorship of O.B. (2020) 9 Cal.5th 989."

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Conservatorship of O.B."],
        )

    def test_citation_italic_spans_cover_additional_proceeding_case_names(self) -> None:
        text = (
            "The court cited Estate of Teed (1952) 112 Cal.App.2d 638, "
            "Guardianship of Ann S. (2009) 45 Cal.4th 1110, "
            "and Matter of Acosta (1985) 480 U.S. 421."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Estate of Teed", "Guardianship of Ann S.", "Matter of Acosta"],
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

    def test_citation_italic_spans_exclude_narrative_intro_phrase(self) -> None:
        text = (
            "As the California Supreme Court explained in MacPherson v. MacPherson "
            "(1939) 13 Cal.2d 271."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["MacPherson v. MacPherson"],
        )

    def test_citation_italic_spans_exclude_sentence_words_before_case_name(self) -> None:
        text = (
            "We faced a somewhat similar problem in Daniels v. Department "
            "of Motor Vehicles (1983) 33 Cal.3d 532."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Daniels v. Department of Motor Vehicles"],
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

    def test_citation_italic_spans_cover_conservatorship_names_before_supra(self) -> None:
        text = "Conservatorship of O.B., supra, at page 1011."

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Conservatorship of O.B.", "supra"],
        )

    def test_citation_italic_spans_cover_estate_names_before_supra(self) -> None:
        text = "(Estate of Teed, supra, 112 Cal.App.2d at p. 644.)"

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Estate of Teed", "supra"],
        )

    def test_citation_italic_spans_cover_short_case_names_before_supra(self) -> None:
        text = (
            "Caden C., supra, 11 Cal.5th at p. 625; "
            "Lehr, supra, 463 U.S. at p. 260."
        )

        spans = citation_italic_spans(text)

        self.assertEqual(
            [text[span.start_offset:span.end_offset] for span in spans],
            ["Caden C.", "supra", "Lehr", "supra"],
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

    def test_cluster_citation_texts_returns_only_official_citation(self) -> None:
        cluster = {
            "citations": [
                {"volume": "51", "reporter": "Cal.3d", "page": "368"},
                {"volume": "795", "reporter": "P.2d", "page": "1244"},
            ],
        }

        self.assertEqual(cluster_citation_texts(cluster), ["51 Cal.3d 368"])

    def test_current_case_exclusion_uses_only_official_citation(self) -> None:
        text = (
            "Header In re Caden C. (2021) 11 Cal.5th 614. "
            "The opinion cites In re Caden C. (2019) 34 Cal.App.5th 87 "
            "and In re Breanna S. (2017) 8 Cal.App.5th 636."
        )
        polluted_cluster = {
            "official_citation": "11 Cal.5th 614",
            "citations": [
                {"volume": "11", "reporter": "Cal.5th", "page": "614"},
                {"volume": "34", "reporter": "Cal.App.5th", "page": "87"},
                {"volume": "8", "reporter": "Cal.App.5th", "page": "636"},
            ],
        }

        links = cited_case_links(text, excluded_citations=cluster_citation_texts(polluted_cluster))

        self.assertEqual([link.lookup_text for link in links], ["34 Cal.App.5th 87", "8 Cal.App.5th 636"])


if __name__ == "__main__":
    unittest.main()
