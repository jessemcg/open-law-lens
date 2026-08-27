"""First-party, bounded stdio MCP client for Linux Computer Use.

This module is the *only* desktop-control path used by deterministic Scholar
recovery. It speaks the MCP 2024-11-05 stdio protocol directly to the
`computer-use-linux` MCP server and intentionally does **not** import
`pi-mcp-adapter` or anything else that requires a model/provider request.

The client is deliberately narrow. It exposes exactly five tools and rejects
everything else, and it refuses every dangerous input shape so the recovery
state machine above it cannot accidentally screenshoot, click by coordinate,
type, scroll, drag, activate by broad app identity, run setup operations, or
press any key other than targeted ``Ctrl+A`` and ``Ctrl+C``.

Privacy invariants:

* No accessibility tree, clipboard content, or opinion text is ever logged.
* URLs are surfaced only as concise Scholar-identity diagnostics (host and, at
  most, the ``/scholar_case`` path prefix), never full query strings.
* stderr, response bytes, accessibility nodes, tree depth, call duration, page
  deadline, and whole-job duration are all bounded.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

MCP_PROTOCOL_VERSION = "2024-11-05"

# The only MCP tools this client may call. Names are the raw stdio server
# names (unprefixed), which are exactly the five deterministic operations the
# recovery state machine needs.
ALLOWED_TOOLS: tuple[str, ...] = (
    "doctor",
    "list_windows",
    "get_app_state",
    "perform_action",
    "press_key",
)
REQUIRED_TOOL_NAMES: tuple[str, ...] = ALLOWED_TOOLS

# Policy-denied MCP tools. These must never be invoked, and their presence in a
# tools/list result does not change the allowlist.
FORBIDDEN_TOOLS: frozenset[str] = frozenset(
    {
        "screenshot",
        "click",
        "type_text",
        "scroll",
        "drag",
        "set_value",
        "activate_window",
        "move_window",
        "resize_window",
        "setup_accessibility",
        "setup_window_targeting",
        "list_apps",
        "focused_window",
    }
)

# The only key combinations permitted through press_key, always with an exact
# numeric window_id target.
ALLOWED_KEYS: frozenset[str] = frozenset({"Ctrl+A", "Ctrl+C"})

# Bounds applied to every request. These mirror the recovered values from the
# proven deterministic procedure and prevent context flooding.
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024
DEFAULT_INITIALIZE_SECONDS = 15.0
DEFAULT_CALL_SECONDS = 30.0
DEFAULT_PAGE_DEADLINE_SECONDS = 120.0
DEFAULT_JOB_DEADLINE_SECONDS = 300.0

DEFAULT_MAX_ACCESSIBILITY_NODES = 1000
DEFAULT_MAX_TREE_DEPTH = 14

_JSONRPC_VERSION = "2.0"


class ComputerUseMCPError(RuntimeError):
    """Base error for the deterministic Computer Use MCP client."""


class ComputerUsePolicyError(ComputerUseMCPError):
    """A request was denied by the client's deterministic policy."""


class ComputerUseTimeout(ComputerUseMCPError):
    """A bounded MCP operation exceeded its deadline."""


@dataclass(frozen=True)
class ComputerUseCapabilities:
    """Summarized readiness from ``doctor``."""

    ready: bool
    blockers: tuple[str, ...]
    can_register_mcp_tools: bool = False
    can_build_accessibility_tree: bool = False
    can_query_windows: bool = False
    can_send_development_input: bool = False


def _home_path(environment: Mapping[str, str]) -> Path:
    home = str(environment.get("HOME") or "").strip()
    if home:
        return Path(home).expanduser()
    return Path.home()


def _which(name: str, environment: Mapping[str, str]) -> str | None:
    path = str(environment.get("PATH") or os.environ.get("PATH") or "")
    return shutil.which(name, path=path or None)


def _node_executable(environment: Mapping[str, str]) -> str | None:
    """Resolve a compatible Node executable for the installed wrapper.

    The ``computer-use-linux`` npm entry point is a ``#!/usr/bin/env node``
    script, so we prefer an explicit Node binary (``node`` on ``PATH``, then
    the Pi-bundled runtime) rather than relying on the child's ``env`` lookup.
    """
    discovered = _which("node", environment)
    if discovered:
        return discovered
    root = _home_path(environment) / ".local" / "share" / "pi-node"
    if root.is_dir():
        for candidate in sorted(root.glob("node-*/bin/node"), reverse=True):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _installed_wrapper_candidates(environment: Mapping[str, str]) -> list[Path]:
    bases: list[Path] = []
    agent_dir = str(environment.get("PI_CODING_AGENT_DIR") or "").strip()
    if agent_dir:
        bases.append(Path(agent_dir).expanduser())
    bases.append(_home_path(environment) / ".pi" / "agent")
    suffix = Path("npm") / "node_modules" / "@agent-sh" / "computer-use-linux" / "npm" / "bin" / "computer-use-linux.js"
    candidates: list[Path] = []
    seen: set[str] = set()
    for base in bases:
        wrapper = base / suffix
        key = str(wrapper)
        if key in seen:
            continue
        seen.add(key)
        if wrapper.is_file():
            candidates.append(wrapper)
    return candidates


def resolve_computer_use_command(
    environment: Mapping[str, str] | None = None,
) -> list[str]:
    """Resolve the argv used to launch the ``computer-use-linux`` MCP server.

    Order: validated ``OPEN_LAW_LENS_COMPUTER_USE_BIN`` override, then
    ``computer-use-linux`` on ``PATH``, then the installed
    ``@agent-sh/computer-use-linux`` wrapper under ``PI_CODING_AGENT_DIR`` or
    ``~/.pi/agent`` using a compatible Node executable when required.
    """
    env = os.environ if environment is None else environment
    override = str(env.get("OPEN_LAW_LENS_COMPUTER_USE_BIN") or "").strip()
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise ComputerUseMCPError(
                f"OPEN_LAW_LENS_COMPUTER_USE_BIN is not a file: {override}"
            )
        if not os.access(candidate, os.X_OK):
            raise ComputerUseMCPError(
                f"OPEN_LAW_LENS_COMPUTER_USE_BIN is not executable: {override}"
            )
        return [str(candidate)]

    discovered = _which("computer-use-linux", env)
    if discovered:
        return [discovered]

    for wrapper in _installed_wrapper_candidates(env):
        node = _node_executable(env)
        if node:
            return [node, str(wrapper)]
        return [str(wrapper)]

    raise ComputerUseMCPError(
        "Linux Computer Use was not found. Set OPEN_LAW_LENS_COMPUTER_USE_BIN, "
        "install `computer-use-linux` on PATH, or install "
        "@agent-sh/computer-use-linux under ~/.pi/agent."
    )


class ComputerUseMCPClient:
    """A single bounded stdio connection to the Computer Use MCP server."""

    def __init__(
        self,
        *,
        command: list[str] | None = None,
        environment: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
        initialize_timeout: float = DEFAULT_INITIALIZE_SECONDS,
        call_timeout: float = DEFAULT_CALL_SECONDS,
        page_deadline: float = DEFAULT_PAGE_DEADLINE_SECONDS,
        job_deadline: float = DEFAULT_JOB_DEADLINE_SECONDS,
        max_nodes: int = DEFAULT_MAX_ACCESSIBILITY_NODES,
        max_depth: int = DEFAULT_MAX_TREE_DEPTH,
    ) -> None:
        self.command = list(command) if command is not None else resolve_computer_use_command(environment)
        self.environment = os.environ if environment is None else environment
        self.cwd = cwd
        self.max_response_bytes = max_response_bytes
        self.max_stderr_bytes = max_stderr_bytes
        self.initialize_timeout = initialize_timeout
        self.call_timeout = call_timeout
        self.page_deadline = page_deadline
        self.job_deadline = job_deadline
        self.max_nodes = max_nodes
        self.max_depth = max_depth

        self.process: subprocess.Popen[str] | None = None
        self._response_bytes = 0
        self._stderr_bytes = 0
        self._next_id = 0
        self._lock = threading.Lock()
        self._cancelled = False
        self._closed = False
        self._stderr_reader: threading.Thread | None = None
        self._job_started_at = time.monotonic()
        self._initialized = False
        self._tools: dict[str, Any] = {}

    # -- process lifecycle --------------------------------------------------

    def start(self) -> None:
        """Launch the server, initialize, and verify the required tools exist."""
        if self.process is not None:
            raise ComputerUseMCPError("Computer Use MCP client already started.")
        env = dict(self.environment)
        # COSMIC helper resolution is handled by the wrapper; nothing else to
        # inject here beyond the inherited environment.
        try:
            self.process = subprocess.Popen(
                self.command + ["mcp"],
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            raise ComputerUseMCPError(
                f"Unable to start Linux Computer Use: {exc}"
            ) from exc
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr, daemon=True
        )
        self._stderr_reader.start()

        try:
            self._handshake()
            self._verify_tools()
        except Exception:
            self.terminate()
            raise

    def _handshake(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        assert self.process.stdin is not None
        initialize = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._allocate_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "open-law-lens", "version": "1.0"},
            },
        }
        self._write(initialize)
        result = self._read_response(initialize["id"], timeout=self.initialize_timeout)
        if result is None:
            raise ComputerUseMCPError("Computer Use did not respond to initialize.")
        self._initialized = True
        self._write(
            {
                "jsonrpc": _JSONRPC_VERSION,
                "method": "notifications/initialized",
                "params": {},
            }
        )

    def _verify_tools(self) -> None:
        tools = self._list_tools()
        names = {str(tool.get("name") or "") for tool in tools}
        missing = [name for name in REQUIRED_TOOL_NAMES if name not in names]
        if missing:
            raise ComputerUseMCPError(
                "Computer Use is missing required tools: " + ", ".join(missing)
            )
        self._tools = {str(tool["name"]): tool for tool in tools if "name" in tool}

    def _list_tools(self) -> list[dict[str, Any]]:
        request = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._allocate_id(),
            "method": "tools/list",
            "params": {},
        }
        self._write(request)
        result = self._read_response(request["id"], timeout=self.initialize_timeout)
        if result is None:
            raise ComputerUseMCPError("Computer Use did not respond to tools/list.")
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ComputerUseMCPError("Computer Use returned an invalid tools/list.")
        return list(tools)

    def _allocate_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    # -- call policy --------------------------------------------------------

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Invoke one allowed tool and return its ``structuredContent``.

        Every request is policy-checked first: unknown tools, screenshots,
        coordinates, typing, scrolling, dragging, setup operations, broad
        app-identity targeting, and any key other than ``Ctrl+A``/``Ctrl+C``
        are rejected before a byte reaches the server.
        """
        self._require_running()
        if name not in ALLOWED_TOOLS:
            raise ComputerUsePolicyError(
                f"Tool {name!r} is not in the deterministic Computer Use allowlist."
            )
        clean = self._enforce_call_policy(name, arguments)
        if self._cancelled:
            raise ComputerUseMCPError("Computer Use client was cancelled.")
        if self._remaining_job_seconds() <= 0:
            raise ComputerUseTimeout("Computer Use job deadline exceeded.")
        effective_timeout = self.call_timeout if timeout is None else timeout
        effective_timeout = min(
            effective_timeout,
            self._remaining_job_seconds(),
            self.page_deadline,
        )
        request = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": self._allocate_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": clean},
        }
        self._write(request)
        result = self._read_response(request["id"], timeout=effective_timeout)
        if result is None:
            raise ComputerUseTimeout(f"Computer Use tool {name!r} timed out.")
        is_error = result.get("isError") is True
        if is_error:
            raise ComputerUseMCPError(
                self._concise_error(result, name)
            )
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        # Fall back to the first text content block when structuredContent is
        # absent (some servers omit it); parse JSON when possible.
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            text = first.get("text") if isinstance(first, dict) else None
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return {"_raw_text": text}
                if isinstance(parsed, dict):
                    return parsed
                return {"_raw": parsed}
        return {}

    def _enforce_call_policy(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        clean = dict(arguments or {})
        if name == "get_app_state":
            return self._policy_get_app_state(clean)
        if name == "perform_action":
            return self._policy_perform_action(clean)
        if name == "press_key":
            return self._policy_press_key(clean)
        if name in {"doctor", "list_windows"}:
            return {}
        # Unreachable due to allowlist, but defensive.
        raise ComputerUsePolicyError(f"Tool {name!r} is not allowed.")

    def _policy_get_app_state(self, clean: dict[str, Any]) -> dict[str, Any]:
        # Reject screenshots unconditionally.
        if clean.get("include_screenshot"):
            raise ComputerUsePolicyError("Screenshots are not allowed during Scholar recovery.")
        # Reject broad app-identity/selection targeting; only an exact numeric
        # window_id is permitted.
        denied_identity = [
            key
            for key in (
                "app_id",
                "app_name_or_bundle_identifier",
                "pid",
                "title",
                "wm_class",
                "tty",
                "terminal_command",
                "terminal_cwd",
                "terminal_pid",
            )
            if key in clean
        ]
        if denied_identity:
            raise ComputerUsePolicyError(
                "get_app_state must target an exact window_id; broad identity keys "
                "are not allowed: " + ", ".join(denied_identity)
            )
        window_id = clean.get("window_id")
        if not isinstance(window_id, int) or window_id <= 0:
            raise ComputerUsePolicyError(
                "get_app_state requires an exact numeric window_id."
            )
        allowed = {"window_id", "max_nodes", "max_depth", "verbose"}
        for key in list(clean):
            if key not in allowed:
                raise ComputerUsePolicyError(
                    f"get_app_state argument {key!r} is not allowed."
                )
        max_nodes = clean.get("max_nodes", self.max_nodes)
        max_depth = clean.get("max_depth", self.max_depth)
        if not isinstance(max_nodes, int) or max_nodes <= 0 or max_nodes > self.max_nodes:
            raise ComputerUsePolicyError(
                f"get_app_state max_nodes must be between 1 and {self.max_nodes}."
            )
        if not isinstance(max_depth, int) or max_depth <= 0 or max_depth > self.max_depth:
            raise ComputerUsePolicyError(
                f"get_app_state max_depth must be between 1 and {self.max_depth}."
            )
        clean["window_id"] = window_id
        clean["max_nodes"] = max_nodes
        clean["max_depth"] = max_depth
        clean["include_screenshot"] = False
        return clean

    def _policy_perform_action(self, clean: dict[str, Any]) -> dict[str, Any]:
        # Only an exact semantic element_index may be acted upon; no identifier
        # or role/name/text/states selector, no explicit action override.
        if "action" in clean:
            raise ComputerUsePolicyError(
                "perform_action must use the element's default action."
            )
        denied = [
            key
            for key in ("element_identifier", "name", "role", "states", "text")
            if key in clean
        ]
        if denied:
            raise ComputerUsePolicyError(
                "perform_action accepts only element_index: " + ", ".join(denied)
            )
        element_index = clean.get("element_index")
        if not isinstance(element_index, int):
            raise ComputerUsePolicyError(
                "perform_action requires an exact numeric element_index."
            )
        return {"element_index": element_index}

    def _policy_press_key(self, clean: dict[str, Any]) -> dict[str, Any]:
        key = str(clean.get("key") or "")
        normalized = key.strip()
        if normalized not in ALLOWED_KEYS:
            raise ComputerUsePolicyError(
                f"press_key only allows {sorted(ALLOWED_KEYS)} during Scholar recovery."
            )
        denied_identity = [
            k
            for k in (
                "app_id",
                "pid",
                "title",
                "wm_class",
                "tty",
                "terminal_command",
                "terminal_cwd",
                "terminal_pid",
            )
            if k in clean
        ]
        if denied_identity:
            raise ComputerUsePolicyError(
                "press_key must target an exact window_id; broad identity keys "
                "are not allowed: " + ", ".join(denied_identity)
            )
        window_id = clean.get("window_id")
        if not isinstance(window_id, int) or window_id <= 0:
            raise ComputerUsePolicyError(
                "press_key requires an exact numeric window_id."
            )
        return {"key": normalized, "window_id": window_id}

    def _concise_error(self, result: dict[str, Any], name: str) -> str:
        message = str(result.get("message") or result.get("_meta") or "").strip()
        text = ""
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                text = first["text"].strip()
        detail = (message or text or "unknown Computer Use error")
        return f"Computer Use tool {name!r} failed: " + _truncate(detail, 300)

    # -- stdio transport ----------------------------------------------------

    def _write(self, message: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        payload = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
        try:
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise ComputerUseMCPError(
                "Unable to write to Linux Computer Use: " + str(exc)
            ) from exc

    def _read_response(self, expected_id: int, *, timeout: float) -> dict[str, Any] | None:
        assert self.process is not None and self.process.stdout is not None
        # The documented byte bound applies to each request, not cumulatively
        # across a recovery job that must observe several browser states.
        self._response_bytes = 0
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ComputerUseTimeout("Computer Use request timed out.")
            self._check_cancelled()
            try:
                ready, _w, _e = select.select(
                    [self.process.stdout], [], [], min(remaining, 0.5)
                )
            except (OSError, ValueError) as exc:
                raise ComputerUseMCPError(
                    "Computer Use output stream failed: " + str(exc)
                ) from exc
            if not ready:
                if self.process.poll() is not None:
                    return None
                continue
            line = self._read_bounded_line()
            if line is None:
                return None
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("id") == expected_id:
                if "result" in message:
                    return message["result"]
                if "error" in message:
                    error = message["error"]
                    raise ComputerUseMCPError(
                        "Computer Use JSON-RPC error: "
                        + _truncate(str(error), 300)
                    )
                return None
            # Ignore notifications and unrelated responses.

    def _read_bounded_line(self) -> str | None:
        assert self.process is not None and self.process.stdout is not None
        try:
            line = self.process.stdout.readline()
        except (OSError, ValueError):
            raise ComputerUseMCPError("Computer Use output stream closed unexpectedly.")
        if line == "":
            return None
        self._consume_response_bytes(line)
        return line

    def _consume_response_bytes(self, chunk: str) -> None:
        self._response_bytes += len(chunk.encode("utf-8", errors="replace"))
        if self._response_bytes > self.max_response_bytes:
            self.terminate()
            raise ComputerUseMCPError(
                "Computer Use output exceeded the response byte limit."
            )

    def _drain_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            while True:
                chunk = self.process.stderr.read(4096)
                if not chunk:
                    break
                self._stderr_bytes += len(chunk.encode("utf-8", errors="replace"))
                if self._stderr_bytes > self.max_stderr_bytes:
                    self.terminate()
                    break
        except (OSError, ValueError):
            pass

    def _check_cancelled(self) -> None:
        if self._cancelled:
            raise ComputerUseMCPError("Computer Use client was cancelled.")

    def _require_running(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise ComputerUseMCPError("Computer Use client is not running.")
        if self._closed:
            raise ComputerUseMCPError("Computer Use client is closed.")

    def _remaining_job_seconds(self) -> float:
        return self.job_deadline - (time.monotonic() - self._job_started_at)

    # -- facade -------------------------------------------------------------

    def doctor(self) -> dict[str, Any]:
        return self.call_tool("doctor", {})

    def list_windows(self) -> dict[str, Any]:
        return self.call_tool("list_windows", {})

    def get_app_state(
        self,
        *,
        window_id: int,
        max_nodes: int | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"window_id": window_id}
        if max_nodes is not None:
            arguments["max_nodes"] = max_nodes
        if max_depth is not None:
            arguments["max_depth"] = max_depth
        return self.call_tool("get_app_state", arguments)

    def perform_action(self, *, element_index: int) -> dict[str, Any]:
        return self.call_tool("perform_action", {"element_index": element_index})

    def press_key(self, *, key: str, window_id: int) -> dict[str, Any]:
        return self.call_tool("press_key", {"key": key, "window_id": window_id})

    # -- shutdown -----------------------------------------------------------

    def cancel(self) -> None:
        self._cancelled = True
        self.terminate()

    def close(self) -> None:
        """Shut down gracefully (EOF) and reap the child."""
        self._closed = True
        if self.process is not None and self.process.poll() is None:
            if self.process.stdin is not None and not self.process.stdin.closed:
                try:
                    self.process.stdin.close()
                except OSError:
                    pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.terminate()
                return
        self._close_process_streams(self.process)
        self.process = None
        self._set_exited()

    def terminate(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            self._close_process_streams(process)
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            try:
                process.wait(timeout=3)
            except Exception:
                pass
        self._close_process_streams(process)

    @staticmethod
    def _close_process_streams(process: subprocess.Popen[str] | None) -> None:
        if process is None:
            return
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except OSError:
                    pass

    def _set_exited(self) -> None:
        self._closed = True

    def __enter__(self) -> "ComputerUseMCPClient":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # On an exception, force-terminate; otherwise close gracefully.
        if exc_type is not None:
            self.terminate()
        else:
            self.close()


def doctor_readiness(payload: dict[str, Any]) -> ComputerUseCapabilities:
    readiness = payload.get("readiness")
    if not isinstance(readiness, dict):
        return ComputerUseCapabilities(ready=False, blockers=())
    blockers = tuple(
        str(item)
        for item in (readiness.get("blockers") or [])
    )

    def truthy(value: Any) -> bool:
        return value is True or value == "true"

    return ComputerUseCapabilities(
        ready=not blockers and truthy(readiness.get("can_register_mcp_tools")),
        blockers=blockers,
        can_register_mcp_tools=truthy(readiness.get("can_register_mcp_tools")),
        can_build_accessibility_tree=truthy(readiness.get("can_build_accessibility_tree")),
        can_query_windows=truthy(readiness.get("can_query_windows")),
        can_send_development_input=truthy(readiness.get("can_send_development_input")),
    )


def scholar_identity_diagnostic(url: str) -> str:
    """Return a concise, log-safe Scholar identity string (never query strings)."""
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    path = parsed.path or ""
    detail = path.split("/scholar_case")[0] if "/scholar_case" in path else ""
    if not parsed.hostname:
        return "(no Scholar host)"
    return "scholar.google.com" + ("/scholar_case" if "/scholar_case" in path else "/search")


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


__all__ = [
    "ALLOWED_KEYS",
    "ALLOWED_TOOLS",
    "ComputerUseCapabilities",
    "ComputerUseMCPClient",
    "ComputerUseMCPError",
    "ComputerUsePolicyError",
    "ComputerUseTimeout",
    "REQUIRED_TOOL_NAMES",
    "doctor_readiness",
    "resolve_computer_use_command",
    "scholar_identity_diagnostic",
]
