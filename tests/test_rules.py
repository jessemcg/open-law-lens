from __future__ import annotations

import unittest

from open_law_lens.rules import (
    RuleCitation,
    cited_rule_links,
    extract_california_rule_text,
    parse_rule_citation,
    rule_display_citation,
    rule_url,
)


class RuleTests(unittest.TestCase):
    def test_parse_short_long_and_bare_forms(self) -> None:
        cases = {
            "Cal. Rules of Court, rule 8.11": ("8.11", ""),
            "California Rules of Court, rule 5.695": ("5.695", ""),
            "rule 8.204(a)(1)(B)": ("8.204", "(a)(1)(B)"),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                citation = parse_rule_citation(text)
                self.assertIsNotNone(citation)
                assert citation is not None
                self.assertEqual((citation.rule_number, citation.subdivision), expected)

    def test_display_and_url(self) -> None:
        citation = RuleCitation("8.11")
        self.assertEqual(rule_display_citation(citation), "Cal. Rules of Court, rule 8.11")
        self.assertEqual(
            rule_url("8.11"),
            "https://courts.ca.gov/cms/rules/index/eight/rule8_11",
        )

    def test_extract_rule_text_starts_at_rule(self) -> None:
        html = """
        <html><body><nav>menu</nav>
        <h1>Rule 8.11. Scope of rules</h1>
        <p>(a) These rules apply.</p>
        <h1>Rule 8.12. Next rule</h1></body></html>
        """
        text = extract_california_rule_text(html, RuleCitation("8.11"))
        self.assertEqual(text, "Rule 8.11. Scope of rules\n(a) These rules apply.")

    def test_cited_rule_links(self) -> None:
        text = "See Cal. Rules of Court, rule 8.204(a)(1)(B), and rule 5.695."
        links = cited_rule_links(text)
        self.assertEqual(
            [link.lookup_text for link in links],
            ["Cal. Rules of Court, rule 8.204(a)(1)(B)", "rule 5.695"],
        )


if __name__ == "__main__":
    unittest.main()
