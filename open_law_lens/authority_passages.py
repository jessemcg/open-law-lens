"""Compact, verified opinion-passage extraction for agent research.

`extract-case --find` returns bounded, exact slices of an already-extracted
authority instead of the full opinion text. Each passage preserves unmodified
source text, maps back to original offsets, and records the nearest preceding
reporter page marker so the agent can quote and pinpoint without pulling the
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
    passages, unmatched, truncated = _locate_passages(result.text, list(queries))
    payload["text_omitted"] = True
    payload["passages"] = passages
    payload["unmatched_queries"] = unmatched
    payload["match_count"] = sum(len(passage["matches"]) for passage in passages)
    payload["truncated"] = truncated
    return payload


def _locate_passages(
    text: str, queries: list[str]
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Find, window, and merge matches into bounded exact source passages."""
    active_queries = [q for q in queries if _normalize_query(q)]
    if not active_queries or not text:
        return [], active_queries, False

    normalized, starts, ends = _normalize_text(text)
    markers = _page_markers(text)
    truncated = False

    matches: list[_Match] = []
    for query_index, query in enumerate(queries):
        normalized_query = _normalize_query(query)
        if not normalized_query:
            continue
        found = _find_all(normalized, normalized_query)
        if len(found) > MAX_MATCHES_PER_QUERY:
            truncated = True
        for norm_start, norm_end in found[:MAX_MATCHES_PER_QUERY]:
            matches.append(
                _Match(
                    query_index=query_index,
                    start=starts[norm_start],
                    end=ends[norm_end - 1],
                )
            )

    matched_indices = {match.query_index for match in matches}
    unmatched = [
        query
        for index, query in enumerate(queries)
        if _normalize_query(query) and index not in matched_indices
    ]

    if not matches:
        return [], unmatched, truncated

    # Build context windows around each match and merge overlaps/adjacencies.
    windows: list[list[int]] = []
    for match in matches:
        windows.append(
            [
                max(0, match.start - PASSAGE_CONTEXT_BEFORE),
                min(len(text), match.end + PASSAGE_CONTEXT_AFTER),
            ]
        )
    windows.sort(key=lambda window: (window[0], window[1]))

    merged: list[list[int]] = []
    for window in windows:
        if merged and window[0] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], window[1])
        else:
            merged.append(window)

    if len(merged) > MAX_MERGED_PASSAGES:
        merged = merged[:MAX_MERGED_PASSAGES]
        truncated = True

    passages: list[dict[str, Any]] = []
    total_chars = 0
    for left, right in merged:
        passage_text, start, end = _trim_whitespace(text, left, right)
        matched = [
            {
                "query": queries[match.query_index],
                "query_index": match.query_index,
                "start_offset": match.start,
                "end_offset": match.end,
            }
            for match in matches
            if match.start >= start and match.end <= end
        ]
        if len(passage_text) > MAX_PASSAGE_CHARS:
            passage_text = passage_text[:MAX_PASSAGE_CHARS]
            end = start + len(passage_text)
            truncated = True

        remaining = MAX_TOTAL_PASSAGE_CHARS - total_chars
        if remaining <= 0:
            truncated = True
            break
        if len(passage_text) > remaining:
            passage_text = passage_text[:remaining]
            end = start + len(passage_text)
            truncated = True
        if not passage_text:
            continue

        total_chars += len(passage_text)
        passages.append(
            {
                "text": passage_text,
                "start_offset": start,
                "end_offset": end,
                "page": _nearest_page(markers, start),
                "matches": matched,
            }
        )

    return passages, unmatched, truncated
