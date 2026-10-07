from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from open_law_lens import cli
from open_law_lens.source_artifacts import export_source_artifacts, source_parts


class SourceArtifactTests(unittest.TestCase):
    def test_lossless_bounded_parts_offsets_modes_metadata_and_late_exception(self):
        for text in ('x' * 126_028 + '\nLate exception.', ('line\n' * 7000),
                     ('Résumé ⚖️ 中 😀\n\n' * 9000) + 'Late exception.\n', '',
                     '\n' * 9000, 'a' * 32767 + '😀b'):
            with self.subTest(length=len(text)), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'source'
                payload = {'text': text, 'ok': True, 'warnings': ['Unpaginated baseline'],
                           'official_pagination': False, 'pagination_marker_count': 0,
                           'source_url': 'https://example.invalid/synthetic', 'provenance': {'provider': 'synthetic'}}
                summary = export_source_artifacts(payload, destination)
                self.assertNotIn('parts', summary)
                self.assertNotIn('text', summary)
                manifest = json.loads((destination / 'manifest.json').read_text())
                metadata = json.loads((destination / 'metadata.json').read_text())
                self.assertEqual(metadata, {k: v for k, v in payload.items() if k != 'text'} | {'text_length': len(text)})
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
                combined = []
                previous = 0
                for part in manifest['parts']:
                    path = destination / part['name']
                    data = path.read_bytes()
                    self.assertLessEqual(len(data), 32768)
                    self.assertLessEqual(len(data.decode().split('\n')), 1500)
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                    self.assertEqual(part['start_offset'], previous)
                    previous = part['end_offset']
                    self.assertEqual(data.decode(), text[part['start_offset']:previous])
                    self.assertEqual(part['byte_count'], len(data))
                    combined.append(data)
                self.assertEqual(b''.join(combined), text.encode())
                self.assertEqual(previous, len(text))
                for path in destination.iterdir():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_symlink_escape_relative_and_failed_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            existing = workspace / 'existing'
            existing.mkdir()
            sentinel = existing / 'sentinel'
            sentinel.write_text('preserve')
            (workspace / 'link').symlink_to(existing, target_is_directory=True)
            payload = {'ok': True, 'text': 'source'}
            for destination in ('relative', existing, workspace / 'link', workspace / 'link' / 'child',
                                root / 'outside', workspace / '..' / 'escape', workspace):
                with self.subTest(destination=destination), self.assertRaises((ValueError, OSError)):
                    export_source_artifacts(payload, destination, workspace=workspace)
            self.assertEqual(sentinel.read_text(), 'preserve')
            with self.assertRaises(ValueError):
                export_source_artifacts({'ok': False, 'text': 'partial'}, workspace / 'bad')
            self.assertFalse((workspace / 'bad').exists())

    def test_write_permission_failure_cleans_only_own_incomplete_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / 'other'
            other.write_text('preserved')
            destination = root / 'new'
            original = os.open
            def opened(path, flags, *args, **kwargs):
                if path == 'metadata.json':
                    raise PermissionError('synthetic denied')
                return original(path, flags, *args, **kwargs)
            with patch('open_law_lens.source_artifacts.os.open', opened), self.assertRaises(PermissionError):
                export_source_artifacts({'text': 'source' * 10000}, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(other.read_text(), 'preserved')

    def test_cli_case_and_brief_export_once_without_body_and_failures(self):
        for command in ('extract-case', 'extract-brief'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                destination = Path(directory) / 'artifact'
                payload = {'ok': True, 'text': 'source' * 10000, 'warnings': ['baseline'], 'official_pagination': False}
                result = SimpleNamespace(to_json=lambda: payload)
                output = io.StringIO()
                with patch.dict(os.environ, {'OPEN_LAW_LENS_AGENT_WORKSPACE': directory}), redirect_stdout(output):
                    if command == 'extract-case':
                        with patch.object(cli, 'extract_authority', return_value=result) as extract:
                            code = cli.main([command, '11 Cal.5th 614', '--output-dir', str(destination)])
                            extract.assert_called_once()
                    else:
                        with patch.object(cli.PriorBriefLibrary, 'default') as library:
                            library.return_value.read.return_value = result
                            code = cli.main([command, 'synthetic-id', '--output-dir', str(destination)])
                            library.return_value.read.assert_called_once_with('synthetic-id')
                self.assertEqual(code, 0)
                self.assertLess(len(output.getvalue()), 1000)
                summary = json.loads(output.getvalue())
                self.assertTrue(summary['ok'])
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(cli._export_source_result(payload, str(destination)), 1)
                self.assertEqual(json.loads(output.getvalue())['export_status'], 'failed')
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli._export_source_result({'ok': False, 'text': 'partial'}, str(Path(directory) / 'fail')), 1)
            self.assertFalse((Path(directory) / 'fail').exists())

    def test_cli_extraction_and_permission_errors_are_structured_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            for error in (RuntimeError('synthetic authority failure'), PermissionError('synthetic permission failure')):
                output = io.StringIO()
                with patch.object(cli, 'extract_authority', side_effect=error), redirect_stdout(output):
                    self.assertEqual(cli.main(['extract-case', '1 Cal.5th 1', '--output-dir', directory + '/source']), 1)
                payload = json.loads(output.getvalue())
                self.assertFalse(payload['ok'])
                self.assertEqual(payload['export_status'], 'failed')
                self.assertFalse((Path(directory) / 'source').exists())
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(cli.main(['extract-case', '--output-dir', directory + '/source']), 1)
            self.assertFalse(json.loads(output.getvalue())['ok'])
            with patch.object(cli.PriorBriefLibrary, 'default') as library, redirect_stdout(io.StringIO()) as output:
                library.return_value.read.return_value = None
                self.assertEqual(cli.main(['extract-brief', 'missing', '--output-dir', directory + '/source']), 1)
            self.assertEqual(json.loads(output.getvalue())['export_status'], 'failed')

    def test_cli_invalid_destination_fails_before_extraction(self):
        for destination in ('', 'relative', '/outside/workspace'):
            with self.subTest(destination=destination), patch.dict(os.environ, {
                'OPEN_LAW_LENS_AGENT_WORKSPACE': '/private/workspace'
            }), patch.object(cli, 'extract_authority') as extract, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['extract-case', '1 Cal.5th 1', '--output-dir', destination]), 1)
                self.assertEqual(json.loads(output.getvalue())['export_status'], 'failed')
                extract.assert_not_called()

    def test_cli_mutually_exclusive_outputs(self):
        parser = cli.build_parser()
        for argv in (['extract-case', '1 Cal.5th 1', '--text', '--output-dir', '/tmp/new'],
                     ['extract-case', '1 Cal.5th 1', '--find', 'term', '--output-dir', '/tmp/new'],
                     ['extract-brief', 'id', '--text', '--output-dir', '/tmp/new']):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                parser.parse_args(argv)
