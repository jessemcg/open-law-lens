"""Network-free California enactment matrix and context isolation regressions."""
import unittest
from unittest.mock import patch

from open_law_lens.california_codes import CODES
from open_law_lens.citation_links import CitationContext, collect_authority_links
from open_law_lens.citation_context import JUVENILE_RULES, JUVENILE_RULE_SOURCE
from open_law_lens.statutes import parse_statute_citation, statute_url, StatuteLink
from open_law_lens.rules import parse_rule_citation, RuleLink


def targets(text, context=CitationContext(california=True)):
    result = []
    for link in collect_authority_links(text, context=context):
        if isinstance(link, StatuteLink):
            citation = parse_statute_citation(link.lookup_text)
            result.append((text[link.start_offset:link.end_offset], citation.statute_id))
        elif isinstance(link, RuleLink):
            citation = parse_rule_citation(link.lookup_text)
            result.append((text[link.start_offset:link.end_offset], citation.rule_id))
    return result


class CitationContextTests(unittest.TestCase):
    def test_catalogue(self):
        self.assertEqual(len(CODES), 29)
        for code in CODES:
            canonical = f'{code.identifier}:1203.1ab'
            self.assertEqual(parse_statute_citation(canonical).statute_id, canonical)
            self.assertEqual(targets(canonical), [(canonical, canonical)])
            for alias in (code.name, code.abbreviation, code.identifier, *code.aliases):
                for qualifier in ('', 'Cal. ', 'California '):
                    text = f'{qualifier}{alias}, § 1203.1ab'
                    with self.subTest(text=text):
                        self.assertEqual(parse_statute_citation(text).law_code, code.identifier)
                        self.assertEqual(targets(text), [(text, f'{code.identifier}:1203.1ab')])
                        self.assertIn(f'lawCode={code.identifier}&sectionNum=1203.1ab', statute_url(code.identifier, '1203.1ab'))

    def test_exact_matrix(self):
        cases = [
            ('Government Code section 815.6', [('Government Code section 815.6', 'GOV:815.6')]),
            ('Gov. Code, § 815.6', [('Gov. Code, § 815.6', 'GOV:815.6')]),
            ('Cal. Civ. Proc. Code § 437c', [('Cal. Civ. Proc. Code § 437c', 'CCP:437c')]),
            ('Welf. & Inst. Code, § 300, subd. (b)(1)', [('Welf. & Inst. Code, § 300, subd. (b)(1)', 'WIC:300')]),
            ('Welf. & Inst. Code, §§ 300, 361.5, and 366.26', [('Welf. & Inst. Code, §§ 300', 'WIC:300'), ('361.5', 'WIC:361.5'), ('366.26', 'WIC:366.26')]),
            ('Civil Code sections 51 and 51.2', [('Civil Code sections 51', 'CIV:51'), ('51.2', 'CIV:51.2')]),
            ('Civil Code §§ 1810.2–1812.12', [('Civil Code §§ 1810.2', 'CIV:1810.2'), ('1812.12', 'CIV:1812.12')]),
            ('BPC § 16700 et seq.', [('BPC § 16700', 'BPC:16700')]),
            ('section 844 of the Penal Code', [('section 844 of the Penal Code', 'PEN:844')]),
            ('section 300, subdivision (b), of the Welfare and Institutions Code', [('section 300, subdivision (b), of the Welfare and Institutions Code', 'WIC:300')]),
            ('Cal. Rules of Court, rules 8.450 and 8.452', [('Cal. Rules of Court, rules 8.450', 'CRC:8.450'), ('8.452', 'CRC:8.452')]),
            ('CRC 5.112.1–5.125', [('CRC 5.112.1', 'CRC:5.112.1'), ('5.125', 'CRC:5.125')]),
            ('😀 Health\u00a0and\nSafety Code § 1203.1ab', [('Health\u00a0and\nSafety Code § 1203.1ab', 'HSC:1203.1ab')]),
            ('WIC § 300, subds. (b) and (c)', [('WIC § 300, subds. (b) and (c)', 'WIC:300')]),
            ('CCP § 437c, subds. (a)–(c)', [('CCP § 437c, subds. (a)–(c)', 'CCP:437c')]),
            ('CIV § 123a.5', [('CIV § 123a.5', 'CIV:123a.5')]),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(targets(text), expected)
        for prefix in ('California Rules of Court, rule', 'Cal. Rules of Court, rule', 'CRC', 'Cal. R. Ct.', 'Cal. R.'):
            for number in ('8.204', '5.112.1', '9.49.1', '10.1'):
                text = f'{prefix} {number}(a)(1)(B)'
                self.assertEqual(targets(text), [(text, f'CRC:{number}')])

    def test_defaults_and_same_section(self):
        declaration = 'All further statutory references are to the Welfare and Institutions Code unless otherwise indicated.'
        self.assertEqual(targets(declaration + '\n\nsection 300(b)(1) and 361.5'),
                         [('section 300(b)(1)', 'WIC:300'), ('361.5', 'WIC:361.5')])
        self.assertEqual(targets('Penal Code section 300 applies; section 300(b)(1) applies.'),
                         [('Penal Code section 300', 'PEN:300'), ('section 300(b)(1)', 'PEN:300')])
        self.assertEqual(len(targets('Penal Code section 300 applies. Section 301 applies.')), 1)
        self.assertEqual(len(targets('Penal Code section 300 applies.\n\nSection 300 applies.')), 1)
        self.assertEqual(len(targets('Penal Code section 300; Civil Code section 51; section 300.')), 2)
        self.assertEqual(targets('section 300', CitationContext(owning_code='FAM')), [('section 300', 'FAM:300')])
        for quote in ('"{}"', '“{}”', "'{}'", '> {}'):
            self.assertEqual(targets(quote.format(declaration) + '\n\nsection 300'), [])
        conflict = declaration + ' All section references are to the Penal Code. section 300'
        self.assertEqual(targets(conflict), [])
        self.assertEqual(targets('section 300'), [])
        self.assertEqual(len(targets('Penal Code section 300; sections 300 and 301.')), 2)
        self.assertEqual(len(targets('Penal Code section 300; CRC 8.204; section 300.')), 2)
        self.assertEqual(len(targets('WIC §§ 300, 361.5; section 361.5.')), 3)
        self.assertEqual(targets('section 51 of the Civil Code; Penal Code § 300; section 300.')[-1], ('section 300', 'PEN:300'))
        self.assertEqual(len(targets('WIC § 300\n \nsection 300')), 1)

    def test_official_family_membership(self):
        self.assertTrue(JUVENILE_RULE_SOURCE.endswith('rule5_502'))
        for rule in JUVENILE_RULES:
            self.assertEqual(targets('section 300', CitationContext(official_rule=rule)), [('section 300', 'WIC:300')])
        for rule in ('5.112.1', '5.499', '5.503', '5.680', '8.204', '5.999'):
            self.assertEqual(targets('section 300', CitationContext(official_rule=rule)), [])

    def test_fail_closed(self):
        context = CitationContext(california=True, owning_code='WIC')
        for text in ('Nevada Civil Code section 300', 'Local rule 3.10',
                     'Rules of Professional Conduct, rule 3.3', 'Federal rule 3.10',
                     '42 U.S.C. section 300', '15 C.F.R. section 300',
                     'California Constitution section 300', 'Municipal Code section 300',
                     'Witkin, section 300', 'WIC § 300.123.456',
                     'CRC 5.112.1.3', 'former rule 8.204', 'former WIC § 300',
                     'rule 39', 'id. at 300', 'ibid. 300',
                     'Nevada\nCivil Code § 300', 'Nev. Civil Code § 300',
                     'Los Angeles Superior Court rule 3.10', 'Fed. R. Civ. P., rule 3.10',
                     'Cal. Code Regs., tit. 22, § 300', 'Cal. Const., art. I, § 7',
                     '42 USC § 300', 'Stats. 2020, § 300', 'CCP WIC § 300',
                     'Family Code / Penal Code § 300', 'rule 5.680 [Repealed]'):
            with self.subTest(text=text):
                self.assertEqual(targets(text, context), [])
        self.assertEqual(targets('rule 8.204', CitationContext()), [])
        self.assertEqual(targets('lab section 300'), [])
        self.assertEqual(targets('See, rule 8.204'), [('rule 8.204', 'CRC:8.204')])
        self.assertEqual(targets('CRC:5.112.1'), [('CRC:5.112.1', 'CRC:5.112.1')])
        self.assertEqual(targets('Unemployment Insurance Code § 100'), [('Unemployment Insurance Code § 100', 'UIC:100')])

    def test_lists_stop_and_occupied_priority(self):
        for suffix in ('; 302', '\n\n302', ',\n\n302', ', in 2020', ', 2020', ', see 302', ', Civil Code § 51'):
            links = targets('WIC §§ 300, 301' + suffix)
            self.assertEqual([target for _, target in links if target.startswith('WIC')], ['WIC:300', 'WIC:301'])
        text = 'Gov. Code § 815.6 and CRC 5.112.1'
        with patch('urllib.request.urlopen', side_effect=AssertionError('render fetched')):
            links = collect_authority_links(text, context=CitationContext(), occupied_ranges=((0, 16),))
        self.assertEqual(len(links), 1)
        self.assertIsInstance(links[0], RuleLink)


if __name__ == '__main__':
    unittest.main()
