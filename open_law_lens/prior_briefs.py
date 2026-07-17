from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator, Literal, Mapping
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIOR_BRIEFS_DIR = PROJECT_ROOT / "prior_briefs"
DEFAULT_PRIOR_BRIEFS_DB = PROJECT_ROOT / "library" / "prior_briefs.sqlite3"
SCHEMA_VERSION = "2"
TEXT_VERSION = "pandoc-plain-headings-v3"
CASE_NUMBER_RE = re.compile(r"(?<![A-Z0-9])([A-Z]\d{6})(?!\d)", re.IGNORECASE)
DATED_LINE_RE = re.compile(
    r"(?im)^\s*(?:\[\])?\s*Dated\s*:\s*(?P<value>[^\n]{1,80}?)(?=\s+By\s*:|\s*$)"
)
NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
MONTH_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(20\d{2})\b",
    re.IGNORECASE,
)
MONTHS = {
    name.casefold(): index
    for index, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
STYLE_NS = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
STYLE_NAME = f"{{{STYLE_NS}}}name"
STYLE_DISPLAY_NAME = f"{{{STYLE_NS}}}display-name"
STYLE_PARENT_NAME = f"{{{STYLE_NS}}}parent-style-name"
TEXT_STYLE_NAME = f"{{{TEXT_NS}}}style-name"
TEXT_PARAGRAPH = f"{{{TEXT_NS}}}p"
HEADING_STYLE_RE = re.compile(r"^Heading(?:\s+|_20_)(10|[1-9])$", re.IGNORECASE)


class PriorBriefError(RuntimeError):
    pass


def prior_briefs_dir() -> Path:
    value = os.environ.get("OPEN_LAW_LENS_PRIOR_BRIEFS_DIR")
    return Path(value).expanduser() if value else DEFAULT_PRIOR_BRIEFS_DIR


def prior_briefs_db_path() -> Path:
    value = os.environ.get("OPEN_LAW_LENS_PRIOR_BRIEFS_DB")
    return Path(value).expanduser() if value else DEFAULT_PRIOR_BRIEFS_DB


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def brief_id_for_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PriorBriefHeading:
    level: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class PriorBriefExtraction:
    text: str
    headings: tuple[PriorBriefHeading, ...] = ()


def _pandoc_executable() -> str:
    executable = shutil.which("pandoc")
    if executable is None:
        raise PriorBriefError("Prior brief indexing requires the pandoc command.")
    return executable


def _run_pandoc(
    arguments: list[str],
    *,
    source_name: str,
    input_text: str | None = None,
) -> str:
    try:
        completed = subprocess.run(
            [_pandoc_executable(), *arguments],
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PriorBriefError(f"Could not extract {source_name}: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "pandoc failed").strip()
        raise PriorBriefError(f"Could not extract {source_name}: {message}")
    return completed.stdout


def _normalize_plain_text(text: str, *, source_name: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise PriorBriefError(f"No text was extracted from {source_name}.")
    return text


def _plain_text_from_odt(path: Path) -> str:
    return _normalize_plain_text(
        _run_pandoc(
            ["-f", "odt", "-t", "plain", "--wrap=none", str(path)],
            source_name=path.name,
        ),
        source_name=path.name,
    )


def _marker_pair(prefix: str, index: int) -> tuple[str, str]:
    return (f"{prefix}S{index}X", f"{prefix}E{index}X")


def _mark_pandoc_headers(
    value: Any,
    *,
    prefix: str,
    levels: list[int],
) -> None:
    if isinstance(value, dict):
        if value.get("t") == "Header":
            contents = value.get("c")
            if (
                isinstance(contents, list)
                and len(contents) == 3
                and isinstance(contents[0], int)
                and isinstance(contents[2], list)
                and contents[2]
            ):
                level = int(contents[0])
                if 1 <= level <= 10:
                    index = len(levels)
                    start_marker, end_marker = _marker_pair(prefix, index)
                    contents[2].insert(0, {"t": "Str", "c": start_marker})
                    contents[2].append({"t": "Str", "c": end_marker})
                    levels.append(level)
        for child in value.values():
            _mark_pandoc_headers(child, prefix=prefix, levels=levels)
    elif isinstance(value, list):
        for child in value:
            _mark_pandoc_headers(child, prefix=prefix, levels=levels)


def _decode_marked_plain_text(
    marked_text: str,
    *,
    prefix: str,
    levels: list[int],
    source_name: str,
    strip_heading_edges: bool = False,
) -> PriorBriefExtraction:
    marked_text = _normalize_plain_text(marked_text, source_name=source_name)
    parts: list[str] = []
    headings: list[PriorBriefHeading] = []
    cursor = 0
    clean_length = 0
    for index, level in enumerate(levels):
        start_marker, end_marker = _marker_pair(prefix, index)
        if marked_text.count(start_marker) != 1 or marked_text.count(end_marker) != 1:
            raise PriorBriefError(
                f"Could not extract {source_name}: heading markers were not preserved."
            )
        start = marked_text.find(start_marker, cursor)
        end = marked_text.find(end_marker, start + len(start_marker))
        if start < cursor or end < 0:
            raise PriorBriefError(
                f"Could not extract {source_name}: heading markers were out of order."
            )
        before = marked_text[cursor:start]
        heading_text = marked_text[start + len(start_marker):end]
        if strip_heading_edges:
            heading_text = heading_text.strip()
        parts.append(before)
        clean_length += len(before)
        start_offset = clean_length
        parts.append(heading_text)
        clean_length += len(heading_text)
        if heading_text.strip():
            headings.append(
                PriorBriefHeading(level, start_offset, clean_length)
            )
        cursor = end + len(end_marker)
    parts.append(marked_text[cursor:])
    text = "".join(parts)
    if prefix in text:
        raise PriorBriefError(
            f"Could not extract {source_name}: a heading marker leaked into the text."
        )
    return PriorBriefExtraction(text=text, headings=tuple(headings))


def _heading_level_from_style(
    style_name: str,
    styles: Mapping[str, tuple[str, str]],
) -> int | None:
    visited: set[str] = set()
    current = style_name
    while current and current not in visited:
        visited.add(current)
        display_name, parent_name = styles.get(current, ("", ""))
        for candidate in (display_name, current):
            match = HEADING_STYLE_RE.fullmatch(candidate.strip())
            if match is not None:
                return int(match.group(1))
        current = parent_name
    return None


def _style_only_heading_extraction(
    path: Path,
    *,
    baseline_text: str,
    prefix: str,
) -> PriorBriefExtraction | None:
    try:
        with zipfile.ZipFile(path) as archive:
            content_bytes = archive.read("content.xml")
            styles_bytes = archive.read("styles.xml")
            content_root = ElementTree.fromstring(content_bytes)
            style_roots = (content_root, ElementTree.fromstring(styles_bytes))
            styles: dict[str, tuple[str, str]] = {}
            for root in style_roots:
                for element in root.iter(f"{{{STYLE_NS}}}style"):
                    name = element.get(STYLE_NAME, "").strip()
                    if not name:
                        continue
                    styles[name] = (
                        element.get(STYLE_DISPLAY_NAME, "").strip(),
                        element.get(STYLE_PARENT_NAME, "").strip(),
                    )
            marked_levels: list[int] = []
            for paragraph in content_root.iter(TEXT_PARAGRAPH):
                level = _heading_level_from_style(
                    paragraph.get(TEXT_STYLE_NAME, "").strip(),
                    styles,
                )
                if level is None:
                    continue
                index = len(marked_levels)
                start_marker, end_marker = _marker_pair(prefix, index)
                paragraph.text = start_marker + (paragraph.text or "")
                if len(paragraph):
                    last_child = paragraph[-1]
                    last_child.tail = (last_child.tail or "") + end_marker
                else:
                    paragraph.text = (paragraph.text or "") + end_marker
                marked_levels.append(level)
            if not marked_levels:
                return None
            marked_content = ElementTree.tostring(
                content_root,
                encoding="utf-8",
                xml_declaration=True,
            )
            with tempfile.TemporaryDirectory(prefix="open-law-lens-brief-") as temp_dir:
                marked_path = Path(temp_dir) / path.name
                with zipfile.ZipFile(marked_path, "w") as output:
                    for entry in archive.infolist():
                        data = (
                            marked_content
                            if entry.filename == "content.xml"
                            else archive.read(entry)
                        )
                        output.writestr(entry, data)
                marked_plain = _run_pandoc(
                    ["-f", "odt", "-t", "plain", "--wrap=none", str(marked_path)],
                    source_name=path.name,
                )
    except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise PriorBriefError(f"Could not inspect headings in {path.name}: {exc}") from exc
    extraction = _decode_marked_plain_text(
        marked_plain,
        prefix=prefix,
        levels=marked_levels,
        source_name=path.name,
        strip_heading_edges=True,
    )
    if extraction.text != baseline_text:
        mismatch = next(
            (
                index
                for index, (actual, expected) in enumerate(
                    zip(extraction.text, baseline_text, strict=False)
                )
                if actual != expected
            ),
            min(len(extraction.text), len(baseline_text)),
        )
        raise PriorBriefError(
            f"Could not extract {path.name}: heading instrumentation changed the text "
            f"at character {mismatch}."
        )
    return extraction


def extract_prior_brief_document(path: Path) -> PriorBriefExtraction:
    baseline_text = _plain_text_from_odt(path)
    pandoc_json_text = _run_pandoc(
        ["-f", "odt", "-t", "json", str(path)],
        source_name=path.name,
    )
    try:
        pandoc_document = json.loads(pandoc_json_text)
    except json.JSONDecodeError as exc:
        raise PriorBriefError(f"Could not extract {path.name}: invalid Pandoc JSON.") from exc
    prefix = f"OLLH{uuid.uuid4().hex}"
    if prefix in pandoc_json_text or prefix in baseline_text:
        raise PriorBriefError(f"Could not extract {path.name}: heading marker collision.")
    marked_document = deepcopy(pandoc_document)
    levels: list[int] = []
    _mark_pandoc_headers(marked_document, prefix=prefix, levels=levels)
    if not levels:
        fallback = _style_only_heading_extraction(
            path,
            baseline_text=baseline_text,
            prefix=prefix,
        )
        return fallback or PriorBriefExtraction(text=baseline_text)
    marked_plain = _run_pandoc(
        ["-f", "json", "-t", "plain", "--wrap=none"],
        source_name=path.name,
        input_text=json.dumps(marked_document, ensure_ascii=False),
    )
    extraction = _decode_marked_plain_text(
        marked_plain,
        prefix=prefix,
        levels=levels,
        source_name=path.name,
    )
    if extraction.text != baseline_text:
        raise PriorBriefError(
            f"Could not extract {path.name}: heading instrumentation changed the text."
        )
    return extraction


def extract_prior_brief_text(path: Path) -> str:
    return extract_prior_brief_document(path).text


def document_date_from_text(text: str) -> date | None:
    parsed: list[date] = []
    for match in DATED_LINE_RE.finditer(text):
        value = match.group("value")
        numeric = NUMERIC_DATE_RE.search(value)
        if numeric is not None:
            try:
                parsed.append(date(int(numeric.group(3)), int(numeric.group(1)), int(numeric.group(2))))
            except ValueError:
                pass
            continue
        named = MONTH_DATE_RE.search(value)
        if named is not None:
            try:
                parsed.append(
                    date(
                        int(named.group(3)),
                        MONTHS[named.group(1).casefold()],
                        int(named.group(2)),
                    )
                )
            except ValueError:
                pass
    return parsed[-1] if parsed else None


def document_type_from_name(name: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9]+", "_", name).upper()
    tokens = {token for token in compact.split("_") if token}
    if "PHOENIXHMEMO" in compact or {"PHOENIX", "MEMO"} <= tokens:
        return "Phoenix H. memo"
    labels = (
        ("AOB", "Appellant's opening brief"),
        ("ARB", "Appellant's reply brief"),
        ("RB", "Respondent's brief"),
        ("OPP", "Opposition"),
    )
    for token, label in labels:
        if token in tokens:
            return label
    return "Prior brief"


@dataclass(frozen=True)
class PriorBrief:
    brief_id: str
    relative_path: str
    source_path: str
    title: str
    case_number: str
    document_type: str
    document_date: str
    date_source: str
    text: str
    sha256: str
    file_size: int
    file_mtime_ns: int
    indexed_at: str
    heading_spans: tuple[PriorBriefHeading, ...] = ()

    def to_json(self, *, include_text: bool = True) -> dict[str, object]:
        payload = asdict(self)
        payload["heading_spans"] = [asdict(heading) for heading in self.heading_spans]
        if not include_text:
            payload.pop("text", None)
            payload.pop("heading_spans", None)
            payload["text_length"] = len(self.text)
            payload["heading_count"] = len(self.heading_spans)
        return payload

    @classmethod
    def from_json(cls, payload: Mapping[str, object]) -> "PriorBrief":
        brief_id = str(payload.get("brief_id") or "").strip()
        text = str(payload.get("text") or "")
        if not brief_id or not text.strip():
            raise ValueError("Prior brief payload requires an ID and text.")
        headings = _headings_from_json(payload.get("heading_spans"), len(text))
        return cls(
            brief_id=brief_id,
            relative_path=str(payload.get("relative_path") or ""),
            source_path=str(payload.get("source_path") or ""),
            title=str(payload.get("title") or ""),
            case_number=str(payload.get("case_number") or ""),
            document_type=str(payload.get("document_type") or "Prior brief"),
            document_date=str(payload.get("document_date") or ""),
            date_source=str(payload.get("date_source") or ""),
            text=text,
            sha256=str(payload.get("sha256") or ""),
            file_size=_safe_int(payload.get("file_size")),
            file_mtime_ns=_safe_int(payload.get("file_mtime_ns")),
            indexed_at=str(payload.get("indexed_at") or ""),
            heading_spans=headings,
        )


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _headings_from_json(
    value: object,
    text_length: int,
) -> tuple[PriorBriefHeading, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    headings: list[PriorBriefHeading] = []
    previous_end = 0
    for item in value:
        if not isinstance(item, Mapping):
            continue
        level = _safe_int(item.get("level"))
        start_offset = _safe_int(item.get("start_offset"))
        end_offset = _safe_int(item.get("end_offset"))
        if (
            not 1 <= level <= 10
            or start_offset < previous_end
            or start_offset < 0
            or end_offset <= start_offset
            or end_offset > text_length
        ):
            continue
        headings.append(PriorBriefHeading(level, start_offset, end_offset))
        previous_end = end_offset
    return tuple(headings)


def _headings_json(headings: tuple[PriorBriefHeading, ...]) -> str:
    return json.dumps([asdict(heading) for heading in headings], separators=(",", ":"))


def _json_value(value: str) -> object:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []


@dataclass(frozen=True)
class PriorBriefSearchResult:
    brief_id: str
    title: str
    case_number: str
    document_type: str
    document_date: str
    date_source: str
    relative_path: str
    snippet: str
    source_link: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PriorBriefSyncResult:
    total: int
    added: int
    updated: int
    removed: int
    unchanged: int
    errors: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class PriorBriefLibrary:
    source_dir: Path
    path: Path

    @classmethod
    def default(cls) -> "PriorBriefLibrary":
        library = cls(prior_briefs_dir(), prior_briefs_db_path())
        library.ensure()
        return library

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
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
                CREATE TABLE IF NOT EXISTS briefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brief_id TEXT NOT NULL UNIQUE,
                    relative_path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    case_number TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    document_date TEXT NOT NULL,
                    date_source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_mtime_ns INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL,
                    text_version TEXT NOT NULL DEFAULT '',
                    heading_spans_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS briefs_fts USING fts5(
                    title,
                    case_number,
                    document_type,
                    text,
                    content='briefs',
                    content_rowid='id',
                    tokenize='unicode61'
                );
                CREATE INDEX IF NOT EXISTS idx_briefs_document_date
                ON briefs(document_date DESC);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("text_version", TEXT_VERSION),
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(briefs)").fetchall()
            }
            if "text_version" not in columns:
                conn.execute(
                    "ALTER TABLE briefs ADD COLUMN text_version TEXT NOT NULL DEFAULT ''"
                )
            if "heading_spans_json" not in columns:
                conn.execute(
                    "ALTER TABLE briefs ADD COLUMN heading_spans_json "
                    "TEXT NOT NULL DEFAULT '[]'"
                )

    def sync(self) -> PriorBriefSyncResult:
        self.ensure()
        self.source_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            (path for path in self.source_dir.rglob("*.odt") if path.is_file()),
            key=lambda path: path.relative_to(self.source_dir).as_posix().casefold(),
        )
        added = updated = unchanged = 0
        errors: list[str] = []
        now = _utc_now()
        with self.connection() as conn:
            existing = {
                str(row["relative_path"]): row
                for row in conn.execute("SELECT * FROM briefs").fetchall()
            }
            current_paths: set[str] = set()
            for source_path in files:
                relative_path = source_path.relative_to(self.source_dir).as_posix()
                current_paths.add(relative_path)
                try:
                    digest = _sha256(source_path)
                except OSError as exc:
                    errors.append(f"{relative_path}: {exc}")
                    continue
                old = existing.get(relative_path)
                if (
                    old is not None
                    and str(old["sha256"]) == digest
                    and str(old["text_version"]) == TEXT_VERSION
                ):
                    unchanged += 1
                    continue
                try:
                    extraction = extract_prior_brief_document(source_path)
                except PriorBriefError as exc:
                    errors.append(str(exc))
                    continue
                text = extraction.text
                stat = source_path.stat()
                parsed_date = document_date_from_text(text)
                if parsed_date is None:
                    parsed_date = datetime.fromtimestamp(stat.st_mtime, UTC).date()
                    date_source = "file_mtime"
                else:
                    date_source = "document_signature"
                title = source_path.stem
                case_match = CASE_NUMBER_RE.search(title)
                values = (
                    brief_id_for_relative_path(relative_path),
                    relative_path,
                    title,
                    case_match.group(1).upper() if case_match else "",
                    document_type_from_name(title),
                    parsed_date.isoformat(),
                    date_source,
                    text,
                    digest,
                    stat.st_size,
                    stat.st_mtime_ns,
                    now,
                    TEXT_VERSION,
                    _headings_json(extraction.headings),
                )
                if old is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO briefs(
                            brief_id, relative_path, title, case_number, document_type,
                            document_date, date_source, text, sha256, file_size,
                            file_mtime_ns, indexed_at, text_version, heading_spans_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                    row_id = int(cursor.lastrowid)
                    added += 1
                else:
                    row_id = int(old["id"])
                    conn.execute("DELETE FROM briefs_fts WHERE rowid = ?", (row_id,))
                    conn.execute(
                        """
                        UPDATE briefs SET
                            brief_id = ?, relative_path = ?, title = ?, case_number = ?,
                            document_type = ?, document_date = ?, date_source = ?, text = ?,
                            sha256 = ?, file_size = ?, file_mtime_ns = ?, indexed_at = ?,
                            text_version = ?, heading_spans_json = ?
                        WHERE id = ?
                        """,
                        (*values, row_id),
                    )
                    updated += 1
                conn.execute(
                    "INSERT INTO briefs_fts(rowid, title, case_number, document_type, text) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (row_id, title, case_match.group(1).upper() if case_match else "", document_type_from_name(title), text),
                )
            removed_paths = sorted(set(existing) - current_paths)
            for relative_path in removed_paths:
                row_id = int(existing[relative_path]["id"])
                conn.execute("DELETE FROM briefs_fts WHERE rowid = ?", (row_id,))
                conn.execute("DELETE FROM briefs WHERE id = ?", (row_id,))
        return PriorBriefSyncResult(
            total=len(files),
            added=added,
            updated=updated,
            removed=len(removed_paths),
            unchanged=unchanged,
            errors=tuple(errors),
        )

    def count(self) -> int:
        self.ensure()
        with self.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0])

    def list_briefs(self) -> list[PriorBrief]:
        self.ensure()
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM briefs ORDER BY document_date DESC, title COLLATE NOCASE"
            ).fetchall()
        return [self._brief_from_row(row) for row in rows]

    def read(self, brief_id: str) -> PriorBrief | None:
        self.ensure()
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM briefs WHERE brief_id = ?", (brief_id,)).fetchone()
        return self._brief_from_row(row) if row is not None else None

    def search(
        self,
        query: str,
        *,
        match: Literal["all", "any", "phrase"] = "all",
        sort: Literal["relevance", "newest"] = "relevance",
        limit: int = 20,
    ) -> list[PriorBriefSearchResult]:
        self.ensure()
        terms = re.findall(r"[\w§'-]+", query, flags=re.UNICODE)
        if not terms:
            return []
        quoted = [f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms]
        if match == "phrase":
            expression = '"' + " ".join(terms).replace('"', '""') + '"'
        elif match == "any":
            expression = " OR ".join(quoted)
        else:
            expression = " AND ".join(quoted)
        limit = max(1, min(int(limit), 100))
        ordering = "briefs.document_date DESC, briefs.title COLLATE NOCASE" if sort == "newest" else "bm25(briefs_fts), briefs.document_date DESC"
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT briefs.*,
                       snippet(briefs_fts, 3, '[', ']', ' ... ', 45) AS snippet
                FROM briefs_fts
                JOIN briefs ON briefs_fts.rowid = briefs.id
                WHERE briefs_fts MATCH ?
                ORDER BY {ordering}
                LIMIT ?
                """,
                (expression, limit),
            ).fetchall()
        return [
            PriorBriefSearchResult(
                brief_id=str(row["brief_id"]),
                title=str(row["title"]),
                case_number=str(row["case_number"]),
                document_type=str(row["document_type"]),
                document_date=str(row["document_date"]),
                date_source=str(row["date_source"]),
                relative_path=str(row["relative_path"]),
                snippet=str(row["snippet"] or ""),
                source_link=f"open-law-lens://prior-brief/{row['brief_id']}",
            )
            for row in rows
        ]

    def backup(self, target: Path) -> Path:
        self.ensure()
        target.parent.mkdir(parents=True, exist_ok=True)
        source_conn = sqlite3.connect(self.path)
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
            source_conn.close()
        return target

    def _brief_from_row(self, row: sqlite3.Row) -> PriorBrief:
        relative_path = str(row["relative_path"])
        return PriorBrief(
            brief_id=str(row["brief_id"]),
            relative_path=relative_path,
            source_path=str(self.source_dir / relative_path),
            title=str(row["title"]),
            case_number=str(row["case_number"]),
            document_type=str(row["document_type"]),
            document_date=str(row["document_date"]),
            date_source=str(row["date_source"]),
            text=str(row["text"]),
            sha256=str(row["sha256"]),
            file_size=int(row["file_size"]),
            file_mtime_ns=int(row["file_mtime_ns"]),
            indexed_at=str(row["indexed_at"]),
            heading_spans=_headings_from_json(
                _json_value(str(row["heading_spans_json"] or "[]")),
                len(str(row["text"])),
            ),
        )
