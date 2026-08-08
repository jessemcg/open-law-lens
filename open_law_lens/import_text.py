from __future__ import annotations

import html
import re


SCHOLAR_UI_NOISE_LINES = {
    "readhow cited",
    "read how cited",
    "how cited",
    "save",
    "cite",
    "cited by",
}
REPORTER_CITATION_RE = re.compile(
    r"\b\d+\s+"
    r"(?:Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?|Cal\.?\s*Rptr\.?\s*(?:\d+d)?|P\.?\s*(?:\d+d)?)"
    r"\s+\d+\b",
    re.IGNORECASE,
)
OFFICIAL_CITATION_RE = re.compile(
    r"\b\d+\s+Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?\s+\d+\b",
    re.IGNORECASE,
)


def normalize_external_reporter_markers(text: str, expected_citation: str) -> str:
    """Convert external bracketed page labels only for the expected reporter series.

    This deliberately does not reinterpret arbitrary bracketed citations.  A marker
    must repeat the target volume and reporter, and its page must fall in the same
    plausible opinion range as the expected first page.
    """
    expected = OFFICIAL_CITATION_RE.search(expected_citation or "")
    if expected is None:
        return text
    expected_match = re.fullmatch(
        r"\s*(?P<volume>\d+)\s+(?P<reporter>Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?)\s+(?P<page>\d+)\s*",
        expected.group(0),
        flags=re.IGNORECASE,
    )
    if expected_match is None:
        return text
    volume = expected_match.group("volume")
    reporter = expected_match.group("reporter")
    first_page = int(expected_match.group("page"))
    reporter_pattern = re.escape(reporter).replace(r"\ ", r"\s*")
    pattern = re.compile(
        rf"(?:\*\*)?\\?\[\s*(?:\*\*)?{re.escape(volume)}\s+{reporter_pattern}\s+(?P<page>\d{{1,5}})(?:\*\*)?\s*\\?\](?:\*\*)?",
        flags=re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        page = int(match.group("page"))
        if first_page <= page <= first_page + 1000:
            return f"[*{page}]"
        return match.group(0)

    return pattern.sub(replace, text)


def basic_external_opinion_html(text: str) -> str:
    """Add conservative paragraph and heading structure to extracted web text."""
    blocks: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^\*\*(.+)\*\*$", r"\1", line)
        escaped = html.escape(line, quote=False)
        tag = "h2" if _looks_like_opinion_heading(line) else "p"
        blocks.append(f"<{tag}>{escaped}</{tag}>")
    return "\n".join(blocks)


def _looks_like_opinion_heading(line: str) -> bool:
    candidate = re.sub(r"^\[\*\d+\]\s*", "", line).strip()
    if not candidate or len(candidate) > 120 or candidate.endswith((".", ";", ":")):
        return False
    if re.fullmatch(r"(?:[IVXLC]+|[A-Z]|\d+)\.", candidate):
        return True
    if re.match(r"^(?:[IVXLC]+|[A-Z]|\d+)\.\s+\S", candidate) and len(candidate.split()) <= 14:
        return True
    words = re.findall(r"[A-Za-z]+", candidate)
    if 1 <= len(words) <= 12 and candidate.upper() == candidate and any(len(word) > 2 for word in words):
        return True
    heading_terms = (
        "background", "discussion", "facts", "factual", "procedural", "analysis",
        "standard of review", "contentions", "disposition", "conclusion",
    )
    lowered = candidate.casefold()
    return len(words) <= 12 and any(term in lowered for term in heading_terms)


def clean_imported_opinion_text(text: str) -> str:
    seen_official_citation = False
    cleaned: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = re.sub(r"\s+", " ", line).strip()
        if not stripped:
            cleaned.append("")
            continue
        if _is_scholar_ui_noise_line(stripped):
            continue
        if _is_standalone_official_citation_line(stripped):
            seen_official_citation = True
        if not seen_official_citation and _looks_like_account_chrome_line(stripped):
            continue
        cleaned.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _is_scholar_ui_noise_line(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line).strip().casefold()
    normalized = normalized.replace("read how cited", "readhow cited")
    return normalized in SCHOLAR_UI_NOISE_LINES


def _is_standalone_official_citation_line(line: str) -> bool:
    match = OFFICIAL_CITATION_RE.search(line)
    if match is None:
        return False
    prefix = line[: match.start()].strip(" ,;")
    if prefix:
        return False
    suffix = line[match.end() :].strip()
    return not suffix or bool(re.fullmatch(r"\(\d{4}\)", suffix))


def _looks_like_account_chrome_line(line: str) -> bool:
    if REPORTER_CITATION_RE.search(line) or _looks_like_case_name(line):
        return False
    if re.search(r"\b(court|appeal|appellate|superior|judge|justice|no\.)\b", line, flags=re.IGNORECASE):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)
    if not 1 <= len(words) <= 4:
        return False
    return all(word[:1].isupper() for word in words)


def _looks_like_case_name(value: str) -> bool:
    return bool(re.search(r"^(In re|Adoption of)\b|\bv\.\b", value, flags=re.IGNORECASE))
