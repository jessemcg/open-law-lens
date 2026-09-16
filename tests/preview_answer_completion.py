"""Synthetic completion responsiveness preview. No model/network/private data.

Run in an isolated project copy. Injects an eight-second log-read delay on the
worker and formats a long answer. Prints main-loop heartbeat gaps; closes at 50s.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='oll-completion-gui-'))
for key, name in {
    'OPEN_LAW_LENS_CONFIG': 'config.json', 'OPEN_LAW_LENS_CACHE_DIR': 'cache',
    'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': 'archive', 'XDG_STATE_HOME': 'state',
}.items():
    os.environ[key] = str(ROOT / name)
os.environ.pop('COURTLISTENER_TOKEN', None)
(ROOT / 'config.json').write_text('{}')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from gi.repository import Gio

workspace = ROOT / 'workspace'
workspace.mkdir()
sessions = workspace / 'pi-sessions'
sessions.mkdir()
answer = '# Synthetic Completion Responsiveness\n*Formatting without blocking*\n\n' + '\n\n'.join(
    f'**Paragraph {i}.** This is synthetic display text, not legal research. '
    'See https://example.invalid/reference for a synthetic navigation target.' for i in range(300))
(sessions / 'session.jsonl').write_text('\n'.join(json.dumps(x) for x in [
    {'type': 'session', 'cwd': str(workspace)},
    {'type': 'message', 'message': {'role': 'assistant', 'stopReason': 'stop',
                                  'content': [{'type': 'text', 'text': answer}]}}
]) + '\n')

original = ui.extract_latest_pi_final_answer_from_jsonl
main_thread = threading.get_ident()
calls = 0


def delayed(path):
    global calls
    assert threading.get_ident() != main_thread
    calls += 1
    if calls == 1:
        time.sleep(float(os.environ.get('OLL_COMPLETION_PREVIEW_DELAY', '8')))
    return original(path)


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass


def activate(app):
    window = Preview(app)
    window.set_title('Synthetic Answer Completion — Responsiveness')
    window.present()
    window._agent_workspace_path = workspace
    window._agent_mode = 'general'
    window._agent_active = True
    beats = [time.monotonic()]
    reported = False

    def heartbeat():
        nonlocal reported
        beats.append(time.monotonic())
        if window._agent_answer_finishing:
            assert window._composer_spinner.get_spinning()
            assert window._composer_spinner.get_visible()
        if window._agent_last_answer_text and not window._agent_answer_working and not reported:
            reported = True
            maximum = max(b - a for a, b in zip(beats, beats[1:]))
            text = window._agent_answer_buffer.get_text(
                window._agent_answer_buffer.get_start_iter(),
                window._agent_answer_buffer.get_end_iter(), True)
            assert 'Paragraph 299.' in text
            assert not window._agent_answer_finishing
            assert len(window._agent_external_url_link_lookup) == 300
            assert maximum < 1, maximum
            print('PASS rendered 300 paragraphs and links; heartbeat max gap', round(maximum, 3),
                  'seconds; beats', len(beats), 'worker reads', calls, flush=True)
        return True

    ui.GLib.timeout_add(10, heartbeat)
    window._start_agent_answer_polling()
    ui.GLib.timeout_add(100, lambda: (window._on_agent_exited(None, 0), False)[1])
    ui.GLib.timeout_add_seconds(50, lambda: (window._stop_agent_answer_polling(), app.quit(), False)[2])
    print('READY', os.getpid(), ROOT, flush=True)


def blocked(*args, **kwargs):
    raise AssertionError('Network forbidden in completion preview')


with patch.object(socket.socket, 'connect', blocked), patch.object(ui, 'extract_latest_pi_final_answer_from_jsonl', delayed):
    app = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.CompletionPreview',
                            flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect('activate', activate)
    app.run([])
