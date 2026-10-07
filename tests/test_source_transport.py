import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from open_law_lens.source_artifacts import export_source_artifacts


class InstalledSourceTransportTests(unittest.TestCase):
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
        texts = [('x' * 126028) + '\nLate exception: the rule does not apply.\n',
                 ('Unicode 😀 ⚖️ 中 résumé\n' * 10000) + '\nLate exception.']
        for text in texts:
            with self.subTest(length=len(text)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = root / 'original.txt'
                original.write_text(text)
                export_source_artifacts({'text': text, 'ok': True}, root / 'source')
                result = subprocess.run([str(node), str(Path(__file__).with_name('source_transport.mjs')),
                                         str(read_module), str(root / 'source'), str(original)],
                                        capture_output=True, text=True, timeout=30, check=True)
                report = json.loads(result.stdout)
                self.assertTrue(report['delivery_complete'])
                self.assertTrue(report['baseline_truncated'])
                self.assertEqual(report['delivered_bytes'], len(text.encode()))
                self.assertEqual(report['extraction_count'], 1)
