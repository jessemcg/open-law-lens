from __future__ import annotations

import re
from typing import Iterable


OPEN_DOUBLE_QUOTE = "\u201c"
CLOSE_DOUBLE_QUOTE = "\u201d"
OPEN_SINGLE_QUOTE = "\u2018"
CLOSE_SINGLE_QUOTE = "\u2019"
QUOTE_STACK_REPLACEMENT = tuple[int, int, str]
MALFORMED_QUOTE_STACK_RE = re.compile(
    r"(?P<outer_open>[\"\u201c\u201d])"
    r"(?P<inner_open>[`'\u2018])"
    r"(?P<extra_open>[\"\u201c\u201d])"
    r"(?P<body>[^\"`'\u2018\u2019\u201c\u201d\n]{1,200}?)"
    r"(?P<extra_close>[\"\u201c\u201d])"
    r"(?P<inner_close>['\u2019])"
    r"(?P<outer_close>[\"\u201c\u201d])"
)
ADJACENT_NESTED_QUOTE_RE = re.compile(
    r"(?P<outer_open>[\"\u201c\u201d])"
    r"(?P<inner_open>[`'\u2018])"
    r"(?P<body>[^\n]{1,1200}?)"
    r"(?P<inner_close>['\u2019])"
    r"(?P<outer_close>[\"\u201c\u201d])"
)
DOUBLE_QUOTE_CHARS = {'"', OPEN_DOUBLE_QUOTE, CLOSE_DOUBLE_QUOTE}


def malformed_quote_stack_replacements(text: str) -> list[QUOTE_STACK_REPLACEMENT]:
    if not text:
        return []
    return [
        (
            match.start(),
            match.end(),
            f"\"`{match.group('body')}'\"",
        )
        for match in MALFORMED_QUOTE_STACK_RE.finditer(text)
    ]


def quote_stack_replacements(text: str) -> list[QUOTE_STACK_REPLACEMENT]:
    if not text:
        return []
    replacements = malformed_quote_stack_replacements(text)
    covered_ranges = [(start, end) for start, end, _replacement in replacements]
    for match in ADJACENT_NESTED_QUOTE_RE.finditer(text):
        start, end = match.span()
        if any(start < covered_end and end > covered_start for covered_start, covered_end in covered_ranges):
            continue
        body = _demote_inner_double_quote_pairs(match.group("body"))
        replacements.append((start, end, f'"{body}"'))
        covered_ranges.append((start, end))
    replacements.sort(key=lambda replacement: replacement[0])
    return replacements


def normalize_malformed_quote_stacks(text: str) -> str:
    replacements = quote_stack_replacements(text)
    if not replacements:
        return text
    return _apply_replacements(text, replacements)


def smart_quote_display_text(text: str) -> str:
    """Convert straight prose quotes to typographic quotes for display only."""
    if not text or ("'" not in text and '"' not in text and "`" not in text):
        return text
    chars = list(text)
    converted: list[str] = []
    for index, char in enumerate(chars):
        if char == "'":
            converted.append(_smart_single_quote(chars, index))
        elif char == "`":
            converted.append(OPEN_SINGLE_QUOTE)
        elif char == '"':
            converted.append(_smart_double_quote(chars, index))
        else:
            converted.append(char)
    return "".join(converted)


def _smart_double_quote(chars: list[str], index: int) -> str:
    if _is_numeric_measure_mark(chars, index):
        return chars[index]
    return OPEN_DOUBLE_QUOTE if _is_opening_context(chars, index) else CLOSE_DOUBLE_QUOTE


def _smart_single_quote(chars: list[str], index: int) -> str:
    previous_char = _previous_char(chars, index)
    next_char = _next_char(chars, index)
    if previous_char is not None and previous_char.isdigit():
        return chars[index]
    if (
        previous_char is not None
        and next_char is not None
        and previous_char.isalpha()
        and next_char.isalpha()
    ):
        return CLOSE_SINGLE_QUOTE
    return OPEN_SINGLE_QUOTE if _is_opening_context(chars, index) else CLOSE_SINGLE_QUOTE


def _is_numeric_measure_mark(chars: list[str], index: int) -> bool:
    previous_char = _previous_char(chars, index)
    if previous_char is None or not previous_char.isdigit():
        return False
    next_char = _next_char(chars, index)
    return next_char is None or not next_char.isalpha()


def _is_opening_context(chars: list[str], index: int) -> bool:
    immediate_previous_char = _previous_char(chars, index)
    previous_char = _previous_nonspace_char(chars, index)
    next_char = _next_nonspace_char(chars, index)
    if previous_char is None:
        return True
    if previous_char in "([{<\u2018\u201c\"`":
        return True
    if not next_char:
        return False
    if immediate_previous_char is not None and immediate_previous_char.isspace():
        return next_char.isalnum() or next_char in "[({<\u2018\u201c'\"`"
    if not next_char.isalnum():
        return False
    return bool(
        immediate_previous_char is not None
        and immediate_previous_char.isspace()
        and previous_char in ".!?"
    )


def _previous_char(chars: list[str], index: int) -> str | None:
    return chars[index - 1] if index > 0 else None


def _next_char(chars: list[str], index: int) -> str | None:
    return chars[index + 1] if index + 1 < len(chars) else None


def _previous_nonspace_char(chars: list[str], index: int) -> str | None:
    cursor = index - 1
    while cursor >= 0:
        if not chars[cursor].isspace():
            return chars[cursor]
        cursor -= 1
    return None


def _next_nonspace_char(chars: list[str], index: int) -> str | None:
    cursor = index + 1
    while cursor < len(chars):
        if not chars[cursor].isspace():
            return chars[cursor]
        cursor += 1
    return None


def _demote_inner_double_quote_pairs(text: str) -> str:
    chars = list(text)
    quote_indexes = [index for index, char in enumerate(chars) if char in DOUBLE_QUOTE_CHARS]
    for pair_index, quote_index in enumerate(quote_indexes):
        chars[quote_index] = "`" if pair_index % 2 == 0 else "'"
    demoted = "".join(chars)
    demoted = re.sub(
        r"`'(?P<body>[^`\n]{1,800}?)'\s+(?P<cites>(?:\[[^\]\n]{1,100}\]\s*)+)'",
        lambda match: f"`{match.group('body')} {match.group('cites').strip()}'",
        demoted,
    )
    return demoted.replace("`'", "`")


def _apply_replacements(text: str, replacements: Iterable[QUOTE_STACK_REPLACEMENT]) -> str:
    parts: list[str] = []
    position = 0
    for start, end, replacement in replacements:
        parts.append(text[position:start])
        parts.append(replacement)
        position = end
    parts.append(text[position:])
    return "".join(parts)


__all__ = [
    "malformed_quote_stack_replacements",
    "normalize_malformed_quote_stacks",
    "quote_stack_replacements",
    "smart_quote_display_text",
]
