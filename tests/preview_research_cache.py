"""Manual isolated full-window acceptance. Run with uv run python tests/preview_research_cache.py.

Only synthetic data. Controls: F5 focus rule, F6 light, F7 dark,
F8 verify checked rule and remove it, F9 stress, F10 reload saved set.
F11 cycles selected/hover/selected-hover/backdrop/focus states on every item.
These controls are process-local; F8 deliberately modifies only this fixture.
For actual Libadwaita high contrast launch with ADW_DEBUG_HIGH_CONTRAST=1.
No normal app identity, discovery, network or model work.
Optional OLL_PREVIEW_BEFORE points at a git-show copy of the old app module.
"""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-cache-preview-"))
for key, value in {
    "OPEN_LAW_LENS_CONFIG": "config.json", "OPEN_LAW_LENS_CACHE_DIR": "cache",
    "OPEN_LAW_LENS_LIBRARY_DB": "library.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DB": "briefs.sqlite3",
}.items():
    os.environ[key] = str(ROOT / value)
os.environ.pop("COURTLISTENER_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from test_research_cache_sidebar import seed, rows
if before := os.environ.get("OLL_PREVIEW_BEFORE"):
    spec = importlib.util.spec_from_file_location("open_law_lens.preview_before", before)
    ui = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ui
    spec.loader.exec_module(ui)

from gi.repository import Gio


def blocked(*args, **kwargs):
    raise AssertionError("Network/model work forbidden in synthetic preview")


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        return None

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass

    def _on_case_selected(self, *args):
        # Retain normal selection dispatch; payloads are local, network blocked.
        return super()._on_case_selected(*args)


def activate(app):
    window = Preview(app)
    window.set_title("Synthetic Research Cache — " + ("BEFORE" if before else "AFTER"))
    seed(window.client.cache)
    window.client.library.save_research_set("Synthetic", window.client.cache)
    window._load_cached_cases()
    manager = ui.Adw.StyleManager.get_default()
    manager.set_color_scheme(ui.Adw.ColorScheme.FORCE_LIGHT)
    controller = ui.Gtk.EventControllerKey()
    controller.set_propagation_phase(ui.Gtk.PropagationPhase.CAPTURE)
    state_index = 0

    def fingerprint():
        original = rows(window)
        checks = [r.get_child().get_last_child().get_last_child().get_active()
                  for r in original if r.get_selectable()]
        scroller = window.case_list.get_ancestor(ui.Gtk.ScrolledWindow)
        return (original, window.case_list.get_selected_row(), checks,
                scroller.get_vadjustment().get_value(),
                window.client.cache.active_research_set_metadata())

    def key(_controller, keyval, _keycode, _state):
        name = ui.Gdk.keyval_name(keyval)
        nonlocal state_index
        before_state = fingerprint()
        if name == "F5":
            rule = next(r for r in rows(window) if getattr(r, "_open_law_lens_authority_type", "") == "rule")
            rule.grab_focus()
            window.case_list.select_row(rule)
            assert window._selected_rule["rule_id"] == "CRC:8.11"
            assert "Rule text" in window._reader_text
            print("RULE activation PASS; Tab twice then Space checks its agent checkbox", flush=True)
        elif name == "F8":
            rule = next(r for r in rows(window) if getattr(r, "_open_law_lens_authority_type", "") == "rule")
            assert window.client.cache.is_rule_agent_selected("CRC:8.11")
            assert rule.get_child().get_last_child().get_last_child().get_active()
            rule.get_child().get_last_child().get_first_child().emit("clicked")
            assert not window.client.cache.list_rule_entries()
            assert len(window.client.cache.list_statute_entries()) == 1
            assert [r._open_law_lens_cache_count for r in rows(window) if not r.get_selectable()] == [1, 1, 1, 1]
            print("CHECK persistence + typed REMOVE/count PASS", flush=True)
        elif name == "F11":
            states = (ui.Gtk.StateFlags.SELECTED, ui.Gtk.StateFlags.PRELIGHT,
                      ui.Gtk.StateFlags.SELECTED | ui.Gtk.StateFlags.PRELIGHT,
                      ui.Gtk.StateFlags.SELECTED | ui.Gtk.StateFlags.BACKDROP,
                      ui.Gtk.StateFlags.SELECTED | ui.Gtk.StateFlags.PRELIGHT | ui.Gtk.StateFlags.FOCUSED | ui.Gtk.StateFlags.FOCUS_VISIBLE,
                      ui.Gtk.StateFlags.NORMAL)
            for row in rows(window):
                if row.get_selectable():
                    row.set_state_flags(states[state_index], True)
            print("STATE", state_index, states[state_index], flush=True)
            state_index = (state_index + 1) % len(states)
        elif name in ("F6", "F7"):
            manager.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK if name == "F7" else ui.Adw.ColorScheme.FORCE_LIGHT)
            assert fingerprint() == before_state
            print("APPEARANCE", name, "dark", manager.get_dark(), "hc", manager.get_high_contrast(), flush=True)
        elif name == "F9":
            for i in range(105):
                window.client.cache.upsert_statute({"statute_id": f"SYN:{i}", "title": f"Synthetic long wrapped statute title for sidebar stress and control alignment {i}", "text": "Synthetic text"})
            window._load_cached_cases()
            print("STRESS", len(rows(window)), flush=True)
        elif name == "F10":
            window.client.library.load_research_set_into_cache("Synthetic", window.client.cache)
            window._load_cached_cases()
            assert not window.client.cache.active_research_set_metadata()["dirty"]
            print("RELOAD clean", flush=True)
        else:
            return False
        return True

    controller.connect("key-pressed", key)
    window.add_controller(controller)
    window.present()
    print("READY", os.getpid(), ROOT, "hc", manager.get_high_contrast(), flush=True)
    if os.environ.get("ADW_DEBUG_HIGH_CONTRAST") == "1":
        assert manager.get_high_contrast()
        if not before:
            assert window.case_list.has_css_class("cache-high-contrast")


with patch.object(socket.socket, "connect", blocked):
    app = ui.Adw.Application(application_id="com.mcglaw.OpenLawLens.CachePreview", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    app.run([])
