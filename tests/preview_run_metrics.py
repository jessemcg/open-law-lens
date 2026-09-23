"""Synthetic session-answer GUI acceptance. No real settings/cases/providers.

uv run python tests/preview_run_metrics.py [--auto]
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='oll-metrics-preview-'))
for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME'):
    path = ROOT / key.lower()
    path.mkdir(mode=0o700)
    os.environ[key] = str(path)
for key, filename in {'OPEN_LAW_LENS_CONFIG': 'config.json', 'OPEN_LAW_LENS_CACHE_DIR': 'cache',
                      'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3', 'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3'}.items():
    os.environ[key] = str(ROOT / filename)
os.environ.pop('COURTLISTENER_TOKEN', None)
os.environ['GSETTINGS_BACKEND'] = 'memory'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from gi.repository import Gio


def blocked(*args, **kwargs):
    raise AssertionError('Network/model work forbidden in metrics preview')


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass

    def _launch_agent_with_prompt(self, *args, **kwargs):
        blocked()


def activate(app):
    window = Preview(app)
    window.set_title('Open Law Lens — Synthetic Metrics Acceptance')
    window.set_default_size(1000, 780)
    workspace = ROOT / 'workspace'
    sessions = workspace / 'pi-sessions'
    sessions.mkdir(parents=True)
    session = sessions / 'synthetic.jsonl'
    session.write_text(json.dumps({'type': 'session', 'cwd': str(workspace)}) + '\n')
    window._agent_workspace_path = workspace
    window._agent_active = True  # Session view only; no provider subprocess
    window._agent_mode = ui.AGENT_MODE_GENERAL
    window._agent_output_collapsed = False
    revision = 1
    expected = ''
    attempts = 0

    def append_answer():
        nonlocal expected
        expected = f'Synthetic answer revision {revision}.\n\nThe **sample conclusion** is for UI acceptance only.'
        with session.open('a') as stream:
            stream.write(json.dumps({'type': 'message', 'message': {'role': 'assistant', 'stopReason': 'stop',
                         'content': [{'type': 'text', 'text': expected}]}}) + '\n')
        window._poll_agent_answer()

    def check():
        nonlocal revision, attempts
        attempts += 1
        if attempts > 150:
            raise AssertionError('Synthetic answer rendering timed out')
        if window._agent_answer_working or window._agent_answer_finishing or window._agent_last_answer_text != expected:
            return True
        assert window._agent_session_log_path == session
        if revision == 1:
            revision = 2
            append_answer()
            return True
        assert not hasattr(window, '_agent_copy_trace_button')
        assert window._agent_save_answer_button.get_sensitive()
        window._set_agent_subview(ui.AGENT_SUBVIEW_SESSION)
        assert window._agent_session_widget.get_visible()
        window._set_agent_subview(ui.AGENT_SUBVIEW_ANSWER)
        assert window._agent_answer_scroller.get_visible()
        print(f'PASS revisions=2 session_transport=retained copy_trace=absent save=enabled pid={os.getpid()} root={ROOT}', flush=True)
        if '--auto' in sys.argv:
            app.quit()
        return False

    window.present()
    append_answer()
    ui.GLib.timeout_add(100, check)


with patch.object(socket.socket, 'connect', blocked), patch.object(socket, 'create_connection', blocked):
    application = ui.Adw.Application(application_id=f'com.mcglaw.OpenLawLens.MetricsPreview.p{os.getpid()}', flags=Gio.ApplicationFlags.NON_UNIQUE)
    failed = False

    def failure(kind, value, tb):
        global failed
        failed = True
        sys.__excepthook__(kind, value, tb)
        application.quit()

    sys.excepthook = failure
    application.connect('activate', activate)
    application.run([])
    sys.exit(1 if failed else 0)
