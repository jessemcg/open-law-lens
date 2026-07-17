from __future__ import annotations

import re
from typing import Any


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
OFFICIAL_CITATION_RE = re.compile(
    r"\b(?P<volume>\d+)\s+"
    r"(?P<reporter>Cal\.?\s*(?:App\.?\s*)?(?:\d+d|[2-5]th)?)\s+"
    r"(?P<page>\d+)\b",
    re.IGNORECASE,
)


def normalized_reporter(value: str) -> str:
    return re.sub(r"\s+", "", value.strip()).casefold()


def official_citation_parts_from_text(text: str) -> tuple[str, str, str] | None:
    match = OFFICIAL_CITATION_RE.search(text)
    if match is None:
        return None
    reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter(match.group("reporter")))
    if reporter is None:
        return None
    return (match.group("volume"), reporter, match.group("page"))


def official_citation_from_parts(parts: tuple[str, str, str]) -> str:
    volume, reporter, page = parts
    return f"{volume} {reporter} {page}"


def official_citation_dict_from_parts(parts: tuple[str, str, str]) -> dict[str, str]:
    volume, reporter, page = parts
    return {"volume": volume, "reporter": reporter, "page": page}


def official_citation_parts_from_cluster(
    cluster: dict[str, object],
) -> tuple[str, str, str] | None:
    explicit = cluster.get("official_citation")
    if isinstance(explicit, str):
        parsed = official_citation_parts_from_text(explicit)
        if parsed is not None:
            return parsed
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return None
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        reporter = citation.get("reporter")
        if not isinstance(reporter, str):
            continue
        display_reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter(reporter))
        if display_reporter is None:
            continue
        volume = str(citation.get("volume") or "").strip()
        page = str(citation.get("page") or "").strip()
        if re.fullmatch(r"\d+", volume) and re.fullmatch(r"\d+", page):
            return (volume, display_reporter, page)
    return None


def official_citation_from_cluster(cluster: dict[str, object]) -> str:
    parsed = official_citation_parts_from_cluster(cluster)
    return official_citation_from_parts(parsed) if parsed is not None else ""


def official_citation_dict_from_text(text: str) -> dict[str, str] | None:
    parsed = official_citation_parts_from_text(text)
    return official_citation_dict_from_parts(parsed) if parsed is not None else None


def canonicalize_cluster_citations(cluster: dict[str, Any]) -> dict[str, Any]:
    canonical = dict(cluster)
    parsed = official_citation_parts_from_cluster(canonical)
    if parsed is None:
        canonical.pop("official_citation", None)
        canonical["citations"] = []
        return canonical
    canonical["official_citation"] = official_citation_from_parts(parsed)
    canonical["citations"] = [official_citation_dict_from_parts(parsed)]
    return canonical


def canonicalize_lookup_result(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    canonical_items: list[Any] = []
    for item in value:
        if not isinstance(item, dict):
            canonical_items.append(item)
            continue
        clusters = item.get("clusters")
        if not isinstance(clusters, list):
            canonical_items.append(item)
            continue
        canonical_items.append(
            {
                **item,
                "clusters": [
                    canonicalize_cluster_citations(cluster)
                    if isinstance(cluster, dict)
                    else cluster
                    for cluster in clusters
                ],
            }
        )
    return canonical_items
