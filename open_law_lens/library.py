from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator

from .cache import JsonCache, cluster_id_from_cluster, normalize_citation, resource_id_from_url
from .case_titles import cluster_short_title_value
from .import_text import clean_imported_opinion_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_LIBRARY_DIR = PROJECT_ROOT / "library"
DEFAULT_LIBRARY_DB = PROJECT_LIBRARY_DIR / "open_law_lens.sqlite3"
SCHEMA_VERSION = "1"
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


def _cluster_title(cluster: dict[str, Any]) -> str:
    title = cluster_short_title_value(cluster)
    if title:
        return title
    cluster_id = cluster_id_from_cluster(cluster)
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def _cluster_citation_line(cluster: dict[str, Any]) -> str:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return ""
    rendered: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        pieces = [
            str(piece).strip()
            for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
            if str(piece).strip()
        ]
        if pieces:
            rendered.append(" ".join(pieces))
    return "; ".join(rendered)


def _citation_text_from_dict(citation: dict[str, Any]) -> str:
    pieces = [
        str(piece).strip()
        for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
        if str(piece).strip()
    ]
    return " ".join(pieces)


def _citation_lookup_key(citation: str) -> str:
    return re.sub(r"\s+", "", normalize_citation(citation)).casefold()


def _external_import_primary_citation_key(cluster: dict[str, Any]) -> str:
    if cluster.get("source_type") != "user_imported_external_case":
        return ""
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return ""
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        text = _citation_text_from_dict(citation)
        if text:
            return _citation_lookup_key(text)
    return ""


def _external_import_matches_lookup(cluster: dict[str, Any], normalized_citation: str) -> bool:
    primary = _external_import_primary_citation_key(cluster)
    return not primary or primary == _citation_lookup_key(normalized_citation)


def _filter_lookup_result_for_citation(
    result: list[dict[str, Any]],
    normalized_citation: str,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        clusters = item.get("clusters")
        if not isinstance(clusters, list):
            filtered.append(item)
            continue
        kept = [
            cluster
            for cluster in clusters
            if isinstance(cluster, dict) and _external_import_matches_lookup(cluster, normalized_citation)
        ]
        if kept:
            filtered.append({**item, "clusters": kept})
    return filtered


def _lookup_result_had_clusters(result: list[dict[str, Any]]) -> bool:
    return any(isinstance(item.get("clusters"), list) and bool(item.get("clusters")) for item in result)


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
            return _normalize_raw_star_page_markers(parser.display_text())
        text = decode_cp1252_control_chars(value).strip()
        return _normalize_raw_star_page_markers(
            DisplayText(text=text, source_field=field, page_markers=[])
        )
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

                CREATE INDEX IF NOT EXISTS idx_cases_title ON cases(title);
                CREATE INDEX IF NOT EXISTS idx_opinions_cluster_id ON opinions(cluster_id);
                CREATE INDEX IF NOT EXISTS idx_aliases_citation ON citation_aliases(normalized_citation);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
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
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT added_at FROM lookup_results WHERE normalized_citation = ?",
                (normalized.casefold(),),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO lookup_results(
                    normalized_citation, result_json, added_at, last_accessed
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    normalized.casefold(),
                    _json_dumps(result),
                    existing["added_at"] if existing else now,
                    now,
                ),
            )
        for cluster in self.clusters_from_lookup(result):
            self.upsert_cluster(cluster)
            cluster_id = cluster_id_from_cluster(cluster)
            if cluster_id:
                self.add_citation_alias(normalized, cluster_id)

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
        citations = cluster.get("citations")
        if isinstance(citations, list):
            for index, citation in enumerate(citations):
                if not isinstance(citation, dict):
                    continue
                if cluster.get("source_type") == "user_imported_external_case" and index > 0:
                    continue
                text = _citation_text_from_dict(citation)
                if text:
                    self.add_citation_alias(text, cluster_id)
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
        return DisplayText(
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

    @staticmethod
    def clusters_from_lookup(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for citation_result in result:
            values = citation_result.get("clusters")
            if isinstance(values, list):
                clusters.extend(cluster for cluster in values if isinstance(cluster, dict))
        return clusters
