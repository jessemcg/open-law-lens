from __future__ import annotations

import unittest

from open_law_lens.cli import (
    _pi_hosted,
    _sanitize_session_component,
    pi_cli_cache_isolation_path,
)


class CacheIsolationTests(unittest.TestCase):
    def test_non_pi_use_returns_none(self) -> None:
        self.assertIsNone(pi_cli_cache_isolation_path("extract-case", {}, pid=1234))

    def test_gui_commands_are_excluded_even_when_pi_hosted(self) -> None:
        env = {"PI_CODING_AGENT": "true", "PI_SESSION_ID": "abc", "XDG_RUNTIME_DIR": "/run/user/1000"}
        for command in ("app", "open", "open-selected"):
            self.assertIsNone(pi_cli_cache_isolation_path(command, env, pid=1234))

    def test_existing_cache_dir_is_honored_exactly(self) -> None:
        env = {"PI_CODING_AGENT": "true", "OPEN_LAW_LENS_CACHE_DIR": "/custom/cache"}
        self.assertIsNone(pi_cli_cache_isolation_path("extract-case", env, pid=1234))

    def test_pi_hosted_derives_private_runtime_path(self) -> None:
        env = {"PI_CODING_AGENT": "true", "PI_SESSION_ID": "01a04073-1234-5678-9abc", "XDG_RUNTIME_DIR": "/run/user/1000"}
        path = pi_cli_cache_isolation_path("extract-case", env, pid=1234)
        self.assertEqual(
            path,
            "/run/user/1000/open-law-lens/pi-cache/01a04073-1234-5678-9abc",
        )

    def test_pi_hosted_session_id_is_sanitized(self) -> None:
        env = {"PI_CODING_AGENT": "true", "PI_SESSION_ID": "bad../id;with:chars", "XDG_RUNTIME_DIR": "/run/user/1000"}
        path = pi_cli_cache_isolation_path("extract-case", env, pid=1234)
        self.assertIn("/run/user/1000/open-law-lens/pi-cache/", path)
        self.assertNotIn("..", path)
        self.assertNotIn(";", path)
        self.assertNotIn(":", path)

    def test_pid_fallback_when_session_id_missing(self) -> None:
        env = {"PI_CODING_AGENT": "true", "XDG_RUNTIME_DIR": "/run/user/1000"}
        path = pi_cli_cache_isolation_path("extract-case", env, pid=4242)
        self.assertEqual(path, "/run/user/1000/open-law-lens/pi-cache/4242")

    def test_pi_hosted_detection(self) -> None:
        self.assertTrue(_pi_hosted({"PI_CODING_AGENT": "true"}))
        self.assertTrue(_pi_hosted({"PI_CODING_AGENT": "TRUE"}))
        self.assertTrue(_pi_hosted({"PI_SESSION_ID": "abc"}))
        self.assertFalse(_pi_hosted({}))
        self.assertFalse(_pi_hosted({"PI_CODING_AGENT": "false"}))

    def test_sanitize_session_component(self) -> None:
        self.assertEqual(_sanitize_session_component("abc-123"), "abc-123")
        self.assertEqual(_sanitize_session_component("  a..b  "), "a_b")
        self.assertEqual(_sanitize_session_component("!!!"), "session")


if __name__ == "__main__":
    unittest.main()
