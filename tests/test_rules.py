from __future__ import annotations

import unittest

from open_law_lens.rules import (
    RuleCitation,
    cited_rule_links,
    extract_california_rule_text,
    parse_rule_citation,
    rule_display_citation,
    rule_pinpoint_citation,
    rule_subdivisions_for_range,
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
        self.assertEqual(text, "Rule 8.11. Scope of rules\n\n(a) These rules apply.")

    def test_extract_rule_text_collapses_source_wraps_inside_paragraphs(self) -> None:
        html = """
        <html><body><nav>menu</nav>
        <h1>Rule 8.11. Scope of rules</h1>
        <p>(a) These rules apply to any orders
        related to custody.</p>
        <p>(b) Next paragraph.</p>
        <h1>Rule 8.12. Next rule</h1></body></html>
        """

        text = extract_california_rule_text(html, RuleCitation("8.11"))

        self.assertEqual(
            text,
            "Rule 8.11. Scope of rules\n\n"
            "(a) These rules apply to any orders related to custody.\n\n"
            "(b) Next paragraph.",
        )

    def test_cited_rule_links(self) -> None:
        text = "See Cal. Rules of Court, rule 8.204(a)(1)(B), and rule 5.695."
        links = cited_rule_links(text)
        self.assertEqual(
            [link.lookup_text for link in links],
            ["Cal. Rules of Court, rule 8.204(a)(1)(B)", "Cal. Rules of Court, rule 5.695"],
        )

    def test_rule_subdivisions_for_selected_range(self) -> None:
        text = (
            "Rule 8.204. Briefs.\n"
            "(a) Contents.\n"
            "(1) Each brief must.\n"
            "(A) State facts.\n"
            "(B) Cite authority."
        )

        subdivisions = rule_subdivisions_for_range(
            text,
            text.index("State facts"),
            text.index("Cite authority") + len("Cite authority"),
        )

        self.assertEqual(subdivisions, ("(a)(1)(A)", "(a)(1)(B)"))

    def test_rule_pinpoint_appends_subdivisions_without_subd_label(self) -> None:
        citation = RuleCitation("8.204")

        self.assertEqual(
            rule_pinpoint_citation(citation, ("(a)(1)(A)",)),
            "Cal. Rules of Court, rule 8.204(a)(1)(A)",
        )
        self.assertEqual(
            rule_pinpoint_citation(citation, ("(a)(1)(A)", "(a)(1)(B)")),
            "Cal. Rules of Court, rule 8.204(a)(1)(A)-(B)",
        )


class RuleSourceSafetyTests(unittest.TestCase):
    def test_three_component_identity(self):
        citation = RuleCitation('5.112.1')
        self.assertEqual(citation.rule_id, 'CRC:5.112.1')
        self.assertTrue(rule_url(citation.rule_number).endswith('/five/rule5_112_1'))

    def test_wrong_missing_navigation_and_soft_error_bodies(self):
        from open_law_lens.rules import CaliforniaRulesError
        for body in (
            '<h1>Rule 5.112.10. Wrong</h1><p>Some real rule content.</p>',
            '<h1>Page not found</h1><p>Sorry we cannot find this page.</p>',
            '<nav><h1>Rule 5.112.1. Title</h1><p>Navigation only.</p></nav>',
            '<h1>Rule 5.112.1. Title</h1>',
            '<h1>Rule 5.112.1. Title</h1><h1>Rule 5.113. Other rule</h1>',
            '<h1>Rule 5.112.1. Title</h1><p>Search results for your request.</p>',
            '<h1>Rule 5.112. Wrong</h1><h2>Rule 5.112.1. A reference</h2><p>Other content.</p>',
        ):
            with self.subTest(body=body), self.assertRaises(CaliforniaRulesError):
                extract_california_rule_text(body, RuleCitation('5.112.1'))

    def test_cross_reference_at_paragraph_start_does_not_truncate_body(self):
        body = ('<h1>Rule 5.112.1. Title</h1><p>Rule 5.111 applies to these declarations.</p>'
                '<p>The remaining content must also be retained.</p>')
        text = extract_california_rule_text(body, RuleCitation('5.112.1'))
        self.assertIn('Rule 5.111 applies', text)
        self.assertIn('remaining content', text)

    def test_timeout_and_unrelated_redirect(self):
        from unittest.mock import patch, MagicMock
        from open_law_lens.rules import fetch_california_rule, CaliforniaRulesError
        with patch('open_law_lens.rules.urlopen', side_effect=TimeoutError):
            with self.assertRaisesRegex(CaliforniaRulesError, 'timed out'):
                fetch_california_rule(RuleCitation('5.112.1'))
        response = MagicMock()
        response.__enter__.return_value.geturl.return_value = 'https://courts.ca.gov/search'
        with patch('open_law_lens.rules.urlopen', return_value=response):
            with self.assertRaisesRegex(CaliforniaRulesError, 'redirected'):
                fetch_california_rule(RuleCitation('5.112.1'))


if __name__ == "__main__":
    unittest.main()
