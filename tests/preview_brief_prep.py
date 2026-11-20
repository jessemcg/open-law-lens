"""Private-bus native Brief Prep acceptance. Real GTK, wrapper and Save; fake Pi.

Run with dbus-run-session -- python tests/preview_brief_prep.py [--hold].
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import traceback
from unittest.mock import patch

from test_brief_prep import pdf, TITLE

ANSWER = '# Synthetic Notice Issue\n*Check the waiver*\n\nRead Welf. & Inst. Code, § 300.'


def fake_pi():
    workspace = Path.cwd()
    args = sys.argv[2:]
    assert args[args.index('--tools') + 1] == 'read,bash,grep,find,ls'
    assert os.environ['OPEN_LAW_LENS_AGENT_PROFILE_KEY'] == 'prep_reply'
    assert 'Brief Prep variant: reply' in args[-1]
    evidence = json.loads((workspace / 'brief-prep-manifest.json').read_text())
    assert evidence['case_number'] == 'B123456'
    assert [s['role'] for s in evidence['filings']] == ['aob', 'rb']
    assert evidence['filings'][0]['source'] == 'nested/AOB-two.pdf'
    log = Path(os.environ['PI_CODING_AGENT_SESSION_DIR']) / 'synthetic.jsonl'
    token = os.environ['OPEN_LAW_LENS_AGENT_FOLLOWUP_TOKEN']
    log.write_text(json.dumps({'type': 'session', 'cwd': str(workspace)}) + '\n')
    count = 0

    def write_turn(text, reason):
        nonlocal count
        count += 1
        with log.open('a') as out:
            for prefix, message in (
                ('q', {'role': 'user', 'content': text}),
                ('a', {'role': 'assistant', 'stopReason': reason,
                       'content': [{'type': 'text', 'text': ANSWER if count == 1 else ANSWER + '\n\nSynthetic follow-up.'}]}),
            ):
                out.write(json.dumps({'type': 'message', 'id': f'{prefix}{count}', 'message': message}) + '\n')

    write_turn('initial', 'stop')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(os.environ['OPEN_LAW_LENS_AGENT_FOLLOWUP_SOCKET'])
        server.listen()
        while True:
            conn, _ = server.accept()
            with conn, conn.makefile('rb') as reader:
                request = json.loads(reader.readline())
                assert request['token'] == token
                response = {k: request[k] for k in ('v', 'type', 'id')}
                response.update(ok=True, state='ready' if request['type'] == 'status' else 'busy')
                conn.sendall(json.dumps(response).encode() + b'\n')
                if request['type'] == 'submit':
                    text = request['text']
                    write_turn(text, 'aborted' if 'interrupt' in text else 'stop')


def primary(root: Path, original: Path, other: Path, hold: bool) -> int:
    from open_law_lens import app as ui
    from open_law_lens.library import CaseLibrary
    from test_research_cache_sidebar import rows

    ui.APP_ID += '.BriefPrepPreview'
    app = ui.OpenLawLensApp()
    error = []
    window = None
    start = time.monotonic()
    successful = False
    attempts = []
    fake_db = CaseLibrary(root / 'library.sqlite3')

    def steps():
        nonlocal window
        window = app._main_window()
        window.set_title('Synthetic Open Law Lens — Brief Prep')
        assert window._brief_prep_dialog.get_heading() == 'Reply Brief Prep'
        assert 'configured model provider' in window._brief_prep_dialog.get_body()
        window._brief_prep_dialog.response('start')
        # Change the pinned selection while the async prerequisite check runs.
        (root / 'selection').write_text(other.name)
        window._refresh_current_case_context()
        yield lambda: getattr(window, '_brief_prep_dialog', None) is not None
        dialog = window._brief_prep_dialog
        assert dialog.get_heading() == 'Choose the operative filings'
        picker = dialog.get_extra_child().get_last_child()
        assert picker.get_model().get_string(1) == 'nested/AOB-two.pdf'
        picker.set_selected(1)
        dialog.response('continue')
        yield lambda: window._agent_answer_eligible and not window._agent_answer_working
        assert window._agent_subview_name == 'answer'
        assert window._agent_prep.case_number == 'B123456'
        assert window._agent_last_answer_text == ANSWER
        assert window._agent_save_answer_button.get_sensitive()
        busy = subprocess.Popen([sys.executable, __file__, '--send', str(other)], stdout=subprocess.DEVNULL)
        attempts.append(busy)
        yield lambda: busy.poll() is not None
        assert busy.returncode == 2  # warm command rejected, not queued
        assert window._agent_prep.case_number == 'B123456'
        window._agent_followup_entry.set_text('interrupt this synthetic turn')
        window._on_agent_followup_activate(window._agent_followup_entry)
        yield lambda: (not window._agent_followup_pending and not window._agent_answer_working
                       and not window._agent_answer_eligible and bool(window._agent_answer_failure_status))
        window._on_save_agent_answer_clicked(None)
        assert not window.client.cache.list_agent_answer_entries()
        window._agent_followup_entry.set_text('complete a synthetic follow-up for the original appeal')
        window._on_agent_followup_activate(window._agent_followup_entry)
        yield lambda: (window._agent_answer_eligible and not window._agent_answer_working
                       and 'Synthetic follow-up.' in window._agent_last_answer_text)
        window._on_save_agent_answer_clicked(None)
        cache = window.client.cache
        answer_id = cache.list_agent_answer_entries()[0]['answer_id']
        assert cache.read_agent_answer(answer_id)['brief_prep'] == {'kind': 'reply', 'case_number': 'B123456'}
        cache.save_agent_answer('# A Regular Answer\n*Regular disposition*\n\nSynthetic.', mode='general')
        cache.set_agent_answer_selected(answer_id, True)
        fake_db.save_research_set('Synthetic Prep', cache)
        cache.clear()
        fake_db.load_research_set_into_cache('Synthetic Prep', cache)
        assert cache.is_agent_answer_selected(answer_id)
        window._set_sidebar_authorities([], [], [], select_agent_answer_id=answer_id)
        groups = {r._open_law_lens_cache_section for r in rows(window)}
        assert {'brief_prep_header', 'agent_answer_header'} <= groups
        row = window.case_list.get_selected_row()
        assert row._open_law_lens_authority_id == answer_id
        assert row.has_css_class('cache-brief-prep')
        window._open_agent_answer(cache.read_agent_answer_index()[answer_id])
        assert window._selected_agent_answer['answer_id'] == answer_id
        assert window._selected_agent_answer['text'].endswith('Synthetic follow-up.')
        window._stop_agent()
        print('PASS cold/warm command line, case pin, ambiguity choice, Answer, interrupted follow-up, Save, reader, Research Set', flush=True)

    checks = steps()

    def tick():
        nonlocal next_check, successful
        try:
            if time.monotonic() - start > 28:
                raise AssertionError(f'timed out at step {next_check}')
            if next_check():
                next_check = next(checks)
        except StopIteration:
            successful = True
            if not hold:
                app.quit()
            return False
        except Exception:
            traceback.print_exc()
            error.append(True)
            if window is not None:
                window._stop_agent()
            app.quit()
            return False
        return True

    next_check = lambda: True
    ui.GLib.timeout_add(150, tick)
    with patch.object(ui.task_prerequisites, 'model_check', return_value=SimpleNamespace(reason=None)):
        app.run([__file__, '--brief-prep', 'reply', '--case-dir', str(original)])
    for process in attempts:
        process.wait(timeout=4)
    return 0 if successful and not error else 1


if __name__ == '__main__':
    if '--pi' in sys.argv:
        fake_pi()
    elif '--send' in sys.argv:
        from open_law_lens import app as ui
        ui.APP_ID += '.BriefPrepPreview'
        raise SystemExit(ui.main(['--brief-prep', 'opposition', '--case-dir', sys.argv[-1]]))
    else:
        with tempfile.TemporaryDirectory(prefix='oll-prep-', dir='/tmp') as td:
            root = Path(td)
            for key, leaf in {
                'OPEN_LAW_LENS_CONFIG': 'config.json', 'OPEN_LAW_LENS_CACHE_DIR': 'cache',
                'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3', 'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
                'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': 'archive', 'OPEN_LAW_LENS_PI_SETTINGS': 'pi-settings.json',
                'OPEN_LAW_LENS_CURRENT_CASE_FILE': 'selection', 'OPEN_LAW_LENS_CASE_ROOTS': 'cases',
                'PI_CODING_AGENT_DIR': 'agent-home', 'XDG_STATE_HOME': 'state', 'XDG_RUNTIME_DIR': 'rt',
                'OPEN_LAW_LENS_PI_BIN': 'fake-pi',
            }.items():
                os.environ[key] = str(root / leaf)
            os.environ.update(COURTLISTENER_TOKEN='synthetic-not-a-token', PI_RUN_METRICS_ENABLED='0',
                              OPEN_LAW_LENS_STORAGE='legacy', OPEN_LAW_LENS_PI_NODE_BIN='/usr/bin/node')
            (root / 'rt').mkdir(mode=0o700)
            (root / 'config.json').write_text('{}')
            import shlex
            (root / 'fake-pi').write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, __file__, '--pi']) + ' "$@"\n')
            (root / 'fake-pi').chmod(0o700)
            original = root / 'cases' / "B123456 Synthetic's Appeal"
            other = root / 'cases' / 'D234567 Different Synthetic Appeal'
            other.mkdir(parents=True)
            for filename, role, body in [('AOB-one.pdf', 'AOB', 'One opening brief.'),
                                          ('AOB-two.pdf', 'AOB', 'Another opening brief.'), ('RB.pdf', 'RB', 'Respondent text.')]:
                pdf(original / 'nested' / filename, ['Court of Appeal', 'B123456', TITLE[role]], [body])
            (root / 'selection').write_text(original.name)
            raise SystemExit(primary(root, original, other, '--hold' in sys.argv))
