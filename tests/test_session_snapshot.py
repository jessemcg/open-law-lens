import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens.agent import PiSessionSnapshotCache


def entry(role, ident='', reason=None, text='same answer', content=None):
    message = {'role': role, 'content': text if content is None else content}
    if reason is not None:
        message['stopReason'] = reason
    return json.dumps({'type': 'message', 'id': ident, 'message': message}) + '\n'


class SessionSnapshotTests(unittest.TestCase):
    def test_completion_requires_stop_without_tools_for_latest_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            cache = PiSessionSnapshotCache()
            successful = entry('user', 'q1') + entry('assistant', 'a1', 'stop')
            for reason in ('length', 'error', 'aborted', 'pending', 'deferred', None, 'future', 'toolUse'):
                with self.subTest(reason=reason):
                    path.write_text(successful + entry('user', 'q2') + entry('assistant', 'a2', reason))
                    result = cache.read(path)
                    self.assertFalse(result.current_completed)
                    self.assertEqual(result.successful_answer_count, 1)
                    self.assertEqual(result.answer_id, 'a1')
                    self.assertEqual(result.request_id, 'q2')
            path.write_text(successful + entry('user', 'q2') + entry('assistant', 'a2', 'stop', content=[
                {'type': 'text', 'text': 'bad'}, {'type': 'toolCall', 'name': 'read'}]))
            self.assertFalse(cache.read(path).current_completed)
            path.write_text(successful + entry('user', 'q2'))
            self.assertFalse(cache.read(path).current_completed)

    def test_identical_successes_retry_and_ordinal_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_text(entry('user') + entry('assistant', reason='stop') +
                            entry('user') + entry('assistant', reason='error') +
                            entry('assistant', reason='stop'))
            result = PiSessionSnapshotCache().read(path)
            self.assertTrue(result.current_completed)
            self.assertEqual(result.successful_answer_count, 2)
            self.assertEqual(result.answer_id, 'ordinal:5')
            self.assertEqual(result.answer_request_id, 'ordinal:3')

    def test_unchanged_polls_open_nothing_changed_poll_one_streaming_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            path.write_text(entry('user') + entry('assistant', reason='stop'))
            cache = PiSessionSnapshotCache()
            first = cache.read(path)
            with patch.object(Path, 'open', side_effect=AssertionError('unchanged opened log')):
                for _ in range(10):
                    self.assertIs(cache.read(path), first)
            path.write_text(entry('user') + entry('assistant', reason='stop', text='new'))
            original = Path.open
            calls = []
            def opened(p, *args, **kw):
                calls.append(p)
                return original(p, *args, **kw)
            with patch.object(Path, 'open', opened), patch.object(Path, 'read_text', side_effect=AssertionError):
                self.assertEqual(cache.read(path).answer, 'new')
            self.assertEqual(calls, [path])

    def test_partial_json_newline_retry_replacement_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.jsonl'
            cache = PiSessionSnapshotCache()
            complete = entry('user') + entry('assistant', reason='stop')
            partial = entry('user', 'q2') + entry('assistant', 'a2', 'stop', text='late')
            path.write_text(complete + partial[:-5])
            self.assertTrue(cache.read(path).partial_record)
            self.assertFalse(cache.read(path).current_completed)
            path.write_text(complete + partial[:-1])
            self.assertFalse(cache.read(path).current_completed)
            with path.open('a') as handle:
                handle.write('\n')
            self.assertTrue(cache.read(path).current_completed)
            replacement = Path(directory) / 'new.jsonl'
            replacement.write_text(entry('assistant', reason='aborted'))
            os.replace(replacement, path)
            self.assertFalse(cache.read(path).current_completed)
            self.assertEqual(cache.read(path).answer, '')
            path.write_text('')
            self.assertEqual(cache.read(path).successful_answer_count, 0)
            path.unlink()
            self.assertEqual(cache.read(path).status, 'error')
