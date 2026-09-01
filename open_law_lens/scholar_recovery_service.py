"""Shared deterministic Scholar recovery, copy, validation, and import service.

This module owns the full high-level flow:

    baseline identity/request
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
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from .browser_recovery import (
    DEFAULT_TIMEOUT_SECONDS,
    CancelCallback,
    ProgressCallback,
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

# Outcome values a caller can branch on.
OUTCOME_IMPORTED = "imported"
OUTCOME_REJECTED = "rejected"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_BLOCKED = "blocked"
OUTCOME_FAILED = "failed"
OUTCOME_BUSY = "busy"


@dataclass(frozen=True)
class ScholarRecoveryServiceResult:
    """The typed final result of one recovery-and-import attempt."""

    outcome: str
    recovery: ScholarRecoveryOutcome
    imported: ScholarClipboardImport | None = None
    authority: Any = None
    reason: str = ""

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
            outcome=OUTCOME_NOT_FOUND, recovery=recovery, reason=recovery.message
        )
    request = _recover_request(
        query=query,
        citation=citation,
        cluster_id=cluster_id,
        case_name=case_name,
        filing_year=filing_year,
        docket_number=docket_number,
    )
    recovery = run_scholar_recovery(
        request,
        timeout=timeout,
        progress=progress,
        cancelled=cancelled,
    )

    if recovery.outcome == "busy":
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_BUSY, recovery=recovery, reason=recovery.message
        )
    if recovery.outcome != "copied":
        outcome = {
            "not_found": OUTCOME_NOT_FOUND,
            "blocked": OUTCOME_BLOCKED,
            "failed": OUTCOME_FAILED,
        }.get(recovery.outcome, OUTCOME_FAILED)
        return ScholarRecoveryServiceResult(
            outcome=outcome, recovery=recovery, reason=recovery.message
        )

    progress_stage(progress, "Validating copy", time.monotonic() - started_at)

    try:
        clipboard_text = read_regular_clipboard()
    except ScholarBrowserError as exc:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_FAILED,
            recovery=recovery,
            reason="Could not read the copied Scholar opinion: " + str(exc),
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
        )
    except (ScholarBrowserError, ValueError, RuntimeError) as exc:
        return ScholarRecoveryServiceResult(
            outcome=OUTCOME_REJECTED,
            recovery=recovery,
            reason=_concise(str(exc)),
        )

    authority = _re_extract_authority(client, imported)

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
    "OUTCOME_FAILED",
    "OUTCOME_IMPORTED",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_REJECTED",
    "ScholarRecoveryServiceResult",
    "recover_official_copy",
]
