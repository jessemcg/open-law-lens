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
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # type: ignore

Vte = None
try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte as VteModule  # type: ignore

    Vte = VteModule
except (ImportError, ValueError):
    Vte = None

from . import APP_ID, APP_NAME
from .cache import cluster_id_from_cluster
from .client import (
    CourtListenerClient,
    CourtListenerError,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
    official_california_reporter_citation,
)
from .case_suggestions import (
    CaseSuggestion,
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    matching_case_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from .config import AppConfig, concordance_file_path, load_config, save_config
from .library import PageMarker


PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENT_WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-codex-agent-vte.sh"
DEFAULT_CODEX_BIN = "codex"
DEFAULT_CODEX_PROFILE = "fireworks"
READER_BG = "#ffffff"
READER_FG = "#000000"
AGENT_TERMINAL_MAX_HEIGHT = 260
AGENT_HEIGHT_DIVISOR = 4
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
        config = load_config()
        self.token_row.set_text(config.courtlistener_token)
        group.add(self.token_row)
        outer.append(group)

        concordance_group = Adw.PreferencesGroup(title="Concordance")
        self.concordance_row = Adw.EntryRow(title="Concordance file")
        self.concordance_row.set_text(config.concordance_file_path)
        self._add_concordance_row_buttons()
        concordance_group.add(self.concordance_row)
        outer.append(concordance_group)

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
        concordance_path = self.concordance_row.get_text().strip()
        save_config(AppConfig(courtlistener_token=token, concordance_file_path=concordance_path))
        self.parent_window.reload_settings()
        self.status_label.set_text("Settings saved.")

    def _add_concordance_row_buttons(self) -> None:
        add_suffix = getattr(self.concordance_row, "add_suffix", None)
        if not callable(add_suffix):
            return
        choose_button = Gtk.Button(icon_name="document-open-symbolic")
        choose_button.add_css_class("flat")
        choose_button.set_tooltip_text("Choose concordance file")
        choose_button.connect("clicked", self._on_choose_concordance_file)
        add_suffix(choose_button)

        clear_button = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_button.add_css_class("flat")
        clear_button.set_tooltip_text("Clear concordance file")
        clear_button.connect("clicked", self._on_clear_concordance_file)
        add_suffix(clear_button)

    def _on_choose_concordance_file(self, _button: Gtk.Button) -> None:
        file_dialog_cls = getattr(Gtk, "FileDialog", None)
        if file_dialog_cls is None:
            self.status_label.set_text("File chooser is unavailable in this GTK version.")
            return
        dialog = file_dialog_cls(title="Choose concordance file")
        dialog.open(self, None, self._on_concordance_file_chosen)

    def _on_concordance_file_chosen(self, dialog: Any, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            self.concordance_row.set_text(path)

    def _on_clear_concordance_file(self, _button: Gtk.Button) -> None:
        self.concordance_row.set_text("")


class OpenLawLensWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.client = CourtListenerClient.default()
        self._clusters: list[dict[str, Any]] = []
        self._selected_cluster: dict[str, Any] | None = None
        self._agent_terminal: Any | None = None
        self._agent_pid: int | None = None
        self._agent_frame: Gtk.Box | None = None
        self._agent_active = False
        self._settings_window: SettingsWindow | None = None
        self._case_suggestions: list[CaseSuggestion] = []
        self._case_suggestions_loaded = False
        self._case_completion_matches: list[CaseSuggestion] = []
        self._case_completion_selected_index = 0
        self._case_completion_results_scroller: Gtk.ScrolledWindow | None = None
        self._case_completion_list_box: Gtk.ListBox | None = None
        self._case_completion_changing = False
        self.toast_overlay: Adw.ToastOverlay | None = None

        self.set_title(APP_NAME)
        self.set_default_size(1260, 860)
        self._install_css()
        self._install_actions()
        self.set_content(self._build_ui())
        self._load_cached_cases()
        self.add_tick_callback(self._on_window_tick)

    def _install_actions(self) -> None:
        settings = Gio.SimpleAction.new("settings", None)
        settings.connect("activate", self._on_open_settings)
        self.add_action(settings)
        clear_cache = Gio.SimpleAction.new("clear_cache", None)
        clear_cache.connect("activate", self._on_clear_cache)
        self.add_action(clear_cache)

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
              background-image: none;
              border: none;
              box-shadow: none;
            }}
            .agent-terminal {{
              border-radius: 8px;
              padding: 8px;
              background-color: @window_bg_color;
              background-image: none;
              color: @window_fg_color;
            }}
            .case-list-frame {{
              border-radius: 8px;
              background: transparent;
            }}
            .case-list-frame > viewport {{
              background: transparent;
            }}
            list.case-list {{
              background-color: @window_bg_color;
              border-radius: 8px;
            }}
            .case-completion-results {{
              background: transparent;
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

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main.set_hexpand(True)
        main.set_vexpand(True)
        main.append(self._build_sidebar())
        main.append(self._build_right_side())
        root.append(main)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(root)
        toolbar_view.set_content(self.toast_overlay)
        return toolbar_view

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Settings", "win.settings")
        menu.append("Clear Research Cache", "win.clear_cache")
        button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        button.set_tooltip_text("Menu")
        button.set_menu_model(menu)
        return button

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(320, -1)
        box.set_hexpand(False)
        box.set_halign(Gtk.Align.START)

        input_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_row.set_hexpand(True)

        self.citation_entry = Gtk.Entry()
        self.citation_entry.set_hexpand(True)
        self.citation_entry.set_width_chars(18)
        self.citation_entry.set_max_width_chars(24)
        self.citation_entry.set_placeholder_text("Citation or case name")
        self.citation_entry.connect("activate", self._on_lookup_clicked)
        self.citation_entry.connect("changed", self._on_citation_entry_changed)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_citation_entry_key_pressed)
        self.citation_entry.add_controller(key_controller)
        input_row.append(self.citation_entry)

        copy_citation_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_citation_button.add_css_class("flat")
        copy_citation_button.set_tooltip_text("Copy official citation")
        copy_citation_button.connect("clicked", self._on_copy_official_citation)
        input_row.append(copy_citation_button)
        box.append(input_row)
        box.append(self._build_case_completion_results())

        heading = Gtk.Label(label="Research Cache", xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        self.case_list = Gtk.ListBox()
        self.case_list.add_css_class("case-list")
        self.case_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.case_list.connect("row-selected", self._on_case_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("case-list-frame")
        scroller.set_overflow(Gtk.Overflow.HIDDEN)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.case_list)
        scroller.set_vexpand(True)
        box.append(scroller)
        return box

    def _build_case_completion_results(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("case-completion-results")
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_max_content_height(220)
        scroller.set_propagate_natural_height(True)
        scroller.set_visible(False)

        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.connect("row-activated", self._on_case_completion_row_activated)
        scroller.set_child(list_box)

        self._case_completion_results_scroller = scroller
        self._case_completion_list_box = list_box
        return scroller

    def _refresh_case_suggestion_index(self, *, force: bool = False) -> None:
        if self._case_suggestions_loaded and not force:
            return
        configured_path = concordance_file_path()
        concordance_suggestions: list[CaseSuggestion] = []
        if configured_path is not None:
            concordance_suggestions = load_concordance_case_suggestions(configured_path)
        library_suggestions = case_suggestions_from_library(self.client.library)
        self._case_suggestions = merge_case_suggestions(concordance_suggestions, library_suggestions)
        self._case_suggestions_loaded = True

    def _on_citation_entry_changed(self, _entry: Gtk.Entry) -> None:
        if self._case_completion_changing:
            return
        self._refresh_case_suggestion_index()
        query = self.citation_entry.get_text().strip()
        matches = matching_case_suggestions(query, self._case_suggestions)
        self._show_case_completion(matches)

    def _on_citation_entry_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _state: Gdk.ModifierType,
    ) -> bool:
        if (
            self._case_completion_results_scroller is None
            or not self._case_completion_results_scroller.get_visible()
        ):
            return False
        if keyval == Gdk.KEY_Down:
            self._move_case_completion_selection(1)
            return True
        if keyval == Gdk.KEY_Up:
            self._move_case_completion_selection(-1)
            return True
        if keyval in {Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Tab}:
            return self._apply_case_completion_selection()
        if keyval == Gdk.KEY_Escape:
            self._hide_case_completion()
            return True
        return False

    def _show_case_completion(self, matches: list[CaseSuggestion]) -> None:
        entry_had_focus = self.citation_entry.has_focus()
        self._case_completion_matches = matches
        self._case_completion_selected_index = 0
        if self._case_completion_results_scroller is None or self._case_completion_list_box is None:
            return
        while row := self._case_completion_list_box.get_row_at_index(0):
            self._case_completion_list_box.remove(row)
        if not matches:
            self._hide_case_completion()
            if entry_had_focus:
                self.citation_entry.grab_focus()
            return
        for index, suggestion in enumerate(matches):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row._open_law_lens_case_suggestion_index = index

            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_top(6)
            row_box.set_margin_bottom(6)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)

            title = Gtk.Label(label=suggestion.label, xalign=0)
            title.set_wrap(True)
            title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            row_box.append(title)

            if suggestion.source:
                source = Gtk.Label(label=suggestion.source, xalign=0)
                source.add_css_class("dim-label")
                row_box.append(source)

            row.set_child(row_box)
            self._case_completion_list_box.append(row)
        first_row = self._case_completion_list_box.get_row_at_index(0)
        if first_row is not None:
            self._case_completion_list_box.select_row(first_row)
        self._case_completion_results_scroller.set_visible(True)
        if entry_had_focus:
            self.citation_entry.grab_focus()

    def _hide_case_completion(self) -> None:
        if self._case_completion_results_scroller is not None:
            self._case_completion_results_scroller.set_visible(False)

    def _move_case_completion_selection(self, direction: int) -> None:
        if not self._case_completion_matches or self._case_completion_list_box is None:
            return
        count = len(self._case_completion_matches)
        self._case_completion_selected_index = (self._case_completion_selected_index + direction) % count
        row = self._case_completion_list_box.get_row_at_index(self._case_completion_selected_index)
        if row is not None:
            self._case_completion_list_box.select_row(row)

    def _on_case_completion_row_activated(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        index = getattr(row, "_open_law_lens_case_suggestion_index", None)
        if isinstance(index, int):
            self._case_completion_selected_index = index
        self._apply_case_completion_selection()

    def _apply_case_completion_selection(self) -> bool:
        if not self._case_completion_matches:
            return False
        index = max(0, min(self._case_completion_selected_index, len(self._case_completion_matches) - 1))
        suggestion = self._case_completion_matches[index]
        self._case_completion_changing = True
        try:
            self.citation_entry.set_text(suggestion.label)
            self.citation_entry.set_position(-1)
        finally:
            self._case_completion_changing = False
        self._hide_case_completion()
        self.citation_entry.grab_focus()
        return True

    def _lookup_text_from_entry(self, entry_text: str) -> str:
        self._refresh_case_suggestion_index()
        return resolve_case_lookup_text(entry_text, self._case_suggestions) or entry_text

    def _build_right_side(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_hexpand(True)
        box.set_vexpand(True)
        box.set_halign(Gtk.Align.FILL)
        box.append(self._build_agent_box())

        self.reader_buffer = Gtk.TextBuffer()
        self.page_marker_tag = self.reader_buffer.create_tag(
            "page-marker",
            weight=Pango.Weight.BOLD,
            foreground="#6f2f00",
            background="#fff0a6",
        )
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
        reader_scroller.set_hexpand(True)
        reader_scroller.set_vexpand(True)
        reader_scroller.set_child(self.reader_view)

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        frame.add_css_class("case-reader-frame")
        frame.set_hexpand(True)
        frame.set_vexpand(True)
        frame.set_halign(Gtk.Align.FILL)
        frame.append(reader_scroller)
        box.append(frame)
        self.reader_buffer.set_text("Enter a citation to load a CourtListener case.")
        return box

    def _build_agent_box(self) -> Gtk.Widget:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        frame.set_hexpand(True)
        frame.set_vexpand(False)
        frame.set_halign(Gtk.Align.FILL)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        controls.set_hexpand(True)
        self.agent_entry = Gtk.Entry()
        self.agent_entry.set_hexpand(True)
        self.agent_entry.set_placeholder_text("Agent question about selected case")
        self.agent_entry.connect("activate", self._on_agent_launch)
        controls.append(self.agent_entry)
        frame.append(controls)

        if Vte is None:
            missing = Gtk.Label(
                label="Install GTK4 VTE packages to use the embedded Codex terminal.",
                xalign=0,
            )
            missing.add_css_class("dim-label")
            frame.append(missing)
            return frame

        terminal_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        terminal_frame.add_css_class("agent-terminal-frame")
        terminal_frame.set_hexpand(True)
        terminal_frame.set_vexpand(False)
        terminal_frame.set_halign(Gtk.Align.FILL)
        terminal_frame.set_overflow(Gtk.Overflow.HIDDEN)
        terminal_frame.set_visible(False)
        self._agent_frame = terminal_frame

        terminal = Vte.Terminal()
        terminal.set_hexpand(True)
        terminal.set_vexpand(True)
        terminal.add_css_class("agent-terminal")
        _apply_terminal_theme(terminal)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_agent_terminal_key_pressed)
        terminal.add_controller(key_controller)
        Adw.StyleManager.get_default().connect(
            "notify::dark",
            self._on_agent_terminal_style_changed,
        )
        terminal.connect("child-exited", self._on_agent_exited)
        terminal_frame.append(terminal)
        frame.append(terminal_frame)
        self._agent_terminal = terminal
        return frame

    def _set_status(self, text: str) -> None:
        if not text:
            return
        if self.toast_overlay is None:
            return
        self.toast_overlay.add_toast(Adw.Toast.new(text))

    def _set_reader_text(self, text: str, page_markers: list[PageMarker] | None = None) -> bool:
        self.reader_buffer.set_text(text)
        if page_markers:
            for marker in page_markers:
                start = max(0, min(marker.start_offset, len(text)))
                end = max(start, min(marker.end_offset, len(text)))
                if start == end:
                    continue
                self.reader_buffer.apply_tag(
                    self.page_marker_tag,
                    self.reader_buffer.get_iter_at_offset(start),
                    self.reader_buffer.get_iter_at_offset(end),
                )
        return False

    def _target_agent_height(self) -> int:
        host_height = max(0, self.get_height())
        if host_height <= 0:
            return 0
        return min(AGENT_TERMINAL_MAX_HEIGHT, host_height // AGENT_HEIGHT_DIVISOR)

    def _update_agent_frame_height(self, *, force: bool = False) -> None:
        if self._agent_frame is None:
            return
        self._agent_frame.set_visible(self._agent_active)
        if not self._agent_active:
            self._agent_frame.set_size_request(-1, 0)
            return
        target_height = self._target_agent_height()
        if force or self._agent_frame.get_height() != target_height:
            self._agent_frame.set_size_request(-1, target_height)

    def _on_window_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        self._update_agent_frame_height()
        return True

    def reload_settings(self) -> None:
        self.client = CourtListenerClient.default()
        self._load_cached_cases()
        self._refresh_case_suggestion_index(force=True)
        self._set_status("Settings saved.")

    def _on_open_settings(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.connect("close-request", self._on_settings_closed)
        self._settings_window.present()

    def _on_settings_closed(self, _window: Gtk.Window) -> bool:
        self._settings_window = None
        return False

    def _on_clear_cache(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        self.client.cache.clear()
        self._load_cached_cases()
        self.reader_buffer.set_text("Enter a citation to load a CourtListener case.")
        self._set_status("Research Cache cleared. Library preserved.")

    def _on_lookup_clicked(self, _widget: Gtk.Widget) -> None:
        entry_text = self.citation_entry.get_text().strip()
        if not entry_text:
            self._set_status("Enter a citation.")
            return
        citation = self._lookup_text_from_entry(entry_text)
        self._hide_case_completion()
        self._set_status(f"Looking up {citation}...")
        self.reader_buffer.set_text("Loading...")
        thread = threading.Thread(target=self._lookup_worker, args=(citation,), daemon=True)
        thread.start()

    def _on_copy_official_citation(self, _button: Gtk.Button) -> None:
        if self._selected_cluster is None:
            self._set_status("Select a Research Cache case first.")
            return
        citation = format_official_california_citation(self._selected_cluster)
        if citation is None:
            self._set_status("No official California reporter citation found.")
            return
        display = Gdk.Display.get_default()
        if display is None:
            self._set_status("Could not access clipboard.")
            return
        html_provider = Gdk.ContentProvider.new_for_bytes(
            "text/html",
            GLib.Bytes.new(citation.html_text.encode("utf-8")),
        )
        plain_provider = Gdk.ContentProvider.new_for_bytes(
            "text/plain",
            GLib.Bytes.new(citation.plain_text.encode("utf-8")),
        )
        provider = Gdk.ContentProvider.new_union([html_provider, plain_provider])
        if not display.get_clipboard().set_content(provider):
            self._set_status("Could not copy official citation.")
            return
        self._set_status("Official citation copied.")

    def _lookup_worker(self, citation: str) -> None:
        try:
            result = self.client.lookup_citation(citation)
            raw_clusters = self.client.clusters_from_lookup(result)
            shown_clusters = dedupe_case_clusters(raw_clusters)
            status = self._lookup_status_text(result, raw_clusters, shown_clusters)
            GLib.idle_add(self._apply_lookup_result, result, shown_clusters, status)
        except (CourtListenerError, ValueError) as exc:
            GLib.idle_add(self._apply_error, str(exc))

    def _lookup_status_text(
        self,
        result: list[dict[str, Any]],
        raw_clusters: list[dict[str, Any]],
        shown_clusters: list[dict[str, Any]],
    ) -> str:
        source = self.client.last_lookup_source or "Unknown source"
        if not result:
            return f"{source}: no citation found"
        statuses = [str(item.get("status", "")) for item in result if isinstance(item, dict)]
        status_text = self._format_lookup_statuses(statuses)
        if raw_clusters:
            noun = "match" if len(raw_clusters) == 1 else "matches"
            if len(raw_clusters) != len(shown_clusters):
                return (
                    f"{source}: {len(raw_clusters)} {noun}, "
                    f"{len(shown_clusters)} shown, {status_text}"
                )
            return f"{source}: {len(raw_clusters)} {noun}, {status_text}"
        messages = [
            str(item.get("error_message", "")).strip()
            for item in result
            if isinstance(item, dict) and item.get("error_message")
        ]
        message = messages[0] if messages else "no matches"
        return f"{source}: {message}, {status_text}"

    def _format_lookup_statuses(self, statuses: list[str]) -> str:
        labels = {
            "200": "exact match",
            "300": "multiple matches",
            "404": "not found",
        }
        rendered: list[str] = []
        for status in statuses:
            label = labels.get(status)
            rendered.append(f"{status} ({label})" if label else status)
        if not rendered:
            return "status unknown"
        return f"status {', '.join(rendered)}"

    def _load_cached_cases(self) -> None:
        clusters = self.client.cached_clusters()
        self._set_sidebar_clusters(clusters)
        self._refresh_case_suggestion_index(force=True)
        if clusters:
            self._set_status(f"{len(clusters)} Research Cache item(s).")

    def _set_sidebar_clusters(
        self,
        clusters: list[dict[str, Any]],
        *,
        select_cluster_id: str = "",
        select_first: bool = False,
    ) -> None:
        self._clusters = clusters
        self._selected_cluster = None
        while row := self.case_list.get_row_at_index(0):
            self.case_list.remove(row)
        selected_row: Gtk.ListBoxRow | None = None
        for index, cluster in enumerate(clusters):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            title = Gtk.Label(label=cluster_short_title(cluster), xalign=0)
            title.set_wrap(True)
            row_box.append(title)
            official_citation = official_california_reporter_citation(cluster)
            if official_citation:
                citation = Gtk.Label(label=official_citation, xalign=0)
                citation.add_css_class("dim-label")
                citation.set_wrap(True)
                row_box.append(citation)
            row.set_child(row_box)
            row._open_law_lens_cluster_index = index
            self.case_list.append(row)
            if select_cluster_id and cluster_id_from_cluster(cluster) == select_cluster_id:
                selected_row = row
        if selected_row is None and select_first:
            selected_row = self.case_list.get_row_at_index(0)
        if selected_row is not None:
            self.case_list.select_row(selected_row)

    def _apply_lookup_result(
        self,
        _result: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        status: str,
    ) -> bool:
        select_cluster_id = cluster_id_from_cluster(clusters[0]) if clusters else ""
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id=select_cluster_id,
            select_first=bool(clusters),
        )
        self._set_status(status)
        self._refresh_case_suggestion_index(force=True)
        if clusters:
            if self.case_list.get_selected_row() is None:
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
            title = cluster_title(cluster)
            citation = cluster_citation_line(cluster)
            header = title if not citation else f"{title}\n{citation}"
            text = header
            page_markers: list[PageMarker] = []
            for opinion in opinions:
                display = self.client.opinion_display(opinion)
                if not display.text:
                    continue
                base_offset = len(text) + 2
                text = f"{text}\n\n{display.text}"
                page_markers.extend(
                    PageMarker(
                        page_label=marker.page_label,
                        marker_text=marker.marker_text,
                        start_offset=base_offset + marker.start_offset,
                        end_offset=base_offset + marker.end_offset,
                        source_field=marker.source_field,
                    )
                    for marker in display.page_markers
                )
            if not text:
                text = f"{header}\n\nNo opinion text found."
            GLib.idle_add(self._set_reader_text, text, page_markers)
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
- Library database: {self.client.library.path}
- Cache root: {self.client.cache.root}

Use the local Open Law Lens CLI and library before making network calls when possible:
- open-law-lens show-library
- open-law-lens library-db
- open-law-lens lookup-citation "<citation>"
- open-law-lens lookup-citation "<citation>" --text

Do not modify app files, library files, or cache files unless explicitly asked. Focus on reading and explaining the selected CourtListener case data.""".strip()

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
            self._agent_active = True
            self._update_agent_frame_height(force=True)
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
        self._agent_active = False
        self._update_agent_frame_height(force=True)
        self._set_status("Embedded agent session ended.")

    def _on_agent_terminal_style_changed(self, *_args: object) -> None:
        if self._agent_terminal is not None:
            _apply_terminal_theme(self._agent_terminal)

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
        self._agent_active = False
        self._update_agent_frame_height(force=True)


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
