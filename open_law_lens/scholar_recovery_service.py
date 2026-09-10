"""Shared deterministic Scholar recovery, copy, validation, and import service.

This module owns the full high-level flow:

    baseline identity/request (citation-less identity is first enriched from
      already-fetched metadata: a California appellate case number from
      trusted fields or URL-like raw opinion metadata is preferred over the
      filing year)
      -> deterministic browser recovery (browser_recovery)
      -> regular clipboard read (scholar_browser)
      -> existing Scholar cleanup + identity validation + pagination validation
      -> existing OfficialImport persistence
      -> re-extraction from the durable Library
      -> typed final result

It is the single entry point used by the CLI (``--recover-official`` and
``recover-scholar``), the GTK app, and the embedded legal-researcher sessions.
Persistence goes **only** through ``import_scholar_text`` and
``persist_official_opinion``.

Privacy invariants:

* Clipboard and opinion text are never placed in progress events, errors, logs,
  or MCP messages.
* A copied opinion that fails validation is reported as validation-rejected and
  the CourtListener/slip baseline is preserved untouched.
* The cross-process recovery lock is held from before the browser job through
  clipboard capture, validation, and persistence, so a concurrent recovery can
  never replace the clipboard mid-flight.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from .browser_recovery import (
    DEFAULT_TIMEOUT_SECONDS,
    CancelCallback,
    ProgressCallback,
    REASON_BUSY,
    REASON_CANCELLED,
    REASON_COPY_FAILED,
    REASON_NO_MATCHING_RESULT,
    RecoveryLock,
    ScholarRecoveryOutcome,
    ScholarRecoveryRequest,
    normalize_recovery_query,
    request_from_query,
    run_scholar_recovery,
    validated_filing_year,
)
from .scholar_browser import (
    ScholarBrowserError,
    ScholarClipboardImport,
    import_scholar_text,
    read_regular_clipboard,
)
from .slip_opinions import case_number_from_cluster, case_number_from_url_values

# Outcome values a caller can branch on.
OUTCOME_IMPORTED = "imported"
OUTCOME_REJECTED = "rejected"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_BLOCKED = "blocked"
OUTCOME_FAILED = "failed"
OUTCOME_BUSY = "busy"
OUTCOME_CANCELLED = "cancelled"

# Service-level reason codes for failures detected after the browser job.
REASON_VALIDATION_REJECTED = "validation_rejected"
REASON_PERSISTENCE_FAILED = "persistence_failed"
REASON_REEXTRACT_FAILED = "reextract_failed"

# Service pipeline stages (controlled identifiers).
SERVICE_STAGE_IDENTITY = "identity"
SERVICE_STAGE_LOCK = "lock"
SERVICE_STAGE_BROWSER = "browser_recovery"
SERVICE_STAGE_CLIPBOARD = "clipboard"
SERVICE_STAGE_VALIDATION = "validation"
SERVICE_STAGE_PERSISTENCE = "persistence"
SERVICE_STAGE_REEXTRACTION = "reextraction"


@dataclass(frozen=True)
class ScholarRecoveryServiceResult:
    """The typed final result of one recovery-and-import attempt."""

    outcome: str
    recovery: ScholarRecoveryOutcome
    imported: ScholarClipboardImport | None = None
    authority: Any = None
    reason: str = ""
    # Backward-compatible optional fields: the pipeline stage (controlled
    # identifier) where the outcome was reached and a stable reason code.
    stage: str = ""
    reason_code: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_IMPORTED

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "ok": self.ok,
            "outcome": self.outcome,
            "recovery_outcome": self.recovery.outcome,
            "query": self.recovery.query,
            "reason": self.reason,
            "stage": self.stage,
            "reason_code": self.reason_code,
        }
        if self.imported is not None:
            value["case_name"] = self.imported.case_name
            value["official_citation"] = self.imported.official_citation
            value["cluster_id"] = self.imported.cluster_id
            value["opinion_id"] = self.imported.opinion_id
            value["marker_count"] = self.imported.marker_count
        if self.authority is not None and hasattr(self.authority, "to_json"):
            value["authority"] = self.authority.to_json()
        return value


def _cluster_url_field_values(cluster: Mapping[str, Any]) -> list[str]:
    """Collect URL-like string values from trusted cluster fields only.

    Opinion text is never scanned or logged; only URL-shaped fields (for
    example a raw opinion's ``download_url``) are inspected.
    """
    values: list[str] = []
    for key, value in cluster.items():
        if "url" not in str(key).casefold():
            continue
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return values


def _cluster_recovery_docket(client: Any, cluster: Mapping[str, Any] | None) -> str:
    """Derive the California appellate case number for citation-less identity.

    A trusted direct/nested docket number is preferred. When absent, only
    URL-like fields of the already-fetched raw opinion metadata — especially
    ``download_url`` — are inspected for a California case number (for
    example ``F084030``). A derived number is accepted only when every
    discovered candidate normalizes to one value; otherwise the caller falls
    back to the validated filing year. Metadata-enrichment failure degrades
    to the year path and never triggers a second Scholar search.
    """
    if not isinstance(cluster, Mapping):
        return ""
    direct = _cluster_docket_number(cluster)
    if direct:
        return direct
    candidates: list[str] = []
    trusted = case_number_from_cluster(dict(cluster))
    if trusted:
        candidates.append(trusted)
    url_values = _cluster_url_field_values(cluster)
    try:
        opinions = client.fetch_cluster_opinions(
            cluster,
            refresh=False,
            persist_to_library=False,
            populate_research_cache=False,
        )
    except Exception:
        opinions = []
    if isinstance(opinions, list):
        for opinion in opinions:
            if isinstance(opinion, Mapping):
                url_values.extend(_cluster_url_field_values(opinion))
    derived = case_number_from_url_values(url_values)
    candidates.append(derived)
    # Accept a derived case number only when every discovered candidate
    # normalizes to one value; otherwise fall back to the filing year.
    agreed = {candidate for candidate in candidates if candidate}
    if len(agreed) == 1:
        return next(iter(agreed))
    return ""


def _cluster_filing_year(cluster: Mapping[str, Any] | None) -> str:
    """Extract the validated four-digit filing year from a cluster."""
    if not isinstance(cluster, Mapping):
        return ""
    filed = str(cluster.get("date_filed") or "").strip()
    return validated_filing_year(filed[:4])


def _cluster_docket_number(cluster: Mapping[str, Any] | None) -> str:
    """Conservatively extract the docket/case number from direct and nested
    cluster fields. No additional docket endpoint is fetched."""
    if not isinstance(cluster, Mapping):
        return ""
    direct = str(cluster.get("docket_number") or "").strip()
    if direct:
        return direct
    docket = cluster.get("docket")
    if isinstance(docket, Mapping):
        return str(docket.get("docket_number") or "").strip()
    return ""


def _cluster_case_name(cluster: Mapping[str, Any] | None) -> str:
    if not isinstance(cluster, Mapping):
        return ""
    return str(cluster.get("case_name") or cluster.get("case_name_full") or "").strip()


def _recover_request(
    *,
    query: str,
    citation: str = "",
    cluster_id: str = "",
    case_name: str = "",
    filing_year: str = "",
    docket_number: str = "",
) -> ScholarRecoveryRequest:
    if citation.strip():
        return request_from_query(
            query,
            expected_citation=citation,
            cluster_id=cluster_id,
            case_name=case_name,
        )
    # Citation-less recovery: the free-form search query is never substituted
    # into ``expected_citation`` and never stands in for the case name. The
    # Scholar search is built from the exact quoted case name plus the
    # strongest available discriminator (docket first, otherwise filing year).
    name = normalize_recovery_query(case_name)
    discriminator = docket_number.strip() or validated_filing_year(filing_year)
    return request_from_query(
        f'"{name}" {discriminator}'.strip(),
        expected_citation="",
        cluster_id=cluster_id,
        case_name=case_name,
        filing_year=filing_year.strip(),
        docket_number=docket_number,
    )


def _citationless_identity_ready(
    *,
    case_name: str,
    filing_year: str,
    docket_number: str,
) -> bool:
    """Citation-less recovery requires an exact case name plus a docket/case
    number or a validated filing year; anything less fails closed."""
    if not normalize_recovery_query(case_name):
        return False
    return bool(docket_number.strip() or validated_filing_year(filing_year))


def recover_official_copy(
    client: Any,
    *,
    query: str,
    citation: str = "",
    cluster_id: str = "",
    case_name: str = "",
    filing_year: str = "",
    docket_number: str = "",
    existing_cluster: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> ScholarRecoveryServiceResult:
    """Perform one deterministic recovery and, on success, import and re-extract.

    Returns a typed result; on ``not_found`` / ``blocked`` / ``failed`` / ``busy``
    the baseline is untouched, and on a copied-but-invalid opinion the baseline
    is preserved with ``rejected``.

    For citation-less recovery (empty ``citation``) the explicit identity
    fields (exact case name plus docket number, otherwise filing year) drive
    both the Scholar search and the corroboration; when not supplied directly
    they are derived from ``existing_cluster``.
    """
    started_at = time.monotonic()
    filing_year = filing_year or _cluster_filing_year(existing_cluster)
    docket_number = docket_number or _cluster_docket_number(existing_cluster)
    case_name = case_name.strip() or _cluster_case_name(existing_cluster)
    if not citation.strip():
        # Enrich citation-less identity from already-fetched metadata before
        # the identity gate: a California appellate case number discovered
        # from trusted fields or URL-like raw opinion metadata (for example
        # ``F084030`` from a ``download_url``) is preferred over the filing
        # year. Enrichment failure degrades to the existing year path without
        # aborting the baseline or triggering a second Scholar search.
        docket_number = docket_number or _cluster_recovery_docket(
            client, existing_cluster
        )
    if not citation.strip() and not _citationless_identity_ready(
        case_name=case_name, filing_year=filing_year, docket_number=docket_number
    ):
        # Missing citation-less identity fails closed before the browser state
        # machine runs: no recovery lock is acquired and no browser is opened.
        recovery = ScholarRecoveryOutcome(
            version=1,
            outcome="not_found",
            query=normalize_recovery_query(query),
            source_url="",
            message=(
                "Citation-less recovery requires an exact case name plus a "
                "docket number or filing year."
            ),
        )
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_NOT_FOUND,
            recovery=recovery,
            reason=recovery.message,
            stage=SERVICE_STAGE_IDENTITY,
        )
    request = _recover_request(
        query=query,
        citation=citation,
        cluster_id=cluster_id,
        case_name=case_name,
        filing_year=filing_year,
        docket_number=docket_number,
    )
    # Hold the cross-process recovery lock through clipboard capture,
    # validation, and persistence so another recovery cannot replace the
    # clipboard between the browser job and the service read. The browser job
    # reuses the already-held lock instead of double-acquiring.
    lock = RecoveryLock()
    if not lock.acquire():
        busy_recovery = ScholarRecoveryOutcome(
            version=1,
            outcome="busy",
            query=request.query,
            source_url="",
            message="Another Scholar recovery is already running.",
            stage=SERVICE_STAGE_LOCK,
            reason_code=REASON_BUSY,
        )
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_BUSY,
            recovery=busy_recovery,
            reason=busy_recovery.message,
            stage=SERVICE_STAGE_LOCK,
            reason_code=REASON_BUSY,
        )
    try:
        return _recover_locked(
            client,
            request=request,
            citation=citation,
            case_name=case_name,
            docket_number=docket_number,
            existing_cluster=existing_cluster,
            timeout=timeout,
            progress=progress,
            cancelled=cancelled,
            started_at=started_at,
            lock=lock,
        )
    finally:
        lock.release()


def _recover_locked(
    client: Any,
    *,
    request: ScholarRecoveryRequest,
    citation: str,
    case_name: str,
    docket_number: str,
    existing_cluster: dict[str, Any] | None,
    timeout: float,
    progress: ProgressCallback | None,
    cancelled: CancelCallback | None,
    started_at: float,
    lock: RecoveryLock,
) -> ScholarRecoveryServiceResult:
    recovery = run_scholar_recovery(
        request,
        timeout=timeout,
        progress=progress,
        cancelled=cancelled,
        lock=lock,
    )

    if recovery.outcome == "busy" or recovery.reason_code == REASON_BUSY:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_BUSY, recovery=recovery, reason=recovery.message,
            stage=recovery.stage or SERVICE_STAGE_LOCK, reason_code=REASON_BUSY,
        )
    if recovery.reason_code == REASON_CANCELLED:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_CANCELLED,
            recovery=recovery,
            reason=recovery.message or "Scholar recovery was cancelled.",
            stage=recovery.stage,
            reason_code=REASON_CANCELLED,
        )
    if recovery.outcome != "copied":
        outcome = {
            "not_found": OUTCOME_NOT_FOUND,
            "blocked": OUTCOME_BLOCKED,
            "failed": OUTCOME_FAILED,
        }.get(recovery.outcome, OUTCOME_FAILED)
        reason_code = recovery.reason_code or (
            REASON_NO_MATCHING_RESULT if outcome == OUTCOME_NOT_FOUND else ""
        )
        return ScholarRecoveryServiceResult(
            outcome=outcome,
            recovery=recovery,
            reason=recovery.message,
            stage=recovery.stage or SERVICE_STAGE_BROWSER,
            reason_code=reason_code,
        )

    progress_stage(progress, "Validating copy", time.monotonic() - started_at)

    if cancelled is not None:
        try:
            if cancelled():
                return ScholarRecoveryServiceResult(
                    outcome=OUTCOME_CANCELLED,
                    recovery=recovery,
                    reason=(
                        "Scholar recovery was cancelled before the copied "
                        "opinion was saved."
                    ),
                    stage=SERVICE_STAGE_CLIPBOARD,
                    reason_code=REASON_CANCELLED,
                )
        except Exception:
            pass

    try:
        clipboard_text = read_regular_clipboard()
    except ScholarBrowserError as exc:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_FAILED,
            recovery=recovery,
            reason="Could not read the copied Scholar opinion: " + str(exc),
            stage=SERVICE_STAGE_CLIPBOARD,
            reason_code=REASON_COPY_FAILED,
        )

    progress_stage(progress, "Importing opinion", time.monotonic() - started_at)
    try:
        imported = import_scholar_text(
            client,
            citation=citation,
            source_url=recovery.source_url,
            clipboard_text=clipboard_text,
            case_name=case_name,
            existing_cluster=existing_cluster,
            # The copied opinion's derived citation must equal the official
            # citation discovered in the selected result's primary metadata,
            # and the citation-less identity (including the enriched docket)
            # is corroborated against the copied text before persistence.
            discovered_citation=recovery.official_citation,
            docket_number=docket_number,
        )
    except (ScholarBrowserError, ValueError) as exc:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_REJECTED,
            recovery=recovery,
            reason=_concise(str(exc)),
            stage=SERVICE_STAGE_VALIDATION,
            reason_code=REASON_VALIDATION_REJECTED,
        )
    except RuntimeError as exc:
        # Persistence-stage failure (Library/Research Cache write, network to
        # CourtListener): the copy was captured but nothing was stored. The
        # exception payload may be arbitrary, so only a controlled message is
        # reported.
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_FAILED,
            recovery=recovery,
            reason=(
                "The copied Scholar opinion could not be saved to the Library "
                "because of a storage or unexpected error."
            ),
            stage=SERVICE_STAGE_PERSISTENCE,
            reason_code=REASON_PERSISTENCE_FAILED,
        )

    authority = _re_extract_authority(client, imported)
    if authority is None:
        # The copy was saved but the post-persistence readback failed: never
        # report not-found and never trigger another search.
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_IMPORTED,
            recovery=recovery,
            imported=imported,
            authority=None,
            reason=(
                "The official copy was saved to the Library, but the saved "
                "copy could not be re-verified and refreshed by re-extraction."
            ),
            stage=SERVICE_STAGE_REEXTRACTION,
            reason_code=REASON_REEXTRACT_FAILED,
        )

    return ScholarRecoveryServiceResult(
        outcome=OUTCOME_IMPORTED,
        recovery=recovery,
        imported=imported,
        authority=authority,
        reason="",
    )


def _re_extract_authority(client: Any, imported: ScholarClipboardImport) -> Any:
    """Re-extract the imported copy from the durable Library."""
    from .authority_resolver import extract_case

    citation = imported.official_citation
    try:
        return extract_case(citation, client=client)
    except (RuntimeError, ValueError):
        return None


# Single presentation mapping for GUI and CLI-facing explanations. Titles
# distinguish blocked / rejected / failed / genuinely-not-found outcomes;
# messages are controlled and never contain opinion, clipboard, or
# accessibility-tree text.
_PRESENTATIONS: dict[str, tuple[str, str]] = {
    OUTCOME_BLOCKED: (
        "Scholar Access Blocked",
        "Google Scholar showed a verification challenge. The recovery stopped "
        "without interacting with it; the challenge is left visible in the "
        "browser window.",
    ),
    OUTCOME_REJECTED: (
        "Scholar Copy Rejected",
        "The copied Scholar page did not pass validation, so nothing was "
        "saved. The current baseline is retained.",
    ),
    OUTCOME_FAILED: (
        "Scholar Recovery Failed",
        "Default-browser Scholar recovery stopped because of a load, "
        "inspection, copy, storage, or unexpected problem. The current "
        "baseline is retained.",
    ),
    OUTCOME_NOT_FOUND: (
        "No Matching Scholar Copy Found",
        "The bounded Google Scholar search found no single qualifying "
        "matching copy. This does not mean no official copy exists.",
    ),
    OUTCOME_CANCELLED: (
        "Scholar Recovery Cancelled",
        "The Scholar recovery was cancelled before any copy was saved.",
    ),
    OUTCOME_BUSY: (
        "Scholar Recovery Busy",
        "Another Scholar recovery is already running.",
    ),
}
_DEFAULT_PRESENTATION = (
    "Scholar Recovery Failed",
    "Default-browser Scholar recovery stopped without an official reporter "
    "copy. The current baseline is retained.",
)


def recovery_presentation(outcome: str, reason_code: str = "") -> tuple[str, str]:
    """Return the ``(title, message)`` presentation for a service outcome.

    The single mapping shared by the GTK app modal and CLI-facing text.
    ``reason_code`` is accepted for future refinement; presentations stay
    keyed on the outcome so every code maps to a controlled message.
    """
    return _PRESENTATIONS.get(outcome, _DEFAULT_PRESENTATION)


def progress_stage(
    progress: ProgressCallback | None, stage: str, elapsed: float
) -> None:
    if progress is not None:
        try:
            progress(stage, elapsed)
        except Exception:
            pass


def _concise(message: str) -> str:
    from re import sub

    cleaned = sub(r"\s+", " ", message or "").strip()
    # Never echo opinion or clipboard text: truncate defensively and collapse.
    return cleaned[:400]


__all__ = [
    "OUTCOME_BLOCKED",
    "OUTCOME_BUSY",
    "OUTCOME_CANCELLED",
    "OUTCOME_FAILED",
    "OUTCOME_IMPORTED",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_REJECTED",
    "REASON_PERSISTENCE_FAILED",
    "REASON_REEXTRACT_FAILED",
    "REASON_VALIDATION_REJECTED",
    "ScholarRecoveryServiceResult",
    "recover_official_copy",
    "recovery_presentation",
]
