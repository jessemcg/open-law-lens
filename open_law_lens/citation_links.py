from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .cache import normalize_citation


REPORTER_CITATION_PATTERN = (
    r"\d{1,4}\s+"
    r"(?:"
    r"Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?"
    r"|U\.?\s*S\.?"
    r")"
    r"\s+\d+"
)

FULL_OFFICIAL_CITATION_RE = re.compile(
    r"\b(?P<full>"
    r"(?P<name>"
    r"In\s+re\s+[A-Z][^();\n]{1,100}?"
    r"|[A-Z][A-Za-z0-9&.' -]{1,80}\s+v\.\s+"
    r"[A-Z][A-Za-z0-9&.' -]{1,80}(?:\s+\([A-Za-z][^)]+\))?"
    r")"
    r"\s+\(\d{4}\)\s+"
    rf"(?P<citation>{REPORTER_CITATION_PATTERN})"
    r")\b",
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


def _link_span_without_signal_prefix(match: re.Match[str]) -> tuple[int, int]:
    start, end = match.span("full")
    name = match.group("name")
    prefix = CITATION_SIGNAL_PREFIX_RE.match(name)
    if prefix is not None:
        start += prefix.end()
    return start, end


def _citation_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_citation(value).casefold())


def cluster_citation_texts(cluster: dict[str, object] | None) -> list[str]:
    if cluster is None:
        return []
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return []
    texts: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        pieces = [
            str(piece).strip()
            for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
            if str(piece).strip()
        ]
        if pieces:
            texts.append(" ".join(pieces))
    return texts
