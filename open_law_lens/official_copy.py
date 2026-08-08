from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from .cache import cluster_id_from_cluster
from .case_titles import normalize_case_title
from .citation_model import official_citation_from_cluster
from .external_import import imported_case_name_from_text, normalize_official_citation
from .import_text import OFFICIAL_CITATION_RE, clean_imported_opinion_text, normalize_external_reporter_markers
from .library import opinion_display_text
from .official_import import OfficialImportResult, persist_official_opinion
from .quality import official_pagination_quality
from .tavily import (
    TavilyAuthenticationError,
    TavilyClient,
    TavilyConfigurationError,
    TavilyError,
    TavilyNetworkError,
)
from .web_import import _validate_public_destination, extract_webpage_text

MIN_OPINION_CHARACTERS = 1200
MIN_OPINION_WORDS = 150


@dataclass(frozen=True)
class CandidateRejection:
    url: str
    reason: str


@dataclass
class OfficialCopyResolution:
    ok: bool
    category: str
    message: str
    imported: OfficialImportResult | None = None
    candidates: list[CandidateRejection] = field(default_factory=list)
    cached: bool = False


def stable_official_copy_identity(cluster: dict[str, Any], query: str = "") -> str:
    citation = normalize_official_citation(
        str(cluster.get("official_citation") or official_citation_from_cluster(cluster)) or query
    )
    if citation:
        return f"citation:{citation.casefold()}"
    values = (
        normalize_case_title(str(cluster.get("case_name") or cluster.get("case_name_full") or query)).casefold(),
        _cluster_docket(cluster).casefold(),
        str(cluster.get("date_filed") or "").strip()[:10],
        cluster_id_from_cluster(cluster),
    )
    return "identity:" + hashlib.sha256("\0".join(values).encode()).hexdigest()


def tavily_case_query(cluster: dict[str, Any], query: str = "") -> str:
    citation = normalize_official_citation(
        str(cluster.get("official_citation") or official_citation_from_cluster(cluster)) or query
    )
    title = str(cluster.get("case_name") or cluster.get("case_name_full") or query).strip()
    docket = _cluster_docket(cluster)
    filed = str(cluster.get("date_filed") or "").strip()
    reporter_hint = "Cal.5th OR Cal.App.5th"
    return " ".join(part for part in (f'"{title}"' if title else "", f'"{citation}"' if citation else "", docket, filed, reporter_hint) if part)


def is_known_unpublished(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("precedential_status") or cluster.get("status") or "").casefold()
    return status in {"unpublished", "non-precedential", "nonprecedential", "errata"}


def resolve_with_tavily(
    client: Any,
    cluster: dict[str, Any],
    *,
    query: str = "",
    refresh: bool = False,
    tavily_client: TavilyClient | None = None,
) -> OfficialCopyResolution:
    if is_known_unpublished(cluster):
        return OfficialCopyResolution(False, "unpublished", "Known unpublished cases do not have an official reporter copy.")
    identity_key = stable_official_copy_identity(cluster, query)
    if not refresh:
        cached = client.library.read_official_copy_search(identity_key)
        if cached is not None:
            return OfficialCopyResolution(
                False,
                str(cached.get("category") or "no_result"),
                str(cached.get("message") or "No qualifying paginated copy was found."),
                candidates=[
                    CandidateRejection(str(item.get("url") or ""), str(item.get("reason") or ""))
                    for item in cached.get("candidates", [])
                    if isinstance(item, dict)
                ],
                cached=True,
            )
    if refresh:
        client.library.delete_official_copy_search(identity_key)
    try:
        results = (tavily_client or TavilyClient()).search(tavily_case_query(cluster, query))
    except TavilyConfigurationError as exc:
        return OfficialCopyResolution(False, "configuration", str(exc))
    except TavilyAuthenticationError as exc:
        return OfficialCopyResolution(False, "authentication", str(exc))
    except TavilyNetworkError as exc:
        return OfficialCopyResolution(False, "network", str(exc))
    except TavilyError as exc:
        return OfficialCopyResolution(False, "network", str(exc))

    rejections: list[CandidateRejection] = []
    for candidate in results:
        direct_error = ""
        try:
            webpage = extract_webpage_text(candidate.url, require_https=True)
            imported = _validate_and_persist_candidate(
                client,
                cluster,
                query=query,
                title="\n".join(part for part in (candidate.title, webpage.title) if part),
                body=webpage.text,
                source_url=candidate.url,
                retrieval_mode="direct",
            )
            return OfficialCopyResolution(True, "success", "Found a qualifying official reporter copy.", imported, rejections)
        except (RuntimeError, ValueError) as exc:
            direct_error = str(exc)
        if candidate.raw_content:
            try:
                _validate_public_destination(candidate.url, require_https=True)
                imported = _validate_and_persist_candidate(
                    client,
                    cluster,
                    query=query,
                    title=candidate.title,
                    body=candidate.raw_content,
                    source_url=candidate.url,
                    retrieval_mode="tavily_raw",
                )
                return OfficialCopyResolution(True, "success", "Found a qualifying official reporter copy.", imported, rejections)
            except (RuntimeError, ValueError) as exc:
                rejections.append(CandidateRejection(candidate.url, _concise_reason(str(exc) or direct_error)))
        else:
            rejections.append(CandidateRejection(candidate.url, _concise_reason(direct_error)))

    message = "Tavily found no candidate that passed case identity and official-pagination validation."
    outcome = {
        "category": "validation" if results else "no_result",
        "message": message,
        "candidates": [{"url": item.url, "reason": item.reason} for item in rejections],
    }
    client.library.write_official_copy_search(identity_key, outcome, ttl_hours=24)
    return OfficialCopyResolution(False, str(outcome["category"]), message, candidates=rejections)


def _validate_and_persist_candidate(
    client: Any,
    cluster: dict[str, Any],
    *,
    query: str,
    title: str,
    body: str,
    source_url: str,
    retrieval_mode: str,
) -> OfficialImportResult:
    cleaned = clean_imported_opinion_text(body)
    words = re.findall(r"\b\w+\b", cleaned)
    if len(cleaned) < MIN_OPINION_CHARACTERS or len(words) < MIN_OPINION_WORDS:
        raise ValueError("Candidate is a snippet or does not contain substantial opinion text.")
    front = "\n".join(part for part in (title, cleaned[:8000]) if part)
    expected = normalize_official_citation(
        str(cluster.get("official_citation") or official_citation_from_cluster(cluster)) or query
    )
    citations = [normalize_official_citation(match.group(0)) for match in OFFICIAL_CITATION_RE.finditer(front)]
    if expected:
        if expected not in citations:
            raise ValueError(f"Candidate front matter does not contain the exact citation {expected}.")
        citation = expected
    else:
        citation = next((value for value in citations if value), "")
        if not citation:
            raise ValueError("Candidate front matter has no California official reporter citation.")
        _validate_uncited_identity(cluster, front)
    normalized = normalize_external_reporter_markers(cleaned, citation)
    provisional = dict(cluster)
    provisional["official_citation"] = citation
    from .citation_model import official_citation_dict_from_text
    parsed = official_citation_dict_from_text(citation)
    if parsed is not None:
        provisional["citations"] = [parsed, *(provisional.get("citations") if isinstance(provisional.get("citations"), list) else [])]
    quality = official_pagination_quality(provisional, [opinion_display_text({"plain_text": normalized})])
    if not quality.eligible:
        raise ValueError(quality.reason)
    return persist_official_opinion(
        client,
        case_name=str(cluster.get("case_name") or imported_case_name_from_text(front)),
        official_citation=citation,
        imported_text=normalized,
        source_url=source_url,
        existing_cluster=cluster if cluster_id_from_cluster(cluster) else None,
        source_provider="external_web",
        retrieval_provider="tavily",
        retrieval_mode=retrieval_mode,
    )


def _validate_uncited_identity(cluster: dict[str, Any], front: str) -> None:
    expected_name = _identity_name(str(cluster.get("case_name") or cluster.get("case_name_full") or ""))
    found_name = _identity_name(imported_case_name_from_text(front))
    if not expected_name or not found_name or expected_name != found_name:
        raise ValueError("Candidate case name does not match the requested case.")
    docket = _cluster_docket(cluster)
    docket_match = bool(docket and re.search(rf"(?<![A-Z0-9]){re.escape(docket)}(?![A-Z0-9])", front, re.IGNORECASE))
    filed = str(cluster.get("date_filed") or "").strip()
    year = filed[:4] if re.fullmatch(r"\d{4}.*", filed) else ""
    date_match = bool(year and re.search(rf"\b{re.escape(year)}\b", front))
    if not (docket_match or date_match):
        raise ValueError("Candidate does not match the requested docket number or filing date.")


def _identity_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_case_title(value).casefold()).strip()


def _cluster_docket(cluster: dict[str, Any]) -> str:
    direct = str(cluster.get("docket_number") or "").strip()
    if direct:
        return direct
    docket = cluster.get("docket")
    return str(docket.get("docket_number") or "").strip() if isinstance(docket, dict) else ""


def _concise_reason(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:240] or "Candidate could not be retrieved or validated."


def result_hostname(result: OfficialCopyResolution) -> str:
    if result.imported is None:
        return ""
    return urlparse(str(result.imported.opinion.get("source_url") or "")).hostname or ""
