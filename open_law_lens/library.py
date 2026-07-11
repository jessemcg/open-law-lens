from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator

from .cache import JsonCache, cluster_id_from_cluster, normalize_citation, resource_id_from_url
from .case_titles import cluster_short_title_value
from .citation_model import (
    canonicalize_cluster_citations,
    canonicalize_lookup_result,
    official_citation_from_cluster,
    official_citation_parts_from_text,
)
from .external_import import repair_reporter_only_imported_cluster
from .import_text import clean_imported_opinion_text
from .storage import (
    external_import_matches_lookup as _external_import_matches_lookup,
    filter_lookup_result_for_citation as _filter_lookup_result_for_citation,
    filter_lookup_result_to_official_citation as _filter_lookup_result_to_official_citation,
    lookup_result_had_clusters as _lookup_result_had_clusters,
    repair_lookup_result_clusters as _repair_lookup_result_clusters,
)
from .text_formatting import quote_stack_replacements

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_LIBRARY_DIR = PROJECT_ROOT / "library"
DEFAULT_LIBRARY_DB = PROJECT_LIBRARY_DIR / "open_law_lens.sqlite3"
SCHEMA_VERSION = "2"
OFFICIAL_CITATION_ONLY_NORMALIZED_KEY = "official_citation_only_normalized_v2"
CASE_TITLES_NORMALIZED_KEY = "case_titles_normalized_v1"
REPORTER_ONLY_IMPORTED_NAMES_NORMALIZED_KEY = "reporter_only_imported_names_normalized_v1"
RESEARCH_SET_SLIP_PAYLOAD_KEY = "_open_law_lens_slip_opinion"
TEXT_FIELDS = (
    "html_with_citations",
    "plain_text",
    "html",
    "html_lawbox",
    "html_columbia",
    "html_anon_2020",
    "xml_harvard",
)
RAW_STAR_PAGE_MARKER_RE = re.compile(
    r"(?<![\w\[])\*(?:Page\s+)?(?P<label>\d{2,5})(?!\d)"
)
BRACKETED_STAR_PAGE_MARKER_RE = re.compile(r"\[\*(?P<label>\d{1,5})\]")

CP1252_CONTROL_TRANSLATION = str.maketrans(
    {
        "\u0080": "\u20ac",
        "\u0082": "\u201a",
        "\u0083": "\u0192",
        "\u0084": "\u201e",
        "\u0085": "\u2026",
        "\u0086": "\u2020",
        "\u0087": "\u2021",
        "\u0088": "\u02c6",
        "\u0089": "\u2030",
        "\u008a": "\u0160",
        "\u008b": "\u2039",
        "\u008c": "\u0152",
        "\u008e": "\u017d",
        "\u0091": "\u2018",
        "\u0092": "\u2019",
        "\u0093": "\u201c",
        "\u0094": "\u201d",
        "\u0095": "\u2022",
        "\u0096": "\u2013",
        "\u0097": "\u2014",
        "\u0098": "\u02dc",
        "\u0099": "\u2122",
        "\u009a": "\u0161",
        "\u009b": "\u203a",
        "\u009c": "\u0153",
        "\u009e": "\u017e",
        "\u009f": "\u0178",
    }
)


def library_db_path() -> Path:
    path = os.environ.get("OPEN_LAW_LENS_LIBRARY_DB")
    if path:
        return Path(path).expanduser()
    return DEFAULT_LIBRARY_DB


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str) -> Any:
    return json.loads(value)


def decode_cp1252_control_chars(value: str) -> str:
    return value.translate(CP1252_CONTROL_TRANSLATION)


def _opinion_import_text(opinion: dict[str, Any]) -> str:
    for field in TEXT_FIELDS:
        value = opinion.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _cluster_title(cluster: dict[str, Any]) -> str:
    title = cluster_short_title_value(cluster)
    if title:
        return title
    cluster_id = cluster_id_from_cluster(cluster)
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def _cluster_citation_line(cluster: dict[str, Any]) -> str:
    return official_citation_from_cluster(cluster)


def _citation_text_from_dict(citation: dict[str, Any]) -> str:
    pieces = [
        str(piece).strip()
        for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
        if str(piece).strip()
    ]
    return " ".join(pieces)


def _case_number_from_cluster_payload(cluster: dict[str, Any]) -> str:
    candidates: list[object] = [
        cluster.get("docket_number"),
        cluster.get("docketNumber"),
        cluster.get("case_number"),
        cluster.get("caseNumber"),
        cluster.get("slug"),
        cluster.get("absolute_url"),
    ]
    docket = cluster.get("docket")
    if isinstance(docket, dict):
        candidates.extend(
            [
                docket.get("docket_number"),
                docket.get("docketNumber"),
                docket.get("case_number"),
                docket.get("caseNumber"),
            ]
        )
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        match = re.search(r"\b([A-Z]\d{6})\b", candidate, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


@dataclass(frozen=True)
class PageMarker:
    page_label: str
    marker_text: str
    start_offset: int
    end_offset: int
    source_field: str


@dataclass(frozen=True)
class DisplayText:
    text: str
    source_field: str
    page_markers: list[PageMarker]


@dataclass(frozen=True)
class LibraryPruneCandidate:
    cluster_id: str
    title: str
    citation_text: str
    opinion_count: int
    marker_count: int
    eligible: bool
    official_citation: str
    reason: str


@dataclass(frozen=True)
class LibraryPruneResult:
    backup_path: Path | None
    pruned: list[LibraryPruneCandidate]
    kept_count: int


@dataclass(frozen=True)
class ResearchSetItem:
    item_type: str
    authority_id: str
    title: str
    citation: str
    payload: dict[str, Any]
    position: int
    agent_selected: bool


@dataclass(frozen=True)
class ResearchSet:
    set_id: int
    name: str
    created_at: str
    updated_at: str
    last_accessed: str
    item_count: int
    case_count: int
    statute_count: int
    rule_count: int
    agent_answer_count: int
    prior_brief_count: int = 0
    items: list[ResearchSetItem] = field(default_factory=list)


class _DisplayTextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "center", "author"}

    def __init__(self, source_field: str) -> None:
        super().__init__()
        self.source_field = source_field
        self.parts: list[str] = []
        self.page_markers: list[PageMarker] = []
        self._page_label: str | None = None
        self._page_text_parts: list[str] = []
        self._pending_space = False
        self._pending_break = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "page-number" or self._is_star_pagination(tag, attr_map):
            self._start_page_marker(attr_map)
            return
        if tag == "br":
            self._queue_block_break()
            return
        if tag in self.BLOCK_TAGS:
            self._queue_block_break()

    def handle_endtag(self, tag: str) -> None:
        if tag in {"page-number", "span"} and self._page_label is not None:
            self._finish_page_marker()
            return
        if tag in self.BLOCK_TAGS:
            self._queue_block_break()

    def handle_data(self, data: str) -> None:
        if self._page_label is not None:
            self._page_text_parts.append(data)
            return
        self._append_data(data)

    def display_text(self) -> DisplayText:
        text = "".join(self.parts).strip()
        return DisplayText(text=text, source_field=self.source_field, page_markers=self.page_markers)

    def _append_data(self, data: str) -> None:
        if not data:
            return
        data = decode_cp1252_control_chars(data)
        has_leading_space = data[:1].isspace()
        has_trailing_space = data[-1:].isspace()
        text = re.sub(r"\s+", " ", data.strip())
        if not text:
            if self._has_text() and not self._ends_with_break():
                self._pending_space = True
            return
        if has_leading_space:
            self._pending_space = True
        self._append_text(text)
        if has_trailing_space:
            self._pending_space = True

    def _append_text(self, text: str) -> int:
        self._flush_pending(text[:1])
        start = len("".join(self.parts))
        self.parts.append(text)
        return start

    def _append_marker_text(self, marker_text: str) -> int:
        return self._append_text(marker_text)

    def _start_page_marker(self, attr_map: dict[str, str | None]) -> None:
        label = attr_map.get("label")
        self._page_label = label.strip() if isinstance(label, str) else ""
        self._page_text_parts = []

    def _finish_page_marker(self) -> None:
        raw_text = decode_cp1252_control_chars(html.unescape("".join(self._page_text_parts))).strip()
        label = _page_marker_label(self._page_label or raw_text)
        if label:
            marker_text = f"[*{label}]"
            start = self._append_marker_text(marker_text)
            end = start + len(marker_text)
            self.page_markers.append(
                PageMarker(
                    page_label=label,
                    marker_text=marker_text,
                    start_offset=start,
                    end_offset=end,
                    source_field=self.source_field,
                )
            )
        self._page_label = None
        self._page_text_parts = []

    @staticmethod
    def _is_star_pagination(tag: str, attr_map: dict[str, str | None]) -> bool:
        class_value = attr_map.get("class")
        if tag != "span" or not isinstance(class_value, str):
            return False
        return "star-pagination" in class_value.split()

    def _queue_block_break(self) -> None:
        if self._has_text() and not self._ends_with_break():
            self._pending_break = True
        self._pending_space = False

    def _flush_pending(self, next_char: str) -> None:
        if self._pending_break:
            self._trim_trailing_spaces()
            if self._has_text() and not self._ends_with_break():
                self.parts.append("\n\n")
            self._pending_break = False
            self._pending_space = False
            return
        if self._pending_space and self._should_insert_space(next_char):
            self.parts.append(" ")
        self._pending_space = False

    def _should_insert_space(self, next_char: str) -> bool:
        if not self.parts or not next_char:
            return False
        previous = self.parts[-1][-1:] if self.parts[-1] else ""
        if not previous or previous.isspace():
            return False
        return next_char not in ".,;:)]}?!"

    def _trim_trailing_spaces(self) -> None:
        while self.parts and self.parts[-1] == "":
            self.parts.pop()
        if self.parts:
            self.parts[-1] = self.parts[-1].rstrip(" ")

    def _has_text(self) -> bool:
        return bool("".join(self.parts).strip())

    def _ends_with_break(self) -> bool:
        return "".join(self.parts).endswith("\n\n")


def _page_marker_label(value: str) -> str:
    label = html.unescape(value).strip()
    label = re.sub(r"\s+", " ", label)
    label = label.lstrip("*").strip()
    label = re.sub(r"(?i)^page\s+", "", label).strip()
    return label


def _research_set_normalized_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def _normalize_raw_star_page_markers(display: DisplayText) -> DisplayText:
    if not display.text:
        return display
    existing_ranges = [
        (marker.start_offset, marker.end_offset)
        for marker in display.page_markers
    ]
    replacements: list[tuple[int, int, str, str]] = []
    for match in BRACKETED_STAR_PAGE_MARKER_RE.finditer(display.text):
        start, end = match.span()
        if any(range_start <= start < range_end for range_start, range_end in existing_ranges):
            continue
        label = _page_marker_label(match.group("label"))
        if not label:
            continue
        replacements.append((start, end, f"[*{label}]", label))
    for match in RAW_STAR_PAGE_MARKER_RE.finditer(display.text):
        start, end = match.span()
        if any(range_start <= start < range_end for range_start, range_end in existing_ranges):
            continue
        label = _page_marker_label(match.group(0))
        if not label:
            continue
        replacements.append((start, end, f"[*{label}]", label))
    replacements.sort(key=lambda replacement: replacement[0])
    if not replacements:
        return display

    parts: list[str] = []
    raw_markers: list[PageMarker] = []
    position = 0
    text_length = 0
    for start, end, marker_text, label in replacements:
        prefix = display.text[position:start]
        parts.append(prefix)
        text_length += len(prefix)
        marker_start = text_length
        parts.append(marker_text)
        text_length += len(marker_text)
        raw_markers.append(
            PageMarker(
                page_label=label,
                marker_text=marker_text,
                start_offset=marker_start,
                end_offset=marker_start + len(marker_text),
                source_field=display.source_field,
            )
        )
        position = end
    suffix = display.text[position:]
    parts.append(suffix)
    text = "".join(parts)

    def translated_offset(offset: int) -> int:
        translated = offset
        for start, end, marker_text, _label in replacements:
            if end <= offset:
                translated += len(marker_text) - (end - start)
        return translated

    page_markers = [
        PageMarker(
            page_label=marker.page_label,
            marker_text=marker.marker_text,
            start_offset=translated_offset(marker.start_offset),
            end_offset=translated_offset(marker.end_offset),
            source_field=marker.source_field,
        )
        for marker in display.page_markers
    ]
    page_markers.extend(raw_markers)
    page_markers.sort(key=lambda marker: marker.start_offset)
    return DisplayText(text=text, source_field=display.source_field, page_markers=page_markers)


def normalize_display_quote_stacks(display: DisplayText) -> DisplayText:
    if not display.text:
        return display
    replacements = quote_stack_replacements(display.text)
    if not replacements:
        return display
    parts: list[str] = []
    position = 0
    for start, end, replacement in replacements:
        parts.append(display.text[position:start])
        parts.append(replacement)
        position = end
    parts.append(display.text[position:])
    text = "".join(parts)

    def translated_offset(offset: int) -> int:
        translated = offset
        for start, end, replacement in replacements:
            delta = len(replacement) - (end - start)
            if end <= offset:
                translated += delta
                continue
            if start < offset < end:
                return start + max(0, min(offset - start, len(replacement)))
        return translated

    return DisplayText(
        text=text,
        source_field=display.source_field,
        page_markers=[
            PageMarker(
                page_label=marker.page_label,
                marker_text=marker.marker_text,
                start_offset=translated_offset(marker.start_offset),
                end_offset=translated_offset(marker.end_offset),
                source_field=marker.source_field,
            )
            for marker in display.page_markers
        ],
    )


def _normalize_opinion_display(display: DisplayText) -> DisplayText:
    return _normalize_raw_star_page_markers(normalize_display_quote_stacks(display))


def opinion_display_text(opinion: dict[str, Any]) -> DisplayText:
    for field in TEXT_FIELDS:
        value = opinion.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if opinion.get("source_type") == "user_imported_official_text":
            value = clean_imported_opinion_text(value)
        if field.startswith("html") or field.startswith("xml"):
            parser = _DisplayTextExtractor(field)
            parser.feed(value)
            parser.close()
            return _normalize_opinion_display(parser.display_text())
        text = decode_cp1252_control_chars(value).strip()
        return _normalize_opinion_display(DisplayText(text=text, source_field=field, page_markers=[]))
    return DisplayText(text="", source_field="", page_markers=[])


@dataclass
class CaseLibrary:
    path: Path

    @classmethod
    def default(cls) -> "CaseLibrary":
        library = cls(library_db_path())
        library.ensure()
        return library

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lookup_results (
                    normalized_citation TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cases (
                    cluster_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    citation_text TEXT NOT NULL,
                    cluster_json TEXT NOT NULL,
                    opinion_ids_json TEXT NOT NULL DEFAULT '[]',
                    added_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS citation_aliases (
                    normalized_citation TEXT NOT NULL,
                    cluster_id TEXT NOT NULL,
                    citation_text TEXT NOT NULL,
                    PRIMARY KEY (normalized_citation, cluster_id),
                    FOREIGN KEY (cluster_id) REFERENCES cases(cluster_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS opinions (
                    opinion_id TEXT PRIMARY KEY,
                    cluster_id TEXT NOT NULL,
                    opinion_json TEXT NOT NULL,
                    display_text TEXT NOT NULL,
                    source_field TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS page_markers (
                    opinion_id TEXT NOT NULL,
                    marker_index INTEGER NOT NULL,
                    page_label TEXT NOT NULL,
                    marker_text TEXT NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    source_field TEXT NOT NULL,
                    PRIMARY KEY (opinion_id, marker_index),
                    FOREIGN KEY (opinion_id) REFERENCES opinions(opinion_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS research_sets (
                    set_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_set_items (
                    set_id INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    authority_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    citation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    agent_selected INTEGER NOT NULL DEFAULT 0,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (set_id, item_type, authority_id),
                    FOREIGN KEY (set_id) REFERENCES research_sets(set_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_cases_title ON cases(title);
                CREATE INDEX IF NOT EXISTS idx_opinions_cluster_id ON opinions(cluster_id);
                CREATE INDEX IF NOT EXISTS idx_aliases_citation ON citation_aliases(normalized_citation);
                CREATE INDEX IF NOT EXISTS idx_research_set_items_set_id
                ON research_set_items(set_id, position);
                """
            )
            self._drop_legacy_statute_rule_tables(conn)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            self._normalize_official_citation_only(conn)
            self._normalize_case_titles(conn)
            self._normalize_reporter_only_imported_case_names(conn)

    def _drop_legacy_statute_rule_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            DROP TABLE IF EXISTS statute_aliases;
            DROP TABLE IF EXISTS rule_aliases;
            DROP TABLE IF EXISTS statutes;
            DROP TABLE IF EXISTS rules;
            """
        )

    def _normalize_official_citation_only(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (OFFICIAL_CITATION_ONLY_NORMALIZED_KEY,),
        ).fetchone()
        if row is not None:
            return
        rows = conn.execute("SELECT cluster_id, cluster_json FROM cases").fetchall()
        conn.execute("DELETE FROM citation_aliases")
        for row in rows:
            cluster_id = str(row["cluster_id"])
            try:
                cluster = _json_loads(str(row["cluster_json"]))
            except json.JSONDecodeError:
                continue
            if not isinstance(cluster, dict):
                continue
            canonical = canonicalize_cluster_citations(cluster)
            citation_text = _cluster_citation_line(canonical)
            conn.execute(
                """
                UPDATE cases
                SET citation_text = ?, cluster_json = ?
                WHERE cluster_id = ?
                """,
                (citation_text, _json_dumps(canonical), cluster_id),
            )
            if citation_text:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO citation_aliases(normalized_citation, cluster_id, citation_text)
                    VALUES (?, ?, ?)
                    """,
                    (normalize_citation(citation_text).casefold(), cluster_id, citation_text),
                )
        lookup_rows = conn.execute(
            "SELECT normalized_citation, result_json FROM lookup_results"
        ).fetchall()
        for row in lookup_rows:
            normalized = str(row["normalized_citation"])
            if official_citation_parts_from_text(normalized) is None:
                conn.execute(
                    "DELETE FROM lookup_results WHERE normalized_citation = ?",
                    (normalized,),
                )
                continue
            try:
                result = _json_loads(str(row["result_json"]))
            except json.JSONDecodeError:
                continue
            canonical_lookup = canonicalize_lookup_result(result)
            if not isinstance(canonical_lookup, list):
                conn.execute(
                    "DELETE FROM lookup_results WHERE normalized_citation = ?",
                    (normalized,),
                )
                continue
            canonical_result = _filter_lookup_result_to_official_citation(canonical_lookup, normalized)
            if canonical_result:
                conn.execute(
                    """
                    UPDATE lookup_results
                    SET result_json = ?
                    WHERE normalized_citation = ?
                    """,
                    (_json_dumps(canonical_result), normalized),
                )
            else:
                conn.execute(
                    "DELETE FROM lookup_results WHERE normalized_citation = ?",
                    (normalized,),
                )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (OFFICIAL_CITATION_ONLY_NORMALIZED_KEY, _utc_now()),
        )

    def _normalize_case_titles(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (CASE_TITLES_NORMALIZED_KEY,),
        ).fetchone()
        if row is not None:
            return
        rows = conn.execute("SELECT cluster_id, title, cluster_json FROM cases").fetchall()
        for row in rows:
            try:
                cluster = _json_loads(str(row["cluster_json"]))
            except json.JSONDecodeError:
                continue
            if not isinstance(cluster, dict):
                continue
            title = _cluster_title(cluster)
            if title and title != str(row["title"]):
                conn.execute(
                    "UPDATE cases SET title = ? WHERE cluster_id = ?",
                    (title, str(row["cluster_id"])),
                )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (CASE_TITLES_NORMALIZED_KEY, _utc_now()),
        )

    def _normalize_reporter_only_imported_case_names(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?",
            (REPORTER_ONLY_IMPORTED_NAMES_NORMALIZED_KEY,),
        ).fetchone()
        if row is not None:
            return
        repaired_clusters: dict[str, dict[str, Any]] = {}
        rows = conn.execute(
            "SELECT cluster_id, cluster_json, opinion_ids_json FROM cases"
        ).fetchall()
        for row in rows:
            cluster_id = str(row["cluster_id"])
            try:
                cluster = _json_loads(str(row["cluster_json"]))
                opinion_ids = _json_loads(str(row["opinion_ids_json"]))
            except json.JSONDecodeError:
                continue
            if not isinstance(cluster, dict) or not isinstance(opinion_ids, list):
                continue
            for opinion_id in opinion_ids:
                opinion_row = conn.execute(
                    "SELECT opinion_json FROM opinions WHERE opinion_id = ?",
                    (str(opinion_id),),
                ).fetchone()
                if opinion_row is None:
                    continue
                try:
                    opinion = _json_loads(str(opinion_row["opinion_json"]))
                except json.JSONDecodeError:
                    continue
                if not isinstance(opinion, dict):
                    continue
                repaired = repair_reporter_only_imported_cluster(
                    cluster,
                    _opinion_import_text(opinion),
                )
                if repaired is None:
                    continue
                canonical = canonicalize_cluster_citations(repaired)
                title = _cluster_title(canonical)
                citation_text = _cluster_citation_line(canonical)
                conn.execute(
                    """
                    UPDATE cases
                    SET title = ?, citation_text = ?, cluster_json = ?, last_accessed = ?
                    WHERE cluster_id = ?
                    """,
                    (title, citation_text, _json_dumps(canonical), _utc_now(), cluster_id),
                )
                repaired_clusters[cluster_id] = canonical
                break
        if repaired_clusters:
            self._normalize_lookup_clusters(conn, repaired_clusters)
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (REPORTER_ONLY_IMPORTED_NAMES_NORMALIZED_KEY, _utc_now()),
        )

    def _normalize_lookup_clusters(
        self,
        conn: sqlite3.Connection,
        repaired_clusters: dict[str, dict[str, Any]],
    ) -> None:
        rows = conn.execute(
            "SELECT normalized_citation, result_json FROM lookup_results"
        ).fetchall()
        for row in rows:
            try:
                result = _json_loads(str(row["result_json"]))
            except json.JSONDecodeError:
                continue
            repaired = _repair_lookup_result_clusters(result, repaired_clusters)
            if repaired is None:
                continue
            conn.execute(
                """
                UPDATE lookup_results
                SET result_json = ?
                WHERE normalized_citation = ?
                """,
                (_json_dumps(repaired), str(row["normalized_citation"])),
            )

    def import_json_cache_once(self, cache: JsonCache) -> None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                ("json_cache_imported",),
            ).fetchone()
        if row is not None:
            return
        for entry in cache.list_case_entries():
            cluster_id = str(entry.get("cluster_id") or "").strip()
            if not cluster_id:
                continue
            cluster = cache.read_cached_cluster(cluster_id)
            if isinstance(cluster, dict):
                self.upsert_cluster(cluster)
                opinion_ids = entry.get("opinion_ids")
                if isinstance(opinion_ids, list):
                    for opinion_id in opinion_ids:
                        opinion = cache.read_resource("opinions", str(opinion_id))
                        if isinstance(opinion, dict):
                            self.upsert_opinion(opinion, cluster=cluster)
        with self.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("json_cache_imported", _utc_now()),
            )

    def upsert_lookup(
        self,
        citation: str,
        result: list[dict[str, Any]],
        *,
        normalized_already: bool = False,
    ) -> None:
        normalized = citation if normalized_already else normalize_citation(citation)
        if not normalized:
            return
        result = canonicalize_lookup_result(result)
        now = _utc_now()
        if official_citation_parts_from_text(normalized) is not None:
            result_for_lookup = _filter_lookup_result_to_official_citation(result, normalized)
            with self.connection() as conn:
                existing = conn.execute(
                    "SELECT added_at FROM lookup_results WHERE normalized_citation = ?",
                    (normalized.casefold(),),
                ).fetchone()
                if result_for_lookup:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO lookup_results(
                            normalized_citation, result_json, added_at, last_accessed
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            normalized.casefold(),
                            _json_dumps(result_for_lookup),
                            existing["added_at"] if existing else now,
                            now,
                        ),
                    )
                else:
                    conn.execute(
                        "DELETE FROM lookup_results WHERE normalized_citation = ?",
                        (normalized.casefold(),),
                    )
        for cluster in self.clusters_from_lookup(result):
            self.upsert_cluster(cluster)

    def read_lookup(self, citation: str) -> list[dict[str, Any]] | None:
        normalized = normalize_citation(citation).casefold()
        if not normalized:
            return None
        with self.connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM lookup_results WHERE normalized_citation = ?",
                (normalized,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE lookup_results SET last_accessed = ? WHERE normalized_citation = ?",
                    (_utc_now(), normalized),
                )
                data = _json_loads(str(row["result_json"]))
                if isinstance(data, list):
                    data = canonicalize_lookup_result(data)
                    if official_citation_parts_from_text(normalized) is not None:
                        data = _filter_lookup_result_to_official_citation(data, normalized)
                    filtered = _filter_lookup_result_for_citation(data, normalized)
                    if filtered or not _lookup_result_had_clusters(data):
                        return filtered
            alias_rows = conn.execute(
                """
                SELECT cases.cluster_json
                FROM citation_aliases
                JOIN cases ON cases.cluster_id = citation_aliases.cluster_id
                WHERE citation_aliases.normalized_citation = ?
                ORDER BY cases.title COLLATE NOCASE
                """,
                (normalized,),
            ).fetchall()
        clusters = []
        for alias_row in alias_rows:
            data = _json_loads(str(alias_row["cluster_json"]))
            if isinstance(data, dict) and _external_import_matches_lookup(data, normalized):
                clusters.append(data)
        if not clusters:
            return None
        return [{"status": 200, "clusters": clusters}]

    def upsert_cluster(self, cluster: dict[str, Any]) -> str:
        cluster = canonicalize_cluster_citations(cluster)
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            return ""
        title = _cluster_title(cluster)
        citation_text = _cluster_citation_line(cluster)
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT added_at, opinion_ids_json FROM cases WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO cases(
                    cluster_id, title, citation_text, cluster_json, opinion_ids_json, added_at, last_accessed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cluster_id,
                    title,
                    citation_text,
                    _json_dumps(cluster),
                    existing["opinion_ids_json"] if existing else "[]",
                    existing["added_at"] if existing else now,
                    now,
                ),
            )
        if citation_text:
            self.add_citation_alias(citation_text, cluster_id)
        return cluster_id

    def add_citation_alias(self, citation: str, cluster_id: str) -> None:
        normalized = normalize_citation(citation).casefold()
        if not normalized or not cluster_id:
            return
        with self.connection() as conn:
            row = conn.execute(
                "SELECT citation_text FROM cases WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT OR IGNORE INTO citation_aliases(normalized_citation, cluster_id, citation_text)
                VALUES (?, ?, ?)
                """,
                (normalized, cluster_id, str(row["citation_text"]) if row else citation),
            )

    def read_cluster(self, cluster_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT cluster_json FROM cases WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE cases SET last_accessed = ? WHERE cluster_id = ?",
                    (_utc_now(), cluster_id),
                )
        if row is None:
            return None
        data = _json_loads(str(row["cluster_json"]))
        return data if isinstance(data, dict) else None

    def upsert_opinion(self, opinion: dict[str, Any], *, cluster: dict[str, Any] | None = None) -> str:
        opinion_id = str(opinion.get("id") or resource_id_from_url(str(opinion.get("resource_uri", "")))).strip()
        if not opinion_id:
            return ""
        cluster_id = str(opinion.get("cluster_id") or "").strip()
        if not cluster_id:
            cluster_url = opinion.get("cluster")
            if isinstance(cluster_url, str) and cluster_url.strip():
                cluster_id = resource_id_from_url(cluster_url)
        if not cluster_id and cluster is not None:
            cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            cluster_id = ""
        display = opinion_display_text(opinion)
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT added_at FROM opinions WHERE opinion_id = ?",
                (opinion_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO opinions(
                    opinion_id, cluster_id, opinion_json, display_text, source_field, added_at, last_accessed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    opinion_id,
                    cluster_id,
                    _json_dumps(opinion),
                    display.text,
                    display.source_field,
                    existing["added_at"] if existing else now,
                    now,
                ),
            )
            conn.execute("DELETE FROM page_markers WHERE opinion_id = ?", (opinion_id,))
            conn.executemany(
                """
                INSERT INTO page_markers(
                    opinion_id, marker_index, page_label, marker_text, start_offset, end_offset, source_field
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        opinion_id,
                        index,
                        marker.page_label,
                        marker.marker_text,
                        marker.start_offset,
                        marker.end_offset,
                        marker.source_field,
                    )
                    for index, marker in enumerate(display.page_markers)
                ],
            )
        if cluster is not None:
            self.update_case_opinions(cluster, [opinion_id])
        elif cluster_id:
            self.update_case_opinion_ids(cluster_id, [opinion_id])
        return opinion_id

    def read_opinion(self, opinion_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT opinion_json FROM opinions WHERE opinion_id = ?",
                (opinion_id,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE opinions SET last_accessed = ? WHERE opinion_id = ?",
                    (_utc_now(), opinion_id),
                )
        if row is None:
            return None
        data = _json_loads(str(row["opinion_json"]))
        return data if isinstance(data, dict) else None

    def read_opinion_display(self, opinion_id: str) -> DisplayText | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT opinion_json, display_text, source_field FROM opinions WHERE opinion_id = ?",
                (opinion_id,),
            ).fetchone()
            if row is None:
                return None
            marker_rows = conn.execute(
                """
                SELECT page_label, marker_text, start_offset, end_offset, source_field
                FROM page_markers
                WHERE opinion_id = ?
                ORDER BY marker_index
                """,
                (opinion_id,),
            ).fetchall()
        try:
            opinion = _json_loads(str(row["opinion_json"]))
        except json.JSONDecodeError:
            opinion = None
        if isinstance(opinion, dict):
            display = opinion_display_text(opinion)
            if display.text:
                return display
        return normalize_display_quote_stacks(
            DisplayText(
                text=str(row["display_text"]),
                source_field=str(row["source_field"]),
                page_markers=[
                    PageMarker(
                        page_label=str(marker["page_label"]),
                        marker_text=str(marker["marker_text"]),
                        start_offset=int(marker["start_offset"]),
                        end_offset=int(marker["end_offset"]),
                        source_field=str(marker["source_field"]),
                    )
                    for marker in marker_rows
                ],
            )
        )

    def update_case_opinions(self, cluster: dict[str, Any], opinion_ids: list[str]) -> None:
        cluster_id = self.upsert_cluster(cluster)
        if cluster_id:
            self.update_case_opinion_ids(cluster_id, opinion_ids)

    def update_case_opinion_ids(self, cluster_id: str, opinion_ids: list[str]) -> None:
        clean_ids = [str(value).strip() for value in opinion_ids if str(value).strip()]
        if not clean_ids:
            return
        with self.connection() as conn:
            row = conn.execute(
                "SELECT opinion_ids_json FROM cases WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            if row is None:
                return
            existing_data = _json_loads(str(row["opinion_ids_json"]))
            existing = [str(value) for value in existing_data] if isinstance(existing_data, list) else []
            merged = list(dict.fromkeys([*existing, *clean_ids]))
            conn.execute(
                "UPDATE cases SET opinion_ids_json = ?, last_accessed = ? WHERE cluster_id = ?",
                (_json_dumps(merged), _utc_now(), cluster_id),
            )

    def read_case_opinion_ids(self, cluster_id: str) -> list[str]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT opinion_ids_json FROM cases WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE cases SET last_accessed = ? WHERE cluster_id = ?",
                    (_utc_now(), cluster_id),
                )
        if row is None:
            return []
        data = _json_loads(str(row["opinion_ids_json"]))
        if not isinstance(data, list):
            return []
        return [str(value).strip() for value in data if str(value).strip()]

    def list_case_entries(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT cluster_id, title, citation_text, cluster_json, opinion_ids_json, added_at, last_accessed
                FROM cases
                ORDER BY title COLLATE NOCASE, citation_text COLLATE NOCASE, cluster_id
                """
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            opinion_ids = _json_loads(str(row["opinion_ids_json"]))
            cluster = _json_loads(str(row["cluster_json"]))
            title = _cluster_title(cluster) if isinstance(cluster, dict) else str(row["title"])
            entries.append(
                {
                    "cluster_id": str(row["cluster_id"]),
                    "title": title,
                    "citation_text": str(row["citation_text"]),
                    "opinion_ids": opinion_ids if isinstance(opinion_ids, list) else [],
                    "added_at": str(row["added_at"]),
                    "last_accessed": str(row["last_accessed"]),
                }
            )
        return entries

    def saved_clusters(self) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for entry in self.list_case_entries():
            cluster = self.read_cluster(str(entry.get("cluster_id", "")))
            if cluster is not None:
                clusters.append(cluster)
        return clusters

    def save_research_set(
        self,
        name: str,
        cache: JsonCache,
        *,
        replace: bool = False,
    ) -> ResearchSet:
        clean_name = re.sub(r"\s+", " ", name.strip())
        normalized_name = _research_set_normalized_name(clean_name)
        if not normalized_name:
            raise ValueError("Research set name is required.")
        items = self._research_set_items_from_cache(cache)
        if not items:
            raise ValueError("Research Cache is empty.")
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT set_id, created_at FROM research_sets WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()
            if existing is not None and not replace:
                raise ValueError(f"Research set already exists: {clean_name}")
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO research_sets(name, normalized_name, created_at, updated_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (clean_name, normalized_name, now, now, now),
                )
                set_id = int(cursor.lastrowid)
            else:
                set_id = int(existing["set_id"])
                conn.execute("DELETE FROM research_set_items WHERE set_id = ?", (set_id,))
                conn.execute(
                    """
                    UPDATE research_sets
                    SET name = ?, normalized_name = ?, updated_at = ?, last_accessed = ?
                    WHERE set_id = ?
                    """,
                    (clean_name, normalized_name, now, now, set_id),
                )
            conn.executemany(
                """
                INSERT INTO research_set_items(
                    set_id, item_type, authority_id, title, citation, payload_json,
                    position, agent_selected, added_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        set_id,
                        item.item_type,
                        item.authority_id,
                        item.title,
                        item.citation,
                        _json_dumps(item.payload),
                        item.position,
                        1 if item.agent_selected else 0,
                        now,
                    )
                    for item in items
                ],
            )
        result = self.read_research_set(clean_name)
        if result is None:
            raise RuntimeError("Saved research set could not be read.")
        cache.set_active_research_set(result.set_id, result.name, dirty=False)
        return result

    def _research_set_items_from_cache(self, cache: JsonCache) -> list[ResearchSetItem]:
        items: list[ResearchSetItem] = []
        position = 0
        for entry in cache.list_case_entries():
            cluster_id = str(entry.get("cluster_id", "")).strip()
            if not cluster_id:
                continue
            cluster = cache.read_cached_cluster(cluster_id)
            if not isinstance(cluster, dict):
                continue
            cluster_payload = dict(cluster)
            cluster_payload.pop(RESEARCH_SET_SLIP_PAYLOAD_KEY, None)
            self.upsert_cluster(cluster_payload)
            case_number = _case_number_from_cluster_payload(cluster_payload)
            slip_payload = (
                cache.read_slip_opinion_payload(case_number)
                if case_number
                else None
            )
            research_set_payload = (
                {**cluster_payload, RESEARCH_SET_SLIP_PAYLOAD_KEY: slip_payload}
                if isinstance(slip_payload, dict)
                else cluster_payload
            )
            opinion_ids = [
                str(value).strip()
                for value in entry.get("opinion_ids", [])
                if str(value).strip()
            ] if isinstance(entry.get("opinion_ids"), list) else []
            saved_opinion_ids: list[str] = []
            for opinion_id in opinion_ids:
                opinion = cache.read_resource("opinions", opinion_id)
                if isinstance(opinion, dict):
                    saved_id = self.upsert_opinion(opinion, cluster=cluster_payload)
                    if saved_id:
                        saved_opinion_ids.append(saved_id)
            if saved_opinion_ids:
                self.update_case_opinion_ids(cluster_id, saved_opinion_ids)
            items.append(
                ResearchSetItem(
                    item_type="case",
                    authority_id=cluster_id,
                    title=str(entry.get("title") or _cluster_title(cluster_payload)),
                    citation=str(entry.get("citation_text") or _cluster_citation_line(cluster_payload)),
                    payload=research_set_payload,
                    position=position,
                    agent_selected=bool(entry.get("agent_selected")),
                )
            )
            position += 1
        for entry in cache.list_statute_entries():
            statute_id = str(entry.get("statute_id", "")).strip()
            if not statute_id:
                continue
            statute = cache.read_cached_statute(statute_id)
            if not isinstance(statute, dict):
                continue
            items.append(
                ResearchSetItem(
                    item_type="statute",
                    authority_id=statute_id,
                    title=str(entry.get("title") or statute.get("title") or ""),
                    citation=str(entry.get("citation") or statute.get("citation") or ""),
                    payload=statute,
                    position=position,
                    agent_selected=bool(entry.get("agent_selected")),
                )
            )
            position += 1
        for entry in cache.list_rule_entries():
            rule_id = str(entry.get("rule_id", "")).strip()
            if not rule_id:
                continue
            rule = cache.read_cached_rule(rule_id)
            if not isinstance(rule, dict):
                continue
            items.append(
                ResearchSetItem(
                    item_type="rule",
                    authority_id=rule_id,
                    title=str(entry.get("title") or rule.get("title") or ""),
                    citation=str(entry.get("citation") or rule.get("citation") or ""),
                    payload=rule,
                    position=position,
                    agent_selected=bool(entry.get("agent_selected")),
                )
            )
            position += 1
        for entry in cache.list_agent_answer_entries():
            answer_id = str(entry.get("answer_id", "")).strip()
            if not answer_id:
                continue
            answer = cache.read_agent_answer(answer_id)
            if not isinstance(answer, dict):
                continue
            items.append(
                ResearchSetItem(
                    item_type="agent_answer",
                    authority_id=answer_id,
                    title=str(entry.get("title") or answer.get("title") or "Saved agent answer"),
                    citation=str(entry.get("mode") or answer.get("mode") or ""),
                    payload=answer,
                    position=position,
                    agent_selected=bool(entry.get("agent_selected")),
                )
            )
            position += 1
        for entry in cache.list_prior_brief_entries():
            brief_id = str(entry.get("brief_id", "")).strip()
            if not brief_id:
                continue
            brief = cache.read_prior_brief(brief_id)
            if not isinstance(brief, dict):
                continue
            items.append(
                ResearchSetItem(
                    item_type="prior_brief",
                    authority_id=brief_id,
                    title=str(entry.get("title") or brief.get("title") or "Prior brief"),
                    citation=str(entry.get("document_date") or brief.get("document_date") or ""),
                    payload=brief,
                    position=position,
                    agent_selected=bool(entry.get("agent_selected")),
                )
            )
            position += 1
        return items

    def matching_research_set_for_cache(self, cache: JsonCache) -> ResearchSet | None:
        cache_signature = self._cache_research_set_signature(cache)
        if not cache_signature:
            return None
        for research_set in self.list_research_sets():
            candidate = self.read_research_set(research_set.set_id)
            if candidate is None:
                continue
            if self._research_set_signature(candidate.items) == cache_signature:
                cache.set_active_research_set(candidate.set_id, candidate.name, dirty=False)
                return candidate
        return None

    @staticmethod
    def _research_set_signature(items: list[ResearchSetItem]) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (item.item_type, item.authority_id)
                for item in items
                if item.item_type and item.authority_id
            )
        )

    @staticmethod
    def _cache_research_set_signature(cache: JsonCache) -> tuple[tuple[str, str], ...]:
        identifiers: list[tuple[str, str]] = []
        identifiers.extend(
            ("case", str(entry.get("cluster_id") or "").strip())
            for entry in cache.list_case_entries()
        )
        identifiers.extend(
            ("statute", str(entry.get("statute_id") or "").strip())
            for entry in cache.list_statute_entries()
        )
        identifiers.extend(
            ("rule", str(entry.get("rule_id") or "").strip())
            for entry in cache.list_rule_entries()
        )
        identifiers.extend(
            ("agent_answer", str(entry.get("answer_id") or "").strip())
            for entry in cache.list_agent_answer_entries()
        )
        identifiers.extend(
            ("prior_brief", str(entry.get("brief_id") or "").strip())
            for entry in cache.list_prior_brief_entries()
        )
        return tuple(sorted((item_type, authority_id) for item_type, authority_id in identifiers if authority_id))

    def list_research_sets(self) -> list[ResearchSet]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT set_id, name, created_at, updated_at, last_accessed
                FROM research_sets
                ORDER BY updated_at DESC, name COLLATE NOCASE
                """
            ).fetchall()
        sets: list[ResearchSet] = []
        for row in rows:
            research_set = self._research_set_from_row(row, include_items=False)
            if research_set is not None:
                sets.append(research_set)
        return sets

    def read_research_set(self, name_or_id: str | int) -> ResearchSet | None:
        with self.connection() as conn:
            if isinstance(name_or_id, int) or str(name_or_id).strip().isdigit():
                row = conn.execute(
                    """
                    SELECT set_id, name, created_at, updated_at, last_accessed
                    FROM research_sets
                    WHERE set_id = ?
                    """,
                    (int(name_or_id),),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT set_id, name, created_at, updated_at, last_accessed
                    FROM research_sets
                    WHERE normalized_name = ?
                    """,
                    (_research_set_normalized_name(str(name_or_id)),),
                ).fetchone()
        if row is None:
            return None
        return self._research_set_from_row(row, include_items=True)

    def _research_set_from_row(
        self,
        row: sqlite3.Row,
        *,
        include_items: bool,
    ) -> ResearchSet | None:
        set_id = int(row["set_id"])
        items = self._research_set_items(set_id) if include_items else []
        counts = self._research_set_counts(set_id)
        return ResearchSet(
            set_id=set_id,
            name=str(row["name"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_accessed=str(row["last_accessed"]),
            item_count=sum(counts.values()),
            case_count=counts.get("case", 0),
            statute_count=counts.get("statute", 0),
            rule_count=counts.get("rule", 0),
            agent_answer_count=counts.get("agent_answer", 0),
            prior_brief_count=counts.get("prior_brief", 0),
            items=items,
        )

    def _research_set_counts(self, set_id: int) -> dict[str, int]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT item_type, COUNT(*) AS count
                FROM research_set_items
                WHERE set_id = ?
                GROUP BY item_type
                """,
                (set_id,),
            ).fetchall()
        return {str(row["item_type"]): int(row["count"]) for row in rows}

    def _research_set_items(self, set_id: int) -> list[ResearchSetItem]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT item_type, authority_id, title, citation, payload_json,
                       position, agent_selected
                FROM research_set_items
                WHERE set_id = ?
                ORDER BY position, item_type, title COLLATE NOCASE
                """,
                (set_id,),
            ).fetchall()
        items: list[ResearchSetItem] = []
        for row in rows:
            try:
                payload = _json_loads(str(row["payload_json"]))
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            items.append(
                ResearchSetItem(
                    item_type=str(row["item_type"]),
                    authority_id=str(row["authority_id"]),
                    title=str(row["title"]),
                    citation=str(row["citation"]),
                    payload=payload,
                    position=int(row["position"]),
                    agent_selected=bool(row["agent_selected"]),
                )
            )
        return items

    def delete_research_set(self, name_or_id: str | int) -> bool:
        research_set = self.read_research_set(name_or_id)
        if research_set is None:
            return False
        with self.connection() as conn:
            conn.execute("DELETE FROM research_sets WHERE set_id = ?", (research_set.set_id,))
        return True

    def load_research_set_into_cache(self, name_or_id: str | int, cache: JsonCache) -> ResearchSet:
        research_set = self.read_research_set(name_or_id)
        if research_set is None:
            raise ValueError(f"Research set not found: {name_or_id}")
        with cache.suppress_dirty_tracking():
            cache.clear(
                preserve_reader_positions=True,
                preserve_reader_highlights=True,
            )
            for item in research_set.items:
                if item.item_type == "case":
                    cluster_payload = dict(item.payload)
                    slip_payload = cluster_payload.pop(RESEARCH_SET_SLIP_PAYLOAD_KEY, None)
                    cluster_id = cache.upsert_cluster(cluster_payload)
                    if isinstance(slip_payload, dict):
                        case_number = (
                            str(slip_payload.get("case_number") or "").strip()
                            or _case_number_from_cluster_payload(cluster_payload)
                        )
                        if case_number:
                            cache.write_slip_opinion_payload(case_number, slip_payload)
                    if item.agent_selected:
                        cache.set_agent_selected(cluster_id or item.authority_id, True)
                elif item.item_type == "statute":
                    statute_id = cache.upsert_statute(item.payload)
                    if item.agent_selected:
                        cache.set_statute_agent_selected(statute_id or item.authority_id, True)
                elif item.item_type == "rule":
                    rule_id = cache.upsert_rule(item.payload)
                    if item.agent_selected:
                        cache.set_rule_agent_selected(rule_id or item.authority_id, True)
                elif item.item_type == "agent_answer":
                    text = str(item.payload.get("text") or "").strip()
                    if not text:
                        continue
                    answer_id = cache.save_agent_answer(
                        text,
                        mode=str(item.payload.get("mode") or item.citation),
                        title=item.title,
                    )
                    if item.agent_selected:
                        cache.set_agent_answer_selected(answer_id or item.authority_id, True)
                elif item.item_type == "prior_brief":
                    brief_id = cache.upsert_prior_brief(item.payload)
                    if item.agent_selected:
                        cache.set_prior_brief_agent_selected(
                            brief_id or item.authority_id,
                            True,
                        )
        with self.connection() as conn:
            conn.execute(
                "UPDATE research_sets SET last_accessed = ? WHERE set_id = ?",
                (_utc_now(), research_set.set_id),
            )
        updated = self.read_research_set(research_set.set_id)
        if updated is None:
            raise RuntimeError("Loaded research set could not be read.")
        cache.set_active_research_set(updated.set_id, updated.name, dirty=False)
        return updated

    def official_pagination_audit(self) -> list[LibraryPruneCandidate]:
        from .quality import official_pagination_quality

        candidates: list[LibraryPruneCandidate] = []
        for entry in self.list_case_entries():
            cluster_id = str(entry.get("cluster_id") or "").strip()
            cluster = self.read_cluster(cluster_id) if cluster_id else None
            if cluster is None:
                continue
            opinion_ids = self.read_case_opinion_ids(cluster_id)
            opinions = [
                opinion
                for opinion_id in opinion_ids
                if (opinion := self.read_opinion(opinion_id)) is not None
            ]
            displays = [opinion_display_text(opinion) for opinion in opinions]
            quality = official_pagination_quality(cluster, displays)
            marker_count = sum(len(display.page_markers) for display in displays)
            candidates.append(
                LibraryPruneCandidate(
                    cluster_id=cluster_id,
                    title=str(entry.get("title") or _cluster_title(cluster)),
                    citation_text=str(entry.get("citation_text") or ""),
                    opinion_count=len(opinions),
                    marker_count=marker_count,
                    eligible=quality.eligible,
                    official_citation=quality.official_citation,
                    reason=quality.reason,
                )
            )
        return candidates

    def prune_ineligible_official_pagination(
        self,
        *,
        create_backup: bool = True,
    ) -> LibraryPruneResult:
        candidates = self.official_pagination_audit()
        pruned = [candidate for candidate in candidates if not candidate.eligible]
        backup_path = self.backup() if create_backup and pruned else None
        self._delete_cases_and_lookup_references([candidate.cluster_id for candidate in pruned])
        return LibraryPruneResult(
            backup_path=backup_path,
            pruned=pruned,
            kept_count=len(candidates) - len(pruned),
        )

    def backup(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup_path = self.path.with_name(f"{self.path.stem}.backup-{timestamp}{self.path.suffix}")
        suffix = 1
        while backup_path.exists():
            backup_path = self.path.with_name(
                f"{self.path.stem}.backup-{timestamp}-{suffix}{self.path.suffix}"
            )
            suffix += 1
        source = self.connect()
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return backup_path

    def _delete_cases_and_lookup_references(self, cluster_ids: list[str]) -> None:
        prune_ids = {str(cluster_id).strip() for cluster_id in cluster_ids if str(cluster_id).strip()}
        if not prune_ids:
            return
        with self.connection() as conn:
            self._rewrite_lookup_results_for_deleted_clusters(conn, prune_ids)
            opinion_ids = self._opinion_ids_for_deleted_clusters(conn, prune_ids)
            if opinion_ids:
                opinion_placeholders = ",".join("?" for _ in opinion_ids)
                conn.execute(
                    f"DELETE FROM page_markers WHERE opinion_id IN ({opinion_placeholders})",
                    tuple(opinion_ids),
                )
                conn.execute(
                    f"DELETE FROM opinions WHERE opinion_id IN ({opinion_placeholders})",
                    tuple(opinion_ids),
                )
            case_placeholders = ",".join("?" for _ in prune_ids)
            conn.execute(
                f"DELETE FROM citation_aliases WHERE cluster_id IN ({case_placeholders})",
                tuple(prune_ids),
            )
            conn.execute(
                f"DELETE FROM cases WHERE cluster_id IN ({case_placeholders})",
                tuple(prune_ids),
            )

    def _opinion_ids_for_deleted_clusters(
        self,
        conn: sqlite3.Connection,
        prune_ids: set[str],
    ) -> set[str]:
        case_placeholders = ",".join("?" for _ in prune_ids)
        rows = conn.execute(
            f"SELECT opinion_ids_json FROM cases WHERE cluster_id IN ({case_placeholders})",
            tuple(prune_ids),
        ).fetchall()
        candidate_opinion_ids: set[str] = set()
        for row in rows:
            values = _json_loads(str(row["opinion_ids_json"]))
            if isinstance(values, list):
                candidate_opinion_ids.update(str(value).strip() for value in values if str(value).strip())
        opinion_rows = conn.execute(
            f"SELECT opinion_id FROM opinions WHERE cluster_id IN ({case_placeholders})",
            tuple(prune_ids),
        ).fetchall()
        candidate_opinion_ids.update(str(row["opinion_id"]) for row in opinion_rows)
        remaining_rows = conn.execute(
            f"SELECT opinion_ids_json FROM cases WHERE cluster_id NOT IN ({case_placeholders})",
            tuple(prune_ids),
        ).fetchall()
        shared_opinion_ids: set[str] = set()
        for row in remaining_rows:
            values = _json_loads(str(row["opinion_ids_json"]))
            if isinstance(values, list):
                shared_opinion_ids.update(str(value).strip() for value in values if str(value).strip())
        return candidate_opinion_ids - shared_opinion_ids

    def _rewrite_lookup_results_for_deleted_clusters(
        self,
        conn: sqlite3.Connection,
        prune_ids: set[str],
    ) -> None:
        rows = conn.execute(
            "SELECT normalized_citation, result_json FROM lookup_results"
        ).fetchall()
        for row in rows:
            data = _json_loads(str(row["result_json"]))
            if not isinstance(data, list):
                continue
            changed = False
            kept_any_cluster = False
            rewritten: list[Any] = []
            for item in data:
                if not isinstance(item, dict):
                    rewritten.append(item)
                    continue
                clusters = item.get("clusters")
                if not isinstance(clusters, list):
                    rewritten.append(item)
                    continue
                kept_clusters = [
                    cluster
                    for cluster in clusters
                    if not (
                        isinstance(cluster, dict)
                        and cluster_id_from_cluster(cluster) in prune_ids
                    )
                ]
                if len(kept_clusters) != len(clusters):
                    changed = True
                if kept_clusters:
                    kept_any_cluster = True
                rewritten.append({**item, "clusters": kept_clusters})
            if not changed:
                continue
            normalized = str(row["normalized_citation"])
            if kept_any_cluster:
                conn.execute(
                    "UPDATE lookup_results SET result_json = ?, last_accessed = ? WHERE normalized_citation = ?",
                    (_json_dumps(rewritten), _utc_now(), normalized),
                )
            else:
                conn.execute(
                    "DELETE FROM lookup_results WHERE normalized_citation = ?",
                    (normalized,),
                )

    @staticmethod
    def clusters_from_lookup(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for citation_result in result:
            values = citation_result.get("clusters")
            if isinstance(values, list):
                clusters.extend(cluster for cluster in values if isinstance(cluster, dict))
        return clusters
