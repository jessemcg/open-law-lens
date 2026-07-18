from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .citation_model import (
    canonicalize_lookup_result,
    official_citation_from_cluster,
    official_citation_parts_from_text,
)

SOURCE_PROVIDER_COURTLISTENER = "courtlistener"
SOURCE_PROVIDER_GOOGLE_SCHOLAR = "google_scholar"
SOURCE_PROVIDER_CALIFORNIA_COURTS = "california_courts"
SOURCE_PROVIDER_MANUAL_IMPORT = "manual_import"
SOURCE_PROVIDER_UNKNOWN = "unknown"
SOURCE_PROVIDER_LABELS = {
    SOURCE_PROVIDER_COURTLISTENER: "CourtListener",
    SOURCE_PROVIDER_GOOGLE_SCHOLAR: "Google Scholar",
    SOURCE_PROVIDER_CALIFORNIA_COURTS: "California Courts",
    SOURCE_PROVIDER_MANUAL_IMPORT: "Imported text",
    SOURCE_PROVIDER_UNKNOWN: "Unknown source",
}


def normalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_source_provider(value: object) -> str:
    provider = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if provider in SOURCE_PROVIDER_LABELS:
        return provider
    return SOURCE_PROVIDER_UNKNOWN


def source_provider_label(value: object) -> str:
    return SOURCE_PROVIDER_LABELS[normalize_source_provider(value)]


def imported_source_provider(source_url: str) -> str:
    hostname = (urlparse(source_url.strip()).hostname or "").casefold()
    if hostname == "scholar.google.com" or hostname.endswith(".scholar.google.com"):
        return SOURCE_PROVIDER_GOOGLE_SCHOLAR
    if hostname == "courts.ca.gov" or hostname.endswith(".courts.ca.gov"):
        return SOURCE_PROVIDER_CALIFORNIA_COURTS
    return SOURCE_PROVIDER_MANUAL_IMPORT


def tagged_source_payload(
    payload: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    return {
        **payload,
        "source_provider": normalize_source_provider(provider),
    }


def tagged_lookup_result(
    result: list[dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for item in result:
        clusters = item.get("clusters")
        if not isinstance(clusters, list):
            tagged.append(item)
            continue
        tagged.append(
            {
                **item,
                "clusters": [
                    tagged_source_payload(cluster, provider)
                    if isinstance(cluster, dict)
                    else cluster
                    for cluster in clusters
                ],
            }
        )
    return tagged


def payload_source_provider(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return SOURCE_PROVIDER_UNKNOWN
    provider = normalize_source_provider(payload.get("source_provider"))
    if provider != SOURCE_PROVIDER_UNKNOWN:
        return provider
    source_type = str(payload.get("source_type") or "").strip()
    if source_type in {
        "user_imported_external_case",
        "user_imported_official_text",
    }:
        return imported_source_provider(str(payload.get("source_url") or ""))
    return SOURCE_PROVIDER_UNKNOWN


def source_payload_with_default(
    payload: dict[str, Any],
    default_provider: str,
) -> dict[str, Any]:
    provider = payload_source_provider(payload)
    if provider == SOURCE_PROVIDER_UNKNOWN:
        provider = default_provider
    return tagged_source_payload(payload, provider)


def displayed_case_source_provider(
    cluster: dict[str, Any],
    opinions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    *,
    explicit: str = "",
) -> str:
    explicit_provider = normalize_source_provider(explicit)
    if explicit_provider != SOURCE_PROVIDER_UNKNOWN:
        return explicit_provider
    for opinion in opinions:
        provider = payload_source_provider(opinion)
        if provider != SOURCE_PROVIDER_UNKNOWN:
            return provider
    return payload_source_provider(cluster)


def resource_id_from_url(url: str) -> str:
    stripped = url.rstrip("/")
    return stripped.rsplit("/", 1)[-1]


def cluster_id_from_cluster(cluster: dict[str, Any]) -> str:
    value = cluster.get("id")
    if value is not None and str(value).strip():
        return str(value).strip()
    for key in ("resource_uri", "absolute_url", "cluster_url"):
        url = cluster.get(key)
        if isinstance(url, str) and url.strip():
            return resource_id_from_url(url)
    return ""


def citation_lookup_key(citation: str) -> str:
    return re.sub(r"\s+", "", normalize_citation(citation)).casefold()


def external_import_primary_citation_key(cluster: dict[str, Any]) -> str:
    if cluster.get("source_type") != "user_imported_external_case":
        return ""
    official = official_citation_from_cluster(cluster)
    return citation_lookup_key(official) if official else ""


def external_import_matches_lookup(cluster: dict[str, Any], normalized_citation: str) -> bool:
    primary = external_import_primary_citation_key(cluster)
    return not primary or primary == citation_lookup_key(normalized_citation)


def lookup_result_had_clusters(result: list[dict[str, Any]]) -> bool:
    return any(isinstance(item.get("clusters"), list) and bool(item.get("clusters")) for item in result)


def filter_lookup_result_for_citation(
    result: list[dict[str, Any]],
    normalized_citation: str,
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
            if isinstance(cluster, dict) and external_import_matches_lookup(cluster, normalized_citation)
        ]
        if kept:
            filtered.append({**item, "clusters": kept})
    return filtered


def filter_lookup_result_for_client(
    result: list[dict[str, Any]],
    normalized_citation: str,
) -> list[dict[str, Any]]:
    filtered = filter_lookup_result_for_citation(result, normalized_citation)
    if filtered or not lookup_result_had_clusters(result):
        return filtered
    return []


def filter_lookup_result_to_official_citation(
    result: list[dict[str, Any]],
    normalized_citation: str,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    normalized_key = citation_lookup_key(normalized_citation)
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
            if (
                isinstance(cluster, dict)
                and citation_lookup_key(official_citation_from_cluster(cluster)) == normalized_key
            )
        ]
        if kept:
            filtered.append({**item, "clusters": kept})
    return filtered


def filter_official_lookup_result_if_needed(
    result: list[dict[str, Any]],
    normalized_citation: str,
) -> list[dict[str, Any]]:
    if official_citation_parts_from_text(normalized_citation) is None:
        return result
    return filter_lookup_result_to_official_citation(result, normalized_citation)


def repair_lookup_result_clusters(
    data: Any,
    repaired_clusters: dict[str, dict[str, Any]],
) -> Any | None:
    if not isinstance(data, list):
        return None
    changed = False
    repaired_items: list[Any] = []
    for item in data:
        if not isinstance(item, dict):
            repaired_items.append(item)
            continue
        clusters = item.get("clusters")
        if not isinstance(clusters, list):
            repaired_items.append(item)
            continue
        repaired_item_clusters: list[Any] = []
        for cluster in clusters:
            if isinstance(cluster, dict):
                cluster_id = cluster_id_from_cluster(cluster)
                repaired = repaired_clusters.get(cluster_id)
                if repaired is not None:
                    repaired_item_clusters.append(repaired)
                    changed = True
                    continue
            repaired_item_clusters.append(cluster)
        repaired_items.append({**item, "clusters": repaired_item_clusters})
    return canonicalize_lookup_result(repaired_items) if changed else None
