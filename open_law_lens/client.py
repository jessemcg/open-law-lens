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
from .config import courtlistener_token


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


class CourtListenerError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


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
    for key in ("case_name", "case_name_full", "case_name_short"):
        value = cluster.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
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


@dataclass
class CourtListenerClient:
    cache: JsonCache
    token: str = ""
    timeout: float = 30.0

    @classmethod
    def default(cls) -> "CourtListenerClient":
        cache = JsonCache.default()
        cache.ensure()
        return cls(cache=cache, token=courtlistener_token())

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
        if not refresh:
            cached = self.cache.read_lookup(normalized)
            if isinstance(cached, list):
                self._cache_lookup_clusters(cached)
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
        return result

    def fetch_url(self, url: str, *, kind: str, refresh: bool = False) -> dict[str, Any]:
        full_url = url if url.startswith("http") else f"{BASE_URL}{url}"
        resource_id = resource_id_from_url(full_url)
        if not refresh:
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
        urls = cluster.get("sub_opinions")
        if not isinstance(urls, list):
            self.cache.upsert_cluster(cluster)
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
        return opinions

    def first_opinion_text(self, cluster: dict[str, Any], *, refresh: bool = False) -> str:
        for opinion in self.fetch_cluster_opinions(cluster, refresh=refresh):
            text = opinion_text(opinion)
            if text:
                return text
        return ""

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
        return clusters

    def _cache_lookup_clusters(self, result: list[dict[str, Any]]) -> None:
        for cluster in self.clusters_from_lookup(result):
            if cluster_id_from_cluster(cluster):
                self.cache.upsert_cluster(cluster)
