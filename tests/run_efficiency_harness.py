"""Offline synthetic stage measurements, not research/answer-quality telemetry.

Run with managed project Python; --source permits the same harness on an archived
baseline. No settings, credentials, production data, networks or models are read.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
sys.path.insert(0, str(args.source))
from open_law_lens import agent, authority_resolver
from open_law_lens.case_suggestions import case_suggestions_from_library
from open_law_lens.library import CaseLibrary

results = {}
with tempfile.TemporaryDirectory(prefix='oll-stages-') as directory:
    root = Path(directory)
    for size in (0, 20, 200):
        library = CaseLibrary(root / f'{size}.sqlite3')
        library.ensure()
        for index in range(size):
            ident = index + 1
            library.upsert_cluster({'id': ident, 'case_name': f'Synthetic {ident} v. State',
                                    'date_filed': '2024-01-01', 'citations': [
                                        {'volume': str(ident), 'reporter': 'Cal.5th', 'page': '1'}]})
            library.upsert_opinion({'id': ident, 'cluster_id': ident,
                                   'plain_text': '[*1] Synthetic paragraph.\n\n[*2] Late exception.'})
            library.update_case_opinion_ids(str(ident), [str(ident)])
        sql = []
        original = library.connection
        @contextmanager
        def traced():
            with original() as conn:
                conn.set_trace_callback(sql.append)
                yield conn
        library.connection = traced
        concordance = root / 'absent.sdi'
        started = time.perf_counter()
        with patch.object(authority_resolver, 'concordance_file_path', return_value=concordance):
            authority_resolver.resolve_case_input('1 Cal.5th 1', SimpleNamespace(library=library))
        results[f'citation_{size}'] = {'ms': (time.perf_counter() - started) * 1000,
                                     'sql': len(sql), 'updates': sum(s.startswith('UPDATE') for s in sql)}
        sql.clear()
        started = time.perf_counter()
        suggestions = case_suggestions_from_library(library)
        results[f'suggestions_{size}'] = {'ms': (time.perf_counter() - started) * 1000,
                                        'candidates': len(suggestions), 'sql': len(sql),
                                        'updates': sum(s.startswith('UPDATE') for s in sql)}
    path = root / 'session.jsonl'
    answer = 'Synthetic ' * 1_000_000
    path.write_text(json.dumps({'type': 'message', 'message': {
        'role': 'assistant', 'stopReason': 'stop', 'content': answer}}) + '\n')
    counts = {'reads': 0, 'parses': 0}
    original_read = Path.read_text
    original_open = Path.open
    original_loads = json.loads
    def read(p, *a, **kw):
        if p == path:
            counts['reads'] += 1
        return original_read(p, *a, **kw)
    def opened(p, *a, **kw):
        if p == path and hasattr(agent, 'PiSessionSnapshotCache'):
            counts['reads'] += 1
        return original_open(p, *a, **kw)
    def loads(*a, **kw):
        counts['parses'] += 1
        return original_loads(*a, **kw)
    cache = agent.PiSessionSnapshotCache() if hasattr(agent, 'PiSessionSnapshotCache') else None
    def poll():
        if cache:
            cache.read(path)
        else:
            agent.extract_latest_pi_final_answer_from_jsonl(path)
            agent.count_pi_final_answers_from_jsonl(path)
    with patch.object(Path, 'read_text', read), patch.object(Path, 'open', opened), patch.object(json, 'loads', loads):
        poll()
        counts.update(reads=0, parses=0)
        started = time.perf_counter()
        for _ in range(10):
            poll()
        results['unchanged_polls'] = {**counts, 'ms': (time.perf_counter() - started) * 1000,
                                      'session_bytes': path.stat().st_size}
        with path.open('a') as handle:
            handle.write(json.dumps({'type': 'message', 'message': {'role': 'user', 'content': 'follow-up'}}) + '\n')
        counts.update(reads=0, parses=0)
        poll()
        results['changed_poll'] = dict(counts)
    if (args.source / 'open_law_lens/source_artifacts.py').is_file():
        from open_law_lens.source_artifacts import export_source_artifacts
        text = 'x' * 126028 + '\nLate exception: the rule does not apply.\n'
        original = root / 'original.txt'
        original.write_text(text)
        started = time.perf_counter()
        exported = export_source_artifacts({'ok': True, 'text': text,
            'official_pagination': False, 'warnings': ['Synthetic unpaginated baseline']}, root / 'artifact')
        results['artifact_export'] = {'ms': (time.perf_counter() - started) * 1000,
            'source_bytes': len(text.encode()), 'part_count': exported['part_count'],
            'stdout_json_bytes': len(json.dumps(exported).encode()), 'extraction_count': 1}
        pi = shutil.which('pi')
        if pi:
            read_module = next((parent / 'dist/core/tools/read.js' for parent in Path(pi).resolve().parents
                                if (parent / 'dist/core/tools/read.js').is_file()), None)
            node = Path(pi).parent / 'node'
            if read_module is not None and node.is_file():
                completed = subprocess.run([str(node), str(Path(__file__).with_name('source_transport.mjs')),
                    str(read_module), str(root / 'artifact'), str(original)],
                    capture_output=True, text=True, timeout=30, check=True)
                results['installed_read_transport'] = json.loads(completed.stdout)
print(json.dumps(results, indent=2))
