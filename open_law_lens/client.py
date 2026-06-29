from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cache import JsonCache, cluster_id_from_cluster, normalize_citation, resource_id_from_url
from .case_titles import (
    cluster_short_title_value,
    cluster_title_value,
    normalize_case_title,
    parenthetical_adoption_title,
    parenthetical_in_re_title,
)
from .config import courtlistener_token
from .library import CaseLibrary, DisplayText, decode_cp1252_control_chars, opinion_display_text


BASE_URL = "https://www.courtlistener.com"
API_BASE = f"{BASE_URL}/api/rest/v4"
CITATION_LOOKUP_URL = f"{API_BASE}/citation-lookup/"
SEARCH_URL = f"{API_BASE}/search/"
CALIFORNIA_COURT_FILTER = "court_id:(cal OR calctapp OR calappdeptsuper)"
TEXT_FIELDS = (
    "html_with_citations",
    "plain_text",
    "html",
    "html_lawbox",
    "html_columbia",
    "html_anon_2020",
    "xml_harvard",
)
OFFICIAL_CALIFORNIA_REPORTERS = {
    "cal.": "Cal.",
    "cal.2d": "Cal.2d",
    "cal.3d": "Cal.3d",
    "cal.4th": "Cal.4th",
    "cal.5th": "Cal.5th",
    "cal.app.": "Cal.App.",
    "cal.app.2d": "Cal.App.2d",
    "cal.app.3d": "Cal.App.3d",
    "cal.app.4th": "Cal.App.4th",
    "cal.app.5th": "Cal.App.5th",
}


class CourtListenerError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class FormattedCitation:
    plain_text: str
    html_text: str


@dataclass(frozen=True)
class CourtListenerSearchResult:
    cluster_id: str
    case_name: str
    citation: str
    court: str
    court_id: str
    date_filed: str
    status: str
    snippet: str = ""


@dataclass(frozen=True)
class CourtListenerSearchPage:
    results: list[CourtListenerSearchResult]
    count: int
    next_url: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        text = html.unescape("".join(self.parts))
        text = decode_cp1252_control_chars(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def opinion_text(opinion: dict[str, Any]) -> str:
    for field in TEXT_FIELDS:
        value = opinion.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if field.startswith("html") or field.startswith("xml"):
            return html_to_text(value)
        return decode_cp1252_control_chars(value).strip()
    return ""


def cluster_title(cluster: dict[str, Any]) -> str:
    title = cluster_title_value(cluster)
    if title:
        return title
    cluster_id = cluster.get("id")
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def cluster_short_title(cluster: dict[str, Any]) -> str:
    title = cluster_short_title_value(cluster)
    if title:
        return title
    cluster_id = cluster.get("id")
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def cluster_citation_line(cluster: dict[str, Any]) -> str:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return ""
    rendered: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        volume = citation.get("volume")
        reporter = citation.get("reporter")
        page = citation.get("page")
        pieces = [str(piece).strip() for piece in (volume, reporter, page) if str(piece).strip()]
        if pieces:
            rendered.append(" ".join(pieces))
    return "; ".join(rendered)


def _normalized_reporter(value: str) -> str:
    return re.sub(r"\s+", "", value.strip()).casefold()


def official_california_reporter_citation(cluster: dict[str, Any]) -> str:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return ""
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        reporter = citation.get("reporter")
        if not isinstance(reporter, str):
            continue
        normalized_reporter = _normalized_reporter(reporter)
        display_reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter)
        if display_reporter is None:
            continue
        pieces = [
            str(piece).strip()
            for piece in (citation.get("volume"), display_reporter, citation.get("page"))
            if str(piece).strip()
        ]
        if len(pieces) == 3:
            return " ".join(pieces)
    return ""


def _official_california_reporter_key(cluster: dict[str, Any]) -> tuple[str, str, str] | None:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return None
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        reporter = citation.get("reporter")
        if not isinstance(reporter, str):
            continue
        normalized_reporter = _normalized_reporter(reporter)
        if normalized_reporter not in OFFICIAL_CALIFORNIA_REPORTERS:
            continue
        volume = str(citation.get("volume") or "").strip()
        page = str(citation.get("page") or "").strip()
        if volume and page:
            return (volume.casefold(), normalized_reporter, page.casefold())
    return None


def cluster_year(cluster: dict[str, Any]) -> str:
    value = cluster.get("date_filed")
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return value[:4]
    return ""


def format_official_california_citation(cluster: dict[str, Any]) -> FormattedCitation | None:
    citation = official_california_reporter_citation(cluster)
    if not citation:
        return None
    title = cluster_short_title(cluster)
    year = cluster_year(cluster)
    year_part = f" ({year})" if year else ""
    plain = f"{title}{year_part} {citation}"
    html_text = f"<i>{html.escape(title)}</i>{html.escape(year_part)} {html.escape(citation)}"
    return FormattedCitation(plain_text=plain, html_text=html_text)


def courtlistener_search_query(query: str, *, include_unpublished: bool = False) -> str:
    cleaned = re.sub(r"\s+", " ", query.strip())
    if not cleaned:
        raise ValueError("Search query is required.")
    pieces = [cleaned, CALIFORNIA_COURT_FILTER]
    if not include_unpublished:
        pieces.append("status:Published")
    return " ".join(pieces)


def _search_citation_line(result: dict[str, Any]) -> str:
    citations = result.get("citation")
    if isinstance(citations, list):
        for value in citations:
            citation = official_california_reporter_citation_from_text(str(value))
            if citation:
                return citation
    if isinstance(citations, str):
        return official_california_reporter_citation_from_text(citations)
    return ""


def official_california_reporter_citation_from_text(text: str) -> str:
    match = re.search(
        r"\b(?P<volume>\d+)\s+"
        r"(?P<reporter>Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?)\s+"
        r"(?P<page>\d+)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    normalized_reporter = _normalized_reporter(match.group("reporter"))
    display_reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter)
    if display_reporter is None:
        return ""
    return f"{match.group('volume')} {display_reporter} {match.group('page')}"


def search_result_full_citation(result: CourtListenerSearchResult) -> str:
    year = result.date_filed[:4] if re.match(r"^\d{4}", result.date_filed) else ""
    if result.citation and year:
        return f"{result.case_name} ({year}) {result.citation}"
    if result.citation:
        return f"{result.case_name} {result.citation}"
    if year:
        return f"{result.case_name} ({year}) [official reporter unavailable]"
    return result.case_name


def us_long_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def clean_search_snippet(value: str) -> str:
    text = re.sub(r"\r\n?", "\n", value)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text).strip()
    if not text:
        return ""

    opinion_match = re.search(r"(?im)^\s*Opinion\s*$", text)
    candidates = [text[opinion_match.end() :]] if opinion_match else []
    candidates.append(text)
    for candidate in candidates:
        trimmed = _trim_snippet_to_body(candidate)
        if trimmed:
            return re.sub(r"\s+", " ", trimmed).strip()
    return re.sub(r"\s+", " ", text).strip()


def _trim_snippet_to_body(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        candidate = _strip_leading_page_marker(line)
        if _looks_like_opinion_body_line(candidate):
            tail = [candidate, *lines[index + 1 :]]
            return "\n".join(tail)
    return ""


def _strip_leading_page_marker(line: str) -> str:
    return re.sub(r"^\*\d+\s*", "", line).strip()


def _looks_like_opinion_body_line(line: str) -> bool:
    if len(line) < 35 or not re.search(r"[a-z]", line):
        return False
    if _is_snippet_boilerplate_line(line):
        return False
    return bool(re.search(r"[.,;:?!]", line))


def _is_snippet_boilerplate_line(line: str) -> bool:
    normalized = re.sub(r"\s+", " ", line.strip())
    upper = normalized.upper()
    if re.fullmatch(r"\*?\d+", normalized):
        return True
    if re.search(r"\b\d+\s+Cal\.", normalized):
        return True
    boilerplate_patterns = (
        r"^Filed\b",
        r"^Certified for Publication\b",
        r"^CERTIFIED FOR PUBLICATION$",
        r"^IN THE COURT OF APPEAL\b",
        r"^COURT OF APPEAL\b",
        r"^STATE OF CALIFORNIA$",
        r"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)\s+APPELLATE DISTRICT\b",
        r"^DIVISION\s+\w+\b",
        r"^No\.\s+",
        r"^B\d+|^C\d+|^D\d+|^E\d+|^F\d+|^G\d+|^H\d+",
        r"^\(Super\. Ct\. No\.",
        r"^\([A-Za-z ]+ County\)$",
        r"^Opinion$",
        r"^[A-Z][A-Z .,'-]+,\s*(Acting\s+)?(P\.\s*J\.|J\.)$",
        r"^THE COURT\.$",
        r"^v\.$",
        r"^----$",
        r"\b(Plaintiff|Defendant|Appellant|Respondent|Petitioner|Real Party)\b",
        r"\b(Person|Persons) Coming Under the Juvenile Court Law\b",
        r"^Court Law\.$",
    )
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in boilerplate_patterns) or upper == normalized


def _search_case_name(result: dict[str, Any]) -> str:
    for key in ("caseName", "caseNameFull"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            parenthetical_title = parenthetical_in_re_title(value) or parenthetical_adoption_title(
                value
            )
            if parenthetical_title:
                return parenthetical_title
            return normalize_case_title(value)
    cluster_id = str(result.get("cluster_id") or "").strip()
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def normalize_search_result(result: dict[str, Any]) -> CourtListenerSearchResult | None:
    cluster_id = str(result.get("cluster_id") or "").strip()
    if not cluster_id:
        return None
    court = result.get("court")
    if isinstance(court, str):
        court_text = court.strip()
    elif isinstance(court, dict):
        court_text = str(court.get("short_name") or court.get("full_name") or "").strip()
    else:
        court_text = ""
    snippet = ""
    opinions = result.get("opinions")
    if isinstance(opinions, list):
        for opinion in opinions:
            if not isinstance(opinion, dict):
                continue
            value = opinion.get("snippet")
            if isinstance(value, str) and value.strip():
                snippet = clean_search_snippet(value)
                break
    return CourtListenerSearchResult(
        cluster_id=cluster_id,
        case_name=_search_case_name(result),
        citation=_search_citation_line(result),
        court=court_text,
        court_id=str(result.get("court_id") or "").strip(),
        date_filed=str(result.get("dateFiled") or "").strip(),
        status=str(result.get("status") or "").strip(),
        snippet=snippet,
    )


def dedupe_search_results(
    results: list[CourtListenerSearchResult],
) -> list[CourtListenerSearchResult]:
    deduped: list[CourtListenerSearchResult] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for result in results:
        key = (result.case_name.casefold(), result.date_filed)
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(deduped)
            deduped.append(result)
            continue
        existing = deduped[existing_index]
        if not existing.citation and result.citation:
            deduped[existing_index] = result
    return deduped


def _citation_count(cluster: dict[str, Any]) -> int:
    value = cluster.get("citation_count")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _cluster_numeric_id(cluster: dict[str, Any]) -> int:
    value = cluster_id_from_cluster(cluster)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _has_lexis_citation(cluster: dict[str, Any]) -> bool:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return False
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        reporter = citation.get("reporter")
        if isinstance(reporter, str) and "lexis" in reporter.casefold():
            return True
    return False


def _dedupe_sort_key(cluster: dict[str, Any]) -> tuple[bool, bool, int, int, int]:
    short_name = cluster.get("case_name_short")
    title = cluster_short_title(cluster)
    return (
        not (isinstance(short_name, str) and bool(short_name.strip())),
        _has_lexis_citation(cluster),
        -_citation_count(cluster),
        len(title.casefold()),
        _cluster_numeric_id(cluster),
    )


def dedupe_case_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    keep: list[tuple[int, dict[str, Any]]] = []
    for index, cluster in enumerate(clusters):
        key = _official_california_reporter_key(cluster)
        if key is None:
            keep.append((index, cluster))
            continue
        grouped.setdefault(key, []).append((index, cluster))
    for values in grouped.values():
        keep.append(min(values, key=lambda item: _dedupe_sort_key(item[1])))
    return [cluster for _, cluster in sorted(keep, key=lambda item: item[0])]


@dataclass
class CourtListenerClient:
    cache: JsonCache
    library: CaseLibrary | None = None
    token: str = ""
    timeout: float = 30.0
    last_lookup_source: str = ""

    def __post_init__(self) -> None:
        if self.library is None:
            self.library = CaseLibrary.default()

    @classmethod
    def default(cls) -> "CourtListenerClient":
        cache = JsonCache.default()
        cache.ensure()
        library = CaseLibrary.default()
        return cls(cache=cache, library=library, token=courtlistener_token())

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "OpenLawLens/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _request_json(self, request: Request) -> Any:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = f"CourtListener returned HTTP {exc.code}"
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                detail = parsed.get("detail") or parsed.get("error") or parsed.get("wait_until")
                if detail:
                    message = f"{message}: {detail}"
            raise CourtListenerError(message, status=exc.code, body=body) from exc
        except URLError as exc:
            raise CourtListenerError(f"Unable to reach CourtListener: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise CourtListenerError("CourtListener returned invalid JSON") from exc

    def lookup_citation(self, citation: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        normalized = normalize_citation(citation)
        if not normalized:
            raise ValueError("Citation is required.")
        self.last_lookup_source = ""
        if not refresh:
            library_result = self.library.read_lookup(normalized)
            if isinstance(library_result, list):
                self.cache.write_lookup(normalized, library_result)
                self._cache_lookup_clusters(library_result)
                self.last_lookup_source = "Library"
                return library_result
            cached = self.cache.read_lookup(normalized)
            if isinstance(cached, list):
                self._cache_lookup_clusters(cached)
                self.library.upsert_lookup(normalized, cached)
                self.last_lookup_source = "Research Cache"
                return cached
        data = urlencode({"text": normalized}).encode("utf-8")
        request = Request(
            CITATION_LOOKUP_URL,
            data=data,
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        result = self._request_json(request)
        if not isinstance(result, list):
            raise CourtListenerError("CourtListener citation lookup returned unexpected JSON.")
        self.cache.write_lookup(normalized, result)
        self._cache_lookup_clusters(result)
        self.library.upsert_lookup(normalized, result)
        self.last_lookup_source = "CourtListener API"
        return result

    def search_opinions(
        self,
        query: str,
        *,
        include_unpublished: bool = False,
        url: str = "",
    ) -> CourtListenerSearchPage:
        if url:
            full_url = url
        else:
            search_query = courtlistener_search_query(
                query,
                include_unpublished=include_unpublished,
            )
            full_url = f"{SEARCH_URL}?{urlencode({'q': search_query, 'type': 'o'})}"
        if full_url.startswith("/"):
            full_url = f"{BASE_URL}{full_url}"
        request = Request(full_url, headers=self._headers(), method="GET")
        result = self._request_json(request)
        if not isinstance(result, dict):
            raise CourtListenerError("CourtListener search returned unexpected JSON.")
        rows = result.get("results")
        if not isinstance(rows, list):
            raise CourtListenerError("CourtListener search returned unexpected results.")
        normalized: list[CourtListenerSearchResult] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            search_result = normalize_search_result(row)
            if search_result is not None:
                normalized.append(search_result)
        count = result.get("count")
        try:
            count_value = int(count)
        except (TypeError, ValueError):
            count_value = len(normalized)
        next_url = result.get("next")
        return CourtListenerSearchPage(
            results=dedupe_search_results(normalized),
            count=count_value,
            next_url=next_url if isinstance(next_url, str) else "",
        )

    def fetch_url(self, url: str, *, kind: str, refresh: bool = False) -> dict[str, Any]:
        full_url = url if url.startswith("http") else f"{BASE_URL}{url}"
        resource_id = resource_id_from_url(full_url)
        if not refresh:
            if kind == "opinions":
                library_opinion = self.library.read_opinion(resource_id)
                if isinstance(library_opinion, dict):
                    return library_opinion
            if kind == "clusters":
                library_cluster = self.library.read_cluster(resource_id)
                if isinstance(library_cluster, dict):
                    return library_cluster
            cached = self.cache.read_resource(kind, resource_id)
            if isinstance(cached, dict):
                if kind == "opinions":
                    self.library.upsert_opinion(cached)
                elif kind == "clusters":
                    self.library.upsert_cluster(cached)
                return cached
        request = Request(full_url, headers=self._headers(), method="GET")
        result = self._request_json(request)
        if not isinstance(result, dict):
            raise CourtListenerError(f"CourtListener {kind} endpoint returned unexpected JSON.")
        self.cache.write_resource(kind, resource_id, result)
        if kind == "opinions":
            self.library.upsert_opinion(result)
        elif kind == "clusters":
            self.library.upsert_cluster(result)
        return result

    def fetch_cluster_opinions(
        self, cluster: dict[str, Any], *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        urls = cluster.get("sub_opinions")
        if not isinstance(urls, list):
            self.cache.upsert_cluster(cluster)
            self.library.upsert_cluster(cluster)
            return []
        opinions: list[dict[str, Any]] = []
        opinion_ids: list[str] = []
        for url in urls:
            if isinstance(url, str) and url:
                opinion = self.fetch_url(url, kind="opinions", refresh=refresh)
                opinions.append(opinion)
                opinion_id = str(opinion.get("id") or resource_id_from_url(url)).strip()
                if opinion_id:
                    opinion_ids.append(opinion_id)
                    self.library.upsert_opinion(opinion, cluster=cluster)
        self.cache.update_case_opinions(cluster, opinion_ids)
        self.library.update_case_opinions(cluster, opinion_ids)
        return opinions

    def first_opinion_text(self, cluster: dict[str, Any], *, refresh: bool = False) -> str:
        for opinion in self.fetch_cluster_opinions(cluster, refresh=refresh):
            text = self.opinion_display(opinion).text
            if text:
                return text
        return ""

    def opinion_display(self, opinion: dict[str, Any]) -> DisplayText:
        opinion_id = str(opinion.get("id") or "").strip()
        if opinion_id:
            display = self.library.read_opinion_display(opinion_id)
            if display is not None:
                return display
        return opinion_display_text(opinion)

    @staticmethod
    def clusters_from_lookup(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for citation_result in result:
            values = citation_result.get("clusters")
            if isinstance(values, list):
                clusters.extend(cluster for cluster in values if isinstance(cluster, dict))
        return clusters

    def cached_clusters(self) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for entry in self.cache.list_case_entries():
            cluster_id = str(entry.get("cluster_id", "")).strip()
            if not cluster_id:
                continue
            cluster = self.cache.read_cached_cluster(cluster_id)
            if cluster is not None:
                clusters.append(cluster)
        return dedupe_case_clusters(clusters)

    def _cache_lookup_clusters(self, result: list[dict[str, Any]]) -> None:
        for cluster in dedupe_case_clusters(self.clusters_from_lookup(result)):
            if cluster_id_from_cluster(cluster):
                self.cache.upsert_cluster(cluster)
