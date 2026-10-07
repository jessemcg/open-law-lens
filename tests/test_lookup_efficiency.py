from contextlib import contextmanager
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from open_law_lens.authority_resolver import resolve_case_input
from open_law_lens.case_suggestions import (case_suggestions_from_library,
    load_concordance_case_suggestions, load_concordance_rule_suggestions,
    load_concordance_statute_suggestions)
from open_law_lens.citation_model import bare_official_citation
from open_law_lens.library import CaseLibrary


class LookupEfficiencyTests(unittest.TestCase):
    def test_only_bare_supported_citations_bypass_suggestions(self):
        for value, canonical in [(' 11 Cal. 5th 614 ', '11 Cal.5th 614'),
                                 ('499 U. S. 279', '499 U.S. 279'),
                                 ('10 Cal.App.4th 25', '10 Cal.App.4th 25')]:
            with self.subTest(value=value), patch('open_law_lens.authority_resolver._case_suggestions', side_effect=AssertionError):
                self.assertEqual(resolve_case_input(value, object()), (canonical, []))
        for value in ('11 Cal.5th 614 and 12 Cal.5th 1', 'name 11 Cal.5th 614',
                      '11 Cal.5th 614x', '11 Cal.5th ___', '11 Cal.6th 1', '1 P.2d 1',
                      '11 Cal.5th 614, 620', '0 Cal.5th 1', '1 Cal.5th 0'):
            with self.subTest(value=value):
                self.assertIsNone(bare_official_citation(value))
                with patch('open_law_lens.authority_resolver._case_suggestions', return_value=[]) as suggestions:
                    resolve_case_input(value, object())
                    suggestions.assert_called_once()

    def test_absent_optional_concordance_and_read_only_suggestions(self):
        for loader in (load_concordance_case_suggestions, load_concordance_rule_suggestions,
                       load_concordance_statute_suggestions):
            self.assertEqual(loader(None), [])
        with tempfile.TemporaryDirectory() as directory:
            library = CaseLibrary(Path(directory) / 'library.sqlite3')
            library.ensure()
            for ident in (1, 2, 3):
                library.upsert_cluster({'id': ident, 'case_name': f'Example {ident} v. State',
                                        'date_filed': '2024-01-01', 'citations': [
                                            {'volume': str(ident), 'reporter': 'Cal.5th', 'page': '1'}]})
                library.upsert_opinion({'id': ident, 'cluster_id': ident,
                                       'plain_text': '[*1] Begins.\n\n[*2] Ends.'})
                library.update_case_opinion_ids(str(ident), [str(ident)])
            before = library.list_case_entries()
            expected = case_suggestions_from_library(library)
            self.assertEqual(len(expected), 3)
            original = library.connection
            statements = []
            @contextmanager
            def traced():
                with original() as conn:
                    conn.set_trace_callback(statements.append)
                    yield conn
            library.connection = traced
            with sqlite3.connect(library.path) as writer:
                writer.execute('BEGIN IMMEDIATE')
                self.assertEqual(case_suggestions_from_library(library), expected)
                with patch('open_law_lens.authority_resolver.concordance_file_path', return_value=None):
                    self.assertEqual(resolve_case_input('Example 1 v. State', SimpleNamespace(library=library))[0], '1 Cal.5th 1')
                writer.rollback()
            self.assertFalse(any(s.startswith(('UPDATE', 'INSERT', 'DELETE')) for s in statements))
            self.assertEqual(library.list_case_entries(), before)
            statements.clear()
            resolve_case_input('1 Cal.5th 1', SimpleNamespace(library=library))
            self.assertEqual(statements, [])
            library.read_cluster('1')
            library.read_case_opinion_ids('1')
            self.assertEqual(sum(s.startswith('UPDATE') for s in statements), 2)
