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
    OUTCOME_FAILED,
    OUTCOME_IMPORTED,
    OUTCOME_NOT_FOUND,
    OUTCOME_REJECTED,
    ScholarRecoveryServiceResult,
    recover_official_copy,
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
            self.assertEqual(recover_official_copy(client, query="q").outcome, OUTCOME_FAILED)
        with mock.patch(
            "open_law_lens.scholar_recovery_service.run_scholar_recovery",
            return_value=ScholarRecoveryOutcome(1, "busy", "q", "", "busy elsewhere"),
        ):
            self.assertEqual(recover_official_copy(client, query="q").outcome, OUTCOME_BUSY)

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
            side_effect=RuntimeError(long_secret),
        ):
            result = recover_official_copy(
                client, query="11 Cal.5th 614", citation="11 Cal.5th 614"
            )
        self.assertEqual(result.outcome, OUTCOME_REJECTED)
        self.assertLessEqual(len(result.reason), 400)

    def test_result_json_omits_clipboard_text(self) -> None:
        result = ScholarRecoveryServiceResult(
            outcome=OUTCOME_IMPORTED,
            recovery=copied_outcome(),
            imported=imported_result(),
        )
        payload = result.to_json()
        self.assertNotIn("TOPSECRET", str(payload))
        self.assertNotIn("clipboard", str(payload))


if __name__ == "__main__":
    unittest.main()
