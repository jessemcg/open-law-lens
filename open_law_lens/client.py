from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cache import JsonCache, cluster_id_from_cluster, normalize_citation, resource_id_from_url
from .case_titles import cluster_short_title_value, cluster_title_value
from .config import courtlistener_token
from .library import CaseLibrary, DisplayText, decode_cp1252_control_chars, opinion_display_text
from .quality import (
    OFFICIAL_CALIFORNIA_REPORTERS,
    OfficialPaginationQuality,
    normalized_reporter,
    official_california_reporter_citation as quality_official_california_reporter_citation,
    official_california_reporter_citation_from_text as quality_official_california_reporter_citation_from_text,
    official_california_reporter_key,
    official_pagination_quality,
)


BASE_URL = "https://www.courtlistener.com"
API_BASE = f"{BASE_URL}/api/rest/v4"
CITATION_LOOKUP_URL = f"{API_BASE}/citation-lookup/"
OPINIONS_CITED_URL = f"{API_BASE}/opinions-cited/"
RATE_LIMIT_RETRY_ATTEMPTS = 3
RATE_LIMIT_RETRY_BUFFER_SECONDS = 1.0
RATE_LIMIT_RETRY_MAX_SECONDS = 90.0
CITED_BY_PAGE_SIZE = 8
TEXT_FIELDS = (
    "html_with_citations",
    "plain_text",
    "html",
    "html_lawbox",
    "html_columbia",
    "html_anon_2020",
    "xml_harvard",
)


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
    return normalized_reporter(value)


def official_california_reporter_citation(cluster: dict[str, Any]) -> str:
    return quality_official_california_reporter_citation(cluster)


def _official_california_reporter_key(cluster: dict[str, Any]) -> tuple[str, str, str] | None:
    return official_california_reporter_key(cluster)


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


def official_california_reporter_citation_from_text(text: str) -> str:
    return quality_official_california_reporter_citation_from_text(text)


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


def normalize_cluster_search_result(
    cluster: dict[str, Any],
    *,
    snippet: str = "",
) -> CourtListenerSearchResult | None:
    cluster_id = cluster_id_from_cluster(cluster)
    if not cluster_id:
        return None
    docket = cluster.get("docket")
    court = ""
    court_id = ""
    if isinstance(docket, dict):
        court_value = docket.get("court")
        if isinstance(court_value, dict):
            court = str(
                court_value.get("short_name") or court_value.get("full_name") or ""
            ).strip()
            court_id = str(court_value.get("id") or "").strip()
    return CourtListenerSearchResult(
        cluster_id=cluster_id,
        case_name=cluster_short_title(cluster),
        citation=official_california_reporter_citation(cluster),
        court=court,
        court_id=court_id,
        date_filed=str(cluster.get("date_filed") or "").strip(),
        status=str(cluster.get("precedential_status") or "").strip(),
        snippet=snippet,
    )


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


def _api_resource_url(value: object, kind: str) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    if isinstance(value, int):
        return f"/api/rest/v4/{kind}/{value}/"
    return ""


def _opinions_cited_url(opinion_id: str, page_size: int) -> str:
    query = urlencode(
        {
            "cited_opinion": opinion_id,
            "page_size": page_size,
        }
    )
    return f"{OPINIONS_CITED_URL}?{query}"


def _rate_limit_wait_seconds(body: str) -> float | None:
    detail = body
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        value = (
            parsed.get("detail")
            or parsed.get("error")
            or parsed.get("wait_until")
        )
        if value:
            detail = str(value)
    match = re.search(r"Expected available in ([0-9]+(?:\.[0-9]+)?) seconds?", detail)
    if not match:
        return None
    try:
        wait_seconds = float(match.group(1)) + RATE_LIMIT_RETRY_BUFFER_SECONDS
    except ValueError:
        return None
    return min(wait_seconds, RATE_LIMIT_RETRY_MAX_SECONDS)


@dataclass
class CourtListenerClient:
    cache: JsonCache
    library: CaseLibrary | None = None
    token: str = ""
    timeout: float = 30.0
    last_lookup_source: str = ""
    last_opinion_source: str = ""

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
        for attempt in range(RATE_LIMIT_RETRY_ATTEMPTS):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                wait_seconds = _rate_limit_wait_seconds(body)
                if (
                    exc.code == 429
                    and wait_seconds is not None
                    and attempt < RATE_LIMIT_RETRY_ATTEMPTS - 1
                ):
                    time.sleep(wait_seconds)
                    continue
                message = f"CourtListener returned HTTP {exc.code}"
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    detail = (
                        parsed.get("detail")
                        or parsed.get("error")
                        or parsed.get("wait_until")
                    )
                    if detail:
                        message = f"{message}: {detail}"
                raise CourtListenerError(message, status=exc.code, body=body) from exc
            except URLError as exc:
                raise CourtListenerError(f"Unable to reach CourtListener: {exc.reason}") from exc
            except json.JSONDecodeError as exc:
                raise CourtListenerError("CourtListener returned invalid JSON") from exc
        raise CourtListenerError("CourtListener request failed.")

    def lookup_citation(self, citation: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        normalized = normalize_citation(citation)
        if not normalized:
            raise ValueError("Citation is required.")
        self.last_lookup_source = ""
        if not refresh:
            library_result = self.library.read_lookup(normalized)
            if isinstance(library_result, list):
                library_result = self._filter_lookup_result_for_citation(normalized, library_result)
                self.cache.write_lookup(normalized, library_result)
                self._cache_lookup_clusters(library_result)
                self.last_lookup_source = "Library"
                return library_result
            cached = self.cache.read_lookup(normalized)
            if isinstance(cached, list):
                filtered_cached = self._filter_lookup_result_for_citation(normalized, cached)
                if filtered_cached or not self._lookup_result_had_clusters(cached):
                    self.cache.write_lookup(normalized, filtered_cached)
                    self._cache_lookup_clusters(filtered_cached)
                    self._upsert_eligible_lookup(normalized, filtered_cached)
                    self.last_lookup_source = "Research Cache"
                    return filtered_cached
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
        self._upsert_eligible_lookup(normalized, result)
        self.last_lookup_source = "CourtListener API"
        return result

    def citing_opinions(
        self,
        cluster: dict[str, Any],
        *,
        url: str = "",
        page_size: int = CITED_BY_PAGE_SIZE,
    ) -> CourtListenerSearchPage:
        if url:
            full_url = url if url.startswith("http") else f"{BASE_URL}{url}"
            opinion_ids: list[str] = []
        else:
            opinions = self.fetch_cluster_opinions(cluster)
            opinion_ids = [
                str(opinion.get("id") or "").strip()
                for opinion in opinions
                if str(opinion.get("id") or "").strip()
            ]
            if not opinion_ids:
                return CourtListenerSearchPage(results=[], count=0, next_url="")
            full_url = _opinions_cited_url(opinion_ids[0], page_size)

        rows: list[dict[str, Any]] = []
        next_url = ""
        count_value = 0
        pending_urls = [full_url]
        if not url:
            pending_urls.extend(
                _opinions_cited_url(opinion_id, page_size)
                for opinion_id in opinion_ids[1:]
            )
        for current_url in pending_urls:
            request = Request(current_url, headers=self._headers(), method="GET")
            result = self._request_json(request)
            if not isinstance(result, dict):
                raise CourtListenerError("CourtListener cited-by lookup returned unexpected JSON.")
            values = result.get("results")
            if not isinstance(values, list):
                raise CourtListenerError("CourtListener cited-by lookup returned unexpected results.")
            rows.extend(value for value in values if isinstance(value, dict))
            count = result.get("count")
            try:
                count_value += int(count)
            except (TypeError, ValueError):
                count_value += len(values)
            if len(pending_urls) == 1:
                next_value = result.get("next")
                next_url = next_value if isinstance(next_value, str) else ""

        normalized: list[CourtListenerSearchResult] = []
        seen_cluster_ids: set[str] = set()
        for row in rows:
            citing_opinion = row.get("citing_opinion")
            if isinstance(citing_opinion, dict):
                opinion = citing_opinion
            else:
                citing_url = _api_resource_url(citing_opinion, "opinions")
                if not citing_url:
                    continue
                opinion = self.fetch_url(citing_url, kind="opinions")
            cluster_url = _api_resource_url(opinion.get("cluster"), "clusters")
            if cluster_url:
                citing_cluster = self.fetch_url(cluster_url, kind="clusters")
            else:
                cluster_id = str(opinion.get("cluster_id") or "").strip()
                if not cluster_id:
                    continue
                citing_cluster = self.fetch_url(
                    f"/api/rest/v4/clusters/{cluster_id}/",
                    kind="clusters",
                )
            if not isinstance(citing_cluster, dict):
                continue
            result = normalize_cluster_search_result(
                citing_cluster,
                snippet=f"Citation depth: {row.get('depth')}",
            )
            if result is None or result.cluster_id in seen_cluster_ids:
                continue
            seen_cluster_ids.add(result.cluster_id)
            normalized.append(result)
        normalized.sort(key=lambda item: item.date_filed, reverse=True)
        normalized.sort(key=lambda item: item.status != "Published")
        return CourtListenerSearchPage(
            results=normalized,
            count=count_value if count_value else len(normalized),
            next_url=next_url,
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
                return cached
        request = Request(full_url, headers=self._headers(), method="GET")
        result = self._request_json(request)
        if not isinstance(result, dict):
            raise CourtListenerError(f"CourtListener {kind} endpoint returned unexpected JSON.")
        self.cache.write_resource(kind, resource_id, result)
        return result

    def fetch_cluster_opinions(
        self, cluster: dict[str, Any], *, refresh: bool = False
    ) -> list[dict[str, Any]]:
        self.last_opinion_source = ""
        cluster_id = cluster_id_from_cluster(cluster)
        if not refresh and cluster_id:
            library_opinions = [
                opinion
                for opinion_id in self.library.read_case_opinion_ids(cluster_id)
                if (opinion := self.library.read_opinion(opinion_id)) is not None
            ]
            if library_opinions:
                self.last_opinion_source = "Library"
                return library_opinions
        urls = cluster.get("sub_opinions")
        if not isinstance(urls, list):
            self.cache.upsert_cluster(cluster)
            self.save_case_if_official_paginated(cluster, [])
            self.last_opinion_source = "Lookup"
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
        self.cache.update_case_opinions(cluster, opinion_ids)
        self.save_case_if_official_paginated(cluster, opinions)
        self.last_opinion_source = "Fetched"
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

    @staticmethod
    def _lookup_result_had_clusters(result: list[dict[str, Any]]) -> bool:
        return any(isinstance(item.get("clusters"), list) and bool(item.get("clusters")) for item in result)

    @staticmethod
    def _citation_lookup_key(citation: str) -> str:
        return re.sub(r"\s+", "", normalize_citation(citation)).casefold()

    @classmethod
    def _external_import_matches_lookup(cls, cluster: dict[str, Any], normalized_citation: str) -> bool:
        if cluster.get("source_type") != "user_imported_external_case":
            return True
        citation = quality_official_california_reporter_citation(cluster)
        if not citation:
            return True
        return cls._citation_lookup_key(citation) == cls._citation_lookup_key(normalized_citation)

    @classmethod
    def _filter_lookup_result_for_citation(
        cls,
        normalized_citation: str,
        result: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            clusters = item.get("clusters")
            if not isinstance(clusters, list):
                filtered.append(item)
                continue
            kept = [
                cluster
                for cluster in clusters
                if isinstance(cluster, dict) and cls._external_import_matches_lookup(cluster, normalized_citation)
            ]
            if kept:
                filtered.append({**item, "clusters": kept})
        if filtered or not cls._lookup_result_had_clusters(result):
            return filtered
        return []

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

    def _upsert_eligible_lookup(self, citation: str, result: list[dict[str, Any]]) -> None:
        eligible_clusters: list[dict[str, Any]] = []
        for cluster in self.clusters_from_lookup(result):
            cluster_id = cluster_id_from_cluster(cluster)
            if not cluster_id:
                continue
            saved = self.save_case_if_official_paginated(cluster)
            if saved.eligible:
                eligible_clusters.append(cluster)
        if eligible_clusters:
            self.library.upsert_lookup(
                citation,
                [{"status": 200, "clusters": eligible_clusters}],
                normalized_already=True,
            )

    def save_case_if_official_paginated(
        self,
        cluster: dict[str, Any],
        opinions: list[dict[str, Any]] | None = None,
    ) -> OfficialPaginationQuality:
        displays = [opinion_display_text(opinion) for opinion in (opinions or [])]
        quality = official_pagination_quality(cluster, displays)
        if not quality.eligible:
            return quality
        opinion_ids: list[str] = []
        self.library.upsert_cluster(cluster)
        for opinion in opinions or []:
            opinion_id = self.library.upsert_opinion(opinion)
            if opinion_id:
                opinion_ids.append(opinion_id)
        if opinion_ids:
            self.library.update_case_opinion_ids(cluster_id_from_cluster(cluster), opinion_ids)
        return quality
