from __future__ import annotations


def literal_match_ranges(text: str, query: str) -> list[tuple[int, int]]:
    needle = query.strip()
    if not needle:
        return []
    haystack = text.lower()
    lowered_needle = needle.lower()
    ranges: list[tuple[int, int]] = []
    start_at = 0
    while True:
        start = haystack.find(lowered_needle, start_at)
        if start < 0:
            break
        end = start + len(needle)
        ranges.append((start, end))
        start_at = end
    return ranges
