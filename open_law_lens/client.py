from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
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
)
from .config import courtlistener_token
from .library import CaseLibrary, DisplayText, opinion_display_text


BASE_URL = "https://www.courtlistener.com"
API_BASE = f"{BASE_URL}/api/rest/v4"
CITATION_LOOKUP_URL = f"{API_BASE}/citation-lookup/"
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
        return value.strip()
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
