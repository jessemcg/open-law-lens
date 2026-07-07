from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .cache import cluster_id_from_cluster
from .case_suggestions import (
    case_suggestions_from_library,
    load_concordance_case_suggestions,
    load_concordance_rule_suggestions,
    load_concordance_statute_suggestions,
    merge_case_suggestions,
    resolve_case_lookup_text,
)
from .citation_links import REPORTER_CITATION_PATTERN, cited_case_links, cited_rule_links, cited_statute_links
from .client import (
    CourtListenerClient,
    dedupe_case_clusters,
    format_official_california_citation,
    official_california_reporter_citation,
)
from .config import concordance_file_path
from .external_import import (
    build_external_import_cluster,
    clean_imported_opinion_text,
    imported_case_name_from_text,
    normalize_official_citation,
)
from .library import opinion_display_text
from .quality import official_pagination_quality
from .rules import parse_rule_citation
from .scholar_search import ScholarSearchError, search_first_case_direct
from .statutes import parse_statute_citation
from .web_import import extract_webpage_text


@dataclass(frozen=True)
class AuthorityCandidate:
    authority_type: str
    text: str
    start: int = 0
    end: int = 0


@dataclass
class AuthorityResult:
    ok: bool
    authority_type: str
    input: str
    resolved_input: str = ""
    source: str = ""
    title: str = ""
    citation: str = ""
    identifier: str = ""
    source_url: str = ""
    text: str = ""
    warnings: list[str] = field(default_factory=list)
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "ok": self.ok,
            "authority_type": self.authority_type,
            "input": self.input,
            "resolved_input": self.resolved_input,
            "source": self.source,
            "title": self.title,
            "citation": self.citation,
            "identifier": self.identifier,
            "source_url": self.source_url,
            "text": self.text,
            "text_length": len(self.text),
            "warnings": self.warnings,
        }
        if self.error:
            value["error"] = self.error
        return value


CASE_WHOLE_INPUT_RE = re.compile(
    rf"(\bIn\s+re\b|\bv\.\b|{REPORTER_CITATION_PATTERN})",
    re.IGNORECASE,
)


def detect_authority_candidates(text: str) -> list[AuthorityCandidate]:
    candidates: list[AuthorityCandidate] = []
    for link in cited_statute_links(text):
        candidates.append(AuthorityCandidate("statute", link.lookup_text, link.start_offset, link.end_offset))
    for link in cited_rule_links(text):
        candidates.append(AuthorityCandidate("rule", link.lookup_text, link.start_offset, link.end_offset))
    for link in cited_case_links(text):
        candidates.append(AuthorityCandidate("case", link.lookup_text, link.start_offset, link.end_offset))
    for match in re.finditer(REPORTER_CITATION_PATTERN, text, re.IGNORECASE):
        span = match.span()
        if any(candidate.start <= span[0] and span[1] <= candidate.end for candidate in candidates):
            continue
        candidates.append(AuthorityCandidate("case", match.group(0), span[0], span[1]))
    return sorted(candidates, key=lambda item: (item.start, item.end))


def first_authority_candidate(text: str) -> AuthorityCandidate:
    stripped = re.sub(r"\s+", " ", text).strip()
    if not stripped:
        raise ValueError("No text provided.")
    candidates = detect_authority_candidates(stripped)
    if candidates:
        return candidates[0]
    if parse_statute_citation(stripped) is not None:
        return AuthorityCandidate("statute", stripped, 0, len(stripped))
    if parse_rule_citation(stripped) is not None:
        return AuthorityCandidate("rule", stripped, 0, len(stripped))
    return AuthorityCandidate("case", stripped, 0, len(stripped))


def _case_suggestions(client: CourtListenerClient):
    path = concordance_file_path()
    return merge_case_suggestions(
        case_suggestions_from_library(client.library),
        load_concordance_case_suggestions(path),
        load_concordance_statute_suggestions(path),
        load_concordance_rule_suggestions(path),
    )


def resolve_case_input(value: str, client: CourtListenerClient) -> tuple[str, list[str]]:
    query = re.sub(r"\s+", " ", value).strip()
    if not query:
        raise ValueError("Case citation or query is required.")
    resolved = resolve_case_lookup_text(query, _case_suggestions(client))
    if resolved:
        return resolved, []
    return query, ["No unique library/concordance shortcut matched; used direct case lookup."]


def extract_authority(
    value: str,
    *,
    authority_type: str = "auto",
    refresh: bool = False,
    client: CourtListenerClient | None = None,
) -> AuthorityResult:
    client = client or CourtListenerClient.default()
    candidate = (
        first_authority_candidate(value)
        if authority_type == "auto"
        else AuthorityCandidate(authority_type, re.sub(r"\s+", " ", value).strip(), 0, len(value))
    )
    if candidate.authority_type == "statute":
        return extract_statute(candidate.text, refresh=refresh, client=client, original_input=value)
    if candidate.authority_type == "rule":
        return extract_rule(candidate.text, refresh=refresh, client=client, original_input=value)
    return extract_case(candidate.text, refresh=refresh, client=client, original_input=value)


def extract_statute(
    citation: str,
    *,
    refresh: bool = False,
    client: CourtListenerClient | None = None,
    original_input: str = "",
) -> AuthorityResult:
    client = client or CourtListenerClient.default()
    statute = client.lookup_statute(citation, refresh=refresh)
    statute_id = str(statute.get("statute_id") or "").strip()
    return AuthorityResult(
        ok=True,
        authority_type="statute",
        input=original_input or citation,
        resolved_input=str(statute.get("citation") or citation),
        source=client.last_lookup_source or "Library",
        title=str(statute.get("title") or ""),
        citation=str(statute.get("citation") or ""),
        identifier=statute_id,
        source_url=str(statute.get("source_url") or ""),
        text=str(statute.get("text") or ""),
    )


def extract_rule(
    citation: str,
    *,
    refresh: bool = False,
    client: CourtListenerClient | None = None,
    original_input: str = "",
) -> AuthorityResult:
    client = client or CourtListenerClient.default()
    rule = client.lookup_rule(citation, refresh=refresh)
    rule_id = str(rule.get("rule_id") or "").strip()
    return AuthorityResult(
        ok=True,
        authority_type="rule",
        input=original_input or citation,
        resolved_input=str(rule.get("citation") or citation),
        source=client.last_lookup_source or "Library",
        title=str(rule.get("title") or ""),
        citation=str(rule.get("citation") or ""),
        identifier=rule_id,
        source_url=str(rule.get("source_url") or ""),
        text=str(rule.get("text") or ""),
    )


def extract_case(
    citation: str,
    *,
    refresh: bool = False,
    client: CourtListenerClient | None = None,
    original_input: str = "",
) -> AuthorityResult:
    client = client or CourtListenerClient.default()
    resolved, warnings = resolve_case_input(citation, client)
    result = client.lookup_citation(resolved, refresh=refresh)
    clusters = dedupe_case_clusters(client.clusters_from_lookup(result))
    if not clusters:
        scholar_result = _extract_case_from_scholar(resolved, client=client)
        scholar_result.input = original_input or citation
        scholar_result.warnings = [*warnings, *scholar_result.warnings]
        return scholar_result
    return _extract_case_from_cluster(
        clusters[0],
        resolved=resolved,
        source=client.last_lookup_source or "CourtListener API",
        refresh=refresh,
        client=client,
        original_input=original_input or citation,
        warnings=warnings,
    )


def extract_case_by_cluster_id(
    cluster_id: str,
    *,
    refresh: bool = False,
    client: CourtListenerClient | None = None,
) -> AuthorityResult:
    client = client or CourtListenerClient.default()
    clean_cluster_id = re.sub(r"\s+", "", str(cluster_id or ""))
    if not clean_cluster_id:
        raise ValueError("Cluster ID is required.")
    cluster = client.fetch_url(
        f"/api/rest/v4/clusters/{clean_cluster_id}/",
        kind="clusters",
        refresh=refresh,
    )
    source = client.last_resource_source or "CourtListener API"
    title = str(cluster.get("case_name_short") or cluster.get("case_name") or clean_cluster_id)
    return _extract_case_from_cluster(
        cluster,
        resolved=clean_cluster_id,
        source=source,
        refresh=refresh,
        client=client,
        original_input=title,
        warnings=[],
    )


def _extract_case_from_cluster(
    cluster: dict[str, Any],
    *,
    resolved: str,
    source: str,
    refresh: bool,
    client: CourtListenerClient,
    original_input: str,
    warnings: list[str],
) -> AuthorityResult:
    opinions = client.reader_opinions(client.fetch_cluster_opinions(cluster, refresh=refresh))
    if client.last_opinion_source == "Fetched":
        source = "CourtListener API"
    elif client.last_opinion_source:
        source = client.last_opinion_source
    displays = [client.opinion_display(opinion) for opinion in opinions]
    text = "\n\n".join(display.text for display in displays if display.text).strip()
    quality = official_pagination_quality(cluster, displays)
    if not text:
        warnings = [*warnings, "No opinion text found for first matching cluster."]
    if not quality.eligible:
        warnings = [*warnings, quality.reason or "Case lacks official reporter pagination."]
    formatted = format_official_california_citation(cluster)
    return AuthorityResult(
        ok=bool(text),
        authority_type="case",
        input=original_input,
        resolved_input=resolved,
        source=source,
        title=str(cluster.get("case_name_short") or cluster.get("case_name") or ""),
        citation=formatted.plain_text if formatted else official_california_reporter_citation(cluster),
        identifier=cluster_id_from_cluster(cluster),
        source_url=str(cluster.get("absolute_url") or cluster.get("resource_uri") or ""),
        text=text,
        warnings=warnings,
        error="" if text else "No opinion text found for first matching cluster.",
    )


def _extract_case_from_scholar(query: str, *, client: CourtListenerClient) -> AuthorityResult:
    try:
        found = search_first_case_direct(query)
        webpage = extract_webpage_text(found.url)
        imported_text = clean_imported_opinion_text(webpage.text) or webpage.text
        source = "\n".join(part for part in (found.title, webpage.title, imported_text) if part)
        official_citation = normalize_official_citation(source) or normalize_official_citation(query)
        cluster = build_external_import_cluster(
            case_name=imported_case_name_from_text(source),
            official_citation=official_citation,
            imported_text=imported_text,
            source_url=webpage.url,
        )
        opinion = {
            "id": f"official-import-{cluster_id_from_cluster(cluster)}",
            "cluster_id": cluster_id_from_cluster(cluster),
            "plain_text": imported_text,
            "source_url": webpage.url,
            "source_type": "user_imported_official_text",
        }
        display = opinion_display_text(opinion)
        quality = official_pagination_quality(cluster, [display])
        if not quality.eligible:
            return AuthorityResult(
                ok=False,
                authority_type="case",
                input=query,
                resolved_input=query,
                source="Google Scholar",
                source_url=webpage.url,
                text=display.text,
                warnings=[quality.reason],
                error=quality.reason,
            )
        client.library.upsert_cluster(cluster)
        client.library.upsert_opinion(opinion)
        client.library.update_case_opinion_ids(cluster_id_from_cluster(cluster), [str(opinion["id"])])
        client.library.upsert_lookup(quality.official_citation, [{"status": 200, "clusters": [cluster]}])
        client.cache.upsert_cluster(cluster)
        client.cache.write_resource("opinions", str(opinion["id"]), opinion)
        client.cache.update_case_opinions(cluster, [str(opinion["id"])])
        client.cache.write_lookup(quality.official_citation, [{"status": 200, "clusters": [cluster]}])
        formatted = format_official_california_citation(cluster)
        return AuthorityResult(
            ok=True,
            authority_type="case",
            input=query,
            resolved_input=quality.official_citation or query,
            source="Google Scholar",
            title=str(cluster.get("case_name_short") or cluster.get("case_name") or ""),
            citation=formatted.plain_text if formatted else quality.official_citation,
            identifier=cluster_id_from_cluster(cluster),
            source_url=webpage.url,
            text=display.text,
        )
    except (ScholarSearchError, RuntimeError, ValueError) as exc:
        return AuthorityResult(
            ok=False,
            authority_type="case",
            input=query,
            resolved_input=query,
            source="Google Scholar",
            warnings=["CourtListener returned no case cluster; Scholar fallback did not produce an import."],
            error=str(exc),
        )


def read_selected_text_from_os() -> tuple[str, str]:
    command_candidates: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("wl-paste --no-newline --primary", ("wl-paste", "--no-newline", "--primary")),
        ("xclip -o -selection primary", ("xclip", "-o", "-selection", "primary")),
        ("xsel --output --primary", ("xsel", "--output", "--primary")),
        ("wl-paste --no-newline", ("wl-paste", "--no-newline")),
        ("xclip -o -selection clipboard", ("xclip", "-o", "-selection", "clipboard")),
        ("xsel --output --clipboard", ("xsel", "--output", "--clipboard")),
    )
    attempted: list[str] = []
    available = False
    for label, command in command_candidates:
        if shutil.which(command[0]) is None:
            continue
        available = True
        attempted.append(label)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
        except Exception:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), label
    if not available:
        raise RuntimeError("No supported clipboard utility was found. Install wl-paste, xclip, or xsel.")
    raise RuntimeError(
        "No selected text was available from OS selection/clipboard. "
        f"Commands tried: {', '.join(attempted)}"
    )
