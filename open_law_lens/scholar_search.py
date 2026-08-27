from __future__ import annotations

import re
import urllib.parse


SCHOLAR_CASE_SEARCH_TEMPLATE = "https://scholar.google.com/scholar?hl=en&as_sdt=6,33&q={query}"
CASE_URL_PATH_PREFIX = "/scholar_case"
SCHOLAR_NETLOC = "scholar.google.com"


class ScholarSearchError(RuntimeError):
    """Base error for invalid Scholar search inputs."""


def build_scholar_search_url(query: str) -> str:
    """Return the case-law scoped Scholar search URL for *query*.

    This is a pure URL builder. It never performs direct HTTP: direct HTTP
    Scholar searching was removed in favor of the confined default-browser
    recovery path.
    """
    clean = re.sub(r"\s+", " ", query or "").strip()
    if not clean:
        raise ScholarSearchError("Cannot search Scholar with an empty query.")
    encoded = urllib.parse.quote_plus(clean)
    return SCHOLAR_CASE_SEARCH_TEMPLATE.format(query=encoded)
