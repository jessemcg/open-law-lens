from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .cache import cluster_id_from_cluster
from .external_import import (
    imported_case_name_from_text,
    normalize_official_citation,
    validated_import_official_citation,
)
from .import_text import clean_imported_opinion_text, normalize_external_reporter_markers
from .official_import import OfficialImportResult, persist_official_opinion
from .quality import official_pagination_quality
from .scholar_search import SCHOLAR_NETLOC, build_scholar_search_url
from .library import opinion_display_text
from .storage import SOURCE_PROVIDER_GOOGLE_SCHOLAR

CLIPBOARD_MAX_BYTES = 8 * 1024 * 1024
CLIPBOARD_COMMAND_TIMEOUT_SECONDS = 10

# A qualifying officially paginated opinion must embed at least one reporter
# page marker in the expected series. This mirrors the floor enforced by
# `official_pagination_quality`, which requires plausible embedded markers;
# it is our explicit "minimum marker count" gate for clipboard imports.
MIN_OFFICIAL_PAGINATION_MARKERS = 1

SCHOLAR_CASE_PATH_PREFIX = "/scholar_case"


class ScholarBrowserError(RuntimeError):
    """Base error for default-browser Scholar recovery."""


class ScholarSourceUrlError(ScholarBrowserError):
    """The supplied source URL is not a Scholar case URL."""


@dataclass(frozen=True)
class ScholarBrowserLaunch:
    citation: str
    scholar_url: str
    handler_name: str
    handler_desktop_id: str


@dataclass(frozen=True)
class ScholarClipboardImport:
    case_name: str
    official_citation: str
    cluster_id: str
    opinion_id: str
    marker_count: int
    eligible: bool
    reason: str = ""


def require_official_citation(citation: str) -> str:
    normalized = normalize_official_citation(citation or "")
    if not normalized:
        raise ScholarBrowserError(
            "A California official reporter citation is required (e.g. '11 Cal.5th 614')."
        )
    return normalized


def validate_scholar_source_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        raise ScholarSourceUrlError("A Scholar case URL is required.")
    parsed = urlparse(candidate)
    if parsed.scheme != "https":
        raise ScholarSourceUrlError("Scholar import requires an HTTPS URL.")
    host = (parsed.hostname or "").casefold()
    if host != SCHOLAR_NETLOC and not host.endswith("." + SCHOLAR_NETLOC):
        raise ScholarSourceUrlError("Scholar import requires a scholar.google.com URL.")
    if not parsed.path.startswith(SCHOLAR_CASE_PATH_PREFIX):
        raise ScholarSourceUrlError("Scholar import requires a /scholar_case URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ScholarSourceUrlError("Scholar URLs containing credentials are not allowed.")
    return parsed._replace(fragment="").geturl()


def build_scholar_case_search_url(citation: str) -> str:
    normalized = require_official_citation(citation)
    return build_scholar_search_url(normalized)


def resolve_default_https_handler() -> tuple[str, str]:
    """Return ``(name, desktop_id)`` for the current default HTTPS handler.

    This intentionally resolves the handler at call time so a user changing
    their default browser is respected without restarting anything. No browser,
    application ID, executable, or profile name is hardcoded.
    """
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError) as exc:
        raise ScholarBrowserError(
            "PyGObject/Gio is unavailable; cannot resolve the default browser."
        ) from exc
    handler = Gio.AppInfo.get_default_for_uri_scheme("https")
    if handler is None:
        raise ScholarBrowserError("No default handler is registered for https:// URIs.")
    name = str(handler.get_name() or "").strip()
    desktop_id = str(handler.get_id() or "").strip()
    if not name and not desktop_id:
        raise ScholarBrowserError("The default https handler exposed no usable identity.")
    return name, desktop_id


def launch_scholar_url(url: str) -> tuple[str, str]:
    """Launch *url* with the current default HTTPS handler via Gio.

    Returns ``(handler_name, handler_desktop_id)``. The URL must be the
    case-law Scholar search URL we built. This is the only launch path and
    never targets a browser by executable or application ID.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ScholarBrowserError("Scholar launch requires an HTTPS URL.")
    host = (parsed.hostname or "").casefold()
    if host != SCHOLAR_NETLOC and not host.endswith("." + SCHOLAR_NETLOC):
        raise ScholarBrowserError("Scholar launch requires a scholar.google.com URL.")
    name, desktop_id = resolve_default_https_handler()
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
    except (ImportError, ValueError) as exc:
        raise ScholarBrowserError(
            "PyGObject/Gio is unavailable; cannot launch the default browser."
        ) from exc
    launched = Gio.AppInfo.launch_default_for_uri(url, None)
    if not launched:
        raise ScholarBrowserError(
            "The default https handler could not launch the Scholar URL."
        )
    return name, desktop_id


def _read_command_capped(command: tuple[str, ...], max_bytes: int) -> str | None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert process.stdout is not None
        data = process.stdout.read(max_bytes + 1)
    finally:
        if process.stdout is not None:
            process.stdout.close()
    try:
        process.wait(timeout=CLIPBOARD_COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return None
    if process.returncode != 0:
        return None
    if len(data) > max_bytes:
        raise ScholarBrowserError(
            f"Clipboard content exceeds the {max_bytes // (1024 * 1024)} MiB limit."
        )
    text = data.decode("utf-8", errors="replace").strip()
    return text or None


def read_regular_clipboard(max_bytes: int = CLIPBOARD_MAX_BYTES) -> str:
    """Read only the regular clipboard, preferring ``wl-paste``.

    The primary X/Wayland selection is deliberately excluded so a stray
    selection never masquerades as the chosen Scholar opinion. The content is
    never logged or printed by this module.
    """
    commands: tuple[tuple[str, ...], ...] = (
        ("wl-paste", "--no-newline"),
        ("xclip", "-o", "-selection", "clipboard"),
        ("xsel", "--output", "--clipboard"),
    )
    available = False
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        available = True
        try:
            text = _read_command_capped(command, max_bytes)
        except ScholarBrowserError:
            raise
        except Exception:
            continue
        if text:
            return text
    if not available:
        raise ScholarBrowserError(
            "No supported clipboard utility was found. Install wl-paste, xclip, or xsel."
        )
    raise ScholarBrowserError("No text was available from the regular clipboard.")


def _provisional_cluster_for_quality(
    *,
    citation: str,
    cleaned_text: str,
    case_name: str,
    existing_cluster: dict[str, Any] | None,
) -> dict[str, Any]:
    from .external_import import build_external_import_cluster
    from .citation_model import official_citation_dict_from_text

    if existing_cluster is not None and cluster_id_from_cluster(existing_cluster):
        provisional = dict(existing_cluster)
        provisional["official_citation"] = citation
        parsed = official_citation_dict_from_text(citation)
        citations = existing_cluster.get("citations")
        if parsed is not None and (
            not isinstance(citations, list)
            or not any(
                isinstance(item, dict)
                and normalize_official_citation(
                    f"{item.get('volume', '')} {item.get('reporter', '')} {item.get('page', '')}"
                )
                == citation
                for item in citations
            )
        ):
            provisional["citations"] = [
                parsed,
                *(citations if isinstance(citations, list) else []),
            ]
        return provisional
    return build_external_import_cluster(
        case_name=case_name or imported_case_name_from_text(cleaned_text),
        official_citation=citation,
        imported_text=cleaned_text,
        source_url="",
    )


def import_scholar_text(
    client: Any,
    *,
    citation: str,
    source_url: str,
    clipboard_text: str,
    case_name: str = "",
    existing_cluster: dict[str, Any] | None = None,
) -> ScholarClipboardImport:
    """Validate and persist a copied Scholar opinion through the shared service.

    This is the single persistence path for default-browser Scholar recovery.
    It validates the exact citation, cleans browser/account chrome, requires a
    qualifying officially paginated opinion, and then persists via
    ``persist_official_opinion``. On any validation failure it raises without
    mutating the Library or Research Cache.
    """
    if not clipboard_text or not clipboard_text.strip():
        raise ScholarBrowserError("Clipboard content was empty.")

    normalized = require_official_citation(citation)
    clean_url = validate_scholar_source_url(source_url)

    cleaned = clean_imported_opinion_text(clipboard_text)
    if not cleaned:
        raise ScholarBrowserError("Clipboard content was empty after cleanup.")

    # Require the document to match the requested citation, not merely to
    # contain a similar one.
    try:
        validated = validated_import_official_citation(normalized, cleaned)
    except ValueError as exc:
        raise ScholarBrowserError(
            "Clipboard text does not match the requested official citation."
        ) from exc
    if not validated or validated != normalized:
        raise ScholarBrowserError(
            "Clipboard text does not match the requested official citation."
        )

    normalized_text = normalize_external_reporter_markers(cleaned, normalized)

    provisional = _provisional_cluster_for_quality(
        citation=normalized,
        cleaned_text=cleaned,
        case_name=case_name,
        existing_cluster=existing_cluster,
    )
    display = opinion_display_text({"plain_text": normalized_text})
    quality = official_pagination_quality(provisional, [display])
    if not quality.eligible or quality.marker_count < MIN_OFFICIAL_PAGINATION_MARKERS:
        raise ScholarBrowserError(
            quality.reason or "Clipboard text has no qualifying official reporter pagination."
        )

    result: OfficialImportResult = persist_official_opinion(
        client,
        case_name=case_name,
        official_citation=normalized,
        imported_text=normalized_text,
        source_url=clean_url,
        existing_cluster=existing_cluster,
        source_provider=SOURCE_PROVIDER_GOOGLE_SCHOLAR,
        retrieval_mode="browser_clipboard",
    )

    resolved_name = (
        str(result.cluster.get("case_name") or result.cluster.get("case_name_full") or "").strip()
        or (case_name or "").strip()
        or imported_case_name_from_text(cleaned)
        or normalized
    )
    return ScholarClipboardImport(
        case_name=resolved_name,
        official_citation=normalized,
        cluster_id=cluster_id_from_cluster(result.cluster),
        opinion_id=str(result.opinion.get("id") or ""),
        marker_count=result.quality.marker_count,
        eligible=result.quality.eligible,
        reason=result.quality.reason,
    )


def scholar_launch_to_json(launch: ScholarBrowserLaunch) -> dict[str, Any]:
    return {
        "ok": True,
        "citation": launch.citation,
        "scholar_url": launch.scholar_url,
        "handler_name": launch.handler_name,
        "handler_desktop_id": launch.handler_desktop_id,
    }


def scholar_import_to_json(imported: ScholarClipboardImport) -> dict[str, Any]:
    return {
        "ok": True,
        "case_name": imported.case_name,
        "official_citation": imported.official_citation,
        "cluster_id": imported.cluster_id,
        "opinion_id": imported.opinion_id,
        "marker_count": imported.marker_count,
        "eligible": imported.eligible,
    }


def scholar_import_failure_json(citation: str, error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "official_citation": normalize_official_citation(citation or ""),
        "case_name": "",
        "cluster_id": "",
        "opinion_id": "",
        "marker_count": 0,
        "eligible": False,
        "error": re.sub(r"\s+", " ", error).strip(),
    }
