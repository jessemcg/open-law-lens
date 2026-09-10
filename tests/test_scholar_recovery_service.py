"""Tests for the shared Scholar recovery-and-import service.

These tests mock the deterministic state machine and the persistence primitives
so no real desktop, clipboard, or Scholar request is involved.
"""

from __future__ import annotations

import unittest
from unittest import mock
from typing import Any

from open_law_lens.scholar_recovery_service import (
    OUTCOME_BLOCKED,
    OUTCOME_BUSY,
    OUTCOME_CANCELLED,
    OUTCOME_FAILED,
    OUTCOME_IMPORTED,
    OUTCOME_NOT_FOUND,
    OUTCOME_REJECTED,
    ScholarRecoveryServiceResult,
    recover_official_copy,
    recovery_presentation,
)
from open_law_lens.browser_recovery import ScholarRecoveryOutcome
from open_law_lens.scholar_browser import ScholarClipboardImport, ScholarBrowserError


def copied_outcome(source_url: str = "https://scholar.google.com/scholar_case?case=1") -> ScholarRecoveryOutcome:
    return ScholarRecoveryOutcome(1, "copied", "11 Cal.5th 614", source_url, "Copied.")


def imported_result() -> ScholarClipboardImport:
    return ScholarClipboardImport(
        case_name="In re Caden C.",
        official_citation="11 Cal.5th 614",
        cluster_id="1",
        opinion_id="official-import-1-abcd",
        marker_count=19,
        eligible=True,
    )


class ServiceTests(unittest.TestCase):
    def _client(self) -> Any:
        return mock.Mock()

    def test_success_imports_and_reports_imported(self) -> None:
        client = self._client()
        progress = mock.Mock()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            return_value=imported_result(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service._re_extract_authority",
            return_value={"text": "imported text"},
        ):
            result = recover_official_copy(
                client,
                query="11 Cal.5th 614",
                citation="11 Cal.5th 614",
                case_name="In re Caden C.",
                progress=progress,
            )
        self.assertEqual(result.outcome, OUTCOME_IMPORTED)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.imported)
        self.assertEqual(result.imported.marker_count, 19)
        # Progress reported Validating copy and Importing opinion.
        stages = [call.args[0] for call in progress.call_args_list]
        self.assertIn("Validating copy", stages)
        self.assertIn("Importing opinion", stages)

    def test_not_found_preserves_baseline(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "q", "", "no match"),
        ):
            result = recover_official_copy(client, query="q", citation="q")
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        self.assertFalse(result.ok)
        self.assertIsNone(result.imported)

    def test_blocked_stops_without_import(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "blocked", "q", "", "captcha"),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text"
        ) as importer:
            result = recover_official_copy(client, query="q", citation="q")
        self.assertEqual(result.outcome, OUTCOME_BLOCKED)
        importer.assert_not_called()

    def test_failed_and_busy_outcomes(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "failed", "q", "", "boom"),
        ):
            self.assertEqual(
                recover_official_copy(client, query="q", citation="q").outcome,
                OUTCOME_FAILED,
            )
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "busy", "q", "", "busy elsewhere"),
        ):
            self.assertEqual(
                recover_official_copy(client, query="q", citation="q").outcome,
                OUTCOME_BUSY,
            )

    def test_citationless_without_identity_is_not_found_before_browser(self) -> None:
        """No case name or no docket/year discriminator fails closed before the
        recovery state machine, lock, or browser is ever involved."""
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery"
        ) as run_recovery:
            result = recover_official_copy(client, query="free-form query text")
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        self.assertFalse(result.ok)
        self.assertIsNone(result.imported)
        self.assertIn("docket number or filing year", result.reason)
        run_recovery.assert_not_called()

    def test_citationless_missing_discriminator_is_not_found_before_browser(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery"
        ) as run_recovery:
            result = recover_official_copy(
                client,
                query="anything",
                citation="",
                case_name="In re S.H.",
                existing_cluster={"id": "7856391", "case_name": "In re S.H."},
            )
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        run_recovery.assert_not_called()

    def test_validation_rejection_preserves_baseline(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            side_effect=ScholarBrowserError("Clipboard text has no qualifying official reporter pagination."),
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertFalse(result.ok)
        self.assertIsNone(result.imported)

    def test_no_opinion_text_in_reason(self) -> None:
        client = self._client()
        long_secret = "TOPSECRET OPINION BODY " * 200
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value=long_secret,
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            side_effect=ScholarBrowserError("Clipboard content was empty after cleanup."),
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertLessEqual(len(result.reason), 400)
        self.assertNotIn("TOPSECRET", result.reason)

    def test_validation_rejection_carries_stage_and_reason_code(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            side_effect=ScholarBrowserError("Clipboard case name does not match the requested case."),
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertEqual(result.reason_code, "validation_rejected")
        self.assertEqual(result.stage, "validation")
        self.assertIn("validation_rejected", result.to_json()["reason_code"])

    def test_persistence_failure_is_failed_not_rejected(self) -> None:
        client = self._client()
        long_secret = "TOPSECRET OPINION BODY " * 200
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value=long_secret,
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            side_effect=RuntimeError("library write failed"),
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_FAILED)
        self.assertEqual(result.reason_code, "persistence_failed")
        self.assertEqual(result.stage, "persistence")
        self.assertIn("could not be saved to the Library", result.reason)
        self.assertNotIn("TOPSECRET", result.reason)

    def test_clipboard_read_failure_reports_copy_failed(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            side_effect=ScholarBrowserError("No text was available from the regular clipboard."),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text"
        ) as importer:
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_FAILED)
        self.assertEqual(result.reason_code, "copy_failed")
        self.assertEqual(result.stage, "clipboard")
        importer.assert_not_called()

    def test_cancelled_before_persistence_never_imports(self) -> None:
        client = self._client()
        cancelled = mock.Mock(return_value=True)
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text"
        ) as importer:
            result = recover_official_copy(
                client,
                query="11 Cal.5th 614",
                citation="11 Cal.5th 614",
                cancelled=cancelled,
            )
        self.assertEqual(result.outcome, OUTCOME_CANCELLED)
        self.assertEqual(result.reason_code, "cancelled")
        importer.assert_not_called()

    def test_cancelled_recovery_outcome_maps_to_cancelled(self) -> None:
        client = self._client()
        recovery = ScholarRecoveryOutcome(
            1, "failed", "q", "", "Scholar recovery was cancelled.",
            stage="search", reason_code="cancelled",
        )
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=recovery,
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text"
        ) as importer:
            result = recover_official_copy(client, query="q", citation="q")
        self.assertEqual(result.outcome, OUTCOME_CANCELLED)
        self.assertEqual(result.reason_code, "cancelled")
        self.assertEqual(result.stage, "search")
        importer.assert_not_called()

    def test_busy_from_reason_code_maps_to_busy(self) -> None:
        client = self._client()
        recovery = ScholarRecoveryOutcome(
            1, "failed", "q", "", "Another Scholar recovery is already running.",
            stage="", reason_code="busy",
        )
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=recovery,
        ):
            result = recover_official_copy(client, query="q", citation="q")
        self.assertEqual(result.outcome, OUTCOME_BUSY)
        self.assertEqual(result.reason_code, "busy")

    def test_lock_held_across_recovery_and_persistence(self) -> None:
        """The service holds one lock through the browser job and persistence.

        The browser job must reuse the service's lock (never double-acquire),
        and the lock must still be held when the clipboard is read so another
        recovery cannot replace the clipboard between copy and read.
        """
        client = self._client()
        seen_locks: list[object] = []
        lock_during_recovery: list[object] = []

        class _TrackingLock:
            def acquire(self) -> bool:
                seen_locks.append("acquire")
                return True

            def release(self) -> None:
                seen_locks.append("release")

        def _fake_run(request, *, lock=None, **kwargs):
            lock_during_recovery.append(lock)
            return copied_outcome()

        real_lock = (
            "open_law_lens.scholar_recovery_service.RecoveryLock"
        )
        with mock.patch(
            real_lock, return_value=_TrackingLock()
        ) as lock_factory, mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            side_effect=_fake_run,
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            return_value=imported_result(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service._re_extract_authority",
            return_value={"text": "imported"},
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertTrue(result.ok)
        lock_factory.assert_called_once_with()
        self.assertEqual(seen_locks, ["acquire", "release"])
        # The job reused the service's already-held lock.
        self.assertEqual(len(lock_during_recovery), 1)
        self.assertIs(lock_during_recovery[0], lock_factory.return_value)

    def test_service_reports_busy_when_lock_is_contented(self) -> None:
        client = self._client()

        class _ContendedLock:
            def acquire(self) -> bool:
                return False

            def release(self) -> None:
                pass

        with mock.patch(
            "open_law_lens.scholar_recovery_service.RecoveryLock",
            return_value=_ContendedLock(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery"
        ) as run_recovery:
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_BUSY)
        self.assertEqual(result.reason_code, "busy")
        run_recovery.assert_not_called()

    def test_failed_readback_reports_saved_but_unverified(self) -> None:
        client = self._client()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=copied_outcome(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="fake opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            return_value=imported_result(),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service._re_extract_authority",
            return_value=None,
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        # Saved-but-unverified is never not-found and never re-searched.
        self.assertEqual(result.outcome, OUTCOME_IMPORTED)
        self.assertTrue(result.ok)
        self.assertEqual(result.reason_code, "reextract_failed")
        self.assertEqual(result.stage, "reextraction")
        self.assertIn("saved to the Library", result.reason)
        self.assertIn("could not be re-verified", result.reason)

    def test_blocked_carries_challenge_reason_code(self) -> None:
        client = self._client()
        recovery = ScholarRecoveryOutcome(
            1, "blocked", "q", "",
            "Google Scholar showed a CAPTCHA challenge; leaving it visible.",
            stage="search", reason_code="challenge_captcha",
        )
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=recovery,
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text"
        ) as importer:
            result = recover_official_copy(client, query="q", citation="q")
        self.assertEqual(result.outcome, OUTCOME_BLOCKED)
        self.assertEqual(result.reason_code, "challenge_captcha")
        self.assertEqual(result.stage, "search")
        importer.assert_not_called()

    def test_presentation_mapping_distinguishes_outcomes(self) -> None:
        cases = {
            OUTCOME_BLOCKED: "Scholar Access Blocked",
            OUTCOME_REJECTED: "Scholar Copy Rejected",
            OUTCOME_FAILED: "Scholar Recovery Failed",
            OUTCOME_NOT_FOUND: "No Matching Scholar Copy Found",
            OUTCOME_CANCELLED: "Scholar Recovery Cancelled",
            OUTCOME_BUSY: "Scholar Recovery Busy",
        }
        for outcome, title in cases.items():
            presentation_title, message = recovery_presentation(outcome, "any_code")
            self.assertEqual(presentation_title, title, outcome)
            self.assertTrue(message)

    def test_result_json_omits_clipboard_text(self) -> None:
        result = ScholarRecoveryServiceResult(
            outcome=OUTCOME_IMPORTED,
            recovery=copied_outcome(),
            imported=imported_result(),
        )
        payload = result.to_json()
        self.assertNotIn("TOPSECRET", str(payload))
        self.assertNotIn("clipboard", str(payload))


class DocketEnrichmentTests(unittest.TestCase):
    """Citation-less identity enrichment from already-fetched metadata.

    Regression for In re E.C. (cluster 8509982): the cluster carries no docket
    number, but the raw opinion's ``download_url`` exposes the California
    appellate case number F084030.
    """

    EC_CLUSTER = {
        "id": "8509982",
        "case_name": "In re E.C.",
        "date_filed": "2022-11-14",
    }

    def _recover(self, client: Any, **kwargs: Any) -> Any:
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "q", "", "no match"),
        ) as run_recovery:
            result = recover_official_copy(client, citation="", **kwargs)
        return result, run_recovery

    def test_case_number_derived_from_download_url(self) -> None:
        client = mock.Mock()
        client.fetch_cluster_opinions.return_value = [
            {
                "id": "9",
                "download_url": (
                    "https://www.courts.ca.gov/opinions/documents/F084030.PDF"
                ),
            }
        ]
        result, run_recovery = self._recover(
            client, query="ignored", existing_cluster=dict(self.EC_CLUSTER)
        )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "F084030")
        self.assertEqual(request.query, '"In re E.C." F084030')
        # The filing year is retained even when the docket is preferred,
        # because Scholar result metadata often shows the year but not the
        # docket.
        self.assertEqual(request.filing_year, "2022")
        client.fetch_cluster_opinions.assert_called_once_with(
            dict(self.EC_CLUSTER),
            refresh=False,
            persist_to_library=False,
            populate_research_cache=False,
        )

    def test_explicit_docket_is_never_overridden(self) -> None:
        client = mock.Mock()
        result, run_recovery = self._recover(
            client,
            query="ignored",
            case_name="In re S.H.",
            docket_number="B299242",
            existing_cluster=dict(self.EC_CLUSTER),
        )
        client.fetch_cluster_opinions.assert_not_called()
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "B299242")
        self.assertEqual(request.query, '"In re S.H." B299242')

    def test_ambiguous_url_candidates_fall_back_to_year(self) -> None:
        client = mock.Mock()
        client.fetch_cluster_opinions.return_value = [
            {"download_url": "https://www.courts.ca.gov/opinions/documents/F084030.PDF"},
            {"download_url": "https://www.courts.ca.gov/opinions/documents/B123456.PDF"},
        ]
        result, run_recovery = self._recover(
            client, query="q", existing_cluster=dict(self.EC_CLUSTER)
        )
        request = run_recovery.call_args.args[0]
        # Ambiguous metadata candidates never beat the validated filing year.
        self.assertEqual(request.docket_number, "")
        self.assertEqual(request.query, '"In re E.C." 2022')

    def test_enrichment_failure_degrades_to_year_path(self) -> None:
        client = mock.Mock()
        client.fetch_cluster_opinions.side_effect = RuntimeError("offline")
        result, run_recovery = self._recover(
            client, query="q", existing_cluster=dict(self.EC_CLUSTER)
        )
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "")
        self.assertEqual(request.query, '"In re E.C." 2022')

    def test_ambiguous_opinion_urls_degrade_to_year(self) -> None:
        client = mock.Mock()
        client.fetch_cluster_opinions.return_value = [
            {"download_url": "https://www.courts.ca.gov/opinions/documents/F084030.PDF"},
            {"download_url": "https://www.courts.ca.gov/opinions/documents/B123456.PDF"},
        ]
        result, run_recovery = self._recover(
            client, query="q", existing_cluster=dict(self.EC_CLUSTER)
        )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "")
        self.assertEqual(request.query, '"In re E.C." 2022')

    def test_opinion_text_is_never_scanned_for_docket(self) -> None:
        # Only URL-like fields are inspected; a plain-text field carrying the
        # case number must never contribute a candidate.
        client = mock.Mock()
        client.fetch_cluster_opinions.return_value = [
            {"plain_text": "No. F084030 IN THE COURT OF APPEAL"}
        ]
        result, _ = self._recover(
            client, query="q", existing_cluster=dict(self.EC_CLUSTER)
        )
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)

    def test_discovered_official_citation_reaches_the_import(self) -> None:
        client = mock.Mock()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(
                1,
                "copied",
                '"In re E.C." F084030',
                "https://scholar.google.com/scholar_case?case=8509982",
                "Copied.",
                "85 Cal.App.5th 123",
            ),
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.read_regular_clipboard",
            return_value="opinion text",
        ), mock.patch(
            "open_law_lens.scholar_recovery_service.import_scholar_text",
            return_value=imported_result(),
        ) as importer, mock.patch(
            "open_law_lens.scholar_recovery_service._re_extract_authority",
            return_value=None,
        ):
            result = recover_official_copy(
                client,
                query="anything",
                citation="",
                case_name="In re E.C.",
                filing_year="2022",
                docket_number="F084030",
            )
        self.assertEqual(result.outcome, OUTCOME_IMPORTED)
        self.assertEqual(
            importer.call_args.kwargs["discovered_citation"], "85 Cal.App.5th 123"
        )


class CitationlessRequestTests(unittest.TestCase):
    """Citation-less identity flows through the request and fails closed."""

    def _recover(self, **kwargs: Any) -> Any:
        client = mock.Mock()
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "q", "", "no match"),
        ) as run_recovery:
            result = recover_official_copy(client, **{"query": "q", **kwargs})
        return result, run_recovery

    def test_docket_and_year_are_derived_from_existing_cluster(self) -> None:
        result, run_recovery = self._recover(
            query="anything",
            citation="",
            case_name="",
            existing_cluster={
                "id": "7856391",
                "case_name": "In re S.H.",
                "date_filed": "2022-05-31",
                "docket_number": "B299242",
            },
        )
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "B299242")
        # Docket is the preferred discriminator over the filing year.
        self.assertEqual(request.query, '"In re S.H." B299242')

    def test_identity_fields_reach_run_scholar_recovery(self) -> None:
        result, run_recovery = self._recover(
            query="ignored free-form",
            citation="",
            case_name="In re S.H.",
            docket_number="B299242",
        )
        self.assertEqual(result.outcome, OUTCOME_NOT_FOUND)
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.expected_citation, "")
        self.assertEqual(request.case_name, "In re S.H.")
        self.assertEqual(request.docket_number, "B299242")
        self.assertEqual(request.filing_year, "")

    def test_quoted_exact_name_plus_docket_query(self) -> None:
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "", "", "no match"),
        ) as run_recovery:
            recover_official_copy(
                mock.Mock(),
                query="free-form",
                citation="",
                case_name="In re S.H.",
                docket_number="B299242",
            )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.query, '"In re S.H." B299242')

    def test_quoted_exact_name_plus_year_query_when_no_docket(self) -> None:
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "", "", "no match"),
        ) as run_recovery:
            recover_official_copy(
                mock.Mock(),
                query="ignored",
                citation="",
                case_name="In re S.H.",
                existing_cluster={
                    "id": "7856391",
                    "case_name": "In re S.H.",
                    "date_filed": "2022-05-31",
                },
            )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.query, '"In re S.H." 2022')
        self.assertEqual(request.filing_year, "2022")
        self.assertEqual(request.docket_number, "")
        self.assertEqual(request.expected_citation, "")

    def test_nested_cluster_docket_is_derived(self) -> None:
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "", "", "no match"),
        ) as run_recovery:
            recover_official_copy(
                mock.Mock(),
                query="q",
                citation="",
                case_name="In re S.H.",
                existing_cluster={
                    "id": "7856391",
                    "docket": {"docket_number": "B299242"},
                },
            )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.docket_number, "B299242")
        self.assertEqual(request.query, '"In re S.H." B299242')

    def test_derived_identity_reaches_run_scholar_recovery(self) -> None:
        existing = {
            "id": "7856391",
            "case_name": "In re S.H.",
            "date_filed": "2022-05-31",
        }
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "not_found", "", "", "no match"),
        ) as run_recovery:
            recover_official_copy(
                mock.Mock(),
                query="",
                citation="",
                case_name="",
                existing_cluster=existing,
            )
        request = run_recovery.call_args.args[0]
        self.assertEqual(request.case_name, "In re S.H.")
        self.assertEqual(request.filing_year, "2022")
        self.assertNotEqual(request.expected_citation, request.query)
        self.assertEqual(request.expected_citation, "")


if __name__ == "__main__":
    unittest.main()
