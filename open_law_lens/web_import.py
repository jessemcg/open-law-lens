from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser


WEB_FETCH_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) OpenLawLens/0.1 Safari/537.36"
)
WEB_FETCH_MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ExtractedWebpage:
    url: str
    title: str
    text: str


def validated_http_url(url: str, *, require_https: bool = False) -> str:
    candidate = (url or "").strip()
    if not candidate:
        raise RuntimeError("Enter a URL.")
    parsed = urllib.parse.urlparse(candidate)
    schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme.lower() not in schemes or not parsed.netloc:
        if require_https:
            raise RuntimeError("Automatic imports require a public HTTPS URL.")
        raise RuntimeError("URL must start with http:// or https://.")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("URLs containing credentials are not allowed.")
    if not parsed.hostname:
        raise RuntimeError("URL must include a hostname.")
    return parsed._replace(fragment="").geturl()


def _validate_public_destination(url: str, *, require_https: bool = False) -> str:
    clean = validated_http_url(url, require_https=require_https)
    parsed = urllib.parse.urlparse(clean)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise RuntimeError("Could not resolve URL hostname.") from exc
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0].split("%", 1)[0])
        except ValueError as exc:
            raise RuntimeError("URL resolved to an invalid address.") from exc
        if not ip.is_global:
            raise RuntimeError("URL resolves to a private, local, or reserved address.")
    return clean


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def fetch_url_html(url: str, *, require_https: bool = False) -> str:
    headers = {
        "User-Agent": WEB_FETCH_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    current_url = _validate_public_destination(url, require_https=require_https)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    for _redirect in range(6):
        request = urllib.request.Request(current_url, headers=headers, method="GET")
        try:
            with opener.open(request, timeout=45) as response:
                content_type = response.headers.get_content_type().lower()
                if content_type and content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise RuntimeError(f"URL did not return HTML content: {content_type}")
                raw = response.read(WEB_FETCH_MAX_BYTES + 1)
                if len(raw) > WEB_FETCH_MAX_BYTES:
                    raise RuntimeError("Webpage is too large to extract safely.")
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location", "")
                if not location:
                    raise RuntimeError("Redirect response did not include a destination.") from exc
                current_url = _validate_public_destination(
                    urllib.parse.urljoin(current_url, location),
                    require_https=require_https,
                )
                continue
            raise RuntimeError(f"Could not fetch URL: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"Could not fetch URL: {reason}") from exc
        except socket.timeout as exc:
            raise RuntimeError("Could not fetch URL: request timed out.") from exc
    raise RuntimeError("URL redirected too many times.")


def extract_webpage_text(url: str, *, require_https: bool = False) -> ExtractedWebpage:
    clean_url = validated_http_url(url, require_https=require_https)
    html = fetch_url_html(clean_url, require_https=require_https)

    scholar = extract_google_scholar_opinion_text(html)
    if scholar is not None:
        return ExtractedWebpage(url=clean_url, title=scholar.title, text=scholar.text)

    try:
        import trafilatura
    except ImportError as exc:
        raise RuntimeError("URL extraction requires trafilatura. Run `uv sync` to install dependencies.") from exc

    text = trafilatura.extract(
        html,
        url=clean_url,
        include_comments=False,
        include_tables=True,
        output_format="txt",
    )
    if not text or not text.strip():
        raise RuntimeError("No readable opinion text was found at that URL.")

    title = ""
    try:
        metadata = trafilatura.extract_metadata(html, default_url=clean_url)
        if metadata is not None and metadata.title:
            title = str(metadata.title).strip()
    except Exception:
        title = ""

    normalized = normalize_extracted_text(text)
    if not normalized:
        raise RuntimeError("No readable opinion text was found at that URL.")
    return ExtractedWebpage(url=clean_url, title=title, text=normalized)


@dataclass(frozen=True)
class _ScholarOpinionText:
    title: str
    text: str


def extract_google_scholar_opinion_text(html_text: str) -> _ScholarOpinionText | None:
    if "gs_opinion" not in html_text and "gsl_pagenum2" not in html_text:
        return None
    parser = _GoogleScholarOpinionParser()
    parser.feed(html_text)
    parser.close()
    text = normalize_extracted_text(parser.text())
    if not text:
        return None
    return _ScholarOpinionText(title=parser.title(), text=text)


def normalize_extracted_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class _GoogleScholarOpinionParser(HTMLParser):
    BLOCK_TAGS = {"center", "div", "h1", "h2", "h3", "h4", "li", "p"}
    SKIP_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_opinion = False
        self._opinion_div_depth = 0
        self._skip_depth = 0
        self._parts: list[str] = []
        self._pending_space = False
        self._pending_break = False
        self._capture_title_depth = 0
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if not self._in_opinion:
            if tag == "div" and attr_map.get("id") == "gs_opinion":
                self._in_opinion = True
                self._opinion_div_depth = 1
            return

        if tag == "div":
            self._opinion_div_depth += 1
        if self._skip_depth:
            self._skip_depth += 1
            return
        if self._should_skip_tag(tag, attr_map):
            self._skip_depth += 1
            return
        if tag == "br":
            self._queue_block_break()
            return
        if tag in self.BLOCK_TAGS:
            self._queue_block_break()
        if tag == "h3" and attr_map.get("id") == "gsl_case_name":
            self._capture_title_depth = 1
        elif self._capture_title_depth:
            self._capture_title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._in_opinion:
            return
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self.BLOCK_TAGS:
            self._queue_block_break()
        if self._capture_title_depth:
            self._capture_title_depth -= 1
        if tag == "div":
            self._opinion_div_depth -= 1
            if self._opinion_div_depth <= 0:
                self._in_opinion = False

    def handle_data(self, data: str) -> None:
        if not self._in_opinion or self._skip_depth:
            return
        self._append_data(data)
        if self._capture_title_depth:
            self._title_parts.append(data)

    def text(self) -> str:
        return "".join(self._parts).strip()

    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._title_parts)).strip()

    def _should_skip_tag(self, tag: str, attr_map: dict[str, str | None]) -> bool:
        if tag in self.SKIP_TAGS:
            return True
        if attr_map.get("id") == "gs_dont_print":
            return True
        classes = set((attr_map.get("class") or "").split())
        if "gsl_pagenum" in classes and "gsl_pagenum2" not in classes:
            return True
        return False

    def _append_data(self, data: str) -> None:
        has_leading_space = data[:1].isspace()
        has_trailing_space = data[-1:].isspace()
        text = re.sub(r"\s+", " ", data.strip())
        if not text:
            if self._has_text() and not self._ends_with_break():
                self._pending_space = True
            return
        if has_leading_space:
            self._pending_space = True
        self._append_text(text)
        if has_trailing_space:
            self._pending_space = True

    def _append_text(self, text: str) -> None:
        self._flush_pending(text[:1])
        self._parts.append(text)

    def _queue_block_break(self) -> None:
        if self._has_text() and not self._ends_with_break():
            self._pending_break = True
        self._pending_space = False

    def _flush_pending(self, next_char: str) -> None:
        if self._pending_break:
            self._trim_trailing_spaces()
            if self._has_text() and not self._ends_with_break():
                self._parts.append("\n\n")
            self._pending_break = False
            self._pending_space = False
            return
        if self._pending_space and self._should_insert_space(next_char):
            self._parts.append(" ")
        self._pending_space = False

    def _should_insert_space(self, next_char: str) -> bool:
        if not self._parts or not next_char:
            return False
        previous = self._parts[-1][-1:] if self._parts[-1] else ""
        if not previous or previous.isspace():
            return False
        return next_char not in ".,;:)]}?!"

    def _trim_trailing_spaces(self) -> None:
        while self._parts and self._parts[-1] == "":
            self._parts.pop()
        if self._parts:
            self._parts[-1] = self._parts[-1].rstrip()

    def _has_text(self) -> bool:
        return bool(self._parts and "".join(self._parts).strip())

    def _ends_with_break(self) -> bool:
        return bool(self._parts and self._parts[-1].endswith("\n\n"))
