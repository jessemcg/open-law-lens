from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .cache import normalize_citation
from .citation_model import official_citation_from_cluster
from .rules import RuleLink, cited_rule_links
from .statutes import StatuteLink, cited_statute_links


REPORTER_CITATION_PATTERN = (
    r"\d{1,4}\s+"
    r"(?:"
    r"Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?"
    r"|U\.?\s*S\.?"
    r")"
    r"\s+\d+"
)
CASE_NAME_PATTERN = (
    r"In\s+re\s+[A-Z][^();\n]{1,100}?"
    r"|[A-Z][A-Za-z0-9&.' -]{1,80}\s+v\.\s+"
    r"[A-Z][A-Za-z0-9&.' -]{1,80}(?:\s+\([A-Za-z][^)]+\))?"
)

FULL_OFFICIAL_CITATION_RE = re.compile(
    r"\b(?P<full>"
    rf"(?P<name>{CASE_NAME_PATTERN})"
    r"\s+\(\d{4}\)\s+"
    rf"(?P<citation>{REPORTER_CITATION_PATTERN})"
    r")\b",
)
SUPRA_CASE_NAME_RE = re.compile(
    rf"\b(?P<name>{CASE_NAME_PATTERN})\s*,\s*supra\b"
)
SHORTHAND_CITATION_TERM_RE = re.compile(
    r"\b(?:Id|Ibid)\.?(?![A-Za-z])|\bsupra\b",
    re.IGNORECASE,
)

CITATION_SIGNAL_PREFIX_RE = re.compile(
    r"^(?:"
    r"Accord|"
    r"But\s+see|"
    r"Compare|"
    r"Citing|"
    r"Following|"
    r"Relying\s+(?:on|upon)|"
    r"See(?:\s+also)?|"
    r"The\s+(?:case|court|decision|holding|opinion)\s+in"
    r")\s+"
)


@dataclass(frozen=True)
class CitedCaseLink:
    start_offset: int
    end_offset: int
    lookup_text: str


@dataclass(frozen=True)
class CitationStyleSpan:
    start_offset: int
    end_offset: int


def cited_case_links(
    text: str,
    *,
    excluded_citations: Iterable[str] = (),
) -> list[CitedCaseLink]:
    excluded = {
        _citation_key(value)
        for value in excluded_citations
        if _citation_key(value)
    }
    links: list[CitedCaseLink] = []
    seen_spans: set[tuple[int, int]] = set()
    for match in FULL_OFFICIAL_CITATION_RE.finditer(text):
        citation = normalize_citation(match.group("citation"))
        if not citation or _citation_key(citation) in excluded:
            continue
        span = _link_span_without_signal_prefix(match)
        if span in seen_spans:
            continue
        seen_spans.add(span)
        links.append(
            CitedCaseLink(
                start_offset=span[0],
                end_offset=span[1],
                lookup_text=citation,
            )
        )
    return links


def citation_italic_spans(text: str) -> list[CitationStyleSpan]:
    spans: list[tuple[int, int]] = []
    for match in FULL_OFFICIAL_CITATION_RE.finditer(text):
        spans.append(_case_name_span_without_signal_prefix(match))
    for match in SUPRA_CASE_NAME_RE.finditer(text):
        spans.append(_case_name_span_without_signal_prefix(match))
    for match in SHORTHAND_CITATION_TERM_RE.finditer(text):
        spans.append(match.span())
    return [
        CitationStyleSpan(start_offset=start, end_offset=end)
        for start, end in _dedupe_spans(spans)
    ]


def _link_span_without_signal_prefix(match: re.Match[str]) -> tuple[int, int]:
    start, end = match.span("full")
    name = match.group("name")
    prefix = CITATION_SIGNAL_PREFIX_RE.match(name)
    if prefix is not None:
        start += prefix.end()
    return start, end


def _case_name_span_without_signal_prefix(match: re.Match[str]) -> tuple[int, int]:
    start, end = match.span("name")
    name = match.group("name")
    prefix = CITATION_SIGNAL_PREFIX_RE.match(name)
    if prefix is not None:
        start += prefix.end()
    return start, end


def _dedupe_spans(spans: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    deduped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for start, end in sorted(spans):
        if start >= end or (start, end) in seen:
            continue
        seen.add((start, end))
        deduped.append((start, end))
    return deduped


def _citation_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_citation(value).casefold())


def cluster_citation_texts(cluster: dict[str, object] | None) -> list[str]:
    if cluster is None:
        return []
    official = official_citation_from_cluster(cluster)
    return [official] if official else []


__all__ = [
    "CitedCaseLink",
    "CitationStyleSpan",
    "RuleLink",
    "StatuteLink",
    "cited_case_links",
    "cited_rule_links",
    "cited_statute_links",
    "citation_italic_spans",
    "cluster_citation_texts",
]
