from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .cache import JsonCache
from .library import DisplayText, PageMarker


CALIFORNIA_SLIP_OPINION_ARCHIVE = "https://www4.courts.ca.gov/opinions/archive"
DEFAULT_SLIP_OPINION_MAX_AGE_DAYS = 180
CASE_NUMBER_RE = re.compile(r"\b([A-Z]\d{6})\b", re.IGNORECASE)
SLIP_PAGE_SOURCE_FIELD = "slip_pdf"


class SlipOpinionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SlipOpinionResult:
    case_number: str
    source_url: str
    pdf_path: Path
    display: DisplayText
    date_filed: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def page_count(self) -> int:
        return len(self.display.page_markers)

    def to_json(self, *, include_text: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": bool(self.display.text),
            "case_number": self.case_number,
            "source_url": self.source_url,
            "cache_pdf_path": str(self.pdf_path),
            "date_filed": self.date_filed,
            "page_count": self.page_count,
            "warnings": list(self.warnings),
            "error": "" if self.display.text else "No extractable slip opinion text found.",
        }
        if include_text:
            payload["text"] = self.display.text
            payload["text_length"] = len(self.display.text)
        return payload


def slip_opinion_url(case_number: str) -> str:
    clean = normalize_case_number(case_number)
    if not clean:
        raise ValueError("California case number is required.")
    return f"{CALIFORNIA_SLIP_OPINION_ARCHIVE}/{clean}.PDF"


def normalize_case_number(value: str) -> str:
    match = CASE_NUMBER_RE.search(str(value or ""))
    return match.group(1).upper() if match else ""


def case_number_from_cluster(cluster: dict[str, Any]) -> str:
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
        if isinstance(candidate, str):
            case_number = normalize_case_number(candidate)
            if case_number:
                return case_number
    return ""


def is_recent_published_california_case(
    cluster: dict[str, Any],
    *,
    max_age_days: int = DEFAULT_SLIP_OPINION_MAX_AGE_DAYS,
    today: date | None = None,
) -> bool:
    if str(cluster.get("precedential_status") or cluster.get("status") or "").strip() != "Published":
        return False
    if not _is_california_court(cluster):
        return False
    filed = _cluster_filed_date(cluster)
    if filed is None:
        return False
    current = today or datetime.now(UTC).date()
    age_days = (current - filed).days
    return 0 <= age_days <= max(0, max_age_days)


def fetch_slip_opinion_for_cluster(
    cluster: dict[str, Any],
    cache: JsonCache,
    *,
    refresh: bool = False,
    force: bool = False,
    max_age_days: int = DEFAULT_SLIP_OPINION_MAX_AGE_DAYS,
    timeout: float = 30.0,
) -> SlipOpinionResult:
    case_number = case_number_from_cluster(cluster)
    if not case_number:
        raise SlipOpinionError("No California appellate case number found for slip-opinion lookup.")
    if not force and not is_recent_published_california_case(cluster, max_age_days=max_age_days):
        raise SlipOpinionError("Case is not a recent published California opinion eligible for slip-opinion fallback.")
    return fetch_slip_opinion(
        case_number,
        cache,
        refresh=refresh,
        timeout=timeout,
        date_filed=str(cluster.get("date_filed") or ""),
    )


def fetch_slip_opinion(
    case_number: str,
    cache: JsonCache,
    *,
    refresh: bool = False,
    timeout: float = 30.0,
    date_filed: str = "",
) -> SlipOpinionResult:
    clean_case_number = normalize_case_number(case_number)
    if not clean_case_number:
        raise ValueError("California case number is required.")
    url = slip_opinion_url(clean_case_number)
    pdf_path = slip_opinion_pdf_path(cache, clean_case_number)
    if refresh or not pdf_path.exists():
        _download_pdf(url, pdf_path, timeout=timeout)
    display = extract_slip_pdf_display(pdf_path)
    if not display.text:
        raise SlipOpinionError("No extractable slip opinion text found.")
    return SlipOpinionResult(
        case_number=clean_case_number,
        source_url=url,
        pdf_path=pdf_path,
        display=display,
        date_filed=date_filed,
    )


def slip_metadata_from_display(display: DisplayText) -> dict[str, str]:
    return slip_metadata_from_text(display.text)


def slip_metadata_from_text(text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    filed = _filed_date_from_text(text)
    if filed:
        metadata["date_filed"] = filed
    title = _case_title_from_text(text)
    if title:
        metadata["case_name"] = title
        metadata["case_name_short"] = title
    return metadata


def slip_opinion_pdf_path(cache: JsonCache, case_number: str) -> Path:
    clean_case_number = normalize_case_number(case_number)
    if not clean_case_number:
        raise ValueError("California case number is required.")
    return cache.root / "slip_opinions" / f"{clean_case_number}.PDF"


def extract_slip_pdf_display(pdf_path: Path) -> DisplayText:
    if shutil.which("pdftotext") is None:
        raise SlipOpinionError("Slip opinion PDF extraction requires the pdftotext command.")
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SlipOpinionError(f"Could not extract slip opinion PDF text: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "pdftotext failed").strip()
        raise SlipOpinionError(f"Could not extract slip opinion PDF text: {message}")
    return slip_text_display_from_pages(completed.stdout.split("\f"))


def slip_text_display_from_pages(pages: list[str]) -> DisplayText:
    text_parts: list[str] = []
    page_markers: list[PageMarker] = []
    for raw_page in pages:
        page_label = str(len(page_markers) + 1)
        page_text = _clean_extracted_text(raw_page, page_label=page_label)
        if not page_text:
            continue
        marker_text = f"[Slip opn. p. {page_label}]"
        if text_parts:
            text_parts.append("\n\n")
        start = sum(len(part) for part in text_parts)
        text_parts.append(marker_text)
        end = start + len(marker_text)
        page_markers.append(
            PageMarker(
                page_label=page_label,
                marker_text=marker_text,
                start_offset=start,
                end_offset=end,
                source_field=SLIP_PAGE_SOURCE_FIELD,
            )
        )
        text_parts.append("\n")
        text_parts.append(page_text)
    return DisplayText(
        text="".join(text_parts).strip(),
        source_field=SLIP_PAGE_SOURCE_FIELD,
        page_markers=page_markers,
    )


def _download_pdf(url: str, pdf_path: Path, *, timeout: float) -> None:
    request = Request(url, headers={"User-Agent": "OpenLawLens/0.1"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            raise SlipOpinionError(f"California Courts slip opinion PDF was not found: {url}") from exc
        raise SlipOpinionError(f"California Courts returned HTTP {exc.code} for slip opinion PDF.") from exc
    except URLError as exc:
        raise SlipOpinionError(f"Unable to reach California Courts slip opinion archive: {exc.reason}") from exc
    if not data:
        raise SlipOpinionError("California Courts slip opinion PDF download was empty.")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(data)


def _cluster_filed_date(cluster: dict[str, Any]) -> date | None:
    value = str(cluster.get("date_filed") or "").strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_california_court(cluster: dict[str, Any]) -> bool:
    court_id = ""
    docket = cluster.get("docket")
    if isinstance(docket, dict):
        court = docket.get("court")
        if isinstance(court, dict):
            court_id = str(court.get("id") or "").strip()
        court_id = court_id or str(docket.get("court_id") or docket.get("court") or "").strip()
    court_id = court_id or str(cluster.get("court_id") or "").strip()
    return court_id == "cal" or court_id.startswith("calctapp")


def _filed_date_from_text(text: str) -> str:
    match = re.search(r"\bFiled\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)
    if match is None:
        return ""
    month = int(match.group(1))
    day = int(match.group(2))
    year = int(match.group(3))
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _case_title_from_text(text: str) -> str:
    for line in text.splitlines():
        stripped = re.sub(r"\s+", " ", line).strip()
        match = re.match(r"^(In re .+?)(?:,|\s+a Person\b|$)", stripped, flags=re.IGNORECASE)
        if match is not None:
            title = match.group(1).strip(" .")
            if re.search(r"\b[A-Z]$", title):
                title = f"{title}."
            return re.sub(r"^in\s+re\b", "In re", title, flags=re.IGNORECASE)
    return ""


def _clean_extracted_text(text: str, *, page_label: str = "") -> str:
    raw_lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()
    raw_lines = _drop_printed_page_number(raw_lines, page_label)

    paragraphs: list[str] = []
    current = ""
    previous_blank = False
    for raw_line in raw_lines:
        stripped = raw_line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            previous_blank = True
            continue
        normalized = re.sub(r"[ \t]+", " ", stripped)
        starts_paragraph = _starts_pdf_paragraph(raw_line, normalized, current, previous_blank)
        if current and starts_paragraph:
            paragraphs.append(current)
            current = ""
        if not current:
            current = normalized
        elif current.endswith("-") and normalized[:1].islower():
            current = f"{current[:-1]}{normalized}"
        else:
            current = f"{current} {normalized}"
        previous_blank = False
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs).strip()


def _drop_printed_page_number(lines: list[str], page_label: str) -> list[str]:
    if not page_label:
        return lines
    page_number_re = re.compile(rf"^\s*{re.escape(page_label)}\s*$")
    trimmed = list(lines)
    if trimmed and page_number_re.match(trimmed[0]):
        trimmed.pop(0)
    if trimmed and page_number_re.match(trimmed[-1]):
        trimmed.pop()
    return trimmed


def _starts_pdf_paragraph(
    raw_line: str,
    normalized: str,
    current: str,
    previous_blank: bool,
) -> bool:
    if previous_blank:
        return True
    if re.fullmatch(r"(?:[IVXLCDM]+|[A-Z])\.", normalized):
        return True
    if (
        len(normalized) <= 80
        and re.search(r"[A-Z]", normalized)
        and normalized.upper() == normalized
    ):
        return True
    indent = len(raw_line) - len(raw_line.lstrip(" "))
    if indent < 2 or not current:
        return False
    if not re.search(r"[.?!)](?:[\"'’”])?$", current):
        return False
    return bool(re.match(r"[A-Z(“\"']", normalized))
