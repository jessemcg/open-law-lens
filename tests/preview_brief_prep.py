"""Private-bus native Brief Prep acceptance. Real GTK, wrapper and Save; fake Pi.

Run with dbus-run-session -- python tests/preview_brief_prep.py
[--unambiguous] [--hold-choice] [--hold].
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
    evidence = json.loads((workspace / 'brief-prep-manifest.json').read_text())
    profile = os.environ['OPEN_LAW_LENS_AGENT_PROFILE_KEY']
    if profile == 'prep_reply':
        assert 'Brief Prep variant: reply' in args[-1]
        assert evidence['case_number'] == 'B123456'
        assert [s['role'] for s in evidence['filings']] == ['aob', 'rb']
        assert evidence['filings'][0]['source'] == 'nested/AOB-two.pdf'
    else:
        assert profile == 'prep_opposition'
        assert 'Brief Prep variant: opposition' in args[-1]
        assert evidence['case_number'] == 'D234567'
        assert [s['role'] for s in evidence['filings']] == ['mtd']
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


def primary(root: Path, original: Path, other: Path, *, ambiguous: bool, hold_choice: bool, hold: bool) -> int:
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

    def send(case: Path, kind: str = 'opposition'):
        process = subprocess.Popen([sys.executable, __file__, '--send', kind, str(case)], stdout=subprocess.PIPE)
        attempts.append(process)
        return process

    def check_receipt(process, *, accepted: bool):
        assert process.returncode == (0 if accepted else 2)
        assert process.communicate(timeout=2)[0] == (b'brief-prep: requested\n' if accepted else b'brief-prep: rejected\n')
        assert not getattr(window, '_brief_prep_dialog', None)
        assert app.get_windows() == [window]

    def steps():
        nonlocal window
        window = app._main_window()
        window.set_title('Synthetic Open Law Lens — Brief Prep')
        assert not getattr(window, '_brief_prep_dialog', None)
        # Changing Current Case after dispatch must not retarget the active request.
        (root / 'selection').write_text(other.name)
        window._refresh_current_case_context()
        if ambiguous:
            yield lambda: window._brief_prep_filing_choice is not None
            panel, _ = window._brief_prep_filing_choice
            assert not getattr(window, '_brief_prep_dialog', None)
            assert window._brief_prep_choice_slot.get_visible()
            assert window._agent_request_pending and not window._agent_active
            assert 'B123456' in window._composer_message_label.get_text()
            choice_busy = send(other)
            yield lambda: choice_busy.poll() is not None
            check_receipt(choice_busy, accepted=False)
            assert window._brief_prep_filing_choice[0] is panel
            proceed = panel.get_last_child().get_last_child()
            assert not proceed.get_sensitive()
            if hold_choice:
                resume_at = time.monotonic() + 15
                yield lambda: time.monotonic() >= resume_at
            picker = panel.get_first_child().get_child().get_child().get_last_child()
            assert picker.get_child().get_text() == 'nested/AOB-two.pdf'
            picker.set_active(True)
            assert proceed.get_sensitive()
            proceed.emit('clicked')
        yield lambda: window._agent_answer_eligible and not window._agent_answer_working
        assert window._brief_prep_filing_choice is None
        assert not window._brief_prep_choice_slot.get_visible()
        assert app.get_windows() == [window]
        assert window._agent_subview_name == 'answer'
        assert window._agent_prep.case_number == 'B123456'
        assert window._agent_last_answer_text == ANSWER
        assert window._agent_save_answer_button.get_sensitive()
        busy = send(other)
        yield lambda: busy.poll() is not None
        check_receipt(busy, accepted=False)  # warm command rejected, not queued
        assert 'use /exit' in window._composer_message_label.get_text()
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
        # Stop the fake Pi normally through Vte's child-exited signal, so its
        # final transcript has settled before testing an idle warm launch.
        os.kill(window._agent_pid, 15)
        yield lambda: not (window._agent_active or window._agent_answer_working or window._agent_answer_finishing)
        assert not window._has_unsaved_agent_answer()
        missing = send(other, 'respondent')
        yield lambda: missing.poll() is not None and not window._agent_request_pending
        check_receipt(missing, accepted=True)
        assert window._composer_message_is_error
        assert 'opening brief' in window._composer_message_label.get_text()
        assert window._agent_prep.case_number == 'B123456'
        if ambiguous:
            cancel = send(original, 'reply')
            yield lambda: cancel.poll() is not None and window._brief_prep_filing_choice is not None
            check_receipt(cancel, accepted=True)
            panel, scratch = window._brief_prep_filing_choice
            panel.get_last_child().get_first_child().emit('clicked')
            assert not scratch.exists() and window._brief_prep_filing_choice is None
            assert not window._agent_request_pending and not window._agent_active
        warm = send(other)
        yield lambda: warm.poll() is not None and window._agent_active
        check_receipt(warm, accepted=True)
        assert app._main_window() is window
        assert window._agent_prep.case_number == 'D234567'
        yield lambda: window._agent_answer_eligible and not window._agent_answer_working
        assert window._agent_subview_name == 'answer'
        assert window._agent_last_answer_text == ANSWER
        os.kill(window._agent_pid, 15)
        yield lambda: not (window._agent_active or window._agent_answer_working or window._agent_answer_finishing)
        assert window._has_unsaved_agent_answer()
        unsaved = send(original, 'reply')
        yield lambda: unsaved.poll() is not None
        check_receipt(unsaved, accepted=False)
        assert 'Save the previous answer first' in window._composer_message_label.get_text()
        assert window._agent_prep.case_number == 'D234567'
        assert window._agent_last_answer_text == ANSWER
        assert window._current_case_socf_path is None
        window._on_brief_prep_menu_choice(None, SimpleNamespace(popdown=lambda: None), 'respondent')
        assert window._brief_prep_dialog.get_heading() == 'Respondent’s Brief Prep'
        assert 'any unsaved answer' in window._brief_prep_dialog.get_body()
        window._brief_prep_dialog.response('cancel')
        print(f'PASS cold ({"inline choice" if ambiguous else "direct"}), warm direct, inline error/cancel, busy/unsaved guards, case pin, Answer, follow-up, Save and Research Set', flush=True)

    checks = steps()

    def tick():
        nonlocal next_check, successful
        try:
            if time.monotonic() - start > (50 if hold_choice else 32):
                raise AssertionError(f'timed out at step {next_check}')
            if next_check():
                next_check = next(checks)
        except StopIteration:
            successful = True
            if hold:
                ui.GLib.timeout_add_seconds(90, lambda: (app.quit(), False)[1])
            else:
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
        raise SystemExit(ui.main(['--brief-prep', sys.argv[-2], '--case-dir', sys.argv[-1]]))
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
            ambiguous = '--unambiguous' not in sys.argv
            filings = [('AOB-two.pdf', 'AOB', 'An opening brief.'), ('RB.pdf', 'RB', 'Respondent text.')]
            if ambiguous:
                filings.append(('AOB-one.pdf', 'AOB', 'Another opening brief.'))
            for filename, role, body in filings:
                pdf(original / 'nested' / filename, ['Court of Appeal', 'B123456', TITLE[role]], [body])
            pdf(other / 'MTD.pdf', ['Court of Appeal', 'D234567', TITLE['MTD']], ['Motion text.'])
            (root / 'selection').write_text(original.name)
            raise SystemExit(primary(root, original, other, ambiguous=ambiguous,
                                     hold_choice='--hold-choice' in sys.argv, hold='--hold' in sys.argv))
