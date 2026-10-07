"""Isolated native GTK completion/Save acceptance; synthetic JSONL, no Pi/model.

Controls append successful or incomplete turns to one private session. Assertions
run after worker/render completion. Only synthetic Save writes temporary cache.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='oll-reliability-gui-'))
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

ANSWER = '# Synthetic Completed Answer\n*Source transport only*\n\nThis is not legal advice or a model answer.'


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass


def activate(app):
    window = Preview(app)
    window.set_title('Synthetic OpenLawLens — Run Reliability')
    content = window.get_content()
    window.set_content(None)
    outer = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL)
    controls = ui.Gtk.Box(spacing=4)
    summary = ui.Gtk.Label(label='Synthetic only: no network, models, user data or settings')
    outer.append(controls)
    outer.append(summary)
    outer.append(content)
    window.set_content(outer)
    window.present()
    workspace = ROOT / 'workspace'
    (workspace / 'pi-sessions').mkdir(parents=True)
    path = workspace / 'pi-sessions/session.jsonl'
    window._agent_workspace_path = workspace
    window._agent_mode = 'general'
    window._agent_active = True
    records = [{'type': 'session', 'cwd': str(workspace)}]
    turn = 0

    def write():
        path.write_text(''.join(json.dumps(record) + '\n' for record in records))

    def check(reason, previous, count_before):
        if window._agent_answer_working:
            return True
        try:
            expected = reason == 'stop'
            assert window._agent_answer_eligible == expected
            assert window._agent_save_answer_button.get_sensitive() == expected
            if expected:
                assert window._agent_last_answer_text == ANSWER
                assert window._agent_subview_name == 'answer'
                assert window._agent_answer_turn_count == count_before + 1
            else:
                assert window._agent_subview_name == 'session'
                assert window._agent_last_answer_text == previous
                assert window._agent_answer_button.get_label() == ('Previous Answer' if previous else 'Answer')
                before = window.client.cache.list_agent_answer_entries()
                window._on_save_agent_answer_clicked(None)
                assert window.client.cache.list_agent_answer_entries() == before
            summary.set_text(f'PASS {reason}: Save={expected}; completed turns={window._agent_answer_turn_count}')
            print(summary.get_text(), flush=True)
        except Exception as exc:
            summary.set_text(f'FAIL {reason}: {exc!r}')
            print(summary.get_text(), flush=True)
            raise
        return False

    def respond(reason, fresh=False):
        nonlocal turn, records
        if window._agent_answer_working:
            return
        if fresh:
            window._stop_agent_answer_polling()
            window._clear_agent_answer()
            window._agent_answer_turn_count = 0
            records = [{'type': 'session', 'cwd': str(workspace)}]
        previous = window._agent_last_answer_text
        count_before = window._agent_answer_turn_count
        turn += 1
        records.extend([
            {'type': 'message', 'id': f'q{turn}', 'message': {'role': 'user', 'content': 'Synthetic request'}},
            {'type': 'message', 'id': f'a{turn}', 'message': {'role': 'assistant', 'stopReason': reason,
              'content': [{'type': 'text', 'text': ANSWER if reason == 'stop' else 'INCOMPLETE — must never become Answer'}]}},
        ])
        write()
        if window._agent_terminal is not None:
            terminal_text = ANSWER if reason == 'stop' else 'INCOMPLETE — must never become Answer'
            window._agent_terminal.feed(f'\r\nSynthetic {reason}:\r\n{terminal_text}\r\n'.encode())
        window._agent_session_log_path = path
        window._poll_agent_answer()
        ui.GLib.timeout_add(30, check, reason, previous, count_before)

    def replace_or_close(close=False):
        if window._agent_answer_working:
            return
        old_cache = window._agent_snapshot_cache
        old_read = old_cache.read
        def delayed(target):
            time.sleep(1)
            return old_read(target)
        old_cache.read = delayed
        window._poll_agent_answer()
        window._stop_agent_answer_polling()
        if close:
            generation = window._agent_answer_generation
            app.hold()  # Let the stale worker finish after the last window closes.
            window.close()
            def closed_check():
                assert window._agent_answer_generation > generation
                assert not window._agent_answer_working
                assert not window._agent_answer_eligible
                print('PASS closed during worker; stale callback ignored', flush=True)
                app.release()
                app.quit()
                return False
            ui.GLib.timeout_add(1500, closed_check)
        else:
            window._clear_agent_answer()
            respond('stop', fresh=True)
            generation = window._agent_answer_generation
            def check_stale():
                assert window._agent_answer_generation == generation
                assert window._agent_answer_eligible
                print('PASS replaced during worker; stale callback ignored', flush=True)
                return False
            ui.GLib.timeout_add(1500, check_stale)

    for label, callback in (
        ('Success / Identical', lambda *_: respond('stop')),
        ('Fresh abort', lambda *_: respond('aborted', fresh=True)),
        ('Aborted follow-up', lambda *_: respond('aborted')),
        ('Error', lambda *_: respond('error')),
        ('Output limit', lambda *_: respond('length')),
        ('Replace worker', lambda *_: replace_or_close()),
        ('Close worker', lambda *_: replace_or_close(True)),
    ):
        button = ui.Gtk.Button(label=label)
        button.connect('clicked', callback)
        controls.append(button)
    write()
    def live_poll():
        if not window.get_visible():
            return False
        window._poll_agent_answer()
        return True
    ui.GLib.timeout_add(1200, live_poll)
    print('READY', os.getpid(), ROOT, flush=True)
    # Exit safely if unattended; normal close uses the production generation guard.
    ui.GLib.timeout_add_seconds(600, lambda: (window.close(), app.quit(), False)[2])


def blocked(*args, **kwargs):
    raise AssertionError('Network forbidden in synthetic preview')


with patch.object(socket.socket, 'connect', blocked):
    application = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.ReliabilityPreview',
                                    flags=Gio.ApplicationFlags.NON_UNIQUE)
    application.connect('activate', activate)
    application.run([])
