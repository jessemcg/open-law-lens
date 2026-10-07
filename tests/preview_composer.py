"""Synthetic composer using the actual application builder and CSS.

Run through project-env with paired disposable source/environment overrides.
--auto checks sizing and selection, then exits. --full-window retains the
synthetic Research Cache, reader and Answer/Session controls for integration
inspection. Otherwise use Tab/Shift+Tab
and Space normally; F6/F7 change light/dark appearance, F8/F9 set wide/narrow
widths, and F10 cycles modes. OLL_PREVIEW_DARK=1 starts dark;
ADW_DEBUG_HIGH_CONTRAST=1 enables process-local Libadwaita high contrast.
OLL_PREVIEW_LARGE=1 increases font size. All state is temporary; no current-case
discovery, network connections, or model launches.
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
    settings = ui.Gtk.Settings.get_default()
    # Where supported, disable GTK's short focus-indicator timeout in this
    # process only so desktop capture latency cannot mask keyboard focus.
    if settings.find_property("gtk-keyboard-focus-visible-timeout") is not None:
        settings.set_property("gtk-keyboard-focus-visible-timeout", 0)
    if os.getenv("OLL_PREVIEW_LARGE"):
        settings.set_property("gtk-xft-dpi", 144 * 1024)
    composer = owner._composer_message_label.get_parent().get_parent()
    full_window = "--full-window" in sys.argv
    wide, narrow, height = (1400, 900, 700) if full_window else (980, 540, 180)
    if full_window:
        from test_research_cache_sidebar import seed

        seed(owner.client.cache)
        owner._load_cached_cases()
        owner._set_reader_header("Synthetic reader", subtitle="Composer styling acceptance")
        owner.reader_buffer.set_text("Synthetic text only. No research or model calls.")
        owner._agent_answer_button.set_active(True)
        owner._agent_output_header.set_visible(True)
        owner._agent_subview_strip.set_visible(True)
        window = owner
    else:
        composer.get_parent().remove(composer)
        window = ui.Gtk.ApplicationWindow(application=app)
        window.set_child(composer)
    window.set_title("Synthetic Composer — isolated acceptance")
    window.set_default_size(wide, height)
    modes = (ui.AGENT_MODE_GENERAL, ui.AGENT_MODE_CASE, ui.AGENT_MODE_BRIEF,
             ui.QUERY_MODE_BRIEF_SEARCH, ui.AGENT_MODE_APPEAL)
    controls = composer.get_first_child()
    assert controls.has_css_class("composer-controls")
    assert not controls.get_focusable()
    for index in range(2):
        assert not controls.get_child_at_index(index).get_focusable()
    assert len(owner._agent_mode_buttons) == 5
    if os.environ.get("ADW_DEBUG_HIGH_CONTRAST") == "1":
        assert manager.get_high_contrast()

    def key(_controller, keyval, _keycode, _state):
        name = ui.Gdk.keyval_name(keyval)
        if name in ("Tab", "ISO_Left_Tab", "space"):
            def report_focus():
                focused = window.get_focus()
                print("FOCUS", name, type(focused).__name__,
                      focused.get_state_flags() if focused else None,
                      focused.has_visible_focus() if focused else False, flush=True)
                if isinstance(focused, ui.Gtk.ToggleButton):
                    snapshot = ui.Gtk.Snapshot()
                    snapshot.render_focus(focused.get_style_context(), 0, 0,
                                          focused.get_width(), focused.get_height())
                    node = snapshot.to_node()
                    assert node is not None, "Missing button focus outline"
                    assert all(width > 0 for width in node.get_widths())
                    assert all(color.alpha > 0 for color in node.get_colors())
                    print("OUTLINE", list(node.get_widths()),
                          [c.to_string() for c in node.get_colors()], flush=True)
                return False
            ui.GLib.timeout_add(250, report_focus)
        if name in ("F6", "F7"):
            manager.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK if name == "F7"
                                     else ui.Adw.ColorScheme.FORCE_LIGHT)
        elif name in ("F8", "F9"):
            window.set_default_size(wide if name == "F8" else narrow, height)
        elif name == "F10":
            mode = modes[(modes.index(owner._selected_agent_mode) + 1) % len(modes)]
            owner._agent_mode_buttons[mode].emit("clicked")
        else:
            return False
        print("STATE", owner._selected_agent_mode, "dark", manager.get_dark(),
              "hc", manager.get_high_contrast(), flush=True)
        return True

    controller = ui.Gtk.EventControllerKey()
    controller.set_propagation_phase(ui.Gtk.PropagationPhase.CAPTURE)
    controller.connect("key-pressed", key)
    window.add_controller(controller)
    widths = iter((1400, 1400, 1200, 1100, 1000, 900) if full_window
                  else (980, 980, 900, 760, 660, 580, 540))
    observed_wrapping = set()

    def advance():
        try:
            width = next(widths)
        except StopIteration:
            assert observed_wrapping == {False, True}, "Need both wide and wrapped layouts"
            for mode in modes:
                owner._agent_mode_buttons[mode].emit("clicked")
                assert owner._selected_agent_mode == mode
                assert owner._agent_mode_buttons[mode].get_active()
                assert sum(b.get_active() for b in owner._agent_mode_buttons.values()) == 1
                assert [m for m, b in owner._agent_mode_buttons.items()
                        if b.has_css_class("focus-ai-view-active")] == [mode]
                if mode in (ui.QUERY_MODE_BRIEF_SEARCH, ui.AGENT_MODE_APPEAL):
                    assert not owner._agent_followup_entry.get_visible()
                else:
                    assert owner._agent_followup_entry.get_visible()
                    assert owner._agent_ask_row.get_homogeneous()
            owner._set_agent_mode(ui.AGENT_MODE_GENERAL)
            if full_window:
                owner._agent_output_header.set_visible(True)
                owner._agent_subview_strip.set_visible(True)
            print("PASS selection, single-entry modes; READY", os.getpid(), ROOT,
                  "dark", manager.get_dark(), "hc", manager.get_high_contrast(), flush=True)
            if "--auto" in sys.argv:
                app.quit()
            return False
        window.set_default_size(width, height)
        window.present()
        # A compositor may restore this preview maximized; do not mistake
        # repeated full-screen allocations for narrow-window acceptance.
        ui.GLib.timeout_add(70, lambda: window.unmaximize())
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
        first_width, second_width, _, _ = controls._sizes()
        wrapped = controls.get_width() < first_width + second_width
        observed_wrapping.add(wrapped)
        if not wrapped:
            assert abs(mb.get_x() - sb.get_x() - sb.get_width()) <= 1
            assert abs(
                (mb.get_y() + mb.get_height() / 2)
                - (sb.get_y() + sb.get_height() / 2)
            ) <= 1
        else:
            assert mb.get_y() >= sb.get_y() + sb.get_height()
            assert abs(mb.get_x() - sb.get_x()) <= 1
        button_bounds = []
        for mode in modes[:4]:
            ok, bounds = owner._agent_mode_buttons[mode].compute_bounds(composer)
            assert ok
            button_bounds.append(bounds)
        for previous, current in zip(button_bounds, button_bounds[1:]):
            assert abs(current.get_x() - previous.get_x() - previous.get_width()) <= 1
        assert abs(mb.get_height() - sb.get_height()) <= 1, (
            mb.get_height(), sb.get_height()
        )
        heights = [b.get_height() for b in owner._agent_mode_buttons.values()]
        assert max(heights) - min(heights) <= 1, heights
        ok, ib = owner._agent_ask_row.compute_bounds(composer)
        assert ok
        assert mb.get_y() + mb.get_height() <= ib.get_y()
        assert sb.get_y() + sb.get_height() <= ib.get_y()
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
