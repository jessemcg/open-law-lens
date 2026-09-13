"""Compact, verified opinion-passage extraction for agent research.

`extract-case --find` returns bounded, exact slices of an already-extracted
authority instead of the full opinion text. Each passage preserves unmodified
source text, maps back to original offsets, and attributes reporter pages only
for a coherent official sequence so the agent can quote without pulling the
whole opinion into context.

This module only transforms the result of the standard extraction pipeline; it
performs no network or library access of its own.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .authority_resolver import AuthorityResult
from .citation_model import official_citation_parts_from_text
from .quality import FIRST_MARKER_TOLERANCE_PAGES, MAX_REASONABLE_CASE_PAGES

# Output bounds. These are deliberate trade-offs: enough verified context to
# support a proposition and a pinpoint, without re-introducing the full opinion
# that this feature exists to avoid.
MAX_MATCHES_PER_QUERY = 2
MAX_MERGED_PASSAGES = 6
MAX_PASSAGE_CHARS = 2000
MAX_TOTAL_PASSAGE_CHARS = 12000
# Context pulled around each match before windows are merged.
PASSAGE_CONTEXT_BEFORE = 1000
PASSAGE_CONTEXT_AFTER = 1000

_PAGE_MARKER_RE = re.compile(r"\[\*(\d{1,5})\]")


@dataclass(frozen=True)
class _Match:
    query_index: int
    start: int
    end: int


def _normalize_text(text: str) -> tuple[str, list[int], list[int]]:
    """Normalize ``text`` for matching and map offsets back to the source.

    Matching is case-insensitive with Unicode NFKC and whitespace
    normalization (runs collapse to a single space). Returns
    ``(normalized, starts, ends)`` where ``starts[i]`` and ``ends[i]`` are the
    original half-open source offsets for normalized character ``i``.
    """
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        folded = unicodedata.normalize("NFKC", char).casefold()
        if not folded:
            continue
        if folded.isspace():
            if previous_space:
                continue
            chars.append(" ")
            starts.append(index)
            ends.append(index + len(char))
            previous_space = True
            continue
        for part in folded:
            chars.append(part)
            starts.append(index)
            ends.append(index + len(char))
        previous_space = False
    return "".join(chars), starts, ends


def _normalize_query(query: str) -> str:
    folded = "".join(
        unicodedata.normalize("NFKC", char).casefold() for char in query
    )
    return re.sub(r"\s+", " ", folded).strip()


def _find_all(normalized: str, query: str) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    start = 0
    while True:
        index = normalized.find(query, start)
        if index < 0:
            break
        matches.append((index, index + len(query)))
        start = index + len(query)
    return matches


def _page_markers(text: str) -> list[tuple[int, str]]:
    return [
        (match.start(), match.group(1)) for match in _PAGE_MARKER_RE.finditer(text)
    ]


def _nearest_page(markers: list[tuple[int, str]], offset: int) -> str:
    label = ""
    for marker_offset, marker_label in markers:
        if marker_offset <= offset:
            label = marker_label
        else:
            break
    return label


def _trim_whitespace(text: str, start: int, end: int) -> tuple[str, int, int]:
    slice_text = text[start:end]
    leading = len(slice_text) - len(slice_text.lstrip())
    trimmed = slice_text[leading:].rstrip()
    new_start = start + leading
    new_end = new_start + len(trimmed)
    return trimmed, new_start, new_end


def build_authority_passages(
    result: AuthorityResult, queries: list[str]
) -> dict[str, Any]:
    """Produce a compact authority JSON with verified passages instead of text.

    ``result`` is the outcome of the standard extraction pipeline. The returned
    payload keeps every metadata field except the full ``text`` and adds a
    bounded ``passages`` list plus per-query match accounting.
    """
    payload = result.to_json()
    payload.pop("text", None)
    markers, pinpoint_status = _pinpoint_markers(result)
    passages, unmatched, accounting = _locate_passages(result.text, list(queries), markers)
    reasons = sorted({reason for row in accounting for reason in row["omission_reasons"]})
    payload["query_accounting"] = accounting
    payload["truncation_reasons"] = reasons
    payload["pinpoint_status"] = pinpoint_status
    payload["text_omitted"] = True
    payload["passages"] = passages
    payload["unmatched_queries"] = unmatched
    payload["match_count"] = sum(len(passage["matches"]) for passage in passages)
    payload["truncated"] = bool(reasons)
    return payload


def _pinpoint_markers(result: AuthorityResult) -> tuple[list[tuple[int, str]], str]:
    markers = _page_markers(result.text)
    parts = official_citation_parts_from_text(result.citation)
    if not markers or not parts or not result.official_pagination:
        return [], "unavailable"
    first = int(parts[2])
    pages = [int(page) for _, page in markers]
    if (
        any(not first <= page <= first + MAX_REASONABLE_CASE_PAGES for page in pages)
        or pages[0] > first + FIRST_MARKER_TOLERANCE_PAGES
        or any(b != a + 1 for a, b in zip(pages, pages[1:]))
    ):
        return [], "ambiguous"
    return markers, "available"


def _locate_passages(
    text: str, queries: list[str], markers: list[tuple[int, str]]
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Allocate whole-match windows in query rounds, then report final slices."""
    normalized, starts, ends = _normalize_text(text)
    candidates: list[list[_Match]] = []
    accounting: list[dict[str, Any]] = []
    unmatched: list[str] = []
    for index, query in enumerate(queries):
        needle = _normalize_query(query)
        found: list[_Match] = []
        if needle:
            for left, right in _find_all(normalized, needle):
                match = _Match(index, starts[left], ends[right - 1])
                # A Unicode expansion may match only part of one source character.
                if _normalize_query(text[match.start:match.end]) == needle:
                    found.append(match)
        if needle and not found:
            unmatched.append(query)
        reasons = []
        oversized = max(len(query.strip()), len(needle)) > MAX_PASSAGE_CHARS
        usable = [] if oversized else [
            m for m in found if m.end - m.start <= MAX_PASSAGE_CHARS
        ]
        if oversized or len(usable) < len(found):
            reasons.append("match_exceeds_passage_limit")
        if len(usable) > MAX_MATCHES_PER_QUERY:
            reasons.append("matches_per_query_limit")
        candidates.append(usable[:MAX_MATCHES_PER_QUERY])
        accounting.append({
            "query": query,
            "query_index": index,
            "total_matches": len(found),
            "returned_matches": 0,
            "omitted_matches": len(found),
            "omission_reasons": reasons,
        })

    windows: list[tuple[int, int]] = []
    selected: list[_Match] = []
    for occurrence in range(MAX_MATCHES_PER_QUERY):
        for group in candidates:
            if occurrence >= len(group):
                continue
            match = group[occurrence]
            room = MAX_PASSAGE_CHARS - (match.end - match.start)
            left = max(0, match.start - min(PASSAGE_CONTEXT_BEFORE, room // 2))
            after = min(PASSAGE_CONTEXT_AFTER, room - (match.start - left))
            right = min(len(text), match.end + after)
            proposed = list(windows)
            for i, (a, b) in enumerate(proposed):
                if a <= match.start and match.end <= b:
                    break
                if (
                    left <= b and a <= right
                    and max(b, right) - min(a, left) <= MAX_PASSAGE_CHARS
                ):
                    proposed[i] = (min(a, left), max(b, right))
                    break
            else:
                proposed.append((left, right))
            reason = ""
            if len(proposed) > MAX_MERGED_PASSAGES:
                reason = "passage_count_limit"
            elif sum(b - a for a, b in proposed) > MAX_TOTAL_PASSAGE_CHARS:
                reason = "total_character_limit"
            if reason:
                accounting[match.query_index]["omission_reasons"].append(reason)
                continue
            windows = proposed
            selected.append(match)

    passages = []
    advertised: set[_Match] = set()
    for left, right in sorted(windows):
        passage_text, start, end = _trim_whitespace(text, left, right)
        matched = []
        for match in selected:
            if match in advertised or not start <= match.start < match.end <= end:
                continue
            advertised.add(match)
            start_page = _nearest_page(markers, match.start)
            matched.append({
                "query": queries[match.query_index],
                "query_index": match.query_index,
                "start_offset": match.start,
                "end_offset": match.end,
                "start_page": start_page,
                "end_page": _nearest_page(markers, match.end - 1),
                "pinpoint_status": "available" if start_page else "unavailable",
            })
            accounting[match.query_index]["returned_matches"] += 1
        passages.append({
            "text": passage_text,
            "start_offset": start,
            "end_offset": end,
            "page": _nearest_page(markers, start),
            "matches": matched,
        })
    for row in accounting:
        row["omitted_matches"] = row["total_matches"] - row["returned_matches"]
        row["omission_reasons"] = sorted(set(row["omission_reasons"]))
    return passages, unmatched, accounting
