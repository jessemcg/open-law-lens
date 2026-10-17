"""Runtime receipts use only synthetic environments; no provisioning occurs here."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/standalone-runtime.py"
spec = importlib.util.spec_from_file_location("standalone_runtime", SCRIPT)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class StandaloneRuntimeTests(unittest.TestCase):
    def invoke(self, environment: Path, *args: str) -> int:
        with patch.object(sys, "prefix", str(environment)), patch.object(sys, "argv", [str(SCRIPT), *args]):
            previous_umask = os.umask(0o077)
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    return runtime.main()
            finally:
                os.umask(previous_umask)

    def environment(self, root: Path) -> Path:
        environment = root / "environment with spaces"
        (environment / "bin").mkdir(parents=True)
        cli = environment / "bin/open-law-lens"
        cli.write_text("#!/bin/sh\nexit 0\n")
        cli.chmod(0o700)
        return environment

    def test_record_check_and_stale_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = self.environment(Path(temporary))
            receipt = environment / ".open-law-lens-runtime.json"
            self.assertEqual(self.invoke(environment, "--check"), 1)
            self.assertEqual(self.invoke(environment, "--record"), 0)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.invoke(environment, "--check"), 0)
            value = json.loads(receipt.read_text())
            value["dependency_sha256"] = "stale"
            receipt.write_text(json.dumps(value))
            self.assertEqual(self.invoke(environment, "--check"), 1)
            self.assertEqual(self.invoke(environment, "--unexpected"), 1)

    def test_record_replaces_symlink_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self.environment(root)
            target = root / "unrelated.txt"
            target.write_text("preserve")
            receipt = environment / ".open-law-lens-runtime.json"
            receipt.symlink_to(target)
            self.assertEqual(self.invoke(environment, "--record"), 0)
            self.assertFalse(receipt.is_symlink())
            self.assertEqual(target.read_text(), "preserve")
            self.assertEqual(list(environment.glob("*.tmp")), [])

    def test_missing_resources_or_native_apis_reject_record_and_check(self):
        from gi.repository import Gtk
        from open_law_lens import diagnostics
        with tempfile.TemporaryDirectory() as temporary:
            environment = self.environment(Path(temporary))
            self.assertEqual(self.invoke(environment, "--record"), 0)
            receipt = environment / ".open-law-lens-runtime.json"
            original = receipt.read_bytes()
            with patch.object(diagnostics, "RESOURCES", ("missing-synthetic-resource",)):
                self.assertEqual(self.invoke(environment, "--record"), 1)
                self.assertEqual(self.invoke(environment, "--check"), 1)
            native_hasattr = hasattr
            with patch("builtins.hasattr", side_effect=lambda obj, name: False
                       if obj is Gtk and name == "FileDialog" else native_hasattr(obj, name)):
                self.assertEqual(self.invoke(environment, "--record"), 1)
                self.assertEqual(self.invoke(environment, "--check"), 1)
            self.assertEqual(receipt.read_bytes(), original)

    def test_incomplete_environment_or_wrong_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = self.environment(Path(temporary))
            (environment / "bin/open-law-lens").chmod(0o600)
            self.assertEqual(self.invoke(environment, "--record"), 1)
            (environment / "bin/open-law-lens").chmod(0o700)
            import open_law_lens
            with patch.object(open_law_lens, "__file__", str(environment / "unrelated/__init__.py")):
                self.assertEqual(self.invoke(environment, "--record"), 1)
            with patch.object(sys, "base_prefix", str(environment)):
                self.assertEqual(self.invoke(environment, "--record"), 1)
            self.assertFalse((environment / ".open-law-lens-runtime.json").exists())


if __name__ == "__main__":
    unittest.main()
