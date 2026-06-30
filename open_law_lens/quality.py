from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .citation_model import (
    OFFICIAL_CALIFORNIA_REPORTERS,
    normalized_reporter,
    official_citation_from_cluster,
    official_citation_from_parts,
    official_citation_parts_from_cluster,
    official_citation_parts_from_text,
)
from .library import DisplayText, PageMarker


MAX_REASONABLE_CASE_PAGES = 1000
FIRST_MARKER_TOLERANCE_PAGES = 25


@dataclass(frozen=True)
class OfficialPaginationQuality:
    eligible: bool
    official_citation: str = ""
    reason: str = ""
    marker_count: int = 0


def official_california_reporter_citation(cluster: dict[str, object]) -> str:
    return official_citation_from_cluster(cluster)


def official_california_reporter_parts(
    cluster: dict[str, object],
) -> tuple[str, str, str] | None:
    return official_citation_parts_from_cluster(cluster)


def official_california_reporter_key(
    cluster: dict[str, object],
) -> tuple[str, str, str] | None:
    parsed = official_california_reporter_parts(cluster)
    if parsed is None:
        return None
    volume, reporter, page = parsed
    return (volume.casefold(), normalized_reporter(reporter), page.casefold())


def official_california_reporter_citation_from_text(text: str) -> str:
    parsed = official_citation_parts_from_text(text)
    return official_citation_from_parts(parsed) if parsed is not None else ""


def official_pagination_quality(
    cluster: dict[str, object],
    displays: Iterable[DisplayText],
) -> OfficialPaginationQuality:
    citation = official_california_reporter_citation(cluster)
    parsed = official_california_reporter_parts(cluster)
    if parsed is None:
        return OfficialPaginationQuality(False, reason="No official California reporter citation.")
    _volume, _reporter, first_page_text = parsed
    try:
        first_page = int(first_page_text)
    except ValueError:
        return OfficialPaginationQuality(False, official_citation=citation, reason="Official first page is not numeric.")

    marker_pages = [
        page
        for display in displays
        for marker in display.page_markers
        if (page := _numeric_marker_page(marker)) is not None
    ]
    if not marker_pages:
        return OfficialPaginationQuality(False, official_citation=citation, reason="No embedded reporter page markers.")

    lower_bound = first_page
    upper_bound = first_page + MAX_REASONABLE_CASE_PAGES
    plausible = [page for page in marker_pages if lower_bound <= page <= upper_bound]
    if len(plausible) < max(1, (len(marker_pages) + 1) // 2):
        return OfficialPaginationQuality(
            False,
            official_citation=citation,
            reason="Reporter page markers do not match the official citation range.",
            marker_count=len(marker_pages),
        )

    first_marker = min(plausible)
    if first_marker > first_page + FIRST_MARKER_TOLERANCE_PAGES:
        return OfficialPaginationQuality(
            False,
            official_citation=citation,
            reason="First embedded marker is too far from the official first page.",
            marker_count=len(marker_pages),
        )

    if _descending_pair_count(plausible) > max(1, len(plausible) // 5):
        return OfficialPaginationQuality(
            False,
            official_citation=citation,
            reason="Reporter page markers are not mostly ascending.",
            marker_count=len(marker_pages),
        )

    return OfficialPaginationQuality(
        True,
        official_citation=citation,
        reason="Official citation and embedded reporter pagination found.",
        marker_count=len(marker_pages),
    )


def _numeric_marker_page(marker: PageMarker) -> int | None:
    label = str(marker.page_label).strip()
    if not re.fullmatch(r"\d{1,5}", label):
        return None
    try:
        return int(label)
    except ValueError:
        return None


def _descending_pair_count(values: list[int]) -> int:
    return sum(1 for left, right in zip(values, values[1:]) if right < left)
