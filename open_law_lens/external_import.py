from __future__ import annotations

import hashlib
import re
from typing import Any

from .case_titles import leading_adoption_title, leading_in_re_title, normalize_case_title
from .import_text import clean_imported_opinion_text
from .citation_model import (
    official_citation_dict_from_parts,
    official_citation_parts_from_text,
)


def normalize_official_citation(text: str) -> str:
    parts = official_citation_parts_from_text(text)
    if parts is None:
        return ""
    volume, reporter, page = parts
    return f"{volume} {reporter} {page}"


def official_citation_parts(text: str) -> tuple[str, str, str] | None:
    return official_citation_parts_from_text(text)


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


def imported_citations_from_text(_text: str, official_citation: str) -> list[dict[str, str]]:
    official_parts = official_citation_parts(official_citation)
    if official_parts is None:
        return []
    return [official_citation_dict_from_parts(official_parts)]


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
        "official_citation": normalized_citation,
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
