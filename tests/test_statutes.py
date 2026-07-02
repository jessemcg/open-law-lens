from __future__ import annotations

import unittest

from open_law_lens.statutes import (
    StatuteCitation,
    cited_statute_links,
    extract_leginfo_text,
    parse_statute_citation,
    statute_display_citation,
    statute_pinpoint_citation,
    statute_subdivisions_for_range,
    statute_url,
)


class StatuteTests(unittest.TestCase):
    def test_parse_short_and_long_forms(self) -> None:
        cases = {
            "Welf. & Inst. Code, § 361.5": ("WIC", "361.5"),
            "Evidence Code section 720": ("EVID", "720"),
            "Code Civ. Proc., § 904.1": ("CCP", "904.1"),
            "Civil Code section 1714": ("CIV", "1714"),
            "Fam. Code, § 7822": ("FAM", "7822"),
            "Pen. Code section 187": ("PEN", "187"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                citation = parse_statute_citation(text)
                self.assertIsNotNone(citation)
                assert citation is not None
                self.assertEqual((citation.law_code, citation.section), expected)

    def test_bare_section_defaults_to_wic(self) -> None:
        citation = parse_statute_citation("section 300, subdivision (b)(1)")
        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.law_code, "WIC")
        self.assertEqual(citation.section, "300")
        self.assertEqual(citation.subdivision, "(b)(1)")

    def test_display_and_url(self) -> None:
        citation = StatuteCitation("WIC", "361.5")
        self.assertEqual(statute_display_citation(citation), "Welf. & Inst. Code, § 361.5")
        self.assertEqual(
            statute_url("WIC", "361.5"),
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=WIC&sectionNum=361.5",
        )

    def test_extract_leginfo_text_starts_at_section(self) -> None:
        html = """
        <html><body><nav>menu</nav>
        <div>361.5. (a) Reunification services shall be provided.</div>
        <div>History</div></body></html>
        """
        text = extract_leginfo_text(html, StatuteCitation("WIC", "361.5"))
        self.assertEqual(text, "361.5. (a) Reunification services shall be provided.")

    def test_cited_statute_links(self) -> None:
        text = "See Welf. & Inst. Code, § 300, subd. (b)(1), and Evidence Code section 720."
        links = cited_statute_links(text)
        self.assertEqual([link.lookup_text for link in links], [
            "Welf. & Inst. Code, § 300, subd. (b)(1)",
            "Evidence Code section 720",
        ])

    def test_statute_subdivisions_for_selected_range(self) -> None:
        text = "300. (a) First.\n(b) Second.\n(1) One.\n(2) Two.\n(c) Third."

        subdivisions = statute_subdivisions_for_range(
            text,
            text.index("One"),
            text.index("Two") + len("Two"),
        )

        self.assertEqual(subdivisions, ("(b)(1)", "(b)(2)"))

    def test_statute_pinpoint_uses_subd_and_subds(self) -> None:
        citation = StatuteCitation("WIC", "300")

        self.assertEqual(
            statute_pinpoint_citation(citation, ("(b)(1)",)),
            "Welf. & Inst. Code, § 300, subd. (b)(1)",
        )
        self.assertEqual(
            statute_pinpoint_citation(citation, ("(b)(1)", "(b)(2)")),
            "Welf. & Inst. Code, § 300, subds. (b)(1)-(2)",
        )


if __name__ == "__main__":
    unittest.main()
