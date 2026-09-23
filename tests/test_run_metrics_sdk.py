"""Offline production-wrapper/SDK/session-transport acceptance; synthetic data only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from open_law_lens.agent import extract_latest_pi_final_answer_from_jsonl
import test_agent_vte_wrapper as wrapper_tests

PROJECT = Path(__file__).resolve().parents[1]


class RunMetricsSDKTests(unittest.TestCase):
    def test_all_workflows_metrics_and_answer_transport_are_passive(self):
        node = shutil.which('node')
        collector = Path(os.environ.get('PI_METRICS_TEST_COLLECTOR', PROJECT.parent / 'PiRunMetrics/run-collector.ts'))
        if not node or not collector.is_file():
            self.skipTest('Installed Node and sibling PiRunMetrics required for offline SDK acceptance')
        helper = wrapper_tests.AgentVteWrapperTests()
        for mode, workflow in [('general', 'law'), ('case', 'research_cache'), ('brief', 'prior_briefs'),
                               ('appeal', 'assess_argument'), ('general', 'subsequent_treatment')]:
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                project, workspace, prompt = helper._fixture(root)
                if mode in {'general', 'appeal'}:
                    web = helper._install_web_access(root)
                    (web / 'index.ts').write_text('export default function(pi) { pi.registerTool({name:"web_search", label:"Synthetic web", description:"Synthetic", parameters:{type:"object",properties:{}}, execute:async()=>({content:[],details:{}})}); }')
                    helper._install_computer_use(root)
                executable = root / 'synthetic-pi.mjs'
                shutil.copyfile(PROJECT / 'tests/metrics_sdk_fixture.mjs', executable)
                executable.chmod(0o700)
                env = dict(os.environ, OPEN_LAW_LENS_AGENT_PROMPT_FILE=str(prompt),
                           OPEN_LAW_LENS_AGENT_WORKSPACE=str(workspace), OPEN_LAW_LENS_AGENT_MODE=mode,
                           OPEN_LAW_LENS_AGENT_PROFILE_KEY=workflow, OPEN_LAW_LENS_PROJECT_DIR=str(project),
                           OPEN_LAW_LENS_PI_BIN=str(executable), OPEN_LAW_LENS_PI_NODE_BIN=node,
                           PI_CODING_AGENT_DIR=str(root / 'pi-agent'), PI_RUN_METRICS_COLLECTOR=str(collector))
                env.pop('PI_RUN_METRICS_ROOT', None)
                captures = []
                for variant in ('enabled', 'disabled', 'missing', 'unwritable'):
                    capture = root / f'capture-{variant}.json'
                    env.pop('PI_RUN_METRICS_ROOT', None)
                    env.update(PI_RUN_METRICS_ENABLED='0' if variant == 'disabled' else '1',
                               PI_RUN_METRICS_COLLECTOR=str(root / 'missing.ts') if variant == 'missing' else str(collector),
                               PI_METRICS_TEST_CAPTURE=str(capture))
                    if variant == 'unwritable':
                        env['PI_RUN_METRICS_ROOT'] = '/dev/null/runs'
                    result = subprocess.run(['bash', str(wrapper_tests.WRAPPER)], env=env,
                                            capture_output=True, text=True, timeout=45)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if variant in {'missing', 'unwritable'}:
                        self.assertIn('Pi run metrics:', result.stderr)
                    data = json.loads(capture.read_text())
                    self.assertEqual(extract_latest_pi_final_answer_from_jsonl(Path(data['session_file'])), data['answer'])
                    data.pop('session_file')
                    captures.append(data)
                for capture in captures[1:]:
                    self.assertEqual(captures[0], capture)
                expected_tools = {'read', 'bash', 'grep', 'find', 'ls'}
                if mode in {'general', 'appeal'}:
                    expected_tools.add('web_search')
                self.assertEqual(set(captures[0]['tools']), expected_tools)
                archive = project / '.run-metrics/runs'
                files = list(archive.glob('*/*.jsonl'))
                self.assertEqual(len(files), 2)
                records = []
                for path in files:
                    text = path.read_text()
                    self.assertNotIn('CANARY', text)
                    self.assertNotIn('synthetic.txt', text)
                    start, end = map(json.loads, text.splitlines())
                    self.assertEqual(start['run_id'], end['run_id'])
                    self.assertEqual(end['workflow'], workflow)
                    self.assertEqual(end['app'], 'open-law-lens')
                    self.assertEqual(end['outcome'], 'completed')
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                    records.append(end)
                first = next(r for r in records if r['cycles'] == 2)
                self.assertEqual(first['assistant_responses'], 3)
                self.assertEqual(first['usage_total']['input'], 33)
                self.assertEqual(first['tools']['read']['calls'], 1)
                self.assertEqual(first['tools']['read']['result_bytes'], len('CANARY synthetic tool result é'.encode()))
                self.assertEqual({r['cycles'] for r in records}, {1, 2})
                self.assertEqual(archive.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
