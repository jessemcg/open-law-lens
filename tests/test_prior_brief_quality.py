"""Static contracts only: these tests do not establish model compliance."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.agent_commands import AGENT_CLI_COMMAND_PREFIX
from open_law_lens.config import DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE, load_config
from open_law_lens.cli import _cmd_search_briefs, _cmd_extract_brief
from open_law_lens.prior_briefs import PriorBriefSearchPage, PriorBriefSearchResult


class PriorBriefQualityTests(unittest.TestCase):
    def test_exact_defaults_upgrade_read_only_and_customizations_survive(self):
        previous = Path(__file__).with_name('fixtures').joinpath(
            'prior_brief_prompt_previous.txt').read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            for prefix in (AGENT_CLI_COMMAND_PREFIX, 'uv run open-law-lens',
                           'uv run --no-sync open-law-lens'):
                for words in ('two to ten words', 'two to five words'):
                    old = previous.replace('$OLL', prefix).replace('two to ten words', words)
                    for suffix in ('', '\nCustom instruction: rank by my issue.'):
                        raw = {'brief_agent_prompt_template': old + suffix,
                               'agent_runtime_profiles_version': 2,
                               'agent_runtime_profiles': {'prior_briefs': {
                                   'provider': 'fireworks', 'model': 'unchanged',
                                   'thinking': 'high'}}}
                        path.write_text(json.dumps(raw))
                        before = path.read_bytes()
                        result = load_config(path)
                        expected = (previous.replace('$OLL', AGENT_CLI_COMMAND_PREFIX)
                                    .replace('two to ten words', words) + suffix
                                    if suffix or words == 'two to five words'
                                    else DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE)
                        self.assertEqual(result.brief_agent_prompt_template, expected)
                        self.assertEqual(path.read_bytes(), before)
                        profile = result.agent_runtime_profiles['prior_briefs']
                        self.assertEqual((profile.provider, profile.model, profile.thinking),
                                         ('fireworks', 'unchanged', 'high'))

    def test_prompt_contracts(self):
        prompt = DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE.format(
            question='Synthetic question', brief_database='/tmp/synthetic.sqlite3', brief_count=5)
        for text in ('until EOF', 'grep is navigation', 'disposable agent workspace only',
                     'strongest directly relevant brief first', 'the opening brief argues',
                     'nondependent-person eligibility', 'has_more: false',
                     'never insert brackets', 'Do not browse the web',
                     'file-date fallback', 'current-case factual context explicitly selected'):
            self.assertIn(text, prompt)

    def test_cli_page_keeps_metadata_and_errors(self):
        result = PriorBriefSearchResult('full-unshortened-id', 'Synthetic opening',
            'B000001', 'opening_brief', '2026-01-01', 'file_mtime', 'synthetic.odt',
            'snippet', 'open-law-lens://prior-brief/full-unshortened-id')
        args = argparse.Namespace(query='synthetic', match='all', sort='newest', limit=1)
        with patch('open_law_lens.cli.PriorBriefLibrary.default') as factory:
            factory.return_value.search_page.return_value = PriorBriefSearchPage([result], 1, True)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(_cmd_search_briefs(args), 0)
            payload = json.loads(output.getvalue())
            self.assertEqual((payload['count'], payload['limit'], payload['has_more']), (1, 1, True))
            self.assertEqual(payload['results'], [result.to_json()])
            factory.return_value.search_page.side_effect = RuntimeError('synthetic search failure')
            with self.assertRaisesRegex(RuntimeError, 'synthetic search failure'):
                _cmd_search_briefs(args)
            factory.return_value.read.return_value = None
            with redirect_stderr(io.StringIO()):
                self.assertEqual(_cmd_extract_brief(argparse.Namespace(brief_id='missing', text=True)), 1)
