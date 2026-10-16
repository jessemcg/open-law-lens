"""Assembled research contracts; no real settings, network, desktop, or models."""
from pathlib import Path
import unittest

from open_law_lens.cli_commands import CLI_COMMANDS
from test_workflow_skills import assembled

PROJECT = Path(__file__).resolve().parents[1]


class ResearchExecutionContractTests(unittest.TestCase):
    def test_assembled_bounds_without_weakening_routes(self):
        for workflow in ('law', 'assess_argument', 'subsequent_treatment'):
            text = ' '.join(assembled(workflow).split())
            for phrase in (
                'timeout: 180', '--recover-official --timeout 120 --progress',
                'complete JSON stdout and separate stderr', 'One attempt per authority across',
                'suspend further Scholar attempts for this run', 'not semantic question answering',
                'query_accounting', 'pinpoint_status', 'resolved_input', 'identifier',
                'Never use Computer Use', 'mandatory enactment-plus-case route',
                'at least one leading published California case',
            ):
                self.assertIn(phrase, text)
        treatment = ' '.join(assembled('subsequent_treatment').split())
        self.assertIn('Do not retry network timeouts', treatment)
        self.assertIn('Never use generic web search, Pi `web_search`', treatment)
        shared = (PROJECT / '.pi/skills/legal-researcher/SKILL.md').read_text()
        self.assertNotIn('Run at most two non-paginated', shared)
        self.assertIn("workflow skill's discovery ceiling", ' '.join(shared.split()))

    def test_system_has_no_obsolete_browser_permission(self):
        text = ' '.join((PROJECT / '.pi/SYSTEM.md').read_text().split())
        self.assertIn('No desktop-control tools or browser-recovery bridge', text)
        self.assertNotIn('Desktop-control tools are available', text)
        self.assertIn('save complete Open Law Lens JSON', text)
        self.assertIn('Closed-corpus modes remain closed', text)

    def test_cli_catalog_advertises_bounded_recovery(self):
        command = next(c for c in CLI_COMMANDS if c.name == 'extract-case')
        self.assertIn('--timeout 120 --progress', command.example)
        self.assertIn('not semantic questions', command.description)
        self.assertIn('separate from stderr', command.description)
