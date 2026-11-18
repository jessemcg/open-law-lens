"""Private receipt lifecycle and actual installed Pi/Bash/CLI boundary; offline."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from open_law_lens import research_observation as observe

PROJECT = Path(__file__).resolve().parents[1]


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.token = str(uuid.uuid4())
        self.context = self.root / f'pi-run-metrics-v1-{self.token}'
        self.context.mkdir(mode=0o700)
        self.enterContext(patch.dict(os.environ, {'PI_SESSION_ID': 'test-a',
            'PI_RUN_METRICS_SUBPROCESS_V1_test-a': self.token, 'PI_RUN_METRICS_ENABLED': '1',
            'XDG_RUNTIME_DIR': str(self.root)}))

    def test_slots_exclusive_bounded_and_retained_descriptor_never_follows_rename(self):
        a, b = (observe.begin('extract-case') for _ in range(2))
        self.assertEqual(sorted(p.name for p in self.context.iterdir()), ['001', '002'])
        archived_descriptor = self.context / '001'
        archived_descriptor.unlink()
        archived_descriptor.write_text('replacement CANARY')
        a.finish(0)
        self.assertEqual(archived_descriptor.read_text(), 'replacement CANARY')
        for _ in range(50):
            request = b.request('https://www.courtlistener.com/api/rest/v4/search/?q=CANARY', 'GET')
            if request is not None:
                request['attempts'].extend([{'status':503,'outcome':'http_error','ms':3,'retry':'gateway','backoff_ms':11}] * 3)
        b.finish(1)
        raw = (self.context / '002').read_bytes()
        self.assertLessEqual(len(raw), 8192)
        self.assertNotIn(b'CANARY', raw)
        self.assertTrue(json.loads(raw.splitlines()[1])['capped'])
        for _ in range(126):
            observe.begin('lookup-citation').finish(0)
        self.assertIsNone(observe.begin('lookup-citation'))
        self.assertEqual((self.context / 'saturated').read_bytes(), b'')
        self.assertEqual(len(list(self.context.iterdir())), 129)

    def test_missing_wrong_disabled_symlink_and_permissive_contexts_decline(self):
        with patch.dict(os.environ, {'PI_SESSION_ID': 'test-b'}):
            self.assertIsNone(observe.begin('case-search'))
        with patch.dict(os.environ, {'PI_RUN_METRICS_ENABLED': '0'}):
            self.assertIsNone(observe.begin('case-search'))
        with patch.dict(os.environ, {'OPEN_LAW_LENS_STORAGE':'standalone', 'PI_RUN_METRICS_ENABLED':''}):
            self.assertIsNone(observe.begin('case-search'))
        with patch.dict(os.environ, {'PI_RUN_METRICS_SUBPROCESS_V1_test-a': '/tmp/CANARY'}):
            self.assertIsNone(observe.begin('case-search'))
        self.context.chmod(0o755)
        self.assertIsNone(observe.begin('case-search'))
        moved = self.context.with_suffix('.old')
        self.context.rename(moved)
        self.assertIsNone(observe.begin('case-search'))
        moved.chmod(0o700)
        self.context.symlink_to(moved, target_is_directory=True)
        self.assertIsNone(observe.begin('case-search'))
        self.assertEqual(list(moved.iterdir()), [])
        self.context.unlink()
        moved.rename(self.context)
        self.assertIsNone(observe.begin('app'))
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(link)}):
            self.assertIsNone(observe.begin('case-search'))
        with patch.object(observe.os, 'write', side_effect=OSError('CANARY')):
            self.assertIsNone(observe.begin('case-search'))

    def test_unverified_endpoint_never_creates_courtlistener_request(self):
        inv = observe.begin('case-search')
        for url in ['https://www.courtlistener.com.evil.example/api/rest/v4/search/',
                    'https://www.courtlistener.com@evil.example/api/rest/v4/search/',
                    'http://www.courtlistener.com/api/rest/v4/search/',
                    'https://www.courtlistener.com/api/rest/v4/unknown/CANARY']:
            self.assertIsNone(inv.request(url, 'GET'))
        inv.finish(1)
        raw = (self.context / '001').read_text()
        self.assertNotIn('CANARY', raw)
        completion = json.loads(raw.splitlines()[1])
        self.assertEqual(completion['requests'], [])
        self.assertEqual(completion['sources'], {'unverified_request': 4})

    def test_local_overhead_sample_for_command_observation(self):
        samples = {}
        for enabled in ('0', '1'):
            self.context.rename(self.context.with_suffix('.old'))
            self.context.with_suffix('.old').rmdir()
            self.context.mkdir(mode=0o700)
            with patch.dict(os.environ, {'PI_RUN_METRICS_ENABLED': enabled}):
                started = time.perf_counter()
                for _ in range(100):
                    receipt = observe.begin('lookup-citation')
                    if receipt:
                        receipt.source('lookup_library')
                        receipt.finish(0)
                samples[enabled] = (time.perf_counter() - started) * 10
            for p in self.context.iterdir():
                p.unlink()
        print(f'producer loop (100 claims; ms/command): off={samples["0"]:.3f}, on={samples["1"]:.3f}', file=sys.stderr)


class ResearchSDKTests(unittest.TestCase):
    def test_cross_app_real_sdk_real_cli_and_no_model_facing_effect(self):
        collector = Path(os.environ.get('PI_METRICS_TEST_COLLECTOR', PROJECT.parent / 'PiRunMetrics/run-collector.ts'))
        node = shutil.which('node')
        cli = Path(sys.executable).with_name('open-law-lens')
        if not (collector.is_file() and node and cli.is_file()):
            self.skipTest('Requires sibling collector, installed Node/Pi SDK and disposable Open Law Lens project-env')
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        hooks = root / 'hooks'
        hooks.mkdir()
        shutil.copyfile(PROJECT / 'tests/research_fake_service.py', hooks / 'research_fake_service.py')
        (hooks / 'sitecustomize.py').write_text('from research_fake_service import load\nload()\n')
        snapshots, traces = [], []
        cwd = root / 'working'
        cwd.mkdir(mode=0o700)
        for variant in ('enabled', 'disabled', 'missing', 'unwritable-archive', 'unsafe-runtime'):
            work = root / variant
            work.mkdir(mode=0o700)
            runtime = work / 'runtime'
            runtime.mkdir(mode=0o700)
            if variant == 'unsafe-runtime':
                runtime.chmod(0o755)
            request_trace = work / 'trace'
            env = dict(os.environ, PI_RUN_METRICS_ENABLED='0' if variant == 'disabled' else '1',
                PI_RUN_METRICS_ROOT='/dev/null/runs' if variant == 'unwritable-archive' else str(work / 'archive'),
                PI_RUN_METRICS_APP='prose', PI_RUN_METRICS_WORKFLOW='check-citations-document',
                TEST_COLLECTOR=str(collector), TEST_REQUEST_TRACE=str(request_trace), PYTHONPATH=str(hooks),
                OPEN_LAW_LENS_CLI_BIN=str(cli), OPEN_LAW_LENS_STORAGE='standalone',
                XDG_RUNTIME_DIR=str(runtime))
            child = subprocess.run([node, '--experimental-strip-types', PROJECT / 'tests/workflow_observation_sdk.mjs', variant],
                                   cwd=cwd, env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(child.returncode, 0, child.stderr)
            snapshots.append(json.loads((cwd / 'capture.json').read_text()))
            traces.append(sorted(request_trace.read_text().splitlines()))
            self.assertEqual(list(runtime.glob('pi-run-metrics-v1-*')), [])
            archives = sorted((work / 'archive').glob('*/*.jsonl'))
            if variant in {'disabled', 'missing', 'unwritable-archive'}:
                self.assertFalse(archives)
                continue
            self.assertEqual(len(archives), 2)
            if variant == 'unsafe-runtime':
                for path in archives:
                    data = json.loads(path.read_text().splitlines()[1])
                    self.assertEqual(data['subprocess_activity']['context'], 'unavailable')
                    self.assertEqual(data['bash_activity']['calls'], data['tools']['bash']['calls'])
                    self.assertFalse(data['incomplete'])
                continue
            runs = []
            for f in archives:
                raw = f.read_text()
                self.assertNotIn('CANARY', raw)
                start, finish = map(json.loads, raw.splitlines())
                self.assertEqual(start['app'], 'prose')
                self.assertEqual(start['workflow'], 'check-citations-document')
                self.assertEqual(start['run_id'], finish['run_id'])
                self.assertEqual(finish['subprocess_activity']['malformed'], 0)
                self.assertEqual(finish['subprocess_activity']['start_only'], 0)
                runs.append(finish)
            initial = max(runs, key=lambda r: r['tools']['bash']['calls'])
            followup = min(runs, key=lambda r: r['tools']['bash']['calls'])
            self.assertEqual(initial['bash_activity']['calls'], 11)
            shells = initial['bash_activity']['ordered']
            self.assertFalse(shells[0]['repeat'])
            self.assertTrue(shells[1]['repeat'])
            self.assertEqual(shells[-3]['kind'], 'compound')
            self.assertEqual(shells[-3]['exit_code'], 0)
            self.assertEqual(shells[-2]['exit_code'], 7)
            self.assertEqual(shells[-1]['state'], 'error_without_exit')
            self.assertEqual([r['turn'] for r in shells], [0] * 11)
            receipts = initial['subprocess_activity']['ordered']
            self.assertEqual(len(receipts), 8)
            retried = [r['completion'] for r in receipts if any(len(q['attempts']) == 2 for q in r['completion']['requests'])]
            self.assertEqual(len(retried), 2)
            for r in retried:
                q, = r['requests']
                self.assertEqual(q['outcome'], 'ok')
                self.assertEqual([a['status'] for a in q['attempts']], [429, 200])
                self.assertEqual([a['retry'] for a in q['attempts']], ['throttle', None])
                self.assertEqual(r['pages'], [{'mode':'semantic','page':'first','received':2,'delivered':1,
                                              'exclusions':{'court_out_of_scope':1}}])
            data = [r['completion'] for r in receipts]
            self.assertTrue(any(r['pages'] and r['pages'][0]['received'] == 1 and r['pages'][0]['delivered'] == 0 for r in data))
            cached, = [r['completion'] for r in receipts if r['operation'] == 'lookup-citation']
            self.assertEqual(cached['requests'], [])
            self.assertEqual(cached['sources'], {'lookup_library':1})
            self.assertEqual(cached['yield']['clusters'], 0)
            extracted, = [r['completion'] for r in receipts if r['operation'] == 'extract-case']
            self.assertEqual([q['family'] for q in extracted['requests']], ['cluster','opinion'])
            self.assertTrue(extracted['yield']['baseline_text'])
            self.assertEqual(extracted['yield']['matches'], 0)
            self.assertEqual(extracted['yield']['unmatched_queries'], 1)
            self.assertEqual(sorted(q['outcome'] for r in data for q in r['requests'] if q['outcome'] != 'ok'),
                             ['decode', 'http_error', 'shape'])
            self.assertTrue(any(len(q['attempts']) == 3 for r in data for q in r['requests']))
            later, = followup['subprocess_activity']['ordered']
            self.assertEqual(later['completion']['pages'][0]['received'], 0)
            # Consume the actual SDK archive at the project boundary as well.
            report = subprocess.run([sys.executable, collector.with_name('analyze_runs.py'),
                '--app', 'prose', '--root', work / 'archive'], cwd=work,
                env={k: v for k, v in env.items() if k != 'PYTHONPATH'}, capture_output=True, text=True,
                timeout=20, check=True)
            md_path, json_path = map(Path, report.stdout.splitlines())
            self.assertNotIn('CANARY', md_path.read_text())
            summary = json.loads(json_path.read_text())
            self.assertNotIn('CANARY', json.dumps(summary))
            cohort, = summary['cohorts']
            self.assertEqual(cohort['current']['bash_activity']['eligible_calls'], 12)
            self.assertEqual(cohort['current']['courtlistener_activity']['rates']['http_429'], {'numerator':2,'denominator':13})
            self.assertEqual(cohort['current']['courtlistener_activity']['rates']['locally_served_lookups'], {'numerator':1,'denominator':1})
        for snapshot, trace in zip(snapshots[1:], traces[1:], strict=True):
            self.assertEqual(snapshots[0], snapshot)
            self.assertEqual(traces[0], trace)
        self.assertEqual(traces[0].count('429'), 2)
        self.assertEqual(traces[0].count('503'), 3)
        self.assertEqual(sum(x.startswith('sleep:') for x in traces[0]), 4)
