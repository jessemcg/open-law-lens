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
from open_law_lens.config import load_config, save_config
from open_law_lens.cli import _cmd_search_briefs, _cmd_extract_brief
from open_law_lens.prior_briefs import PriorBriefSearchPage, PriorBriefSearchResult

PROJECT = Path(__file__).resolve().parents[1]


def instructions():
    return ' '.join((PROJECT / '.pi/skills/prior-briefs/SKILL.md').read_text().split())


class PriorBriefQualityTests(unittest.TestCase):
    def test_historical_defaults_and_customizations_are_opaque_and_read_only(self):
        for fixture in ('prior_brief_prompt_previous.txt', 'prior_brief_prompt_pre_artifacts.txt',
                        'prior_brief_prompt_pre_lookup.txt'):
            previous = (Path(__file__).with_name('fixtures') / fixture).read_text()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.json'
                for prefix in (AGENT_CLI_COMMAND_PREFIX, 'uv run open-law-lens', 'uv run --no-sync open-law-lens'):
                    for suffix in ('', '\nCustom instruction: rank by my issue.'):
                        retired = previous.replace('$OLL', prefix) + suffix
                        raw = {'brief_agent_prompt_template': retired,
                               'agent_runtime_profiles_version': 2,
                               'agent_runtime_profiles': {'prior_briefs': {
                                   'provider': 'fireworks', 'model': 'unchanged', 'thinking': 'high'}}}
                        path.write_text(json.dumps(raw))
                        before = path.read_bytes()
                        result = load_config(path)
                        self.assertEqual(result.retired_prompt_settings['brief_agent_prompt_template'], retired)
                        self.assertEqual(path.read_bytes(), before)
                        save_config(result, path)
                        self.assertEqual(json.loads(path.read_text())['brief_agent_prompt_template'], retired)
                        profile = result.agent_runtime_profiles['prior_briefs']
                        self.assertEqual((profile.provider, profile.model, profile.thinking), ('fireworks', 'unchanged', 'high'))

    def test_lookup_contract_is_distinct_from_comparison_and_keeps_verification(self):
        prompt = instructions()
        lookup = prompt.split('## Document lookup', 1)[1].split('## Research or comparison', 1)[0]
        for text in (
            '--match all --limit 5 --sort newest',
            "Match the substance of the argument, not the user's exact wording",
            'Resolve plausible newer candidates before selecting an older one',
            'at most one or two targeted refinements for a concrete gap',
            'Stop when the requested document is verified',
            'Return one linked title, document type/date',
            'No ranked list, supporting or contrasting briefs',
            'Do not read or compare the selected current-case fact pattern merely',
            'dates are tied or genuinely unresolved', 'file-date fallback',
            'initial inquiry versus further inquiry', 'No directory listings', 'Do not inspect SQL',
        ):
            self.assertIn(text, lookup)
        self.assertIn('Follow-ups may change the requested task within the original', prompt)
        shared = prompt.split('## Source verification and answer rules (both scopes)', 1)[1]
        for text in ('read EVERY part in manifest order until EOF',
                     'single-result answer rule above takes precedence',
                     'A lookup does not require a quote', 'For research or comparison only',
                     'open-law-lens://prior-brief/<brief_id>'):
            self.assertIn(text, shared)

    def test_prompt_contracts(self):
        prompt = instructions()
        for text in ('until EOF', 'grep is navigation', 'disposable agent workspace only',
                     '--output-dir', 'read EVERY part in manifest order', '32 KiB UTF-8',
                     'Chunk numbers are not legal pinpoints', 'Fetch each selected document once',
                     'strongest directly relevant brief first', 'the opening brief argues',
                     'nondependent-person eligibility', 'has_more: false', 'two to ten words (2–10)',
                     'never insert brackets', 'Do not browse the web', 'file-date fallback',
                     'current-case factual context explicitly selected'):
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
