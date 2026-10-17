"""Synthetic native Setup, missing-VTE reader and Settings save/reopen acceptance.

Run only from a disposable source/environment. --hold keeps Setup visible for
local desktop observation; close that window when finished. No real Pi/network.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-public-gui-"))
for name, suffix in (("HOME", "home"), ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                     ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state"), ("PI_CODING_AGENT_DIR", "pi")):
    os.environ[name] = str(ROOT / suffix)
for name in ("OPEN_LAW_LENS_CONFIG", "OPEN_LAW_LENS_CACHE_DIR", "OPEN_LAW_LENS_LIBRARY_DB",
             "OPEN_LAW_LENS_PRIOR_BRIEFS_DIR", "OPEN_LAW_LENS_PRIOR_BRIEFS_DB", "COURTLISTENER_TOKEN",
             "OPEN_LAW_LENS_CURRENT_CASE_FILE", "OPEN_LAW_LENS_CASE_ROOTS"):
    os.environ.pop(name, None)
os.environ.update(OPEN_LAW_LENS_STORAGE="standalone", OPEN_LAW_LENS_PI_BIN="/nonexistent/pi",
                  OPEN_LAW_LENS_PI_NODE_BIN="", GSETTINGS_BACKEND="memory")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.config import config_path, load_config
from open_law_lens.diagnostics_ui import SetupWindow
from open_law_lens.pi_runtime import PiRuntimeCatalog
from gi.repository import Gio

FAILURES = []


def activate(application):
    window = ui.OpenLawLensWindow(application)
    window.set_title("Synthetic Public Open Law Lens")
    window.present()
    setup = SetupWindow(window)
    setup.set_title("Synthetic Open Law Lens Setup / Diagnostics")
    setup.present()
    settings = ui.SettingsWindow(window)
    settings.set_title("Synthetic Public Settings")
    settings.present()
    phase = 0

    def check():
        nonlocal settings, phase
        try:
            if setup._report is None or not settings._pi_profiles_ready:
                return True
            if phase == 0:
                assert window._agent_terminal is None  # VTE deliberately absent
                assert not config_path().exists()
                assert "not configured" in window._current_case_error
                assert setup._report['capabilities']['core_gui']['status'] == 'ready'
                assert setup._report['capabilities']['agent_workflows']['status'] == 'missing'
                assert "can be sent to that model provider" in setup.text.get_buffer().get_text(
                    setup.text.get_buffer().get_start_iter(), setup.text.get_buffer().get_end_iter(), True)
                settings.token_row.set_text("synthetic-token")
                settings._on_save_clicked(None)
                assert load_config().courtlistener_token == "synthetic-token"
                assert config_path().stat().st_mode & 0o777 == 0o600
                settings.close()
                settings = ui.SettingsWindow(window)
                settings.present()
                phase = 1
            else:
                assert settings.token_row.get_text() == "synthetic-token"
                settings.close()
                setup.present()
                print(f"PASS Setup/core reader without VTE/unconfigured Current Case/Settings save and reopen; synthetic root={ROOT}", flush=True)
                if '--hold' not in sys.argv:
                    application.quit()
                return False
        except Exception as exc:
            FAILURES.append(repr(exc))
            print(f"FAIL {exc!r}", flush=True)
            application.quit()
            return False
        return True
    ui.GLib.timeout_add(150, check)


application = ui.Adw.Application(application_id="com.mcglaw.OpenLawLens.SyntheticPortability",
                                 flags=Gio.ApplicationFlags.NON_UNIQUE)
with patch.object(ui, "Vte", None), patch.object(ui, "available_pi_runtime_catalog", return_value=PiRuntimeCatalog((), None, "medium")):
    application.connect("activate", activate)
    application.run([])
raise SystemExit(bool(FAILURES))
