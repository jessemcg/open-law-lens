from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterator, Literal


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIOR_BRIEFS_DIR = PROJECT_ROOT / "prior_briefs"
DEFAULT_PRIOR_BRIEFS_DB = PROJECT_ROOT / "library" / "prior_briefs.sqlite3"
SCHEMA_VERSION = "1"
TEXT_VERSION = "pandoc-plain-v2"
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


def extract_prior_brief_text(path: Path) -> str:
    executable = shutil.which("pandoc")
    if executable is None:
        raise PriorBriefError("Prior brief indexing requires the pandoc command.")
    try:
        completed = subprocess.run(
            [executable, "-f", "odt", "-t", "plain", "--wrap=none", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PriorBriefError(f"Could not extract {path.name}: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "pandoc failed").strip()
        raise PriorBriefError(f"Could not extract {path.name}: {message}")
    text = completed.stdout.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise PriorBriefError(f"No text was extracted from {path.name}.")
    return text


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

    def to_json(self, *, include_text: bool = True) -> dict[str, object]:
        payload = asdict(self)
        if not include_text:
            payload.pop("text", None)
            payload["text_length"] = len(self.text)
        return payload


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
                    text_version TEXT NOT NULL DEFAULT ''
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
                    text = extract_prior_brief_text(source_path)
                except PriorBriefError as exc:
                    errors.append(str(exc))
                    continue
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
                )
                if old is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO briefs(
                            brief_id, relative_path, title, case_number, document_type,
                            document_date, date_source, text, sha256, file_size,
                            file_mtime_ns, indexed_at, text_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            text_version = ?
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
        )
