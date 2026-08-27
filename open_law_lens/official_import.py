from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .cache import cluster_id_from_cluster
from .citation_model import official_citation_dict_from_text, official_citation_from_cluster
from .external_import import (
    build_external_import_cluster,
    imported_case_name_from_text,
    normalize_official_citation,
    validated_import_official_citation,
)
from .import_text import (
    basic_external_opinion_html,
    clean_imported_opinion_text,
    normalize_external_reporter_markers,
)
from .library import DisplayText, opinion_display_text
from .quality import OfficialPaginationQuality, official_pagination_quality
from .storage import SOURCE_PROVIDER_GOOGLE_SCHOLAR, imported_source_provider

SOURCE_PROVIDER_EXTERNAL_WEB = "external_web"


@dataclass(frozen=True)
class OfficialImportResult:
    cluster: dict[str, Any]
    opinion: dict[str, Any]
    display: DisplayText
    quality: OfficialPaginationQuality


def persist_official_opinion(
    client: Any,
    *,
    case_name: str,
    official_citation: str,
    imported_text: str,
    source_url: str,
    existing_cluster: dict[str, Any] | None = None,
    source_provider: str = "",
    retrieval_mode: str = "direct",
) -> OfficialImportResult:
    cleaned = clean_imported_opinion_text(imported_text)
    if not cleaned:
        raise ValueError("Imported text was empty after cleanup.")
    citation = validated_import_official_citation(official_citation, cleaned)
    if not citation:
        raise ValueError("Official California citation is required.")
    cleaned = normalize_external_reporter_markers(cleaned, citation)

    if existing_cluster is not None and cluster_id_from_cluster(existing_cluster):
        cluster = dict(existing_cluster)
        parsed_citation = official_citation_dict_from_text(citation)
        if parsed_citation is None:
            raise ValueError("Official California citation is required.")
        existing_citation = normalize_official_citation(
            str(cluster.get("official_citation") or official_citation_from_cluster(cluster))
        )
        if existing_citation and existing_citation != citation:
            raise ValueError("Imported opinion citation does not match the CourtListener case.")
        cluster["official_citation"] = citation
        citations = cluster.get("citations")
        if not isinstance(citations, list) or not any(
            normalize_official_citation(
                f"{item.get('volume', '')} {item.get('reporter', '')} {item.get('page', '')}"
            ) == citation
            for item in citations
            if isinstance(item, dict)
        ):
            cluster["citations"] = [parsed_citation, *(citations if isinstance(citations, list) else [])]
    else:
        cluster = build_external_import_cluster(
            case_name=case_name or imported_case_name_from_text(cleaned),
            official_citation=citation,
            imported_text=cleaned,
            source_url=source_url,
        )

    cluster_id = cluster_id_from_cluster(cluster)
    if not cluster_id:
        raise ValueError("Selected case has no cluster id.")
    provider = source_provider or imported_source_provider(source_url)
    digest = hashlib.sha256(f"{cluster_id}\0{source_url}\0{citation}".encode()).hexdigest()[:16]
    text_field = "html_with_citations" if re.search(r"<[a-zA-Z][^>]*>", cleaned) else "plain_text"
    opinion_text: dict[str, str] = {text_field: cleaned}
    formatting_mode = ""
    if provider == SOURCE_PROVIDER_EXTERNAL_WEB and text_field == "plain_text":
        opinion_text = {
            "html_with_citations": basic_external_opinion_html(cleaned),
            "raw_text": cleaned,
        }
        formatting_mode = "basic_external_html"
    opinion = {
        "id": f"official-import-{cluster_id}-{digest}",
        "cluster_id": cluster_id,
        "type": "010combined",
        **opinion_text,
        "source_url": source_url,
        "source_type": "user_imported_official_text",
        "source_provider": provider,
        "retrieval_mode": retrieval_mode,
    }
    if formatting_mode:
        opinion["formatting_mode"] = formatting_mode
    display = opinion_display_text(opinion)
    quality = official_pagination_quality(cluster, [display])
    if not quality.eligible:
        raise ValueError(quality.reason)

    client.library.upsert_cluster(cluster)
    client.library.upsert_opinion(opinion, cluster=cluster)
    client.library.update_case_opinion_ids(cluster_id, [str(opinion["id"])])
    client.library.upsert_lookup(citation, [{"status": 200, "clusters": [cluster]}])
    client.cache.upsert_cluster(cluster)
    client.cache.write_resource("opinions", str(opinion["id"]), opinion)
    client.cache.update_case_opinions(cluster, [str(opinion["id"])])
    client.cache.write_lookup(citation, [{"status": 200, "clusters": [cluster]}])
    return OfficialImportResult(cluster=cluster, opinion=opinion, display=display, quality=quality)


def scholar_source_provider() -> str:
    return SOURCE_PROVIDER_GOOGLE_SCHOLAR
