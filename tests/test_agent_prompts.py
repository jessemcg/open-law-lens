from pathlib import Path
import json
import os
import shlex
import subprocess
import sys
import tempfile
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
        commands = dict(block.split(':\n', 1) for block in request.split('\n\n')[1:])
        self.assertEqual(list(commands), [
            'published_citing_cases_command', 'citation_search_command',
            'case_name_search_command', 'compact_extract_command',
            'recover_official_extract_command', 'full_extract_command',
        ])
        graph, search_cite, search_title, compact, recovery = (
            shlex.split(command) for command in list(commands.values())[:5]
        )
        full = shlex.split(commands['full_extract_command'].split(' && ', 1)[1])
        self.assertEqual(graph, ['$OPEN_LAW_LENS_CLI_BIN', 'published-citing-cases',
                                 '--cluster-id', cluster, '--limit', '10', '--json'])
        for tokens, value in ((search_cite, citation), (search_title, title)):
            self.assertEqual(json.loads(tokens[tokens.index('case-search') + 1]), value)
            self.assertEqual(tokens[-3:], ['--limit', '10', '--compact'])
        self.assertEqual(compact[-4:], ['--find', '<term>', '--find', '<term>'])
        self.assertEqual(recovery[recovery.index('extract-case') + 1], '<official citation>')
        self.assertIn('--recover-official', recovery)
        self.assertEqual(full, ['$OPEN_LAW_LENS_CLI_BIN', 'extract-case', '--cluster-id',
                                '<cluster_id>', '--output-dir', '$full_source_parent/source'])
        self.assertEqual(compact, ['$OPEN_LAW_LENS_CLI_BIN', 'extract-case', '--cluster-id',
                                   '<cluster_id>', '--find', '<term>', '--find', '<term>'])
        self.assertEqual(recovery, ['$OPEN_LAW_LENS_CLI_BIN', 'extract-case', '<official citation>',
                                    '--recover-official', '--timeout', '120', '--progress',
                                    '--find', '<term>'])

    def test_full_extract_template_uses_one_call_and_fresh_nonexistent_child(self):
        with tempfile.TemporaryDirectory(prefix='treatment workspace ') as directory:
            root = Path(directory)
            executable = root / 'synthetic cli'
            log = root / 'calls.jsonl'
            executable.write_text(
                f'#!{sys.executable}\n'
                'import json, os, pathlib, sys\n'
                'args = sys.argv[1:]\n'
                'dest = pathlib.Path(args[args.index("--output-dir") + 1])\n'
                'assert not dest.exists()\n'
                'assert dest.parent.is_dir()\n'
                'dest.mkdir()\n'
                '(dest / "sentinel").write_text("preserved")\n'
                'with open(os.environ["CALL_LOG"], "a") as log:\n'
                '    log.write(json.dumps(args) + "\\n")\n'
            )
            executable.chmod(0o700)
            request = prompts.treatment_request('Synthetic', '1', '1 Cal.5th 1')
            template = request.split('full_extract_command:\n', 1)[1]
            # Replace the entire placeholder argument with a shell-quoted value.
            cluster = 'id with spaces; $(false) `false` "quote" \' é'
            command = template.replace('"<cluster_id>"', shlex.quote(cluster))
            env = dict(os.environ, OPEN_LAW_LENS_AGENT_WORKSPACE=str(root),
                       OPEN_LAW_LENS_CLI_BIN=str(executable), CALL_LOG=str(log))
            for _ in range(2):
                subprocess.run(['bash', '-c', command], env=env, capture_output=True,
                               text=True, timeout=10, check=True)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            destinations = []
            for args in calls:
                self.assertEqual(args[:4], ['extract-case', '--cluster-id', cluster, '--output-dir'])
                self.assertEqual(len(args), 5)
                destination = Path(args[4])
                self.assertEqual(destination.name, 'source')
                self.assertEqual(destination.parent.parent, root)
                self.assertTrue(destination.parent.name.startswith('treatment-source.'))
                self.assertEqual(destination.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual((destination / 'sentinel').read_text(), 'preserved')
                destinations.append(destination)
            self.assertNotEqual(*destinations)
            # mktemp failure must not fall through to extraction or overwrite a source.
            env['OPEN_LAW_LENS_AGENT_WORKSPACE'] = str(root / 'missing workspace')
            result = subprocess.run(['bash', '-c', command], env=env, capture_output=True,
                                    text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(log.read_text().splitlines()), 2)
            for destination in destinations:
                self.assertEqual((destination / 'sentinel').read_text(), 'preserved')
