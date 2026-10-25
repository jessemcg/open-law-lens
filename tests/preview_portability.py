"""Quiet standalone startup and task-time feedback using synthetic native GTK.

Disposable source/environment only. --hold leaves the final synthetic main window
visible for local observation; no Pi, service, model or document extraction calls.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-public-gui-"))
for name, suffix in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("PI_CODING_AGENT_DIR", "pi")):
    os.environ[name] = str(ROOT / suffix)
for name in ("OPEN_LAW_LENS_CONFIG", "OPEN_LAW_LENS_CACHE_DIR", "OPEN_LAW_LENS_LIBRARY_DB",
             "OPEN_LAW_LENS_PRIOR_BRIEFS_DIR", "OPEN_LAW_LENS_PRIOR_BRIEFS_DB", "COURTLISTENER_TOKEN",
             "OPEN_LAW_LENS_CURRENT_CASE_FILE", "OPEN_LAW_LENS_CASE_ROOTS"):
    os.environ.pop(name, None)
os.environ.update(OPEN_LAW_LENS_STORAGE="standalone", GSETTINGS_BACKEND="memory")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.config import config_path, load_config
from open_law_lens.pi_runtime import PiRuntimeCatalog, PiExecutableMissing
from open_law_lens.task_prerequisites import MESSAGES, Reason
from gi.repository import Gio

FAILURES = []


def activate(application):
    window = ui.OpenLawLensApp._main_window(application)
    window.set_title("Synthetic Quiet Open Law Lens")
    assert ui.OpenLawLensApp._main_window(application) is window
    assert len(application.get_windows()) == 1
    assert not config_path().exists()
    assert window.lookup_action('setup_diagnostics') is None
    assert load_config().reader_font_family == 'Linux Libertine O'
    assert load_config().reader_font_size_pt == 14
    window._set_reader_text('Synthetic token-free reading. No authority lookup needed.')
    assert 'Synthetic token-free reading' in window.reader_buffer.get_text(
        window.reader_buffer.get_start_iter(), window.reader_buffer.get_end_iter(), True)
    window.prior_briefs.source_dir.mkdir(parents=True, exist_ok=True)
    window._set_agent_mode(ui.QUERY_MODE_BRIEF_SEARCH)
    window.agent_question_entry.set_text('synthetic exact phrase')
    window._on_agent_launch(None)  # real local worker, empty disposable archive
    pi_check.assert_not_called()
    model_catalog.assert_not_called()
    window._set_agent_mode(ui.AGENT_MODE_GENERAL)
    window._agent_answer_buffer.set_text('Synthetic saved answer — preserved.')
    window.agent_question_entry.set_text('Synthetic legal question?')
    window._on_agent_launch(None)
    assert window._composer_message_label.get_text() == MESSAGES[Reason.TOKEN]
    settings = ui.SettingsWindow(window)
    settings.set_title("Synthetic Quiet Settings")
    settings.present()
    phase = 0
    deadline = time.monotonic() + 20
    ready = Mock()
    window._prepare_agent_question = ready

    def check():
        nonlocal settings, phase
        try:
            assert time.monotonic() < deadline, 'Synthetic GUI acceptance timed out'
            if not settings._pi_profiles_ready:
                return True
            if phase == 0:
                assert settings.reader_font_size_row.get_value() == 14
                assert settings.reader_font_family_values[settings.reader_font_family_row.get_selected()] == 'Linux Libertine O'
                settings.token_row.set_text('synthetic-token')
                # Explicit alternatives remain authoritative after Save/reopen.
                settings.reader_font_size_row.set_value(11)
                settings.reader_font_family_row.set_selected(settings.reader_font_family_values.index('Noto Serif'))
                settings._on_save_clicked(None)
                assert load_config().courtlistener_token == 'synthetic-token'
                settings.close()
                window._on_agent_launch(None)
                assert window._composer_message_label.get_text() == MESSAGES[Reason.PI_MISSING]
                settings = ui.SettingsWindow(window)
                settings.present()
                phase = 1
            elif phase == 1:
                assert settings.token_row.get_text() == 'synthetic-token'
                assert settings.reader_font_size_row.get_value() == 11
                assert settings.reader_font_family_values[settings.reader_font_family_row.get_selected()] == 'Noto Serif'
                settings.close()
                pi_check.side_effect = None
                window._on_agent_launch(None)
                assert window._composer_message_label.get_text() == MESSAGES[Reason.TERMINAL]
                ui.Vte = object()  # checks only, never used for spawning
                window._agent_terminal = object()
                window._on_agent_launch(None)
                phase = 2
            else:
                if window._composer_message_label.get_text() != MESSAGES[Reason.MODELS_EMPTY]:
                    return True
                assert window.agent_question_entry.get_text() == 'Synthetic legal question?'
                buffer = window._agent_answer_buffer
                assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True) == 'Synthetic saved answer — preserved.'
                ready.assert_not_called()
                assert len(application.get_windows()) == 1
                print(f'PASS quiet/repeated startup; no diagnostics action/window; token/Pi/VTE/model messages; preserved question/answer; token-free reader/local search; Settings Save/reopen; Libertine O/14 defaults and explicit Noto Serif/11; synthetic root={ROOT}', flush=True)
                if '--hold' not in sys.argv:
                    application.quit()
                return False
        except Exception as exc:
            FAILURES.append(repr(exc))
            print(f'FAIL {exc!r}', flush=True)
            application.quit()
            return False
        return True
    ui.GLib.timeout_add(150, check)


application = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.SyntheticQuiet',
                                 flags=Gio.ApplicationFlags.NON_UNIQUE)
with patch.object(ui, 'Vte', None), \
     patch.object(ui, 'available_pi_runtime_catalog', return_value=PiRuntimeCatalog((), None, 'medium')), \
     patch.object(ui.task_prerequisites.pi_runtime, 'available_pi_runtime_catalog', return_value=PiRuntimeCatalog((), None, 'medium')) as model_catalog, \
     patch.object(ui.task_prerequisites.pi_runtime, 'require_pi_executable', side_effect=PiExecutableMissing()) as pi_check, \
     patch.object(ui.CourtListenerClient, '_request_json', side_effect=AssertionError('No network in preview')):
    application.connect('activate', activate)
    application.run([])
raise SystemExit(bool(FAILURES))
