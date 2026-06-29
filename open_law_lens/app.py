from __future__ import annotations

import os
import re
import signal
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

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
    CourtListenerSearchPage,
    CourtListenerSearchResult,
    FormattedCitation,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
    search_result_full_citation,
    us_long_date,
)
from .case_suggestions import (
    CaseSuggestion,
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    matching_case_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from .citation_links import (
    CitedCaseLink,
    citation_italic_spans,
    cited_case_links,
    cluster_citation_texts,
)
from .config import (
    AppConfig,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    concordance_file_path,
    coerce_reader_font_size,
    courtlistener_token,
    load_config,
    reader_font_css,
    normalize_reader_font_family,
    READER_FONT_FAMILY_OPTIONS,
    save_config,
)
from .dbus_commands import DBUS_COMMAND_GROUPS, DbusCommand, dbus_action_command
from .external_import import (
    build_external_import_cluster,
    clean_imported_opinion_text,
    imported_case_name_from_text,
    normalize_official_citation,
)
from .library import PageMarker, opinion_display_text
from .quality import official_pagination_quality
from .speech import DEFAULT_SPEECH_QUESTION_FILE, normalize_speech_question_text
from .text_search import literal_match_ranges
from .web_import import ExtractedWebpage, extract_webpage_text


PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENT_WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-codex-agent-vte.sh"
DEFAULT_CODEX_BIN = "codex"
READER_BG = "#ffffff"
READER_FG = "#000000"
AGENT_PANEL_MIN_HEIGHT = 260
AGENT_HEIGHT_DIVISOR = 4
AGENT_SUBVIEW_ANSWER = "answer"
AGENT_SUBVIEW_SESSION = "session"
AGENT_MODE_GENERAL = "general"
AGENT_MODE_CASE = "case"
GOOGLE_SCHOLAR_CASE_SEARCH_TEMPLATE = "https://scholar.google.com/scholar?hl=en&as_sdt=6,33&q={query}"
AGENT_MODE_RESULTS = "results"
SEARCH_NEXT_PAGE_TARGET = "search-next-page"
CITED_BY_INCLUDE_UNPUBLISHED_TARGET = "cited-by-include-unpublished"
CITED_BY_PUBLISHED_ONLY_TARGET = "cited-by-published-only"
AGENT_ANSWER_FONT_SIZE_PT = 14
SEARCH_RESULTS_FONT_SIZE_PT = 11
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


class DbusCommandsWindow(Adw.ApplicationWindow):
    def __init__(self, parent: "OpenLawLensWindow") -> None:
        super().__init__(application=parent.get_application(), title="D-Bus Commands")
        self.parent_window = parent
        self.set_transient_for(parent)
        self.set_default_size(900, 560)
        self.set_resizable(True)
        self._build_ui()

    def _build_ui(self) -> None:
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        header.set_title_widget(
            Adw.WindowTitle(title="D-Bus Commands", subtitle="Run or copy Open Law Lens actions")
        )
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup(
            title="How to use",
            description=(
                "Use Run to trigger an action inside Open Law Lens. "
                "Use Copy Command to place the GApplication call on your clipboard."
            ),
        )
        page.add(intro)

        for group_title, commands in DBUS_COMMAND_GROUPS:
            group = Adw.PreferencesGroup(title=group_title)
            group.add_css_class("list-stack")
            page.add(group)
            for command in commands:
                group.add(self._build_command_row(command))

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page)
        view.set_content(scroller)
        self.set_content(view)

    def _build_command_row(self, command: DbusCommand) -> Adw.ActionRow:
        row = Adw.ActionRow(
            title=command.title,
            subtitle=f"{command.action_name} - {command.description}",
        )
        row.set_activatable(False)

        suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        run_button = Gtk.Button(label="Run")
        run_button.add_css_class("suggested-action")
        run_button.add_css_class("flat")
        run_button.connect("clicked", self._on_run_clicked, command.action_name)
        suffix.append(run_button)

        copy_button = Gtk.Button(label="Copy Command")
        copy_button.add_css_class("flat")
        copy_button.add_css_class("link")
        copy_button.connect("clicked", self._on_copy_clicked, command.action_name)
        suffix.append(copy_button)

        row.add_suffix(suffix)
        return row

    def _on_run_clicked(self, _button: Gtk.Button, action_name: str) -> None:
        app = self.get_application()
        if app is None or app.lookup_action(action_name) is None:
            self.parent_window._set_status(f"Action not available: {action_name}")
            return
        app.activate_action(action_name, None)

    def _on_copy_clicked(self, _button: Gtk.Button, action_name: str) -> None:
        app = self.get_application()
        object_path = app.get_dbus_object_path() if app else None
        if object_path:
            command = dbus_action_command(action_name, object_path=object_path)
        else:
            command = dbus_action_command(action_name)
        display = Gdk.Display.get_default()
        if display:
            display.get_clipboard().set(command)
            self.parent_window._set_status("D-Bus command copied to clipboard.")


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

        display_group = Adw.PreferencesGroup(title="Display")
        reader_font_adjustment = Gtk.Adjustment(
            value=config.reader_font_size_pt,
            lower=8,
            upper=48,
            step_increment=1,
            page_increment=2,
        )
        self.reader_font_size_row = Adw.SpinRow(
            title="Case View Font Size (pt)",
            adjustment=reader_font_adjustment,
        )
        self.reader_font_size_row.set_digits(0)
        display_group.add(self.reader_font_size_row)

        self.reader_font_family_values = [name for name, _css in READER_FONT_FAMILY_OPTIONS]
        self.reader_font_family_row = Adw.ComboRow(title="Case View Font")
        self.reader_font_family_row.set_model(Gtk.StringList.new(self.reader_font_family_values))
        try:
            selected_index = self.reader_font_family_values.index(config.reader_font_family)
        except ValueError:
            selected_index = 0
        self.reader_font_family_row.set_selected(selected_index)
        display_group.add(self.reader_font_family_row)
        outer.append(display_group)

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
        selected_font_family_index = int(self.reader_font_family_row.get_selected())
        if 0 <= selected_font_family_index < len(self.reader_font_family_values):
            reader_font_family = self.reader_font_family_values[selected_font_family_index]
        else:
            reader_font_family = load_config().reader_font_family
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
                reader_font_size_pt=coerce_reader_font_size(
                    int(round(self.reader_font_size_row.get_value()))
                ),
                reader_font_family=normalize_reader_font_family(reader_font_family),
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
        self._agent_output_toggle_button: Gtk.Button | None = None
        self._agent_subview_strip: Gtk.Widget | None = None
        self._agent_subview_name = AGENT_SUBVIEW_SESSION
        self._agent_subview_toggle_guard = False
        self._agent_mode_buttons: dict[str, Gtk.ToggleButton] = {}
        self._agent_mode_toggle_guard = False
        self._agent_active = False
        self._agent_output_collapsed = False
        self._agent_workspace_path: Path | None = None
        self._agent_session_log_path: Path | None = None
        self._agent_answer_poll_id: int | None = None
        self._agent_last_answer_text = ""
        self._agent_search_output_visible = False
        self._agent_search_query = ""
        self._agent_search_results: list[CourtListenerSearchResult] = []
        self._agent_search_next_url = ""
        self._agent_search_heading = ""
        self._agent_search_scope_text = ""
        self._agent_cited_by_published_only = True
        self._agent_cited_by_total_count = 0
        self._agent_panel_height = AGENT_PANEL_MIN_HEIGHT
        self._agent_mode = AGENT_MODE_GENERAL
        self._selected_agent_mode = AGENT_MODE_GENERAL
        self._case_agent_text_sources: list[CaseTextSource] = []
        self._agent_link_tags: list[Gtk.TextTag] = []
        self._agent_link_lookup: dict[Gtk.TextTag, QuoteTarget] = {}
        self._agent_citation_link_lookup: dict[Gtk.TextTag, CitedCaseLink] = {}
        self._agent_search_link_lookup: dict[Gtk.TextTag, CourtListenerSearchResult] = {}
        self._agent_search_next_link_tags: set[Gtk.TextTag] = set()
        self._agent_search_action_link_lookup: dict[Gtk.TextTag, str] = {}
        self._agent_search_highlight_tags: list[Gtk.TextTag] = []
        self._agent_motion_controller: Gtk.EventControllerMotion | None = None
        self._agent_click_gesture: Gtk.GestureClick | None = None
        self._reader_text = ""
        self._reader_highlight_tag: Gtk.TextTag | None = None
        self._reader_find_tag: Gtk.TextTag | None = None
        self._reader_find_current_tag: Gtk.TextTag | None = None
        self._reader_find_bar: Gtk.Widget | None = None
        self._reader_find_entry: Gtk.Entry | None = None
        self._reader_find_count_label: Gtk.Label | None = None
        self._reader_find_matches: list[tuple[int, int]] = []
        self._reader_find_index = -1
        self._reader_citation_italic_tag: Gtk.TextTag | None = None
        self._reader_citation_link_tags: list[Gtk.TextTag] = []
        self._reader_citation_link_lookup: dict[Gtk.TextTag, CitedCaseLink] = {}
        self._reader_citation_motion_controller: Gtk.EventControllerMotion | None = None
        self._reader_citation_click_gesture: Gtk.GestureClick | None = None
        self._reader_header_citation: FormattedCitation | None = None
        self._reader_has_official_pagination = False
        self._last_lookup_text = ""
        self._external_lookup_window: Gtk.Window | None = None
        self._pending_quote_target: QuoteTarget | None = None
        self._settings_window: SettingsWindow | None = None
        self._dbus_commands_window: DbusCommandsWindow | None = None
        self._shortcuts_window: Gtk.ShortcutsWindow | None = None
        self._case_suggestions: list[CaseSuggestion] = []
        self._case_suggestions_loaded = False
        self._case_completion_matches: list[CaseSuggestion] = []
        self._case_completion_selected_index = 0
        self._case_completion_results_scroller: Gtk.ScrolledWindow | None = None
        self._case_completion_list_box: Gtk.ListBox | None = None
        self._case_completion_changing = False
        self._case_completion_click_gesture: Gtk.GestureClick | None = None
        self._css_provider: Gtk.CssProvider | None = None
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
        show_dbus_commands = Gio.SimpleAction.new("show_dbus_commands", None)
        show_dbus_commands.connect("activate", self._on_show_dbus_commands)
        self.add_action(show_dbus_commands)
        focus_citation = Gio.SimpleAction.new("focus_citation", None)
        focus_citation.connect("activate", self._on_focus_citation)
        self.add_action(focus_citation)
        focus_law_question = Gio.SimpleAction.new("focus_law_question", None)
        focus_law_question.connect("activate", self._on_focus_law_question)
        self.add_action(focus_law_question)
        focus_cache_question = Gio.SimpleAction.new("focus_cache_question", None)
        focus_cache_question.connect("activate", self._on_focus_cache_question)
        self.add_action(focus_cache_question)
        show_shortcuts = Gio.SimpleAction.new("show_shortcuts", None)
        show_shortcuts.connect("activate", self._on_show_shortcuts)
        self.add_action(show_shortcuts)
        open_official_search = Gio.SimpleAction.new("open_official_search", None)
        open_official_search.connect("activate", self._on_open_official_search)
        self.add_action(open_official_search)
        import_official_text = Gio.SimpleAction.new("import_official_text", None)
        import_official_text.connect("activate", self._on_import_official_text)
        self.add_action(import_official_text)

    def _install_css(self) -> None:
        provider = self._css_provider or Gtk.CssProvider()
        config = load_config()
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
            box.case-reader-fixed-header {{
              background-color: {READER_BG};
              padding: 4px 12px 8px 12px;
            }}
            label.case-reader-fixed-header {{
              color: {READER_FG};
              background-color: {READER_BG};
              font-family: {reader_font_css(config.reader_font_family)};
              font-size: {config.reader_font_size_pt}pt;
              font-weight: bold;
            }}
            button.case-reader-copy-button {{
              color: {READER_FG};
              background-color: {READER_BG};
              background-image: none;
              border: none;
              box-shadow: none;
              padding: 4px;
              min-width: 28px;
              min-height: 28px;
            }}
            button.case-reader-copy-button:hover {{
              background-color: #eeeeee;
            }}
            button.case-reader-copy-button:active {{
              background-color: #dddddd;
            }}
            textview.case-reader {{
              color: {READER_FG};
              background-color: {READER_BG};
              font-family: {reader_font_css(config.reader_font_family)};
              font-size: {config.reader_font_size_pt}pt;
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
            list.case-list row.case-cache-row {{
              border-radius: 8px;
              margin: 3px 4px;
              background-color: alpha(@window_fg_color, 0.03);
            }}
            list.case-list row.case-cache-row > box {{
              border-radius: 8px;
            }}
            list.case-list row.case-cache-row:hover {{
              background-color: alpha(@window_fg_color, 0.06);
            }}
            list.case-list row:selected {{
              background-color: alpha(@window_fg_color, 0.08);
              color: @window_fg_color;
            }}
            list.case-list row:selected label {{
              color: @window_fg_color;
            }}
            button.case-row-icon-button {{
              min-width: 24px;
              min-height: 24px;
              padding: 2px;
              border-radius: 6px;
              color: alpha(@window_fg_color, 0.45);
            }}
            button.case-row-icon-button:hover {{
              background-color: alpha(@window_fg_color, 0.08);
              color: alpha(@window_fg_color, 0.75);
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
            box.reader-find-chip {{
              background-color: alpha(@window_bg_color, 0.96);
              border: 1px solid alpha(@window_fg_color, 0.14);
              border-radius: 8px;
              padding: 4px;
              box-shadow: 0 2px 8px alpha(@window_fg_color, 0.16);
            }}
            entry.reader-find-entry {{
              min-width: 220px;
            }}
            label.reader-find-count {{
              min-width: 44px;
              font-size: 0.86rem;
              color: alpha(@window_fg_color, 0.72);
            }}
            """.encode("utf-8")
        )
        if self._css_provider is None and (display := Gdk.Display.get_default()):
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        self._css_provider = provider

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
        self._install_reader_find_key_controller(root)

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
        menu.append("Keyboard Shortcuts", "win.show_shortcuts")
        menu.append("D-Bus Commands", "win.show_dbus_commands")
        menu.append("Find Official Text", "win.open_official_search")
        menu.append("Import Official Text", "win.import_official_text")
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
            self.citation_entry.set_text("")
            self.citation_entry.set_position(-1)
        finally:
            self._case_completion_changing = False
        self._hide_case_completion()
        self.citation_entry.grab_focus()
        self._open_case_suggestion(suggestion)
        return True

    def _open_case_suggestion(self, suggestion: CaseSuggestion) -> None:
        if suggestion.cluster_id:
            cluster = self.client.library.read_cluster(suggestion.cluster_id)
            if cluster is not None:
                cluster_id = self.client.cache.upsert_cluster(cluster)
                if cluster_id:
                    self._set_sidebar_clusters(self.client.cached_clusters(), select_cluster_id=cluster_id)
                    self._refresh_case_suggestion_index(force=True)
                    if self.case_list.get_selected_row() is None:
                        self._set_status(f"Library: cached {suggestion.lookup_text}, but could not select the case.")
                    else:
                        self._set_status(f"Library: opened {suggestion.lookup_text}.")
                    return
        self._start_lookup(suggestion.lookup_text)

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
        )
        self._reader_citation_italic_tag = self.reader_buffer.create_tag(
            "reader-citation-italic",
            style=Pango.Style.ITALIC,
        )
        self._reader_highlight_tag = self.reader_buffer.create_tag(
            "agent-quote-highlight",
            background="#fff0a6",
        )
        self._reader_find_tag = self.reader_buffer.create_tag(
            "reader-find-match",
            background="#fff3b0",
        )
        self._reader_find_current_tag = self.reader_buffer.create_tag(
            "reader-find-current-match",
            background="#ffd35a",
            weight=Pango.Weight.BOLD,
        )
        self.reader_header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.reader_header_box.add_css_class("case-reader-fixed-header")
        self.reader_header_box.set_hexpand(True)
        self.reader_header_box.set_visible(False)

        self.reader_header_label = Gtk.Label(label="", xalign=0.5)
        self.reader_header_label.add_css_class("case-reader-fixed-header")
        self.reader_header_label.set_wrap(True)
        self.reader_header_label.set_justify(Gtk.Justification.CENTER)
        self.reader_header_label.set_selectable(True)
        self.reader_header_label.set_hexpand(True)
        self.reader_header_box.append(self.reader_header_label)

        self.reader_header_copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.reader_header_copy_button.add_css_class("case-reader-copy-button")
        self.reader_header_copy_button.set_tooltip_text("Copy citation")
        self.reader_header_copy_button.set_valign(Gtk.Align.CENTER)
        self.reader_header_copy_button.connect("clicked", self._on_copy_reader_citation_clicked)
        self.reader_header_box.append(self.reader_header_copy_button)

        self.reader_header_cited_by_button = Gtk.Button(icon_name="edit-find-symbolic")
        self.reader_header_cited_by_button.add_css_class("case-reader-copy-button")
        self.reader_header_cited_by_button.set_tooltip_text("Show later citing cases")
        self.reader_header_cited_by_button.set_valign(Gtk.Align.CENTER)
        self.reader_header_cited_by_button.connect("clicked", self._on_cited_by_clicked)
        self.reader_header_box.append(self.reader_header_cited_by_button)

        self.reader_view = Gtk.TextView(buffer=self.reader_buffer)
        self.reader_view.set_editable(False)
        self.reader_view.set_cursor_visible(False)
        self.reader_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.reader_view.set_left_margin(22)
        self.reader_view.set_right_margin(22)
        self.reader_view.set_top_margin(18)
        self.reader_view.set_bottom_margin(18)
        self.reader_view.add_css_class("case-reader")
        self._install_reader_find_key_controller(self.reader_view)
        self._install_reader_citation_link_controllers()

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
        frame.append(self.reader_header_box)
        frame.append(reader_scroller)
        reader_overlay = Gtk.Overlay()
        reader_overlay.set_hexpand(True)
        reader_overlay.set_vexpand(True)
        reader_overlay.set_child(frame)
        reader_overlay.add_overlay(self._build_reader_find_bar())
        box.append(reader_overlay)
        self.reader_buffer.set_text("")
        return box

    def _build_reader_find_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.add_css_class("reader-find-chip")
        bar.set_halign(Gtk.Align.END)
        bar.set_valign(Gtk.Align.START)
        bar.set_margin_top(10)
        bar.set_margin_end(10)
        bar.set_visible(False)

        entry = Gtk.Entry()
        entry.add_css_class("reader-find-entry")
        entry.set_placeholder_text("Find in case")
        entry.connect("changed", self._on_reader_find_entry_changed)
        entry.connect("activate", self._on_reader_find_entry_activate)
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_reader_find_entry_key_pressed)
        entry.add_controller(key_controller)
        bar.append(entry)

        count = Gtk.Label(label="0/0")
        count.add_css_class("reader-find-count")
        count.set_xalign(0.5)
        bar.append(count)

        previous_button = Gtk.Button(icon_name="go-up-symbolic")
        previous_button.add_css_class("flat")
        previous_button.set_tooltip_text("Previous match")
        previous_button.connect("clicked", self._on_reader_find_previous_clicked)
        bar.append(previous_button)

        next_button = Gtk.Button(icon_name="go-down-symbolic")
        next_button.add_css_class("flat")
        next_button.set_tooltip_text("Next match")
        next_button.connect("clicked", self._on_reader_find_next_clicked)
        bar.append(next_button)

        close_button = Gtk.Button(icon_name="window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.set_tooltip_text("Close find")
        close_button.connect("clicked", self._on_reader_find_close_clicked)
        bar.append(close_button)

        self._reader_find_bar = bar
        self._reader_find_entry = entry
        self._reader_find_count_label = count
        return bar

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
        answer_scroller.set_min_content_height(self._agent_panel_height)
        answer_scroller.set_max_content_height(self._agent_panel_height)
        answer_scroller.set_size_request(-1, self._agent_panel_height)
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

        collapse_button = Gtk.Button(icon_name="go-up-symbolic")
        collapse_button.add_css_class("flat")
        collapse_button.set_tooltip_text("Hide agent output")
        collapse_button.set_visible(False)
        collapse_button.connect("clicked", self._on_agent_output_toggle_clicked)
        row.append(collapse_button)
        self._agent_output_toggle_button = collapse_button

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

    def _set_reader_text(
        self,
        text: str,
        page_markers: list[PageMarker] | None = None,
    ) -> bool:
        self._close_reader_find(clear_entry=True)
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
        self._apply_reader_citation_italics(text)
        self._apply_reader_citation_links(text)
        if self._pending_quote_target is not None:
            target = self._pending_quote_target
            self._pending_quote_target = None
            self._highlight_reader_phrase(target.phrase)
        return False

    def _set_reader_header(
        self,
        text: str,
        citation: FormattedCitation | None = None,
    ) -> None:
        header = text.strip()
        self._reader_header_citation = citation
        self.reader_header_label.set_text(header)
        self.reader_header_copy_button.set_visible(citation is not None)
        self.reader_header_cited_by_button.set_visible(
            bool(header and self._selected_cluster)
        )
        self.reader_header_box.set_visible(bool(header))

    def _case_header_text(self, cluster: dict[str, Any]) -> str:
        formatted_citation = format_official_california_citation(cluster)
        if formatted_citation is not None:
            return formatted_citation.plain_text
        title = cluster_title(cluster)
        citation = cluster_citation_line(cluster)
        return title if not citation else f"{title}\n{citation}"

    def _case_header_citation(self, cluster: dict[str, Any]) -> FormattedCitation | None:
        return format_official_california_citation(cluster)

    def _on_copy_reader_citation_clicked(self, _button: Gtk.Button) -> None:
        if self._reader_header_citation is None:
            self._set_status("No citation available to copy.")
            return
        self._copy_formatted_citation(self._reader_header_citation)

    def _on_cited_by_clicked(self, _button: Gtk.Button) -> None:
        cluster = self._selected_cluster
        if cluster is None:
            self._set_status("Select a case first.")
            return
        self._start_cited_by_lookup(cluster)

    def _apply_reader_citation_links(self, text: str) -> None:
        table = self.reader_buffer.get_tag_table()
        if table is not None:
            for tag in self._reader_citation_link_tags:
                table.remove(tag)
        self._reader_citation_link_tags.clear()
        self._reader_citation_link_lookup.clear()
        excluded = cluster_citation_texts(self._selected_cluster)
        for index, link in enumerate(cited_case_links(text, excluded_citations=excluded)):
            start = max(0, min(link.start_offset, len(text)))
            end = max(start, min(link.end_offset, len(text)))
            if start == end:
                continue
            tag = self.reader_buffer.create_tag(
                f"reader-citation-link-{index}",
                underline=Pango.Underline.SINGLE,
                foreground="#1a5fb4",
            )
            self.reader_buffer.apply_tag(
                tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )
            self._reader_citation_link_tags.append(tag)
            self._reader_citation_link_lookup[tag] = link

    def _apply_reader_citation_italics(self, text: str) -> None:
        if self._reader_citation_italic_tag is None:
            return
        for span in citation_italic_spans(text):
            start = max(0, min(span.start_offset, len(text)))
            end = max(start, min(span.end_offset, len(text)))
            if start == end:
                continue
            self.reader_buffer.apply_tag(
                self._reader_citation_italic_tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )

    def _install_reader_citation_link_controllers(self) -> None:
        if self._reader_citation_motion_controller is None:
            motion = Gtk.EventControllerMotion()
            motion.connect("motion", self._on_reader_citation_motion)
            motion.connect("enter", self._on_reader_citation_motion)
            motion.connect("leave", self._on_reader_citation_leave)
            self.reader_view.add_controller(motion)
            self._reader_citation_motion_controller = motion
        if self._reader_citation_click_gesture is None:
            click = Gtk.GestureClick.new()
            click.set_button(Gdk.BUTTON_PRIMARY)
            click.connect("released", self._on_reader_citation_click)
            self.reader_view.add_controller(click)
            self._reader_citation_click_gesture = click

    def _reader_citation_link_at_coords(self, x: float, y: float) -> CitedCaseLink | None:
        bx, by = self.reader_view.window_to_buffer_coords(Gtk.TextWindowType.WIDGET, int(x), int(y))
        iter_result = self.reader_view.get_iter_at_location(int(bx), int(by))
        if isinstance(iter_result, tuple):
            success, iter_ = iter_result
            if not success:
                return None
        else:
            iter_ = iter_result
        if iter_ is None:
            return None
        for tag in iter_.get_tags():
            link = self._reader_citation_link_lookup.get(tag)
            if link is not None:
                return link
        return None

    def _on_reader_citation_motion(
        self,
        _controller: Gtk.EventControllerMotion,
        x: float,
        y: float,
    ) -> None:
        if self._reader_citation_link_at_coords(x, y):
            self.reader_view.set_cursor_from_name("pointer")
        else:
            self.reader_view.set_cursor_from_name(None)

    def _on_reader_citation_leave(self, _controller: Gtk.EventControllerMotion) -> None:
        self.reader_view.set_cursor_from_name(None)

    def _on_reader_citation_click(
        self,
        gesture: Gtk.GestureClick,
        _n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        if button and button != Gdk.BUTTON_PRIMARY:
            return
        link = self._reader_citation_link_at_coords(x, y)
        if link is None:
            return
        self._open_cited_case_link(link)

    def _open_cited_case_link(self, link: CitedCaseLink) -> None:
        current_cluster_id = cluster_id_from_cluster(self._selected_cluster or {})
        self._set_status(f"Opening {link.lookup_text}...")
        thread = threading.Thread(
            target=self._cited_case_lookup_worker,
            args=(link.lookup_text, current_cluster_id),
            daemon=True,
        )
        thread.start()

    def _cited_case_lookup_worker(self, citation: str, current_cluster_id: str) -> None:
        try:
            result = self.client.lookup_citation(citation)
            clusters = dedupe_case_clusters(self.client.clusters_from_lookup(result))
            cluster = next(
                (
                    candidate
                    for candidate in clusters
                    if cluster_id_from_cluster(candidate) != current_cluster_id
                ),
                clusters[0] if clusters else None,
            )
            if cluster is None:
                GLib.idle_add(self._set_status, f"No case found for {citation}.")
                return
            cluster_id = cluster_id_from_cluster(cluster)
            if not cluster_id:
                GLib.idle_add(self._set_status, f"No cached case id found for {citation}.")
                return
            self.client.fetch_cluster_opinions(cluster)
            source = self.client.last_lookup_source or "Lookup"
            GLib.idle_add(self._finish_cited_case_lookup, citation, cluster_id, source)
        except (CourtListenerError, ValueError) as exc:
            GLib.idle_add(self._set_status, f"Unable to open {citation}: {exc}")

    def _finish_cited_case_lookup(self, citation: str, cluster_id: str, source: str) -> bool:
        clusters = self.client.cached_clusters()
        self._set_sidebar_clusters(clusters, select_cluster_id=cluster_id)
        self._refresh_case_suggestion_index(force=True)
        if self.case_list.get_selected_row() is None:
            self._set_status(f"Cached {citation}, but could not select the case.")
        else:
            self._set_status(f"{source}: opened {citation}.")
        return False

    def _install_reader_find_key_controller(self, widget: Gtk.Widget) -> None:
        key_controller = Gtk.EventControllerKey()
        key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_controller.connect("key-pressed", self._on_reader_find_key_pressed)
        widget.add_controller(key_controller)

    def _on_reader_find_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        has_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        has_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if has_ctrl and keyval in {Gdk.KEY_f, Gdk.KEY_F}:
            self._open_reader_find()
            return True
        if has_ctrl and keyval in {Gdk.KEY_g, Gdk.KEY_G}:
            self._move_reader_find_match(-1 if has_shift else 1)
            return True
        if keyval == Gdk.KEY_Escape and self._reader_find_bar is not None and self._reader_find_bar.get_visible():
            self._close_reader_find(clear_entry=False)
            return True
        return False

    def _open_reader_find(self) -> None:
        if self._reader_find_bar is None or self._reader_find_entry is None:
            return
        self._reader_find_bar.set_visible(True)
        self._reader_find_entry.grab_focus()
        self._reader_find_entry.select_region(0, -1)
        self._refresh_reader_find_matches(scroll_to_match=True)

    def _close_reader_find(self, *, clear_entry: bool) -> None:
        if self._reader_find_bar is not None:
            self._reader_find_bar.set_visible(False)
        if clear_entry and self._reader_find_entry is not None:
            self._reader_find_entry.set_text("")
        self._reader_find_matches = []
        self._reader_find_index = -1
        self._update_reader_find_count()
        self._clear_reader_find_tags()

    def _on_reader_find_entry_changed(self, _entry: Gtk.Entry) -> None:
        self._reader_find_index = 0
        self._refresh_reader_find_matches(scroll_to_match=True)

    def _on_reader_find_entry_activate(self, _entry: Gtk.Entry) -> None:
        self._move_reader_find_match(1)

    def _on_reader_find_entry_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self._close_reader_find(clear_entry=False)
            self.reader_view.grab_focus()
            return True
        if keyval in {Gdk.KEY_Return, Gdk.KEY_KP_Enter}:
            direction = -1 if state & Gdk.ModifierType.SHIFT_MASK else 1
            self._move_reader_find_match(direction)
            return True
        return False

    def _on_reader_find_previous_clicked(self, _button: Gtk.Button) -> None:
        self._move_reader_find_match(-1)

    def _on_reader_find_next_clicked(self, _button: Gtk.Button) -> None:
        self._move_reader_find_match(1)

    def _on_reader_find_close_clicked(self, _button: Gtk.Button) -> None:
        self._close_reader_find(clear_entry=False)
        self.reader_view.grab_focus()

    def _refresh_reader_find_matches(self, *, scroll_to_match: bool) -> None:
        query = self._reader_find_entry.get_text() if self._reader_find_entry is not None else ""
        self._reader_find_matches = literal_match_ranges(self._reader_text, query)
        if not self._reader_find_matches:
            self._reader_find_index = -1
        elif self._reader_find_index < 0 or self._reader_find_index >= len(self._reader_find_matches):
            self._reader_find_index = 0
        self._apply_reader_find_tags(scroll_to_match=scroll_to_match)
        self._update_reader_find_count()

    def _move_reader_find_match(self, direction: int) -> None:
        if self._reader_find_bar is None or not self._reader_find_bar.get_visible():
            self._open_reader_find()
            return
        if not self._reader_find_matches:
            self._set_status("No matches.")
            return
        self._reader_find_index = (self._reader_find_index + direction) % len(self._reader_find_matches)
        self._apply_reader_find_tags(scroll_to_match=True)
        self._update_reader_find_count()

    def _clear_reader_find_tags(self) -> None:
        start = self.reader_buffer.get_start_iter()
        end = self.reader_buffer.get_end_iter()
        if self._reader_find_tag is not None:
            self.reader_buffer.remove_tag(self._reader_find_tag, start, end)
        if self._reader_find_current_tag is not None:
            self.reader_buffer.remove_tag(self._reader_find_current_tag, start, end)

    def _apply_reader_find_tags(self, *, scroll_to_match: bool) -> None:
        self._clear_reader_find_tags()
        if self._reader_find_tag is None or self._reader_find_current_tag is None:
            return
        for start, end in self._reader_find_matches:
            self.reader_buffer.apply_tag(
                self._reader_find_tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )
        if 0 <= self._reader_find_index < len(self._reader_find_matches):
            start, end = self._reader_find_matches[self._reader_find_index]
            start_iter = self.reader_buffer.get_iter_at_offset(start)
            end_iter = self.reader_buffer.get_iter_at_offset(end)
            self.reader_buffer.apply_tag(self._reader_find_current_tag, start_iter, end_iter)
            self.reader_buffer.place_cursor(start_iter)
            if scroll_to_match:
                self.reader_view.scroll_to_iter(start_iter, 0.15, True, 0.0, 0.2)

    def _update_reader_find_count(self) -> None:
        if self._reader_find_count_label is None:
            return
        if not self._reader_find_matches:
            self._reader_find_count_label.set_text("0/0")
            return
        self._reader_find_count_label.set_text(
            f"{self._reader_find_index + 1}/{len(self._reader_find_matches)}"
        )

    def _sync_agent_subviews(self) -> None:
        self._update_agent_panel_height()
        has_agent_output = (
            self._agent_active
            or bool(self._agent_last_answer_text)
            or self._agent_search_output_visible
        )
        output_visible = has_agent_output and not self._agent_output_collapsed
        if self._agent_output_toggle_button is not None:
            self._agent_output_toggle_button.set_visible(has_agent_output)
            self._agent_output_toggle_button.set_icon_name(
                "go-down-symbolic" if self._agent_output_collapsed else "go-up-symbolic"
            )
            self._agent_output_toggle_button.set_tooltip_text(
                "Show agent output" if self._agent_output_collapsed else "Hide agent output"
            )
        if self._agent_subview_strip is not None:
            self._agent_subview_strip.set_visible(
                output_visible and self._agent_mode != AGENT_MODE_RESULTS
            )
        if self._agent_answer_scroller is not None:
            self._agent_answer_scroller.set_visible(
                output_visible and self._agent_subview_name == AGENT_SUBVIEW_ANSWER
            )
        if self._agent_session_widget is not None:
            self._agent_session_widget.set_visible(
                output_visible and self._agent_subview_name == AGENT_SUBVIEW_SESSION
            )
            if self._agent_subview_name == AGENT_SUBVIEW_SESSION:
                self._agent_session_widget.set_size_request(-1, self._agent_panel_height)
            else:
                self._agent_session_widget.set_size_request(-1, -1)

    def _on_agent_output_toggle_clicked(self, _button: Gtk.Button) -> None:
        self._agent_output_collapsed = not self._agent_output_collapsed
        self._sync_agent_subviews()

    def _update_agent_panel_height(self) -> None:
        allocated_height = self.get_allocated_height()
        proportional_height = (
            allocated_height // AGENT_HEIGHT_DIVISOR
            if allocated_height > 0
            else AGENT_PANEL_MIN_HEIGHT
        )
        height = max(AGENT_PANEL_MIN_HEIGHT, proportional_height)
        if height == self._agent_panel_height:
            return
        self._agent_panel_height = height
        if self._agent_answer_scroller is not None:
            self._agent_answer_scroller.set_min_content_height(height)
            self._agent_answer_scroller.set_max_content_height(height)
            self._agent_answer_scroller.set_size_request(-1, height)
        if (
            self._agent_session_widget is not None
            and self._agent_subview_name == AGENT_SUBVIEW_SESSION
        ):
            self._agent_session_widget.set_size_request(-1, height)

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
            mode
            if mode in {AGENT_MODE_GENERAL, AGENT_MODE_CASE}
            else AGENT_MODE_GENERAL
        )
        if hasattr(self, "agent_question_entry"):
            if self._selected_agent_mode == AGENT_MODE_GENERAL:
                placeholder = "Ask a California law question"
            else:
                placeholder = "Ask about marked Research Cache cases"
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

    def _focus_entry_and_select_text(self, entry: Gtk.Entry) -> None:
        entry.grab_focus()
        entry.select_region(0, -1)

    def _on_focus_citation(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._focus_entry_and_select_text(self.citation_entry)

    def _on_focus_law_question(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._set_agent_mode(AGENT_MODE_GENERAL)
        self._focus_entry_and_select_text(self.agent_question_entry)

    def _on_focus_cache_question(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._set_agent_mode(AGENT_MODE_CASE)
        self._focus_entry_and_select_text(self.agent_question_entry)

    def _build_shortcuts_window(self) -> Gtk.ShortcutsWindow:
        if self._shortcuts_window is not None:
            return self._shortcuts_window

        window = Gtk.ShortcutsWindow(
            transient_for=self,
            modal=False,
            hide_on_close=True,
            title=f"{APP_NAME} Keyboard Shortcuts",
        )
        window.set_default_size(640, 420)

        section = Gtk.ShortcutsSection(title="Keyboard Shortcuts")

        navigation_group = Gtk.ShortcutsGroup(title="Navigation")
        navigation_group.append(
            Gtk.ShortcutsShortcut(title="Focus citation field", accelerator="<Primary>L")
        )
        navigation_group.append(
            Gtk.ShortcutsShortcut(title="Focus California law question", accelerator="<Primary>Q")
        )
        navigation_group.append(
            Gtk.ShortcutsShortcut(
                title="Focus marked-cache question",
                accelerator="<Primary><Shift>Q",
            )
        )
        section.append(navigation_group)

        search_group = Gtk.ShortcutsGroup(title="Case Text Find")
        search_group.append(
            Gtk.ShortcutsShortcut(title="Open find", accelerator="<Primary>F")
        )
        search_group.append(
            Gtk.ShortcutsShortcut(title="Next find result", accelerator="<Primary>G")
        )
        search_group.append(
            Gtk.ShortcutsShortcut(
                title="Previous find result",
                accelerator="<Primary><Shift>G",
            )
        )
        section.append(search_group)

        help_group = Gtk.ShortcutsGroup(title="Reference")
        help_group.append(Gtk.ShortcutsShortcut(title="Show keyboard shortcuts", accelerator="F1"))
        section.append(help_group)

        window.add_section(section)
        self._shortcuts_window = window
        return window

    def _on_show_shortcuts(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        window = self._build_shortcuts_window()
        window.set_transient_for(self)
        window.present()

    def _on_show_dbus_commands(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self._dbus_commands_window is None:
            self._dbus_commands_window = DbusCommandsWindow(self)
            self._dbus_commands_window.connect("close-request", self._on_dbus_commands_closed)
        self._dbus_commands_window.present()

    def _on_dbus_commands_closed(self, _window: Gtk.Window) -> bool:
        self._dbus_commands_window = None
        return False

    def _on_window_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        self._update_agent_panel_height()
        return True

    def reload_settings(self) -> None:
        self.client = CourtListenerClient.default()
        self._install_css()
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
        self._set_reader_header("")
        self.reader_buffer.set_text("")
        self._set_status("Research Cache cleared. Library preserved.")

    def _on_open_official_search(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        query = self._official_search_query()
        if not query.strip():
            self._set_status("Enter or select a case before searching for official text.")
            return
        self._show_external_lookup_window(query)

    def _official_search_query(self) -> str:
        cluster = self._selected_cluster
        if cluster is not None:
            citation = cluster_citation_line(cluster)
            formatted = format_official_california_citation(cluster)
            query = formatted.plain_text if formatted is not None else f"{cluster_short_title(cluster)} {citation}"
            return query.strip()
        entry_text = self.citation_entry.get_text().strip()
        if entry_text:
            return entry_text
        return self._last_lookup_text.strip()

    def _external_search_urls(self, query: str) -> list[tuple[str, str]]:
        encoded = quote_plus(query)
        return [("Google Scholar Case Law", GOOGLE_SCHOLAR_CASE_SEARCH_TEMPLATE.format(query=encoded))]

    def _launch_external_url(self, url: str) -> bool:
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error as exc:
            self._set_status(f"Could not open browser: {exc.message}")
            return False
        return True

    def _show_external_lookup_window(self, query: str) -> None:
        clean_query = re.sub(r"\s+", " ", query).strip()
        if not clean_query:
            return
        if self._external_lookup_window is not None:
            self._close_external_lookup_window()
        window = Gtk.Window(title="Find Case Online")
        window.set_transient_for(self)
        window.set_modal(False)
        window.set_default_size(520, 300)
        window.connect("close-request", self._on_external_lookup_closed)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        heading = Gtk.Label(label=clean_query, xalign=0)
        heading.set_wrap(True)
        heading.add_css_class("heading")
        box.append(heading)

        for label, url in self._external_search_urls(clean_query):
            button = Gtk.Button(label=label)
            button.set_halign(Gtk.Align.FILL)
            button.set_hexpand(True)
            button.connect("clicked", self._on_external_lookup_button_clicked, url)
            box.append(button)

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        source_entry = Gtk.Entry()
        source_entry.set_hexpand(True)
        source_entry.set_placeholder_text("Google Scholar case URL")
        source_row.append(source_entry)
        fetch_button = Gtk.Button(label="Fetch URL")
        fetch_button.connect("clicked", self._on_external_lookup_fetch_clicked, source_entry)
        source_row.append(fetch_button)
        box.append(source_row)

        import_button = Gtk.Button(label="Import Official Text")
        import_button.connect(
            "clicked",
            self._on_external_lookup_import_clicked,
        )
        box.append(import_button)

        window.set_child(box)
        self._external_lookup_window = window
        window.present()

    def _on_external_lookup_closed(self, _window: Gtk.Window) -> bool:
        self._external_lookup_window = None
        return False

    def _close_external_lookup_window(self) -> None:
        window = self._external_lookup_window
        self._external_lookup_window = None
        if window is not None:
            window.close()

    def _on_external_lookup_button_clicked(self, _button: Gtk.Button, url: str) -> None:
        if self._launch_external_url(url):
            self._set_status("Opened Google Scholar case search in browser.")

    def _on_external_lookup_import_clicked(self, _button: Gtk.Button) -> None:
        self._on_import_official_text(None, None)

    def _on_external_lookup_fetch_clicked(self, _button: Gtk.Button, source_entry: Gtk.Entry) -> None:
        self._on_import_official_text(
            None,
            None,
            initial_source_url=source_entry.get_text().strip(),
            fetch_on_present=True,
        )

    def _default_import_case_name(self) -> str:
        if self._selected_cluster is not None:
            title = cluster_short_title(self._selected_cluster)
            citation = normalize_official_citation(title)
            return "" if citation and citation == title else title
        return ""

    def _default_import_official_citation(self) -> str:
        cluster = self._selected_cluster
        if cluster is not None:
            formatted = format_official_california_citation(cluster)
            if formatted is not None:
                citation = normalize_official_citation(formatted.plain_text)
                if citation:
                    return citation
            citation = normalize_official_citation(cluster_citation_line(cluster))
            if citation:
                return citation
        return normalize_official_citation(self._official_search_query())

    def _on_import_official_text(
        self,
        _action: Gio.SimpleAction | None,
        _parameter: GLib.Variant | None,
        *,
        initial_source_url: str = "",
        fetch_on_present: bool = False,
    ) -> bool:
        default_citation = self._default_import_official_citation()
        if not default_citation:
            self._set_status("Select a case or enter an official California citation before importing.")
            return False
        window = Gtk.Window(title="Import Official Text")
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(720, 560)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        case_name_entry = Gtk.Entry()
        case_name_entry.set_placeholder_text("Case name")
        case_name_entry.set_text(self._default_import_case_name())
        box.append(case_name_entry)

        citation_entry = Gtk.Entry()
        citation_entry.set_placeholder_text("Official citation")
        citation_entry.set_text(default_citation)
        box.append(citation_entry)

        text_buffer = Gtk.TextBuffer()

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        source_entry = Gtk.Entry()
        source_entry.set_hexpand(True)
        source_entry.set_placeholder_text("Source URL")
        source_entry.set_text(initial_source_url)
        source_row.append(source_entry)
        fetch_button = Gtk.Button(label="Fetch URL")
        fetch_button.connect(
            "clicked",
            self._on_import_fetch_url_clicked,
            case_name_entry,
            citation_entry,
            source_entry,
            text_buffer,
        )
        source_row.append(fetch_button)
        box.append(source_row)

        text_view = Gtk.TextView(buffer=text_buffer)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_left_margin(8)
        text_view.set_right_margin(8)
        text_view.set_top_margin(8)
        text_view.set_bottom_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(text_view)
        box.append(scroller)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _button: window.close())
        buttons.append(cancel_button)
        import_button = Gtk.Button(label="Import")
        import_button.connect(
            "clicked",
            self._on_import_official_text_confirmed,
            window,
            case_name_entry,
            citation_entry,
            source_entry,
            text_buffer,
        )
        buttons.append(import_button)
        box.append(buttons)

        window.set_child(box)
        window.present()
        if fetch_on_present:
            self._on_import_fetch_url_clicked(
                fetch_button,
                case_name_entry,
                citation_entry,
                source_entry,
                text_buffer,
            )
        return True

    def _on_import_fetch_url_clicked(
        self,
        button: Gtk.Button,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
    ) -> None:
        url = source_entry.get_text().strip()
        button.set_sensitive(False)
        self._set_status("Fetching URL...")
        thread = threading.Thread(
            target=self._import_fetch_url_worker,
            args=(url, button, case_name_entry, citation_entry, source_entry, text_buffer),
            daemon=True,
        )
        thread.start()

    def _import_fetch_url_worker(
        self,
        url: str,
        button: Gtk.Button,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
    ) -> None:
        try:
            webpage = extract_webpage_text(url)
        except RuntimeError as exc:
            GLib.idle_add(self._finish_import_fetch_url_error, button, str(exc))
            return
        GLib.idle_add(
            self._finish_import_fetch_url,
            webpage,
            button,
            case_name_entry,
            citation_entry,
            source_entry,
            text_buffer,
        )

    def _finish_import_fetch_url_error(self, button: Gtk.Button, message: str) -> bool:
        button.set_sensitive(True)
        self._set_status(message)
        return False

    def _finish_import_fetch_url(
        self,
        webpage: ExtractedWebpage,
        button: Gtk.Button,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
    ) -> bool:
        button.set_sensitive(True)
        source_entry.set_text(webpage.url)
        cleaned_text = clean_imported_opinion_text(webpage.text) or webpage.text
        text_buffer.set_text(cleaned_text)
        case_source = "\n".join(part for part in (webpage.title, cleaned_text) if part)
        if not case_name_entry.get_text().strip():
            case_name_entry.set_text(imported_case_name_from_text(case_source))
        if not normalize_official_citation(citation_entry.get_text()):
            citation_entry.set_text(normalize_official_citation(case_source))
        self._set_status("Fetched URL text. Review it, then import.")
        return False

    def _on_import_official_text_confirmed(
        self,
        _button: Gtk.Button,
        window: Gtk.Window,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
    ) -> None:
        start = text_buffer.get_start_iter()
        end = text_buffer.get_end_iter()
        pasted_text = text_buffer.get_text(start, end, True).strip()
        if not pasted_text:
            self._set_status("Paste official text before importing.")
            return
        imported_text = clean_imported_opinion_text(pasted_text)
        if not imported_text:
            self._set_status("Imported text was empty after cleanup.")
            return
        official_citation = (
            normalize_official_citation(citation_entry.get_text())
            or normalize_official_citation(pasted_text)
            or self._default_import_official_citation()
        )
        case_name = case_name_entry.get_text().strip() or imported_case_name_from_text(pasted_text)
        try:
            cluster = build_external_import_cluster(
                case_name=case_name,
                official_citation=official_citation,
                imported_text=pasted_text,
                source_url=source_entry.get_text().strip(),
            )
        except ValueError as exc:
            self._set_status(str(exc))
            return
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            self._set_status("Selected case has no cluster id.")
            return
        text_field = "html_with_citations" if re.search(r"<[a-zA-Z][^>]*>", imported_text) else "plain_text"
        opinion = {
            "id": f"official-import-{cluster_id}",
            "cluster_id": cluster_id,
            text_field: imported_text,
            "source_url": source_entry.get_text().strip(),
            "source_type": "user_imported_official_text",
        }
        display = opinion_display_text(opinion)
        quality = official_pagination_quality(cluster, [display])
        if not quality.eligible:
            self._set_status(f"Import not saved: {quality.reason}")
            return
        self.client.library.upsert_cluster(cluster)
        self.client.library.upsert_opinion(opinion)
        self.client.library.update_case_opinion_ids(cluster_id, [str(opinion["id"])])
        self.client.library.upsert_lookup(
            quality.official_citation,
            [{"status": 200, "clusters": [cluster]}],
        )
        self.client.cache.upsert_cluster(cluster)
        self.client.cache.write_resource("opinions", str(opinion["id"]), opinion)
        self.client.cache.update_case_opinions(cluster, [str(opinion["id"])])
        self.client.cache.write_lookup(
            quality.official_citation,
            [{"status": 200, "clusters": [cluster]}],
        )
        self._set_sidebar_clusters(self.client.cached_clusters(), select_cluster_id=cluster_id)
        self._refresh_case_suggestion_index(force=True)
        self._reader_has_official_pagination = True
        self._set_reader_header(
            self._case_header_text(cluster),
            self._case_header_citation(cluster),
        )
        self._set_reader_text(display.text, display.page_markers)
        self._set_status("Imported official reporter text, saved to Library, and added to Research Cache.")
        self._close_external_lookup_window()
        window.close()

    def _on_lookup_clicked(self, _widget: Gtk.Widget) -> None:
        entry_text = self.citation_entry.get_text().strip()
        if not entry_text:
            self._set_status("Enter a citation.")
            return
        citation = self._lookup_text_from_entry(entry_text)
        self._start_lookup(citation)

    def _start_lookup(self, citation: str) -> None:
        self._last_lookup_text = citation.strip()
        self._hide_case_completion()
        self._set_status(f"Looking up {citation}...")
        self._set_reader_header("")
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

    def _lookup_worker(self, citation: str) -> None:
        try:
            result = self.client.lookup_citation(citation)
            raw_clusters = self.client.clusters_from_lookup(result)
            shown_clusters = dedupe_case_clusters(raw_clusters)
            status = self._lookup_status_text(result, raw_clusters, shown_clusters)
            GLib.idle_add(self._apply_lookup_result, result, shown_clusters, status, citation)
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
        else:
            self._set_reader_header("")

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
            row.add_css_class("case-cache-row")
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            cluster_id = cluster_id_from_cluster(cluster)
            formatted_citation = format_official_california_citation(cluster)
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            actions_box.set_valign(Gtk.Align.START)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic")
            remove_button.add_css_class("flat")
            remove_button.add_css_class("case-row-icon-button")
            remove_button.set_tooltip_text("Remove from Research Cache")
            remove_button.set_sensitive(bool(cluster_id))
            remove_button.connect("clicked", self._on_remove_cached_case_clicked, cluster_id, cluster)
            actions_box.append(remove_button)
            row_box.append(actions_box)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title_text = cluster_short_title(cluster)
            title = Gtk.Label(label=title_text, xalign=0)
            title.set_wrap(True)
            text_box.append(title)
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
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make case available to Case Agent")
            check.set_active(self.client.cache.is_agent_selected(cluster_id))
            check.connect("toggled", self._on_agent_case_toggled, cluster_id)
            row_box.append(check)
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

    def _on_remove_cached_case_clicked(
        self,
        _button: Gtk.Button,
        cluster_id: str,
        cluster: dict[str, Any],
    ) -> None:
        if not cluster_id:
            self._set_status("Could not remove case from Research Cache.")
            return
        current_cluster_id = cluster_id_from_cluster(self._selected_cluster or {})
        removed_selected = current_cluster_id == cluster_id
        title = cluster_short_title(cluster)
        if not self.client.cache.remove_case(cluster_id):
            self._set_status("Case was not found in Research Cache.")
            return
        if removed_selected:
            self._selected_cluster = None
            self._set_reader_header("")
            self.reader_buffer.set_text("")
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id="" if removed_selected else current_cluster_id,
        )
        self._refresh_case_suggestion_index(force=True)
        self._set_status(f"Removed {title} from Research Cache. Library preserved.")

    def _apply_lookup_result(
        self,
        _result: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        status: str,
        citation: str = "",
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
            self._set_reader_header("")
            self.reader_buffer.set_text(status)
            if citation.strip():
                self._show_external_lookup_window(citation)
                self._set_status(f"{status}. External search options opened.")
        return False

    def _apply_error(self, message: str) -> bool:
        self._set_status(message)
        self._set_reader_header("")
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
        self._set_reader_header(
            self._case_header_text(cluster),
            self._case_header_citation(cluster),
        )
        self.reader_buffer.set_text(f"Loading {cluster_title(cluster)}...")
        thread = threading.Thread(target=self._case_worker, args=(cluster,), daemon=True)
        thread.start()

    def _case_worker(self, cluster: dict[str, Any]) -> None:
        try:
            opinions = self.client.fetch_cluster_opinions(cluster)
            text_parts: list[str] = []
            page_markers: list[PageMarker] = []
            text_length = 0
            for opinion in opinions:
                display = self.client.opinion_display(opinion)
                if not display.text:
                    continue
                if text_parts:
                    text_parts.append("\n\n")
                    text_length += 2
                base_offset = text_length
                text_parts.append(display.text)
                text_length += len(display.text)
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
            text = "".join(text_parts)
            if not text:
                text = "No opinion text found."
            quality = official_pagination_quality(
                cluster,
                [opinion_display_text(opinion) for opinion in opinions],
            )
            GLib.idle_add(
                self._set_reader_text,
                text,
                page_markers,
            )
            GLib.idle_add(self._finish_case_quality_status, quality.eligible, quality.reason)
        except CourtListenerError as exc:
            GLib.idle_add(self._apply_error, str(exc))

    def _finish_case_quality_status(self, eligible: bool, reason: str) -> bool:
        self._reader_has_official_pagination = eligible
        if eligible:
            self._set_status("Saved to Library with official reporter pagination.")
        elif reason:
            self._set_status(f"Transient view only: {reason} Use Find Official Text or Import Official Text.")
        return False

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
        mode = self._selected_agent_mode
        question = self.agent_question_entry.get_text().strip()
        if not question:
            self._set_status("Enter an agent question.")
            return
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
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

    def submit_speech_question(self, mode: str) -> None:
        try:
            raw_question = DEFAULT_SPEECH_QUESTION_FILE.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except FileNotFoundError:
            self._set_status(f"Speech question file not found: {DEFAULT_SPEECH_QUESTION_FILE}")
            return
        except OSError as exc:
            self._set_status(f"Could not read speech question file: {exc}")
            return
        question = normalize_speech_question_text(raw_question)
        if not question:
            self._set_status("Speech question file is empty.")
            return
        self._set_agent_mode(mode)
        self.agent_question_entry.set_text(question)
        self.agent_question_entry.set_position(-1)
        self._on_agent_launch(self.agent_question_entry)

    def _start_cited_by_lookup(self, cluster: dict[str, Any]) -> None:
        self._stop_agent()
        self._stop_agent_answer_polling()
        self._clear_agent_answer()
        title = cluster_short_title(cluster)
        self._agent_output_collapsed = False
        self._agent_search_output_visible = True
        self._agent_search_query = title
        self._agent_search_results = []
        self._agent_search_next_url = ""
        self._agent_cited_by_published_only = True
        self._agent_cited_by_total_count = 0
        self._agent_search_heading = f"Cited By: {title}"
        self._agent_search_scope_text = (
            "CourtListener Citation Graph | Later citing cases, not legal-treatment signals"
        )
        self._agent_mode = AGENT_MODE_RESULTS
        self._set_agent_subview(AGENT_SUBVIEW_ANSWER)
        self._set_status(f"Finding cases that cite {title}...")
        if self._agent_answer_buffer is not None:
            self._agent_answer_buffer.set_text("Finding later citing cases...")
        thread = threading.Thread(
            target=self._cited_by_worker,
            args=(cluster, ""),
            daemon=True,
        )
        thread.start()

    def _cited_by_worker(self, cluster: dict[str, Any], next_url: str) -> None:
        try:
            page = self.client.citing_opinions(cluster, url=next_url)
            GLib.idle_add(
                self._finish_cited_by_lookup,
                cluster_short_title(cluster),
                page,
                bool(next_url),
            )
        except (CourtListenerError, ValueError) as exc:
            GLib.idle_add(self._apply_search_error, str(exc))

    def _finish_cited_by_lookup(
        self,
        title: str,
        page: CourtListenerSearchPage,
        append: bool,
    ) -> bool:
        if not append:
            self._agent_search_results = []
        self._agent_search_results.extend(page.results)
        self._agent_search_next_url = page.next_url
        self._agent_cited_by_total_count = max(
            self._agent_cited_by_total_count,
            page.count,
            len(self._agent_search_results),
        )
        self._agent_search_heading = f"Cited By: {title}"
        self._agent_search_scope_text = (
            "CourtListener Citation Graph | Later citing cases, not legal-treatment signals"
        )
        self._render_cited_by_results(title)
        return False

    def _published_cited_by_results(self) -> list[CourtListenerSearchResult]:
        return [
            result
            for result in self._agent_search_results
            if result.status == "Published"
        ]

    def _render_cited_by_results(self, title: str) -> None:
        published_results = self._published_cited_by_results()
        unpublished_count = len(self._agent_search_results) - len(published_results)
        if self._agent_cited_by_published_only:
            rendered_results = published_results
            mode_text = "Published citing cases"
            action_text = "Include unpublished" if unpublished_count else ""
            action_target = (
                CITED_BY_INCLUDE_UNPUBLISHED_TARGET if unpublished_count else ""
            )
        else:
            rendered_results = self._agent_search_results
            mode_text = "Published and unpublished citing cases"
            action_text = "Show published only" if unpublished_count else ""
            action_target = CITED_BY_PUBLISHED_ONLY_TARGET if unpublished_count else ""
        loaded_count = len(self._agent_search_results)
        summary_text = (
            f"{mode_text} | Showing {len(rendered_results)} of "
            f"{loaded_count} loaded"
        )
        self._render_search_results(
            title,
            rendered_results,
            True,
            self._agent_cited_by_total_count or loaded_count,
            self._agent_search_next_url,
            heading=self._agent_search_heading,
            summary_text=summary_text,
            action_text=action_text,
            action_target=action_target,
        )
        if self._agent_cited_by_published_only:
            self._set_status(
                f"Cited By: showing {len(rendered_results)} published citing case(s), "
                f"{loaded_count} loaded."
            )
        else:
            self._set_status(f"Cited By: showing {loaded_count} citing case(s).")

    def _apply_search_error(self, message: str) -> bool:
        self._set_status(message)
        if self._agent_answer_buffer is not None:
            self._agent_answer_buffer.set_text(message)
        return False

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
        self._agent_output_collapsed = False
        if not AGENT_WRAPPER.is_file():
            self._set_status(f"Agent wrapper not found: {AGENT_WRAPPER}")
            return
        env = os.environ.copy()
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt_path),
                "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                "OPEN_LAW_LENS_AGENT_MODE": mode,
                "OPEN_LAW_LENS_CACHE_DIR": str(self.client.cache.root),
                "CODEX_BIN": os.environ.get("OPEN_LAW_LENS_CODEX_BIN", DEFAULT_CODEX_BIN),
            }
        )
        profile = os.environ.get("OPEN_LAW_LENS_CODEX_PROFILE", "").strip()
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
        self._sync_agent_subviews()
        self._set_status("Embedded agent session ended.")

    def _clear_agent_answer(self) -> None:
        self._agent_last_answer_text = ""
        self._agent_search_output_visible = False
        self._agent_search_query = ""
        self._agent_search_results = []
        self._agent_search_next_url = ""
        self._agent_search_heading = ""
        self._agent_search_scope_text = ""
        self._agent_cited_by_published_only = True
        self._agent_cited_by_total_count = 0
        self._agent_link_lookup.clear()
        self._agent_citation_link_lookup.clear()
        self._agent_search_link_lookup.clear()
        self._agent_search_next_link_tags.clear()
        self._agent_search_action_link_lookup.clear()
        self._agent_search_highlight_tags.clear()
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
        self._agent_citation_link_lookup.clear()
        self._agent_search_link_lookup.clear()
        self._agent_search_next_link_tags.clear()
        self._agent_search_highlight_tags.clear()
        clean_text, quote_spans = self._extract_agent_quote_spans(text)
        rendered, markdown_spans, offset_map = self._render_markdown_text(clean_text)
        buffer.set_text(rendered)
        self._apply_agent_markdown_spans(buffer, markdown_spans)
        self._apply_agent_citation_italics(buffer, rendered)
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
        if self._agent_mode == AGENT_MODE_GENERAL:
            self._apply_agent_citation_links(buffer, rendered)

    def _apply_agent_citation_italics(self, buffer: Gtk.TextBuffer, text: str) -> None:
        table = buffer.get_tag_table()
        if table is None:
            return
        italic_tag = table.lookup("agent-citation-italic")
        if italic_tag is None:
            italic_tag = buffer.create_tag("agent-citation-italic", style=Pango.Style.ITALIC)
        for span in citation_italic_spans(text):
            start = max(0, min(span.start_offset, len(text)))
            end = max(start, min(span.end_offset, len(text)))
            if start == end:
                continue
            buffer.apply_tag(
                italic_tag,
                buffer.get_iter_at_offset(start),
                buffer.get_iter_at_offset(end),
            )

    def _apply_agent_citation_links(self, buffer: Gtk.TextBuffer, text: str) -> None:
        for link in cited_case_links(text):
            start = max(0, min(link.start_offset, len(text)))
            end = max(start, min(link.end_offset, len(text)))
            if start == end:
                continue
            tag = buffer.create_tag(
                None,
                foreground_rgba=self._resolve_agent_quote_color(),
                underline=Pango.Underline.NONE,
                weight=Pango.Weight.MEDIUM,
            )
            buffer.apply_tag(
                tag,
                buffer.get_iter_at_offset(start),
                buffer.get_iter_at_offset(end),
            )
            self._agent_link_tags.append(tag)
            self._agent_citation_link_lookup[tag] = link

    def _render_search_results(
        self,
        query: str,
        results: list[CourtListenerSearchResult],
        include_unpublished: bool,
        total_count: int,
        next_url: str,
        *,
        heading: str = "",
        scope_text: str = "",
        summary_text: str = "",
        action_text: str = "",
        action_target: str = "",
    ) -> None:
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
            for tag in self._agent_search_highlight_tags:
                try:
                    table.remove(tag)
                except TypeError:
                    pass
        self._agent_link_tags.clear()
        self._agent_link_lookup.clear()
        self._agent_citation_link_lookup.clear()
        self._agent_search_link_lookup.clear()
        self._agent_search_next_link_tags.clear()
        self._agent_search_action_link_lookup.clear()
        self._agent_search_highlight_tags.clear()

        scope = scope_text or (
            "California published and unpublished cases"
            if include_unpublished
            else "California published cases"
        )
        title_line = heading or f"CourtListener Results: {query}"
        lines = [
            title_line,
            summary_text or f"{scope} | Showing {len(results)} of {total_count}",
        ]
        action_span: tuple[int, int] | None = None
        offset = sum(len(line) + 1 for line in lines)
        if action_text and action_target:
            action_span = (offset, offset + len(action_text))
            lines.append(action_text)
            offset += len(action_text) + 1
        lines.append("")
        offset += 1
        spans: list[tuple[int, int, CourtListenerSearchResult]] = []
        meta_spans: list[tuple[int, int]] = []
        highlight_spans: list[tuple[int, int]] = []
        next_span: tuple[int, int] | None = None
        if not results:
            no_matches = "No matching cases found."
            lines.append(no_matches)
            offset += len(no_matches) + 1
            lines.append("")
            offset += 1
        else:
            for result in results:
                title = search_result_full_citation(result)
                start = offset
                end = offset + len(title)
                lines.append(title)
                offset += len(title) + 1
                spans.append((start, end, result))
                meta_parts = [
                    part
                    for part in (
                        result.court or result.court_id,
                        us_long_date(result.date_filed),
                        result.status,
                    )
                    if part
                ]
                if meta_parts:
                    meta = " | ".join(meta_parts)
                    meta_start = offset
                    lines.append(meta)
                    offset += len(meta) + 1
                    meta_spans.append((meta_start, meta_start + len(meta)))
                if result.snippet:
                    snippet = self._search_snippet_text(result.snippet)
                    snippet_start = offset
                    lines.append(snippet)
                    highlight_spans.extend(
                        (snippet_start + start, snippet_start + end)
                        for start, end in self._search_highlight_ranges(snippet, query)
                    )
                    offset += len(snippet) + 1
                lines.append("")
                offset += 1
        if next_url:
            next_text = "Next results"
            next_span = (offset, offset + len(next_text))
            lines.append(next_text)
            offset += len(next_text) + 1

        buffer.set_text("\n".join(lines))
        self._apply_search_text_tags(buffer, highlight_spans, meta_spans)
        link_color = self._resolve_agent_quote_color()
        for start, end, result in spans:
            tag = buffer.create_tag(
                None,
                foreground_rgba=link_color,
                underline=Pango.Underline.SINGLE,
                weight=Pango.Weight.MEDIUM,
            )
            buffer.apply_tag(
                tag,
                buffer.get_iter_at_offset(start),
                buffer.get_iter_at_offset(end),
            )
            self._agent_link_tags.append(tag)
            self._agent_search_link_lookup[tag] = result
        self._apply_search_action_tag(buffer, action_span, action_target)
        if next_span is not None:
            tag = buffer.create_tag(
                None,
                foreground_rgba=link_color,
                underline=Pango.Underline.SINGLE,
                weight=Pango.Weight.MEDIUM,
            )
            buffer.apply_tag(
                tag,
                buffer.get_iter_at_offset(next_span[0]),
                buffer.get_iter_at_offset(next_span[1]),
            )
            self._agent_link_tags.append(tag)
            self._agent_search_next_link_tags.add(tag)

    def _apply_search_action_tag(
        self,
        buffer: Gtk.TextBuffer,
        action_span: tuple[int, int] | None,
        action_target: str,
    ) -> None:
        if action_span is None or not action_target:
            return
        link_color = self._resolve_agent_quote_color()
        tag = buffer.create_tag(
            None,
            foreground_rgba=link_color,
            underline=Pango.Underline.SINGLE,
            weight=Pango.Weight.MEDIUM,
        )
        buffer.apply_tag(
            tag,
            buffer.get_iter_at_offset(action_span[0]),
            buffer.get_iter_at_offset(action_span[1]),
        )
        self._agent_link_tags.append(tag)
        self._agent_search_action_link_lookup[tag] = action_target

    def _apply_search_text_tags(
        self,
        buffer: Gtk.TextBuffer,
        highlight_spans: list[tuple[int, int]],
        meta_spans: list[tuple[int, int]] | None = None,
    ) -> None:
        search_text_tag = buffer.create_tag(None, size_points=SEARCH_RESULTS_FONT_SIZE_PT)
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        buffer.apply_tag(search_text_tag, start_iter, end_iter)
        self._agent_search_highlight_tags.append(search_text_tag)
        if meta_spans:
            meta_color = self._resolve_search_metadata_color()
            meta_tag = buffer.create_tag(None, foreground_rgba=meta_color)
            for start, end in meta_spans:
                if end <= start:
                    continue
                buffer.apply_tag(
                    meta_tag,
                    buffer.get_iter_at_offset(start),
                    buffer.get_iter_at_offset(end),
                )
            self._agent_search_highlight_tags.append(meta_tag)
        highlight_tag = buffer.create_tag(
            None,
            foreground_rgba=self._resolve_agent_quote_color(),
            underline=Pango.Underline.NONE,
            weight=Pango.Weight.BOLD,
        )
        applied_highlight = False
        for start, end in highlight_spans:
            if end <= start:
                continue
            buffer.apply_tag(
                highlight_tag,
                buffer.get_iter_at_offset(start),
                buffer.get_iter_at_offset(end),
            )
            applied_highlight = True
        if applied_highlight:
            self._agent_search_highlight_tags.append(highlight_tag)
        else:
            try:
                table = buffer.get_tag_table()
                if table is not None:
                    table.remove(highlight_tag)
            except TypeError:
                pass

    def _search_snippet_text(self, snippet: str) -> str:
        text = re.sub(r"\s+", " ", snippet).strip()
        max_length = 650
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3].rstrip()}..."

    def _search_highlight_ranges(self, text: str, query: str) -> list[tuple[int, int]]:
        exact = re.sub(r"\s+", " ", query.strip())
        ranges = self._literal_ranges_case_insensitive(text, exact) if exact else []
        if ranges:
            return ranges
        terms = [
            term
            for term in re.findall(r"[A-Za-z0-9']+", query)
            if len(term) >= 3 and term.casefold() not in {"and", "or", "the"}
        ]
        ranges = []
        for term in terms:
            ranges.extend(self._literal_ranges_case_insensitive(text, term))
        return self._merge_ranges(ranges)

    def _literal_ranges_case_insensitive(self, text: str, needle: str) -> list[tuple[int, int]]:
        if not needle:
            return []
        ranges: list[tuple[int, int]] = []
        folded_text = text.casefold()
        folded_needle = needle.casefold()
        start = 0
        while True:
            index = folded_text.find(folded_needle, start)
            if index < 0:
                break
            end = index + len(folded_needle)
            ranges.append((index, end))
            start = end
        return ranges

    def _merge_ranges(self, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not ranges:
            return []
        merged: list[tuple[int, int]] = []
        for start, end in sorted(ranges):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
                continue
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        return merged

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

    def _resolve_search_metadata_color(self) -> Gdk.RGBA:
        base = self._resolve_agent_quote_color()
        luminance = (0.2126 * base.red) + (0.7152 * base.green) + (0.0722 * base.blue)
        color = Gdk.RGBA()
        color.parse("#4f6f8f" if luminance < 0.5 else "#86a6c4")
        color.alpha = 1.0
        return color

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

    def _agent_link_at_coords(
        self,
        x: float,
        y: float,
    ) -> CitedCaseLink | QuoteTarget | CourtListenerSearchResult | str | None:
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
            if tag in self._agent_search_next_link_tags:
                return SEARCH_NEXT_PAGE_TARGET
            action_target = self._agent_search_action_link_lookup.get(tag)
            if action_target is not None:
                return action_target
            target = self._agent_link_lookup.get(tag)
            if target is not None:
                return target
            citation_link = self._agent_citation_link_lookup.get(tag)
            if citation_link is not None:
                return citation_link
            search_result = self._agent_search_link_lookup.get(tag)
            if search_result is not None:
                return search_result
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
        if target == SEARCH_NEXT_PAGE_TARGET:
            self._load_next_search_results()
        elif target in {
            CITED_BY_INCLUDE_UNPUBLISHED_TARGET,
            CITED_BY_PUBLISHED_ONLY_TARGET,
        }:
            self._toggle_cited_by_publication_filter(str(target))
        elif isinstance(target, CourtListenerSearchResult):
            self._open_search_result(target)
        elif isinstance(target, CitedCaseLink):
            self._open_cited_case_link(target)
        elif target is not None:
            self._open_quote_target(target)

    def _toggle_cited_by_publication_filter(self, target: str) -> None:
        if not self._agent_search_heading.startswith("Cited By:"):
            return
        self._agent_cited_by_published_only = (
            target == CITED_BY_PUBLISHED_ONLY_TARGET
        )
        title = self._agent_search_heading.removeprefix("Cited By:").strip()
        self._render_cited_by_results(title)

    def _load_next_search_results(self) -> None:
        if not self._agent_search_next_url:
            return
        next_url = self._agent_search_next_url
        self._agent_search_next_url = ""
        if (
            self._agent_search_heading.startswith("Cited By:")
            and self._selected_cluster is not None
        ):
            self._set_status("Loading more citing cases...")
            thread = threading.Thread(
                target=self._cited_by_worker,
                args=(self._selected_cluster, next_url),
                daemon=True,
            )
        else:
            return
        thread.start()

    def _open_search_result(self, result: CourtListenerSearchResult) -> None:
        self._set_status(f"Opening {result.case_name}...")
        thread = threading.Thread(
            target=self._search_result_open_worker,
            args=(result,),
            daemon=True,
        )
        thread.start()

    def _search_result_open_worker(self, result: CourtListenerSearchResult) -> None:
        try:
            cluster = self.client.fetch_url(
                f"/api/rest/v4/clusters/{result.cluster_id}/",
                kind="clusters",
            )
            cluster_id = self.client.cache.upsert_cluster(cluster)
            GLib.idle_add(
                self._finish_search_result_open,
                cluster_id or result.cluster_id,
                result.case_name,
            )
        except CourtListenerError as exc:
            GLib.idle_add(self._set_status, f"Unable to open {result.case_name}: {exc}")

    def _finish_search_result_open(self, cluster_id: str, title: str) -> bool:
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id=cluster_id,
        )
        self._refresh_case_suggestion_index(force=True)
        if self.case_list.get_selected_row() is None:
            self._set_status(f"Cached {title}, but could not select the case.")
        else:
            self._set_status(f"Opened {title}.")
        return False

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
        self._install_actions()
        self.set_accels_for_action("win.focus_citation", ["<Primary>l"])
        self.set_accels_for_action("win.focus_law_question", ["<Primary>q"])
        self.set_accels_for_action("win.focus_cache_question", ["<Primary><Shift>q"])
        self.set_accels_for_action("win.show_shortcuts", ["F1"])

    def _install_actions(self) -> None:
        submit_speech_law_question = Gio.SimpleAction.new("submit_speech_law_question", None)
        submit_speech_law_question.connect(
            "activate",
            self._on_submit_speech_law_question,
        )
        self.add_action(submit_speech_law_question)

        submit_speech_cache_question = Gio.SimpleAction.new("submit_speech_cache_question", None)
        submit_speech_cache_question.connect(
            "activate",
            self._on_submit_speech_cache_question,
        )
        self.add_action(submit_speech_cache_question)

    def _on_activate(self, _app: Adw.Application) -> None:
        window = OpenLawLensWindow(self)
        window.present()

    def _main_window(self) -> OpenLawLensWindow:
        active = self.get_active_window()
        if isinstance(active, OpenLawLensWindow):
            return active
        for window in self.get_windows():
            if isinstance(window, OpenLawLensWindow):
                window.present()
                return window
        window = OpenLawLensWindow(self)
        window.present()
        return window

    def _on_submit_speech_law_question(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._main_window().submit_speech_question(AGENT_MODE_GENERAL)

    def _on_submit_speech_cache_question(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._main_window().submit_speech_question(AGENT_MODE_CASE)


def main() -> int:
    app = OpenLawLensApp()
    return int(app.run(None))
