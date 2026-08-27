from __future__ import annotations

import unittest
from pathlib import Path

from open_law_lens.browser_recovery import (
    ENV_REQUEST_QUERY,
    ENV_RESULT_PATH,
    RECOVERY_USER_MESSAGE,
    ScholarRecoveryRequest,
    is_scholar_case_url,
    recovery_environment,
    recovery_pi_command,
    request_from_query,
    validate_recovery_result,
)


class BrowserRecoveryResultTests(unittest.TestCase):
    def test_copied_requires_scholar_case_url(self) -> None:
        outcome = validate_recovery_result(
            {
                "version": 1,
                "outcome": "copied",
                "query": "11 Cal.5th 614",
                "source_url": "https://scholar.google.com/scholar_case?case=1",
                "message": "found",
            }
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.outcome, "copied")
        self.assertEqual(outcome.source_url, "https://scholar.google.com/scholar_case?case=1")

    def test_copied_rejects_non_scholar_url(self) -> None:
        self.assertIsNone(
            validate_recovery_result(
                {
                    "version": 1,
                    "outcome": "copied",
                    "query": "q",
                    "source_url": "https://example.com/x",
                    "message": "m",
                }
            )
        )

    def test_non_copied_ignores_source_url(self) -> None:
        outcome = validate_recovery_result(
            {"version": 1, "outcome": "blocked", "query": "q", "source_url": "junk", "message": "captcha"}
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.outcome, "blocked")
        self.assertEqual(outcome.source_url, "")

    def test_rejects_invalid_version_or_outcome(self) -> None:
        self.assertIsNone(validate_recovery_result({"version": 2, "outcome": "copied", "query": "q", "source_url": "https://scholar.google.com/scholar_case?case=1", "message": "m"}))
        self.assertIsNone(validate_recovery_result({"version": 1, "outcome": "bogus", "query": "q", "message": "m"}))

    def test_is_scholar_case_url(self) -> None:
        self.assertTrue(is_scholar_case_url("https://scholar.google.com/scholar_case?case=1"))
        self.assertTrue(is_scholar_case_url("https://www.scholar.google.com/scholar_case?case=2"))
        self.assertFalse(is_scholar_case_url("https://scholar.google.com/scholar?q=x"))
        self.assertFalse(is_scholar_case_url("http://scholar.google.com/scholar_case?case=1"))
        self.assertFalse(is_scholar_case_url("https://example.com/scholar_case?case=1"))


class BrowserRecoveryRequestTests(unittest.TestCase):
    def test_request_from_query_normalizes(self) -> None:
        request = request_from_query("  11  Cal.5th 614 ", cluster_id="42", case_name="In re C.L.")
        self.assertEqual(request.query, "11 Cal.5th 614")
        self.assertEqual(request.cluster_id, "42")
        self.assertEqual(request.case_name, "In re C.L.")

    def test_command_loads_bridge_and_job_extensions(self) -> None:
        project_dir = Path("/src/open-law-lens")
        prompt_path = Path("/tmp/recovery-prompt.txt")
        command = recovery_pi_command(
            project_dir=project_dir,
            prompt_path=prompt_path,
            profile=None,
        )
        joined = " ".join(command)
        self.assertIn("--print", command)
        self.assertIn("--no-session", command)
        self.assertIn("--no-extensions", command)
        self.assertIn("open_law_lens_launch_scholar_query", joined)
        self.assertIn("open_law_lens_complete_scholar_recovery", joined)
        self.assertIn("open_law_lens_authorize_scholar_window", joined)
        self.assertIn("open-law-lens-browser-recovery/index.ts", joined)
        self.assertIn("open-law-lens-scholar-recovery/index.ts", joined)
        self.assertIn("--system-prompt", command)
        self.assertEqual(command[-1], RECOVERY_USER_MESSAGE)
        # No bash or filesystem tools may be exposed.
        self.assertNotIn("bash,", joined)

    def test_environment_binds_request_and_project(self) -> None:
        request = ScholarRecoveryRequest(query="11 Cal.5th 614", expected_citation="11 Cal.5th 614")
        env = recovery_environment(
            runtime_dir=Path("/tmp/recovery-run"),
            request=request,
            project_dir=Path("/src/open-law-lens"),
            base={},
        )
        self.assertEqual(env[ENV_REQUEST_QUERY], "11 Cal.5th 614")
        self.assertEqual(env[ENV_RESULT_PATH], "/tmp/recovery-run/result.json")
        self.assertEqual(env["OPEN_LAW_LENS_PROJECT_DIR"], "/src/open-law-lens")
        self.assertTrue(env["OPEN_LAW_LENS_UV_BIN"])


if __name__ == "__main__":
    unittest.main()
