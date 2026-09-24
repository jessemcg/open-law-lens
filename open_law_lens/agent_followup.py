"""Bounded Unix-socket transport for live Pi Agent follow-up questions.

This module is deliberately GTK-independent. It owns the application side of
the documented follow-up protocol v1: a newline-delimited JSON request/response
exchange over a private Unix-domain socket served by the explicitly loaded Pi
bridge extension. It never queues a prompt, persists conversation content, or
opens a TCP listener.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import tempfile
from typing import Any

PROTOCOL_VERSION = 1
MAX_TEXT_BYTES = 64 * 1024
MAX_FRAME_BYTES = 128 * 1024
DEFAULT_TIMEOUT_SECONDS = 4.0

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24,128}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

FOLLOWUP_STATES = frozenset({"starting", "busy", "ready", "closed"})
FOLLOWUP_ERRORS = frozenset(
    {
        "unauthorized",
        "invalid_request",
        "bad_version",
        "too_large",
        "busy",
        "closed",
        "rejected",
        "unavailable",
    }
)


class FollowUpError(Exception):
    """Base class for follow-up transport failures."""


class FollowUpUnavailable(FollowUpError):
    """The bridge is missing, closed, or the socket cannot be reached."""


class FollowUpUnauthorized(FollowUpError):
    """The bridge rejected the session token."""


class FollowUpBusy(FollowUpError):
    """The bridge is not idle and cannot accept another request."""


class FollowUpRejected(FollowUpError):
    """The bridge refused delivery before dispatch."""


class FollowUpUncertain(FollowUpError):
    """The request was sent but no acknowledgement was observed."""


class FollowUpProtocolError(FollowUpError):
    """A malformed, oversized, or unexpected response was received."""


@dataclass(frozen=True)
class FollowUpEndpoint:
    """One captured follow-up channel bound to a live Pi session generation."""

    socket_path: Path
    token: str
    generation: int


@dataclass(frozen=True)
class FollowUpRuntime:
    """Application-owned runtime directory hosting one bridge socket."""

    directory: Path
    endpoint: FollowUpEndpoint


def create_followup_token() -> str:
    return secrets.token_urlsafe(32)


def create_followup_request_id() -> str:
    return secrets.token_urlsafe(18)


def open_law_lens_followup_runtime_root() -> Path:
    """Return Open Law Lens's private runtime root for follow-up bridge sockets."""
    configured = str(os.environ.get("XDG_RUNTIME_DIR", "") or "").strip()
    if configured:
        root = Path(configured).expanduser()
    else:
        root = Path(tempfile.gettempdir()) / f"open-law-lens-{os.getuid()}"
    path = root / "open-law-lens" / "agent-followup"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path.resolve(strict=False)


def create_followup_runtime(*, generation: int) -> FollowUpRuntime:
    """Create a unique private directory and endpoint for one Pi session."""
    root = open_law_lens_followup_runtime_root()
    directory = Path(tempfile.mkdtemp(prefix="session.", dir=root))
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    endpoint = FollowUpEndpoint(
        socket_path=directory / "bridge.sock",
        token=create_followup_token(),
        generation=generation,
    )
    return FollowUpRuntime(directory=directory, endpoint=endpoint)


def _is_owned_by_current_user(file_stat: os.stat_result) -> bool:
    return file_stat.st_uid == os.getuid()


def _has_private_mode(file_stat: os.stat_result) -> bool:
    return stat.S_IMODE(file_stat.st_mode) & 0o077 == 0


def remove_followup_runtime(directory: Path | None) -> None:
    """Remove only an application-owned private runtime directory.

    A missing directory is ignored. A path that is not a real directory under
    the follow-up root, is a symlink, is owned by another user, or does not have
    private permissions is left untouched.
    """
    if directory is None:
        return
    root = open_law_lens_followup_runtime_root()
    try:
        resolved = directory.resolve(strict=False)
    except OSError:
        return
    if resolved == root or root not in resolved.parents:
        return
    try:
        file_stat = directory.lstat()
    except OSError:
        return
    if not stat.S_ISDIR(file_stat.st_mode) or stat.S_ISLNK(file_stat.st_mode):
        return
    if not _is_owned_by_current_user(file_stat):
        return
    shutil.rmtree(directory, ignore_errors=True)


def validate_endpoint(endpoint: FollowUpEndpoint | None) -> str:
    """Return an empty string when the endpoint is safe, else a reason code."""
    if endpoint is None:
        return "missing"
    if not TOKEN_RE.fullmatch(endpoint.token or ""):
        return "invalid_token"
    socket_path = endpoint.socket_path
    if not socket_path.is_absolute():
        return "invalid_path"
    if socket_path.name != "bridge.sock":
        return "invalid_path"
    try:
        file_stat = socket_path.lstat()
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISSOCK(file_stat.st_mode):
        return "invalid_type"
    if not _is_owned_by_current_user(file_stat):
        return "foreign_owner"
    return ""


def normalize_submit_text(text: str) -> str:
    """Trim leading/trailing whitespace without altering interior content."""
    return (text or "").strip()


def text_transport_error(text: str) -> str:
    """Return an empty string when text fits the protocol limits."""
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        return "invalid_text"
    if not encoded:
        return "empty_text"
    if len(encoded) > MAX_TEXT_BYTES:
        return "too_large"
    return ""


class FollowUpClient:
    """One short-lived blocking client bound to a captured endpoint."""

    def __init__(
        self,
        endpoint: FollowUpEndpoint,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = max(0.5, float(timeout))

    @property
    def endpoint(self) -> FollowUpEndpoint:
        return self._endpoint

    @property
    def generation(self) -> int:
        return self._endpoint.generation

    def status(self) -> str:
        """Return the bridge state without submitting anything."""
        response = self._exchange("status")
        return response

    def submit(self, text: str) -> str:
        """Submit literal user text to the captured session.

        Returns the acknowledged bridge state (normally ``busy`` when the new
        turn has started). Raises typed failures otherwise; an ambiguous
        delivery raises :class:`FollowUpUncertain`.
        """
        normalized = normalize_submit_text(text)
        return self._exchange("submit", text=normalized)

    # -- wire -----------------------------------------------------------

    def _exchange(self, request_type: str, *, text: str | None = None) -> str:
        endpoint = self._endpoint
        reason = validate_endpoint(endpoint)
        if reason:
            raise FollowUpUnavailable(f"follow-up bridge is unavailable ({reason})")
        request_id = create_followup_request_id()
        request: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "type": request_type,
            "id": request_id,
            "token": endpoint.token,
        }
        if text is not None:
            text_error = text_transport_error(text)
            if text_error:
                raise FollowUpProtocolError(f"follow-up text rejected ({text_error})")
            request["text"] = text
        try:
            frame = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        except (TypeError, ValueError) as exc:  # pragma: no cover - guarded inputs
            raise FollowUpProtocolError(f"follow-up request could not be encoded: {exc}")
        if len(frame) > MAX_FRAME_BYTES:
            raise FollowUpProtocolError("follow-up request exceeds the frame limit")

        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self._timeout)
        sent = False
        try:
            try:
                connection.connect(str(endpoint.socket_path))
            except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError):
                raise FollowUpUnavailable("follow-up bridge is not listening")
            except OSError as exc:
                raise FollowUpUnavailable(f"follow-up bridge connection failed: {exc}")
            sent = True
            try:
                connection.sendall(frame)
            except OSError as exc:
                if request_type == "submit":
                    raise FollowUpUncertain(
                        "follow-up delivery could not be confirmed; inspect Session before retrying"
                    ) from exc
                raise FollowUpUnavailable(f"follow-up bridge write failed: {exc}") from exc
            raw = self._read_response(connection, sent=bool(sent))
        finally:
            try:
                connection.close()
            except OSError:
                pass
        return self._parse_response(raw, request_type)

    def _read_response(self, connection: socket.socket, *, sent: bool) -> bytes:
        chunks = bytearray()
        while True:
            try:
                chunk = connection.recv(4096)
            except socket.timeout as exc:
                if sent:
                    raise FollowUpUncertain(
                        "follow-up acknowledgement timed out; inspect Session before retrying"
                    ) from exc
                raise FollowUpUnavailable("follow-up status timed out") from exc
            except OSError as exc:
                if sent:
                    raise FollowUpUncertain(
                        "follow-up connection ended before acknowledgement"
                    ) from exc
                raise FollowUpUnavailable(f"follow-up read failed: {exc}")
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_FRAME_BYTES:
                raise FollowUpProtocolError("follow-up response exceeds the frame limit")
            if b"\n" in chunks:
                break
        newline = chunks.find(b"\n")
        if newline < 0:
            if not chunks:
                if sent:
                    raise FollowUpUncertain(
                        "follow-up connection closed before acknowledgement"
                    )
                raise FollowUpUnavailable("follow-up bridge closed without a response")
            raise FollowUpProtocolError("follow-up response was not newline terminated")
        return bytes(chunks[:newline])

    def _parse_response(self, raw: bytes, request_type: str) -> str:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FollowUpProtocolError("follow-up response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise FollowUpProtocolError("follow-up response was not an object")
        if payload.get("v") != PROTOCOL_VERSION:
            raise FollowUpProtocolError("follow-up response had an unsupported version")
        if payload.get("type") != request_type:
            raise FollowUpProtocolError("follow-up response type did not match the request")
        identifier = payload.get("id")
        if not isinstance(identifier, str) or not REQUEST_ID_RE.fullmatch(identifier):
            raise FollowUpProtocolError("follow-up response id was invalid")
        state = payload.get("state")
        if not isinstance(state, str) or state not in FOLLOWUP_STATES:
            raise FollowUpProtocolError("follow-up response state was invalid")
        if payload.get("ok") is True:
            return state
        error = payload.get("error")
        if not isinstance(error, str) or error not in FOLLOWUP_ERRORS:
            raise FollowUpProtocolError("follow-up response error was invalid")
        if error == "unauthorized":
            raise FollowUpUnauthorized("follow-up bridge rejected the session token")
        if error == "busy":
            raise FollowUpBusy("Agent is still working")
        if error in {"closed", "unavailable"}:
            raise FollowUpUnavailable(f"follow-up bridge is unavailable ({error})")
        if error in {"invalid_request", "bad_version", "too_large"}:
            raise FollowUpProtocolError(f"follow-up request was rejected ({error})")
        raise FollowUpRejected(f"follow-up delivery was rejected ({error})")


def socket_error_category(exc: BaseException) -> str:
    """Map a transport failure to a short user-facing category."""
    if isinstance(exc, FollowUpBusy):
        return "busy"
    if isinstance(exc, FollowUpUnavailable):
        return "unavailable"
    if isinstance(exc, FollowUpUnauthorized):
        return "unauthorized"
    if isinstance(exc, FollowUpUncertain):
        return "uncertain"
    if isinstance(exc, FollowUpProtocolError):
        return "protocol"
    if isinstance(exc, FollowUpRejected):
        return "rejected"
    return "error"
