from __future__ import annotations

import os
import re
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
from .agent import (
    CaseTextSource,
    QuoteTarget,
    export_selected_cases,
    extract_latest_codex_final_answer_from_jsonl,
    extract_quoted_phrases,
    find_latest_codex_session_log_for_cwd,
    resolve_quote_target,
)
from .cache import cluster_id_from_cluster
from .client import (
    CourtListenerClient,
    CourtListenerError,
    FormattedCitation,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
)
from .case_suggestions import (
    CaseSuggestion,
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    matching_case_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from .config import (
    AppConfig,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    concordance_file_path,
    courtlistener_token,
    load_config,
    save_config,
)
from .library import PageMarker


PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENT_WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-codex-agent-vte.sh"
DEFAULT_CODEX_BIN = "codex"
READER_BG = "#ffffff"
READER_FG = "#000000"
AGENT_TERMINAL_MAX_HEIGHT = 260
AGENT_HEIGHT_DIVISOR = 4
AGENT_SUBVIEW_ANSWER = "answer"
AGENT_SUBVIEW_SESSION = "session"
AGENT_MODE_GENERAL = "general"
AGENT_MODE_CASE = "case"
AGENT_ANSWER_FONT_SIZE_PT = 14
AGENT_ANSWER_LINE_HEIGHT = 1.25
AGENT_AI_PANEL_BG_COLOR = "alpha(@window_fg_color, 0.08)"
AGENT_ANSWER_TEXT_COLOR = "alpha(@window_fg_color, 0.68)"
AGENT_BLOCKQUOTE_LEFT_MARGIN = 24
AGENT_BLOCKQUOTE_RIGHT_MARGIN = 12
AGENT_BLOCKQUOTE_INDENT = 0
AGENT_BLOCKQUOTE_SPACING_PX = 4
AGENT_MARKDOWN_HEADING_SCALES = {
    1: 1.55,
    2: 1.3,
    3: 1.15,
}
CODEX_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
MARKDOWN_TOKEN_RE = re.compile(r"(\*\*([^*\n]+)\*\*|\*([^*\n]+)\*)")
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
        super().__init__(application=parent.get_application())
        self.parent_window = parent
        self.set_title("Settings")
        self.set_default_size(760, 820)
        self.set_modal(False)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Settings"))
        toolbar_view.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        outer.set_vexpand(True)

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

        prompt_group = Adw.PreferencesGroup(title="Agent Prompts")
        prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        prompt_group.set_vexpand(True)
        prompt_box.set_vexpand(True)
        prompt_box.set_margin_top(8)
        prompt_box.set_margin_bottom(8)
        prompt_box.set_margin_start(8)
        prompt_box.set_margin_end(8)
        general_label = Gtk.Label(label="General California Law prompt", xalign=0)
        general_label.add_css_class("dim-label")
        prompt_box.append(general_label)
        general_scroller, self.general_agent_prompt_buffer = self._build_prompt_editor(
            config.general_agent_prompt_template,
        )
        prompt_box.append(general_scroller)
        case_label = Gtk.Label(label="Marked Research Cache Cases prompt", xalign=0)
        case_label.add_css_class("dim-label")
        prompt_box.append(case_label)
        case_scroller, self.case_agent_prompt_buffer = self._build_prompt_editor(
            config.case_agent_prompt_template,
        )
        prompt_box.append(case_scroller)
        prompt_group.add(prompt_box)
        outer.append(prompt_group)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        save_button = Gtk.Button(label="Save Settings")
        save_button.connect("clicked", self._on_save_clicked)
        buttons.append(save_button)
        outer.append(buttons)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim-label")
        outer.append(self.status_label)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(outer)
        toolbar_view.set_content(scroller)
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

    def _build_prompt_editor(self, text: str) -> tuple[Gtk.ScrolledWindow, Gtk.TextBuffer]:
        buffer = Gtk.TextBuffer()
        buffer.set_text(text)
        view = Gtk.TextView(buffer=buffer)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(8)
        view.set_right_margin(8)
        view.set_top_margin(8)
        view.set_bottom_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(260)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_child(view)
        return scroller, buffer

    def _prompt_text(self, buffer: Gtk.TextBuffer) -> str:
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, True)

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        token = self.token_row.get_text().strip()
        concordance_path = self.concordance_row.get_text().strip()
        save_config(
            AppConfig(
                courtlistener_token=token,
                concordance_file_path=concordance_path,
                general_agent_prompt_template=(
                    self._prompt_text(self.general_agent_prompt_buffer).strip()
                    or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
                ),
                case_agent_prompt_template=(
                    self._prompt_text(self.case_agent_prompt_buffer).strip()
                    or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
                ),
            )
        )
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
        self._agent_session_widget: Gtk.Widget | None = None
        self._agent_answer_scroller: Gtk.ScrolledWindow | None = None
        self._agent_answer_buffer: Gtk.TextBuffer | None = None
        self._agent_answer_view: Gtk.TextView | None = None
        self._agent_answer_button: Gtk.ToggleButton | None = None
        self._agent_session_button: Gtk.ToggleButton | None = None
        self._agent_subview_strip: Gtk.Widget | None = None
        self._agent_subview_name = AGENT_SUBVIEW_SESSION
        self._agent_subview_toggle_guard = False
        self._agent_mode_buttons: dict[str, Gtk.ToggleButton] = {}
        self._agent_mode_toggle_guard = False
        self._agent_active = False
        self._agent_workspace_path: Path | None = None
        self._agent_session_log_path: Path | None = None
        self._agent_answer_poll_id: int | None = None
        self._agent_last_answer_text = ""
        self._agent_mode = AGENT_MODE_GENERAL
        self._selected_agent_mode = AGENT_MODE_GENERAL
        self._case_agent_text_sources: list[CaseTextSource] = []
        self._agent_link_tags: list[Gtk.TextTag] = []
        self._agent_link_lookup: dict[Gtk.TextTag, QuoteTarget] = {}
        self._agent_motion_controller: Gtk.EventControllerMotion | None = None
        self._agent_click_gesture: Gtk.GestureClick | None = None
        self._reader_text = ""
        self._reader_highlight_tag: Gtk.TextTag | None = None
        self._pending_quote_target: QuoteTarget | None = None
        self._settings_window: SettingsWindow | None = None
        self._case_suggestions: list[CaseSuggestion] = []
        self._case_suggestions_loaded = False
        self._case_completion_matches: list[CaseSuggestion] = []
        self._case_completion_selected_index = 0
        self._case_completion_results_scroller: Gtk.ScrolledWindow | None = None
        self._case_completion_list_box: Gtk.ListBox | None = None
        self._case_completion_changing = False
        self._case_completion_click_gesture: Gtk.GestureClick | None = None
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
            .agent-answer-view {{
              background: transparent;
              color: {AGENT_ANSWER_TEXT_COLOR};
              font-size: {AGENT_ANSWER_FONT_SIZE_PT}pt;
              line-height: {AGENT_ANSWER_LINE_HEIGHT};
            }}
            .ai-output-frame {{
              background-color: {AGENT_AI_PANEL_BG_COLOR};
              border-radius: 8px;
              padding: 8px;
            }}
            box.agent-ask-bar {{
              min-height: 34px;
              margin-bottom: 6px;
            }}
            .no-bold {{
              font-weight: normal;
            }}
            box.focus-pill-group > button.focus-pill-segment {{
              min-width: 28px;
              min-height: 28px;
              padding: 4px 8px;
              margin: 0;
              border: none;
              box-shadow: none;
              background-image: none;
            }}
            button.focus-ai-view-active,
            button.focus-ai-view-active:hover,
            button.focus-ai-view-active:active {{
              background-color: alpha(@window_fg_color, 0.08);
              color: @window_fg_color;
              background-image: none;
              box-shadow: none;
            }}
            button.focus-ai-view-active image {{
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
            list.case-list row:selected {{
              background-color: alpha(@window_fg_color, 0.08);
              color: @window_fg_color;
            }}
            list.case-list row:selected label {{
              color: @window_fg_color;
            }}
            checkbutton.neutral-agent-check check:checked {{
              background-color: alpha(@window_fg_color, 0.18);
              color: @window_fg_color;
              border-color: alpha(@window_fg_color, 0.38);
            }}
            .case-completion-results {{
              background: transparent;
              border: none;
              box-shadow: none;
            }}
            .case-completion-results > viewport {{
              background: transparent;
            }}
            list.case-completion-list {{
              min-width: 260px;
              padding: 2px;
              background-color: transparent;
            }}
            .case-completion-row {{
              border-radius: 4px;
              padding: 3px 6px;
            }}
            .case-completion-row label {{
              font-size: 0.92rem;
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
        header.set_title_widget(Adw.WindowTitle(title=APP_NAME))
        header.pack_end(self._build_menu_button())
        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(10)
        root.set_margin_bottom(10)
        root.set_margin_start(10)
        root.set_margin_end(10)
        self._install_case_completion_click_away(root)

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
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", self._on_case_completion_focus_leave)
        self.citation_entry.add_controller(focus_controller)
        input_row.append(self.citation_entry)

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
        list_box.add_css_class("case-completion-list")
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.connect("row-activated", self._on_case_completion_row_activated)
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", self._on_case_completion_focus_leave)
        list_box.add_controller(focus_controller)
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
            row.add_css_class("case-completion-row")
            row._open_law_lens_case_suggestion_index = index

            title = Gtk.Label(label=suggestion.label, xalign=0)
            title.set_ellipsize(Pango.EllipsizeMode.END)
            title.set_tooltip_text(suggestion.label)
            row.set_child(title)
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

    def _on_case_completion_focus_leave(self, _controller: Gtk.EventControllerFocus) -> None:
        GLib.idle_add(self._hide_case_completion_if_focus_outside)

    def _hide_case_completion_if_focus_outside(self) -> bool:
        if (
            self._case_completion_results_scroller is None
            or not self._case_completion_results_scroller.get_visible()
        ):
            return False
        focused = self.get_focus()
        if focused is not None and self._case_completion_contains_widget(focused):
            return False
        self._hide_case_completion()
        return False

    def _case_completion_contains_widget(self, widget: Gtk.Widget) -> bool:
        candidates = [
            self.citation_entry,
            self._case_completion_results_scroller,
            self._case_completion_list_box,
        ]
        current: Gtk.Widget | None = widget
        while current is not None:
            if any(current is candidate for candidate in candidates if candidate is not None):
                return True
            current = current.get_parent()
        return False

    def _install_case_completion_click_away(self, widget: Gtk.Widget) -> None:
        click = Gtk.GestureClick()
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_case_completion_root_pressed)
        widget.add_controller(click)
        self._case_completion_click_gesture = click

    def _on_case_completion_root_pressed(
        self,
        gesture: Gtk.GestureClick,
        _n_press: int,
        x: float,
        y: float,
    ) -> None:
        if (
            self._case_completion_results_scroller is None
            or not self._case_completion_results_scroller.get_visible()
        ):
            return
        widget = gesture.get_widget()
        if widget is None:
            return
        picked = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
        if picked is not None and self._case_completion_contains_widget(picked):
            return
        self._hide_case_completion()

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
        self._reader_highlight_tag = self.reader_buffer.create_tag(
            "agent-quote-highlight",
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
        self.reader_buffer.set_text("")
        return box

    def _build_agent_box(self) -> Gtk.Widget:
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        frame.add_css_class("ai-output-frame")
        frame.set_hexpand(True)
        frame.set_vexpand(False)
        frame.set_halign(Gtk.Align.FILL)

        frame.append(self._build_agent_ask_bar())

        subview_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        subview_strip.add_css_class("focus-pill-group")
        subview_strip.set_halign(Gtk.Align.END)
        self._agent_answer_button = self._build_agent_subview_button(
            "Answer",
            AGENT_SUBVIEW_ANSWER,
            "Show the latest linked Agent final answer",
        )
        subview_strip.append(self._agent_answer_button)
        self._agent_session_button = self._build_agent_subview_button(
            "Session",
            AGENT_SUBVIEW_SESSION,
            "Show the embedded Agent terminal session",
        )
        subview_strip.append(self._agent_session_button)
        self._agent_subview_strip = subview_strip
        frame.append(subview_strip)

        self._agent_answer_buffer = Gtk.TextBuffer()
        self._agent_answer_view = Gtk.TextView(buffer=self._agent_answer_buffer)
        self._agent_answer_view.set_editable(False)
        self._agent_answer_view.set_cursor_visible(False)
        self._agent_answer_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._agent_answer_view.set_left_margin(12)
        self._agent_answer_view.set_right_margin(12)
        self._agent_answer_view.set_top_margin(10)
        self._agent_answer_view.set_bottom_margin(10)
        self._agent_answer_view.add_css_class("agent-answer-view")
        self._install_agent_answer_link_controllers()
        answer_scroller = Gtk.ScrolledWindow()
        answer_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        answer_scroller.set_min_content_height(AGENT_TERMINAL_MAX_HEIGHT)
        answer_scroller.set_max_content_height(AGENT_TERMINAL_MAX_HEIGHT)
        answer_scroller.set_child(self._agent_answer_view)
        self._agent_answer_scroller = answer_scroller
        frame.append(answer_scroller)

        if Vte is None:
            missing = Gtk.Label(
                label="Install GTK4 VTE packages to use the embedded Codex terminal.",
                xalign=0,
            )
            missing.add_css_class("dim-label")
            self._agent_session_widget = missing
            frame.append(missing)
            self._set_agent_subview(AGENT_SUBVIEW_ANSWER)
            return frame

        terminal_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        terminal_frame.add_css_class("agent-terminal-frame")
        terminal_frame.set_hexpand(True)
        terminal_frame.set_vexpand(False)
        terminal_frame.set_halign(Gtk.Align.FILL)
        terminal_frame.set_overflow(Gtk.Overflow.HIDDEN)

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
        self._agent_session_widget = terminal_frame
        self._set_agent_subview(AGENT_SUBVIEW_SESSION)
        return frame

    def _build_agent_ask_bar(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.add_css_class("agent-ask-bar")
        row.set_hexpand(True)

        mode_strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        mode_strip.add_css_class("focus-pill-group")
        mode_strip.append(self._build_agent_mode_button("Law", AGENT_MODE_GENERAL))
        mode_strip.append(self._build_agent_mode_button("Cache", AGENT_MODE_CASE))
        row.append(mode_strip)

        self.agent_question_entry = Gtk.Entry()
        self.agent_question_entry.set_hexpand(True)
        self.agent_question_entry.set_placeholder_text("Ask a California law question")
        self.agent_question_entry.connect("activate", self._on_agent_launch)
        row.append(self.agent_question_entry)

        self._set_agent_mode(AGENT_MODE_GENERAL)
        return row

    def _build_agent_mode_button(self, label: str, mode: str) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton(label=label)
        button.add_css_class("flat")
        button.add_css_class("no-bold")
        button.add_css_class("focus-pill-segment")
        tooltip = (
            "Ask from CourtListener legal authority"
            if mode == AGENT_MODE_GENERAL
            else "Ask from marked Research Cache cases"
        )
        button.set_tooltip_text(tooltip)
        button.connect("toggled", self._on_agent_mode_button_toggled, mode)
        self._agent_mode_buttons[mode] = button
        return button

    def _build_agent_subview_button(
        self,
        label: str,
        subview_name: str,
        tooltip: str,
    ) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton(label=label)
        button.add_css_class("flat")
        button.add_css_class("no-bold")
        button.add_css_class("focus-pill-segment")
        button.set_tooltip_text(tooltip)
        button.connect("toggled", self._on_agent_subview_button_toggled, subview_name)
        return button

    def _set_status(self, text: str) -> None:
        if not text:
            return
        if self.toast_overlay is None:
            return
        self.toast_overlay.add_toast(Adw.Toast.new(text))

    def _set_reader_text(self, text: str, page_markers: list[PageMarker] | None = None) -> bool:
        self._reader_text = text
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
        if self._pending_quote_target is not None:
            target = self._pending_quote_target
            self._pending_quote_target = None
            self._highlight_reader_phrase(target.phrase)
        return False

    def _sync_agent_subviews(self) -> None:
        has_agent_output = self._agent_active or bool(self._agent_last_answer_text)
        if self._agent_subview_strip is not None:
            self._agent_subview_strip.set_visible(has_agent_output)
        if self._agent_answer_scroller is not None:
            self._agent_answer_scroller.set_visible(
                has_agent_output and self._agent_subview_name == AGENT_SUBVIEW_ANSWER
            )
        if self._agent_session_widget is not None:
            self._agent_session_widget.set_visible(
                has_agent_output and self._agent_subview_name == AGENT_SUBVIEW_SESSION
            )
            if self._agent_subview_name == AGENT_SUBVIEW_SESSION:
                self._agent_session_widget.set_size_request(-1, AGENT_TERMINAL_MAX_HEIGHT)
            else:
                self._agent_session_widget.set_size_request(-1, -1)

    def _set_agent_subview(self, subview_name: str) -> None:
        self._agent_subview_name = (
            subview_name
            if subview_name in {AGENT_SUBVIEW_ANSWER, AGENT_SUBVIEW_SESSION}
            else AGENT_SUBVIEW_SESSION
        )
        self._sync_agent_subviews()
        self._agent_subview_toggle_guard = True
        try:
            for name, button in (
                (AGENT_SUBVIEW_ANSWER, self._agent_answer_button),
                (AGENT_SUBVIEW_SESSION, self._agent_session_button),
            ):
                if button is None:
                    continue
                active = name == self._agent_subview_name
                button.set_active(active)
                if active:
                    button.add_css_class("focus-ai-view-active")
                else:
                    button.remove_css_class("focus-ai-view-active")
        finally:
            self._agent_subview_toggle_guard = False

    def _on_agent_subview_button_toggled(
        self,
        button: Gtk.ToggleButton,
        subview_name: str,
    ) -> None:
        if self._agent_subview_toggle_guard:
            return
        if not button.get_active():
            if self._agent_subview_name == subview_name:
                self._set_agent_subview(subview_name)
            return
        self._set_agent_subview(subview_name)

    def _set_agent_mode(self, mode: str) -> None:
        self._selected_agent_mode = (
            mode if mode in {AGENT_MODE_GENERAL, AGENT_MODE_CASE} else AGENT_MODE_GENERAL
        )
        if hasattr(self, "agent_question_entry"):
            placeholder = (
                "Ask a California law question"
                if self._selected_agent_mode == AGENT_MODE_GENERAL
                else "Ask about marked Research Cache cases"
            )
            self.agent_question_entry.set_placeholder_text(placeholder)
        self._agent_mode_toggle_guard = True
        try:
            for name, button in self._agent_mode_buttons.items():
                active = name == self._selected_agent_mode
                button.set_active(active)
                if active:
                    button.add_css_class("focus-ai-view-active")
                else:
                    button.remove_css_class("focus-ai-view-active")
        finally:
            self._agent_mode_toggle_guard = False

    def _on_agent_mode_button_toggled(
        self,
        button: Gtk.ToggleButton,
        mode: str,
    ) -> None:
        if self._agent_mode_toggle_guard:
            return
        if not button.get_active():
            if self._selected_agent_mode == mode:
                self._set_agent_mode(mode)
            return
        self._set_agent_mode(mode)

    def _on_window_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
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
        self.reader_buffer.set_text("")
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

    def _copy_formatted_citation(self, citation: FormattedCitation) -> None:
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

    def _on_copy_case_citation(
        self,
        _button: Gtk.Button,
        citation: FormattedCitation,
    ) -> None:
        self._copy_formatted_citation(citation)

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
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            cluster_id = cluster_id_from_cluster(cluster)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title_text = cluster_short_title(cluster)
            title = Gtk.Label(label=title_text, xalign=0)
            title.set_wrap(True)
            text_box.append(title)
            formatted_citation = format_official_california_citation(cluster)
            official_citation = ""
            if formatted_citation is not None:
                title_prefix = f"{title_text} "
                official_citation = formatted_citation.plain_text.removeprefix(title_prefix)
            if official_citation:
                citation = Gtk.Label(label=official_citation, xalign=0)
                citation.add_css_class("dim-label")
                citation.set_wrap(True)
                text_box.append(citation)
            row_box.append(text_box)
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            actions_box.set_valign(Gtk.Align.START)
            if formatted_citation is not None:
                copy_button = Gtk.Button(label="Cite")
                copy_button.add_css_class("flat")
                copy_button.add_css_class("no-bold")
                copy_button.set_tooltip_text("Copy citation")
                copy_button.connect("clicked", self._on_copy_case_citation, formatted_citation)
                actions_box.append(copy_button)
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make case available to Case Agent")
            check.set_active(self.client.cache.is_agent_selected(cluster_id))
            check.connect("toggled", self._on_agent_case_toggled, cluster_id)
            actions_box.append(check)
            row_box.append(actions_box)
            row.set_child(row_box)
            row._open_law_lens_cluster_index = index
            self.case_list.append(row)
            if select_cluster_id and cluster_id_from_cluster(cluster) == select_cluster_id:
                selected_row = row
        if selected_row is None and select_first:
            selected_row = self.case_list.get_row_at_index(0)
        if selected_row is not None:
            self.case_list.select_row(selected_row)

    def _on_agent_case_toggled(self, button: Gtk.CheckButton, cluster_id: str) -> None:
        self.client.cache.set_agent_selected(cluster_id, button.get_active())

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

    def _format_agent_prompt(
        self,
        template: str,
        fallback: str,
        values: dict[str, object],
    ) -> str:
        try:
            return template.format_map(values).strip()
        except (KeyError, ValueError):
            return fallback.format_map(values).strip()

    def _compose_general_agent_prompt(self, question: str) -> str:
        config = load_config()
        return self._format_agent_prompt(
            config.general_agent_prompt_template,
            DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
            {"question": question},
        )

    def _compose_case_agent_prompt(self, question: str, export: Any) -> str:
        config = load_config()
        return self._format_agent_prompt(
            config.case_agent_prompt_template,
            DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
            {
                "question": question,
                "case_manifest": str(export.manifest_path),
                "case_dir": str(export.case_dir),
                "case_count": export.case_count,
            },
        )

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

    def _create_agent_workspace(self) -> Path:
        cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()
        parent = cache_root / "open-law-lens" / "agent-workspaces"
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="workspace.", dir=parent))

    def _selected_agent_clusters(self) -> list[dict[str, Any]]:
        selected_ids = {
            str(entry.get("cluster_id", "")).strip()
            for entry in self.client.cache.selected_case_entries()
        }
        return [
            cluster
            for cluster in self.client.cached_clusters()
            if cluster_id_from_cluster(cluster) in selected_ids
        ]

    def _on_agent_launch(self, _widget: Gtk.Widget) -> None:
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return
        mode = self._selected_agent_mode
        question = self.agent_question_entry.get_text().strip()
        if not question:
            self._set_status("Enter an agent question.")
            return
        if mode == AGENT_MODE_CASE:
            clusters = self._selected_agent_clusters()
            if not clusters:
                self._set_status("Mark at least one Research Cache case for the Case Agent.")
                return
            self._set_status("Preparing marked cases for Case Agent...")
            thread = threading.Thread(
                target=self._prepare_case_agent_worker,
                args=(question, clusters),
                daemon=True,
            )
            thread.start()
            return
        self._case_agent_text_sources = []
        self._agent_mode = AGENT_MODE_GENERAL
        prompt_path = self._write_prompt_file(self._compose_general_agent_prompt(question))
        try:
            workspace = self._create_agent_workspace()
        except OSError as exc:
            self._set_status(f"Unable to create agent workspace: {exc}")
            return
        self._launch_agent_with_prompt(prompt_path, workspace, AGENT_MODE_GENERAL)

    def _prepare_case_agent_worker(self, question: str, clusters: list[dict[str, Any]]) -> None:
        try:
            workspace = self._create_agent_workspace()
            export = export_selected_cases(self.client, clusters, workspace / "selected_cases")
            if export.case_count == 0:
                GLib.idle_add(self._set_status, "No opinion text found for marked cases.")
                return
            prompt_path = self._write_prompt_file(self._compose_case_agent_prompt(question, export))
            GLib.idle_add(
                self._finish_case_agent_prepare,
                prompt_path,
                workspace,
                export.text_sources,
            )
        except (CourtListenerError, OSError) as exc:
            GLib.idle_add(self._set_status, f"Unable to prepare marked cases: {exc}")

    def _finish_case_agent_prepare(
        self,
        prompt_path: Path,
        workspace: Path,
        text_sources: list[CaseTextSource],
    ) -> bool:
        self._case_agent_text_sources = text_sources
        self._agent_mode = AGENT_MODE_CASE
        self._launch_agent_with_prompt(prompt_path, workspace, AGENT_MODE_CASE)
        return False

    def _launch_agent_with_prompt(self, prompt_path: Path, workspace: Path, mode: str) -> None:
        self._stop_agent()
        self._stop_agent_answer_polling()
        self._clear_agent_answer()
        if not AGENT_WRAPPER.is_file():
            self._set_status(f"Agent wrapper not found: {AGENT_WRAPPER}")
            return
        env = os.environ.copy()
        if not env.get("COURTLISTENER_TOKEN"):
            token = courtlistener_token()
            if token:
                env["COURTLISTENER_TOKEN"] = token
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt_path),
                "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                "OPEN_LAW_LENS_AGENT_MODE": mode,
                "OPEN_LAW_LENS_CACHE_DIR": str(self.client.cache.root),
                "CODEX_BIN": os.environ.get("OPEN_LAW_LENS_CODEX_BIN", DEFAULT_CODEX_BIN),
            }
        )
        profile = os.environ.get("OPEN_LAW_LENS_CODEX_PROFILE", "open-law-lens").strip()
        if profile:
            env["CODEX_PROFILE"] = profile
        else:
            env.pop("CODEX_PROFILE", None)
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
            self._agent_workspace_path = workspace
            self._agent_session_log_path = None
            self._agent_last_answer_text = ""
            self._set_agent_subview(AGENT_SUBVIEW_SESSION)
            self._start_agent_answer_polling()
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
        self._poll_agent_answer()
        self._set_status("Embedded agent session ended.")

    def _clear_agent_answer(self) -> None:
        self._agent_last_answer_text = ""
        self._agent_link_lookup.clear()
        if self._agent_answer_buffer is not None:
            self._agent_answer_buffer.set_text("")

    def _stop_agent_answer_polling(self) -> None:
        if self._agent_answer_poll_id is not None:
            GLib.source_remove(self._agent_answer_poll_id)
            self._agent_answer_poll_id = None
        self._agent_session_log_path = None

    def _start_agent_answer_polling(self) -> None:
        self._stop_agent_answer_polling()
        self._agent_answer_poll_id = GLib.timeout_add(1200, self._poll_agent_answer)
        self._poll_agent_answer()

    def _poll_agent_answer(self) -> bool:
        workspace = self._agent_workspace_path
        if workspace is None:
            self._agent_answer_poll_id = None
            return False
        if self._agent_session_log_path is None:
            self._agent_session_log_path = find_latest_codex_session_log_for_cwd(
                CODEX_SESSIONS_ROOT,
                workspace,
            )
        if self._agent_session_log_path is not None:
            answer = extract_latest_codex_final_answer_from_jsonl(self._agent_session_log_path)
            if answer and answer != self._agent_last_answer_text:
                self._agent_last_answer_text = answer
                self._render_agent_answer(answer)
                self._set_agent_subview(AGENT_SUBVIEW_ANSWER)
                self._set_status("Agent final answer mirrored.")
        if not self._agent_active:
            self._agent_answer_poll_id = None
            return False
        return True

    def _render_markdown_text(
        self,
        text: str,
    ) -> tuple[str, list[tuple[int, int, str]], list[int]]:
        out: list[str] = []
        spans: list[tuple[int, int, str]] = []
        orig_to_clean = [0] * (len(text) + 1)
        clean_offset = 0
        pos = 0
        for line in text.splitlines(keepends=True):
            line_start = pos
            line_end = pos + len(line)
            has_newline = line.endswith("\n")
            content = line[:-1] if has_newline else line
            prefix_len = 0
            heading = ""
            blockquote = False
            if content.startswith("### "):
                prefix_len = 4
                heading = "heading3"
            elif content.startswith("## "):
                prefix_len = 3
                heading = "heading2"
            elif content.startswith("# "):
                prefix_len = 2
                heading = "heading1"
            elif content.startswith("> "):
                prefix_len = 2
                blockquote = True
            for idx in range(line_start, line_start + prefix_len):
                orig_to_clean[idx] = clean_offset
            content_start = line_start + prefix_len
            line_text = text[content_start:line_start + len(content)]
            if re.match(r"\s*[-*]\s+", line_text):
                bullet_start = line_text.find("-")
                if bullet_start < 0:
                    bullet_start = line_text.find("*")
                if bullet_start >= 0:
                    line_text = f"{line_text[:bullet_start]}*{line_text[bullet_start + 1:]}"
            line_out, line_spans, line_map = self._render_inline_markdown(line_text, clean_offset)
            out.append(line_out)
            for idx in range(len(line_text) + 1):
                orig_to_clean[content_start + idx] = clean_offset + line_map[idx]
            if heading and line_out:
                spans.append((clean_offset, clean_offset + len(line_out), heading))
            if blockquote and line_out:
                spans.append((clean_offset, clean_offset + len(line_out), "blockquote"))
            spans.extend(line_spans)
            clean_offset += len(line_out)
            if has_newline:
                newline_orig = line_start + len(content)
                orig_to_clean[newline_orig] = clean_offset
                out.append("\n")
                clean_offset += 1
                orig_to_clean[line_end] = clean_offset
            pos = line_end
        orig_to_clean[len(text)] = clean_offset
        return "".join(out), spans, orig_to_clean

    def _render_inline_markdown(
        self,
        text: str,
        base_offset: int,
    ) -> tuple[str, list[tuple[int, int, str]], list[int]]:
        out: list[str] = []
        spans: list[tuple[int, int, str]] = []
        orig_to_clean = [0] * (len(text) + 1)
        cursor = 0
        clean_offset = 0
        for match in MARKDOWN_TOKEN_RE.finditer(text):
            start, end = match.span()
            before = text[cursor:start]
            out.append(before)
            for idx in range(cursor, start):
                orig_to_clean[idx] = clean_offset + (idx - cursor)
            clean_offset += len(before)
            content = match.group(2) or match.group(3) or ""
            kind = "bold" if match.group(2) is not None else "italic"
            span_start = clean_offset
            out.append(content)
            clean_offset += len(content)
            if content:
                spans.append((base_offset + span_start, base_offset + clean_offset, kind))
            for idx in range(start, end):
                orig_to_clean[idx] = span_start
            orig_to_clean[end] = clean_offset
            cursor = end
        tail = text[cursor:]
        out.append(tail)
        for idx in range(cursor, len(text)):
            orig_to_clean[idx] = clean_offset + (idx - cursor)
        clean_offset += len(tail)
        orig_to_clean[len(text)] = clean_offset
        return "".join(out), spans, orig_to_clean

    def _map_offset(self, offset: int, offset_map: list[int]) -> int:
        if not offset_map:
            return offset
        offset = max(0, min(offset, len(offset_map) - 1))
        return offset_map[offset]

    def _extract_agent_quote_spans(self, text: str) -> tuple[str, list[tuple[int, int, str]]]:
        spans: list[tuple[int, int, str]] = []
        parts: list[str] = []
        cursor = 0
        offset = 0
        for start, end, phrase in extract_quoted_phrases(text):
            quote_start = start - 1 if start > 0 and text[start - 1] in {'"', "\u201c"} else start
            quote_end = end + 1 if end < len(text) and text[end] in {'"', "\u201d"} else end
            if quote_start < cursor:
                continue
            before = text[cursor:quote_start]
            parts.append(before)
            offset += len(before)
            parts.append(phrase)
            spans.append((offset, offset + len(phrase), phrase))
            offset += len(phrase)
            cursor = quote_end
        tail = text[cursor:]
        parts.append(tail)
        return "".join(parts), spans

    def _render_agent_answer(self, text: str) -> None:
        if self._agent_answer_buffer is None:
            return
        buffer = self._agent_answer_buffer
        table = buffer.get_tag_table()
        if table is not None:
            for tag in self._agent_link_tags:
                try:
                    table.remove(tag)
                except TypeError:
                    pass
        self._agent_link_tags.clear()
        self._agent_link_lookup.clear()
        clean_text, quote_spans = self._extract_agent_quote_spans(text)
        rendered, markdown_spans, offset_map = self._render_markdown_text(clean_text)
        buffer.set_text(rendered)
        self._apply_agent_markdown_spans(buffer, markdown_spans)
        quote_color = self._resolve_agent_quote_color()
        for start, end, phrase in quote_spans:
            mapped_start = self._map_offset(start, offset_map)
            mapped_end = self._map_offset(end, offset_map)
            if mapped_end <= mapped_start:
                continue
            tag = buffer.create_tag(
                None,
                foreground_rgba=quote_color,
                underline=Pango.Underline.NONE,
                weight=Pango.Weight.MEDIUM,
            )
            buffer.apply_tag(
                tag,
                buffer.get_iter_at_offset(mapped_start),
                buffer.get_iter_at_offset(mapped_end),
            )
            self._agent_link_tags.append(tag)
            if self._agent_mode == AGENT_MODE_CASE:
                target = resolve_quote_target(phrase, self._case_agent_text_sources)
                if target is not None:
                    self._agent_link_lookup[tag] = target

    def _resolve_agent_quote_color(self) -> Gdk.RGBA:
        fallback = Gdk.RGBA()
        fallback.parse("#ffffff")
        view = self._agent_answer_view
        if view is None:
            return fallback
        if hasattr(view, "get_color"):
            base = view.get_color()
        else:
            context = view.get_style_context()
            try:
                base = context.get_color()
            except TypeError:
                base = context.get_color(Gtk.StateFlags.NORMAL)
        quote = Gdk.RGBA()
        quote.red = base.red
        quote.green = base.green
        quote.blue = base.blue
        quote.alpha = 1.0
        return quote

    def _apply_agent_markdown_spans(
        self,
        buffer: Gtk.TextBuffer,
        spans: list[tuple[int, int, str]],
    ) -> None:
        if not spans:
            return
        table = buffer.get_tag_table()
        if table is None:
            return

        def ensure_tag(name: str, **props: object) -> Gtk.TextTag:
            tag = table.lookup(name)
            if tag is None:
                tag = buffer.create_tag(name, **props)
            return tag

        bold_tag = ensure_tag("md-bold", weight=Pango.Weight.BOLD)
        italic_tag = ensure_tag("md-italic", style=Pango.Style.ITALIC)
        blockquote_tag = ensure_tag(
            "md-blockquote",
            style=Pango.Style.ITALIC,
            left_margin=AGENT_BLOCKQUOTE_LEFT_MARGIN,
            right_margin=AGENT_BLOCKQUOTE_RIGHT_MARGIN,
            indent=AGENT_BLOCKQUOTE_INDENT,
            pixels_above_lines=AGENT_BLOCKQUOTE_SPACING_PX,
            pixels_below_lines=AGENT_BLOCKQUOTE_SPACING_PX,
        )
        heading_tags: dict[str, Gtk.TextTag] = {}
        for level, scale in AGENT_MARKDOWN_HEADING_SCALES.items():
            heading_tags[f"heading{level}"] = ensure_tag(
                f"md-h{level}",
                weight=Pango.Weight.BOLD,
                scale=scale,
            )

        for start, end, kind in spans:
            if end <= start:
                continue
            start_iter = buffer.get_iter_at_offset(start)
            end_iter = buffer.get_iter_at_offset(end)
            if kind == "bold":
                buffer.apply_tag(bold_tag, start_iter, end_iter)
            elif kind == "italic":
                buffer.apply_tag(italic_tag, start_iter, end_iter)
            elif kind == "blockquote":
                buffer.apply_tag(blockquote_tag, start_iter, end_iter)
            elif kind.startswith("heading"):
                tag = heading_tags.get(kind)
                if tag is not None:
                    buffer.apply_tag(tag, start_iter, end_iter)

    def _install_agent_answer_link_controllers(self) -> None:
        view = self._agent_answer_view
        if view is None:
            return
        if self._agent_motion_controller is None:
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", self._on_agent_answer_motion)
            motion.connect("enter", self._on_agent_answer_motion)
            motion.connect("leave", self._on_agent_answer_leave)
            view.add_controller(motion)
            self._agent_motion_controller = motion
        if self._agent_click_gesture is None:
            click = Gtk.GestureClick.new()
            click.set_button(Gdk.BUTTON_PRIMARY)
            click.connect("released", self._on_agent_answer_click)
            view.add_controller(click)
            self._agent_click_gesture = click

    def _agent_link_at_coords(self, x: float, y: float) -> QuoteTarget | None:
        view = self._agent_answer_view
        if view is None:
            return None
        bx, by = view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        iter_result = view.get_iter_at_location(int(bx), int(by))
        if isinstance(iter_result, tuple):
            success, iter_ = iter_result
            if not success:
                return None
        else:
            iter_ = iter_result
        if iter_ is None:
            return None
        for tag in iter_.get_tags():
            target = self._agent_link_lookup.get(tag)
            if target is not None:
                return target
        return None

    def _on_agent_answer_motion(
        self,
        _controller: Gtk.EventControllerMotion,
        x: float,
        y: float,
    ) -> None:
        if self._agent_answer_view is None:
            return
        if self._agent_link_at_coords(x, y):
            self._agent_answer_view.set_cursor_from_name("pointer")
        else:
            self._agent_answer_view.set_cursor_from_name(None)

    def _on_agent_answer_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        if self._agent_answer_view is not None:
            self._agent_answer_view.set_cursor_from_name(None)

    def _on_agent_answer_click(
        self,
        gesture: Gtk.GestureClick,
        _n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        if button and button != Gdk.BUTTON_PRIMARY:
            return
        target = self._agent_link_at_coords(x, y)
        if target is not None:
            self._open_quote_target(target)

    def _open_quote_target(self, target: QuoteTarget) -> None:
        for index, cluster in enumerate(self._clusters):
            if cluster_id_from_cluster(cluster) != target.cluster_id:
                continue
            row = self.case_list.get_row_at_index(index)
            if row is not None:
                if self._selected_cluster is cluster:
                    self._highlight_reader_phrase(target.phrase)
                else:
                    self._pending_quote_target = target
                    self.case_list.select_row(row)
            return
        self._set_status("Quoted case is no longer in Research Cache.")

    def _highlight_reader_phrase(self, phrase: str) -> None:
        if self._reader_highlight_tag is None:
            return
        self.reader_buffer.remove_tag(
            self._reader_highlight_tag,
            self.reader_buffer.get_start_iter(),
            self.reader_buffer.get_end_iter(),
        )
        start = self._reader_text.find(phrase)
        if start < 0:
            self._set_status("Quoted phrase was not found in the loaded case text.")
            return
        end = start + len(phrase)
        start_iter = self.reader_buffer.get_iter_at_offset(start)
        end_iter = self.reader_buffer.get_iter_at_offset(end)
        self.reader_buffer.apply_tag(self._reader_highlight_tag, start_iter, end_iter)
        self.reader_buffer.place_cursor(start_iter)
        self.reader_view.scroll_to_iter(start_iter, 0.15, True, 0.0, 0.2)

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
        self._sync_agent_subviews()


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
