from __future__ import annotations

import contextlib
import os
import re
import signal
import shutil
import sqlite3
import sys
import tempfile
import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Callable
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
    export_selected_authorities,
    extract_latest_codex_final_answer_from_jsonl,
    find_latest_codex_session_log_for_cwd,
    quote_match_spans,
    resolved_agent_quote_spans,
)
from .authority_resolver import first_authority_candidate
from .cache import cluster_id_from_cluster
from .cli_commands import CLI_COMMANDS
from .client import (
    CourtListenerClient,
    CourtListenerError,
    CourtListenerSearchResult,
    FormattedCitation,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
    format_published_slip_opinion_citation,
    search_result_full_citation,
    us_long_date,
)
from .case_suggestions import (
    CaseSuggestion,
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    load_concordance_rule_suggestions,
    load_concordance_statute_suggestions,
    matching_case_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from .citation_links import (
    CitedCaseLink,
    CitationStyleSpan,
    RuleLink,
    StatuteLink,
    citation_italic_spans,
    cited_case_links,
    cited_rule_links,
    cited_statute_links,
    cluster_citation_texts,
)
from .citation_model import official_citation_parts_from_cluster
from .config import (
    AGENT_PERMISSION_MODE_FULL_ACCESS,
    AGENT_PERMISSION_MODE_OPTIONS,
    AGENT_PERMISSION_MODE_SANDBOXED,
    AppConfig,
    BARE_STATUTE_LAW_CODE_OPTIONS,
    DEFAULT_APPEAL_ISSUE_PRESETS,
    DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
    concordance_file_path,
    coerce_reader_font_size,
    courtlistener_token,
    load_config,
    normalize_agent_permission_mode,
    normalize_appeal_issue_labels,
    normalize_appeal_issue_presets,
    normalize_bare_statute_law_code,
    normalize_reader_font_family,
    reader_font_css,
    READER_FONT_FAMILY_OPTIONS,
    save_config,
)
from .current_case import (
    CurrentCaseError,
    CurrentCaseSocf,
    current_case_socf,
    current_case_socf_odt,
    read_current_case,
)
from .dbus_commands import DBUS_COMMAND_GROUPS, DbusCommand, dbus_action_command
from .external_import import (
    build_external_import_cluster,
    clean_imported_opinion_text,
    imported_case_name_from_text,
    normalize_official_citation,
    repair_reporter_only_cluster_name,
    validated_import_official_citation,
)
from .fact_patterns import (
    FactPatternError,
    FactPatternExport,
    export_fact_pattern,
    extract_fact_pattern_text,
)
from .launch_request import pop_open_authority_request
from .library import (
    DisplayText,
    PageMarker,
    ResearchSet,
    normalize_display_quote_stacks,
    opinion_display_text,
)
from .quality import official_pagination_quality
from .reader_highlights import (
    ReaderHighlight,
    resolved_reader_highlights,
    toggle_reader_highlight,
)
from .scholar_search import (
    ScholarSearchError,
    ScholarSearchResult,
    search_first_case_direct,
)
from .slip_opinions import (
    DEFAULT_SLIP_OPINION_MAX_AGE_DAYS,
    SlipOpinionError,
    SlipOpinionResult,
    case_number_from_cluster,
    display_from_payload,
    normalize_case_number,
    slip_opinion_pdf_path,
    slip_metadata_from_display,
    slip_result_to_payload,
)
from .speech import DEFAULT_SPEECH_QUESTION_FILE, normalize_speech_question_text
from .rules import (
    CaliforniaRulesError,
    RuleCitation,
    parse_rule_citation,
    rule_pinpoint_citation,
    rule_subdivisions_for_range,
)
from .statutes import (
    LegInfoError,
    StatuteCitation,
    normalize_section,
    parse_statute_citation,
    statute_display_citation,
    statute_pinpoint_citation,
    statute_subdivisions_for_range,
)
from .text_search import literal_match_ranges
from .text_formatting import normalize_malformed_quote_stacks, smart_quote_display_text
from .web_import import ExtractedWebpage, extract_webpage_text


PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENT_WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-codex-agent-vte.sh"
DEFAULT_CODEX_BIN = "codex"
READER_BG = "#ffffff"
READER_FG = "#000000"
READER_RENDER_TEXT_CHUNK_SIZE = 8000
READER_RENDER_TAG_CHUNK_SIZE = 250
AGENT_PANEL_MIN_HEIGHT = 260
AGENT_HEIGHT_DIVISOR = 4
AGENT_SUBVIEW_ANSWER = "answer"
AGENT_SUBVIEW_SESSION = "session"
AGENT_MODE_GENERAL = "general"
AGENT_MODE_CASE = "case"
AGENT_MODE_APPEAL = "appeal"
CODEX_REASONING_EFFORT_XHIGH = "xhigh"
AGENT_MODE_ICONS = {
    AGENT_MODE_GENERAL: "license-symbolic",
    AGENT_MODE_CASE: "file-cabinet-symbolic",
}
GOOGLE_SCHOLAR_CASE_SEARCH_TEMPLATE = "https://scholar.google.com/scholar?hl=en&as_sdt=6,33&q={query}"
EXTERNAL_URL_RE = re.compile(r"https?://\S+")
SCHOLAR_FALLBACK_MANUAL_WINDOW = "manual_window"
SCHOLAR_FALLBACK_TRANSIENT_NOTICE = "transient_notice"
SCHOLAR_FALLBACK_NOTICE_ONLY = "notice_only"
OFFICIAL_PAGINATION_NOT_FOUND_TITLE = "Official Pagination Not Found"
OFFICIAL_PAGINATION_NOT_FOUND_MESSAGE = (
    "A version of this case with pagination from the official reporter was not found. "
    "You can view this version, but page citations may not match the official reporter."
)
OFFICIAL_PAGINATION_NOT_FOUND_ONLY_MESSAGE = (
    "A version of this case with pagination from the official reporter was not found."
)
READER_PAGINATION_NONE = "none"
READER_PAGINATION_OFFICIAL = "official"
READER_PAGINATION_SLIP = "slip"
SEARCH_NEXT_PAGE_TARGET = "search-next-page"
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


def appeal_issue_menu_label(issue: str, label: str = "", max_length: int = 72) -> str:
    source = label.strip() or issue
    for raw_line in source.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if len(line) <= max_length:
            return line
        return line[: max_length - 3].rstrip() + "..."
    return "Untitled argument"


def xhigh_reasoning_effort(enabled: bool) -> str:
    return CODEX_REASONING_EFFORT_XHIGH if enabled else ""


def build_agent_launch_env(
    client: CourtListenerClient,
    prompt_path: Path,
    workspace: Path,
    mode: str,
    config: AppConfig,
    reasoning_effort: str = "",
) -> dict[str, str]:
    permission_mode = normalize_agent_permission_mode(config.agent_permission_mode)
    sandbox_mode = "workspace-write"
    approval_policy = ""
    if permission_mode == AGENT_PERMISSION_MODE_FULL_ACCESS:
        sandbox_mode = "danger-full-access"
        approval_policy = "never"

    env = {
        "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt_path),
        "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
        "OPEN_LAW_LENS_AGENT_MODE": mode,
        "OPEN_LAW_LENS_CACHE_DIR": str(workspace / "research-cache"),
        "OPEN_LAW_LENS_CODEX_SANDBOX": sandbox_mode,
        "OPEN_LAW_LENS_CODEX_APPROVAL": approval_policy,
        "CODEX_BIN": os.environ.get("OPEN_LAW_LENS_CODEX_BIN", DEFAULT_CODEX_BIN),
    }
    if reasoning_effort == CODEX_REASONING_EFFORT_XHIGH:
        env["OPEN_LAW_LENS_CODEX_REASONING_EFFORT"] = reasoning_effort
    library = getattr(client, "library", None)
    library_path = getattr(library, "path", None)
    if library_path is not None:
        env["OPEN_LAW_LENS_LIBRARY_DB"] = str(library_path)
    return env


MARKDOWN_TOKEN_RE = re.compile(r"(\*\*([^*\n]+)\*\*|\*([^*\n]+)\*)")
BACKTICK_TOKEN_RE = re.compile(r"`([^`\n]+)`")
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


@dataclass(frozen=True)
class CaseReaderPayload:
    generation: int
    cache_generation: int
    cluster_id: str
    cluster: dict[str, Any]
    opinion_ids: tuple[str, ...]
    text: str
    page_markers: list[PageMarker]
    italic_spans: list[CitationStyleSpan]
    cited_links: list[CitedCaseLink]
    quality_eligible: bool
    quality_reason: str
    opinion_source: str
    pagination_mode: str = READER_PAGINATION_NONE
    slip_source_url: str = ""
    slip_case_number: str = ""


@dataclass(frozen=True)
class LibrarySuggestionOpenResult:
    lookup_text: str
    cluster: dict[str, Any]
    cache_generation: int


@dataclass(frozen=True)
class AgentExternalUrlLink:
    url: str


@dataclass(frozen=True)
class LinkPressState:
    target: object
    x: float
    y: float


def strip_agent_legal_authority_backticks(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        content = match.group(1)
        if (
            cited_case_links(content)
            or cited_statute_links(content)
            or cited_rule_links(content)
            or citation_italic_spans(content)
        ):
            return content
        return match.group(0)

    return BACKTICK_TOKEN_RE.sub(replace, text)


def build_case_reader_payload(
    cluster: dict[str, Any],
    displays: list[DisplayText],
    *,
    generation: int = 0,
    cache_generation: int = 0,
    opinion_ids: tuple[str, ...] = (),
    opinion_source: str = "",
    pagination_mode: str = "",
    slip_source_url: str = "",
    slip_case_number: str = "",
) -> CaseReaderPayload:
    text_parts: list[str] = []
    page_markers: list[PageMarker] = []
    text_length = 0
    for display in displays:
        display = normalize_display_quote_stacks(display)
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
    text = smart_quote_display_text("".join(text_parts) or "No opinion text found.")
    quality = official_pagination_quality(cluster, displays)
    resolved_pagination_mode = pagination_mode or (
        READER_PAGINATION_OFFICIAL if quality.eligible else READER_PAGINATION_NONE
    )
    return CaseReaderPayload(
        generation=generation,
        cache_generation=cache_generation,
        cluster_id=cluster_id_from_cluster(cluster),
        cluster=cluster,
        opinion_ids=opinion_ids,
        text=text,
        page_markers=page_markers,
        italic_spans=citation_italic_spans(text),
        cited_links=cited_case_links(text, excluded_citations=cluster_citation_texts(cluster)),
        quality_eligible=quality.eligible,
        quality_reason=quality.reason,
        opinion_source=opinion_source,
        pagination_mode=resolved_pagination_mode,
        slip_source_url=slip_source_url,
        slip_case_number=slip_case_number,
    )


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


class CliCommandsWindow(Adw.ApplicationWindow):
    def __init__(self, parent: "OpenLawLensWindow") -> None:
        super().__init__(application=parent.get_application(), title="CLI Commands")
        self.parent_window = parent
        self.set_transient_for(parent)
        self.set_default_size(900, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        header.set_title_widget(Adw.WindowTitle(title="CLI Commands"))
        view.add_top_bar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(16)
        outer.set_margin_bottom(16)
        outer.set_margin_start(16)
        outer.set_margin_end(16)

        intro = Gtk.Label(
            label=(
                "Run these from the OpenLawLens project directory. "
                "Extract commands print JSON by default; add --text to print only the authority text."
            ),
            xalign=0,
        )
        intro.set_wrap(True)
        outer.append(intro)

        command_list = Gtk.ListBox()
        command_list.add_css_class("boxed-list")
        command_list.set_selection_mode(Gtk.SelectionMode.NONE)
        for command in CLI_COMMANDS:
            row = Gtk.ListBoxRow()
            row.set_activatable(False)
            row.set_selectable(False)
            row.set_child(self._build_command_row(command))
            command_list.append(row)
        outer.append(command_list)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(outer)
        view.set_content(scroller)
        self.set_content(view)

    def _build_command_row(self, command: Any) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(10)
        row.set_margin_bottom(10)
        row.set_margin_start(12)
        row.set_margin_end(12)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)

        title = Gtk.Label(label=command.title, xalign=0)
        title.add_css_class("heading")
        title.set_wrap(True)
        text_box.append(title)

        name = Gtk.Label(label=command.name, xalign=0)
        name.add_css_class("monospace")
        name.add_css_class("dim-label")
        name.set_selectable(True)
        text_box.append(name)

        description = Gtk.Label(label=command.description, xalign=0)
        description.set_wrap(True)
        description.set_selectable(True)
        text_box.append(description)

        example = Gtk.Label(label=command.example, xalign=0)
        example.add_css_class("monospace")
        example.set_wrap(True)
        example.set_selectable(True)
        text_box.append(example)

        row.append(text_box)

        copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        copy_button.add_css_class("flat")
        copy_button.set_tooltip_text(f"Copy {command.name} example")
        copy_button.set_valign(Gtk.Align.CENTER)
        copy_button.connect("clicked", self._on_copy_cli_command_clicked, command.example)
        row.append(copy_button)
        return row

    def _on_copy_cli_command_clicked(self, _button: Gtk.Button, command: str) -> None:
        display = Gdk.Display.get_default()
        if display is None:
            self.parent_window._set_status("Could not access clipboard.")
            return
        display.get_clipboard().set(command)
        self.parent_window._set_status("CLI command copied to clipboard.")


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, parent: "OpenLawLensWindow") -> None:
        super().__init__(application=parent.get_application())
        self.parent_window = parent
        self.set_title("Settings")
        self.set_default_size(900, 760)
        self.set_modal(False)
        self._settings_page_keys: dict[Gtk.ListBoxRow, str] = {}
        self._settings_stack: Gtk.Stack | None = None

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Settings"))
        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        root.set_vexpand(True)

        basic_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        basic_box.set_hexpand(True)

        group = Adw.PreferencesGroup(title="CourtListener")
        self.token_row = self._build_token_row()
        config = load_config()
        self.token_row.set_text(config.courtlistener_token)
        group.add(self.token_row)
        basic_box.append(group)

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
        basic_box.append(display_group)

        authority_group = Adw.PreferencesGroup(title="Authority Lookup")
        self.bare_statute_law_code_values = [code for code, _label in BARE_STATUTE_LAW_CODE_OPTIONS]
        bare_statute_labels = [
            f"{label} ({code})"
            for code, label in BARE_STATUTE_LAW_CODE_OPTIONS
        ]
        self.bare_statute_law_code_row = Adw.ComboRow(
            title="Bare Number Statute Code",
            subtitle="When selected text is only a section number, open it as this California code.",
        )
        self.bare_statute_law_code_row.set_model(Gtk.StringList.new(bare_statute_labels))
        try:
            selected_bare_statute_index = self.bare_statute_law_code_values.index(
                config.default_bare_statute_law_code
            )
        except ValueError:
            selected_bare_statute_index = 0
        self.bare_statute_law_code_row.set_selected(selected_bare_statute_index)
        authority_group.add(self.bare_statute_law_code_row)
        basic_box.append(authority_group)

        concordance_group = Adw.PreferencesGroup(title="Concordance")
        self.concordance_row = Adw.EntryRow(title="Concordance file")
        self.concordance_row.set_text(config.concordance_file_path)
        self._add_concordance_row_buttons()
        concordance_group.add(self.concordance_row)
        basic_box.append(concordance_group)

        agent_group = Adw.PreferencesGroup(title="Agent Runtime")
        self.agent_permission_mode_values = [
            mode for mode, _label in AGENT_PERMISSION_MODE_OPTIONS
        ]
        agent_permission_mode_labels = [label for _mode, label in AGENT_PERMISSION_MODE_OPTIONS]
        self.agent_permission_mode_row = Adw.ComboRow(
            title="Embedded Codex Permissions",
            subtitle=(
                "Full access lets Codex use normal user paths without sandbox approval prompts."
            ),
        )
        self.agent_permission_mode_row.set_model(Gtk.StringList.new(agent_permission_mode_labels))
        try:
            selected_agent_permission_mode_index = self.agent_permission_mode_values.index(
                config.agent_permission_mode
            )
        except ValueError:
            selected_agent_permission_mode_index = 0
        self.agent_permission_mode_row.set_selected(selected_agent_permission_mode_index)
        agent_group.add(self.agent_permission_mode_row)
        basic_box.append(agent_group)

        root.append(basic_box)

        split = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        split.set_hexpand(True)
        split.set_vexpand(True)
        split.set_shrink_start_child(False)
        split.set_shrink_end_child(False)
        split.set_resize_start_child(False)
        split.set_resize_end_child(True)

        page_list = Gtk.ListBox()
        page_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        page_list.add_css_class("navigation-sidebar")
        page_list.connect("row-selected", self._on_settings_page_row_selected)

        page_list_scroller = Gtk.ScrolledWindow()
        page_list_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page_list_scroller.set_min_content_width(220)
        page_list_scroller.set_child(page_list)

        settings_stack = Gtk.Stack()
        settings_stack.set_hexpand(True)
        settings_stack.set_vexpand(True)
        settings_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._settings_stack = settings_stack

        appeal_group = Adw.PreferencesGroup(title="Appeal Issue Assessment")
        appeal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        appeal_box.set_margin_top(8)
        appeal_box.set_margin_bottom(8)
        appeal_box.set_margin_start(8)
        appeal_box.set_margin_end(8)

        file_label = Gtk.Label(label="Fact pattern ODT or PDF", xalign=0)
        file_label.add_css_class("dim-label")
        appeal_box.append(file_label)

        file_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.appeal_fact_pattern_entry = Gtk.Entry()
        self.appeal_fact_pattern_entry.set_hexpand(True)
        self.appeal_fact_pattern_entry.set_placeholder_text("Current case SOCF ODT")
        file_row.append(self.appeal_fact_pattern_entry)
        choose_fact_button = Gtk.Button(icon_name="document-open-symbolic")
        choose_fact_button.add_css_class("flat")
        choose_fact_button.set_tooltip_text("Choose fact pattern")
        choose_fact_button.connect("clicked", self._on_choose_appeal_fact_pattern)
        file_row.append(choose_fact_button)
        reset_fact_button = Gtk.Button(icon_name="view-refresh-symbolic")
        reset_fact_button.add_css_class("flat")
        reset_fact_button.set_tooltip_text("Use current case SOCF")
        reset_fact_button.connect("clicked", self._on_reset_appeal_fact_pattern)
        file_row.append(reset_fact_button)
        appeal_box.append(file_row)

        issues_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        issues_label = Gtk.Label(label="Arguments to assess", xalign=0)
        issues_label.add_css_class("dim-label")
        issues_label.set_hexpand(True)
        issues_header.append(issues_label)
        add_issue_button = Gtk.Button(icon_name="list-add-symbolic")
        add_issue_button.add_css_class("flat")
        add_issue_button.set_tooltip_text("Add argument")
        add_issue_button.connect("clicked", self._on_add_appeal_issue)
        issues_header.append(add_issue_button)
        appeal_box.append(issues_header)

        self.appeal_issue_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.appeal_issue_buffers: list[Gtk.TextBuffer] = []
        self.appeal_issue_label_entries: list[Gtk.Entry] = []
        appeal_box.append(self.appeal_issue_list_box)
        appeal_group.add(appeal_box)
        appeal_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        appeal_page.set_margin_top(12)
        appeal_page.set_margin_bottom(12)
        appeal_page.set_margin_start(12)
        appeal_page.set_margin_end(12)
        appeal_page.append(appeal_group)
        appeal_scroller = Gtk.ScrolledWindow()
        appeal_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        appeal_scroller.set_vexpand(True)
        appeal_scroller.set_child(appeal_page)
        self._reload_appeal_issue_editors(
            config.appeal_issue_presets,
            config.appeal_issue_labels,
        )
        self._refresh_appeal_fact_pattern_entry()

        (
            general_prompt_page,
            self.general_agent_prompt_buffer,
            self.general_agent_xhigh_switch,
        ) = self._build_prompt_settings_page(
            "General California Law Prompt",
            "Prompt",
            config.general_agent_prompt_template,
            config.general_agent_xhigh_reasoning,
        )
        (
            case_prompt_page,
            self.case_agent_prompt_buffer,
            self.case_agent_xhigh_switch,
        ) = self._build_prompt_settings_page(
            "Marked Research Cache Authorities Prompt",
            "Prompt",
            config.case_agent_prompt_template,
            config.case_agent_xhigh_reasoning,
        )
        (
            appeal_prompt_page,
            self.appeal_issue_agent_prompt_buffer,
            self.appeal_issue_xhigh_switch,
        ) = self._build_prompt_settings_page(
            "Appeal Issue Assessment Prompt",
            "Prompt",
            config.appeal_issue_agent_prompt_template,
            config.appeal_issue_xhigh_reasoning,
        )
        (
            later_treatment_prompt_page,
            self.later_treatment_agent_prompt_buffer,
            self.later_treatment_xhigh_switch,
        ) = self._build_prompt_settings_page(
            "Subsequent Treatment Prompt",
            "Prompt",
            config.later_treatment_agent_prompt_template,
            config.later_treatment_xhigh_reasoning,
        )

        pages = [
            ("appeal", "Appeal Arguments", appeal_scroller),
            ("general_prompt", "General Prompt", general_prompt_page),
            ("cache_prompt", "Research Cache Prompt", case_prompt_page),
            ("appeal_prompt", "Appeal Prompt", appeal_prompt_page),
            ("later_treatment_prompt", "Subsequent Treatment Prompt", later_treatment_prompt_page),
        ]
        first_row: Gtk.ListBoxRow | None = None
        for key, title, page in pages:
            row = Gtk.ListBoxRow()
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(12)
            row_box.set_margin_end(12)
            label = Gtk.Label(label=title, xalign=0)
            row_box.append(label)
            row.set_child(row_box)
            page_list.append(row)
            self._settings_page_keys[row] = key
            if first_row is None:
                first_row = row
            settings_stack.add_named(page, key)

        if first_row is not None:
            settings_stack.set_visible_child_name(self._settings_page_keys[first_row])

            def _select_first_row() -> bool:
                if first_row.get_parent() is page_list:
                    page_list.select_row(first_row)
                return False

            GLib.idle_add(_select_first_row)

        split.set_start_child(page_list_scroller)
        split.set_end_child(settings_stack)
        root.append(split)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        buttons.set_halign(Gtk.Align.END)
        save_button = Gtk.Button(label="Save Settings")
        save_button.connect("clicked", self._on_save_clicked)
        buttons.append(save_button)
        root.append(buttons)

        self.status_label = Gtk.Label(label="", xalign=0)
        self.status_label.add_css_class("dim-label")
        root.append(self.status_label)

        toolbar_view.set_content(root)
        self.set_content(toolbar_view)

    def _build_prompt_settings_page(
        self,
        title: str,
        label: str,
        text: str,
        xhigh_active: bool,
    ) -> tuple[Gtk.ScrolledWindow, Gtk.TextBuffer, Gtk.Switch]:
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page_box.set_margin_top(12)
        page_box.set_margin_bottom(12)
        page_box.set_margin_start(12)
        page_box.set_margin_end(12)
        page_box.set_vexpand(True)

        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("title-3")
        page_box.append(title_label)

        prompt_group = Adw.PreferencesGroup()
        prompt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        prompt_box.set_vexpand(True)
        prompt_box.set_margin_top(8)
        prompt_box.set_margin_bottom(8)
        prompt_box.set_margin_start(8)
        prompt_box.set_margin_end(8)
        reasoning_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reasoning_label = Gtk.Label(label="Use xhigh reasoning", xalign=0)
        reasoning_label.set_hexpand(True)
        reasoning_row.append(reasoning_label)
        reasoning_switch = Gtk.Switch()
        reasoning_switch.set_valign(Gtk.Align.CENTER)
        reasoning_switch.set_active(bool(xhigh_active))
        reasoning_row.append(reasoning_switch)
        prompt_box.append(reasoning_row)
        prompt_label = Gtk.Label(label=label, xalign=0)
        prompt_label.add_css_class("dim-label")
        prompt_box.append(prompt_label)
        prompt_scroller, buffer = self._build_prompt_editor(text)
        prompt_box.append(prompt_scroller)
        prompt_group.add(prompt_box)
        page_box.append(prompt_group)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_child(page_box)
        return scrolled, buffer, reasoning_switch

    def _on_settings_page_row_selected(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if row is None or self._settings_stack is None:
            return
        key = self._settings_page_keys.get(row)
        if key:
            self._settings_stack.set_visible_child_name(key)

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

    def _text_buffer_text(self, buffer: Gtk.TextBuffer) -> str:
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        return buffer.get_text(start, end, True).strip()

    def _appeal_issue_data(self) -> tuple[list[str], list[str]]:
        raw_issues = [self._text_buffer_text(buffer) for buffer in self.appeal_issue_buffers]
        raw_labels = [entry.get_text() for entry in self.appeal_issue_label_entries]
        issues: list[str] = []
        labels: list[str] = []
        seen: set[str] = set()
        for index, raw_issue in enumerate(raw_issues):
            issue = raw_issue.strip()
            key = issue.casefold()
            if not issue or key in seen:
                continue
            issues.append(issue)
            labels.append(raw_labels[index].strip() if index < len(raw_labels) else "")
            seen.add(key)
        if not issues:
            issues = list(DEFAULT_APPEAL_ISSUE_PRESETS)
            labels = normalize_appeal_issue_labels(None, issues)
        return issues, normalize_appeal_issue_labels(labels, issues)

    def _reload_appeal_issue_editors(
        self,
        issues: list[str],
        labels: list[str] | None = None,
    ) -> None:
        while True:
            child = self.appeal_issue_list_box.get_first_child()
            if child is None:
                break
            self.appeal_issue_list_box.remove(child)
        self.appeal_issue_buffers = []
        self.appeal_issue_label_entries = []
        normalized_issues = normalize_appeal_issue_presets(issues)
        normalized_labels = normalize_appeal_issue_labels(labels, normalized_issues)
        for index, issue in enumerate(normalized_issues):
            self._append_appeal_issue_editor(index, issue, normalized_labels[index])

    def _append_appeal_issue_editor(self, index: int, issue: str, label: str) -> None:
        frame = Gtk.Frame()
        frame.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        label_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label_label = Gtk.Label(label="Short label", xalign=0)
        label_label.add_css_class("dim-label")
        label_label.set_hexpand(True)
        label_header.append(label_label)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic")
        delete_button.add_css_class("flat")
        delete_button.set_tooltip_text("Delete argument")
        delete_button.connect("clicked", self._on_delete_appeal_issue, index)
        label_header.append(delete_button)
        box.append(label_header)

        label_entry = Gtk.Entry()
        label_entry.set_text(label)
        label_entry.set_placeholder_text("Menu label")
        label_entry.set_hexpand(True)
        self.appeal_issue_label_entries.append(label_entry)
        box.append(label_entry)

        argument_label = Gtk.Label(label="Argument", xalign=0)
        argument_label.add_css_class("dim-label")
        box.append(argument_label)

        buffer = Gtk.TextBuffer()
        buffer.set_text(issue)
        self.appeal_issue_buffers.append(buffer)
        view = Gtk.TextView(buffer=buffer)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(8)
        view.set_right_margin(8)
        view.set_top_margin(8)
        view.set_bottom_margin(8)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(96)
        scroller.set_child(view)
        box.append(scroller)

        frame.set_child(box)
        self.appeal_issue_list_box.append(frame)

    def _refresh_appeal_fact_pattern_entry(self) -> None:
        if self.parent_window._appeal_fact_pattern_path_override is not None:
            self.appeal_fact_pattern_entry.set_text(
                str(self.parent_window._appeal_fact_pattern_path_override)
            )
            return
        try:
            path = current_case_socf_odt()
        except CurrentCaseError as exc:
            self.appeal_fact_pattern_entry.set_text("")
            self.appeal_fact_pattern_entry.set_placeholder_text(str(exc))
            return
        self.appeal_fact_pattern_entry.set_text(str(path))
        self.appeal_fact_pattern_entry.set_placeholder_text("Current case SOCF ODT")

    def _on_choose_appeal_fact_pattern(self, _button: Gtk.Button) -> None:
        file_dialog_cls = getattr(Gtk, "FileDialog", None)
        if file_dialog_cls is None:
            self.status_label.set_text("File chooser is unavailable in this GTK version.")
            return
        dialog = file_dialog_cls(title="Choose fact pattern")
        dialog.open(self, None, self._on_appeal_fact_pattern_chosen)

    def _on_appeal_fact_pattern_chosen(self, dialog: Any, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is None:
            return
        path = file.get_path()
        if path:
            self.parent_window._appeal_fact_pattern_path_override = Path(path)
            self.appeal_fact_pattern_entry.set_text(path)

    def _on_reset_appeal_fact_pattern(self, _button: Gtk.Button) -> None:
        self.parent_window._appeal_fact_pattern_path_override = None
        self._refresh_appeal_fact_pattern_entry()

    def _on_add_appeal_issue(self, _button: Gtk.Button) -> None:
        issues, labels = self._appeal_issue_data()
        issues.append("New appellate argument.")
        labels.append("")
        self._reload_appeal_issue_editors(issues, labels)

    def _on_delete_appeal_issue(self, _button: Gtk.Button, index: int) -> None:
        issues, labels = self._appeal_issue_data()
        if 0 <= index < len(issues):
            del issues[index]
            del labels[index]
        if issues:
            self._reload_appeal_issue_editors(issues, labels)
        else:
            self._reload_appeal_issue_editors(list(DEFAULT_APPEAL_ISSUE_PRESETS))

    def _on_save_clicked(self, _button: Gtk.Button) -> None:
        token = self.token_row.get_text().strip()
        concordance_path = self.concordance_row.get_text().strip()
        selected_font_family_index = int(self.reader_font_family_row.get_selected())
        if 0 <= selected_font_family_index < len(self.reader_font_family_values):
            reader_font_family = self.reader_font_family_values[selected_font_family_index]
        else:
            reader_font_family = load_config().reader_font_family
        selected_bare_statute_index = int(self.bare_statute_law_code_row.get_selected())
        if 0 <= selected_bare_statute_index < len(self.bare_statute_law_code_values):
            bare_statute_law_code = self.bare_statute_law_code_values[selected_bare_statute_index]
        else:
            bare_statute_law_code = load_config().default_bare_statute_law_code
        selected_agent_permission_mode_index = int(self.agent_permission_mode_row.get_selected())
        if 0 <= selected_agent_permission_mode_index < len(self.agent_permission_mode_values):
            agent_permission_mode = self.agent_permission_mode_values[
                selected_agent_permission_mode_index
            ]
        else:
            agent_permission_mode = AGENT_PERMISSION_MODE_SANDBOXED
        appeal_issue_presets, appeal_issue_labels = self._appeal_issue_data()
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
                appeal_issue_agent_prompt_template=(
                    self._prompt_text(self.appeal_issue_agent_prompt_buffer).strip()
                    or DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
                ),
                later_treatment_agent_prompt_template=(
                    self._prompt_text(self.later_treatment_agent_prompt_buffer).strip()
                    or DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
                ),
                general_agent_xhigh_reasoning=bool(self.general_agent_xhigh_switch.get_active()),
                case_agent_xhigh_reasoning=bool(self.case_agent_xhigh_switch.get_active()),
                appeal_issue_xhigh_reasoning=bool(self.appeal_issue_xhigh_switch.get_active()),
                later_treatment_xhigh_reasoning=bool(self.later_treatment_xhigh_switch.get_active()),
                appeal_issue_presets=appeal_issue_presets,
                appeal_issue_labels=appeal_issue_labels,
                reader_font_size_pt=coerce_reader_font_size(
                    int(round(self.reader_font_size_row.get_value()))
                ),
                reader_font_family=normalize_reader_font_family(reader_font_family),
                default_bare_statute_law_code=normalize_bare_statute_law_code(
                    bare_statute_law_code
                ),
                agent_permission_mode=normalize_agent_permission_mode(agent_permission_mode),
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
        self._statutes: list[dict[str, Any]] = []
        self._selected_statute: dict[str, Any] | None = None
        self._rules: list[dict[str, Any]] = []
        self._selected_rule: dict[str, Any] | None = None
        self._agent_answers: list[dict[str, Any]] = []
        self._selected_agent_answer: dict[str, Any] | None = None
        self._suppress_sidebar_selection_lookup = False
        self._current_case_name = ""
        self._current_case_socf_path: Path | None = None
        self._current_case_error = ""
        self._current_case_context_list: Gtk.ListBox | None = None
        self._current_case_context_row: Gtk.ListBoxRow | None = None
        self._current_case_context_title: Gtk.Label | None = None
        self._current_case_context_subtitle: Gtk.Label | None = None
        self._current_case_context_check: Gtk.CheckButton | None = None
        self._current_case_context_toggle_guard = False
        self._agent_terminal: Any | None = None
        self._agent_pid: int | None = None
        self._agent_session_widget: Gtk.Widget | None = None
        self._agent_answer_scroller: Gtk.ScrolledWindow | None = None
        self._agent_answer_buffer: Gtk.TextBuffer | None = None
        self._agent_answer_view: Gtk.TextView | None = None
        self._agent_answer_button: Gtk.ToggleButton | None = None
        self._agent_session_button: Gtk.ToggleButton | None = None
        self._agent_save_answer_button: Gtk.Button | None = None
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
        self._agent_statute_link_lookup: dict[Gtk.TextTag, StatuteLink] = {}
        self._agent_rule_link_lookup: dict[Gtk.TextTag, RuleLink] = {}
        self._agent_external_url_link_lookup: dict[Gtk.TextTag, AgentExternalUrlLink] = {}
        self._agent_search_link_lookup: dict[Gtk.TextTag, CourtListenerSearchResult] = {}
        self._agent_search_next_link_tags: set[Gtk.TextTag] = set()
        self._agent_search_action_link_lookup: dict[Gtk.TextTag, str] = {}
        self._agent_search_highlight_tags: list[Gtk.TextTag] = []
        self._agent_motion_controller: Gtk.EventControllerMotion | None = None
        self._agent_click_gesture: Gtk.GestureClick | None = None
        self._agent_link_press: LinkPressState | None = None
        self._reader_text = ""
        self._reader_position_key: tuple[str, str] | None = None
        self._reader_page_markers: list[PageMarker] = []
        self._reader_highlight_tag: Gtk.TextTag | None = None
        self._reader_saved_highlight_tag: Gtk.TextTag | None = None
        self._reader_find_tag: Gtk.TextTag | None = None
        self._reader_find_current_tag: Gtk.TextTag | None = None
        self._reader_find_bar: Gtk.Widget | None = None
        self._reader_find_entry: Gtk.Entry | None = None
        self._reader_find_count_label: Gtk.Label | None = None
        self._reader_find_matches: list[tuple[int, int]] = []
        self._reader_find_index = -1
        self._reader_busy_box: Gtk.Widget | None = None
        self._reader_busy_spinner: Gtk.Spinner | None = None
        self._reader_busy_label: Gtk.Label | None = None
        self._reader_citation_italic_tag: Gtk.TextTag | None = None
        self._reader_citation_link_tags: list[Gtk.TextTag] = []
        self._reader_citation_link_lookup: dict[Gtk.TextTag, CitedCaseLink] = {}
        self._reader_statute_link_lookup: dict[Gtk.TextTag, StatuteLink] = {}
        self._reader_rule_link_lookup: dict[Gtk.TextTag, RuleLink] = {}
        self._reader_citation_motion_controller: Gtk.EventControllerMotion | None = None
        self._reader_citation_click_gesture: Gtk.GestureClick | None = None
        self._reader_link_press: LinkPressState | None = None
        self._reader_header_citation: FormattedCitation | None = None
        self._reader_display_cluster: dict[str, Any] | None = None
        self._active_research_set_id: int | None = None
        self._active_research_set_name = ""
        self._active_research_set_dirty = False
        self._research_set_label: Gtk.Label | None = None
        self._research_sets_menu_button: Gtk.MenuButton | None = None
        self.reader_selection_pinpoint_button: Gtk.Button | None = None
        self.reader_subsequent_treatment_button: Gtk.Button | None = None
        self.reader_helper_case_button: Gtk.Button | None = None
        self._reader_highlight_button: Gtk.Button | None = None
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._case_load_generation = 0
        self._research_cache_generation = 0
        self._last_lookup_text = ""
        self._external_lookup_window: Gtk.Window | None = None
        self._external_lookup_query: str = ""
        self._external_lookup_auto_find_button: Gtk.Button | None = None
        self._external_lookup_source_entry: Gtk.Entry | None = None
        self._external_lookup_auto_finding = False
        self._external_lookup_auto_query = ""
        self._external_lookup_auto_fallback_mode = SCHOLAR_FALLBACK_MANUAL_WINDOW
        self._external_lookup_auto_import = False
        self._external_lookup_auto_cache_generation: int | None = None
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._pending_quote_target: QuoteTarget | None = None
        self._settings_window: SettingsWindow | None = None
        self._appeal_fact_pattern_path_override: Path | None = None
        self._appeal_issue_menu_button: Gtk.MenuButton | None = None
        self._dbus_commands_window: DbusCommandsWindow | None = None
        self._cli_commands_window: CliCommandsWindow | None = None
        self._shortcuts_window: Gtk.ShortcutsWindow | None = None
        self._case_suggestions: list[CaseSuggestion] = []
        self._case_suggestions_loaded = False
        self._case_completion_matches: list[CaseSuggestion] = []
        self._case_completion_selected_index = 0
        self._case_completion_results_scroller: Gtk.ScrolledWindow | None = None
        self._case_completion_list_box: Gtk.ListBox | None = None
        self._case_completion_changing = False
        self._case_completion_click_gesture: Gtk.GestureClick | None = None
        self._case_suggestion_refresh_pending = False
        self._css_provider: Gtk.CssProvider | None = None
        self._status_label: Gtk.Label | None = None

        self.set_title(APP_NAME)
        self.set_default_size(1260, 860)
        self._install_css()
        self._install_actions()
        self.set_content(self._build_ui())
        self.connect("close-request", self._on_window_close_request)
        self.connect("notify::is-active", self._on_window_active_changed)
        self._restore_active_research_set()
        self._load_cached_cases()
        self.add_tick_callback(self._on_window_tick)

    def _install_actions(self) -> None:
        settings = Gio.SimpleAction.new("settings", None)
        settings.connect("activate", self._on_open_settings)
        self.add_action(settings)
        clear_cache = Gio.SimpleAction.new("clear_cache", None)
        clear_cache.connect("activate", self._on_clear_cache)
        self.add_action(clear_cache)
        save_research_set = Gio.SimpleAction.new("save_research_set", None)
        save_research_set.connect("activate", self._on_save_research_set)
        self.add_action(save_research_set)
        open_research_set = Gio.SimpleAction.new("open_research_set", None)
        open_research_set.connect("activate", self._on_open_research_set)
        self.add_action(open_research_set)
        show_dbus_commands = Gio.SimpleAction.new("show_dbus_commands", None)
        show_dbus_commands.connect("activate", self._on_show_dbus_commands)
        self.add_action(show_dbus_commands)
        show_cli_commands = Gio.SimpleAction.new("show_cli_commands", None)
        show_cli_commands.connect("activate", self._on_show_cli_commands)
        self.add_action(show_cli_commands)
        assess_appeal_issue = Gio.SimpleAction.new("assess_appeal_issue", None)
        assess_appeal_issue.connect("activate", self._on_assess_appeal_issue)
        self.add_action(assess_appeal_issue)
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
              background-color: #fafafa;
              border-bottom: 1px solid #e6e6e6;
              padding: 6px 12px 8px 12px;
            }}
            label.case-reader-fixed-header {{
              color: {READER_FG};
              background-color: #fafafa;
              font-family: {reader_font_css(config.reader_font_family)};
              font-size: {config.reader_font_size_pt}pt;
              font-weight: bold;
            }}
            button.case-reader-header-action-button {{
              color: {READER_FG};
              background-color: transparent;
              background-image: none;
              border: none;
              box-shadow: none;
              padding: 4px;
              min-width: 28px;
              min-height: 28px;
            }}
            button.case-reader-header-action-button:hover {{
              background-color: #eeeeee;
            }}
            button.case-reader-header-action-button:active {{
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
            list.research-set-menu {{
              background-color: transparent;
            }}
            list.research-set-menu row {{
              background-color: transparent;
              border-radius: 6px;
              margin: 0;
            }}
            list.research-set-menu row > box {{
              padding: 0;
            }}
            list.research-set-menu row:hover {{
              background-color: transparent;
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
            button.cache-row-remove-button {{
              background-color: transparent;
              color: alpha(@window_fg_color, 0.14);
            }}
            list.case-list row.case-cache-row:hover button.cache-row-remove-button,
            list.case-list row.case-cache-row:selected button.cache-row-remove-button {{
              color: alpha(@window_fg_color, 0.52);
            }}
            button.cache-row-remove-button:hover {{
              background-color: alpha(@window_fg_color, 0.08);
              color: alpha(@window_fg_color, 0.78);
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
            box.reader-busy-chip {{
              background-color: alpha(@window_bg_color, 0.96);
              border: 1px solid alpha(@window_fg_color, 0.14);
              border-radius: 8px;
              padding: 8px 12px;
              box-shadow: 0 2px 8px alpha(@window_fg_color, 0.16);
            }}
            label.reader-busy-label {{
              font-size: 0.9rem;
              color: alpha(@window_fg_color, 0.72);
            }}
            label.app-status-strip {{
              min-height: 18px;
              font-size: 0.88rem;
              color: alpha(@window_fg_color, 0.52);
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

        status_label = Gtk.Label(label="", xalign=0)
        status_label.add_css_class("app-status-strip")
        status_label.set_ellipsize(Pango.EllipsizeMode.END)
        status_label.set_single_line_mode(True)
        status_label.set_hexpand(True)
        root.append(status_label)
        self._status_label = status_label

        main = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        main.set_hexpand(True)
        main.set_vexpand(True)
        main.append(self._build_sidebar())
        main.append(self._build_right_side())
        root.append(main)

        toolbar_view.set_content(root)
        return toolbar_view

    def _build_menu_button(self) -> Gtk.MenuButton:
        menu = Gio.Menu()
        menu.append("Keyboard Shortcuts", "win.show_shortcuts")
        menu.append("CLI Commands", "win.show_cli_commands")
        menu.append("D-Bus Commands", "win.show_dbus_commands")
        menu.append("Settings", "win.settings")
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

        box.append(self._build_current_case_context())
        box.append(self._build_research_cache_header())

        self.case_list = Gtk.ListBox()
        self.case_list.add_css_class("case-list")
        self.case_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.case_list.set_sort_func(self._sort_research_cache_rows)
        self.case_list.connect("row-selected", self._on_case_selected)

        scroller = Gtk.ScrolledWindow()
        scroller.add_css_class("case-list-frame")
        scroller.set_overflow(Gtk.Overflow.HIDDEN)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.case_list)
        scroller.set_vexpand(True)
        box.append(scroller)
        return box

    def _build_current_case_context(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_hexpand(True)

        heading = Gtk.Label(label="Current Case", xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        list_box = Gtk.ListBox()
        list_box.add_css_class("case-list")
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.connect("row-activated", self._on_current_case_context_activated)

        row = Gtk.ListBoxRow()
        row.set_selectable(True)
        row.set_activatable(True)
        row.add_css_class("case-cache-row")

        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row_box.set_margin_top(8)
        row_box.set_margin_bottom(8)
        row_box.set_margin_start(8)
        row_box.set_margin_end(8)

        icon = Gtk.Image(icon_name="text-x-generic-symbolic")
        icon.set_valign(Gtk.Align.START)
        row_box.append(icon)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_hexpand(True)
        title = Gtk.Label(label="Current Case", xalign=0)
        title.set_wrap(True)
        text_box.append(title)
        subtitle = Gtk.Label(label="Statement of Case and Facts", xalign=0)
        subtitle.add_css_class("dim-label")
        subtitle.set_wrap(True)
        text_box.append(subtitle)
        row_box.append(text_box)

        check = Gtk.CheckButton()
        check.add_css_class("neutral-agent-check")
        check.set_valign(Gtk.Align.START)
        check.set_tooltip_text(
            "Include this SOCF in Law and Cache agent questions; appeal assessments always include their fact pattern"
        )
        check.connect("toggled", self._on_current_case_context_toggled)
        row_box.append(check)

        row.set_child(row_box)
        list_box.append(row)
        box.append(list_box)

        self._current_case_context_list = list_box
        self._current_case_context_row = row
        self._current_case_context_title = title
        self._current_case_context_subtitle = subtitle
        self._current_case_context_check = check
        self._refresh_current_case_context()
        return box

    def _build_research_cache_header(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.set_hexpand(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_hexpand(True)

        heading = Gtk.Label(label="Research Cache", xalign=0)
        heading.add_css_class("heading")
        heading.set_hexpand(True)
        header.append(heading)

        save_button = Gtk.Button(icon_name="document-save-symbolic")
        save_button.add_css_class("flat")
        save_button.add_css_class("case-row-icon-button")
        save_button.set_action_name("win.save_research_set")
        save_button.set_tooltip_text("Save Research Set")
        save_button.set_valign(Gtk.Align.CENTER)
        header.append(save_button)

        open_button = Gtk.MenuButton(icon_name="folder-open-symbolic")
        open_button.add_css_class("flat")
        open_button.add_css_class("case-row-icon-button")
        open_button.set_tooltip_text("Open Research Set")
        open_button.set_valign(Gtk.Align.CENTER)
        self._research_sets_menu_button = open_button
        OpenLawLensWindow._refresh_research_sets_menu(self)
        header.append(open_button)

        clear_button = Gtk.Button(icon_name="edit-clear-symbolic")
        clear_button.add_css_class("flat")
        clear_button.add_css_class("case-row-icon-button")
        clear_button.set_action_name("win.clear_cache")
        clear_button.set_tooltip_text("Clear Research Cache")
        clear_button.set_valign(Gtk.Align.CENTER)
        header.append(clear_button)

        self._research_set_label = Gtk.Label(label="", xalign=0)
        self._research_set_label.add_css_class("dim-label")
        self._research_set_label.set_visible(False)
        box.append(header)
        box.append(self._research_set_label)
        return box

    def _refresh_research_sets_menu(self) -> None:
        button = getattr(self, "_research_sets_menu_button", None)
        if button is None:
            return
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.set_margin_top(3)
        box.set_margin_bottom(3)
        box.set_margin_start(3)
        box.set_margin_end(3)

        client = getattr(self, "client", None)
        if client is None:
            research_sets: list[ResearchSet] = []
        else:
            research_sets = client.library.list_research_sets()
        if not research_sets:
            empty = Gtk.Label(label="No saved research sets.", xalign=0)
            empty.add_css_class("dim-label")
            empty.set_margin_top(6)
            empty.set_margin_bottom(6)
            empty.set_margin_start(6)
            empty.set_margin_end(6)
            box.append(empty)
        else:
            list_box = Gtk.ListBox()
            list_box.add_css_class("research-set-menu")
            list_box.set_selection_mode(Gtk.SelectionMode.NONE)
            for research_set in research_sets:
                list_box.append(OpenLawLensWindow._build_research_set_row(self, research_set, popover))
            box.append(list_box)

        popover.set_child(box)
        button.set_popover(popover)

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
        self._case_suggestions = self._load_case_suggestion_index()
        self._case_suggestions_loaded = True

    def _load_case_suggestion_index(self) -> list[CaseSuggestion]:
        configured_path = concordance_file_path()
        concordance_suggestions: list[CaseSuggestion] = []
        if configured_path is not None:
            concordance_suggestions = [
                *load_concordance_case_suggestions(configured_path),
                *load_concordance_statute_suggestions(configured_path),
                *load_concordance_rule_suggestions(configured_path),
            ]
        library_suggestions = case_suggestions_from_library(self.client.library)
        return merge_case_suggestions(
            concordance_suggestions,
            library_suggestions,
        )

    def _refresh_case_suggestion_index_async(self, *, force: bool = False) -> None:
        if self._case_suggestion_refresh_pending:
            return
        if self._case_suggestions_loaded and not force:
            return
        self._case_suggestion_refresh_pending = True
        self._start_background_worker(
            self._load_case_suggestion_index,
            on_success=self._finish_case_suggestion_index_refresh,
            on_error=lambda _exc: self._finish_case_suggestion_index_refresh(self._case_suggestions),
        )

    def _case_suggestion_index_worker(self) -> None:
        try:
            suggestions = self._load_case_suggestion_index()
        except Exception:
            GLib.idle_add(self._finish_case_suggestion_index_refresh, self._case_suggestions)
            return
        GLib.idle_add(self._finish_case_suggestion_index_refresh, suggestions)

    def _finish_case_suggestion_index_refresh(self, suggestions: list[CaseSuggestion]) -> bool:
        self._case_suggestions = suggestions
        self._case_suggestions_loaded = True
        self._case_suggestion_refresh_pending = False
        if self.citation_entry.has_focus():
            query = self.citation_entry.get_text().strip()
            self._show_case_completion(matching_case_suggestions(query, self._case_suggestions))
        return False

    def _on_citation_entry_changed(self, _entry: Gtk.Entry) -> None:
        if self._case_completion_changing:
            return
        if not self._case_suggestions_loaded:
            self._refresh_case_suggestion_index_async()
            return
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
        if suggestion.authority_type == "statute":
            self._start_statute_lookup(suggestion.lookup_text)
            return
        if suggestion.authority_type == "rule":
            self._start_rule_lookup(suggestion.lookup_text)
            return
        if suggestion.cluster_id:
            self._set_status(f"Opening {suggestion.lookup_text} from Library...")
            self._set_reader_busy(True, "Opening from Library...")
            cache_generation = self._research_cache_generation
            thread = threading.Thread(
                target=self._library_case_suggestion_worker,
                args=(suggestion, cache_generation),
                daemon=True,
            )
            thread.start()
            return
        self._start_lookup(suggestion.lookup_text)

    def _library_case_suggestion_worker(
        self,
        suggestion: CaseSuggestion,
        cache_generation: int,
    ) -> None:
        try:
            cluster = self.client.library.read_cluster(suggestion.cluster_id)
            if cluster is None:
                GLib.idle_add(self._start_lookup_from_idle, suggestion.lookup_text)
                return
            result = LibrarySuggestionOpenResult(
                lookup_text=suggestion.lookup_text,
                cluster=cluster,
                cache_generation=cache_generation,
            )
            GLib.idle_add(self._finish_library_case_suggestion_open, result)
        except Exception as exc:
            GLib.idle_add(self._apply_error, f"Unable to open {suggestion.lookup_text}: {exc}")

    def _start_lookup_from_idle(self, lookup_text: str) -> bool:
        self._start_lookup(lookup_text)
        return False

    def _finish_library_case_suggestion_open(self, result: LibrarySuggestionOpenResult) -> bool:
        if result.cache_generation != self._research_cache_generation:
            return False
        cluster_id = self.client.cache.upsert_cluster(result.cluster)
        if not cluster_id:
            self._start_lookup(result.lookup_text)
            return False
        self._set_sidebar_clusters(self.client.cached_clusters(), select_cluster_id=cluster_id)
        self._refresh_case_suggestion_index_async(force=True)
        if self.case_list.get_selected_row() is None:
            self._set_reader_busy(False)
            self._set_status(f"Library: cached {result.lookup_text}, but could not select the case.")
        else:
            self._set_status(f"Library: opened {result.lookup_text}.")
        return False

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
        self.reader_buffer.connect("mark-set", self._on_reader_selection_changed)
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
        self._reader_saved_highlight_tag = self.reader_buffer.create_tag(
            "reader-saved-highlight",
            background="#fff0a6",
            foreground="#1f1f1f",
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

        self.reader_header_leading_spacer = Gtk.Box()
        self.reader_header_leading_spacer.set_can_target(False)
        self.reader_header_box.append(self.reader_header_leading_spacer)

        self.reader_header_label = Gtk.Label(label="", xalign=0.5)
        self.reader_header_label.add_css_class("case-reader-fixed-header")
        self.reader_header_label.set_wrap(True)
        self.reader_header_label.set_justify(Gtk.Justification.CENTER)
        self.reader_header_label.set_selectable(True)
        self.reader_header_label.set_hexpand(True)
        self.reader_header_box.append(self.reader_header_label)

        self.reader_header_action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.reader_header_action_box.set_halign(Gtk.Align.END)
        self.reader_header_action_box.set_valign(Gtk.Align.CENTER)
        self.reader_header_box.append(self.reader_header_action_box)

        self.reader_header_size_group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        self.reader_header_size_group.add_widget(self.reader_header_leading_spacer)
        self.reader_header_size_group.add_widget(self.reader_header_action_box)

        self.reader_header_copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
        self.reader_header_copy_button.add_css_class("case-reader-header-action-button")
        self.reader_header_copy_button.set_tooltip_text("Copy citation")
        self.reader_header_copy_button.set_valign(Gtk.Align.CENTER)
        self.reader_header_copy_button.connect("clicked", self._on_copy_reader_citation_clicked)
        self.reader_header_action_box.append(self.reader_header_copy_button)

        self.reader_selection_pinpoint_button = Gtk.Button(icon_name="insert-text-symbolic")
        self.reader_selection_pinpoint_button.add_css_class("case-reader-header-action-button")
        self.reader_selection_pinpoint_button.set_tooltip_text(
            "Copy selected text with pinpoint citation"
        )
        self.reader_selection_pinpoint_button.set_valign(Gtk.Align.CENTER)
        self.reader_selection_pinpoint_button.set_sensitive(False)
        self.reader_selection_pinpoint_button.connect(
            "clicked",
            self._on_copy_reader_selection_pinpoint_clicked,
        )
        self.reader_header_action_box.append(self.reader_selection_pinpoint_button)

        self.reader_subsequent_treatment_button = Gtk.Button(icon_name="go-next-symbolic")
        self.reader_subsequent_treatment_button.add_css_class("case-reader-header-action-button")
        self.reader_subsequent_treatment_button.set_tooltip_text("Analyze subsequent treatment")
        self.reader_subsequent_treatment_button.set_valign(Gtk.Align.CENTER)
        self.reader_subsequent_treatment_button.set_visible(False)
        self.reader_subsequent_treatment_button.connect(
            "clicked",
            self._on_later_treatment_clicked,
        )
        self.reader_header_action_box.append(self.reader_subsequent_treatment_button)

        self.reader_helper_case_button = Gtk.Button(icon_name="go-jump-symbolic")
        self.reader_helper_case_button.add_css_class("case-reader-header-action-button")
        self.reader_helper_case_button.set_tooltip_text("Find helper citing case")
        self.reader_helper_case_button.set_valign(Gtk.Align.CENTER)
        self.reader_helper_case_button.set_visible(False)
        self.reader_helper_case_button.set_sensitive(False)
        self.reader_helper_case_button.connect(
            "clicked",
            self._on_helper_case_clicked,
        )
        self.reader_header_action_box.append(self.reader_helper_case_button)

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
        reader_overlay.add_overlay(self._build_reader_busy_indicator())
        box.append(reader_overlay)
        self.reader_buffer.set_text("")
        return box

    def _build_reader_busy_indicator(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.add_css_class("reader-busy-chip")
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        box.set_can_target(False)
        box.set_visible(False)

        spinner = Gtk.Spinner()
        spinner.set_size_request(18, 18)
        box.append(spinner)

        label = Gtk.Label(label="Loading...", xalign=0)
        label.add_css_class("reader-busy-label")
        box.append(label)

        self._reader_busy_box = box
        self._reader_busy_spinner = spinner
        self._reader_busy_label = label
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

    def _set_reader_busy(self, busy: bool, text: str = "Loading...") -> None:
        if self._reader_busy_box is None or self._reader_busy_spinner is None:
            return
        if self._reader_busy_label is not None:
            self._reader_busy_label.set_text(text)
        self._reader_busy_box.set_visible(busy)
        if busy:
            self._reader_busy_spinner.start()
        else:
            self._reader_busy_spinner.stop()

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
        self._agent_save_answer_button = Gtk.Button(icon_name="document-save-symbolic")
        self._agent_save_answer_button.add_css_class("flat")
        self._agent_save_answer_button.set_tooltip_text("Save final answer to Research Cache")
        self._agent_save_answer_button.set_sensitive(False)
        self._agent_save_answer_button.connect("clicked", self._on_save_agent_answer_clicked)
        subview_strip.append(self._agent_save_answer_button)
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
        mode_strip.append(self._build_agent_mode_button(AGENT_MODE_GENERAL))
        mode_strip.append(self._build_agent_mode_button(AGENT_MODE_CASE))
        row.append(mode_strip)

        self.agent_question_entry = Gtk.Entry()
        self.agent_question_entry.set_hexpand(True)
        self.agent_question_entry.set_placeholder_text("Ask a California law question")
        self.agent_question_entry.connect("activate", self._on_agent_launch)
        row.append(self.agent_question_entry)

        appeal_button = self._build_appeal_issue_menu_button()
        row.append(appeal_button)

        row.append(self._build_reader_highlight_button())

        collapse_button = Gtk.Button(icon_name="go-up-symbolic")
        collapse_button.add_css_class("flat")
        collapse_button.set_tooltip_text("Hide agent output")
        collapse_button.set_visible(False)
        collapse_button.connect("clicked", self._on_agent_output_toggle_clicked)
        row.append(collapse_button)
        self._agent_output_toggle_button = collapse_button

        self._set_agent_mode(AGENT_MODE_GENERAL)
        return row

    def _build_appeal_issue_menu_button(self) -> Gtk.MenuButton:
        button = Gtk.MenuButton(icon_name="cafe-symbolic")
        button.add_css_class("flat")
        button.set_tooltip_text("Assess appeal argument")
        self._appeal_issue_menu_button = button
        self._refresh_appeal_issue_menu()
        return button

    def _build_reader_highlight_button(self) -> Gtk.Button:
        button = Gtk.Button(icon_name="highlighter-symbolic")
        button.add_css_class("flat")
        button.set_tooltip_text("Highlight selected text")
        button.set_sensitive(False)
        button.connect("clicked", self._on_toggle_reader_highlight_clicked)
        self._reader_highlight_button = button
        return button

    def _refresh_appeal_issue_menu(self) -> None:
        if self._appeal_issue_menu_button is None:
            return
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        assess_custom_button = Gtk.Button(label="Assess custom argument...")
        OpenLawLensWindow._style_appeal_issue_menu_button(assess_custom_button)
        assess_custom_button.connect("clicked", self._on_custom_appeal_issue_clicked, popover)
        box.append(assess_custom_button)
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.append(separator)
        config = load_config()
        issues = config.appeal_issue_presets
        labels = normalize_appeal_issue_labels(config.appeal_issue_labels, issues)
        for index, issue in enumerate(issues):
            label = appeal_issue_menu_label(issue, labels[index])
            assess_button = Gtk.Button(label=label)
            OpenLawLensWindow._style_appeal_issue_menu_button(assess_button)
            assess_button.connect(
                "clicked",
                self._on_appeal_issue_menu_item_clicked,
                index,
                popover,
            )
            box.append(assess_button)
        settings_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        box.append(settings_separator)
        settings_button = Gtk.Button(label="Edit appeal arguments...")
        OpenLawLensWindow._style_appeal_issue_menu_button(settings_button)
        settings_button.connect("clicked", self._on_appeal_issue_settings_clicked, popover)
        box.append(settings_button)
        popover.set_child(box)
        self._appeal_issue_menu_button.set_popover(popover)

    @staticmethod
    def _style_appeal_issue_menu_button(button: Gtk.Button) -> None:
        button.add_css_class("flat")
        button.set_halign(Gtk.Align.FILL)
        button.set_hexpand(True)
        child = button.get_child()
        if isinstance(child, Gtk.Label):
            child.set_xalign(0)

    def _build_agent_mode_button(self, mode: str) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton()
        button.add_css_class("flat")
        button.add_css_class("no-bold")
        button.add_css_class("focus-pill-segment")
        icon = Gtk.Image(icon_name=AGENT_MODE_ICONS[mode])
        icon.set_pixel_size(16)
        button.set_child(icon)
        tooltip = (
            "Ask from CourtListener legal authority"
            if mode == AGENT_MODE_GENERAL
            else "Ask from marked Research Cache authorities"
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
        if self._status_label is None:
            return
        self._status_label.set_text(text)

    def _start_background_worker(
        self,
        worker: Callable[[], Any],
        *,
        on_success: Callable[[Any], Any] | None = None,
        on_error: Callable[[BaseException], Any] | None = None,
        handled_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> threading.Thread:
        thread = threading.Thread(
            target=self._background_worker,
            args=(worker, on_success, on_error, handled_exceptions),
            daemon=True,
        )
        thread.start()
        return thread

    def _background_worker(
        self,
        worker: Callable[[], Any],
        on_success: Callable[[Any], Any] | None,
        on_error: Callable[[BaseException], Any] | None,
        handled_exceptions: tuple[type[BaseException], ...],
    ) -> None:
        try:
            result = worker()
        except handled_exceptions as exc:
            callback = on_error or (lambda error: self._apply_error(str(error)))
            GLib.idle_add(callback, exc)
            return
        if on_success is not None:
            GLib.idle_add(on_success, result)

    def _on_window_close_request(self, _window: Gtk.Window) -> bool:
        self._capture_current_reader_position()
        return False

    def _on_window_active_changed(self, _window: Gtk.Window, _param: Any) -> None:
        if not self.is_active():
            return
        self._refresh_current_case_context()

    def _refresh_current_case_context(self) -> CurrentCaseSocf | None:
        try:
            resolved = current_case_socf()
        except CurrentCaseError as exc:
            try:
                case_name = read_current_case()
            except CurrentCaseError:
                case_name = ""
            self._current_case_name = case_name
            self._current_case_socf_path = None
            self._current_case_error = str(exc)
            if self._current_case_context_title is not None:
                self._current_case_context_title.set_text(case_name or "Current Case")
            if self._current_case_context_subtitle is not None:
                self._current_case_context_subtitle.set_text("SOCF unavailable")
                self._current_case_context_subtitle.set_tooltip_text(str(exc))
            self._current_case_context_toggle_guard = True
            try:
                if self._current_case_context_check is not None:
                    self._current_case_context_check.set_active(
                        bool(
                            case_name
                            and self.client.cache.is_current_case_context_selected(case_name)
                        )
                    )
                    self._current_case_context_check.set_sensitive(False)
            finally:
                self._current_case_context_toggle_guard = False
            return None

        self._current_case_name = resolved.case_name
        self._current_case_socf_path = resolved.path
        self._current_case_error = ""
        if self._current_case_context_title is not None:
            self._current_case_context_title.set_text(resolved.case_name)
        if self._current_case_context_subtitle is not None:
            self._current_case_context_subtitle.set_text("Statement of Case and Facts")
            self._current_case_context_subtitle.set_tooltip_text(str(resolved.path))
        self._current_case_context_toggle_guard = True
        try:
            if self._current_case_context_check is not None:
                self._current_case_context_check.set_sensitive(True)
                self._current_case_context_check.set_active(
                    self.client.cache.is_current_case_context_selected(resolved.case_name)
                )
        finally:
            self._current_case_context_toggle_guard = False
        return resolved

    def _on_current_case_context_toggled(self, button: Gtk.CheckButton) -> None:
        if self._current_case_context_toggle_guard:
            return
        selected = button.get_active()
        resolved = self._refresh_current_case_context()
        if resolved is None:
            return
        self.client.cache.set_current_case_context_selected(
            resolved.case_name,
            selected,
        )
        self._current_case_context_toggle_guard = True
        try:
            button.set_active(selected)
        finally:
            self._current_case_context_toggle_guard = False
        state = "included in" if selected else "excluded from"
        self._set_status(f"Current-case SOCF will be {state} Law and Cache questions.")

    def _on_current_case_context_activated(
        self,
        _list_box: Gtk.ListBox,
        row: Gtk.ListBoxRow | None,
    ) -> None:
        if row is None:
            return
        self.case_list.unselect_all()
        self._open_current_case_socf()

    def _open_current_case_socf(self) -> None:
        resolved = self._refresh_current_case_context()
        if resolved is None:
            self._set_status(self._current_case_error or "Current-case SOCF is unavailable.")
            return
        self._capture_current_reader_position()
        self._set_reader_position_key("socf", resolved.case_name)
        self._case_load_generation += 1
        generation = self._case_load_generation
        self._selected_cluster = None
        self._selected_statute = None
        self._selected_rule = None
        self._selected_agent_answer = None
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._reader_page_markers = []
        self._clear_reader_citation_links()
        self._set_reader_header(f"{resolved.case_name}\nStatement of Case and Facts")
        self._reader_text = ""
        self.reader_buffer.set_text("")
        self._set_reader_busy(True, "Loading current-case SOCF...")
        self._set_status("Loading current-case SOCF...")
        threading.Thread(
            target=self._current_case_socf_worker,
            args=(resolved, generation),
            daemon=True,
        ).start()

    def _current_case_socf_worker(self, resolved: CurrentCaseSocf, generation: int) -> None:
        try:
            text = extract_fact_pattern_text(resolved.path)
        except (FactPatternError, OSError) as exc:
            GLib.idle_add(self._apply_current_case_socf_error, str(exc), generation)
            return
        GLib.idle_add(self._finish_current_case_socf_load, resolved, text, generation)

    def _finish_current_case_socf_load(
        self,
        resolved: CurrentCaseSocf,
        text: str,
        generation: int,
    ) -> bool:
        if generation != self._case_load_generation:
            return False
        self._set_reader_text(text)
        self._set_status(f"Loaded the current-case SOCF for {resolved.case_name}.")
        return False

    def _apply_current_case_socf_error(self, message: str, generation: int) -> bool:
        if generation != self._case_load_generation:
            return False
        self._set_reader_busy(False)
        self._reader_text = ""
        self.reader_buffer.set_text(message)
        self._set_status(f"Unable to load current-case SOCF: {message}")
        return False

    def _capture_current_reader_position(self) -> None:
        key = self._reader_position_key
        if key is None or not self._reader_text:
            return
        view = getattr(self, "reader_view", None)
        if view is None:
            return
        visible = view.get_visible_rect()
        iter_result = view.get_iter_at_position(int(visible.x), int(visible.y))
        if not isinstance(iter_result, tuple) or len(iter_result) < 2:
            return
        # GTK returns False when the point is in the TextView margin, but the
        # accompanying iterator still identifies the nearest text position.
        iter_ = iter_result[1]
        if iter_ is None:
            return
        self.client.cache.set_reader_position(key[0], key[1], iter_.get_offset())

    def _set_reader_position_key(self, item_type: str, authority_id: str) -> None:
        clean_id = str(authority_id or "").strip()
        self._reader_position_key = (item_type, clean_id) if clean_id else None
        update_button = getattr(self, "_update_reader_highlight_button", None)
        if update_button is not None:
            update_button()

    def _clear_reader_position_key(self) -> None:
        self._reader_position_key = None
        update_button = getattr(self, "_update_reader_highlight_button", None)
        if update_button is not None:
            update_button()

    def _schedule_reader_position_restore(self) -> None:
        key = self._reader_position_key
        if key is None or self._pending_quote_target is not None:
            return
        offset = self.client.cache.reader_position(key[0], key[1])
        if offset is None:
            return
        generation = self._case_load_generation
        GLib.idle_add(self._restore_reader_position, key, generation, offset)

    def _restore_reader_position(
        self,
        key: tuple[str, str],
        generation: int,
        offset: int,
    ) -> bool:
        if (
            generation != self._case_load_generation
            or key != self._reader_position_key
            or self._pending_quote_target is not None
            or not self._reader_text
        ):
            return False
        clean_offset = max(0, min(offset, self.reader_buffer.get_char_count()))
        iter_ = self.reader_buffer.get_iter_at_offset(clean_offset)
        self.reader_view.scroll_to_iter(iter_, 0.0, True, 0.0, 0.0)
        return False

    def _set_reader_text(
        self,
        text: str,
        page_markers: list[PageMarker] | None = None,
        *,
        apply_markdown: bool = False,
    ) -> bool:
        if page_markers:
            display = normalize_display_quote_stacks(
                DisplayText(text=text, source_field="", page_markers=list(page_markers))
            )
            text = display.text
            page_markers = display.page_markers
        else:
            text = normalize_malformed_quote_stacks(text)
        markdown_spans: list[tuple[int, int, str]] = []
        if apply_markdown:
            text, markdown_spans, _offset_map = self._render_markdown_text(text)
        text = smart_quote_display_text(text)
        self._set_reader_busy(False)
        self._close_reader_find(clear_entry=True)
        self._reader_text = text
        self._reader_page_markers = list(page_markers or [])
        if not page_markers and getattr(self, "_reader_pagination_mode", READER_PAGINATION_NONE) == READER_PAGINATION_SLIP:
            self._reader_pagination_mode = READER_PAGINATION_NONE
            self._reader_slip_source_url = ""
            self._reader_slip_case_number = ""
        self.reader_buffer.set_text(text)
        self._update_reader_selection_pinpoint_button()
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
        self._apply_reader_markdown_spans(markdown_spans)
        self._apply_reader_citation_italics(text)
        self._apply_reader_citation_links(text)
        apply_highlights = getattr(self, "_apply_saved_reader_highlights", None)
        if apply_highlights is not None:
            apply_highlights()
        if self._pending_quote_target is not None:
            target = self._pending_quote_target
            self._pending_quote_target = None
            self._highlight_reader_quote_target(target)
        else:
            schedule_restore = getattr(self, "_schedule_reader_position_restore", None)
            if schedule_restore is not None:
                schedule_restore()
        return False

    def _case_load_is_current(self, generation: int, cluster_id: str) -> bool:
        if generation != self._case_load_generation:
            return False
        selected_cluster_id = cluster_id_from_cluster(self._selected_cluster or {})
        return not cluster_id or cluster_id == selected_cluster_id

    def _start_reader_payload_render(self, payload: CaseReaderPayload) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        if payload.cache_generation == self._research_cache_generation and payload.opinion_ids:
            self.client.cache.update_case_opinions(
                payload.cluster,
                list(payload.opinion_ids),
                mark_dirty=False,
            )
        self._close_reader_find(clear_entry=True)
        self._reader_text = ""
        self._reader_page_markers = list(payload.page_markers)
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = payload.pagination_mode
        self._reader_slip_source_url = payload.slip_source_url
        self._reader_slip_case_number = payload.slip_case_number
        if payload.pagination_mode == READER_PAGINATION_SLIP:
            formatted = format_published_slip_opinion_citation(
                payload.cluster,
                case_number=payload.slip_case_number,
            )
            if formatted is not None:
                self._set_reader_header(formatted.plain_text, formatted, payload.cluster)
        self._clear_reader_citation_links()
        self.reader_buffer.set_text("")
        self._update_reader_selection_pinpoint_button()
        GLib.idle_add(self._insert_reader_payload_text_chunk, payload, 0)
        return False

    def _insert_reader_payload_text_chunk(self, payload: CaseReaderPayload, offset: int) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        end = min(offset + READER_RENDER_TEXT_CHUNK_SIZE, len(payload.text))
        if end > offset:
            self.reader_buffer.insert(
                self.reader_buffer.get_end_iter(),
                payload.text[offset:end],
            )
        if end < len(payload.text):
            GLib.idle_add(self._insert_reader_payload_text_chunk, payload, end)
            return False
        self._reader_text = payload.text
        GLib.idle_add(self._apply_reader_payload_page_marker_chunk, payload, 0)
        return False

    def _apply_reader_payload_page_marker_chunk(self, payload: CaseReaderPayload, index: int) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        end_index = min(index + READER_RENDER_TAG_CHUNK_SIZE, len(payload.page_markers))
        for marker in payload.page_markers[index:end_index]:
            start = max(0, min(marker.start_offset, len(payload.text)))
            end = max(start, min(marker.end_offset, len(payload.text)))
            if start == end:
                continue
            self.reader_buffer.apply_tag(
                self.page_marker_tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )
        if end_index < len(payload.page_markers):
            GLib.idle_add(self._apply_reader_payload_page_marker_chunk, payload, end_index)
            return False
        GLib.idle_add(self._apply_reader_payload_italic_chunk, payload, 0)
        return False

    def _apply_reader_payload_italic_chunk(self, payload: CaseReaderPayload, index: int) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        if self._reader_citation_italic_tag is None:
            GLib.idle_add(self._apply_reader_payload_link_chunk, payload, 0)
            return False
        end_index = min(index + READER_RENDER_TAG_CHUNK_SIZE, len(payload.italic_spans))
        for span in payload.italic_spans[index:end_index]:
            start = max(0, min(span.start_offset, len(payload.text)))
            end = max(start, min(span.end_offset, len(payload.text)))
            if start == end:
                continue
            self.reader_buffer.apply_tag(
                self._reader_citation_italic_tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )
        if end_index < len(payload.italic_spans):
            GLib.idle_add(self._apply_reader_payload_italic_chunk, payload, end_index)
            return False
        GLib.idle_add(self._apply_reader_payload_link_chunk, payload, 0)
        return False

    def _apply_reader_payload_link_chunk(self, payload: CaseReaderPayload, index: int) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        end_index = min(index + READER_RENDER_TAG_CHUNK_SIZE, len(payload.cited_links))
        for link_index, link in enumerate(payload.cited_links[index:end_index], start=index):
            self._apply_reader_citation_link(link_index, link)
        if end_index < len(payload.cited_links):
            GLib.idle_add(self._apply_reader_payload_link_chunk, payload, end_index)
            return False
        GLib.idle_add(self._finish_reader_payload_render, payload)
        return False

    def _finish_reader_payload_render(self, payload: CaseReaderPayload) -> bool:
        if not self._case_load_is_current(payload.generation, payload.cluster_id):
            return False
        apply_highlights = getattr(self, "_apply_saved_reader_highlights", None)
        if apply_highlights is not None:
            apply_highlights()
        if self._pending_quote_target is not None:
            target = self._pending_quote_target
            self._pending_quote_target = None
            self._highlight_reader_quote_target(target)
        else:
            schedule_restore = getattr(self, "_schedule_reader_position_restore", None)
            if schedule_restore is not None:
                schedule_restore()
        self._set_reader_busy(False)
        self._finish_case_quality_status(
            payload.cluster_id,
            payload.quality_eligible,
            payload.quality_reason,
            payload.opinion_source,
            payload.pagination_mode,
            payload.cache_generation,
        )
        return False

    def _set_reader_header(
        self,
        text: str,
        citation: FormattedCitation | None = None,
        cluster: dict[str, Any] | None = None,
    ) -> None:
        header = text.strip()
        self._reader_header_citation = citation
        self._reader_display_cluster = cluster
        self.reader_header_label.set_text(header)
        self.reader_header_copy_button.set_visible(citation is not None)
        if self.reader_selection_pinpoint_button is not None:
            has_selected_authority = (
                self._reader_display_cluster is not None
                or self._selected_cluster is not None
                or self._selected_statute is not None
                or self._selected_rule is not None
            )
            self.reader_selection_pinpoint_button.set_visible(
                bool(header and has_selected_authority)
            )
            self._update_reader_selection_pinpoint_button()
        if self.reader_subsequent_treatment_button is not None:
            self.reader_subsequent_treatment_button.set_visible(
                bool(header and self._reader_display_cluster is not None)
            )
            self.reader_subsequent_treatment_button.set_sensitive(
                self._reader_display_cluster is not None
            )
        self._update_reader_helper_case_button()
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

    def _on_reader_selection_changed(self, *_args: object) -> None:
        self._update_reader_selection_pinpoint_button()
        update_highlight = getattr(self, "_update_reader_highlight_button", None)
        if update_highlight is not None:
            update_highlight()

    def _reader_highlight_key(self) -> tuple[str, str] | None:
        key = getattr(self, "_reader_position_key", None)
        if key is None or key[0] not in {"case", "statute", "rule"} or not key[1]:
            return None
        return key

    def _update_reader_highlight_button(self) -> None:
        button = getattr(self, "_reader_highlight_button", None)
        if button is None:
            return
        key = self._reader_highlight_key()
        selection = self._reader_selection_bounds() if key is not None else None
        button.set_sensitive(selection is not None)
        remove = False
        if selection is not None and key is not None:
            start, end, _selected_text = selection
            entries = self.client.cache.reader_highlights(key[0], key[1])
            remove = any(
                span_start <= start and end <= span_end
                for _entry, span_start, span_end in resolved_reader_highlights(
                    self._reader_text,
                    entries,
                )
            )
        button.set_tooltip_text(
            "Remove highlight" if remove else "Highlight selected text"
        )

    def _apply_saved_reader_highlights(
        self,
        entries: list[ReaderHighlight] | None = None,
    ) -> None:
        tag = getattr(self, "_reader_saved_highlight_tag", None)
        if tag is None:
            return
        self.reader_buffer.remove_tag(
            tag,
            self.reader_buffer.get_start_iter(),
            self.reader_buffer.get_end_iter(),
        )
        key = self._reader_highlight_key()
        if key is None or not self._reader_text:
            return
        if entries is None:
            entries = self.client.cache.reader_highlights(key[0], key[1])
        for _entry, start, end in resolved_reader_highlights(self._reader_text, entries):
            self.reader_buffer.apply_tag(
                tag,
                self.reader_buffer.get_iter_at_offset(start),
                self.reader_buffer.get_iter_at_offset(end),
            )

    def _on_toggle_reader_highlight_clicked(self, _button: Gtk.Button) -> None:
        key = self._reader_highlight_key()
        selection = self._reader_selection_bounds()
        if key is None or selection is None:
            self._set_status("Select case, statute, or rule text before highlighting.")
            return
        start, end, _selected_text = selection
        existing = self.client.cache.reader_highlights(key[0], key[1])
        updated, action = toggle_reader_highlight(
            self._reader_text,
            existing,
            start,
            end,
        )
        if action == "unchanged":
            self._set_status("Selected text could not be highlighted.")
            return
        try:
            self.client.cache.set_reader_highlights(key[0], key[1], updated)
        except OSError as exc:
            self._set_status(f"Could not save highlight: {exc}")
            return
        self._apply_saved_reader_highlights(updated)
        self.reader_buffer.place_cursor(self.reader_buffer.get_iter_at_offset(end))
        self._set_status(
            "Removed highlight." if action == "removed" else "Highlighted selected text."
        )

    def _update_reader_selection_pinpoint_button(self) -> None:
        has_authority = (
            getattr(self, "_reader_display_cluster", None) is not None
            or getattr(self, "_selected_cluster", None) is not None
            or getattr(self, "_selected_statute", None) is not None
            or getattr(self, "_selected_rule", None) is not None
        )
        has_selection = self._reader_selection_bounds() is not None
        if self.reader_selection_pinpoint_button is not None:
            self.reader_selection_pinpoint_button.set_sensitive(
                bool(has_authority and has_selection)
            )
        self._update_reader_helper_case_button()

    def _update_reader_helper_case_button(self) -> None:
        if self.reader_helper_case_button is None:
            return
        available = self._helper_case_available()
        self.reader_helper_case_button.set_visible(available)
        self.reader_helper_case_button.set_sensitive(available)

    def _helper_case_available(self) -> bool:
        cluster = (
            getattr(self, "_reader_display_cluster", None)
            or getattr(self, "_selected_cluster", None)
        )
        if cluster is None:
            return False
        if getattr(self, "_reader_has_official_pagination", False):
            return False
        if getattr(self, "_reader_pagination_mode", READER_PAGINATION_NONE) == READER_PAGINATION_SLIP:
            return False
        if not getattr(self, "_reader_text", "").strip():
            return False
        return bool(cluster_citation_line(cluster))

    def _reader_selection_bounds(self) -> tuple[int, int, str] | None:
        bounds = self.reader_buffer.get_selection_bounds()
        if not bounds:
            return None
        if len(bounds) == 3:
            selected, start_iter, end_iter = bounds
            if not selected:
                return None
        elif len(bounds) == 2:
            start_iter, end_iter = bounds
        else:
            return None
        start_offset = start_iter.get_offset()
        end_offset = end_iter.get_offset()
        if start_offset == end_offset:
            return None
        if end_offset < start_offset:
            start_offset, end_offset = end_offset, start_offset
            start_iter = self.reader_buffer.get_iter_at_offset(start_offset)
            end_iter = self.reader_buffer.get_iter_at_offset(end_offset)
        selected_text = self.reader_buffer.get_text(start_iter, end_iter, True)
        return start_offset, end_offset, selected_text

    def _on_copy_reader_selection_pinpoint_clicked(self, _button: Gtk.Button) -> None:
        selection = self._reader_selection_bounds()
        if selection is None:
            self._set_status(
                "Select case, statute, or rule text before copying a pinpoint citation."
            )
            return
        start_offset, end_offset, selected_text = selection
        citation = self._reader_selection_pinpoint_formatted_citation(start_offset, end_offset)
        if citation is None:
            self._set_status("Could not determine a pinpoint citation for the selected text.")
            return
        selected_text = self._clipboard_selected_authority_text(
            selected_text,
            strip_page_markers=True,
        )
        if not selected_text:
            self._set_status("Selected text is empty.")
            return
        payload = self._selection_pinpoint_clipboard_payload(
            selected_text,
            citation,
        )
        if self._set_formatted_clipboard(payload, "Could not copy selected text."):
            self._set_status("Selected text and pinpoint citation copied.")

    def _on_helper_case_clicked(
        self,
        _button: Gtk.Button,
    ) -> None:
        cluster = (
            getattr(self, "_reader_display_cluster", None)
            or getattr(self, "_selected_cluster", None)
        )
        if cluster is None:
            self._set_status("Select a case before asking Codex for a helper case.")
            return
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            self._set_status("Selected case has no CourtListener cluster id.")
            return
        target_citation = cluster_citation_line(cluster)
        if not target_citation:
            self._set_status("No official reporter citation is available for this case.")
            return
        OpenLawLensWindow._start_helper_case_agent(
            self,
            cluster,
            cluster_id,
            target_citation,
        )

    def _start_later_treatment_agent(
        self,
        cluster: dict[str, Any],
        cluster_id: str,
        target_citation: str,
    ) -> None:
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return
        prompt = OpenLawLensWindow._compose_later_treatment_agent_prompt(
            self,
            cluster,
            cluster_id,
            target_citation,
        )
        prompt_path = self._write_prompt_file(prompt)
        try:
            workspace = self._create_agent_workspace()
        except OSError as exc:
            self._set_status(f"Unable to create agent workspace: {exc}")
            return
        self._set_agent_mode(AGENT_MODE_GENERAL)
        self._case_agent_text_sources = []
        self._agent_mode = AGENT_MODE_GENERAL
        config = load_config()
        self._launch_agent_with_prompt(
            prompt_path,
            workspace,
            AGENT_MODE_GENERAL,
            xhigh_reasoning_effort(config.later_treatment_xhigh_reasoning),
        )

    def _compose_later_treatment_agent_prompt(
        self,
        cluster: dict[str, Any],
        cluster_id: str,
        target_citation: str,
    ) -> str:
        command = (
            "uv run --no-sync open-law-lens published-citing-cases "
            f"--cluster-id {cluster_id} --limit 10 --json"
        )
        config = load_config()
        return self._format_agent_prompt(
            config.later_treatment_agent_prompt_template,
            DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
            {
                "target_title": cluster_short_title(cluster),
                "target_citation": target_citation,
                "cluster_id": cluster_id,
                "published_citing_cases_command": command,
            },
        )

    def _start_helper_case_agent(
        self,
        cluster: dict[str, Any],
        cluster_id: str,
        target_citation: str,
    ) -> None:
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return
        prompt = OpenLawLensWindow._compose_helper_case_agent_prompt(
            self,
            cluster,
            cluster_id,
            target_citation,
        )
        prompt_path = self._write_prompt_file(prompt)
        try:
            workspace = self._create_agent_workspace()
        except OSError as exc:
            self._set_status(f"Unable to create agent workspace: {exc}")
            return
        self._set_agent_mode(AGENT_MODE_GENERAL)
        self._case_agent_text_sources = []
        self._agent_mode = AGENT_MODE_GENERAL
        self._launch_agent_with_prompt(prompt_path, workspace, AGENT_MODE_GENERAL)

    def _compose_helper_case_agent_prompt(
        self,
        cluster: dict[str, Any],
        cluster_id: str,
        target_citation: str,
    ) -> str:
        title = cluster_short_title(cluster)
        command = (
            "uv run --no-sync open-law-lens best-published-citing-case "
            f"--cluster-id {cluster_id} --json"
        )
        return (
            "Find the best published helper case for pinpointing the currently "
            "viewed case.\n\n"
            f"Target case: {title}\n"
            f"Target official citation: {target_citation}\n"
            f"CourtListener cluster id: {cluster_id}\n\n"
            "Run exactly this bounded OpenLawLens CLI command:\n"
            f"{command}\n\n"
            "Use only that command's first-page published citing-case result. "
            "Do not continue crawling CourtListener unless the user asks. "
            "If the JSON says ok=false or has no result, say that no published "
            "helper case was found in the first cited-by page. Otherwise return "
            "only the best published helper case citation in a form the app can "
            "link, followed by one short sentence explaining the total citation "
            "depth and citation-reference count."
        )

    def _reader_selection_pinpoint_citation(self, start_offset: int, end_offset: int) -> str:
        formatted = OpenLawLensWindow._reader_selection_pinpoint_formatted_citation(
            self,
            start_offset,
            end_offset,
        )
        return formatted.plain_text if formatted is not None else ""

    def _reader_selection_pinpoint_formatted_citation(
        self,
        start_offset: int,
        end_offset: int,
    ) -> FormattedCitation | None:
        selected_cluster = (
            getattr(self, "_reader_display_cluster", None)
            or getattr(self, "_selected_cluster", None)
        )
        selected_statute = getattr(self, "_selected_statute", None)
        selected_rule = getattr(self, "_selected_rule", None)
        if selected_cluster is not None:
            if getattr(self, "_reader_pagination_mode", READER_PAGINATION_NONE) == READER_PAGINATION_SLIP:
                return OpenLawLensWindow._case_selection_slip_pinpoint_formatted_citation(
                    self,
                    selected_cluster,
                    start_offset,
                    end_offset,
                )
            return OpenLawLensWindow._case_selection_pinpoint_formatted_citation(
                self,
                selected_cluster,
                start_offset,
                end_offset,
            )
        if selected_statute is not None:
            statute = selected_statute
            citation_text = str(statute.get("citation") or "").strip()
            parsed = parse_statute_citation(citation_text)
            law_code = str(statute.get("law_code") or "").strip()
            section = str(statute.get("section") or "").strip()
            if parsed is not None:
                law_code = law_code or parsed.law_code
                section = section or parsed.section
            if not law_code or not section:
                return None
            subdivisions = statute_subdivisions_for_range(
                self._reader_text,
                start_offset,
                end_offset,
            )
            if not subdivisions and parsed is not None and parsed.subdivision:
                subdivisions = (parsed.subdivision,)
            plain = statute_pinpoint_citation(
                StatuteCitation(law_code, section),
                subdivisions,
            )
            return FormattedCitation(
                plain_text=plain,
                html_text=GLib.markup_escape_text(plain),
            )
        if selected_rule is not None:
            rule = selected_rule
            citation_text = str(rule.get("citation") or "").strip()
            parsed = parse_rule_citation(citation_text)
            rule_number = str(rule.get("rule_number") or "").strip()
            if parsed is not None:
                rule_number = rule_number or parsed.rule_number
            if not rule_number:
                return None
            subdivisions = rule_subdivisions_for_range(
                self._reader_text,
                start_offset,
                end_offset,
            )
            if not subdivisions:
                existing = str(rule.get("subdivision") or "").strip()
                if existing:
                    subdivisions = (existing,)
                elif parsed is not None and parsed.subdivision:
                    subdivisions = (parsed.subdivision,)
            plain = rule_pinpoint_citation(
                RuleCitation(rule_number),
                subdivisions,
            )
            return FormattedCitation(
                plain_text=plain,
                html_text=GLib.markup_escape_text(plain),
            )
        return None

    def _case_selection_pinpoint_formatted_citation(
        self,
        cluster: dict[str, Any],
        start_offset: int,
        end_offset: int,
    ) -> FormattedCitation | None:
        formatted = format_official_california_citation(cluster)
        if formatted is None:
            return None
        if not getattr(self, "_reader_page_markers", []):
            return None
        first_page = OpenLawLensWindow._case_first_official_page(cluster)
        start_page = OpenLawLensWindow._reader_page_for_offset(self, start_offset)
        if start_page is None:
            start_page = first_page
        end_page = OpenLawLensWindow._reader_page_for_offset(
            self,
            max(start_offset, end_offset - 1),
        )
        if end_page is None:
            end_page = start_page
        if start_page is None or end_page is None:
            return None
        pinpoint = start_page if start_page == end_page else f"{start_page}\u2013{end_page}"
        return FormattedCitation(
            plain_text=f"{formatted.plain_text}, {pinpoint}",
            html_text=f"{formatted.html_text}, {GLib.markup_escape_text(pinpoint)}",
        )

    def _case_selection_slip_pinpoint_formatted_citation(
        self,
        cluster: dict[str, Any],
        start_offset: int,
        end_offset: int,
    ) -> FormattedCitation | None:
        if not getattr(self, "_reader_page_markers", []):
            return None
        start_page = OpenLawLensWindow._reader_page_for_offset(self, start_offset)
        end_page = OpenLawLensWindow._reader_page_for_offset(
            self,
            max(start_offset, end_offset - 1),
        )
        if start_page is None:
            start_page = "1"
        if end_page is None:
            end_page = start_page
        pinpoint = start_page if start_page == end_page else f"{start_page}\u2013{end_page}"
        case_number = (
            str(getattr(self, "_reader_slip_case_number", "") or "").strip()
            or case_number_from_cluster(cluster)
        )
        if not case_number:
            return None
        formatted = format_published_slip_opinion_citation(
            cluster,
            case_number=case_number,
            long_date=True,
        )
        if formatted is None:
            return None
        page_label = "pp." if start_page != end_page else "p."
        pinpoint = pinpoint.replace("\u2013", "-")
        plain = f"{formatted.plain_text} slip opn. at {page_label} {pinpoint}"
        html_text = f"{formatted.html_text} slip opn. at {page_label} {GLib.markup_escape_text(pinpoint)}"
        return FormattedCitation(plain_text=plain, html_text=html_text)

    def _case_selection_pinpoint_citation(
        self,
        cluster: dict[str, Any],
        start_offset: int,
        end_offset: int,
    ) -> str:
        formatted = OpenLawLensWindow._case_selection_pinpoint_formatted_citation(
            self,
            cluster,
            start_offset,
            end_offset,
        )
        return formatted.plain_text if formatted is not None else ""

    def _reader_page_for_offset(self, offset: int) -> str | None:
        page = ""
        for marker in sorted(
            getattr(self, "_reader_page_markers", []),
            key=lambda value: value.start_offset,
        ):
            if marker.start_offset <= offset:
                label = str(marker.page_label).strip()
                if re.fullmatch(r"\d{1,5}", label):
                    page = label
                continue
            break
        return page or None

    @staticmethod
    def _case_first_official_page(cluster: dict[str, Any]) -> str | None:
        parts = official_citation_parts_from_cluster(cluster)
        if parts is None:
            return None
        return parts[2]

    @staticmethod
    def _clipboard_selected_authority_text(text: str, *, strip_page_markers: bool = False) -> str:
        if strip_page_markers:
            text = re.sub(r"\[\*\d{1,5}\]", " ", text)
            text = re.sub(r"\[Slip opn\. p\. \d{1,5}\]", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _pinpoint_citation_parenthetical(citation: str) -> str:
        stripped = citation.strip()
        if not stripped:
            return ""
        suffix = "" if stripped.endswith(".") else "."
        return f"({stripped}{suffix})"

    @staticmethod
    def _pinpoint_citation_parenthetical_html(citation_html: str) -> str:
        stripped = citation_html.strip()
        if not stripped:
            return ""
        suffix = "" if stripped.endswith(".") else "."
        return f"({stripped}{suffix})"

    @staticmethod
    def _selection_pinpoint_clipboard_payload(
        selected_text: str,
        citation: FormattedCitation,
    ) -> FormattedCitation:
        return FormattedCitation(
            plain_text=(
                f"{selected_text} "
                f"{OpenLawLensWindow._pinpoint_citation_parenthetical(citation.plain_text)}"
            ),
            html_text=(
                f"{GLib.markup_escape_text(selected_text)} "
                f"{OpenLawLensWindow._pinpoint_citation_parenthetical_html(citation.html_text)}"
            ),
        )

    def _on_later_treatment_clicked(
        self,
        _button: Gtk.Button,
    ) -> None:
        cluster = (
            getattr(self, "_reader_display_cluster", None)
            or getattr(self, "_selected_cluster", None)
        )
        if cluster is None:
            self._set_status("Select a case first.")
            return
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            self._set_status("Selected case has no CourtListener cluster id.")
            return
        target_citation = cluster_citation_line(cluster)
        if not target_citation:
            self._set_status("No reporter citation is available for this case.")
            return
        OpenLawLensWindow._start_later_treatment_agent(
            self,
            cluster,
            cluster_id,
            target_citation,
        )

    def _apply_reader_citation_links(self, text: str) -> None:
        self._clear_reader_citation_links()
        excluded = cluster_citation_texts(self._selected_cluster)
        for index, link in enumerate(cited_case_links(text, excluded_citations=excluded)):
            self._apply_reader_citation_link(index, link)
        offset = len(self._reader_citation_link_tags)
        for index, link in enumerate(cited_statute_links(text), start=offset):
            self._apply_reader_statute_link(index, link)
        offset = len(self._reader_citation_link_tags)
        for index, link in enumerate(cited_rule_links(text), start=offset):
            self._apply_reader_rule_link(index, link)

    def _apply_reader_markdown_spans(self, spans: list[tuple[int, int, str]]) -> None:
        if not spans:
            return
        table = self.reader_buffer.get_tag_table()
        if table is None:
            return

        def ensure_tag(name: str, **props: object) -> Gtk.TextTag:
            tag = table.lookup(name)
            if tag is None:
                tag = self.reader_buffer.create_tag(name, **props)
            return tag

        bold_tag = ensure_tag("reader-md-bold", weight=Pango.Weight.BOLD)
        italic_tag = ensure_tag("reader-md-italic", style=Pango.Style.ITALIC)
        for start, end, kind in spans:
            if end <= start:
                continue
            start_iter = self.reader_buffer.get_iter_at_offset(start)
            end_iter = self.reader_buffer.get_iter_at_offset(end)
            if kind == "bold":
                self.reader_buffer.apply_tag(bold_tag, start_iter, end_iter)
            elif kind == "italic":
                self.reader_buffer.apply_tag(italic_tag, start_iter, end_iter)

    def _clear_reader_citation_links(self) -> None:
        table = self.reader_buffer.get_tag_table()
        if table is not None:
            for tag in self._reader_citation_link_tags:
                table.remove(tag)
        self._reader_citation_link_tags.clear()
        self._reader_citation_link_lookup.clear()
        self._reader_statute_link_lookup.clear()
        self._reader_rule_link_lookup.clear()

    def _apply_reader_citation_link(self, index: int, link: CitedCaseLink) -> None:
        start = max(0, min(link.start_offset, len(self._reader_text)))
        end = max(start, min(link.end_offset, len(self._reader_text)))
        if start == end:
            return
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

    def _apply_reader_statute_link(self, index: int, link: StatuteLink) -> None:
        start = max(0, min(link.start_offset, len(self._reader_text)))
        end = max(start, min(link.end_offset, len(self._reader_text)))
        if start == end:
            return
        tag = self.reader_buffer.create_tag(
            f"reader-statute-link-{index}",
            underline=Pango.Underline.SINGLE,
            foreground="#1a5fb4",
        )
        self.reader_buffer.apply_tag(
            tag,
            self.reader_buffer.get_iter_at_offset(start),
            self.reader_buffer.get_iter_at_offset(end),
        )
        self._reader_citation_link_tags.append(tag)
        self._reader_statute_link_lookup[tag] = link

    def _apply_reader_rule_link(self, index: int, link: RuleLink) -> None:
        start = max(0, min(link.start_offset, len(self._reader_text)))
        end = max(start, min(link.end_offset, len(self._reader_text)))
        if start == end:
            return
        tag = self.reader_buffer.create_tag(
            f"reader-rule-link-{index}",
            underline=Pango.Underline.SINGLE,
            foreground="#1a5fb4",
        )
        self.reader_buffer.apply_tag(
            tag,
            self.reader_buffer.get_iter_at_offset(start),
            self.reader_buffer.get_iter_at_offset(end),
        )
        self._reader_citation_link_tags.append(tag)
        self._reader_rule_link_lookup[tag] = link

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
            click.connect("pressed", self._on_reader_citation_pressed)
            click.connect("released", self._on_reader_citation_click)
            click.connect("stopped", self._clear_reader_link_press)
            click.connect("cancel", self._clear_reader_link_press)
            self.reader_view.add_controller(click)
            self._reader_citation_click_gesture = click

    @staticmethod
    def _link_release_is_click(
        view: Gtk.Widget,
        press: LinkPressState | None,
        target: object | None,
        n_press: int,
        x: float,
        y: float,
    ) -> bool:
        if press is None or n_press != 1 or target is not press.target:
            return False
        return not view.drag_check_threshold(
            int(press.x),
            int(press.y),
            int(x),
            int(y),
        )

    def _reader_citation_link_at_coords(self, x: float, y: float) -> CitedCaseLink | StatuteLink | RuleLink | None:
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
            statute_link = self._reader_statute_link_lookup.get(tag)
            if statute_link is not None:
                return statute_link
            rule_link = self._reader_rule_link_lookup.get(tag)
            if rule_link is not None:
                return rule_link
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

    def _on_reader_citation_pressed(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        target = self._reader_citation_link_at_coords(x, y)
        self._reader_link_press = (
            LinkPressState(target, x, y)
            if n_press == 1 and target is not None and (not button or button == Gdk.BUTTON_PRIMARY)
            else None
        )

    def _clear_reader_link_press(self, *_args: object) -> None:
        self._reader_link_press = None

    def _on_reader_citation_click(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        press = self._reader_link_press
        self._reader_link_press = None
        if button and button != Gdk.BUTTON_PRIMARY:
            return
        link = self._reader_citation_link_at_coords(x, y)
        if not self._link_release_is_click(self.reader_view, press, link, n_press, x, y):
            return
        if isinstance(link, StatuteLink):
            self._open_statute_link(link)
            return
        if isinstance(link, RuleLink):
            self._open_rule_link(link)
            return
        self._open_cited_case_link(link)

    def _open_cited_case_link(self, link: CitedCaseLink) -> None:
        self._open_citation_lookup_link(link)

    def _open_agent_cited_case_link(self, link: CitedCaseLink) -> None:
        self._open_citation_lookup_link(link)

    def _open_statute_link(self, link: StatuteLink) -> None:
        self._start_statute_lookup(link.lookup_text)

    def _open_rule_link(self, link: RuleLink) -> None:
        self._start_rule_lookup(link.lookup_text)

    def _open_citation_lookup_link(
        self,
        link: CitedCaseLink,
        *,
        populate_research_cache: bool = True,
    ) -> None:
        self._start_lookup(
            link.lookup_text,
            link=link,
            populate_research_cache=populate_research_cache,
        )

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
            self._agent_subview_strip.set_visible(output_visible)
        if self._agent_save_answer_button is not None:
            self._agent_save_answer_button.set_sensitive(bool(self._agent_last_answer_text.strip()))
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

    def _on_save_agent_answer_clicked(self, _button: Gtk.Button) -> None:
        text = strip_agent_legal_authority_backticks(self._agent_last_answer_text).strip()
        if not text:
            self._set_status("No agent final answer to save.")
            return
        self._agent_last_answer_text = text
        answer_id = self.client.cache.save_agent_answer(text, mode=self._agent_mode)
        if not answer_id:
            self._set_status("No agent final answer to save.")
            return
        self._set_sidebar_authorities(
            self._clusters,
            self._statutes,
            self._rules,
            select_agent_answer_id=answer_id,
        )
        self._set_status("Saved agent answer to Research Cache. Library preserved.")

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
                placeholder = "Ask about marked Research Cache authorities"
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

    def _on_show_cli_commands(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self._cli_commands_window is None:
            self._cli_commands_window = CliCommandsWindow(self)
            self._cli_commands_window.connect("close-request", self._on_cli_commands_closed)
        self._cli_commands_window.present()

    def _on_cli_commands_closed(self, _window: Gtk.Window) -> bool:
        self._cli_commands_window = None
        return False

    def open_authority_text(self, text: str) -> bool:
        entry_text = re.sub(r"\s+", " ", text).strip()
        if not entry_text:
            self._set_status("No authority text provided.")
            return False
        bare_statute_lookup_text = self._bare_statute_lookup_text(entry_text)
        if bare_statute_lookup_text:
            self.citation_entry.set_text("")
            self._start_statute_lookup(bare_statute_lookup_text)
            return False
        candidate = first_authority_candidate(entry_text)
        lookup_text = candidate.text
        self.citation_entry.set_text("")
        if candidate.authority_type == "statute" or parse_statute_citation(lookup_text) is not None:
            self._start_statute_lookup(lookup_text)
            return False
        if candidate.authority_type == "rule" or parse_rule_citation(lookup_text) is not None:
            self._start_rule_lookup(lookup_text)
            return False
        citation = self._external_lookup_text(lookup_text)
        self._start_lookup(citation)
        return False

    def _external_lookup_text(self, lookup_text: str) -> str:
        if not self._case_suggestions_loaded:
            self._refresh_case_suggestion_index_async()
            return lookup_text
        return resolve_case_lookup_text(lookup_text, self._case_suggestions) or lookup_text

    def _bare_statute_lookup_text(self, text: str) -> str:
        if re.fullmatch(r"\d+[a-z]?(?:\.\d+[a-z]?)?", text, re.IGNORECASE) is None:
            return ""
        try:
            law_code = normalize_bare_statute_law_code(load_config().default_bare_statute_law_code)
            section = normalize_section(text)
            return statute_display_citation(StatuteCitation(law_code, section))
        except ValueError:
            return ""

    def show_open_authority_pending(self, message: str = "Opening selected authority...") -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        self._hide_case_completion()
        self._set_reader_header("")
        self._set_status(message)
        self._set_reader_busy(True, message)
        self.reader_buffer.set_text("Loading...")

    def _on_window_tick(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        self._update_agent_panel_height()
        return True

    def reload_settings(self) -> None:
        self.client = CourtListenerClient.default()
        self._research_cache_generation += 1
        self._case_load_generation += 1
        self._install_css()
        self._refresh_current_case_context()
        self._load_cached_cases()
        self._refresh_case_suggestion_index_async(force=True)
        self._refresh_appeal_issue_menu()
        self._set_status("Settings saved.")

    def _on_open_settings(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.connect("close-request", self._on_settings_closed)
        self._settings_window.present()

    def _on_settings_closed(self, _window: Gtk.Window) -> bool:
        self._settings_window = None
        return False

    def _on_assess_appeal_issue(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._on_open_settings(_action, _parameter)

    def _on_appeal_issue_settings_clicked(
        self,
        _button: Gtk.Button,
        popover: Gtk.Popover,
    ) -> None:
        popover.popdown()
        self._on_open_settings(self.lookup_action("settings"), None)

    def _on_custom_appeal_issue_clicked(
        self,
        _button: Gtk.Button,
        popover: Gtk.Popover,
    ) -> None:
        popover.popdown()
        self._show_custom_appeal_issue_window()

    def _show_custom_appeal_issue_window(self) -> None:
        window = Gtk.Window(title="Assess Argument")
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(560, 300)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        text_buffer = Gtk.TextBuffer()
        text_view = Gtk.TextView(buffer=text_buffer)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_view.set_vexpand(True)
        text_view.set_hexpand(True)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(text_view)
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        box.append(scroller)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_row.set_halign(Gtk.Align.END)
        cancel_button = Gtk.Button(label="Cancel")
        cancel_button.connect("clicked", lambda _button: window.close())
        button_row.append(cancel_button)
        action_button = Gtk.Button(label="Assess")
        action_button.connect(
            "clicked",
            self._on_custom_appeal_issue_assess_clicked,
            window,
            text_buffer,
        )
        button_row.append(action_button)
        box.append(button_row)

        window.set_child(box)
        window.present()
        text_view.grab_focus()

    def _on_custom_appeal_issue_assess_clicked(
        self,
        _button: Gtk.Button,
        window: Gtk.Window,
        text_buffer: Gtk.TextBuffer,
    ) -> None:
        start = text_buffer.get_start_iter()
        end = text_buffer.get_end_iter()
        issue = text_buffer.get_text(start, end, True).strip()
        started = self._start_custom_appeal_issue_assessment(issue)
        if started:
            window.close()

    def _on_appeal_issue_menu_item_clicked(
        self,
        _button: Gtk.Button,
        index: int,
        popover: Gtk.Popover,
    ) -> None:
        popover.popdown()
        self._start_appeal_issue_assessment_by_index(index)

    def _appeal_fact_pattern_path(self) -> Path | None:
        if self._appeal_fact_pattern_path_override is not None:
            return self._appeal_fact_pattern_path_override
        try:
            return current_case_socf_odt()
        except CurrentCaseError as exc:
            self._set_status(f"Unable to find current case SOCF: {exc}")
            return None

    def _start_appeal_issue_assessment_by_index(self, index: int) -> None:
        issues = load_config().appeal_issue_presets
        if not (0 <= index < len(issues)):
            self._set_status("Choose an argument to assess.")
            return
        fact_pattern_path = self._appeal_fact_pattern_path()
        if fact_pattern_path is None:
            return
        if not fact_pattern_path.is_file():
            self._set_status(f"Fact pattern file not found: {fact_pattern_path}")
            return
        self.start_appeal_issue_assessment(issues[index], fact_pattern_path)

    def _start_custom_appeal_issue_assessment(self, issue: str) -> bool:
        issue = issue.strip()
        if not issue:
            self._set_status("Enter an argument to assess.")
            return False
        fact_pattern_path = self._appeal_fact_pattern_path()
        if fact_pattern_path is None:
            return False
        if not fact_pattern_path.is_file():
            self._set_status(f"Fact pattern file not found: {fact_pattern_path}")
            return False
        return self.start_appeal_issue_assessment(issue, fact_pattern_path)

    def _on_clear_cache(self, _action: Gio.SimpleAction, _parameter: GLib.Variant | None) -> None:
        try:
            trash_path = self.client.cache.detach_for_clear()
        except Exception as exc:
            self._set_status(f"Unable to clear Research Cache: {exc}")
            return
        self._set_active_research_set(None)
        self._research_cache_generation += 1
        self._case_load_generation += 1
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        self._reader_text = ""
        self._load_cached_cases()
        self._set_reader_header("")
        self.reader_buffer.set_text("")
        self._set_reader_busy(False)
        if trash_path is None:
            self._set_status("Research Cache cleared. Library preserved.")
            return
        self._set_status("Research Cache cleared. Library preserved. Deleting old files in background.")
        thread = threading.Thread(
            target=self._delete_detached_cache_worker,
            args=(trash_path,),
            daemon=True,
        )
        thread.start()

    def _delete_detached_cache_worker(self, trash_path: Path) -> None:
        try:
            shutil.rmtree(trash_path)
        except OSError as exc:
            GLib.idle_add(self._set_status, f"Research Cache cleared, but old files remain: {exc}")

    def _restore_active_research_set(self) -> None:
        metadata = self.client.cache.active_research_set_metadata()
        if metadata is not None:
            research_set = self.client.library.read_research_set(
                int(metadata["active_research_set_id"])
            )
            if research_set is not None:
                self._set_active_research_set(
                    research_set,
                    dirty=bool(metadata.get("dirty")),
                )
                return
            self.client.cache.clear_active_research_set()
        try:
            matched = self.client.library.matching_research_set_for_cache(self.client.cache)
        except (OSError, RuntimeError, sqlite3.Error):
            matched = None
        self._set_active_research_set(matched)

    def _set_active_research_set(
        self,
        research_set: ResearchSet | None,
        *,
        dirty: bool = False,
    ) -> None:
        if research_set is None:
            self._active_research_set_id = None
            self._active_research_set_name = ""
            self._active_research_set_dirty = False
        else:
            self._active_research_set_id = research_set.set_id
            self._active_research_set_name = research_set.name
            self._active_research_set_dirty = bool(dirty)
        refresh_label = getattr(self, "_refresh_research_set_label", None)
        if callable(refresh_label):
            refresh_label()
            return
        label = getattr(self, "_research_set_label", None)
        if label is None:
            return
        if self._active_research_set_name:
            label.set_text(f"Set: {self._active_research_set_name}")
            label.set_visible(True)
        else:
            label.set_text("")
            label.set_visible(False)

    def _refresh_active_research_set_from_cache(self) -> None:
        metadata = self.client.cache.active_research_set_metadata()
        if metadata is None:
            self._active_research_set_id = None
            self._active_research_set_name = ""
            self._active_research_set_dirty = False
        else:
            self._active_research_set_id = int(metadata["active_research_set_id"])
            self._active_research_set_name = str(metadata["active_research_set_name"])
            self._active_research_set_dirty = bool(metadata.get("dirty"))
        self._refresh_research_set_label()

    def _refresh_research_set_label(self) -> None:
        if self._research_set_label is None:
            return
        if self._active_research_set_name:
            suffix = " (unsaved changes)" if self._active_research_set_dirty else ""
            self._research_set_label.set_text(f"Set: {self._active_research_set_name}{suffix}")
            self._research_set_label.set_visible(True)
        else:
            count = self._research_cache_authority_count()
            if count:
                self._research_set_label.set_text("Unattached Research Cache")
                self._research_set_label.set_visible(True)
            else:
                self._research_set_label.set_text("")
                self._research_set_label.set_visible(False)

    def _research_cache_authority_count(self) -> int:
        return (
            len(self.client.cache.list_case_entries())
            + len(self.client.cache.list_statute_entries())
            + len(self.client.cache.list_rule_entries())
            + len(self.client.cache.list_agent_answer_entries())
        )

    def _on_save_research_set(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        if self._research_cache_authority_count() == 0:
            self._set_status("Research Cache has no items to save.")
            return
        if self._active_research_set_id is not None and self._active_research_set_name:
            self._save_research_set(self._active_research_set_name, replace=True)
            return
        window = Gtk.Window(title="Save Research Set")
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(420, 120)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Research set name")
        entry.set_activates_default(True)
        box.append(entry)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        cancel_button = Gtk.Button(label="Cancel")
        save_button = Gtk.Button(label="Save")
        save_button.add_css_class("suggested-action")
        save_button.set_receives_default(True)
        cancel_button.connect("clicked", lambda *_args: window.close())
        save_button.connect("clicked", self._on_save_research_set_confirmed, window, entry)
        button_box.append(cancel_button)
        button_box.append(save_button)
        box.append(button_box)

        window.set_child(box)
        window.set_default_widget(save_button)
        window.present()
        entry.grab_focus()

    def _on_save_research_set_confirmed(
        self,
        _button: Gtk.Button,
        window: Gtk.Window,
        entry: Gtk.Entry,
    ) -> None:
        name = entry.get_text().strip()
        if not name:
            self._set_status("Research set name is required.")
            return
        existing = self.client.library.read_research_set(name)
        if existing is not None:
            self._show_replace_research_set_confirm(name, window)
            return
        self._save_research_set(name, replace=False)
        window.close()

    def _show_replace_research_set_confirm(self, name: str, parent: Gtk.Window) -> None:
        window = Gtk.Window(title="Replace Research Set")
        window.set_transient_for(parent)
        window.set_modal(True)
        window.set_default_size(420, 120)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        label = Gtk.Label(label=f"Replace existing research set '{name}'?", xalign=0)
        label.set_wrap(True)
        box.append(label)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        cancel_button = Gtk.Button(label="Cancel")
        replace_button = Gtk.Button(label="Replace")
        replace_button.add_css_class("destructive-action")
        cancel_button.connect("clicked", lambda *_args: window.close())
        replace_button.connect(
            "clicked",
            self._on_replace_research_set_confirmed,
            window,
            parent,
            name,
        )
        button_box.append(cancel_button)
        button_box.append(replace_button)
        box.append(button_box)

        window.set_child(box)
        window.present()

    def _on_replace_research_set_confirmed(
        self,
        _button: Gtk.Button,
        confirm_window: Gtk.Window,
        save_window: Gtk.Window,
        name: str,
    ) -> None:
        self._save_research_set(name, replace=True)
        confirm_window.close()
        save_window.close()

    def _save_research_set(self, name: str, *, replace: bool) -> None:
        try:
            research_set = self.client.library.save_research_set(
                name,
                self.client.cache,
                replace=replace,
            )
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self._set_status(f"Unable to save Research Set: {exc}")
            return
        self._set_active_research_set(research_set)
        OpenLawLensWindow._refresh_research_sets_menu(self)
        self._set_status(
            f"Saved Research Set '{research_set.name}' with {research_set.item_count} Research Cache item(s)."
        )

    def _on_open_research_set(
        self,
        _action: Gio.SimpleAction,
        _parameter: GLib.Variant | None,
    ) -> None:
        self._refresh_research_sets_menu()
        if self._research_sets_menu_button is not None:
            self._research_sets_menu_button.popup()

    def _build_research_set_row(
        self,
        research_set: ResearchSet,
        popover: Gtk.Popover | None = None,
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(False)
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row_box.set_margin_top(2)
        row_box.set_margin_bottom(2)
        row_box.set_margin_start(4)
        row_box.set_margin_end(4)

        name_button = Gtk.Button(label=research_set.name)
        name_button.add_css_class("flat")
        name_button.set_halign(Gtk.Align.FILL)
        name_button.set_hexpand(True)
        name_button.set_tooltip_text("Open Research Set")
        child = name_button.get_child()
        if isinstance(child, Gtk.Label):
            child.set_xalign(0)
            child.set_wrap(True)
        name_button.connect(
            "clicked",
            lambda button, set_id=research_set.set_id, row_popover=popover: (
                OpenLawLensWindow._on_load_research_set_clicked(
                    self,
                    button,
                    set_id,
                    row_popover,
                )
            ),
        )
        row_box.append(name_button)

        delete_button = Gtk.Button(icon_name="user-trash-symbolic")
        delete_button.add_css_class("flat")
        delete_button.add_css_class("case-row-icon-button")
        delete_button.set_tooltip_text("Delete Research Set")
        delete_button.connect(
            "clicked",
            lambda button, set_id=research_set.set_id, row_popover=popover: (
                OpenLawLensWindow._on_delete_research_set_clicked(
                    self,
                    button,
                    set_id,
                    row_popover,
                )
            ),
        )
        row_box.append(delete_button)

        row.set_child(row_box)
        return row

    def _on_load_research_set_clicked(
        self,
        _button: Gtk.Button,
        set_id: int,
        popover: Gtk.Popover | None = None,
    ) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        self._research_cache_generation += 1
        try:
            research_set = self.client.library.load_research_set_into_cache(set_id, self.client.cache)
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            self._set_status(f"Unable to open Research Set: {exc}")
            return
        self._set_active_research_set(research_set)
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_first=True,
        )
        self._refresh_case_suggestion_index_async(force=True)
        if popover is not None:
            popover.popdown()
        self._set_status(
            f"Opened Research Set '{research_set.name}' with {research_set.item_count} Research Cache item(s)."
        )

    def _on_delete_research_set_clicked(
        self,
        _button: Gtk.Button,
        set_id: int,
        popover: Gtk.Popover | None = None,
    ) -> None:
        if not self.client.library.delete_research_set(set_id):
            self._set_status("Research Set was not found.")
            return
        self._set_status("Deleted Research Set.")
        if self._active_research_set_id == set_id:
            self._set_active_research_set(None)
        self._refresh_research_sets_menu()
        if popover is not None:
            popover.popdown()
            if self._research_sets_menu_button is not None:
                self._research_sets_menu_button.popup()

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

    def _show_external_lookup_window(self, query: str, *, initial_source_url: str = "") -> None:
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

        auto_find_button = Gtk.Button(label="Auto-Find on Scholar")
        auto_find_button.set_tooltip_text(
            "Automatically search Google Scholar and import the first case result"
        )
        auto_find_button.connect("clicked", self._on_external_lookup_auto_find_clicked)
        box.append(auto_find_button)
        self._external_lookup_auto_find_button = auto_find_button

        source_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        source_entry = Gtk.Entry()
        source_entry.set_hexpand(True)
        source_entry.set_placeholder_text("Google Scholar case URL")
        source_entry.set_text(initial_source_url)
        source_row.append(source_entry)
        fetch_button = Gtk.Button(label="Fetch URL")
        fetch_button.connect("clicked", self._on_external_lookup_fetch_clicked, source_entry)
        source_row.append(fetch_button)
        box.append(source_row)
        self._external_lookup_source_entry = source_entry

        import_button = Gtk.Button(label="Import Official Text")
        import_button.connect(
            "clicked",
            self._on_external_lookup_import_clicked,
        )
        box.append(import_button)

        window.set_child(box)
        self._external_lookup_window = window
        self._external_lookup_query = clean_query
        window.present()

    def _on_external_lookup_closed(self, _window: Gtk.Window) -> bool:
        self._external_lookup_window = None
        self._external_lookup_query = ""
        self._external_lookup_auto_find_button = None
        self._external_lookup_source_entry = None
        self._external_lookup_auto_finding = False
        self._external_lookup_auto_query = ""
        self._external_lookup_auto_cache_generation = None
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

    def _on_external_lookup_auto_find_clicked(self, _button: Gtk.Button) -> None:
        self._start_scholar_auto_find(
            self._external_lookup_query,
            fallback_mode=SCHOLAR_FALLBACK_MANUAL_WINDOW,
            auto_import=False,
        )

    def _start_scholar_auto_find(
        self,
        query: str,
        *,
        fallback_mode: str,
        auto_import: bool,
        cache_generation: int | None = None,
    ) -> None:
        clean_query = re.sub(r"\s+", " ", query).strip()
        if self._external_lookup_auto_finding:
            return
        query = clean_query
        if not query.strip():
            self._set_status("No search query available for Auto-Find.")
            return
        self._external_lookup_auto_finding = True
        self._external_lookup_auto_query = query
        self._external_lookup_auto_fallback_mode = fallback_mode
        self._external_lookup_auto_import = auto_import
        self._external_lookup_auto_cache_generation = (
            self._research_cache_generation
            if cache_generation is None
            else cache_generation
        )
        if self._external_lookup_auto_find_button is not None:
            self._external_lookup_auto_find_button.set_sensitive(False)
            self._external_lookup_auto_find_button.set_label("Searching Scholar...")
        self._set_reader_busy(True, "Searching Google Scholar...")
        self._set_status("Auto-searching Google Scholar...")
        thread = threading.Thread(
            target=self._external_lookup_auto_find_worker,
            args=(query,),
            daemon=True,
        )
        thread.start()

    def _external_lookup_auto_find_worker(self, query: str) -> None:
        try:
            result = search_first_case_direct(query)
        except ScholarSearchError as exc:
            GLib.idle_add(self._finish_external_lookup_auto_find, query, None, str(exc))
            return
        GLib.idle_add(self._finish_external_lookup_auto_find, query, result, "")

    def _finish_external_lookup_auto_find(
        self,
        query: str,
        result: ScholarSearchResult | None,
        error: str,
    ) -> bool:
        if query != self._external_lookup_auto_query:
            return False
        self._external_lookup_auto_finding = False
        self._external_lookup_auto_query = ""
        auto_import = self._external_lookup_auto_import
        fallback_mode = self._external_lookup_auto_fallback_mode
        cache_generation = self._external_lookup_auto_cache_generation
        self._external_lookup_auto_import = False
        self._external_lookup_auto_fallback_mode = SCHOLAR_FALLBACK_MANUAL_WINDOW
        self._external_lookup_auto_cache_generation = None
        button = self._external_lookup_auto_find_button
        if button is not None:
            button.set_sensitive(True)
            button.set_label("Auto-Find on Scholar")

        if (
            cache_generation is not None
            and cache_generation != self._research_cache_generation
        ):
            return False

        if result is not None:
            if self._external_lookup_source_entry is not None:
                self._external_lookup_source_entry.set_text(result.url)
            title = f" - {result.title}" if result.title else ""
            action = "importing" if auto_import else "fetching"
            self._set_status(f"Found case on Scholar{title}. {action.capitalize()} text...")
            if auto_import:
                self._start_scholar_auto_import(
                    query,
                    result,
                    fallback_mode,
                    cache_generation,
                )
                return False
            self._set_reader_busy(False)
            # Reuse the existing Import + Fetch flow with the discovered URL.
            self._on_import_official_text(
                None,
                None,
                initial_source_url=result.url,
                fetch_on_present=True,
                fetch_error_fallback_query=query,
            )
            return False

        self._set_reader_busy(False)
        self._handle_scholar_auto_failure(
            query,
            f"Auto-Find could not complete: {error or 'unknown error'}.",
            fallback_mode,
        )
        return False

    def _start_scholar_auto_import(
        self,
        query: str,
        result: ScholarSearchResult,
        fallback_mode: str,
        cache_generation: int | None,
    ) -> None:
        self._set_reader_busy(True, "Importing Scholar text...")
        thread = threading.Thread(
            target=self._scholar_auto_import_worker,
            args=(query, result, fallback_mode, cache_generation),
            daemon=True,
        )
        thread.start()

    def _scholar_auto_import_worker(
        self,
        query: str,
        result: ScholarSearchResult,
        fallback_mode: str,
        cache_generation: int | None,
    ) -> None:
        try:
            webpage = extract_webpage_text(result.url)
        except RuntimeError as exc:
            GLib.idle_add(
                self._finish_scholar_auto_import_error,
                query,
                result.url,
                str(exc),
                fallback_mode,
                cache_generation,
            )
            return
        GLib.idle_add(
            self._finish_scholar_auto_import,
            query,
            webpage,
            fallback_mode,
            cache_generation,
        )

    def _finish_scholar_auto_import_error(
        self,
        query: str,
        source_url: str,
        message: str,
        fallback_mode: str,
        cache_generation: int | None = None,
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        self._set_reader_busy(False)
        self._handle_scholar_auto_failure(
            query,
            f"Scholar found a case, but automatic import failed: {message}",
            fallback_mode,
            initial_source_url=source_url,
        )
        return False

    def _finish_scholar_auto_import(
        self,
        query: str,
        webpage: ExtractedWebpage,
        fallback_mode: str,
        cache_generation: int | None = None,
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        imported_text = clean_imported_opinion_text(webpage.text) or webpage.text
        case_source = "\n".join(part for part in (webpage.title, imported_text) if part)
        try:
            official_citation = validated_import_official_citation(query, case_source)
        except ValueError:
            self._handle_scholar_auto_failure(
                query,
                "Scholar first result did not match the requested official citation.",
                fallback_mode,
                initial_source_url=webpage.url,
            )
            return False
        official_citation = official_citation or self._default_import_official_citation()
        case_name = imported_case_name_from_text(case_source) or self._default_import_case_name()
        if self._save_imported_official_text(
            case_name=case_name,
            official_citation=official_citation,
            imported_text=imported_text,
            source_url=webpage.url,
            failure_prefix="Automatic Scholar import not saved",
            success_status="Imported Scholar official reporter text, saved to Library, and added to Research Cache.",
        ):
            self._close_external_lookup_window()
            return False
        self._handle_scholar_auto_failure(
            query,
            "Scholar did not provide official reporter pagination.",
            fallback_mode,
            initial_source_url=webpage.url,
        )
        return False

    def _handle_scholar_auto_failure(
        self,
        query: str,
        message: str,
        fallback_mode: str,
        *,
        initial_source_url: str = "",
    ) -> None:
        self._set_reader_busy(False)
        if fallback_mode == SCHOLAR_FALLBACK_MANUAL_WINDOW:
            self._set_status(f"{message} Open Scholar manually and paste the case URL.")
            if query.strip():
                self._show_external_lookup_window(query, initial_source_url=initial_source_url)
            return
        if fallback_mode == SCHOLAR_FALLBACK_TRANSIENT_NOTICE:
            self._set_status("Transient view only: official reporter pagination was not found.")
            self._show_official_pagination_not_found_notice(can_view_current=True)
            return
        self._set_status(OFFICIAL_PAGINATION_NOT_FOUND_ONLY_MESSAGE)
        self._show_official_pagination_not_found_notice(can_view_current=False)

    def _show_official_pagination_not_found_notice(self, *, can_view_current: bool) -> None:
        message = (
            OFFICIAL_PAGINATION_NOT_FOUND_MESSAGE
            if can_view_current
            else OFFICIAL_PAGINATION_NOT_FOUND_ONLY_MESSAGE
        )
        window = Gtk.Window(title=OFFICIAL_PAGINATION_NOT_FOUND_TITLE)
        window.set_transient_for(self)
        window.set_modal(True)
        window.set_default_size(460, 160)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(16)
        box.set_margin_end(16)

        heading = Gtk.Label(label=OFFICIAL_PAGINATION_NOT_FOUND_TITLE, xalign=0)
        heading.add_css_class("heading")
        box.append(heading)

        label = Gtk.Label(label=message, xalign=0)
        label.set_wrap(True)
        box.append(label)

        ok_button = Gtk.Button(label="OK")
        ok_button.set_halign(Gtk.Align.END)
        ok_button.connect("clicked", lambda _button: window.close())
        box.append(ok_button)

        window.set_child(box)
        window.present()

    def _default_import_case_name(self) -> str:
        if self._selected_cluster is not None:
            title = cluster_short_title(self._selected_cluster)
            citation = normalize_official_citation(title)
            return "" if citation and citation == title else title
        return imported_case_name_from_text(self._official_search_query())

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
        fetch_error_fallback_query: str = "",
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
            window,
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
                window,
                case_name_entry,
                citation_entry,
                source_entry,
                text_buffer,
                fetch_error_fallback_query,
            )
        return True

    def _on_import_fetch_url_clicked(
        self,
        button: Gtk.Button,
        window: Gtk.Window,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
        fetch_error_fallback_query: str = "",
    ) -> None:
        url = source_entry.get_text().strip()
        button.set_sensitive(False)
        self._set_status("Fetching URL...")
        thread = threading.Thread(
            target=self._import_fetch_url_worker,
            args=(
                url,
                button,
                window,
                case_name_entry,
                citation_entry,
                source_entry,
                text_buffer,
                fetch_error_fallback_query,
            ),
            daemon=True,
        )
        thread.start()

    def _import_fetch_url_worker(
        self,
        url: str,
        button: Gtk.Button,
        window: Gtk.Window,
        case_name_entry: Gtk.Entry,
        citation_entry: Gtk.Entry,
        source_entry: Gtk.Entry,
        text_buffer: Gtk.TextBuffer,
        fetch_error_fallback_query: str,
    ) -> None:
        try:
            webpage = extract_webpage_text(url)
        except RuntimeError as exc:
            GLib.idle_add(
                self._finish_import_fetch_url_error,
                button,
                window,
                str(exc),
                fetch_error_fallback_query,
                url,
            )
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

    def _finish_import_fetch_url_error(
        self,
        button: Gtk.Button,
        window: Gtk.Window,
        message: str,
        fallback_query: str = "",
        fallback_source_url: str = "",
    ) -> bool:
        button.set_sensitive(True)
        if fallback_query.strip():
            self._set_reader_busy(False)
            self._set_status("Scholar result needs manual review. Paste or choose a case URL.")
            self._show_external_lookup_window(
                fallback_query,
                initial_source_url=fallback_source_url,
            )
            window.close()
        else:
            self._set_reader_busy(False)
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
        if not self._save_imported_official_text(
            case_name=case_name,
            official_citation=official_citation,
            imported_text=pasted_text,
            source_url=source_entry.get_text().strip(),
            failure_prefix="Import not saved",
            success_status="Imported official reporter text, saved to Library, and added to Research Cache.",
        ):
            return
        self._close_external_lookup_window()
        window.close()

    def _save_imported_official_text(
        self,
        *,
        case_name: str,
        official_citation: str,
        imported_text: str,
        source_url: str,
        failure_prefix: str,
        success_status: str,
    ) -> bool:
        imported_text = clean_imported_opinion_text(imported_text)
        if not imported_text:
            self._set_status(f"{failure_prefix}: imported text was empty after cleanup.")
            return False
        try:
            cluster = build_external_import_cluster(
                case_name=case_name,
                official_citation=official_citation,
                imported_text=imported_text,
                source_url=source_url,
            )
        except ValueError as exc:
            self._set_status(str(exc))
            return False
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            self._set_status("Selected case has no cluster id.")
            return False
        text_field = "html_with_citations" if re.search(r"<[a-zA-Z][^>]*>", imported_text) else "plain_text"
        opinion = {
            "id": f"official-import-{cluster_id}",
            "cluster_id": cluster_id,
            text_field: imported_text,
            "source_url": source_url,
            "source_type": "user_imported_official_text",
        }
        display = opinion_display_text(opinion)
        quality = official_pagination_quality(cluster, [display])
        if not quality.eligible:
            self._set_status(f"{failure_prefix}: {quality.reason}")
            return False
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
        self._refresh_case_suggestion_index_async(force=True)
        self._reader_has_official_pagination = True
        self._reader_pagination_mode = READER_PAGINATION_OFFICIAL
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._set_reader_header(
            self._case_header_text(cluster),
            self._case_header_citation(cluster),
            cluster,
        )
        self._set_reader_text(display.text, display.page_markers)
        self._set_status(success_status)
        return True

    def _on_lookup_clicked(self, _widget: Gtk.Widget) -> None:
        entry_text = self.citation_entry.get_text().strip()
        if not entry_text:
            self._set_status("Enter a citation.")
            return
        citation = self._lookup_text_from_entry(entry_text)
        case_number = normalize_case_number(citation)
        if case_number and citation.strip().casefold() == case_number.casefold():
            self._start_case_number_lookup(case_number)
            return
        if parse_statute_citation(citation) is not None:
            self._start_statute_lookup(citation)
            return
        if parse_rule_citation(citation) is not None:
            self._start_rule_lookup(citation)
            return
        self._start_lookup(citation)

    def _start_case_number_lookup(self, case_number: str) -> None:
        clean_case_number = normalize_case_number(case_number)
        if not clean_case_number:
            self._set_status("Enter a California appellate case number.")
            return
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        self._last_lookup_text = clean_case_number
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._set_status(f"Looking up case number {clean_case_number}...")
        self._set_reader_header("")
        self._set_reader_busy(True, "Looking up case number...")
        self.reader_buffer.set_text("Loading...")
        cache_generation = self._research_cache_generation
        generation = self._case_load_generation + 1
        thread = threading.Thread(
            target=self._case_number_lookup_worker,
            args=(clean_case_number, generation, cache_generation),
            daemon=True,
        )
        thread.start()

    def _case_number_lookup_worker(
        self,
        case_number: str,
        generation: int,
        cache_generation: int,
    ) -> None:
        try:
            page = self.client.search_cases(case_number, page_size=1)
            if page.results:
                result = page.results[0]
                cluster = self.client.fetch_url(
                    f"/api/rest/v4/clusters/{result.cluster_id}/",
                    kind="clusters",
                )
                cluster = {**cluster, "docket_number": case_number}
                GLib.idle_add(
                    self._finish_case_number_cluster_lookup,
                    cluster,
                    case_number,
                    cache_generation,
                )
                return
            slip = self.client.fetch_slip_opinion(case_number)
            cluster = {
                "id": f"slip-{case_number}",
                "case_name": case_number,
                "case_name_short": case_number,
                "precedential_status": "Published",
                "docket": {"docket_number": case_number},
            }
            cluster.update(slip_metadata_from_display(slip.display))
            GLib.idle_add(
                self._finish_case_number_direct_slip_lookup,
                cluster,
                slip.display,
                slip.source_url,
                slip.case_number,
                cache_generation,
            )
        except (CourtListenerError, SlipOpinionError, ValueError, OSError) as exc:
            GLib.idle_add(self._apply_error, f"Unable to open {case_number}: {exc}")

    def _finish_case_number_direct_slip_lookup(
        self,
        cluster: dict[str, Any],
        display: DisplayText,
        source_url: str,
        case_number: str,
        cache_generation: int,
    ) -> bool:
        if cache_generation != self._research_cache_generation:
            return False
        generation = self._begin_case_load(cluster)
        payload = build_case_reader_payload(
            cluster,
            [display],
            generation=generation,
            cache_generation=cache_generation,
            opinion_ids=(),
            opinion_source="California Courts",
            pagination_mode=READER_PAGINATION_SLIP,
            slip_source_url=source_url,
            slip_case_number=case_number,
        )
        return self._start_reader_payload_render(payload)

    def _finish_case_number_cluster_lookup(
        self,
        cluster: dict[str, Any],
        case_number: str,
        cache_generation: int,
    ) -> bool:
        if cache_generation != self._research_cache_generation:
            return False
        clean_case_number = normalize_case_number(case_number) or case_number
        if clean_case_number:
            cluster = {**cluster, "docket_number": clean_case_number}
        cluster_id = self.client.cache.upsert_cluster(cluster) or cluster_id_from_cluster(cluster)
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id=cluster_id,
            select_first=True,
            suppress_selection_lookup=True,
        )
        self._set_status(f"Opened case number {case_number}.")
        self._refresh_case_suggestion_index_async(force=True)
        generation = self._begin_case_load(cluster)
        thread = threading.Thread(
            target=self._case_worker,
            args=(cluster, generation, cache_generation, True),
            daemon=True,
        )
        thread.start()
        return False

    def _start_statute_lookup(self, citation: str) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        self._last_lookup_text = citation.strip()
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._set_status(f"Looking up {citation}...")
        self._set_reader_header("")
        self._set_reader_busy(True, "Looking up statute...")
        self.reader_buffer.set_text("Loading...")
        cache_generation = self._research_cache_generation
        self._start_background_worker(
            lambda: self.client.lookup_statute(citation, populate_research_cache=False),
            on_success=lambda statute: self._apply_statute_lookup_result(
                statute,
                cache_generation,
            ),
            on_error=lambda exc: self._apply_error(str(exc)),
            handled_exceptions=(LegInfoError, ValueError),
        )

    def _open_cached_statute(self, statute: dict[str, Any]) -> None:
        citation = str(statute.get("citation") or "").strip()
        if not citation:
            return
        self._last_lookup_text = citation
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._open_statute_in_reader(statute)

    def _apply_statute_lookup_result(
        self,
        statute: dict[str, Any],
        cache_generation: int | None = None,
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        statute_id = self.client.cache.upsert_statute(statute) or str(
            statute.get("statute_id") or ""
        ).strip()
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_statute_id=statute_id,
            suppress_selection_lookup=True,
        )
        self._refresh_case_suggestion_index_async(force=True)
        self._open_statute_in_reader(statute)
        source = self.client.last_lookup_source or "Live source"
        self._set_status(f"{source}: opened {statute.get('citation') or statute_id}.")
        return False

    def _start_rule_lookup(self, citation: str) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        self._last_lookup_text = citation.strip()
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._set_status(f"Looking up {citation}...")
        self._set_reader_header("")
        self._set_reader_busy(True, "Looking up rule...")
        self.reader_buffer.set_text("Loading...")
        cache_generation = self._research_cache_generation
        self._start_background_worker(
            lambda: self.client.lookup_rule(citation, populate_research_cache=False),
            on_success=lambda rule: self._apply_rule_lookup_result(rule, cache_generation),
            on_error=lambda exc: self._apply_error(str(exc)),
            handled_exceptions=(CaliforniaRulesError, ValueError),
        )

    def _open_cached_rule(self, rule: dict[str, Any]) -> None:
        citation = str(rule.get("citation") or "").strip()
        if not citation:
            return
        self._last_lookup_text = citation
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._open_rule_in_reader(rule)

    def _open_agent_answer(self, answer_entry: dict[str, Any]) -> None:
        answer_id = str(answer_entry.get("answer_id") or "").strip()
        if not answer_id:
            return
        answer = self.client.cache.read_agent_answer(answer_id)
        if not isinstance(answer, dict):
            self._set_status("Saved answer was not found in Research Cache.")
            return
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        set_position_key = getattr(self, "_set_reader_position_key", None)
        if set_position_key is not None:
            set_position_key("agent_answer", answer_id)
        title = str(answer.get("title") or answer_entry.get("title") or "Saved agent answer")
        text = str(answer.get("text") or "").strip()
        self._selected_cluster = None
        self._selected_statute = None
        self._selected_rule = None
        self._selected_agent_answer = answer
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._reader_page_markers = []
        self._set_reader_busy(False)
        self._set_reader_header(title)
        self._set_reader_text(text, apply_markdown=True)
        self._set_status(f"Loaded saved answer: {title}")

    def _apply_rule_lookup_result(
        self,
        rule: dict[str, Any],
        cache_generation: int | None = None,
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        rule_id = self.client.cache.upsert_rule(rule) or str(rule.get("rule_id") or "").strip()
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_rule_id=rule_id,
            suppress_selection_lookup=True,
        )
        self._refresh_case_suggestion_index_async(force=True)
        self._open_rule_in_reader(rule)
        source = self.client.last_lookup_source or "Live source"
        self._set_status(f"{source}: opened {rule.get('citation') or rule_id}.")
        return False

    def _start_lookup(
        self,
        citation: str,
        *,
        link: CitedCaseLink | None = None,
        populate_research_cache: bool = True,
    ) -> None:
        case_number = normalize_case_number(citation)
        if case_number and citation.strip().casefold() == case_number.casefold():
            self._start_case_number_lookup(case_number)
            return
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        clear_position_key = getattr(self, "_clear_reader_position_key", None)
        if clear_position_key is not None:
            clear_position_key()
        lookup_context = self._lookup_context_text(citation, link)
        self._last_lookup_text = lookup_context
        self._pending_auto_scholar_cluster_id = ""
        self._pending_auto_scholar_query = ""
        self._hide_case_completion()
        self._set_status(f"Looking up {lookup_context or citation}...")
        self._set_reader_header("")
        self._set_reader_busy(True, "Looking up...")
        self.reader_buffer.set_text("Loading...")
        cache_generation = self._research_cache_generation
        self._start_background_worker(
            lambda: self._lookup_worker_result(citation, link, cache_generation, populate_research_cache),
            on_success=self._finish_lookup_worker_result,
        )

    def _lookup_context_text(self, citation: str, link: CitedCaseLink | None = None) -> str:
        if link is not None:
            return (link.full_text or link.lookup_text).strip()
        return citation.strip()

    def _scholar_lookup_query(self, citation: str, link: CitedCaseLink | None = None) -> str:
        if link is not None and link.lookup_text.strip():
            return link.lookup_text.strip()
        return citation.strip()

    def _set_formatted_clipboard(
        self,
        citation: FormattedCitation,
        failure_message: str,
    ) -> bool:
        display = Gdk.Display.get_default()
        if display is None:
            self._set_status("Could not access clipboard.")
            return False
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
            self._set_status(failure_message)
            return False
        return True

    def _copy_formatted_citation(self, citation: FormattedCitation) -> None:
        if not self._set_formatted_clipboard(
            citation,
            "Could not copy official citation.",
        ):
            return
        self._set_status("Official citation copied.")

    def _lookup_worker(
        self,
        citation: str,
        link: CitedCaseLink | None = None,
        cache_generation: int = 0,
        populate_research_cache: bool = True,
    ) -> None:
        result = self._lookup_worker_result(citation, link, cache_generation, populate_research_cache)
        GLib.idle_add(self._finish_lookup_worker_result, result)

    def _lookup_worker_result(
        self,
        citation: str,
        link: CitedCaseLink | None = None,
        cache_generation: int = 0,
        populate_research_cache: bool = True,
    ) -> tuple[Any, ...]:
        try:
            result = self.client.lookup_citation(
                citation,
                populate_research_cache=False,
            )
            raw_clusters = self.client.clusters_from_lookup(result)
            shown_clusters = self._lookup_clusters_for_display(raw_clusters, link)
            if link is not None and shown_clusters:
                shown_clusters = shown_clusters[:1]
            status = self._lookup_status_text(result, raw_clusters, shown_clusters)
            return (
                "success",
                result,
                shown_clusters,
                status,
                self._lookup_context_text(citation, link),
                cache_generation,
                populate_research_cache,
                self._scholar_lookup_query(citation, link),
            )
        except CourtListenerError:
            return (
                "fallback",
                self._scholar_lookup_query(citation, link),
                cache_generation,
            )
        except ValueError as exc:
            return ("error", str(exc))

    def _finish_lookup_worker_result(self, payload: tuple[Any, ...]) -> bool:
        kind = str(payload[0] if payload else "")
        if kind == "success":
            return self._apply_lookup_result(*payload[1:])
        if kind == "fallback":
            return self._fallback_lookup_to_scholar(
                str(payload[1] if len(payload) > 1 else ""),
                int(payload[2]) if len(payload) > 2 else None,
            )
        if kind == "error":
            return self._apply_error(str(payload[1] if len(payload) > 1 else "Lookup failed."))
        return False

    def _lookup_clusters_for_display(
        self,
        raw_clusters: list[dict[str, Any]],
        link: CitedCaseLink | None = None,
    ) -> list[dict[str, Any]]:
        clusters = dedupe_case_clusters(raw_clusters)
        if link is None or not link.case_name.strip():
            return clusters
        repaired: list[dict[str, Any]] = []
        for cluster in clusters:
            repaired.append(repair_reporter_only_cluster_name(cluster, link.case_name) or cluster)
        return repaired

    def _fallback_lookup_to_scholar(
        self,
        citation: str,
        cache_generation: int | None = None,
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        self._set_reader_header("")
        self.reader_buffer.set_text("")
        self._set_reader_busy(True, "Searching Google Scholar...")
        self._set_status("CourtListener lookup unavailable. Searching Google Scholar...")
        self._start_scholar_auto_find(
            citation,
            fallback_mode=SCHOLAR_FALLBACK_NOTICE_ONLY,
            auto_import=True,
            cache_generation=cache_generation,
        )
        return False

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
        statutes = self.client.cached_statutes()
        rules = self.client.cached_rules()
        self._set_sidebar_authorities(clusters, statutes, rules)
        self._refresh_case_suggestion_index_async(force=True)
        count = (
            len(clusters)
            + len(statutes)
            + len(rules)
            + len(self.client.cache.list_agent_answer_entries())
        )
        if count:
            self._set_status(f"{count} Research Cache item(s).")
        else:
            self._set_reader_header("")

    def _set_sidebar_clusters(
        self,
        clusters: list[dict[str, Any]],
        *,
        select_cluster_id: str = "",
        select_first: bool = False,
        suppress_selection_lookup: bool = False,
    ) -> None:
        self._set_sidebar_authorities(
            clusters,
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_cluster_id=select_cluster_id,
            select_first=select_first,
            suppress_selection_lookup=suppress_selection_lookup,
        )

    def _set_sidebar_authorities(
        self,
        clusters: list[dict[str, Any]],
        statutes: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        *,
        select_cluster_id: str = "",
        select_statute_id: str = "",
        select_rule_id: str = "",
        select_agent_answer_id: str = "",
        select_first: bool = False,
        suppress_selection_lookup: bool = False,
    ) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        self._clusters = clusters
        self._statutes = statutes
        self._rules = rules
        self._agent_answers = self.client.cache.list_agent_answer_entries()
        self._refresh_active_research_set_from_cache()
        self._selected_cluster = None
        self._selected_statute = None
        self._selected_rule = None
        self._selected_agent_answer = None
        while row := self.case_list.get_row_at_index(0):
            self.case_list.remove(row)
        selected_row: Gtk.ListBoxRow | None = None
        case_entries = {
            str(entry.get("cluster_id") or "").strip(): entry
            for entry in self.client.cache.list_case_entries()
        }
        statute_entries = {
            str(entry.get("statute_id") or "").strip(): entry
            for entry in self.client.cache.list_statute_entries()
        }
        rule_entries = {
            str(entry.get("rule_id") or "").strip(): entry
            for entry in self.client.cache.list_rule_entries()
        }
        answer_entries = {
            str(entry.get("answer_id") or "").strip(): entry
            for entry in self._agent_answers
        }
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
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            actions_box.set_valign(Gtk.Align.START)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic")
            remove_button.add_css_class("flat")
            remove_button.add_css_class("case-row-icon-button")
            remove_button.add_css_class("cache-row-remove-button")
            remove_button.set_tooltip_text("Remove from Research Cache")
            remove_button.set_sensitive(bool(cluster_id))
            remove_button.connect("clicked", self._on_remove_cached_case_clicked, cluster_id, cluster)
            actions_box.append(remove_button)
            row_box.append(actions_box)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title_text, citation_text = self._research_cache_case_row_text(cluster)
            title = Gtk.Label(label=title_text, xalign=0)
            title.set_wrap(True)
            text_box.append(title)
            if citation_text:
                citation = Gtk.Label(label=citation_text, xalign=0)
                citation.add_css_class("dim-label")
                citation.set_wrap(True)
                text_box.append(citation)
            row_box.append(text_box)
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make case available to Cache Agent")
            check.set_active(self.client.cache.is_agent_selected(cluster_id))
            check.connect("toggled", self._on_agent_case_toggled, cluster_id)
            row_box.append(check)
            row.set_child(row_box)
            row._open_law_lens_cluster_index = index
            row._open_law_lens_authority_type = "case"
            row._open_law_lens_authority_id = cluster_id
            row._open_law_lens_cache_section = "authority"
            row._open_law_lens_cache_sort_key = self._research_cache_row_sort_key(
                case_entries.get(cluster_id, {}),
                title_text,
                citation_text,
                "case",
                cluster_id,
            )
            self.case_list.append(row)
            if select_cluster_id and cluster_id_from_cluster(cluster) == select_cluster_id:
                selected_row = row
        for index, statute in enumerate(statutes):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row.add_css_class("case-cache-row")
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            statute_id = str(statute.get("statute_id") or "").strip()
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            actions_box.set_valign(Gtk.Align.START)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic")
            remove_button.add_css_class("flat")
            remove_button.add_css_class("case-row-icon-button")
            remove_button.add_css_class("cache-row-remove-button")
            remove_button.set_tooltip_text("Remove from Research Cache")
            remove_button.set_sensitive(bool(statute_id))
            remove_button.connect("clicked", self._on_remove_cached_statute_clicked, statute_id, statute)
            actions_box.append(remove_button)
            row_box.append(actions_box)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title = Gtk.Label(label=str(statute.get("title") or "Untitled statute"), xalign=0)
            title.set_wrap(True)
            text_box.append(title)
            citation_text = str(statute.get("citation") or "").strip()
            if citation_text:
                citation = Gtk.Label(label=citation_text, xalign=0)
                citation.add_css_class("dim-label")
                citation.set_wrap(True)
                text_box.append(citation)
            row_box.append(text_box)
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make statute available to Cache Agent")
            check.set_active(self.client.cache.is_statute_agent_selected(statute_id))
            check.connect("toggled", self._on_agent_statute_toggled, statute_id)
            row_box.append(check)
            row.set_child(row_box)
            row._open_law_lens_statute_index = index
            row._open_law_lens_authority_type = "statute"
            row._open_law_lens_authority_id = statute_id
            row._open_law_lens_cache_section = "authority"
            row._open_law_lens_cache_sort_key = self._research_cache_row_sort_key(
                statute_entries.get(statute_id, {}),
                str(statute.get("title") or "Untitled statute"),
                citation_text,
                "statute",
                statute_id,
            )
            self.case_list.append(row)
            if select_statute_id and statute_id == select_statute_id:
                selected_row = row
        for index, rule in enumerate(rules):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row.add_css_class("case-cache-row")
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            rule_id = str(rule.get("rule_id") or "").strip()
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            actions_box.set_valign(Gtk.Align.START)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic")
            remove_button.add_css_class("flat")
            remove_button.add_css_class("case-row-icon-button")
            remove_button.add_css_class("cache-row-remove-button")
            remove_button.set_tooltip_text("Remove from Research Cache")
            remove_button.set_sensitive(bool(rule_id))
            remove_button.connect("clicked", self._on_remove_cached_rule_clicked, rule_id, rule)
            actions_box.append(remove_button)
            row_box.append(actions_box)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title = Gtk.Label(label=str(rule.get("title") or "Untitled rule"), xalign=0)
            title.set_wrap(True)
            text_box.append(title)
            citation_text = str(rule.get("citation") or "").strip()
            if citation_text:
                citation = Gtk.Label(label=citation_text, xalign=0)
                citation.add_css_class("dim-label")
                citation.set_wrap(True)
                text_box.append(citation)
            row_box.append(text_box)
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make rule available to Cache Agent")
            check.set_active(self.client.cache.is_rule_agent_selected(rule_id))
            check.connect("toggled", self._on_agent_rule_toggled, rule_id)
            row_box.append(check)
            row.set_child(row_box)
            row._open_law_lens_rule_index = index
            row._open_law_lens_authority_type = "rule"
            row._open_law_lens_authority_id = rule_id
            row._open_law_lens_cache_section = "authority"
            row._open_law_lens_cache_sort_key = self._research_cache_row_sort_key(
                rule_entries.get(rule_id, {}),
                str(rule.get("title") or "Untitled rule"),
                citation_text,
                "rule",
                rule_id,
            )
            self.case_list.append(row)
            if select_rule_id and rule_id == select_rule_id:
                selected_row = row
        if self._agent_answers:
            header_row = Gtk.ListBoxRow()
            header_row.set_selectable(False)
            header_row.set_activatable(False)
            header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            header_box.set_margin_top(12)
            header_box.set_margin_bottom(2)
            header_box.set_margin_start(8)
            header_box.set_margin_end(8)
            header = Gtk.Label(label="Saved Answers", xalign=0)
            header.add_css_class("dim-label")
            header_box.append(header)
            header_row.set_child(header_box)
            header_row._open_law_lens_cache_section = "agent_answer_header"
            header_row._open_law_lens_cache_sort_key = ("", "", "", "", "")
            self.case_list.append(header_row)
        for index, answer_entry in enumerate(self._agent_answers):
            row = Gtk.ListBoxRow()
            row.set_selectable(True)
            row.set_activatable(True)
            row.add_css_class("case-cache-row")
            row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            row_box.set_margin_top(8)
            row_box.set_margin_bottom(8)
            row_box.set_margin_start(8)
            row_box.set_margin_end(8)
            answer_id = str(answer_entry.get("answer_id") or "").strip()
            actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
            actions_box.set_valign(Gtk.Align.START)
            remove_button = Gtk.Button(icon_name="user-trash-symbolic")
            remove_button.add_css_class("flat")
            remove_button.add_css_class("case-row-icon-button")
            remove_button.add_css_class("cache-row-remove-button")
            remove_button.set_tooltip_text("Remove from Research Cache")
            remove_button.set_sensitive(bool(answer_id))
            remove_button.connect("clicked", self._on_remove_agent_answer_clicked, answer_id, answer_entry)
            actions_box.append(remove_button)
            row_box.append(actions_box)
            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            text_box.set_hexpand(True)
            title_text = str(answer_entry.get("title") or "Saved agent answer")
            title = Gtk.Label(label=title_text, xalign=0)
            title.set_wrap(True)
            text_box.append(title)
            mode_text = self._agent_answer_mode_label(str(answer_entry.get("mode") or ""))
            subtitle = Gtk.Label(label=mode_text, xalign=0)
            subtitle.add_css_class("dim-label")
            subtitle.set_wrap(True)
            text_box.append(subtitle)
            row_box.append(text_box)
            check = Gtk.CheckButton()
            check.add_css_class("neutral-agent-check")
            check.set_valign(Gtk.Align.START)
            check.set_tooltip_text("Make saved answer available to Cache Agent")
            check.set_active(self.client.cache.is_agent_answer_selected(answer_id))
            check.connect("toggled", self._on_agent_answer_toggled, answer_id)
            row_box.append(check)
            row.set_child(row_box)
            row._open_law_lens_agent_answer_index = index
            row._open_law_lens_authority_type = "agent_answer"
            row._open_law_lens_authority_id = answer_id
            row._open_law_lens_cache_section = "agent_answer"
            row._open_law_lens_cache_sort_key = self._research_cache_row_sort_key(
                answer_entries.get(answer_id, {}),
                title_text,
                mode_text,
                "agent_answer",
                answer_id,
            )
            self.case_list.append(row)
            if select_agent_answer_id and answer_id == select_agent_answer_id:
                selected_row = row
        if selected_row is None and select_first:
            selected_row = self.case_list.get_row_at_index(0)
        if selected_row is not None:
            old_suppress = self._suppress_sidebar_selection_lookup
            self._suppress_sidebar_selection_lookup = suppress_selection_lookup
            try:
                self.case_list.select_row(selected_row)
            finally:
                self._suppress_sidebar_selection_lookup = old_suppress

    def _research_cache_row_sort_key(
        self,
        entry: dict[str, Any],
        title: str,
        citation: str,
        authority_type: str,
        authority_id: str,
    ) -> tuple[str, str, str, str, str]:
        loaded_at = str(entry.get("loaded_at") or entry.get("added_at") or "")
        return (
            loaded_at,
            title.casefold(),
            citation.casefold(),
            authority_type,
            authority_id,
        )

    def _sort_research_cache_rows(
        self,
        row_a: Gtk.ListBoxRow,
        row_b: Gtk.ListBoxRow,
        _user_data: Any = None,
    ) -> int:
        section_order = {
            "authority": 0,
            "agent_answer_header": 1,
            "agent_answer": 2,
        }
        section_a = section_order.get(getattr(row_a, "_open_law_lens_cache_section", "authority"), 0)
        section_b = section_order.get(getattr(row_b, "_open_law_lens_cache_section", "authority"), 0)
        if section_a != section_b:
            return -1 if section_a < section_b else 1
        key_a = getattr(row_a, "_open_law_lens_cache_sort_key", ("", "", "", "", ""))
        key_b = getattr(row_b, "_open_law_lens_cache_sort_key", ("", "", "", "", ""))
        if key_a[0] != key_b[0]:
            return -1 if key_a[0] > key_b[0] else 1
        if key_a[1:] == key_b[1:]:
            return 0
        return -1 if key_a[1:] < key_b[1:] else 1

    @staticmethod
    def _agent_answer_mode_label(mode: str) -> str:
        if mode == AGENT_MODE_APPEAL:
            return "Issue assessment answer"
        if mode == AGENT_MODE_CASE:
            return "Research Cache answer"
        return "General legal answer"

    def _on_agent_case_toggled(self, button: Gtk.CheckButton, cluster_id: str) -> None:
        self.client.cache.set_agent_selected(cluster_id, button.get_active())

    def _on_agent_statute_toggled(self, button: Gtk.CheckButton, statute_id: str) -> None:
        self.client.cache.set_statute_agent_selected(statute_id, button.get_active())

    def _on_agent_rule_toggled(self, button: Gtk.CheckButton, rule_id: str) -> None:
        self.client.cache.set_rule_agent_selected(rule_id, button.get_active())

    def _on_agent_answer_toggled(self, button: Gtk.CheckButton, answer_id: str) -> None:
        self.client.cache.set_agent_answer_selected(answer_id, button.get_active())

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
            clear_position_key = getattr(self, "_clear_reader_position_key", None)
            if clear_position_key is not None:
                clear_position_key()
            self._reader_text = ""
            self._set_reader_header("")
            self.reader_buffer.set_text("")
            self._set_reader_busy(False)
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id="" if removed_selected else current_cluster_id,
        )
        self._refresh_case_suggestion_index_async(force=True)
        self._set_status(f"Removed {title} from Research Cache. Library preserved.")

    def _on_remove_cached_statute_clicked(
        self,
        _button: Gtk.Button,
        statute_id: str,
        statute: dict[str, Any],
    ) -> None:
        if not statute_id:
            self._set_status("Could not remove statute from Research Cache.")
            return
        current_statute_id = str((self._selected_statute or {}).get("statute_id") or "")
        removed_selected = current_statute_id == statute_id
        title = str(statute.get("title") or statute_id)
        if not self.client.cache.remove_statute(statute_id):
            self._set_status("Statute was not found in Research Cache.")
            return
        if removed_selected:
            self._selected_statute = None
            clear_position_key = getattr(self, "_clear_reader_position_key", None)
            if clear_position_key is not None:
                clear_position_key()
            self._reader_text = ""
            self._set_reader_header("")
            self.reader_buffer.set_text("")
            self._set_reader_busy(False)
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_statute_id="" if removed_selected else current_statute_id,
        )
        self._refresh_case_suggestion_index_async(force=True)
        self._set_status(f"Removed {title} from Research Cache. Library preserved.")

    def _on_remove_cached_rule_clicked(
        self,
        _button: Gtk.Button,
        rule_id: str,
        rule: dict[str, Any],
    ) -> None:
        if not rule_id:
            self._set_status("Could not remove rule from Research Cache.")
            return
        current_rule_id = str((self._selected_rule or {}).get("rule_id") or "")
        removed_selected = current_rule_id == rule_id
        title = str(rule.get("title") or rule_id)
        if not self.client.cache.remove_rule(rule_id):
            self._set_status("Rule was not found in Research Cache.")
            return
        if removed_selected:
            self._selected_rule = None
            clear_position_key = getattr(self, "_clear_reader_position_key", None)
            if clear_position_key is not None:
                clear_position_key()
            self._reader_text = ""
            self._set_reader_header("")
            self.reader_buffer.set_text("")
            self._set_reader_busy(False)
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
            select_rule_id="" if removed_selected else current_rule_id,
        )
        self._refresh_case_suggestion_index_async(force=True)
        self._set_status(f"Removed {title} from Research Cache. Library preserved.")

    def _on_remove_agent_answer_clicked(
        self,
        _button: Gtk.Button,
        answer_id: str,
        answer_entry: dict[str, Any],
    ) -> None:
        if not answer_id:
            self._set_status("Could not remove saved answer from Research Cache.")
            return
        current_answer_id = str((self._selected_agent_answer or {}).get("answer_id") or "")
        removed_selected = current_answer_id == answer_id
        title = str(answer_entry.get("title") or "Saved agent answer")
        if not self.client.cache.remove_agent_answer(answer_id):
            self._set_status("Saved answer was not found in Research Cache.")
            return
        if removed_selected:
            self._selected_agent_answer = None
            clear_position_key = getattr(self, "_clear_reader_position_key", None)
            if clear_position_key is not None:
                clear_position_key()
            self._reader_text = ""
            self._set_reader_header("")
            self.reader_buffer.set_text("")
            self._set_reader_busy(False)
        self._set_sidebar_authorities(
            self.client.cached_clusters(),
            self.client.cached_statutes(),
            self.client.cached_rules(),
        )
        self._set_status(f"Removed {title} from Research Cache. Library preserved.")

    def _apply_lookup_result(
        self,
        _result: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        status: str,
        citation: str = "",
        cache_generation: int | None = None,
        populate_research_cache: bool = True,
        scholar_query: str = "",
    ) -> bool:
        if cache_generation is not None and cache_generation != self._research_cache_generation:
            return False
        select_cluster_id = cluster_id_from_cluster(clusters[0]) if clusters else ""
        if not populate_research_cache and not clusters:
            self._pending_auto_scholar_cluster_id = ""
            self._pending_auto_scholar_query = ""
            self._set_reader_header("")
            self.reader_buffer.set_text(status)
            self._set_reader_busy(False)
            self._set_status(status)
            return False
        if clusters and not populate_research_cache:
            self._pending_auto_scholar_cluster_id = ""
            self._pending_auto_scholar_query = ""
            generation = self._begin_case_load(clusters[0])
            thread = threading.Thread(
                target=self._case_worker,
                args=(clusters[0], generation, -1),
                daemon=True,
            )
            thread.start()
            return False
        if clusters:
            self._pending_auto_scholar_cluster_id = select_cluster_id
            self._pending_auto_scholar_query = (scholar_query or citation).strip()
            for cluster in clusters:
                self.client.cache.upsert_cluster(cluster)
        else:
            self._pending_auto_scholar_cluster_id = ""
            self._pending_auto_scholar_query = ""
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id=select_cluster_id,
            select_first=bool(clusters),
        )
        self._set_status(status)
        self._refresh_case_suggestion_index_async(force=True)
        if clusters:
            if self.case_list.get_selected_row() is None:
                first = self.case_list.get_row_at_index(0)
                if first:
                    self.case_list.select_row(first)
        else:
            self._set_reader_header("")
            query = (scholar_query or citation).strip()
            if query:
                self.reader_buffer.set_text("")
                self._set_reader_busy(True, "Searching Google Scholar...")
                self._set_status("No CourtListener match shown. Searching Google Scholar...")
                self._start_scholar_auto_find(
                    query,
                    fallback_mode=SCHOLAR_FALLBACK_NOTICE_ONLY,
                    auto_import=True,
                    cache_generation=cache_generation,
                )
            else:
                self._set_reader_busy(False)
                self.reader_buffer.set_text(status)
        return False

    def _apply_error(self, message: str) -> bool:
        self._set_reader_busy(False)
        self._set_status(message)
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._set_reader_header("")
        self.reader_buffer.set_text(message)
        return False

    @staticmethod
    def _research_cache_case_row_text(cluster: dict[str, Any]) -> tuple[str, str]:
        title_text = cluster_short_title(cluster)
        formatted_citation = format_official_california_citation(cluster)
        if formatted_citation is None:
            status = str(cluster.get("precedential_status") or cluster.get("status") or "").strip()
            if status == "Published":
                formatted_citation = format_published_slip_opinion_citation(cluster)
        if formatted_citation is None:
            return title_text, ""
        title_prefix = f"{title_text} "
        citation_text = formatted_citation.plain_text.removeprefix(title_prefix).strip()
        if citation_text == formatted_citation.plain_text and citation_text.startswith(title_text):
            citation_text = citation_text[len(title_text):].strip()
        return title_text, citation_text

    def _on_case_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        if self._suppress_sidebar_selection_lookup:
            return
        if self._current_case_context_list is not None:
            self._current_case_context_list.unselect_all()
        authority_type = getattr(row, "_open_law_lens_authority_type", "case")
        if authority_type == "statute":
            index = getattr(row, "_open_law_lens_statute_index", None)
            if not isinstance(index, int) or index < 0 or index >= len(self._statutes):
                return
            self._open_cached_statute(self._statutes[index])
            return
        if authority_type == "rule":
            index = getattr(row, "_open_law_lens_rule_index", None)
            if not isinstance(index, int) or index < 0 or index >= len(self._rules):
                return
            self._open_cached_rule(self._rules[index])
            return
        if authority_type == "agent_answer":
            index = getattr(row, "_open_law_lens_agent_answer_index", None)
            if not isinstance(index, int) or index < 0 or index >= len(self._agent_answers):
                return
            self._open_agent_answer(self._agent_answers[index])
            return
        index = getattr(row, "_open_law_lens_cluster_index", None)
        if not isinstance(index, int) or index < 0 or index >= len(self._clusters):
            return
        cluster = self._clusters[index]
        generation = self._begin_case_load(cluster)
        cache_generation = self._research_cache_generation
        thread = threading.Thread(
            target=self._case_worker,
            args=(cluster, generation, cache_generation),
            daemon=True,
        )
        thread.start()

    def _open_statute_in_reader(self, statute: dict[str, Any]) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        set_position_key = getattr(self, "_set_reader_position_key", None)
        if set_position_key is not None:
            set_position_key("statute", str(statute.get("statute_id") or ""))
        self._case_load_generation += 1
        self._selected_cluster = None
        self._selected_statute = statute
        self._selected_rule = None
        self._selected_agent_answer = None
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._clear_reader_citation_links()
        citation_text = str(statute.get("citation") or "").strip()
        header = str(statute.get("title") or citation_text or "Untitled statute")
        formatted = FormattedCitation(
            plain_text=citation_text,
            html_text=GLib.markup_escape_text(citation_text),
        ) if citation_text else None
        self._set_reader_header(header, formatted)
        self._set_reader_text(str(statute.get("text") or "No statute text found."))
        self._set_status(f"Loaded {citation_text or header} from Research Cache.")

    def _open_rule_in_reader(self, rule: dict[str, Any]) -> None:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        set_position_key = getattr(self, "_set_reader_position_key", None)
        if set_position_key is not None:
            set_position_key("rule", str(rule.get("rule_id") or ""))
        self._case_load_generation += 1
        self._selected_cluster = None
        self._selected_statute = None
        self._selected_rule = rule
        self._selected_agent_answer = None
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._clear_reader_citation_links()
        citation_text = str(rule.get("citation") or "").strip()
        header = str(rule.get("title") or citation_text or "Untitled rule")
        formatted = FormattedCitation(
            plain_text=citation_text,
            html_text=GLib.markup_escape_text(citation_text),
        ) if citation_text else None
        self._set_reader_header(header, formatted)
        self._set_reader_text(str(rule.get("text") or "No rule text found."))
        self._set_status(f"Loaded {citation_text or header} from Research Cache.")

    def _begin_case_load(self, cluster: dict[str, Any]) -> int:
        capture_position = getattr(self, "_capture_current_reader_position", None)
        if capture_position is not None:
            capture_position()
        set_position_key = getattr(self, "_set_reader_position_key", None)
        if set_position_key is not None:
            set_position_key("case", cluster_id_from_cluster(cluster))
        self._case_load_generation += 1
        generation = self._case_load_generation
        self._selected_cluster = cluster
        self._selected_statute = None
        self._selected_rule = None
        self._selected_agent_answer = None
        self._reader_has_official_pagination = False
        self._reader_pagination_mode = READER_PAGINATION_NONE
        self._reader_slip_source_url = ""
        self._reader_slip_case_number = ""
        self._reader_page_markers = []
        self._set_reader_header(
            self._case_header_text(cluster),
            self._case_header_citation(cluster),
            cluster,
        )
        title = cluster_title(cluster)
        self.reader_buffer.set_text("")
        self._reader_text = ""
        self._clear_reader_citation_links()
        self._set_reader_busy(True, f"Loading {title}...")
        self._set_status(f"Loading {title}...")
        return generation

    def _cached_slip_opinion_for_cluster(self, cluster: dict[str, Any]) -> SlipOpinionResult | None:
        case_number = case_number_from_cluster(cluster)
        if not case_number:
            return None
        payload = self.client.cache.read_slip_opinion_payload(case_number)
        if not isinstance(payload, dict):
            return None
        display = display_from_payload(payload.get("display"))
        if display is None:
            return None
        return SlipOpinionResult(
            case_number=str(payload.get("case_number") or case_number),
            source_url=str(payload.get("source_url") or ""),
            pdf_path=slip_opinion_pdf_path(self.client.cache, case_number),
            display=display,
            date_filed=str(payload.get("date_filed") or cluster.get("date_filed") or ""),
        )

    def _cache_slip_opinion(self, cluster: dict[str, Any], slip: SlipOpinionResult) -> None:
        case_number = slip.case_number or case_number_from_cluster(cluster)
        if not case_number:
            return
        payload = slip_result_to_payload(slip)
        if not payload.get("date_filed") and cluster.get("date_filed"):
            payload["date_filed"] = str(cluster.get("date_filed") or "")
        self.client.cache.write_slip_opinion_payload(
            case_number,
            payload,
            mark_dirty=False,
        )

    def _case_worker(
        self,
        cluster: dict[str, Any],
        generation: int,
        cache_generation: int,
        force_slip_opinion: bool = False,
    ) -> None:
        cluster_id = cluster_id_from_cluster(cluster)
        try:
            cached_slip = OpenLawLensWindow._cached_slip_opinion_for_cluster(self, cluster)
            if cached_slip is not None:
                payload = build_case_reader_payload(
                    cluster,
                    [cached_slip.display],
                    generation=generation,
                    cache_generation=cache_generation,
                    opinion_ids=(),
                    opinion_source="Research Cache",
                    pagination_mode=READER_PAGINATION_SLIP,
                    slip_source_url=cached_slip.source_url,
                    slip_case_number=cached_slip.case_number,
                )
                GLib.idle_add(self._start_reader_payload_render, payload)
                return
            if force_slip_opinion:
                GLib.idle_add(
                    self._set_reader_busy,
                    True,
                    "Downloading slip opinion PDF...",
                )
                try:
                    slip = self.client.fetch_cluster_slip_opinion(
                        cluster,
                        force=True,
                        max_age_days=DEFAULT_SLIP_OPINION_MAX_AGE_DAYS,
                        populate_research_cache=False,
                    )
                except (SlipOpinionError, ValueError, OSError):
                    slip = None
                if slip is not None:
                    OpenLawLensWindow._cache_slip_opinion(self, cluster, slip)
                    GLib.idle_add(
                        self._set_reader_busy,
                        True,
                        "Rendering slip opinion...",
                    )
                    payload = build_case_reader_payload(
                        cluster,
                        [slip.display],
                        generation=generation,
                        cache_generation=cache_generation,
                        opinion_ids=(),
                        opinion_source="California Courts",
                        pagination_mode=READER_PAGINATION_SLIP,
                        slip_source_url=slip.source_url,
                        slip_case_number=slip.case_number,
                    )
                    GLib.idle_add(self._start_reader_payload_render, payload)
                    return
            opinions = self.client.fetch_cluster_opinions(
                cluster,
                populate_research_cache=False,
            )
            opinion_source = self.client.last_opinion_source
            reader_opinions = self.client.reader_opinions(opinions)
            opinion_ids = tuple(
                str(opinion.get("id") or "").strip()
                for opinion in opinions
                if str(opinion.get("id") or "").strip()
            )
            displays = [self.client.opinion_display(opinion) for opinion in reader_opinions]
            quality = official_pagination_quality(cluster, displays)
            if not quality.eligible:
                try:
                    slip = self.client.fetch_cluster_slip_opinion(
                        cluster,
                        force=force_slip_opinion,
                        max_age_days=DEFAULT_SLIP_OPINION_MAX_AGE_DAYS,
                        populate_research_cache=False,
                    )
                except (SlipOpinionError, ValueError, OSError):
                    slip = None
                if slip is not None:
                    OpenLawLensWindow._cache_slip_opinion(self, cluster, slip)
                    payload = build_case_reader_payload(
                        cluster,
                        [slip.display],
                        generation=generation,
                        cache_generation=cache_generation,
                        opinion_ids=(),
                        opinion_source="California Courts",
                        pagination_mode=READER_PAGINATION_SLIP,
                        slip_source_url=slip.source_url,
                        slip_case_number=slip.case_number,
                    )
                    GLib.idle_add(self._start_reader_payload_render, payload)
                    return
            payload = build_case_reader_payload(
                cluster,
                displays,
                generation=generation,
                cache_generation=cache_generation,
                opinion_ids=opinion_ids,
                opinion_source=opinion_source,
            )
            GLib.idle_add(self._start_reader_payload_render, payload)
        except (CourtListenerError, ValueError, OSError) as exc:
            GLib.idle_add(self._apply_case_error, cluster_id, str(exc), generation)

    def _apply_case_error(self, cluster_id: str, message: str, generation: int = 0) -> bool:
        if generation and not self._case_load_is_current(generation, cluster_id):
            return False
        self._set_reader_busy(False)
        if cluster_id and cluster_id == self._pending_auto_scholar_cluster_id:
            self._pending_auto_scholar_cluster_id = ""
            self._pending_auto_scholar_query = ""
        return self._apply_error(message)

    def _finish_case_quality_status(
        self,
        cluster_id: str,
        eligible: bool,
        reason: str,
        source: str,
        pagination_mode: str = READER_PAGINATION_NONE,
        cache_generation: int | None = None,
    ) -> bool:
        self._reader_has_official_pagination = eligible
        self._reader_pagination_mode = pagination_mode
        pending_query = ""
        if cluster_id and cluster_id == self._pending_auto_scholar_cluster_id:
            pending_query = self._pending_auto_scholar_query
            self._pending_auto_scholar_cluster_id = ""
            self._pending_auto_scholar_query = ""
        if eligible:
            self._set_status(self._official_pagination_status(source))
        elif pagination_mode == READER_PAGINATION_SLIP:
            self._set_status("Loaded California Courts slip opinion PDF with slip-opinion pagination.")
        elif pending_query:
            self._set_reader_busy(True, "Searching Google Scholar...")
            self._set_status("Searching Google Scholar for official reporter text...")
            self._start_scholar_auto_find(
                pending_query,
                fallback_mode=SCHOLAR_FALLBACK_TRANSIENT_NOTICE,
                auto_import=True,
                cache_generation=cache_generation,
            )
        elif reason:
            self._set_status(f"Transient view only: {reason} Use Find Official Text or Import Official Text.")
        self._update_reader_selection_pinpoint_button()
        return False

    def _official_pagination_status(self, source: str) -> str:
        if source == "Library":
            return "Loaded from Library with official reporter pagination."
        if source == "Fetched":
            return "Saved to Library with official reporter pagination."
        return "Loaded with official reporter pagination."

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

    def _compose_general_agent_prompt(
        self,
        question: str,
        current_case_export: FactPatternExport | None = None,
        current_case_selected: bool = False,
        current_case_warning: str = "",
    ) -> str:
        config = load_config()
        prompt = self._format_agent_prompt(
            config.general_agent_prompt_template,
            DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
            {"question": question},
        )
        if not current_case_selected:
            return prompt
        context = OpenLawLensWindow._compose_current_case_context(
            current_case_export,
            True,
            current_case_warning,
        )
        return f"{prompt}\n\n{context}"

    def _compose_case_agent_prompt(
        self,
        question: str,
        export: Any,
        current_case_export: FactPatternExport | None = None,
        current_case_selected: bool = False,
        current_case_warning: str = "",
    ) -> str:
        config = load_config()
        prompt = self._format_agent_prompt(
            config.case_agent_prompt_template,
            DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
            {
                "question": question,
                "case_manifest": str(export.manifest_path),
                "case_dir": str(export.case_dir),
                "case_count": getattr(export, "authority_count", export.case_count),
            },
        )
        context = OpenLawLensWindow._compose_current_case_context(
            current_case_export,
            current_case_selected,
            current_case_warning,
        )
        return f"{prompt}\n\n{context}"

    @staticmethod
    def _compose_current_case_context(
        current_case_export: FactPatternExport | None,
        selected: bool,
        warning: str = "",
    ) -> str:
        heading = "Current-case factual context for this run:\n"
        if not selected:
            return (
                f"{heading}Not selected. Answer without assuming facts about the current case."
            )
        if current_case_export is None:
            reason = warning.strip() or "Current case SOCF was not available."
            return (
                f"{heading}Unavailable: {reason}\n"
                "Do not guess about the current case. If the question requires current-case "
                "facts, explain that the selected factual context is unavailable."
            )
        return (
            f"{heading}This material is within the authorized scope. Treat it as facts, not "
            "legal authority. Read the extracted text before applying or comparing legal "
            "authority to the current case. Cite facts with record citations already present "
            "in the text; do not cite local paths, filenames, or line numbers.\n"
            f"Extracted fact-pattern text: {current_case_export.text_path}\n"
            f"Copied source file: {current_case_export.source_copy_path}"
        )

    def _compose_appeal_issue_agent_prompt(
        self,
        issue: str,
        export: FactPatternExport,
    ) -> str:
        config = load_config()
        return self._format_agent_prompt(
            config.appeal_issue_agent_prompt_template,
            DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            {
                "issue": issue,
                "fact_pattern_path": str(export.text_path),
                "fact_pattern_source_path": str(export.source_copy_path),
                "fact_pattern_original_path": str(export.source_path),
                "fact_pattern_source_name": export.source_path.name,
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

    def _selected_agent_statutes(self) -> list[dict[str, Any]]:
        selected_ids = {
            str(entry.get("statute_id", "")).strip()
            for entry in self.client.cache.selected_statute_entries()
        }
        return [
            statute
            for statute in self.client.cached_statutes()
            if str(statute.get("statute_id") or "").strip() in selected_ids
        ]

    def _selected_agent_rules(self) -> list[dict[str, Any]]:
        selected_ids = {
            str(entry.get("rule_id", "")).strip()
            for entry in self.client.cache.selected_rule_entries()
        }
        return [
            rule
            for rule in self.client.cached_rules()
            if str(rule.get("rule_id") or "").strip() in selected_ids
        ]

    def _selected_agent_answers(self) -> list[dict[str, Any]]:
        answers: list[dict[str, Any]] = []
        for entry in self.client.cache.selected_agent_answer_entries():
            answer_id = str(entry.get("answer_id") or "").strip()
            answer = self.client.cache.read_agent_answer(answer_id) if answer_id else None
            if isinstance(answer, dict):
                answers.append({**entry, **answer})
        return answers

    def start_appeal_issue_assessment(self, issue: str, fact_pattern_path: Path) -> bool:
        issue = issue.strip()
        if not issue:
            self._set_status("Enter an argument to assess.")
            return False
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return False
        try:
            workspace = self._create_agent_workspace()
        except OSError as exc:
            self._set_status(f"Unable to create agent workspace: {exc}")
            return False
        self._set_status("Preparing appeal issue assessment...")
        thread = threading.Thread(
            target=self._prepare_appeal_issue_worker,
            args=(issue, fact_pattern_path, workspace),
            daemon=True,
        )
        thread.start()
        return True

    def _prepare_appeal_issue_worker(
        self,
        issue: str,
        fact_pattern_path: Path,
        workspace: Path,
    ) -> None:
        try:
            export = export_fact_pattern(fact_pattern_path, workspace / "fact_pattern")
            prompt_path = self._write_prompt_file(
                self._compose_appeal_issue_agent_prompt(issue, export)
            )
            GLib.idle_add(self._finish_appeal_issue_prepare, prompt_path, workspace)
        except (FactPatternError, OSError, ValueError) as exc:
            GLib.idle_add(self._set_status, f"Unable to prepare fact pattern: {exc}")

    def _finish_appeal_issue_prepare(self, prompt_path: Path, workspace: Path) -> bool:
        self._case_agent_text_sources = []
        self._agent_mode = AGENT_MODE_APPEAL
        config = load_config()
        self._launch_agent_with_prompt(
            prompt_path,
            workspace,
            AGENT_MODE_APPEAL,
            xhigh_reasoning_effort(config.appeal_issue_xhigh_reasoning),
        )
        return False

    def _current_case_context_for_launch(
        self,
    ) -> tuple[CurrentCaseSocf | None, bool, str]:
        resolved = self._refresh_current_case_context()
        case_name = resolved.case_name if resolved is not None else self._current_case_name
        selected = bool(
            case_name
            and self.client.cache.is_current_case_context_selected(case_name)
        )
        warning = self._current_case_error if selected and resolved is None else ""
        return resolved, selected, warning

    def _on_agent_launch(self, _widget: Gtk.Widget) -> None:
        mode = self._selected_agent_mode
        question = self.agent_question_entry.get_text().strip()
        if not question:
            self._set_status("Enter an agent question.")
            return
        if Vte is None or self._agent_terminal is None:
            self._set_status("Embedded terminal is unavailable.")
            return
        current_case, current_case_selected, current_case_warning = (
            self._current_case_context_for_launch()
        )
        if mode == AGENT_MODE_CASE:
            clusters = self._selected_agent_clusters()
            statutes = self._selected_agent_statutes()
            rules = self._selected_agent_rules()
            agent_answers = self._selected_agent_answers()
            if (
                not clusters
                and not statutes
                and not rules
                and not agent_answers
                and not (current_case_selected and current_case is not None)
            ):
                if current_case_selected and current_case_warning:
                    self._set_status(
                        f"Selected current-case SOCF is unavailable: {current_case_warning}"
                    )
                else:
                    self._set_status(
                        "Mark a Research Cache item or include the current-case SOCF for the Cache Agent."
                    )
                return
            self._set_status("Preparing marked authorities for Cache Agent...")
            thread = threading.Thread(
                target=self._prepare_case_agent_worker,
                args=(
                    question,
                    clusters,
                    statutes,
                    rules,
                    agent_answers,
                    current_case,
                    current_case_selected,
                    current_case_warning,
                ),
                daemon=True,
            )
            thread.start()
            return
        self._set_status("Preparing Law Agent...")
        threading.Thread(
            target=self._prepare_general_agent_worker,
            args=(
                question,
                current_case,
                current_case_selected,
                current_case_warning,
            ),
            daemon=True,
        ).start()

    def _prepare_general_agent_worker(
        self,
        question: str,
        current_case: CurrentCaseSocf | None,
        current_case_selected: bool,
        current_case_warning: str,
    ) -> None:
        try:
            workspace = self._create_agent_workspace()
            current_case_export: FactPatternExport | None = None
            warning = current_case_warning
            if current_case_selected and current_case is not None:
                try:
                    current_case_export = export_fact_pattern(
                        current_case.path,
                        workspace / "current_case_fact_pattern",
                    )
                except (FactPatternError, OSError) as exc:
                    warning = str(exc)
            prompt_path = self._write_prompt_file(
                self._compose_general_agent_prompt(
                    question,
                    current_case_export,
                    current_case_selected,
                    warning,
                )
            )
            GLib.idle_add(
                self._finish_general_agent_prepare,
                prompt_path,
                workspace,
                current_case_export is not None,
                warning if current_case_selected and current_case_export is None else "",
            )
        except OSError as exc:
            GLib.idle_add(self._set_status, f"Unable to prepare Law Agent: {exc}")

    def _finish_general_agent_prepare(
        self,
        prompt_path: Path,
        workspace: Path,
        current_case_included: bool,
        current_case_warning: str = "",
    ) -> bool:
        self._case_agent_text_sources = []
        self._agent_mode = AGENT_MODE_GENERAL
        config = load_config()
        if current_case_included:
            success_status = "Started Law Agent with current-case SOCF."
        elif current_case_warning:
            success_status = (
                "Started Law Agent without selected current-case SOCF; see the session for details."
            )
        else:
            success_status = "Started Law Agent."
        self._launch_agent_with_prompt(
            prompt_path,
            workspace,
            AGENT_MODE_GENERAL,
            xhigh_reasoning_effort(config.general_agent_xhigh_reasoning),
            success_status=success_status,
        )
        return False

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

    def _apply_search_error(self, message: str) -> bool:
        self._set_status(message)
        if self._agent_answer_buffer is not None:
            self._agent_answer_buffer.set_text(message)
        return False

    def _prepare_case_agent_worker(
        self,
        question: str,
        clusters: list[dict[str, Any]],
        statutes: list[dict[str, Any]],
        rules: list[dict[str, Any]],
        agent_answers: list[dict[str, Any]],
        current_case: CurrentCaseSocf | None,
        current_case_selected: bool,
        current_case_warning: str = "",
    ) -> None:
        try:
            workspace = self._create_agent_workspace()
            export = export_selected_authorities(
                self.client,
                clusters,
                statutes,
                rules,
                workspace / "selected_authorities",
                agent_answers,
            )
            current_case_export: FactPatternExport | None = None
            warning = current_case_warning
            if current_case_selected and current_case is not None:
                try:
                    current_case_export = export_fact_pattern(
                        current_case.path,
                        workspace / "current_case_fact_pattern",
                    )
                except (FactPatternError, OSError) as exc:
                    warning = str(exc)
            if export.authority_count == 0 and current_case_export is None:
                message = (
                    f"Selected current-case SOCF is unavailable: {warning}"
                    if current_case_selected and warning
                    else "No text found for marked authorities or current-case SOCF."
                )
                GLib.idle_add(self._set_status, message)
                return
            prompt_path = self._write_prompt_file(
                self._compose_case_agent_prompt(
                    question,
                    export,
                    current_case_export,
                    current_case_selected,
                    warning,
                )
            )
            GLib.idle_add(
                self._finish_case_agent_prepare,
                prompt_path,
                workspace,
                export.text_sources,
                current_case_export is not None,
                warning if current_case_selected and current_case_export is None else "",
            )
        except (CourtListenerError, LegInfoError, CaliforniaRulesError, OSError, ValueError) as exc:
            GLib.idle_add(self._set_status, f"Unable to prepare marked authorities: {exc}")

    def _finish_case_agent_prepare(
        self,
        prompt_path: Path,
        workspace: Path,
        text_sources: list[CaseTextSource],
        current_case_included: bool,
        current_case_warning: str = "",
    ) -> bool:
        self._case_agent_text_sources = text_sources
        self._agent_mode = AGENT_MODE_CASE
        config = load_config()
        self._launch_agent_with_prompt(
            prompt_path,
            workspace,
            AGENT_MODE_CASE,
            xhigh_reasoning_effort(config.case_agent_xhigh_reasoning),
            success_status=(
                "Started Cache Agent with current-case SOCF."
                if current_case_included
                else (
                    "Started Cache Agent without selected current-case SOCF; see the session for details."
                    if current_case_warning
                    else "Started Cache Agent without current-case SOCF."
                )
            ),
        )
        return False

    def _launch_agent_with_prompt(
        self,
        prompt_path: Path,
        workspace: Path,
        mode: str,
        reasoning_effort: str = "",
        success_status: str = "Started embedded Codex agent.",
    ) -> None:
        self._stop_agent()
        self._stop_agent_answer_polling()
        self._clear_agent_answer()
        self._agent_output_collapsed = False
        if not AGENT_WRAPPER.is_file():
            self._set_status(f"Agent wrapper not found: {AGENT_WRAPPER}")
            return
        config = load_config()
        env = os.environ.copy()
        env.update(
            build_agent_launch_env(
                self.client,
                prompt_path,
                workspace,
                mode,
                config,
                reasoning_effort,
            )
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
            self._set_status(success_status)
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
        self._agent_statute_link_lookup.clear()
        self._agent_rule_link_lookup.clear()
        self._agent_external_url_link_lookup.clear()
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
            answer = strip_agent_legal_authority_backticks(
                extract_latest_codex_final_answer_from_jsonl(self._agent_session_log_path)
            )
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
                bullet_match = re.match(r"(\s*)\*\s+", line_text)
                if bullet_match:
                    line_text = f"{bullet_match.group(1)}- {line_text[bullet_match.end():]}"
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

    def _render_agent_answer(self, text: str) -> None:
        if self._agent_answer_buffer is None:
            return
        text = strip_agent_legal_authority_backticks(text)
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
        self._agent_external_url_link_lookup.clear()
        self._agent_search_link_lookup.clear()
        self._agent_search_next_link_tags.clear()
        self._agent_search_highlight_tags.clear()
        quote_spans = (
            resolved_agent_quote_spans(text, self._case_agent_text_sources)
            if self._agent_mode == AGENT_MODE_CASE
            else []
        )
        rendered, markdown_spans, offset_map = self._render_markdown_text(text)
        buffer.set_text(rendered)
        self._apply_agent_markdown_spans(buffer, markdown_spans)
        self._apply_agent_citation_italics(buffer, rendered)
        quote_color = self._resolve_agent_quote_color()
        for span in quote_spans:
            if span.target is None:
                continue
            mapped_start = self._map_offset(span.start_offset, offset_map)
            mapped_end = self._map_offset(span.end_offset, offset_map)
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
            self._agent_link_lookup[tag] = span.target
        if self._agent_mode in {AGENT_MODE_GENERAL, AGENT_MODE_APPEAL}:
            self._apply_agent_citation_links(buffer, rendered)
            self._apply_agent_statute_links(buffer, rendered)
            self._apply_agent_rule_links(buffer, rendered)
        self._apply_agent_external_url_links(buffer, rendered)

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

    def _apply_agent_statute_links(self, buffer: Gtk.TextBuffer, text: str) -> None:
        for link in cited_statute_links(text):
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
            self._agent_statute_link_lookup[tag] = link

    def _apply_agent_rule_links(self, buffer: Gtk.TextBuffer, text: str) -> None:
        for link in cited_rule_links(text):
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
            self._agent_rule_link_lookup[tag] = link

    def _apply_agent_external_url_links(self, buffer: Gtk.TextBuffer, text: str) -> None:
        for start, end, url in self._external_url_links(text):
            tag = buffer.create_tag(
                None,
                foreground_rgba=self._resolve_agent_quote_color(),
                underline=Pango.Underline.SINGLE,
                weight=Pango.Weight.MEDIUM,
            )
            buffer.apply_tag(
                tag,
                buffer.get_iter_at_offset(start),
                buffer.get_iter_at_offset(end),
            )
            self._agent_link_tags.append(tag)
            self._agent_external_url_link_lookup[tag] = AgentExternalUrlLink(url)

    @staticmethod
    def _external_url_links(text: str) -> list[tuple[int, int, str]]:
        links: list[tuple[int, int, str]] = []
        for match in EXTERNAL_URL_RE.finditer(text):
            start, end = match.span()
            url = match.group(0)
            while url and url[-1] in ".,;:)]}":
                url = url[:-1]
                end -= 1
            if url:
                links.append((start, end, url))
        return links

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
        self._agent_statute_link_lookup.clear()
        self._agent_rule_link_lookup.clear()
        self._agent_external_url_link_lookup.clear()
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
            click.connect("pressed", self._on_agent_answer_pressed)
            click.connect("released", self._on_agent_answer_click)
            click.connect("stopped", self._clear_agent_link_press)
            click.connect("cancel", self._clear_agent_link_press)
            view.add_controller(click)
            self._agent_click_gesture = click

    def _agent_link_at_coords(
        self,
        x: float,
        y: float,
    ) -> CitedCaseLink | StatuteLink | RuleLink | AgentExternalUrlLink | QuoteTarget | CourtListenerSearchResult | str | None:
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
            statute_link = self._agent_statute_link_lookup.get(tag)
            if statute_link is not None:
                return statute_link
            rule_link = self._agent_rule_link_lookup.get(tag)
            if rule_link is not None:
                return rule_link
            external_url = self._agent_external_url_link_lookup.get(tag)
            if external_url is not None:
                return external_url
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

    def _on_agent_answer_pressed(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        target = self._agent_link_at_coords(x, y)
        self._agent_link_press = (
            LinkPressState(target, x, y)
            if n_press == 1 and target is not None and (not button or button == Gdk.BUTTON_PRIMARY)
            else None
        )

    def _clear_agent_link_press(self, *_args: object) -> None:
        self._agent_link_press = None

    def _on_agent_answer_click(
        self,
        gesture: Gtk.GestureClick,
        n_press: int,
        x: float,
        y: float,
    ) -> None:
        button = gesture.get_current_button()
        press = self._agent_link_press
        self._agent_link_press = None
        if button and button != Gdk.BUTTON_PRIMARY:
            return
        target = self._agent_link_at_coords(x, y)
        view = self._agent_answer_view
        if view is None or not self._link_release_is_click(view, press, target, n_press, x, y):
            return
        if target == SEARCH_NEXT_PAGE_TARGET:
            return
        if isinstance(target, CourtListenerSearchResult):
            self._open_search_result(target)
        elif isinstance(target, CitedCaseLink):
            self._open_agent_cited_case_link(target)
        elif isinstance(target, StatuteLink):
            self._open_statute_link(target)
        elif isinstance(target, RuleLink):
            self._open_rule_link(target)
        elif isinstance(target, AgentExternalUrlLink):
            self._launch_external_url(target.url)
        elif target is not None:
            self._open_quote_target(target)

    def _open_search_result(self, result: CourtListenerSearchResult) -> None:
        self._set_status(f"Opening {result.case_name}...")
        cache_generation = self._research_cache_generation
        self._start_background_worker(
            lambda: self.client.fetch_url(
                f"/api/rest/v4/clusters/{result.cluster_id}/",
                kind="clusters",
            ),
            on_success=lambda cluster: self._finish_search_result_open(
                cluster,
                result,
                cache_generation,
            ),
            on_error=lambda exc: self._set_status(f"Unable to open {result.case_name}: {exc}"),
            handled_exceptions=(CourtListenerError,),
        )

    def _search_result_open_worker(
        self,
        result: CourtListenerSearchResult,
        cache_generation: int,
    ) -> None:
        try:
            cluster = self.client.fetch_url(
                f"/api/rest/v4/clusters/{result.cluster_id}/",
                kind="clusters",
            )
            GLib.idle_add(
                self._finish_search_result_open,
                cluster,
                result.case_name,
                cache_generation,
            )
        except CourtListenerError as exc:
            GLib.idle_add(self._set_status, f"Unable to open {result.case_name}: {exc}")

    def _finish_search_result_open(
        self,
        cluster: dict[str, Any],
        title: str,
        cache_generation: int,
    ) -> bool:
        if cache_generation != self._research_cache_generation:
            return False
        cluster_id = self.client.cache.upsert_cluster(cluster) or cluster_id_from_cluster(cluster)
        self._set_sidebar_clusters(
            self.client.cached_clusters(),
            select_cluster_id=cluster_id,
        )
        self._refresh_case_suggestion_index_async(force=True)
        if self.case_list.get_selected_row() is None:
            self._set_status(f"Cached {title}, but could not select the case.")
        else:
            self._set_status(f"Opened {title}.")
        return False

    def _open_quote_target(self, target: QuoteTarget) -> None:
        authority_id = self._quote_target_authority_id(target)
        row = self._research_cache_authority_row(target.authority_type, authority_id)
        if row is None:
            self._set_status("Quoted authority is no longer in Research Cache.")
            return
        if self._quote_target_is_selected(target) and self._reader_text:
            self._highlight_reader_quote_target(target)
            return
        self._pending_quote_target = target
        if self.case_list.get_selected_row() is not row:
            self.case_list.select_row(row)

    @staticmethod
    def _quote_target_authority_id(target: QuoteTarget) -> str:
        if target.authority_type == "statute":
            return target.statute_id
        if target.authority_type == "rule":
            return target.rule_id
        return target.cluster_id

    def _research_cache_authority_row(
        self,
        authority_type: str,
        authority_id: str,
    ) -> Gtk.ListBoxRow | None:
        index = 0
        while row := self.case_list.get_row_at_index(index):
            if (
                getattr(row, "_open_law_lens_authority_type", "") == authority_type
                and getattr(row, "_open_law_lens_authority_id", "") == authority_id
            ):
                return row
            index += 1
        return None

    def _quote_target_is_selected(self, target: QuoteTarget) -> bool:
        if target.authority_type == "statute":
            selected_id = str((self._selected_statute or {}).get("statute_id") or "")
            return bool(target.statute_id and selected_id == target.statute_id)
        if target.authority_type == "rule":
            selected_id = str((self._selected_rule or {}).get("rule_id") or "")
            return bool(target.rule_id and selected_id == target.rule_id)
        selected_id = cluster_id_from_cluster(self._selected_cluster or {})
        return bool(target.cluster_id and selected_id == target.cluster_id)

    def _highlight_reader_quote_target(self, target: QuoteTarget) -> None:
        if self._reader_highlight_tag is None:
            return
        self.reader_buffer.remove_tag(
            self._reader_highlight_tag,
            self.reader_buffer.get_start_iter(),
            self.reader_buffer.get_end_iter(),
        )
        spans = quote_match_spans(self._reader_text, target.phrase)
        if not spans:
            self._set_status("Quoted phrase was not found in the loaded authority text.")
            return
        start, end = min(spans, key=lambda span: abs(span[0] - target.offset))
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
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._resource_context = contextlib.ExitStack()
        self._installed_bundled_icon_path = False
        self.connect("activate", self._on_activate)
        self.connect("command-line", self._on_command_line)
        self.connect("shutdown", self._on_shutdown)
        self.add_main_option(
            "open-authority",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.STRING,
            "Open authority text after launching the app",
            "TEXT",
        )
        self._install_actions()
        self.set_accels_for_action("win.focus_citation", ["<Primary>l"])
        self.set_accels_for_action("win.focus_law_question", ["<Primary>q"])
        self.set_accels_for_action("win.focus_cache_question", ["<Primary><Shift>q"])
        self.set_accels_for_action("win.show_shortcuts", ["F1"])

    def _install_bundled_icon_path(self) -> None:
        if self._installed_bundled_icon_path:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        icons_ref = resources.files(__package__).joinpath("icons")
        icons_path = self._resource_context.enter_context(resources.as_file(icons_ref))
        Gtk.IconTheme.get_for_display(display).add_search_path(str(icons_path))
        self._installed_bundled_icon_path = True

    def _on_shutdown(self, _app: Adw.Application) -> None:
        self._resource_context.close()

    def _install_actions(self) -> None:
        open_authority = Gio.SimpleAction.new("open_authority", GLib.VariantType.new("s"))
        open_authority.connect(
            "activate",
            self._on_open_authority,
        )
        self.add_action(open_authority)

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
        install_bundled_icons = getattr(self, "_install_bundled_icon_path", None)
        if install_bundled_icons is not None:
            install_bundled_icons()
        window = self._main_window()
        self._open_startup_authority_if_requested(window)

    def _on_command_line(
        self,
        _app: Adw.Application,
        command_line: Gio.ApplicationCommandLine,
    ) -> int:
        options = command_line.get_options_dict()
        open_text_variant = options.lookup_value("open-authority", GLib.VariantType.new("s"))
        open_text = open_text_variant.get_string().strip() if open_text_variant is not None else ""
        install_bundled_icons = getattr(self, "_install_bundled_icon_path", None)
        if install_bundled_icons is not None:
            install_bundled_icons()
        window = self._main_window()
        if open_text:
            window.show_open_authority_pending()
            GLib.idle_add(window.open_authority_text, open_text)
        else:
            self._open_startup_authority_if_requested(window)
        return 0

    def _open_startup_authority_if_requested(self, window: OpenLawLensWindow) -> None:
        open_text = pop_open_authority_request()
        if open_text:
            window.show_open_authority_pending()
            GLib.idle_add(window.open_authority_text, open_text)

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

    def _on_open_authority(
        self,
        _action: Gio.SimpleAction,
        parameter: GLib.Variant | None,
    ) -> None:
        if parameter is None:
            return
        self._main_window().open_authority_text(parameter.get_string())


def main(argv: list[str] | None = None) -> int:
    app = OpenLawLensApp()
    run_argv = None if argv is None else [sys.argv[0], *argv]
    return int(app.run(run_argv))
