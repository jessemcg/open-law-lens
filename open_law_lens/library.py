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
    def __init__(self, source_field: str) -> None:
        super().__init__()
        self.source_field = source_field
        self.parts: list[str] = []
        self.page_markers: list[PageMarker] = []
        self._page_label: str | None = None
        self._page_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "page-number":
            attr_map = dict(attrs)
            label = attr_map.get("label")
            self._page_label = label.strip() if isinstance(label, str) else ""
            self._page_text_parts = []
            return
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "page-number" and self._page_label is not None:
            raw_text = html.unescape("".join(self._page_text_parts)).strip()
            label = self._page_label or raw_text.lstrip("*").strip()
            if label:
                marker_text = f"[*{label}]"
                start = len("".join(self.parts))
                self.parts.append(marker_text)
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
            return
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._page_label is not None:
            self._page_text_parts.append(data)
            return
        self.parts.append(data)

    def display_text(self) -> DisplayText:
        text, markers = _normalize_text_and_markers("".join(self.parts), self.page_markers)
        return DisplayText(text=text, source_field=self.source_field, page_markers=markers)


def _normalize_text_and_markers(
    raw_text: str,
    raw_markers: list[PageMarker],
) -> tuple[str, list[PageMarker]]:
    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[ \t\r\f\v]+", raw_text):
        replacements.append((match.start(), match.end(), " "))
    for match in re.finditer(r"\n{3,}", raw_text):
        replacements.append((match.start(), match.end(), "\n\n"))
    leading = len(raw_text) - len(raw_text.lstrip())
    trailing_end = len(raw_text.rstrip())
    if leading:
        replacements.append((0, leading, ""))
    if trailing_end < len(raw_text):
        replacements.append((trailing_end, len(raw_text), ""))
    replacements.sort(key=lambda item: item[0])

    parts: list[str] = []
    marker_positions = {index: marker for index, marker in enumerate(raw_markers)}
    marker_cursors: dict[int, int] = {}
    cursor = 0
    output_len = 0
    for start, end, replacement in replacements:
        if start < cursor:
            continue
        unchanged = raw_text[cursor:start]
        parts.append(unchanged)
        for marker_index, marker in marker_positions.items():
            if cursor <= marker.start_offset < start:
                marker_cursors[marker_index] = output_len + (marker.start_offset - cursor)
        output_len += len(unchanged)
        parts.append(replacement)
        for marker_index, marker in marker_positions.items():
            if start <= marker.start_offset < end:
                marker_cursors[marker_index] = output_len
        output_len += len(replacement)
        cursor = end
    tail = raw_text[cursor:]
    parts.append(tail)
    for marker_index, marker in marker_positions.items():
        if marker_index not in marker_cursors and cursor <= marker.start_offset <= len(raw_text):
            marker_cursors[marker_index] = output_len + (marker.start_offset - cursor)
    normalized = "".join(parts)
    markers: list[PageMarker] = []
    for marker_index, marker in enumerate(raw_markers):
        start = marker_cursors.get(marker_index)
        if start is None:
            continue
        end = start + len(marker.marker_text)
        if normalized[start:end] != marker.marker_text:
            found = normalized.find(marker.marker_text, max(0, start - 4), end + 4)
            if found >= 0:
                start = found
                end = found + len(marker.marker_text)
        markers.append(
            PageMarker(
                page_label=marker.page_label,
                marker_text=marker.marker_text,
                start_offset=start,
                end_offset=end,
                source_field=marker.source_field,
            )
        )
    return normalized, markers


def opinion_display_text(opinion: dict[str, Any]) -> DisplayText:
    for field in TEXT_FIELDS:
        value = opinion.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if field.startswith("html") or field.startswith("xml"):
            parser = _DisplayTextExtractor(field)
            parser.feed(value)
            parser.close()
            return parser.display_text()
        text = value.strip()
        return DisplayText(text=text, source_field=field, page_markers=[])
    return DisplayText(text="", source_field="", page_markers=[])


@dataclass
class CaseLibrary:
    path: Path

    @classmethod
    def default(cls) -> "CaseLibrary":
        library = cls(library_db_path())
        library.ensure()
        library.import_json_cache_once(JsonCache.default())
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
                return data if isinstance(data, list) else None
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
            if isinstance(data, dict):
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
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                pieces = [
                    str(piece).strip()
                    for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
                    if str(piece).strip()
                ]
                if pieces:
                    self.add_citation_alias(" ".join(pieces), cluster_id)
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
                "SELECT display_text, source_field FROM opinions WHERE opinion_id = ?",
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
