from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .library import DisplayText, PageMarker


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
MAX_REASONABLE_CASE_PAGES = 1000
FIRST_MARKER_TOLERANCE_PAGES = 25


@dataclass(frozen=True)
class OfficialPaginationQuality:
    eligible: bool
    official_citation: str = ""
    reason: str = ""
    marker_count: int = 0


def normalized_reporter(value: str) -> str:
    return re.sub(r"\s+", "", value.strip()).casefold()


def official_california_reporter_citation(cluster: dict[str, object]) -> str:
    parsed = official_california_reporter_parts(cluster)
    if parsed is None:
        return ""
    volume, reporter, page = parsed
    return f"{volume} {reporter} {page}"


def official_california_reporter_parts(
    cluster: dict[str, object],
) -> tuple[str, str, str] | None:
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
        if volume and page:
            return (volume, display_reporter, page)
    return None


def official_california_reporter_key(
    cluster: dict[str, object],
) -> tuple[str, str, str] | None:
    parsed = official_california_reporter_parts(cluster)
    if parsed is None:
        return None
    volume, reporter, page = parsed
    return (volume.casefold(), normalized_reporter(reporter), page.casefold())


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
    display_reporter = OFFICIAL_CALIFORNIA_REPORTERS.get(normalized_reporter(match.group("reporter")))
    if display_reporter is None:
        return ""
    return f"{match.group('volume')} {display_reporter} {match.group('page')}"


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
