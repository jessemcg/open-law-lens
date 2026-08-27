"""Tests for the first-party, bounded Computer Use MCP client.

These tests use an in-process fake stdio MCP server (a Python subprocess) so no
real desktop, browser, or Scholar request is ever involved.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from open_law_lens.computer_use_mcp import (
    ALLOWED_KEYS,
    ALLOWED_TOOLS,
    ComputerUseMCPClient,
    ComputerUseMCPError,
    ComputerUsePolicyError,
    ComputerUseTimeout,
    doctor_readiness,
    resolve_computer_use_command,
    scholar_identity_diagnostic,
)

FAKE_SERVER = textwrap.dedent(
    """
    import json
    import sys

    TOOLS = [
        {"name": "doctor", "description": "report readiness"},
        {"name": "list_windows", "description": "list windows"},
        {"name": "focused_window", "description": "get focused window"},
        {"name": "get_app_state", "description": "get app state"},
        {"name": "perform_action", "description": "invoke action"},
        {"name": "press_key", "description": "press key"},
        {"name": "activate_window", "description": "focus exact window"},
        {"name": "screenshot", "description": "forbidden screenshot"},
        {"name": "click", "description": "forbidden click"},
        {"name": "type_text", "description": "forbidden type"},
        {"name": "scroll", "description": "forbidden scroll"},
    ]

    def respond(message_id, result):
        out = {"jsonrpc": "2.0", "id": message_id, "result": result}
        sys.stdout.write(json.dumps(out) + "\\n")
        sys.stdout.flush()

    def respond_error(message_id, message):
        out = {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32000, "message": message}}
        sys.stdout.write(json.dumps(out) + "\\n")
        sys.stdout.flush()

    def main():
        for line in sys.stdin:
            if not line.strip():
                continue
            message = json.loads(line)
            method = message.get("method")
            message_id = message.get("id")
            if method == "initialize":
                respond(message_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-computer-use", "version": "1.0"},
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                respond(message_id, {"tools": TOOLS})
            elif method == "tools/call":
                params = message.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                if name == "doctor":
                    respond(message_id, {
                        "structuredContent": {
                            "readiness": {
                                "can_register_mcp_tools": True,
                                "can_build_accessibility_tree": True,
                                "can_query_windows": True,
                                "can_send_development_input": True,
                                "blockers": [],
                            }
                        }
                    })
                elif name == "list_windows":
                    respond(message_id, {
                        "structuredContent": {
                            "windows": [
                                {"window_id": 7, "title": "Google Scholar", "focused": False}
                            ]
                        }
                    })
                elif name == "focused_window":
                    respond(message_id, {
                        "structuredContent": {
                            "focused_window": {"window_id": 7, "title": "Google Scholar"}
                        }
                    })
                elif name == "get_app_state":
                    wid = args.get("window_id")
                    include_screenshot = args.get("include_screenshot")
                    if include_screenshot:
                        respond_error(message_id, "screenshot denied")
                        continue
                    import collections
                    node = {
                        "index": 0,
                        "role": "application",
                        "name": "Firefox",
                        "text": {"content": "scholar.google.com/scholar_case"},
                        "states": ["showing", "visible"],
                        "parent_index": None,
                        "depth": 0,
                    }
                    respond(message_id, {
                        "structuredContent": {
                            "accessibility_tree": [node],
                            "window_context": {"title": "Google Scholar"},
                        }
                    })
                elif name == "perform_action":
                    respond(message_id, {
                        "structuredContent": {"ok": True, "element_index": args.get("element_index")}
                    })
                elif name == "press_key":
                    respond(message_id, {
                        "structuredContent": {"ok": True, "key": args.get("key"), "window_id": args.get("window_id")}
                    })
                elif name == "activate_window":
                    respond(message_id, {
                        "structuredContent": {"ok": True, "window_id": args.get("window_id")}
                    })
                elif name == "screenshot":
                    respond_error(message_id, "screenshot attempted")
                else:
                    respond_error(message_id, "unknown tool " + str(name))

    main()
    """
)


def _write_fake_server(path: Path, mode: str = "normal") -> str:
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return str(path)


class ComputerUseMCPClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            __import__("tempfile").mkdtemp(prefix="computer-use-mcp-test-")
        )
        self.server_py = self.tmpdir / "fake_server.py"
        _write_fake_server(self.server_py)
        self.commands: list[str] = [
            sys.executable,
            str(self.server_py),
        ]

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def make_client(self, **overrides: Any) -> ComputerUseMCPClient:
        kwargs: dict[str, Any] = {
            "command": self.commands,
            "cwd": self.tmpdir,
            "initialize_timeout": 10,
            "call_timeout": 10,
            "job_deadline": 30,
        }
        kwargs.update(overrides)
        return ComputerUseMCPClient(**kwargs)

    def test_start_initializes_and_verifies_tools(self) -> None:
        client = self.make_client()
        client.start()
        try:
            self.assertTrue(client._initialized)
            self.assertIn("doctor", client._tools)
            self.assertIn("screenshot", client._tools)
        finally:
            client.close()

    def test_doctor_and_list_windows_and_get_app_state(self) -> None:
        client = self.make_client()
        client.start()
        try:
            doctor = client.doctor()
            capabilities = doctor_readiness(doctor)
            self.assertTrue(capabilities.ready)
            self.assertEqual(capabilities.blockers, ())

            windows = client.list_windows()
            self.assertEqual(windows["windows"][0]["window_id"], 7)

            state = client.get_app_state(window_id=7, max_nodes=1000, max_depth=14)
            tree = state["accessibility_tree"]
            self.assertEqual(tree[0]["role"], "application")
        finally:
            client.close()

    def test_response_byte_limit_resets_for_each_request(self) -> None:
        client = self.make_client(max_response_bytes=4096)
        client.start()
        try:
            client._response_bytes = client.max_response_bytes - 1
            self.assertTrue(doctor_readiness(client.doctor()).ready)
            self.assertLess(client._response_bytes, client.max_response_bytes)
        finally:
            client.close()

    def test_focused_window_and_exact_activation(self) -> None:
        client = self.make_client()
        client.start()
        try:
            focused = client.focused_window()
            self.assertEqual(focused["focused_window"]["window_id"], 7)
            activated = client.activate_window(window_id=7)
            self.assertTrue(activated["ok"])
            self.assertEqual(activated["window_id"], 7)
        finally:
            client.close()

    def test_perform_action_and_press_key(self) -> None:
        client = self.make_client()
        client.start()
        try:
            acted = client.perform_action(element_index=3)
            self.assertEqual(acted["element_index"], 3)
            pressed = client.press_key(key="Ctrl+A", window_id=7)
            self.assertEqual(pressed["key"], "Ctrl+A")
            self.assertEqual(pressed["window_id"], 7)
        finally:
            client.close()

    def test_rejects_screenshot_tool(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("screenshot", {})
        finally:
            client.close()

    def test_rejects_unapproved_key(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.press_key(key="Ctrl+V", window_id=7)
            with self.assertRaises(ComputerUsePolicyError):
                client.press_key(key="Enter", window_id=7)
        finally:
            client.close()

    def test_rejects_screenshot_argument_in_get_app_state(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool(
                    "get_app_state",
                    {"window_id": 7, "include_screenshot": True},
                )
        finally:
            client.close()

    def test_rejects_broad_identity_targeting(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("get_app_state", {"app_id": "org.mozilla.firefox"})
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("press_key", {"key": "Ctrl+A", "title": "Firefox"})
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("activate_window", {"app_id": "com.mcglaw.OpenLawLens"})
        finally:
            client.close()

    def test_rejects_perform_action_selectors(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("perform_action", {"name": "click me"})
            with self.assertRaises(ComputerUsePolicyError):
                client.call_tool("perform_action", {"action": "activate"})
        finally:
            client.close()

    def test_requires_numeric_window_id(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.get_app_state(window_id=0)
            with self.assertRaises(ComputerUsePolicyError):
                client.press_key(key="Ctrl+C", window_id=-1)
            with self.assertRaises(ComputerUsePolicyError):
                client.activate_window(window_id=0)
        finally:
            client.close()

    def test_max_nodes_and_depth_bounded(self) -> None:
        client = self.make_client()
        client.start()
        try:
            with self.assertRaises(ComputerUsePolicyError):
                client.get_app_state(window_id=7, max_nodes=5000)
            with self.assertRaises(ComputerUsePolicyError):
                client.get_app_state(window_id=7, max_depth=200)
        finally:
            client.close()

    def test_cancel_and_reap(self) -> None:
        client = self.make_client()
        client.start()
        try:
            client.cancel()
            self.assertEqual(client.process, None)
        finally:
            pass

    def test_context_manager_cleanup(self) -> None:
        with self.make_client() as client:
            self.assertIsNotNone(client.process)
            client.doctor()
        self.assertIsNone(client.process)


class ComputerUseResolutionTests(unittest.TestCase):
    def test_override_must_be_a_file(self) -> None:
        env = {"OPEN_LAW_LENS_COMPUTER_USE_BIN": "/nonexistent/computer-use-linux"}
        with self.assertRaises(ComputerUseMCPError):
            resolve_computer_use_command(env)

    def test_override_valid_file(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix="", delete=False) as handle:
            path = handle.name
            os.chmod(path, 0o755)
        try:
            env = {"OPEN_LAW_LENS_COMPUTER_USE_BIN": path}
            self.assertEqual(resolve_computer_use_command(env), [path])
        finally:
            os.unlink(path)

    def test_path_resolution_prefers_path(self) -> None:
        env: dict[str, str] = {}
        # PATH wins when a computer-use-linux binary is present; manufacture one.
        import tempfile

        bindir = tempfile.mkdtemp(prefix="cu-path-")
        fake_bin = Path(bindir) / "computer-use-linux"
        fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")
        fake_bin.chmod(0o755)
        env["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        try:
            resolved = resolve_computer_use_command(env)
            self.assertEqual(resolved, [str(fake_bin)])
        finally:
            import shutil

            shutil.rmtree(bindir, ignore_errors=True)

    def test_missing_without_override_path_or_wrapper(self) -> None:
        env = {
            "PATH": "/nonexistent",
            "PI_CODING_AGENT_DIR": "/nonexistent/agent",
            "HOME": "/nonexistent/home",
        }
        with self.assertRaises(ComputerUseMCPError):
            resolve_computer_use_command(env)


class ScholarIdentityDiagnosticTests(unittest.TestCase):
    def test_strips_query_strings(self) -> None:
        diag = scholar_identity_diagnostic(
            "https://scholar.google.com/scholar_case?case=123&q=secret"
        )
        self.assertEqual(diag, "scholar.google.com/scholar_case")

    def test_search_path(self) -> None:
        diag = scholar_identity_diagnostic("https://scholar.google.com/scholar?q=x")
        self.assertEqual(diag, "scholar.google.com/search")

    def test_empty(self) -> None:
        self.assertEqual(
            scholar_identity_diagnostic(""), "(no Scholar host)"
        )


class DoctorReadinessTests(unittest.TestCase):
    def test_ready_payload(self) -> None:
        caps = doctor_readiness(
            {
                "readiness": {
                    "can_register_mcp_tools": True,
                    "can_build_accessibility_tree": True,
                    "can_query_windows": True,
                    "can_send_development_input": True,
                    "blockers": [],
                }
            }
        )
        self.assertTrue(caps.ready)
        self.assertEqual(caps.blockers, ())

    def test_blocker(self) -> None:
        caps = doctor_readiness(
            {
                "readiness": {
                    "can_register_mcp_tools": True,
                    "blockers": ["missing accessibility"],
                }
            }
        )
        self.assertFalse(caps.ready)
        self.assertEqual(caps.blockers, ("missing accessibility",))


class AllowedSurfaceTests(unittest.TestCase):
    def test_allowed_tools_are_the_seven(self) -> None:
        self.assertEqual(
            set(ALLOWED_TOOLS),
            {
                "doctor",
                "list_windows",
                "focused_window",
                "get_app_state",
                "perform_action",
                "press_key",
                "activate_window",
            },
        )

    def test_allowed_keys_are_only_ctrl_a_and_ctrl_c(self) -> None:
        self.assertEqual(ALLOWED_KEYS, frozenset({"Ctrl+A", "Ctrl+C"}))


if __name__ == "__main__":
    unittest.main()
