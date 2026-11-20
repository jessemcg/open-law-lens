"""Real resource assembly through the offline wrapper; no Pi API or credentials."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.agent import export_selected_authorities
from open_law_lens.agent_prompts import cache_request
from open_law_lens.fact_patterns import export_fact_pattern
from test_agent import DummyClient
import test_agent_vte_wrapper as wrapper_tests

WRAPPER = wrapper_tests.WRAPPER

PROJECT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ('general', 'law', 'law-question', True),
    ('case', 'research_cache', 'research-cache', False),
    ('brief', 'prior_briefs', 'prior-briefs', False),
    ('appeal', 'assess_argument', 'case-assessment', True),
    ('general', 'subsequent_treatment', 'subsequent-treatment', True),
    ('general', 'prep_reply', 'brief-prep', True),
    ('general', 'prep_respondent', 'brief-prep', True),
    ('general', 'prep_opposition', 'brief-prep', True),
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

    def assert_shared_legal_style(self, system):
        self.assertEqual(system.splitlines().count('## Legal writing and citations'), 1)
        text = ' '.join(system.split())
        for rule in (
            'Put one terminal period inside the outer closing parenthesis, after '
            'any bracketed explanation, and none after the parenthesis.',
            'Instead of: `The clerk reported that notice was mailed '
            '(CT 18, 20-21; but see RT 44 [counsel disputed the date]).`',
            'Write: `The clerk reported that notice was mailed. '
            '(CT 18, 20–21; but see RT 44 [counsel disputed the date].)`',
            '`The petition alleged a violation of section 300, subdivision (b)(1).`',
        ):
            self.assertEqual(text.count(rule), 1, rule)

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
                delivered = system.read_text(encoding='utf-8')
                self.assertEqual(delivered, expected)
                self.assert_shared_legal_style(delivered)
                self.assertEqual(delivered.count(f'name: {name}\n'), 1)
                self.assertEqual(delivered.count('name: legal-researcher\n'), int(research))
                self.assertEqual(args[args.index('--system-prompt') + 1], str(system))
                self.assertIn('Literal {question} /skill:not-an-invocation é', args)
                self.assertEqual(args[args.index('--tools') + 1], 'read,bash,grep,find,ls')
                self.assertIn('--no-extensions', args)
                # Required instructions are preloaded, independent of global slash-command policy.
                agent = root / 'pi-agent'
                agent.mkdir(exist_ok=True)
                (agent / 'settings.json').write_text('{"enableSkillCommands":false}')
                # Reinvoke the actual wrapper in the SAME workspace, not the fixture.
                env = dict(os.environ, OPEN_LAW_LENS_PROJECT_DIR=str(root / 'project'),
                    OPEN_LAW_LENS_AGENT_WORKSPACE=str(root / 'workspace'),
                    OPEN_LAW_LENS_AGENT_PROMPT_FILE=str(root / 'prompt.txt'),
                    OPEN_LAW_LENS_AGENT_MODE=mode, OPEN_LAW_LENS_AGENT_PROFILE_KEY=workflow,
                    OPEN_LAW_LENS_PI_BIN=str(root / 'pi'), CAPTURE_ARGS=str(root / 'again'),
                    PI_CODING_AGENT_DIR=str(root / 'pi-agent'), PI_RUN_METRICS_ENABLED='0')
                subprocess.run(['bash', str(WRAPPER)], env=env, check=True, capture_output=True)
                delivered = system.read_text(encoding='utf-8')
                self.assertEqual(delivered, expected)
                self.assert_shared_legal_style(delivered)
                self.assertEqual((agent / 'settings.json').read_text(), '{"enableSkillCommands":false}')
                if workflow != 'subsequent_treatment' and not workflow.startswith('prep_'):
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
        briefs = ' '.join(assembled('prior_briefs').split())
        for phrase in ('exact Markdown link returned by search',
                       'two to ten words (2–10), copied as exact continuous phrases'):
            self.assertIn(phrase, briefs)
        treatment = ' '.join(assembled('subsequent_treatment').split())
        for phrase in ('exactly once', 'at most the two supplied non-paginated',
                       'Do not retry network timeouts', 'not a quota', 'do not search elsewhere',
                       'Omit any treatment characterization', 'one identity form, not two attempts'):
            self.assertIn(phrase, treatment)

    def test_case_question_flexible_body_preserves_bench_memo_contract(self):
        prompt = assembled('assess_argument')
        text = ' '.join(prompt.split())
        for phrase in (
            'complete factual record', 'not an advocate', 'issue-specific focus',
            'do not add a generic record-completeness caveat',
            'strongest material reasoning supporting each possible answer',
            'use the traditional bench-memorandum sections when useful',
            'choose issue-specific headings or answer a narrow question in a few paragraphs without headings',
            'End the answer with these two lines exactly in this form:',
            '(CT 335–343.)', '(RT 22–34; CRT 17–22; CT 295–301.)',
        ):
            self.assertIn(phrase, text)
        self.assertIn('\n# Specific Issue Title\n*Short disposition*\n', prompt)
        self.assertIn(
            '\nConclusion: <direct answer to the legal question>\n'
            'Confidence: <High, Medium, or Low> — <brief basis tied to the law and record>\n',
            prompt,
        )

    def test_law_followup_reuses_inspected_evidence_but_fills_specific_gaps(self):
        law = ' '.join(assembled('law').split())
        # "Put that in one paragraph" versus "Does the later amendment change that?"
        for phrase in (
            'answer the new question, not the entire previous memo',
            'reuse directly inspected passages still available in this session',
            'when they support the answer',
            'Do not repeat discovery just because a new turn began',
            'A previous assistant assertion or search snippet is not verified evidence',
            'new proposition, changed date, material objection, or passage no longer available',
            'use Legal Researcher to fill that specific gap',
            'published-case requirement for doctrinal conclusions',
            'qualified fallback if bounded research cannot verify a case',
            'confine the answer to the extracted enactment',
        ):
            self.assertIn(phrase, law)
        for _, workflow, _, _ in WORKFLOWS:
            if workflow != 'law':
                self.assertNotIn('answer the new question', assembled(workflow))

    def test_cache_navigation_cue_keeps_source_inspection_and_corpus_boundaries(self):
        cache = ' '.join(assembled('research_cache').split())
        for phrase in (
            "manifest's `text_path` entries",
            'For a question only about the current-case facts, use the supplied extracted factual-text path directly',
            'verify quotations in the source text itself',
            'Skip the manifest if the needed evidence is already available',
            'a targeted lookup within the declared selected export is allowed',
            'qualify any material gap; do not broaden the corpus',
            'Do not use web browsing or unselected Open Law Lens cache or library materials',
        ):
            self.assertIn(phrase, cache)

    def test_cache_request_locates_selected_sources_and_facts_without_a_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = export_selected_authorities(
                DummyClient(), [{'id': 42, 'case_name': 'Example v. State'}],
                [{'statute_id': 'TEST:1', 'citation': 'Test Code, § 1',
                  'text': 'Notice must be given.'}], [], root / 'selected',
            )
            request = cache_request('What do the selected sources say about risk and notice?', selected)
            manifest_path = request.split('Selected authority manifest:\n', 1)[1].splitlines()[0]
            manifest = json.loads(Path(manifest_path).read_text())
            opinion = Path(manifest['cases'][0]['opinions'][0]['text_path'])
            statute = Path(manifest['statutes'][0]['text_path'])
            self.assertEqual(opinion.parent, selected.case_dir)
            self.assertEqual(statute.parent, selected.case_dir)
            self.assertIn('active risk today', opinion.read_text())
            self.assertIn('Notice must be given.', statute.read_text())
            # If a listed path fails, another selected file is still usable;
            # the manifest is not a substitute for the missing source's text.
            opinion.unlink()
            self.assertFalse(opinion.exists())
            self.assertNotIn('active risk today', json.dumps(manifest))
            self.assertIn('Notice must be given.', statute.read_text())

            fact_source = root / 'facts.odt'
            fact_source.touch()
            with patch('open_law_lens.fact_patterns.extract_fact_pattern_text',
                       return_value='The hearing occurred on Monday.'):
                facts = export_fact_pattern(fact_source, root / 'factual_context')
            empty = export_selected_authorities(DummyClient(), [], [], [], root / 'empty')
            facts_only = cache_request('When was the hearing?', empty, facts, True)
            self.assertIn('Selected authority count: 0', facts_only)
            text_path = facts_only.split('Extracted fact-pattern text: ', 1)[1].splitlines()[0]
            self.assertEqual(Path(text_path).read_text(), 'The hearing occurred on Monday.\n')

    def test_treatment_lossless_transport_and_optional_failure_contract(self):
        treatment = ' '.join(assembled('subsequent_treatment').split())
        for phrase in ('at most one ordinary `full_extract_command`',
                       'previously nonexistent `source` child',
                       'metadata and manifest paths', 'lossless source-part paths',
                       'surrounding qualifications under the shared source-inspection rules',
                       'Reuse an already inspected artifact when sufficient',
                       'directory creation, export, or subsequent artifact reading fails',
                       'preserve useful compact baselines',
                       'Answer the supported portion with the specific inspection limitation',
                       'do not restart discovery or official-copy recovery',
                       'Do not characterize treatment the inspected text does not support'):
            self.assertIn(phrase, treatment)

    def test_simple_definition_is_proportionate_without_weakening_research(self):
        for workflow in ('law', 'assess_argument', 'subsequent_treatment'):
            with self.subTest(workflow=workflow):
                text = ' '.join(assembled(workflow).split())
                self.assertNotRegex(text, r'350\s*(?:to|[–-])\s*650')
                for phrase in ('lead with a short direct definition',
                               'statutory routes and qualifications material to that question',
                               'with the required source support',
                               'expand when the question or a material distinction requires it',
                               'Do not pad the answer to a word target',
                               'Concision must not remove a decisive exception, contrary authority, or uncertainty',
                               'mandatory enactment-plus-case route',
                               'least one leading published California case',
                               'One attempt per authority across',
                               'exact, continuous text verified in the source'):
                    self.assertIn(phrase, text)
