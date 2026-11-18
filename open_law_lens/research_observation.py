"""Optional, content-free Open Law Lens subprocess observations (Linux, v1).

No collector import or archive access. No context is created by this module.
"""
from __future__ import annotations

from contextvars import ContextVar
import json
import os
import re
import stat
import time
from urllib.parse import parse_qs, urlsplit

_OPERATIONS = frozenset({
    "case-search", "lookup-citation", "extract-case", "extract", "extract-slip-opinion",
    "published-citing-cases", "recover-scholar", "extract-statute", "extract-rule",
    "lookup-statute", "lookup-rule", "search-briefs", "extract-brief",
})
_SESSION = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOKEN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_CREATE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_MAX_BYTES = 8192
current: ContextVar[Invocation | None] = ContextVar("research_observation", default=None)


def elapsed(start: float) -> float:
    return round(max(0, (time.monotonic() - start) * 1000), 3)


def _private_directory(fd: int) -> bool:
    info = os.fstat(fd)
    return info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700


def _runtime(path: str) -> int:
    if not path.startswith("/") or len(path) > 4096:
        raise ValueError("invalid runtime")
    parts = path[1:].split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid runtime")
    fd = os.open("/", _DIR)
    try:
        for part in parts:
            next_fd = os.open(part, _DIR, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        if not _private_directory(fd):
            raise ValueError("unsafe runtime")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _line(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def _claim(operation: str) -> tuple[int, int] | None:
    session = os.environ.get("PI_SESSION_ID", "")
    enabled = os.environ.get("PI_RUN_METRICS_ENABLED")
    if (enabled == "0" or not _SESSION.fullmatch(session)
            or (os.environ.get("OPEN_LAW_LENS_STORAGE") == "standalone" and not enabled)):
        return None
    token = os.environ.get(f"PI_RUN_METRICS_SUBPROCESS_V1_{session}", "")
    if not _TOKEN.fullmatch(token):
        return None
    name = f"pi-run-metrics-v1-{token}"
    try:
        parent = _runtime(os.environ.get("XDG_RUNTIME_DIR", ""))
        try:
            directory = os.open(name, _DIR, dir_fd=parent)
            try:
                if not _private_directory(directory):
                    return None
                held = os.fstat(directory)
                for slot in [*(f"{i:03d}" for i in range(1, 129)), "saturated"]:
                    path = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if (path.st_dev, path.st_ino) != (held.st_dev, held.st_ino):
                        return None
                    try:
                        fd = os.open(slot, _CREATE, 0o600, dir_fd=directory)
                    except FileExistsError:
                        continue
                    try:
                        try:
                            path = os.stat(name, dir_fd=parent, follow_symlinks=False)
                            live = (path.st_dev, path.st_ino) == (held.st_dev, held.st_ino)
                        except OSError:
                            live = False
                        if not live:
                            os.unlink(slot, dir_fd=directory)
                            return None
                        info = os.fstat(fd)
                        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                            return None
                        if slot == "saturated":
                            return None
                        start = _line({"version": 1, "operation": operation})
                        if os.write(fd, start) == len(start):
                            result, fd = fd, None
                            return result, len(start)
                        return None
                    finally:
                        if fd is not None:
                            os.close(fd)
            finally:
                os.close(directory)
        finally:
            os.close(parent)
    except (OSError, ValueError, OverflowError):
        pass
    return None


def begin(operation: str) -> Invocation | None:
    if operation not in _OPERATIONS:
        return None
    claim = _claim(operation)
    return Invocation(*claim) if claim is not None else None


_ENDPOINTS = {
    ("GET", "/api/rest/v4/search/"): "search",
    ("POST", "/api/rest/v4/citation-lookup/"): "citation_lookup",
    ("GET", "/api/rest/v4/opinions-cited/"): "cited_by",
}
_RESOURCE = re.compile(r"/api/rest/v4/(clusters|opinions)/[0-9]+/?\Z")
_EXCLUSIONS = frozenset({"missing_identity", "unverified_court", "court_out_of_scope",
                         "unverified_or_unpublished_status", "delivery_limit"})
_RECOVERY = frozenset({"blocked", "rejected", "failed", "not-found", "cancelled", "busy",
                      "saved-but-unverified"})


class Invocation:
    def __init__(self, fd: int, start_bytes: int):
        self.fd = fd
        self.start_bytes = start_bytes
        self.clock = time.monotonic()
        self.capped = False
        self.requests: list[dict] = []
        self.pages: list[dict] = []
        self.sources: dict[str, int] = {}
        self.yield_data: dict = {}
        self.last_request: dict | None = None

    def source(self, key: str) -> None:
        self.sources[key] = self.sources.get(key, 0) + 1

    def request(self, url: str, method: str) -> dict | None:
        self.last_request = None
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc not in {"www.courtlistener.com", "www.courtlistener.com:443"}:
                raise ValueError
            family = _ENDPOINTS.get((method, parsed.path))
            if family is None and method == "GET":
                resource = _RESOURCE.fullmatch(parsed.path)
                if resource:
                    family = "cluster" if resource[1] == "clusters" else "opinion"
            if family is None:
                raise ValueError
        except ValueError:
            self.source("unverified_request")
            return None
        if len(self.requests) >= 40:
            self.capped = True
            return None
        self.last_request = {"family": family, "method": method, "outcome": "incomplete", "attempts": []}
        self.requests.append(self.last_request)
        return self.last_request

    def shape_error(self) -> None:
        if self.last_request is not None:
            self.last_request["outcome"] = "shape"

    def page(self, *, semantic: bool, next_url: str, received: int, delivered: int,
             exclusions: dict[str, int]) -> None:
        if len(self.pages) >= 16:
            self.capped = True
            return
        mode = "semantic" if semantic else "lexical"
        if next_url:
            # The cursor can be opaque. Do not infer its strategy from the CLI default.
            try:
                values = parse_qs(urlsplit(next_url).query, max_num_fields=64).get("semantic")
            except ValueError:
                values = None
            mode = "semantic" if values == ["true"] else "lexical" if values == ["false"] else "unknown"
            if self.last_request is None or self.last_request["family"] != "search":
                return
        self.pages.append({"mode": mode, "page": "next" if next_url else "first", "received": received,
                           "delivered": delivered, "exclusions": {k: v for k, v in exclusions.items() if k in _EXCLUSIONS}})

    def recovery(self, outcome: str) -> None:
        self.yield_data["recovery"] = outcome if outcome in _RECOVERY else "unknown"

    def finish(self, code: int | None) -> None:
        try:
            code = code if type(code) is int and 0 <= code <= 255 else None
            payload = {"version": 1, "elapsed_ms": elapsed(self.clock), "exit_code": code,
                       "capped": self.capped, "requests": self.requests, "pages": self.pages,
                       "sources": self.sources, "yield": self.yield_data}
            line = _line(payload)
            if self.start_bytes + len(line) > _MAX_BYTES:
                payload["capped"] = True
                # Keep the prefix of request/page evidence and all typed CLI yield.
                while self.start_bytes + len(line) > _MAX_BYTES and (self.requests or self.pages):
                    (self.requests if self.requests else self.pages).pop()
                    line = _line(payload)
            if self.start_bytes + len(line) <= _MAX_BYTES:
                os.write(self.fd, line)
        except (OSError, ValueError, TypeError, OverflowError):
            pass
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass


def source(key: str) -> None:
    if observation := current.get():
        observation.source(key)


def note_yield(**fields) -> None:
    if observation := current.get():
        observation.yield_data.update(fields)


def shape_error() -> None:
    if observation := current.get():
        observation.shape_error()


def attempt_result(attempt: dict, request: dict, outcome: str, status: int | None, start: float) -> None:
    attempt.update(outcome=outcome, status=status if type(status) is int and 100 <= status <= 599 else None,
                   ms=elapsed(start))
    request["outcome"] = outcome


def retry_sleep(seconds: float, attempt: dict | None, reason: str) -> None:
    if attempt is None:
        time.sleep(seconds)
        return
    attempt["retry"] = reason
    clock = time.monotonic()
    try:
        time.sleep(seconds)
    finally:
        attempt["backoff_ms"] = elapsed(clock)
