from __future__ import annotations

import html.parser
import re
import urllib.parse
from dataclasses import dataclass

from .web_import import fetch_url_html


SCHOLAR_CASE_SEARCH_TEMPLATE = "https://scholar.google.com/scholar?hl=en&as_sdt=6,33&q={query}"
CASE_URL_PATH_PREFIX = "/scholar_case"
SCHOLAR_NETLOC = "scholar.google.com"


class ScholarSearchError(RuntimeError):
    """Base error for automated Scholar searches."""


class ScholarCaptchaError(ScholarSearchError):
    """Scholar returned a bot/CAPTCHA challenge instead of results."""


class ScholarNoResultError(ScholarSearchError):
    """No case result was found on the results page."""


@dataclass(frozen=True)
class ScholarSearchResult:
    url: str
    title: str


def build_scholar_search_url(query: str) -> str:
    """Return the case-law scoped Scholar search URL for *query*."""
    clean = re.sub(r"\s+", " ", query or "").strip()
    if not clean:
        raise ScholarSearchError("Cannot search Scholar with an empty query.")
    encoded = urllib.parse.quote_plus(clean)
    return SCHOLAR_CASE_SEARCH_TEMPLATE.format(query=encoded)


def looks_like_captcha_page(html: str) -> bool:
    """Heuristic check for Google bot-detection interstitials."""
    lowered = (html or "").lower()
    needles = (
        "our systems have detected unusual traffic",
        "unusual traffic from your computer network",
        "please show you're not a robot",
        "recaptcha",
        "g-recaptcha",
        "/sorry/index",
    )
    return any(needle in lowered for needle in needles)


def first_case_url_from_html(html_text: str) -> ScholarSearchResult | None:
    """Parse Scholar results HTML and return the first case detail URL.

    Scholar result pages include anchors pointing at
    ``/scholar_case?case=...`` when direct HTTP access is allowed. This walks
    anchors in document order and returns the first whose path begins with the
    case prefix, with its link text as a best-effort title.
    """
    if not html_text:
        return None

    class _AnchorCollector(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.anchors: list[tuple[str, str]] = []
            self._capture_depth = 0
            self._current_href = ""
            self._current_text: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag != "a":
                return
            href = next((value for name, value in attrs if name == "href"), "") or ""
            self._capture_depth = 1
            self._current_href = href
            self._current_text = []

        def handle_data(self, data: str) -> None:
            if self._capture_depth:
                self._current_text.append(data)

        def handle_endtag(self, tag: str) -> None:
            if tag != "a" or not self._capture_depth:
                return
            self._capture_depth = 0
            text = re.sub(r"\s+", " ", "".join(self._current_text)).strip()
            self.anchors.append((self._current_href, text))
            self._current_href = ""
            self._current_text = []

    parser = _AnchorCollector()
    parser.feed(html_text)
    parser.close()

    for href, title in parser.anchors:
        candidate = _resolve_case_url(href)
        if candidate is None:
            continue
        return ScholarSearchResult(url=candidate, title=title)
    return None


def _resolve_case_url(href: str) -> str | None:
    if not href:
        return None
    parsed = urllib.parse.urlparse(href)
    if not parsed.path.startswith(CASE_URL_PATH_PREFIX):
        return None
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() != "https" or parsed.netloc.lower() != SCHOLAR_NETLOC:
            return None
        return urllib.parse.urlunparse(parsed._replace(fragment=""))
    # Scholar sometimes emits relative hrefs ("/scholar_case?case=..."); make
    # them absolute so the existing Fetch path can use them directly.
    return urllib.parse.urlunparse(
        parsed._replace(scheme="https", netloc=SCHOLAR_NETLOC, fragment="")
    )


def search_first_case_direct(query: str) -> ScholarSearchResult:
    """Search Google Scholar case law with direct HTTP and return the first case URL."""
    url = build_scholar_search_url(query)
    try:
        html = fetch_url_html(url)
    except RuntimeError as exc:
        raise ScholarSearchError(f"Could not fetch Scholar search results: {exc}") from exc
    if looks_like_captcha_page(html):
        raise ScholarCaptchaError(
            "Google Scholar showed a CAPTCHA / bot challenge. "
            "Open Scholar manually and paste the case URL."
        )
    result = first_case_url_from_html(html)
    if result is None:
        raise ScholarNoResultError("No case result was found on the Scholar search page.")
    return result
