"""Browser launch must not keep a piped CLI alive; no real desktop is used."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens import scholar_browser as browser

URL = "https://scholar.google.com/scholar?q=11+Cal.5th+614"


class ScholarLaunchStdioTests(unittest.TestCase):
    def test_launch_detaches_streams_and_keeps_default_handler(self):
        with (
            patch.object(browser, "resolve_default_https_handler",
                         return_value=("Browser", "browser.desktop")),
            patch.object(browser.subprocess, "run") as run,
        ):
            self.assertEqual(
                browser.launch_scholar_url(URL), ("Browser", "browser.desktop")
            )
        args, kwargs = run.call_args
        self.assertEqual(
            args[0], [sys.executable, "-c", browser._BROWSER_LAUNCH_CODE, URL]
        )
        for stream in ("stdin", "stdout", "stderr"):
            self.assertEqual(kwargs[stream], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(kwargs["timeout"], browser.BROWSER_LAUNCH_TIMEOUT_SECONDS)

    def test_launch_failures_are_reported(self):
        for error in (
            OSError("cannot spawn"),
            subprocess.CalledProcessError(1, "launch"),
            subprocess.TimeoutExpired("launch", 15),
        ):
            with (
                self.subTest(error=error),
                patch.object(browser, "resolve_default_https_handler",
                             return_value=("Browser", "browser.desktop")),
                patch.object(browser.subprocess, "run", side_effect=error),
            ):
                with self.assertRaises(browser.ScholarBrowserError):
                    browser.launch_scholar_url(URL)

    def test_invalid_url_never_launches(self):
        with patch.object(browser.subprocess, "run") as run:
            with self.assertRaises(browser.ScholarBrowserError):
                browser.launch_scholar_url("https://example.org/")
        run.assert_not_called()

    def test_piped_cli_reaches_eof_while_launched_browser_stays_alive(self):
        # A fake Gio starts a long-lived process exactly as a cold browser
        # launch does. Both stdout and stderr must reach EOF before it exits.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "gi" / "repository").mkdir(parents=True)
            (root / "gi" / "__init__.py").write_text(
                "def require_version(*args): pass\n"
            )
            (root / "gi" / "repository" / "__init__.py").write_text('''
import os, subprocess, sys
from pathlib import Path
class Gio:
    class AppInfo:
        @staticmethod
        def launch_default_for_uri(url, context):
            child = subprocess.Popen([
                sys.executable, "-c", "import time; time.sleep(30)"
            ])
            Path(os.environ["FAKE_BROWSER_PID"]).write_text(str(child.pid))
            return True
''')
            pid_file = root / "browser.pid"
            env = dict(os.environ, FAKE_BROWSER_PID=str(pid_file))
            env["PYTHONPATH"] = os.pathsep.join(
                (str(root), str(Path(__file__).resolve().parents[1]))
            )
            program = '''
from open_law_lens import scholar_browser as b
b.resolve_default_https_handler = lambda: ("Fake", "fake.desktop")
b.launch_scholar_url(%r)
print('{"ok": true}')
''' % URL
            try:
                result = subprocess.run(
                    [sys.executable, "-c", program], env=env,
                    capture_output=True, text=True, timeout=5, check=True,
                )
                self.assertEqual(json.loads(result.stdout), {"ok": True})
                self.assertEqual(result.stderr, "")
                os.kill(int(pid_file.read_text()), 0)  # browser still alive
            finally:
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGTERM)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
