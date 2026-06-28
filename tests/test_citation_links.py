from __future__ import annotations

import unittest

from open_law_lens.citation_links import cited_case_links, cluster_citation_texts


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
