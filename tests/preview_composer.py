"""Isolated synthetic composer: uv run python tests/preview_composer.py --auto.

Use OLL_PREVIEW_DARK=1 and OLL_PREVIEW_LARGE=1 for appearance/font variants.
No current-case discovery, network connections, or model launches.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-composer-preview-"))
for key, name in {
    "OPEN_LAW_LENS_CONFIG": "config.json",
    "OPEN_LAW_LENS_CACHE_DIR": "cache",
    "OPEN_LAW_LENS_LIBRARY_DB": "library.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DB": "briefs.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DIR": "prior-briefs",
}.items():
    os.environ[key] = str(ROOT / name)
os.environ.pop("COURTLISTENER_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from gi.repository import Gio


def blocked(*_args, **_kwargs):
    raise AssertionError("Network/model launch forbidden in synthetic preview")


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        return None

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass

    def _on_agent_launch(self, *args, **kwargs):
        blocked()

    def _launch_agent_with_prompt(self, *args, **kwargs):
        blocked()

    def start_appeal_issue_assessment(self, *args, **kwargs):
        blocked()


def activate(app):
    manager = ui.Adw.StyleManager.get_default()
    manager.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK if os.getenv("OLL_PREVIEW_DARK")
                             else ui.Adw.ColorScheme.FORCE_LIGHT)
    ui.Gtk.IconTheme.get_for_display(ui.Gdk.Display.get_default()).add_search_path(
        str(Path(ui.__file__).resolve().parent / "icons")
    )
    owner = Preview(app)
    if os.getenv("OLL_PREVIEW_LARGE"):
        settings = ui.Gtk.Settings.get_default()
        settings.set_property("gtk-xft-dpi", 144 * 1024)
    composer = owner._composer_message_label.get_parent().get_parent()
    composer.get_parent().remove(composer)
    window = ui.Gtk.ApplicationWindow(application=app, title="Synthetic Composer — isolated acceptance")
    window.set_default_size(980, 180)
    window.set_child(composer)
    widths = iter((980, 980, 900, 760, 660, 580))

    def advance():
        try:
            width = next(widths)
        except StopIteration:
            for mode in (ui.AGENT_MODE_GENERAL, ui.AGENT_MODE_CASE,
                         ui.AGENT_MODE_BRIEF, ui.QUERY_MODE_BRIEF_SEARCH):
                owner._set_agent_mode(mode)
                assert owner._selected_agent_mode == mode
                assert owner._agent_mode_buttons[mode].get_active()
                if mode == ui.QUERY_MODE_BRIEF_SEARCH:
                    assert not owner._agent_followup_entry.get_visible()
                else:
                    assert owner._agent_followup_entry.get_visible()
                    assert owner._agent_ask_row.get_homogeneous()
            owner._set_agent_mode(ui.AGENT_MODE_GENERAL)
            if "--auto" in sys.argv:
                app.quit()
            return False
        window.set_default_size(width, 180)
        window.present()
        ui.GLib.timeout_add(350, lambda: check(width))
        return False

    def check(width):
        controls = composer.get_first_child()
        strip = controls.get_child_at_index(0).get_child()
        menu = controls.get_child_at_index(1).get_child()
        ok, sb = strip.compute_bounds(composer)
        assert ok
        ok, mb = menu.compute_bounds(composer)
        assert ok
        ok, cb = composer.compute_bounds(composer)
        assert ok
        ok, fb = controls.compute_bounds(composer)
        assert ok
        assert mb.get_x() >= sb.get_x()
        assert mb.get_x() + mb.get_width() <= cb.get_width() + 1
        assert mb.get_y() >= sb.get_y()
        if cb.get_width() >= sb.get_width() + mb.get_width() + 12:
            assert abs(mb.get_x() - sb.get_x() - sb.get_width() - 6) <= 1
            assert abs(
                (mb.get_y() + mb.get_height() / 2)
                - (sb.get_y() + sb.get_height() / 2)
            ) <= 1
        else:
            assert mb.get_y() >= sb.get_y() + sb.get_height()
        assert abs(mb.get_height() - sb.get_height()) <= 1, (
            mb.get_height(), sb.get_height()
        )
        assert owner._appeal_issue_menu_button.get_popover() is not None
        print(
            f"requested={width} allocated={cb.get_width():.0f} "
            f"strip={sb.get_width():.0f} flow={fb.get_width():.0f} "
            f"menu=({mb.get_x():.0f},{mb.get_y():.0f},"
            f"{mb.get_width():.0f},{mb.get_height():.0f})",
            flush=True,
        )
        ui.GLib.idle_add(advance)
        return False

    advance()


with patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked):
    app = ui.Adw.Application(application_id="com.mcglaw.OpenLawLens.ComposerPreview",
                             flags=Gio.ApplicationFlags.NON_UNIQUE)
    failed = False

    def failure(kind, value, traceback):
        global failed
        failed = True
        sys.__excepthook__(kind, value, traceback)
        app.quit()

    sys.excepthook = failure
    app.connect("activate", activate)
    app.run([])
    sys.exit(1 if failed else 0)
