from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from open_law_lens import cli


class InstalledSourceTransportTests(unittest.TestCase):
    def setUp(self):
        network = patch('open_law_lens.client.urlopen',
                        side_effect=AssertionError('Network forbidden in synthetic transport tests'))
        network.start()
        self.addCleanup(network.stop)

    def test_installed_pi_read_delivers_every_part_exactly_offline(self):
        pi = shutil.which('pi')
        if not pi:
            self.skipTest('Installed Pi unavailable; no automatic installation')
        read_module = next((parent / 'dist/core/tools/read.js'
                            for parent in Path(pi).resolve().parents
                            if (parent / 'dist/core/tools/read.js').is_file()), Path('/nonexistent/read.js'))
        node = Path(shutil.which('pi')).parent / 'node'
        if not node.is_file() or not read_module.is_file():
            self.skipTest('Installed Pi read module or matching Node unavailable')
        texts = ['Opening rule: synthetic only.\n' + ('x' * 126028)
                 + '\nLate exception: the rule does not apply.\n',
                 'Opening rule: synthetic only.\n' + ('Unicode 😀 ⚖️ 中 résumé\n' * 10000)
                 + '\nLate exception: the rule does not apply.']
        for text in texts:
            with self.subTest(length=len(text)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = root / 'original.txt'
                original.write_text(text)
                payload = {'text': text, 'ok': True, 'warnings': ['Synthetic unpaginated baseline'],
                           'official_pagination': False, 'pagination_marker_count': 0,
                           'source_url': 'https://example.invalid/synthetic-opinion',
                           'provenance': {'provider': 'synthetic'}}
                output = io.StringIO()
                with patch.dict(os.environ, {'OPEN_LAW_LENS_AGENT_WORKSPACE': directory}), \
                        patch.object(cli, 'extract_case_by_cluster_id',
                                     return_value=SimpleNamespace(to_json=lambda: payload)) as extract, \
                        redirect_stdout(output):
                    code = cli.main(['extract-case', '--cluster-id', 'synthetic-id',
                                     '--output-dir', str(root / 'source')])
                self.assertEqual(code, 0)
                extract.assert_called_once()
                self.assertLess(len(output.getvalue().encode()), 1000)
                summary = json.loads(output.getvalue())
                self.assertNotIn('text', summary)
                self.assertNotIn('parts', summary)
                metadata = json.loads((root / 'source/metadata.json').read_text())
                self.assertEqual(metadata, {k: v for k, v in payload.items() if k != 'text'}
                                 | {'text_length': len(text)})
                result = subprocess.run([str(node), str(Path(__file__).with_name('source_transport.mjs')),
                                         str(read_module), str(root / 'source'), str(original)],
                                        capture_output=True, text=True, timeout=30, check=True)
                report = json.loads(result.stdout)
                self.assertTrue(report['delivery_complete'])
                self.assertTrue(report['baseline_truncated'])
                self.assertEqual(report['delivered_bytes'], len(text.encode()))
                self.assertEqual(report['extraction_count'], 1)
