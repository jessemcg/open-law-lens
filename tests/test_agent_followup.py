from __future__ import annotations

import json
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import unittest

from open_law_lens.agent_followup import (
    MAX_TEXT_BYTES,
    FollowUpBusy,
    FollowUpClient,
    FollowUpEndpoint,
    FollowUpProtocolError,
    FollowUpUnauthorized,
    FollowUpUncertain,
    FollowUpUnavailable,
    create_followup_runtime,
    create_followup_token,
    normalize_submit_text,
    open_law_lens_followup_runtime_root,
    remove_followup_runtime,
    text_transport_error,
    validate_endpoint,
)


class _FakeBridge:
    def __init__(self, socket_path: Path, token: str, *, fail_mode: str = "") -> None:
        self.socket_path = socket_path
        self.token = token
        self.fail_mode = fail_mode
        self.requests: list[dict] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(socket_path))
        self._server.listen(16)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._handle, args=(connection,), daemon=True
            ).start()

    def _handle(self, connection: socket.socket) -> None:
        try:
            data = b""
            while b"\n" not in data:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                data += chunk
            if self.fail_mode == "oversize":
                connection.sendall(b"x" * 300_000 + b"\n")
                return
            if self.fail_mode == "malformed":
                connection.sendall(b"not json\n")
                return
            payload = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
            self.requests.append(payload)
            response = {
                "v": 1,
                "type": payload.get("type"),
                "id": payload.get("id"),
            }
            if payload.get("token") != self.token:
                response.update(ok=False, error="unauthorized", state="closed")
            elif self.fail_mode == "busy":
                response.update(ok=False, error="busy", state="busy")
            elif payload.get("type") == "status":
                response.update(ok=True, state="ready")
            else:
                response.update(ok=True, state="busy", duplicate=False)
            connection.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        finally:
            connection.close()

    def close(self) -> None:
        try:
            self._server.close()
        except OSError:
            pass


class AgentFollowupTests(unittest.TestCase):
    def setUp(self) -> None:
        # AF_UNIX paths are limited; /tmp keeps the temp prefix short.
        self._runtime_temp = Path(tempfile.mkdtemp(prefix="oll-fu-", dir="/tmp"))
        self._previous_runtime = None
        import os

        self._previous_runtime = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = str(self._runtime_temp)
        self.runtime_root = open_law_lens_followup_runtime_root()

    def tearDown(self) -> None:
        import os

        if self._previous_runtime is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._previous_runtime
        shutil.rmtree(self._runtime_temp, ignore_errors=True)

    def _endpoint(self, *, token: str | None = None) -> FollowUpEndpoint:
        directory = Path(tempfile.mkdtemp(prefix="session.", dir=self.runtime_root))
        return FollowUpEndpoint(
            socket_path=directory / "bridge.sock",
            token=token or create_followup_token(),
            generation=1,
        )

    def test_create_and_remove_runtime_is_private(self) -> None:
        runtime = create_followup_runtime(generation=3)
        self.assertEqual(runtime.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(runtime.endpoint.generation, 3)
        remove_followup_runtime(runtime.directory)
        self.assertFalse(runtime.directory.exists())

    def test_status_and_submit_round_trip(self) -> None:
        endpoint = self._endpoint()
        bridge = _FakeBridge(endpoint.socket_path, endpoint.token)
        try:
            client = FollowUpClient(endpoint)
            self.assertEqual(client.status(), "ready")
            self.assertEqual(client.submit("  live follow up  "), "busy")
            self.assertEqual(bridge.requests[-1]["text"], "live follow up")
        finally:
            bridge.close()

    def test_wrong_token_is_unauthorized(self) -> None:
        endpoint = self._endpoint()
        bridge = _FakeBridge(endpoint.socket_path, endpoint.token)
        try:
            with self.assertRaises(FollowUpUnauthorized):
                FollowUpClient(
                    FollowUpEndpoint(endpoint.socket_path, create_followup_token(), 1)
                ).status()
        finally:
            bridge.close()

    def test_busy_rejected(self) -> None:
        endpoint = self._endpoint()
        bridge = _FakeBridge(endpoint.socket_path, endpoint.token, fail_mode="busy")
        try:
            with self.assertRaises(FollowUpBusy):
                FollowUpClient(endpoint).submit("question")
        finally:
            bridge.close()

    def test_malformed_and_oversize_responses_rejected(self) -> None:
        for mode in ("malformed", "oversize"):
            endpoint = self._endpoint()
            bridge = _FakeBridge(endpoint.socket_path, endpoint.token, fail_mode=mode)
            try:
                with self.assertRaises(FollowUpProtocolError):
                    FollowUpClient(endpoint).status()
            finally:
                bridge.close()

    def test_oversized_text_rejected_before_sending(self) -> None:
        endpoint = self._endpoint()
        bridge = _FakeBridge(endpoint.socket_path, endpoint.token)
        try:
            with self.assertRaises(FollowUpProtocolError):
                FollowUpClient(endpoint).submit("x" * (MAX_TEXT_BYTES + 1))
            self.assertEqual(bridge.requests, [])
        finally:
            bridge.close()

    def test_closed_connection_before_reply_is_uncertain(self) -> None:
        endpoint = self._endpoint()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(endpoint.socket_path))
        server.listen(1)

        def _drop() -> None:
            connection, _ = server.accept()
            connection.recv(4096)
            connection.close()

        threading.Thread(target=_drop, daemon=True).start()
        try:
            with self.assertRaises(FollowUpUncertain):
                FollowUpClient(endpoint).submit("question")
        finally:
            server.close()

    def test_unavailable_when_socket_absent(self) -> None:
        with self.assertRaises(FollowUpUnavailable):
            FollowUpClient(self._endpoint()).status()

    def test_validate_and_text_helpers(self) -> None:
        self.assertEqual(validate_endpoint(None), "missing")
        self.assertEqual(normalize_submit_text("  keep  interior  "), "keep  interior")
        self.assertEqual(text_transport_error(""), "empty_text")
        self.assertEqual(text_transport_error("ok"), "")
        self.assertEqual(text_transport_error("x" * (MAX_TEXT_BYTES + 1)), "too_large")


if __name__ == "__main__":
    unittest.main()
