from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CALIFORNIA_RULES_BASE_URL = "https://courts.ca.gov/cms/rules/index"


@dataclass(frozen=True)
class RuleCitation:
    rule_number: str
    subdivision: str = ""
    input_text: str = ""

    @property
    def rule_id(self) -> str:
        return rule_id(self.rule_number)

    @property
    def rule_slug(self) -> str:
        return rule_slug(self.rule_number)

    @property
    def title_slug(self) -> str:
        return title_slug_for_rule(self.rule_number)


@dataclass(frozen=True)
class RuleLink:
    start_offset: int
    end_offset: int
    lookup_text: str


@dataclass(frozen=True)
class RuleSubdivisionSpan:
    start_offset: int
    end_offset: int
    subdivision: str


class CaliforniaRulesError(RuntimeError):
    pass


TITLE_SLUGS = {
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "10": "ten",
}

RULE_NUMBER_RE = re.compile(
    r"(?P<number>(?:10|[1-9])\.\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
RULE_CITATION_RE = re.compile(
    r"\b(?P<full>"
    r"(?:Cal(?:ifornia)?\.?\s+Rules\s+of\s+Court,?\s+)?"
    r"rule\s+"
    r"(?P<number>(?:10|[1-9])\.\d+(?:\.\d+)?)"
    r"(?P<subdivision>(?:\([A-Za-z0-9]+\))*)"
    r")",
    re.IGNORECASE,
)
SUBDIVISION_MARKER_RE = re.compile(
    r"(?m)(?:^|\n)\s*(?:Rule\s+(?:10|[1-9])\.\d+(?:\.\d+)?\.?\s*)?"
    r"(?P<markers>\([A-Za-z0-9]+\)(?:\s*\([A-Za-z0-9]+\))*)"
    r"(?=\s+)",
)


def normalize_rule_number(value: str) -> str:
    number = value.strip().rstrip(".")
    number = re.sub(r"\s+", "", number)
    if not re.fullmatch(r"(?:10|[1-9])\.\d+(?:\.\d+)?", number):
        raise ValueError(f"Unsupported California rule number: {value}")
    title = number.split(".", 1)[0]
    if title not in TITLE_SLUGS:
        raise ValueError(f"Unsupported California rule title: {value}")
    return number


def rule_id(rule_number: str) -> str:
    return f"CRC:{normalize_rule_number(rule_number)}"


def rule_slug(rule_number: str) -> str:
    return normalize_rule_number(rule_number).replace(".", "_", 1)


def title_slug_for_rule(rule_number: str) -> str:
    title = normalize_rule_number(rule_number).split(".", 1)[0]
    return TITLE_SLUGS[title]


def rule_url(rule_number: str) -> str:
    normalized = normalize_rule_number(rule_number)
    return f"{CALIFORNIA_RULES_BASE_URL}/{title_slug_for_rule(normalized)}/rule{rule_slug(normalized)}"


def rule_display_citation(citation: RuleCitation | dict[str, Any]) -> str:
    if isinstance(citation, dict):
        number = normalize_rule_number(str(citation.get("rule_number") or ""))
        subdivision = str(citation.get("subdivision") or "").strip()
    else:
        number = citation.rule_number
        subdivision = citation.subdivision.strip()
    return f"Cal. Rules of Court, rule {number}{subdivision}"


def rule_pinpoint_citation(
    citation: RuleCitation | dict[str, Any],
    subdivisions: tuple[str, ...] | list[str],
) -> str:
    parts = _rule_citation_parts(citation)
    base = rule_display_citation({**parts, "subdivision": ""})
    cleaned = _clean_subdivision_values(subdivisions)
    if not cleaned:
        return base
    if len(cleaned) == 1:
        return f"{base}{cleaned[0]}"
    return f"{base}{_format_subdivision_range(cleaned)}"


def rule_subdivision_spans(text: str) -> list[RuleSubdivisionSpan]:
    markers = list(_iter_subdivision_markers(text))
    spans: list[RuleSubdivisionSpan] = []
    for index, marker in enumerate(markers):
        end_offset = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        spans.append(
            RuleSubdivisionSpan(
                start_offset=marker[0],
                end_offset=end_offset,
                subdivision=marker[1],
            )
        )
    return spans


def rule_subdivisions_for_range(
    text: str,
    start_offset: int,
    end_offset: int,
) -> tuple[str, ...]:
    return _subdivisions_for_range(rule_subdivision_spans(text), start_offset, end_offset)


def rule_title(citation: RuleCitation | dict[str, Any]) -> str:
    if isinstance(citation, dict):
        number = normalize_rule_number(str(citation.get("rule_number") or ""))
    else:
        number = citation.rule_number
    return f"California Rules of Court, rule {number}"


def parse_rule_citation(value: str) -> RuleCitation | None:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    match = RULE_CITATION_RE.search(text)
    if match is not None:
        return RuleCitation(
            rule_number=normalize_rule_number(match.group("number")),
            subdivision=match.group("subdivision") or "",
            input_text=text,
        )
    if not re.search(r"\bCal(?:ifornia)?\.?\s+Rules\s+of\s+Court\b", text, re.IGNORECASE):
        return None
    number_match = RULE_NUMBER_RE.search(text)
    if number_match is None:
        return None
    return RuleCitation(
        rule_number=normalize_rule_number(number_match.group("number")),
        input_text=text,
    )


def looks_like_rule_citation(value: str) -> bool:
    return parse_rule_citation(value) is not None


def rule_search_terms(rule: dict[str, Any]) -> tuple[str, ...]:
    citation = RuleCitation(
        rule_number=normalize_rule_number(str(rule.get("rule_number") or "")),
    )
    values = [
        rule_display_citation(citation),
        rule_title(citation),
        f"rule {citation.rule_number}",
        citation.rule_number,
        citation.rule_slug,
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        for term in (_normalize_lookup(value), _compact_lookup(value)):
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return tuple(terms)


def cited_rule_links(text: str) -> list[RuleLink]:
    links: list[RuleLink] = []
    seen: set[tuple[int, int]] = set()
    for match in RULE_CITATION_RE.finditer(text):
        full = re.sub(r"\s+", " ", match.group("full")).strip()
        if parse_rule_citation(full) is None:
            continue
        span = match.span("full")
        if span in seen:
            continue
        seen.add(span)
        links.append(RuleLink(start_offset=span[0], end_offset=span[1], lookup_text=full))
    return links


def fetch_california_rule(citation: RuleCitation, *, timeout: float = 30.0) -> dict[str, Any]:
    url = rule_url(citation.rule_number)
    request = Request(url, headers={"User-Agent": "OpenLawLens/0.1"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise CaliforniaRulesError(f"California Courts returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise CaliforniaRulesError(f"Unable to reach California Courts: {exc.reason}") from exc
    text = extract_california_rule_text(raw_html, citation)
    if not text:
        raise CaliforniaRulesError(f"Could not extract text for {rule_display_citation(citation)}")
    return {
        "rule_id": citation.rule_id,
        "rule_number": citation.rule_number,
        "rule_slug": citation.rule_slug,
        "title_slug": citation.title_slug,
        "subdivision": citation.subdivision,
        "citation": rule_display_citation(citation),
        "title": rule_title(citation),
        "source_url": url,
        "source_html": raw_html,
        "text": text,
    }


class _RulesTextParser(HTMLParser):
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
            self.parts.append(data)

    def text(self) -> str:
        text = html.unescape("".join(self.parts))
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = "\n".join(line.strip() for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()


def extract_california_rule_text(raw_html: str, citation: RuleCitation) -> str:
    body_html = _rule_body_html(raw_html, citation)
    parser = _RulesTextParser()
    parser.feed(body_html)
    parser.close()
    text = parser.text()
    if not text:
        return ""
    start_patterns = [
        rf"\bRule\s+{re.escape(citation.rule_number)}\b",
        rf"\brule\s+{re.escape(citation.rule_number)}\b",
        rf"\b{re.escape(citation.rule_number)}\.",
    ]
    start = -1
    for pattern in start_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            start = match.start()
            break
    if start >= 0:
        text = text[start:]
    next_rule_pattern = rf"Rule\s+(?!{re.escape(citation.rule_number)}\b)(?:10|[1-9])\.\d+"
    end_match = re.search(
        rf"\n\s*(?:{next_rule_pattern}|Back to Top|Footer|Disclaimer)\b",
        text,
        re.IGNORECASE,
    )
    if end_match is not None:
        text = text[:end_match.start()]
    return text.strip()


def _rule_body_html(raw_html: str, citation: RuleCitation) -> str:
    heading_re = re.compile(
        rf"<h1\b[^>]*>.*?\bRule\s+{re.escape(citation.rule_number)}\b.*?</h1>",
        re.IGNORECASE | re.DOTALL,
    )
    heading_match = heading_re.search(raw_html)
    if heading_match is None:
        return raw_html
    article_start = raw_html.rfind("<article", 0, heading_match.start())
    start = article_start if article_start >= 0 else heading_match.start()
    article_end = raw_html.find("</article>", heading_match.end())
    end = article_end + len("</article>") if article_end >= 0 else len(raw_html)
    return raw_html[start:end]


def _rule_citation_parts(citation: RuleCitation | dict[str, Any]) -> dict[str, str]:
    if isinstance(citation, dict):
        return {
            "rule_number": normalize_rule_number(str(citation.get("rule_number") or "")),
            "subdivision": str(citation.get("subdivision") or "").strip(),
        }
    return {
        "rule_number": normalize_rule_number(citation.rule_number),
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
    spans: list[RuleSubdivisionSpan],
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


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _compact_lookup(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())
