"""Small setup/about surface. No settings writes or implicit model/network checks."""
from __future__ import annotations

import json
import threading
from gi.repository import Adw, Gdk, GLib, Gtk

from .diagnostics import format_report, report

GUIDANCE = (
    "Open Law Lens focuses on California law. Configure a CourtListener token in Settings "
    "for reliable case research. Citation lookup and reading do not require Pi, a briefs archive, "
    "or Current Case integration.\n\n"
    "Agent workflows are optional: install Pi and authorize your chosen provider in Pi itself, "
    "then review the five independent workflow models in Settings. Selected case facts, brief "
    "text and research requests can be sent to that model provider. Local storage does not "
    "mean entirely local processing. Never submit material you are not authorized to disclose.\n\n"
    "Browser recovery is optional and desktop-dependent. It never bypasses a human challenge "
    "or relaxes exact-target verification. No browser or desktop permissions are changed here."
)


class SetupWindow(Adw.ApplicationWindow):
    def __init__(self, parent: Gtk.Window) -> None:
        super().__init__(application=parent.get_application(), transient_for=parent, modal=False)
        self.set_title("Setup / Diagnostics — Open Law Lens")
        self.set_default_size(760, 720)
        self._generation = 0
        self._report: dict | None = None
        self.connect("close-request", self._on_close)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Setup / Diagnostics", subtitle="About Open Law Lens"))
        root.append(header)
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12, margin_top=12, margin_bottom=12)
        for index, (label, callback) in enumerate((
            ("Refresh local checks", lambda *_: self.refresh()),
            ("Check Pi setup (offline)", lambda *_: self.refresh(agent_check=True)),
            ("Test CourtListener connection", lambda *_: self.refresh(connectivity=True)),
            ("Copy redacted JSON", self._copy),
        )):
            if index % 2 == 0:
                row = Gtk.Box(spacing=8)
                actions.append(row)
            button = Gtk.Button(label=label, hexpand=True)
            button.connect("clicked", callback)
            row.append(button)
        root.append(actions)
        self.text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                 left_margin=18, right_margin=18, top_margin=12, bottom_margin=18)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.text)
        root.append(scroll)
        self.set_content(root)
        self.refresh()

    def _on_close(self, *_args) -> bool:
        self._generation += 1
        return False

    def _copy(self, *_args) -> None:
        if self._report is not None:
            Gdk.Display.get_default().get_clipboard().set(json.dumps(self._report, indent=2))

    def refresh(self, *, agent_check: bool = False, connectivity: bool = False) -> None:
        self._generation += 1
        generation = self._generation
        self._report = None
        self.text.get_buffer().set_text(GUIDANCE + "\n\nChecking capabilities…")

        def worker() -> None:
            value = None
            try:
                value = report(agent_check=agent_check, connectivity=connectivity)
                summary = format_report(value)
            except Exception:
                # Never expose exception text: paths or service errors can
                # contain private data. A failed probe must not strand the UI.
                summary = "Diagnostics could not complete. Check the installed runtime and retry local checks. No settings were changed."

            def finish() -> bool:
                if generation == self._generation:
                    self._report = value
                    self.text.get_buffer().set_text(GUIDANCE + "\n\n" + summary)
                return False
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()
