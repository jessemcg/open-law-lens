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
    return normalize_rule_number(rule_number).replace(".", "_")


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
    from .citation_context import RULE_PREFIX, NUMBER
    match = re.fullmatch(
        rf'(?:(?:{RULE_PREFIX})[:,]?\s*(?:rule\s+)?|rule\s+)'
        rf'(?P<number>{NUMBER})(?P<subdivision>(?:\([A-Za-z0-9]+\))*)', text, re.I)
    if match is None:
        return None
    return RuleCitation(normalize_rule_number(match['number']), match['subdivision'], text)


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
    from .citation_context import CitationContext, enactment_links
    return [link for link in enactment_links(text, CitationContext(california=True))
            if isinstance(link, RuleLink)]


def fetch_california_rule(citation: RuleCitation, *, timeout: float = 30.0) -> dict[str, Any]:
    url = rule_url(citation.rule_number)
    request = Request(url, headers={"User-Agent": "OpenLawLens/0.1"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.geturl().rstrip('/') != url.rstrip('/'):
                raise CaliforniaRulesError('California Courts redirected to unrelated content.')
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise CaliforniaRulesError('California Courts response exceeds the size limit.')
            raw_html = body.decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise CaliforniaRulesError(f"California Courts returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise CaliforniaRulesError(f"Unable to reach California Courts: {exc.reason}") from exc
    except TimeoutError as exc:
        raise CaliforniaRulesError('California Courts request timed out.') from exc
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
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "title"}:
            self._skip_depth += 1
            return
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "nav", "footer", "header", "title"} and self._skip_depth:
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
        text = "\n".join(line.strip() for line in text.splitlines())
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_california_rule_text(raw_html: str, citation: RuleCitation) -> str:
    raw_html = re.sub(r'<(nav|footer|header|script|style)\b[^>]*>.*?</\1>', '',
                      raw_html, flags=re.I | re.S)
    for heading in re.findall(r'<h1\b[^>]*>(.*?)</h1>', raw_html, re.I | re.S):
        plain = re.sub(r'<[^>]+>', '', html.unescape(heading))
        identity = re.match(r'\s*Rule\s+((?:10|[1-9])\.\d+(?:\.\d+)?)', plain, re.I)
        if identity and identity[1] != citation.rule_number:
            # A following rule heading may delimit concatenated content, but a
            # wrong primary rule heading is never an identity match.
            break
        if identity:
            break
    else:
        identity = None
    if identity and identity[1] != citation.rule_number:
        raise CaliforniaRulesError('California Courts response has conflicting rule identity.')
    body_html = _rule_body_html(raw_html, citation)
    parser = _RulesTextParser()
    parser.feed(body_html)
    parser.close()
    text = parser.text()
    heading = re.search(rf'(?im)^Rule\s+{re.escape(citation.rule_number)}(?![\w]|\.\d)\.?[^\n]*\n', text)
    if heading is None:
        raise CaliforniaRulesError('California Courts response has no matching rule heading.')
    content = text[heading.end():]
    if (not re.search(r'<p\b', body_html, re.I) or not re.search(r'[A-Za-z]{2,}\s+[A-Za-z]{2,}', content)
            or re.search(r'(?im)^\s*(?:page not found|access denied|no results|search results|'
                         r'sorry[,!]|(?:this )?(?:rule|page) (?:could not be found|does not exist))', content)):
        raise CaliforniaRulesError('California Courts response has no valid rule content.')
    text = text[heading.start():]
    end_match = re.search(r'\n\s*(?:Back to Top|Footer|Disclaimer)\b', text, re.I)
    if end_match is not None:
        text = text[:end_match.start()]
    return text.strip()


def _rule_body_html(raw_html: str, citation: RuleCitation) -> str:
    heading_re = re.compile(
        rf"<h[1-4]\b[^>]*>\s*(?:<[^>]+>\s*)*Rule\s+{re.escape(citation.rule_number)}(?![\w]|\.\d)[^<]*(?:</[^>]+>\s*)*</h[1-4]>",
        re.IGNORECASE | re.DOTALL,
    )
    heading_match = heading_re.search(raw_html)
    if heading_match is None:
        raise CaliforniaRulesError('California Courts response has no exact rule heading.')
    article_start = raw_html.rfind("<article", 0, heading_match.start())
    start = article_start if article_start >= 0 else heading_match.start()
    article_end = raw_html.find("</article>", heading_match.end())
    end = article_end + len("</article>") if article_end >= 0 else len(raw_html)
    next_heading = re.search(
        r'<h[1-4]\b[^>]*>\s*(?:<[^>]+>\s*)*Rule\s+(?:10|[1-9])\.\d+',
        raw_html[heading_match.end():end], re.I,
    )
    if next_heading:
        end = heading_match.end() + next_heading.start()
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
