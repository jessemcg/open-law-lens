from __future__ import annotations


OPEN_DOUBLE_QUOTE = "\u201c"
CLOSE_DOUBLE_QUOTE = "\u201d"
OPEN_SINGLE_QUOTE = "\u2018"
CLOSE_SINGLE_QUOTE = "\u2019"


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
    if previous_char in "([{<\u2018\u201c":
        return True
    if not next_char:
        return False
    if immediate_previous_char is not None and immediate_previous_char.isspace():
        return next_char.isalnum() or next_char in "[({<\u2018\u201c"
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


__all__ = ["smart_quote_display_text"]
