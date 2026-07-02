from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


LEGINFO_SECTION_URL = "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml"


@dataclass(frozen=True)
class StatuteCitation:
    law_code: str
    section: str
    subdivision: str = ""
    input_text: str = ""

    @property
    def statute_id(self) -> str:
        return statute_id(self.law_code, self.section)


@dataclass(frozen=True)
class StatuteLink:
    start_offset: int
    end_offset: int
    lookup_text: str


@dataclass(frozen=True)
class StatuteSubdivisionSpan:
    start_offset: int
    end_offset: int
    subdivision: str


class LegInfoError(RuntimeError):
    pass


CODE_LABELS = {
    "WIC": "Welfare and Institutions Code",
    "EVID": "Evidence Code",
    "CIV": "Civil Code",
    "CCP": "Code of Civil Procedure",
    "FAM": "Family Code",
    "PEN": "Penal Code",
}

CODE_SHORT_LABELS = {
    "WIC": "Welf. & Inst. Code",
    "EVID": "Evid. Code",
    "CIV": "Civ. Code",
    "CCP": "Code Civ. Proc.",
    "FAM": "Fam. Code",
    "PEN": "Pen. Code",
}

CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("WIC", r"\bWelf(?:are)?\.?\b|\bWIC\b|\bW\s*&\s*I\b|Welf\.\s*&\s*Inst\.?"),
    ("EVID", r"\bEvid(?:ence)?\.?\b|Evidence\s+Code"),
    ("CCP", r"Code\s+Civ\.?\s+Proc\.?|Code\s+of\s+Civil\s+Procedure|\bCCP\b"),
    ("CIV", r"\bCiv\.?\s+Code\b|Civil\s+Code"),
    ("FAM", r"\bFam(?:ily)?\.?\b|Family\s+Code"),
    ("PEN", r"\bPen(?:al)?\.?\b|Penal\s+Code"),
)

SECTION_RE = re.compile(
    r"(?:§+\s*|(?:sections?|secs?\.?)\s+)?(?P<section>\d+[a-z]?(?:\.\d+[a-z]?)?)",
    re.IGNORECASE,
)
SUBDIVISION_RE = re.compile(
    r"(?:,\s*)?(?:subd\.?|subdivision)\s*(?P<subdivision>\([^)]+\)(?:\([^)]+\))*)",
    re.IGNORECASE,
)
SUBDIVISION_MARKER_RE = re.compile(
    r"(?m)(?:^|\n)\s*(?:\d+[a-z]?(?:\.\d+[a-z]?)?\.\s*)?"
    r"(?P<markers>\([A-Za-z0-9]+\)(?:\s*\([A-Za-z0-9]+\))*)"
    r"(?=\s+)",
)

STATUTE_LINK_RE = re.compile(
    r"\b(?P<full>"
    r"(?:"
    r"Welf\.?\s*&\s*Inst\.?\s+Code|Welfare\s+and\s+Institutions\s+Code|WIC|"
    r"Evid\.?\s+Code|Evidence\s+Code|"
    r"Code\s+Civ\.?\s+Proc\.?|Code\s+of\s+Civil\s+Procedure|CCP|"
    r"Civ\.?\s+Code|Civil\s+Code|"
    r"Fam\.?\s+Code|Family\s+Code|"
    r"Pen\.?\s+Code|Penal\s+Code"
    r")"
    r",?\s*(?:§|section|sec\.?)\s*"
    r"\d+[a-z]?(?:\.\d+[a-z]?)?"
    r"(?:,\s*(?:subd\.?|subdivision)\s*\([^)]+\)(?:\([^)]+\))*)?"
    r")",
    re.IGNORECASE,
)


def statute_id(law_code: str, section: str) -> str:
    return f"{normalize_law_code(law_code)}:{normalize_section(section)}"


def normalize_law_code(value: str) -> str:
    code = value.strip().upper()
    if code not in CODE_LABELS:
        raise ValueError(f"Unsupported California code: {value}")
    return code


def normalize_section(value: str) -> str:
    section = value.strip().rstrip(".")
    section = re.sub(r"\s+", "", section)
    if not re.fullmatch(r"\d+[a-z]?(?:\.\d+[a-z]?)?", section, re.IGNORECASE):
        raise ValueError(f"Unsupported statute section number: {value}")
    return section


def statute_url(law_code: str, section: str) -> str:
    query = urlencode(
        {
            "lawCode": normalize_law_code(law_code),
            "sectionNum": normalize_section(section),
        }
    )
    return f"{LEGINFO_SECTION_URL}?{query}"


def statute_display_citation(citation: StatuteCitation | dict[str, Any]) -> str:
    if isinstance(citation, dict):
        law_code = normalize_law_code(str(citation.get("law_code") or ""))
        section = normalize_section(str(citation.get("section") or ""))
        subdivision = str(citation.get("subdivision") or "").strip()
    else:
        law_code = citation.law_code
        section = citation.section
        subdivision = citation.subdivision.strip()
    base = f"{CODE_SHORT_LABELS[law_code]}, § {section}"
    return f"{base}, subd. {subdivision}" if subdivision else base


def statute_pinpoint_citation(
    citation: StatuteCitation | dict[str, Any],
    subdivisions: tuple[str, ...] | list[str],
) -> str:
    base = statute_display_citation({**_statute_citation_parts(citation), "subdivision": ""})
    cleaned = _clean_subdivision_values(subdivisions)
    if not cleaned:
        return base
    if len(cleaned) == 1:
        return f"{base}, subd. {cleaned[0]}"
    return f"{base}, subds. {_format_subdivision_range(cleaned)}"


def statute_subdivision_spans(text: str) -> list[StatuteSubdivisionSpan]:
    markers = list(_iter_subdivision_markers(text))
    spans: list[StatuteSubdivisionSpan] = []
    for index, marker in enumerate(markers):
        end_offset = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        spans.append(
            StatuteSubdivisionSpan(
                start_offset=marker[0],
                end_offset=end_offset,
                subdivision=marker[1],
            )
        )
    return spans


def statute_subdivisions_for_range(
    text: str,
    start_offset: int,
    end_offset: int,
) -> tuple[str, ...]:
    return _subdivisions_for_range(statute_subdivision_spans(text), start_offset, end_offset)


def statute_title(citation: StatuteCitation | dict[str, Any]) -> str:
    if isinstance(citation, dict):
        law_code = normalize_law_code(str(citation.get("law_code") or ""))
        section = normalize_section(str(citation.get("section") or ""))
    else:
        law_code = citation.law_code
        section = citation.section
    return f"{CODE_LABELS[law_code]} section {section}"


def parse_statute_citation(value: str) -> StatuteCitation | None:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    law_code = _detect_law_code(text)
    if law_code is None:
        if not re.search(r"\bsections?\b|\bsecs?\.?\b|§", text, re.IGNORECASE):
            return None
        law_code = "WIC"
    section_match = SECTION_RE.search(text)
    if section_match is None:
        return None
    section = normalize_section(section_match.group("section"))
    subdivision = ""
    subdivision_match = SUBDIVISION_RE.search(text[section_match.end():])
    if subdivision_match is not None:
        subdivision = subdivision_match.group("subdivision").strip()
    return StatuteCitation(
        law_code=law_code,
        section=section,
        subdivision=subdivision,
        input_text=text,
    )


def looks_like_statute_citation(value: str) -> bool:
    return parse_statute_citation(value) is not None


def statute_search_terms(statute: dict[str, Any]) -> tuple[str, ...]:
    citation = StatuteCitation(
        law_code=normalize_law_code(str(statute.get("law_code") or "")),
        section=normalize_section(str(statute.get("section") or "")),
    )
    values = [
        statute_display_citation(citation),
        statute_title(citation),
        f"section {citation.section}",
        f"{citation.law_code} {citation.section}",
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for term in (_normalize_lookup(value), _compact_lookup(value)):
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return tuple(terms)


def cited_statute_links(text: str) -> list[StatuteLink]:
    links: list[StatuteLink] = []
    seen: set[tuple[int, int]] = set()
    for match in STATUTE_LINK_RE.finditer(text):
        full = re.sub(r"\s+", " ", match.group("full")).strip()
        if parse_statute_citation(full) is None:
            continue
        span = match.span("full")
        if span in seen:
            continue
        seen.add(span)
        links.append(StatuteLink(start_offset=span[0], end_offset=span[1], lookup_text=full))
    return links


def fetch_leginfo_statute(citation: StatuteCitation, *, timeout: float = 30.0) -> dict[str, Any]:
    url = statute_url(citation.law_code, citation.section)
    request = Request(url, headers={"User-Agent": "OpenLawLens/0.1"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise LegInfoError(f"LegInfo returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise LegInfoError(f"Unable to reach LegInfo: {exc.reason}") from exc
    text = extract_leginfo_text(raw_html, citation)
    if not text:
        raise LegInfoError(f"Could not extract text for {statute_display_citation(citation)}")
    return {
        "statute_id": citation.statute_id,
        "law_code": citation.law_code,
        "code_label": CODE_LABELS[citation.law_code],
        "section": citation.section,
        "citation": statute_display_citation(citation),
        "title": statute_title(citation),
        "source_url": url,
        "source_html": raw_html,
        "text": text,
    }


class _LegInfoTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        text = html.unescape("".join(self.parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_leginfo_text(raw_html: str, citation: StatuteCitation) -> str:
    parser = _LegInfoTextParser()
    parser.feed(raw_html)
    parser.close()
    text = parser.text()
    if not text:
        return ""
    start_patterns = [
        rf"\b{re.escape(citation.section)}\s*\.",
        rf"\bSECTION\s+{re.escape(citation.section)}\b",
        rf"\bSection\s+{re.escape(citation.section)}\b",
    ]
    start = -1
    for pattern in start_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            start = match.start()
            break
    if start >= 0:
        text = text[start:]
    end_match = re.search(r"\n\s*(?:Disclaimer|History|Read this complete)", text, re.IGNORECASE)
    if end_match is not None:
        text = text[:end_match.start()]
    return text.strip()


def _statute_citation_parts(citation: StatuteCitation | dict[str, Any]) -> dict[str, str]:
    if isinstance(citation, dict):
        return {
            "law_code": normalize_law_code(str(citation.get("law_code") or "")),
            "section": normalize_section(str(citation.get("section") or "")),
            "subdivision": str(citation.get("subdivision") or "").strip(),
        }
    return {
        "law_code": normalize_law_code(citation.law_code),
        "section": normalize_section(citation.section),
        "subdivision": citation.subdivision.strip(),
    }


def _iter_subdivision_markers(text: str) -> list[tuple[int, str]]:
    current: list[str] = []
    markers: list[tuple[int, str]] = []
    for match in SUBDIVISION_MARKER_RE.finditer(text):
        parts = re.findall(r"\([A-Za-z0-9]+\)", match.group("markers"))
        if not parts:
            continue
        for part in parts:
            level = _subdivision_part_level(part)
            if level < 1:
                continue
            current = current[: level - 1]
            current.append(part)
        if current:
            markers.append((match.start("markers"), "".join(current)))
    return markers


def _subdivision_part_level(part: str) -> int:
    value = part.strip("()")
    if re.fullmatch(r"[a-z]", value):
        return 1
    if re.fullmatch(r"\d+", value):
        return 2
    if re.fullmatch(r"[A-Z]", value):
        return 3
    if re.fullmatch(r"[ivxlcdm]+", value):
        return 4
    return 1


def _subdivisions_for_range(
    spans: list[StatuteSubdivisionSpan],
    start_offset: int,
    end_offset: int,
) -> tuple[str, ...]:
    if end_offset < start_offset:
        start_offset, end_offset = end_offset, start_offset
    selected_end = max(start_offset, end_offset)
    values: list[str] = []
    for span in spans:
        if span.end_offset <= start_offset:
            continue
        if span.start_offset >= selected_end:
            break
        values.append(span.subdivision)
    if values:
        return tuple(dict.fromkeys(values))
    previous = ""
    for span in spans:
        if span.start_offset <= start_offset:
            previous = span.subdivision
            continue
        break
    return (previous,) if previous else ()


def _clean_subdivision_values(subdivisions: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    values: list[str] = []
    for subdivision in subdivisions:
        value = re.sub(r"\s+", "", subdivision.strip())
        if value and value not in values:
            values.append(value)
    return tuple(values)


def _format_subdivision_range(subdivisions: tuple[str, ...]) -> str:
    if not subdivisions:
        return ""
    if len(subdivisions) == 1:
        return subdivisions[0]
    common = _common_subdivision_prefix(subdivisions)
    if common:
        start_suffix = subdivisions[0][len(common):]
        end_suffix = subdivisions[-1][len(common):]
        if start_suffix and end_suffix:
            return f"{common}{start_suffix}-{end_suffix}"
    first_parts = re.findall(r"\([^)]+\)", subdivisions[0])
    last_parts = re.findall(r"\([^)]+\)", subdivisions[-1])
    if first_parts and len(first_parts) == len(last_parts):
        return f"{subdivisions[0]}-{subdivisions[-1]}"
    return ", ".join(subdivisions)


def _common_subdivision_prefix(subdivisions: tuple[str, ...]) -> str:
    split_values = [re.findall(r"\([^)]+\)", value) for value in subdivisions]
    if not split_values:
        return ""
    prefix: list[str] = []
    for parts in zip(*split_values):
        first = parts[0]
        if all(part == first for part in parts):
            prefix.append(first)
        else:
            break
    return "".join(prefix)


def _detect_law_code(text: str) -> str | None:
    for code, pattern in CODE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return None


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _compact_lookup(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
