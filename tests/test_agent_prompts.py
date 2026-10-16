from pathlib import Path
import json
import shlex
from types import SimpleNamespace
import unittest

from open_law_lens import agent_prompts as prompts


class RequestBuilderTests(unittest.TestCase):
    def setUp(self):
        self.question = '  Literal {question} {broken "quotes" O’Brien 日本語\n/skill:not-a-command $(touch /tmp/never)  '
        self.fact = SimpleNamespace(text_path=Path('/tmp/a {fact} é.txt'),
            source_copy_path=Path('/tmp/source "fact".odt'), source_path=Path('/original/fact.pdf'))
        self.authorities = SimpleNamespace(manifest_path=Path('/tmp/manifest {x}.json'),
            case_dir=Path('/tmp/authorities é'), authority_count=7)

    def test_questions_are_literal_and_requests_do_not_load_configuration(self):
        requests = (
            prompts.law_request(self.question),
            prompts.cache_request(self.question, self.authorities),
            prompts.briefs_request(self.question, Path('/tmp/snapshot {x}.sqlite3'), 42),
            prompts.assessment_request(self.question, self.fact),
        )
        for request in requests:
            self.assertIn(self.question, request)
            self.assertNotIn('You are the', request)
            self.assertNotIn('Treat the supplied', request)
        self.assertIn(str(self.authorities.manifest_path), requests[1])
        self.assertIn(str(self.authorities.case_dir), requests[1])
        self.assertIn('Selected authority count: 7', requests[1])
        self.assertIn('Indexed brief count: 42', requests[2])
        self.assertIn('/tmp/snapshot {x}.sqlite3', requests[2])
        for path in (self.fact.text_path, self.fact.source_copy_path, self.fact.source_path):
            self.assertIn(str(path), requests[3])

    def test_context_states_and_paths_in_all_ordinary_requests(self):
        factories = (
            lambda **kwargs: prompts.law_request(self.question, **kwargs),
            lambda **kwargs: prompts.cache_request(self.question, self.authorities, **kwargs),
            lambda **kwargs: prompts.briefs_request(self.question, Path('/tmp/snapshot'), 0, **kwargs),
        )
        for factory in factories:
            self.assertIn('Not selected.', factory(current_case_export=self.fact))
            self.assertNotIn(str(self.fact.text_path), factory(current_case_export=self.fact))
            missing = factory(current_case_selected=True, current_case_warning='Literal {warning} é')
            self.assertIn('Selected; unavailable: Literal {warning} é', missing)
            available = factory(current_case_export=self.fact, current_case_selected=True)
            self.assertIn('Selected; available.', available)
            self.assertIn(str(self.fact.text_path), available)
            self.assertIn(str(self.fact.source_copy_path), available)
        legacy = SimpleNamespace(manifest_path=Path('/tmp/m'), case_dir=Path('/tmp/c'), case_count=2)
        self.assertIn('Selected authority count: 2', prompts.cache_request('', legacy))

    def test_treatment_commands_keep_exact_shell_safe_arguments(self):
        title = 'O\'Brien "Fictional" v. State; $(false) {x} é'
        citation = '88 Cal.App.5th 1093; "quoted" `false`'
        cluster = 'external-id; $(false)\' é'
        request = prompts.treatment_request(title, cluster, citation)
        self.assertIn(f'Target case: {title}', request)
        self.assertIn(f'Target official citation: {citation}', request)
        commands = [line for line in request.splitlines() if line.startswith('"$OPEN_LAW_LENS_PROJECT_DIR')]
        self.assertEqual(len(commands), 6)
        graph, search_cite, search_title, compact, recovery, full = map(shlex.split, commands)
        self.assertEqual(graph[graph.index('--cluster-id') + 1], cluster)
        for tokens, value in ((search_cite, citation), (search_title, title)):
            self.assertEqual(json.loads(tokens[tokens.index('case-search') + 1]), value)
            self.assertEqual(tokens[-3:], ['--limit', '10', '--compact'])
        self.assertEqual(compact[-4:], ['--find', '<term>', '--find', '<term>'])
        self.assertEqual(recovery[recovery.index('extract-case') + 1], '<official citation>')
        self.assertIn('--recover-official', recovery)
        self.assertEqual(full[-2:], ['--cluster-id', '<cluster_id>'])
