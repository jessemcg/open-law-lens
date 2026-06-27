from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .case_titles import cluster_short_title_value
from .library import CaseLibrary


CALIFORNIA_REPORTER_PATTERN = re.compile(
    r"\b(?P<volume>\d+)\s+"
    r"(?P<reporter>"
    r"Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?"
    r"|P\.?\s*\d+d"
    r"|U\.?S\.?"
    r")\s+"
    r"(?P<page>\d+)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaseSuggestion:
    label: str
    lookup_text: str
    display_name: str
    search_terms: tuple[str, ...]
    source: str = ""


def normalize_lookup_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def compact_lookup_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def case_name_from_citation(citation: str) -> str:
    match = re.search(r"\s+\(\d{4}\)", citation)
    if match:
        return citation[:match.start()].strip()
    return citation.strip()


def reporter_citation_from_text(text: str) -> str:
    match = CALIFORNIA_REPORTER_PATTERN.search(text)
    if not match:
        return ""
    reporter = re.sub(r"\s+", " ", match.group("reporter")).strip()
    return f"{match.group('volume')} {reporter} {match.group('page')}"


def is_slip_or_placeholder_case(term: str, citation: str) -> bool:
    combined = f"{term} {citation}".casefold()
    return "slip opn" in combined or "___" in combined


def case_search_terms(label: str, lookup_text: str, display_name: str) -> tuple[str, ...]:
    candidates = [label, lookup_text, display_name, reporter_citation_from_text(label)]
    seen: set[str] = set()
    terms: list[str] = []
    for candidate in candidates:
        for normalized in (normalize_lookup_text(candidate), compact_lookup_text(candidate)):
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
    return tuple(terms)


def make_case_suggestion(
    label: str,
    *,
    lookup_text: str = "",
    display_name: str = "",
    source: str = "",
) -> CaseSuggestion | None:
    clean_label = re.sub(r"\s+", " ", label).strip()
    if not clean_label:
        return None
    clean_lookup = re.sub(r"\s+", " ", lookup_text or reporter_citation_from_text(clean_label) or clean_label).strip()
    clean_display = re.sub(r"\s+", " ", display_name or case_name_from_citation(clean_label)).strip()
    search_terms = case_search_terms(clean_label, clean_lookup, clean_display)
    if not search_terms:
        return None
    return CaseSuggestion(
        label=clean_label,
        lookup_text=clean_lookup,
        display_name=clean_display,
        search_terms=search_terms,
        source=source,
    )


def load_concordance_case_suggestions(path: Path) -> list[CaseSuggestion]:
    try:
        handle = path.open(encoding="utf-8", errors="ignore", newline="")
    except OSError:
        return []
    suggestions: list[CaseSuggestion] = []
    seen_labels: set[str] = set()
    with handle:
        for row in csv.reader(handle, delimiter=";"):
            if len(row) < 3 or row[2].strip() != "Cases":
                continue
            term = row[0].strip()
            citation = (row[1] or term).strip()
            if not citation or is_slip_or_placeholder_case(term, citation):
                continue
            if citation in seen_labels:
                continue
            suggestion = make_case_suggestion(citation, source="Concordance")
            if suggestion is None:
                continue
            seen_labels.add(citation)
            suggestions.append(suggestion)
    return sorted(suggestions, key=lambda item: item.display_name.casefold())


def _cluster_citations(cluster: dict[str, object]) -> list[str]:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return []
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
    return rendered


def case_suggestions_from_library(library: CaseLibrary) -> list[CaseSuggestion]:
    suggestions: list[CaseSuggestion] = []
    seen_labels: set[str] = set()
    for cluster in library.saved_clusters():
        title = cluster_short_title_value(cluster)
        if not title:
            continue
        citations = _cluster_citations(cluster)
        if not citations:
            continue
        date_filed = str(cluster.get("date_filed") or "")
        year = date_filed[:4] if re.fullmatch(r"\d{4}.*", date_filed) else ""
        label = f"{title} ({year}) {citations[0]}" if year else f"{title} {citations[0]}"
        if label in seen_labels:
            continue
        suggestion = make_case_suggestion(
            label,
            lookup_text=citations[0],
            display_name=title,
            source="Library",
        )
        if suggestion is None:
            continue
        seen_labels.add(label)
        suggestions.append(suggestion)
    return sorted(suggestions, key=lambda item: item.display_name.casefold())


def merge_case_suggestions(*groups: Iterable[CaseSuggestion]) -> list[CaseSuggestion]:
    merged: dict[str, CaseSuggestion] = {}
    for group in groups:
        for suggestion in group:
            key = normalize_lookup_text(suggestion.label)
            if key not in merged:
                merged[key] = suggestion
    return sorted(merged.values(), key=lambda item: item.display_name.casefold())


def matching_case_suggestions(
    query: str,
    suggestions: Iterable[CaseSuggestion],
    *,
    limit: int | None = 10,
) -> list[CaseSuggestion]:
    normalized = normalize_lookup_text(query)
    compact = compact_lookup_text(query)
    prefixes = tuple(value for value in (normalized, compact) if value)
    if not prefixes:
        return []
    ranked: list[tuple[int, str, CaseSuggestion]] = []
    for suggestion in suggestions:
        rank: int | None = None
        for term in suggestion.search_terms:
            if any(term.startswith(prefix) for prefix in prefixes):
                rank = 0
                break
            if any(prefix in term for prefix in prefixes):
                rank = 1
        if rank is not None:
            ranked.append((rank, suggestion.display_name.casefold(), suggestion))
    ranked.sort(key=lambda item: (item[0], item[1], item[2].label.casefold()))
    matches = [suggestion for _rank, _display, suggestion in ranked]
    return matches if limit is None else matches[:limit]


def resolve_case_lookup_text(query: str, suggestions: Iterable[CaseSuggestion]) -> str | None:
    normalized = normalize_lookup_text(query)
    compact = compact_lookup_text(query)
    exact_matches = [
        suggestion
        for suggestion in suggestions
        if normalized
        and normalized
        in {
            normalize_lookup_text(suggestion.label),
            normalize_lookup_text(suggestion.display_name),
            normalize_lookup_text(suggestion.lookup_text),
        }
    ]
    if len(exact_matches) == 1:
        return exact_matches[0].lookup_text
    if compact:
        compact_matches = [
            suggestion
            for suggestion in suggestions
            if compact
            in {
                compact_lookup_text(suggestion.label),
                compact_lookup_text(suggestion.display_name),
                compact_lookup_text(suggestion.lookup_text),
            }
        ]
        if len(compact_matches) == 1:
            return compact_matches[0].lookup_text
    matches = matching_case_suggestions(query, suggestions, limit=None)
    if len(matches) == 1:
        return matches[0].lookup_text
    return None
