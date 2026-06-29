from __future__ import annotations

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
