from __future__ import annotations

import hashlib
import re
from typing import Any

from .case_titles import leading_adoption_title, leading_in_re_title, normalize_case_title
from .import_text import clean_imported_opinion_text
from .quality import OFFICIAL_CALIFORNIA_REPORTERS, normalized_reporter


OFFICIAL_CITATION_RE = re.compile(
    r"\b(?P<volume>\d+)\s+"
    r"(?P<reporter>Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?)\s+"
    r"(?P<page>\d+)\b",
    re.IGNORECASE,
)
REPORTER_CITATION_RE = re.compile(
    r"\b(?P<volume>\d+)\s+"
    r"(?P<reporter>"
    r"Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?"
    r"|Cal\.?\s*Rptr\.?\s*(?:\d+d)?"
    r"|P\.?\s*(?:\d+d)?)\s+"
    r"(?P<page>\d+)\b",
    re.IGNORECASE,
)


def normalize_official_citation(text: str) -> str:
    parts = official_citation_parts(text)
    if parts is None:
        return ""
    volume, reporter, page = parts
    return f"{volume} {reporter} {page}"


def official_citation_parts(text: str) -> tuple[str, str, str] | None:
    match = OFFICIAL_CITATION_RE.search(text)
    if match is None:
        return None
    reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter(match.group("reporter")))
    if reporter is None:
        return None
    return (match.group("volume"), reporter, match.group("page"))


def external_cluster_id(official_citation: str) -> str:
    normalized = re.sub(r"\s+", " ", official_citation).strip().casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"external-{digest}"


def imported_case_name_from_text(text: str) -> str:
    for line in _meaningful_lines(text):
        scholar_title = _scholar_result_case_name(line)
        if scholar_title:
            return scholar_title
        leading_title = leading_in_re_title(line) or leading_adoption_title(line)
        if leading_title:
            return leading_title
        civil_title = _civil_case_name(line)
        if civil_title:
            return civil_title
    return ""


def imported_citations_from_text(text: str, official_citation: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    citations: list[dict[str, str]] = []

    def append(volume: str, reporter: str, page: str) -> None:
        key = re.sub(r"\s+", "", f"{volume} {reporter} {page}").casefold()
        if key in seen:
            return
        seen.add(key)
        citations.append({"volume": volume, "reporter": reporter, "page": page})

    official_parts = official_citation_parts(official_citation)
    if official_parts is not None:
        append(*official_parts)
    for match in REPORTER_CITATION_RE.finditer(_citation_front_matter_text(text)):
        reporter = _display_reporter(match.group("reporter"))
        if reporter:
            append(match.group("volume"), reporter, match.group("page"))
    return citations


def build_external_import_cluster(
    *,
    case_name: str,
    official_citation: str,
    imported_text: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    normalized_citation = normalize_official_citation(official_citation)
    if not normalized_citation:
        raise ValueError("Official California citation is required.")
    clean_name = normalize_case_title(case_name.strip()) if case_name.strip() else ""
    if not clean_name:
        clean_name = imported_case_name_from_text(imported_text)
    if not clean_name:
        clean_name = normalized_citation
    citations = imported_citations_from_text(imported_text, normalized_citation)
    if not citations:
        parts = official_citation_parts(normalized_citation)
        if parts is None:
            raise ValueError("Official California citation is required.")
        volume, reporter, page = parts
        citations = [{"volume": volume, "reporter": reporter, "page": page}]
    return {
        "id": external_cluster_id(normalized_citation),
        "case_name": clean_name,
        "case_name_short": clean_name,
        "case_name_full": clean_name,
        "date_filed": imported_year_from_text(imported_text),
        "citations": citations,
        "source_type": "user_imported_external_case",
        "source_url": source_url.strip(),
    }


def imported_year_from_text(text: str) -> str:
    for line in _meaningful_lines(text):
        match = re.search(r"\b(19|20)\d{2}\b", line)
        if match is not None:
            return match.group(0)
    return ""


def _citation_front_matter_text(text: str) -> str:
    lines = _meaningful_lines(clean_imported_opinion_text(text))
    citation_lines: list[str] = []
    seen_citation = False
    for line in lines:
        if REPORTER_CITATION_RE.search(line):
            citation_lines.append(line)
            seen_citation = True
            continue
        if seen_citation:
            break
    return "\n".join(citation_lines)


def _display_reporter(reporter: str) -> str:
    official = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter(reporter))
    if official is not None:
        return official
    compact = normalized_reporter(reporter)
    if compact.startswith("cal.rptr."):
        suffix = compact.removeprefix("cal.rptr.")
        return "Cal.Rptr." if not suffix else f"Cal.Rptr.{suffix}"
    if compact.startswith("p."):
        suffix = compact.removeprefix("p.")
        return "P." if not suffix else f"P.{suffix}"
    return re.sub(r"\s+", " ", reporter).strip()


def _meaningful_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        stripped = re.sub(r"\s+", " ", line).strip()
        if not stripped or stripped.isdigit():
            continue
        if stripped.casefold() in {"readhow cited", "read how cited"}:
            continue
        if re.match(r"^\*\d+\b", stripped):
            continue
        lines.append(stripped)
    return lines[:80]


def _scholar_result_case_name(line: str) -> str:
    candidate = re.split(r"\s+-\s+Cal:|\s+-\s+", line, maxsplit=1)[0]
    candidate = re.sub(r",\s*\d+\s+.+$", "", candidate).strip(" ,")
    if not _looks_like_case_name(candidate):
        return ""
    return normalize_case_title(candidate)


def _civil_case_name(line: str) -> str:
    if not re.search(r"\bv\.\b", line, flags=re.IGNORECASE):
        return ""
    candidate = re.split(r",|\(\d{4}\)|\d+\s+Cal\.", line, maxsplit=1)[0].strip(" ,")
    if not _looks_like_case_name(candidate):
        return ""
    return normalize_case_title(candidate)


def _looks_like_case_name(value: str) -> bool:
    return bool(re.search(r"^(In re|Adoption of)\b|\bv\.\b", value, flags=re.IGNORECASE))
