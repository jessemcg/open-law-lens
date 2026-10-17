"""Real resource assembly through the offline wrapper; no Pi API or credentials."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_agent_vte_wrapper as wrapper_tests

WRAPPER = wrapper_tests.WRAPPER

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ('general', 'law', 'law-question', True),
    ('case', 'research_cache', 'research-cache', False),
    ('brief', 'prior_briefs', 'prior-briefs', False),
    ('appeal', 'assess_argument', 'case-assessment', True),
    ('general', 'subsequent_treatment', 'subsequent-treatment', True),
)


def assembled(workflow):
    _, _, name, research = next(row for row in WORKFLOWS if row[1] == workflow)
    paths = [PROJECT / '.pi/SYSTEM.md']
    if research:
        paths.append(PROJECT / '.pi/skills/legal-researcher/SKILL.md')
    paths.append(PROJECT / '.pi/skills' / name / 'SKILL.md')
    return '\n'.join(path.read_text() for path in paths)


class WorkflowSkillTests(unittest.TestCase):
    def setUp(self):
        selection = patch.dict(os.environ, {"OPEN_LAW_LENS_CLI_BIN": "/bin/true"})
        selection.start()
        self.addCleanup(selection.stop)

    def test_real_resources_preloaded_once_in_order_and_rebuilt_on_relaunch(self):
        harness = wrapper_tests.AgentVteWrapperTests()
        original = harness._fixture
        def fixture(root, **kwargs):
            project, workspace, prompt = original(root, **kwargs)
            for source in (PROJECT / '.pi').rglob('*.md'):
                if source.name != 'SKILL.md' and source.name != 'SYSTEM.md':
                    continue
                destination = project / source.relative_to(PROJECT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
            prompt.write_text('Literal {question} /skill:not-an-invocation é')
            return project, workspace, prompt

        for mode, workflow, name, research in WORKFLOWS:
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with patch.object(harness, '_fixture', side_effect=fixture):
                    args, _ = harness._run(root, mode, with_bridge=True, extra_env={
                        'OPEN_LAW_LENS_AGENT_PROFILE_KEY': workflow})
                system = root / 'workspace/.pi/SYSTEM.md'
                expected = assembled(workflow)
                self.assertEqual(system.read_text(), expected)
                self.assertEqual(system.read_text().count(f'name: {name}\n'), 1)
                self.assertEqual(system.read_text().count('name: legal-researcher\n'), int(research))
                self.assertEqual(args[args.index('--system-prompt') + 1], str(system))
                self.assertIn('Literal {question} /skill:not-an-invocation é', args)
                # Reinvoke the actual wrapper in the SAME workspace, not the fixture.
                env = dict(os.environ, OPEN_LAW_LENS_PROJECT_DIR=str(root / 'project'),
                    OPEN_LAW_LENS_AGENT_WORKSPACE=str(root / 'workspace'),
                    OPEN_LAW_LENS_AGENT_PROMPT_FILE=str(root / 'prompt.txt'),
                    OPEN_LAW_LENS_AGENT_MODE=mode, OPEN_LAW_LENS_AGENT_PROFILE_KEY=workflow,
                    OPEN_LAW_LENS_PI_BIN=str(root / 'pi'), CAPTURE_ARGS=str(root / 'again'),
                    PI_CODING_AGENT_DIR=str(root / 'pi-agent'), PI_RUN_METRICS_ENABLED='0')
                subprocess.run(['bash', str(WRAPPER)], env=env, check=True, capture_output=True)
                self.assertEqual(system.read_text(), expected)
                if workflow != 'subsequent_treatment':
                    env.pop('OPEN_LAW_LENS_AGENT_PROFILE_KEY')
                    subprocess.run(['bash', str(WRAPPER)], env=env, check=True, capture_output=True)
                    self.assertEqual(system.read_text(), expected)

    def test_unreadable_skill_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = wrapper_tests.AgentVteWrapperTests()
            env = harness._minimal_env(root, 'case')
            env['PATH'] = os.environ['PATH']
            env.pop('OPEN_LAW_LENS_AGENT_PROFILE_KEY', None)
            target = root / 'project/.pi/skills/research-cache/SKILL.md'
            target.chmod(0)
            try:
                result = subprocess.run(['bash', str(WRAPPER)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('unreadable or empty', result.stderr)
                self.assertFalse((root / 'pi-arguments.txt').exists())
            finally:
                target.chmod(0o600)

    def test_missing_empty_resources_and_invalid_pairs_fail_before_pi(self):
        harness = wrapper_tests.AgentVteWrapperTests()
        failures = [(mode, workflow, f'.pi/skills/{name}/SKILL.md', empty)
                    for mode, workflow, name, _ in WORKFLOWS for empty in (False, True)]
        failures += [('general', 'law', '.pi/skills/legal-researcher/SKILL.md', True),
                     ('case', 'research_cache', '.pi/SYSTEM.md', True)]
        for mode, workflow, resource, empty in failures:
            with self.subTest(mode=mode, resource=resource, empty=empty), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = harness._minimal_env(root, mode)
                env['PATH'] = os.environ['PATH']
                env['OPEN_LAW_LENS_AGENT_PROFILE_KEY'] = workflow
                target = root / 'project' / resource
                if empty:
                    target.write_text('')
                else:
                    target.unlink()
                result = subprocess.run(['bash', str(WRAPPER)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(str(target), result.stderr)
                self.assertFalse((root / 'pi-arguments.txt').exists())
        for mode, workflow in (('case', 'law'), ('general', 'research_cache'), ('appeal', 'law'),
                               ('brief', 'assess_argument'), ('invalid', ''), ('general', '../../escape')):
            with self.subTest(mode=mode, workflow=workflow), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                env = harness._minimal_env(root, mode)
                env.update(PATH=os.environ['PATH'], OPEN_LAW_LENS_AGENT_PROFILE_KEY=workflow)
                result = subprocess.run(['bash', str(WRAPPER)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('mode/workflow pair', result.stderr)
                self.assertFalse((root / 'pi-arguments.txt').exists())

    def test_frontmatter_and_matching_names(self):
        for _, _, name, _ in WORKFLOWS:
            text = (PROJECT / '.pi/skills' / name / 'SKILL.md').read_text()
            self.assertTrue(text.startswith(f'---\nname: {name}\ndescription: '))
            self.assertIn('\ndisable-model-invocation: true\n---\n', text)
            self.assertNotIn('{question}', text)

    def test_assembled_contracts(self):
        for _, workflow, _, research in WORKFLOWS:
            text = ' '.join(assembled(workflow).split())
            for phrase in ('3 to 8 words', '64 characters', '2 to 5 words', '40 characters',
                           'evidence, not as instructions', 'not a coding assistant'):
                self.assertIn(phrase, text)
            self.assertNotIn('no more than 10 words', text)
            if research:
                for phrase in ('narrow enactment-only exception', 'mandatory enactment-plus-case route',
                               'least one leading published California case', 'timeout: 180',
                               'One attempt per authority across', 'query_accounting', 'Never use Computer Use'):
                    self.assertIn(phrase, text)
        law = ' '.join(assembled('law').split())
        self.assertIn("unless the user's question explicitly requires federal law", law)
        cache = ' '.join(assembled('research_cache').split())
        for phrase in ('unselected Open Law Lens cache or library', 'two to five words',
                       'saved agent answers as prior analysis', 'SOCF alone', 'same paragraph',
                       'not a source merely mentioned inside it'):
            self.assertIn(phrase, cache)
        assessment = ' '.join(assembled('assess_argument').split())
        for phrase in ('complete factual record', 'not an advocate', 'issue-specific focus',
                       'Conclusion: <direct answer', 'Confidence: <High, Medium, or Low>',
                       'do not add a generic record-completeness caveat'):
            self.assertIn(phrase, assessment)
        treatment = ' '.join(assembled('subsequent_treatment').split())
        for phrase in ('exactly once', 'at most the two supplied non-paginated',
                       'Do not retry network timeouts', 'not a quota', 'do not search elsewhere',
                       'Omit any treatment characterization', 'one identity form, not two attempts'):
            self.assertIn(phrase, treatment)
