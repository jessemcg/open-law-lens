from __future__ import annotations

from dataclasses import dataclass
from typing import Any


HIGHLIGHT_CONTEXT_LENGTH = 48


@dataclass(frozen=True)
class ReaderHighlight:
    start_offset: int
    end_offset: int
    text: str
    prefix: str = ""
    suffix: str = ""

    @classmethod
    def from_mapping(cls, value: Any) -> "ReaderHighlight | None":
        if not isinstance(value, dict):
            return None
        start = value.get("start_offset")
        end = value.get("end_offset")
        text = value.get("text")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or not isinstance(text, str)
            or not text
        ):
            return None
        prefix = value.get("prefix", "")
        suffix = value.get("suffix", "")
        return cls(
            start_offset=start,
            end_offset=end,
            text=text,
            prefix=prefix if isinstance(prefix, str) else "",
            suffix=suffix if isinstance(suffix, str) else "",
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "text": self.text,
            "prefix": self.prefix,
            "suffix": self.suffix,
        }


def make_reader_highlight(text: str, start: int, end: int) -> ReaderHighlight | None:
    clean_start = max(0, min(int(start), len(text)))
    clean_end = max(clean_start, min(int(end), len(text)))
    selected = text[clean_start:clean_end]
    if not selected:
        return None
    return ReaderHighlight(
        start_offset=clean_start,
        end_offset=clean_end,
        text=selected,
        prefix=text[max(0, clean_start - HIGHLIGHT_CONTEXT_LENGTH):clean_start],
        suffix=text[clean_end:clean_end + HIGHLIGHT_CONTEXT_LENGTH],
    )


def _common_suffix_length(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(reversed(left), reversed(right)):
        if left_char != right_char:
            break
        count += 1
    return count


def _common_prefix_length(left: str, right: str) -> int:
    count = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        count += 1
    return count


def resolve_reader_highlight(text: str, highlight: ReaderHighlight) -> tuple[int, int] | None:
    start = highlight.start_offset
    end = highlight.end_offset
    if 0 <= start < end <= len(text) and text[start:end] == highlight.text:
        return start, end

    candidates: list[int] = []
    search_from = 0
    while True:
        candidate = text.find(highlight.text, search_from)
        if candidate < 0:
            break
        candidates.append(candidate)
        search_from = candidate + 1
    if not candidates:
        return None

    def score(candidate: int) -> tuple[int, int]:
        candidate_end = candidate + len(highlight.text)
        prefix = text[max(0, candidate - len(highlight.prefix)):candidate]
        suffix = text[candidate_end:candidate_end + len(highlight.suffix)]
        context_score = _common_suffix_length(prefix, highlight.prefix)
        context_score += _common_prefix_length(suffix, highlight.suffix)
        return context_score, -abs(candidate - highlight.start_offset)

    resolved_start = max(candidates, key=score)
    return resolved_start, resolved_start + len(highlight.text)


def resolved_reader_highlights(
    text: str,
    highlights: list[ReaderHighlight],
) -> list[tuple[ReaderHighlight, int, int]]:
    resolved: list[tuple[ReaderHighlight, int, int]] = []
    for highlight in highlights:
        span = resolve_reader_highlight(text, highlight)
        if span is not None:
            resolved.append((highlight, span[0], span[1]))
    return resolved


def toggle_reader_highlight(
    text: str,
    highlights: list[ReaderHighlight],
    start: int,
    end: int,
) -> tuple[list[ReaderHighlight], str]:
    clean_start = max(0, min(int(start), len(text)))
    clean_end = max(clean_start, min(int(end), len(text)))
    if clean_end <= clean_start:
        return list(highlights), "unchanged"

    resolved = resolved_reader_highlights(text, highlights)
    containing = [
        (highlight, span_start, span_end)
        for highlight, span_start, span_end in resolved
        if span_start <= clean_start and clean_end <= span_end
    ]
    if containing:
        removed = min(containing, key=lambda item: item[2] - item[1])[0]
        return [item for item in highlights if item is not removed], "removed"

    merge_start = clean_start
    merge_end = clean_end
    merged_ids: set[int] = set()
    changed = True
    while changed:
        changed = False
        for highlight, span_start, span_end in resolved:
            if id(highlight) in merged_ids:
                continue
            if span_start <= merge_end and merge_start <= span_end:
                merged_ids.add(id(highlight))
                merge_start = min(merge_start, span_start)
                merge_end = max(merge_end, span_end)
                changed = True

    merged = make_reader_highlight(text, merge_start, merge_end)
    if merged is None:
        return list(highlights), "unchanged"
    retained = [item for item in highlights if id(item) not in merged_ids]
    retained.append(merged)
    retained.sort(key=lambda item: (item.start_offset, item.end_offset, item.text))
    return retained, "added"
