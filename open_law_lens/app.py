from __future__ import annotations

import os
import signal
import tempfile
import threading
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # type: ignore

Vte = None
try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte as VteModule  # type: ignore

    Vte = VteModule
except (ImportError, ValueError):
    Vte = None

from . import APP_ID, APP_NAME
from .client import (
    CourtListenerClient,
    CourtListenerError,
    cluster_citation_line,
    cluster_title,
    opinion_text,
)
from .config import AppConfig, load_config, save_config


PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENT_WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-codex-agent-vte.sh"
DEFAULT_CODEX_BIN = "codex"
DEFAULT_CODEX_PROFILE = "fireworks"
READER_BG = "#ffffff"
READER_FG = "#000000"
TERMINAL_DARK_FOREGROUND = "#f2f4f8"
TERMINAL_DARK_BACKGROUND = "#3d3d3d"
TERMINAL_LIGHT_FOREGROUND = "#20242c"
TERMINAL_LIGHT_BACKGROUND = "#f5f5f5"
TERMINAL_PALETTE = (
    "#2e3436",
    "#cc0000",
    "#4e9a06",
    "#c4a000",
    "#3465a4",
    "#75507b",
    "#06989a",
    "#d3d7cf",
    "#555753",
    "#ef2929",
    "#8ae234",
    "#fce94f",
    "#729fcf",
    "#ad7fa8",
    "#34e2e2",
    "#eeeeec",
)


def _rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    if not color.parse(spec):
        raise ValueError(f"Invalid color: {spec}")
    return color


def _apply_terminal_theme(terminal: Any) -> None:
    dark = Adw.StyleManager.get_default().get_dark()
    foreground = _rgba(TERMINAL_DARK_FOREGROUND if dark else TERMINAL_LIGHT_FOREGROUND)
    background = _rgba(TERMINAL_DARK_BACKGROUND if dark else TERMINAL_LIGHT_BACKGROUND)
    palette = [_rgba(spec) for spec in TERMINAL_PALETTE]
    terminal.set_colors(foreground, background, palette)
    terminal.set_color_background(background)
    terminal.set_color_foreground(foreground)
    terminal.set_clear_background(True)


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, parent: "OpenLawLensWindow") -> None:
        super().__init__(application=parent.get_application(), transient_for=parent)
        self.parent_window = parent
        self.set_title("Settings")
        self.set_default_size(560, 260)
        self.set_modal(True)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Settings"))
        toolbar_view.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        group = Adw.PreferencesGroup(title="CourtListener")
        self.token_row = self._build_token_row()
        self.token_row.set_text(load_config().courtlistener_token)
        group.add(self.token_row)
        outer.append(group)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        save_button = Gtk.Button(label="Save Settings")
        save_button.add_css_class("suggested-action")
        save_button.connect("clicked", self._on_save_clicked)
        buttons.append(save_button)
        outer.append(buttons)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim-label")
        outer.append(self.status_label)

        toolbar_view.set_content(outer)
        self.set_content(toolbar_view)

    def _build_token_row(self) -> Adw.EntryRow:
        password_row_cls = getattr(Adw, "PasswordEntryRow", None)
        if password_row_cls is not None:
            return password_row_cls(title="CourtListener API Token")
        row = Adw.EntryRow(title="CourtListener API Token")
        try:
            row.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        except AttributeError:
            pass
        set_visibility = getattr(row, "set_visibility", None)
        if callable(set_visibility):
            set_visibility(False)
        return row

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        token = self.token_row.get_text().strip()
        save_config(AppConfig(courtlistener_token=token))
        self.parent_window.reload_settings()
        self.status_label.set_text("Settings saved.")


class OpenLawLensWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.client = CourtListenerClient.default()
        self._clusters: list[dict[str, Any]] = []
        self._selected_cluster: dict[str, Any] | None = None
        self._agent_terminal: Any | None = None
        self._agent_pid: int | None = None
        self._settings_window: SettingsWindow | None = None

        self.set_title(APP_NAME)
        self.set_default_size(1260, 860)
        self._install_css()
        self._install_actions()
        self.set_content(self._build_ui())

    def _install_actions(self) -> None:
        settings = Gio.SimpleAction.new("settings", None)
        settings.connect("activate", self._on_open_settings)
        self.add_action(settings)

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            f"""
            .case-reader-frame {{
              background-color: {READER_BG};
              border-radius: 8px;
              padding: 8px;
            }}
            .case-reader-frame > scrolledwindow,
            .case-reader-frame > scrolledwindow > viewport {{
              background-color: {READER_BG};
            }}
            textview.case-reader {{
              color: {READER_FG};
              background-color: {READER_BG};
              font-family: "Noto Serif", "Liberation Serif", "DejaVu Serif", serif;
              font-size: 12pt;
              line-height: 1.25;
            }}
            textview.case-reader text {{
              color: {READER_FG};
              background-color: {READER_BG};
            }}
            .agent-terminal-frame {{
              border-radius: 8px;
              background-color: @window_bg_color;
              padding: 6px;
            }}
            .agent-terminal {{
              border-radius: 8px;
              padding: 8px;
            }}
            .sidebar-box {{
              border-right: 1px solid alpha(@window_fg_color, 0.12);
            }}
            """.encode("utf-8")
        )
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_ui(self) -> Gtk.Widget:
        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=APP_NAME, subtitle="CourtListener citation lookup"))
        header.pack_end(self._build_menu_button())
        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(10)
        root.set_margin_bottom(10)
        root.set_margin_start(10)
        root.set_margin_end(10)

        lookup_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.citation_entry = Gtk.Entry()
        self.citation_entry.set_hexpand(True)
        self.citation_entry.set_placeholder_text("Citation, e.g. 576 U.S. 644")
        self.citation_entry.connect("activate", self._on_lookup_clicked)
        lookup_row.append(self.citation_entry)

        lookup_button = Gtk.Button(icon_name="system-search-symbolic")
        lookup_button.set_tooltip_text("Look up citation")
        lookup_button.connect("clicked", self._on_lookup_clicked)
        lookup_row.append(lookup_button)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim-label")
        lookup_row.append(self.status_label)
        root.append(lookup_row)

        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_hexpand(True)
        main.set_vexpand(True)
        main.set_start_child(self._build_sidebar())
        main.set_resize_start_child(False)
        main.set_shrink_start_child(False)
        main.set_end_child(self._build_right_side())
        root.append(main)

        toolbar_view.set_content(root)
        return toolbar_view

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Settings", "win.settings")
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_tooltip_text("Menu")
        button.set_menu_model(menu)
        return button

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(320, -1)
        box.add_css_class("sidebar-box")
        heading = Gtk.Label(label="Cases", xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        self.case_list = Gtk.ListBox()
        self.case_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.case_list.connect("row-selected", self._on_case_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.case_list)
        scroller.set_vexpand(True)
        box.append(scroller)
        return box

    def _build_right_side(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_hexpand(True)
        box.set_vexpand(True)
        box.append(self._build_agent_box())

        self.reader_buffer = Gtk.TextBuffer()
        self.reader_view = Gtk.TextView(buffer=self.reader_buffer)
        self.reader_view.set_editable(False)
        self.reader_view.set_cursor_visible(False)
        self.reader_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.reader_view.set_left_margin(22)
        self.reader_view.set_right_margin(22)
        self.reader_view.set_top_margin(18)
        self.reader_view.set_bottom_margin(18)
        self.reader_view.add_css_class("case-reader")

        reader_scroller = Gtk.ScrolledWindow()
        reader_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        reader_scroller.set_vexpand(True)
        reader_scroller.set_child(self.reader_view)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("case-reader-frame")
        frame.set_vexpand(True)
        frame.append(reader_scroller)
        box.append(frame)
        self.reader_buffer.set_text("Enter a citation to load a CourtListener case.")
        return box

    def _build_agent_box(self) -> Gtk.Widget:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        frame.add_css_class("agent-terminal-frame")
        frame.set_size_request(-1, 260)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.agent_entry = Gtk.Entry()
        self.agent_entry.set_hexpand(True)
        self.agent_entry.set_placeholder_text("Agent question about selected case")
        self.agent_entry.connect("activate", self._on_agent_launch)
        controls.append(self.agent_entry)

        launch_button = Gtk.Button(icon_name="utilities-terminal-symbolic")
        launch_button.set_tooltip_text("Launch Codex agent")
        launch_button.connect("clicked", self._on_agent_launch)
        controls.append(launch_button)
        frame.append(controls)

        if Vte is None:
            missing = Gtk.Label(
                label="Install GTK4 VTE packages to use the embedded Codex terminal.",
                xalign=0,
            )
            missing.add_css_class("dim-label")
            frame.append(missing)
            return frame

        terminal = Vte.Terminal()
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.add_css_class("agent-terminal")
        _apply_terminal_theme(terminal)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_agent_terminal_key_pressed)
        terminal.add_controller(key_controller)
        terminal.connect("child-exited", self._on_agent_exited)
        frame.append(terminal)
        self._agent_terminal = terminal
        return frame

    def _set_status(self, text: str) -> None:
        self.status_label.set_text(text)

    def reload_settings(self) -> None:
        self.client = CourtListenerClient.default()
        self._set_status("Settings saved.")

    def _on_open_settings(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.connect("close-request", self._on_settings_closed)
        self._settings_window.present()

    def _on_settings_closed(self, _window: Gtk.Window) -> bool:
        self._settings_window = None
        return False

    def _on_lookup_clicked(self, _widget: Gtk.Widget) -> None:
        citation = self.citation_entry.get_text().strip()
        if not citation:
            self._set_status("Enter a citation.")
            return
        self._set_status("Looking up citation...")
        self.reader_buffer.set_text("Loading...")
        thread = threading.Thread(target=self._lookup_worker, args=(citation,), daemon=True)
        thread.start()

    def _lookup_worker(self, citation: str) -> None:
        try:
            result = self.client.lookup_citation(citation)
            clusters = self.client.clusters_from_lookup(result)
            status = self._lookup_status_text(result, clusters)
            GLib.idle_add(self._apply_lookup_result, result, clusters, status)
        except (CourtListenerError, ValueError) as exc:
            GLib.idle_add(self._apply_error, str(exc))

    def _lookup_status_text(self, result: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> str:
        if not result:
            return "No citation found in text."
        statuses = [str(item.get("status", "")) for item in result if isinstance(item, dict)]
        if clusters:
            return f"{len(clusters)} case(s). Status: {', '.join(statuses)}"
        messages = [
            str(item.get("error_message", "")).strip()
            for item in result
            if isinstance(item, dict) and item.get("error_message")
        ]
        return messages[0] if messages else f"No matching cases. Status: {', '.join(statuses)}"

    def _apply_lookup_result(
        self,
        _result: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        status: str,
    ) -> bool:
        self._clusters = clusters
        self._selected_cluster = None
        while row := self.case_list.get_row_at_index(0):
            self.case_list.remove(row)
        for index, cluster in enumerate(clusters):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            title = Gtk.Label(label=cluster_title(cluster), xalign=0)
            title.set_wrap(True)
            citation = Gtk.Label(label=cluster_citation_line(cluster), xalign=0)
            citation.add_css_class("dim-label")
            citation.set_wrap(True)
            row_box.append(title)
            row_box.append(citation)
            row.set_child(row_box)
            row._open_law_lens_cluster_index = index
            self.case_list.append(row)
        self._set_status(status)
        if clusters:
            first = self.case_list.get_row_at_index(0)
            if first:
                self.case_list.select_row(first)
        else:
            self.reader_buffer.set_text(status)
        return False

    def _apply_error(self, message: str) -> bool:
        self._set_status(message)
        self.reader_buffer.set_text(message)
        return False

    def _on_case_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        index = getattr(row, "_open_law_lens_cluster_index", None)
        if not isinstance(index, int) or index < 0 or index >= len(self._clusters):
            return
        cluster = self._clusters[index]
        self._selected_cluster = cluster
        self.reader_buffer.set_text(f"Loading {cluster_title(cluster)}...")
        thread = threading.Thread(target=self._case_worker, args=(cluster,), daemon=True)
        thread.start()

    def _case_worker(self, cluster: dict[str, Any]) -> None:
        try:
            opinions = self.client.fetch_cluster_opinions(cluster)
            text_parts: list[str] = []
            title = cluster_title(cluster)
            citation = cluster_citation_line(cluster)
            header = title if not citation else f"{title}\n{citation}"
            text_parts.append(header)
            for opinion in opinions:
                text = opinion_text(opinion)
                if text:
                    text_parts.append(text)
            text = "\n\n".join(text_parts).strip()
            if not text:
                text = f"{header}\n\nNo opinion text found."
            GLib.idle_add(self.reader_buffer.set_text, text)
        except CourtListenerError as exc:
            GLib.idle_add(self._apply_error, str(exc))

    def _compose_agent_prompt(self, question: str) -> str:
        cluster = self._selected_cluster or {}
        cluster_id = cluster.get("id", "")
        title = cluster_title(cluster) if cluster else "No case selected"
        citation = cluster_citation_line(cluster) if cluster else ""
        return f"""You are working inside Open Law Lens.

Question:
{question}

Selected case:
- Title: {title}
- Citations: {citation}
- CourtListener cluster id: {cluster_id}
- Cache root: {self.client.cache.root}

Use the local Open Law Lens CLI and cached JSON before making network calls when possible:
- open-law-lens show-cache
- open-law-lens lookup-citation "<citation>"
- open-law-lens lookup-citation "<citation>" --text

For this version, do not modify app files or cache files unless explicitly asked. Focus on reading and explaining the selected CourtListener case data.""".strip()

    def _write_prompt_file(self, prompt: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            prefix="open-law-lens-agent-",
            suffix=".txt",
            delete=False,
        )
        with handle:
            handle.write(prompt)
        return Path(handle.name)

    def _on_agent_launch(self, _widget: Gtk.Widget) -> None:
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return
        question = self.agent_entry.get_text().strip() or "Review the selected case."
        prompt_path = self._write_prompt_file(self._compose_agent_prompt(question))
        self._stop_agent()
        if not AGENT_WRAPPER.is_file():
            self._set_status(f"Agent wrapper not found: {AGENT_WRAPPER}")
            return
        env = os.environ.copy()
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt_path),
                "OPEN_LAW_LENS_CACHE_DIR": str(self.client.cache.root),
                "CODEX_BIN": os.environ.get("OPEN_LAW_LENS_CODEX_BIN", DEFAULT_CODEX_BIN),
                "CODEX_PROFILE": os.environ.get("OPEN_LAW_LENS_CODEX_PROFILE", DEFAULT_CODEX_PROFILE),
            }
        )
        argv = ["bash", str(AGENT_WRAPPER)]
        try:
            self._agent_terminal.reset(True, True)
            _apply_terminal_theme(self._agent_terminal)
            self._agent_terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                str(PROJECT_DIR),
                argv,
                [f"{key}={value}" for key, value in env.items()],
                GLib.SpawnFlags.DEFAULT,
                None,
                None,
                -1,
                None,
                self._on_agent_spawned,
                None,
            )
            self._set_status("Started embedded Codex agent.")
            self._agent_terminal.grab_focus()
        except Exception as exc:
            self._set_status(f"Unable to start embedded agent: {exc}")

    def _on_agent_spawned(
        self,
        _terminal: Any,
        pid: int,
        error: GLib.Error | None,
        _user_data: object,
    ) -> None:
        if error is not None:
            self._agent_pid = None
            self._set_status(f"Unable to start embedded agent: {error.message}")
            return
        self._agent_pid = int(pid)

    def _on_agent_exited(self, _terminal: Any, _status: int) -> None:
        self._agent_pid = None
        self._set_status("Embedded agent session ended.")

    def _on_agent_terminal_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        terminal = self._agent_terminal
        if Vte is None or terminal is None:
            return False
        required = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        if state & required != required:
            return False
        if keyval in (Gdk.KEY_C, Gdk.KEY_c):
            terminal.copy_clipboard_format(Vte.Format.TEXT)
            return True
        if keyval in (Gdk.KEY_V, Gdk.KEY_v):
            terminal.paste_clipboard()
            return True
        return False

    def _stop_agent(self) -> None:
        if self._agent_pid is not None:
            try:
                os.kill(self._agent_pid, signal.SIGTERM)
            except OSError:
                pass
            self._agent_pid = None


class OpenLawLensApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self._on_activate)

    def _on_activate(self, _app: Adw.Application) -> None:
        window = OpenLawLensWindow(self)
        window.present()


def main() -> int:
    app = OpenLawLensApp()
    return int(app.run(None))
