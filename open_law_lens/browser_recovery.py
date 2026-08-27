"""Deterministic default-browser Google Scholar recovery state machine.

This module owns the *only* desktop-recovery path for officially paginated
Scholar copies. It replaces the former model-driven Pi subprocess with a
deterministic state machine that drives Linux Computer Use directly through the
first-party ``ComputerUseMCPClient``. No Pi, model, provider, or
``pi-mcp-adapter`` import exists here.

The job is deliberately small and side-effect constrained:

* It acquires a nonblocking user-session lock so only one recovery runs across
  every Open Law Lens and Current Case TUI process.
* It checks desktop readiness, snapshots existing windows, opens Scholar with
  the current default HTTPS handler, scopes the exact target frame and tab, and
  matches exactly one corroborated result.
* It only ever performs a targeted ``perform_action`` (semantic element index)
  and targeted ``Ctrl+A`` / ``Ctrl+C`` key presses with an exact numeric
  ``window_id``, revalidating window/frame/title/URL around every mutation.
* Barriers (CAPTCHA, robot check, unusual traffic, login, consent) stop the job
  immediately with ``blocked`` and no interaction.
* No accessibility tree, clipboard content, opinion text, or full URL is ever
  logged.
"""

from __future__ import annotations

import fcntl
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .computer_use_mcp import (
    ComputerUseMCPClient,
    ComputerUseMCPError,
    doctor_readiness,
)
from .scholar_browser import (
    SCHOLAR_NETLOC,
    build_scholar_case_search_url,
    launch_scholar_url,
    validate_scholar_source_url,
)

RESULT_VERSION = 1
VALID_OUTCOMES = ("copied", "not_found", "blocked", "failed")

DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_PAGE_DEADLINE_SECONDS = 120.0

# Progress callback: ``progress(stage: str, elapsed_seconds: float) -> None``.
ProgressCallback = Callable[[str, float], None]
# Cancellation callback: ``cancelled() -> bool``.
CancelCallback = Callable[[], bool]

LOCK_DIR_REL = Path("open-law-lens")
LOCK_FILENAME = "scholar-recovery.lock"

# Barrier signals that must stop recovery without interaction.
_BARRIER_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("captcha",),
    ("i'm not a robot", "i am not a robot", "not a robot"),
    ("unusual traffic", "automated queries"),
    ("log in", "sign in", "login required"),
    ("your choice", "consent", "before you continue"),
)


class BrowserRecoveryError(RuntimeError):
    """Base error for default-browser Scholar recovery."""


class RecoveryBusyError(BrowserRecoveryError):
    """Another recovery is already running in this user session."""


@dataclass(frozen=True)
class ScholarRecoveryRequest:
    query: str
    expected_citation: str = ""
    cluster_id: str = ""
    case_name: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "expected_citation": self.expected_citation,
            "cluster_id": self.cluster_id,
            "case_name": self.case_name,
        }


@dataclass(frozen=True)
class ScholarRecoveryOutcome:
    version: int
    outcome: str
    query: str
    source_url: str
    message: str

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "outcome": self.outcome,
            "query": self.query,
            "source_url": self.source_url,
            "message": self.message,
        }


def normalize_recovery_query(query: str) -> str:
    return re.sub(r"\s+", " ", query or "").strip()


def is_scholar_case_url(url: str) -> bool:
    try:
        validate_scholar_source_url(url)
    except Exception:
        return False
    return True


def validate_recovery_result(payload: Any) -> ScholarRecoveryOutcome | None:
    """Return a validated outcome, or ``None`` if the payload is invalid."""
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != RESULT_VERSION:
        return None
    outcome = str(payload.get("outcome") or "")
    if outcome not in VALID_OUTCOMES:
        return None
    query = normalize_recovery_query(str(payload.get("query") or ""))
    source_url = str(payload.get("source_url") or "").strip()
    message = re.sub(r"\s+", " ", str(payload.get("message") or "")).strip()
    if outcome == "copied":
        if not source_url or not is_scholar_case_url(source_url):
            return None
    else:
        source_url = ""
    return ScholarRecoveryOutcome(
        version=RESULT_VERSION,
        outcome=outcome,
        query=query,
        source_url=source_url,
        message=message,
    )


def request_from_query(
    query: str,
    *,
    expected_citation: str = "",
    cluster_id: str = "",
    case_name: str = "",
) -> ScholarRecoveryRequest:
    clean_query = normalize_recovery_query(query)
    if not clean_query:
        raise BrowserRecoveryError("A Scholar recovery query is required.")
    return ScholarRecoveryRequest(
        query=clean_query,
        expected_citation=re.sub(r"\s+", " ", expected_citation or "").strip(),
        cluster_id=str(cluster_id or "").strip(),
        case_name=re.sub(r"\s+", " ", case_name or "").strip(),
    )


# ---------------------------------------------------------------------------
# Cross-process user-session recovery lock
# ---------------------------------------------------------------------------


def _runtime_dir(environment: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environment is None else environment
    base = str(env.get("XDG_RUNTIME_DIR") or "").strip()
    if not base:
        base = str(env.get("TMPDIR") or "").strip() or "/tmp"
    return Path(base)


class RecoveryLock:
    """A nonblocking user-session lock preventing concurrent recovery.

    The lock uses ``flock`` on a file under ``$XDG_RUNTIME_DIR/open-law-lens/``,
    so a second Open Law Lens window, embedded session, or Current Case TUI
    workflow fails fast with ``RecoveryBusyError`` instead of queueing.
    """

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        lock_dir = _runtime_dir(environment) / LOCK_DIR_REL
        lock_dir.mkdir(parents=True, exist_ok=True)
        self.path = lock_dir / LOCK_FILENAME
        self._fd: int | None = None

    def acquire(self) -> bool:
        if self._fd is not None:
            return True
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        # Clear any stale holder record (the fd itself is the lock).
        try:
            os.ftruncate(fd, 0)
        except OSError:
            pass
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None

    def __enter__(self) -> "RecoveryLock":
        if not self.acquire():
            raise RecoveryBusyError("Another Scholar recovery is already running.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Pure accessibility-tree helpers (unit-testable with synthetic trees)
# ---------------------------------------------------------------------------


def normalize_match_token(value: str) -> str:
    """Casefold and strip non-alphanumerics for corroboration matching."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def node_text(node: Mapping[str, Any]) -> str:
    text = node.get("text")
    if isinstance(text, str):
        return text
    if isinstance(text, dict):
        return str(text.get("content") or "")
    return ""


def node_name(node: Mapping[str, Any]) -> str:
    name = node.get("name")
    return str(name) if name else ""


def node_full_text(node: Mapping[str, Any]) -> str:
    return f"{node_name(node)} {node_text(node)}".strip()


def node_is_visible(node: Mapping[str, Any]) -> bool:
    states = node.get("states")
    return bool(
        isinstance(states, list)
        and "showing" in states
        and "visible" in states
    )


def node_role(node: Mapping[str, Any]) -> str:
    return str(node.get("role") or "").casefold()


def _descendant_set(
    tree: Sequence[Mapping[str, Any]], root_index: int
) -> set[int]:
    """Return the indexes of ``root_index`` and every descendant in ``tree``.

    Walks each node's ``parent_index`` chain up to the root, bounded so a
    malformed or cyclic tree cannot hang.
    """
    by_index: dict[int, Mapping[str, Any]] = {int(n.get("index")): n for n in tree}
    result: set[int] = {root_index}
    for node in tree:
        current = int(node.get("index"))
        for _ in range(512):
            if current == root_index:
                result.add(int(node.get("index")))
                break
            holder = by_index.get(current)
            if holder is None:
                break
            pid = holder.get("parent_index")
            if pid is None:
                break
            try:
                pidx = int(pid)
            except (TypeError, ValueError):
                break
            if pidx == current or pidx not in by_index:
                break
            current = pidx
    return result


def scope_frame_index(
    tree: Sequence[Mapping[str, Any]], window_title: str
) -> int | None:
    """Return the frame node whose name matches the compositor window title.

    Firefox can expose multiple tabs and same-process windows in one tree, so
    the match must be confined to the exact frame for the selected tab.
    """
    expected = normalize_match_token(window_title)
    if not expected:
        return None
    matches: list[int] = []
    for node in tree:
        if node_role(node) != "frame":
            continue
        name = normalize_match_token(node_name(node))
        if name and (name == expected or expected in name or name in expected):
            matches.append(int(node.get("index")))
    if len(matches) == 1:
        return matches[0]
    if matches:
        # Prefer the visible frame when multiple collide.
        for node in tree:
            if int(node.get("index")) in matches and node_is_visible(node):
                return int(node.get("index"))
        return matches[0]
    # Fallback: the visible frame node itself.
    for node in tree:
        if node_role(node) == "frame" and node_is_visible(node):
            return int(node.get("index"))
    return None


def find_scholar_url(
    tree: Sequence[Mapping[str, Any]], scoped: Sequence[Mapping[str, Any]]
) -> str | None:
    """Return the Scholar URL from the address-bar combo box, or ``None``.

    Only ``https://`` URLs are surfaced, and only the Scholar host (or its
    ``www.`` subdomain) qualifies.
    """
    for node in scoped:
        if node_role(node) != "combo box":
            continue
        raw = node_text(node)
        if not raw:
            raw = node_name(node)
        if "scholar.google" not in raw.casefold():
            continue
        address = raw.strip()
        if not address.startswith("https://"):
            # The address bar may prepend the scheme inconsistently.
            address = "https://" + address.lstrip("/")
        host_part = re.split(r"[/?#]", address)[2] if address.count("/") >= 2 else address
        hostname = host_part.casefold()
        if hostname == SCHOLAR_NETLOC or hostname.endswith("." + SCHOLAR_NETLOC):
            return address
    return None


def detect_barrier(
    tree: Sequence[Mapping[str, Any]], scoped: Sequence[Mapping[str, Any]]
) -> str | None:
    """Return a barrier reason if the scoped page is blocked, else ``None``."""
    text = " ".join(node_full_text(node) for node in scoped).casefold()
    for patterns in _BARRIER_PATTERNS:
        for pattern in patterns:
            if pattern in text:
                return pattern
    absent = ("page not found", "no results", "did not match any")
    if any(word in text for word in absent):
        return "missing page"
    return None


def find_result_link(
    tree: Sequence[Mapping[str, Any]],
    scoped: Sequence[Mapping[str, Any]],
    expected_citation: str,
    case_name: str,
) -> Mapping[str, Any] | None:
    """Return the single corroborated visible result link, or ``None``.

    When a trustworthy case name is supplied, the link must match the name and
    its containing block must also corroborate the expected citation. When only
    a citation is known, a citation-only fallback is permitted but duplicate
    candidates are rejected (never a guess).
    """
    by_index: dict[int, Mapping[str, Any]] = {
        int(n.get("index")): n for n in tree
    }
    scoped_indexes = {int(n.get("index")) for n in scoped}

    def within(node: Mapping[str, Any], ancestor_index: int) -> bool:
        current = node
        for _ in range(64):
            if int(current.get("index")) == ancestor_index:
                return True
            pid = current.get("parent_index")
            if pid is None:
                return False
            try:
                parent = by_index[int(pid)]
            except (KeyError, TypeError, ValueError):
                return False
            current = parent
        return False

    def block_for_link(link: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Walk up from the link to a heading, then return the heading's parent."""
        current = link
        heading = None
        for _ in range(32):
            pid = current.get("parent_index")
            if pid is None:
                break
            try:
                parent = by_index[int(pid)]
            except (KeyError, TypeError, ValueError):
                break
            if node_role(parent) == "heading":
                heading = parent
                break
            current = parent
        if heading is None:
            return None
        parent_index = heading.get("parent_index")
        if parent_index is None:
            return heading
        try:
            return by_index[int(parent_index)]
        except (KeyError, TypeError, ValueError):
            return heading

    def nearby_text(block: Mapping[str, Any]) -> str:
        block_index = int(block.get("index"))
        parts = []
        for node in tree:
            if int(node.get("index")) not in scoped_indexes:
                continue
            if within(node, block_index):
                parts.append(node_full_text(node))
        return " ".join(parts)

    citation_norm = normalize_match_token(expected_citation)
    case_norm = normalize_match_token(case_name)

    visible_links = [
        node
        for node in scoped
        if node_role(node) == "link"
        and node_is_visible(node)
        and node_name(node)
    ]

    candidates: list[Mapping[str, Any]] = []

    # Pass 1: name + citation corroboration.
    if case_norm:
        for link in visible_links:
            link_norm = normalize_match_token(node_name(link))
            if not (case_norm in link_norm or link_norm in case_norm):
                continue
            block = block_for_link(link)
            if block is None:
                continue
            if citation_norm and citation_norm in normalize_match_token(
                nearby_text(block)
            ):
                candidates.append(link)

    # Pass 2: citation-only fallback (only when no trustworthy case name).
    if not candidates and citation_norm and not case_norm:
        for link in visible_links:
            block = block_for_link(link)
            if block is None:
                continue
            if citation_norm in normalize_match_token(nearby_text(block)):
                candidates.append(link)

    # Deduplicate by index and reject ambiguity.
    unique: dict[int, Mapping[str, Any]] = {}
    for link in candidates:
        unique[int(link.get("index"))] = link

    if len(unique) == 1:
        return next(iter(unique.values()))
    return None


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class ScholarRecoveryJob:
    """Owns the deterministic Scholar recovery state machine.

    On success the job leaves the copied opinion text on the regular clipboard
    and returns a ``copied`` outcome carrying the validated Scholar case URL.
    The caller (``scholar_recovery_service``) is responsible for reading the
    clipboard and persisting through the shared import path.
    """

    def __init__(
        self,
        request: ScholarRecoveryRequest,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
        client: ComputerUseMCPClient | None = None,
    ) -> None:
        self.request = request
        self.timeout = timeout
        self.progress = progress
        self.cancelled = cancelled
        self._owns_client = client is None
        self.client = client
        self._started_at = time.monotonic()
        self._target_window_id: int | None = None
        self._target_title: str = ""
        self._handler_name = ""
        self._handler_desktop_id = ""

    # -- helpers ------------------------------------------------------------

    def _elapsed(self) -> float:
        return time.monotonic() - self._started_at

    def _report(self, stage: str) -> None:
        if self.progress is not None:
            self.progress(stage, self._elapsed())

    def _is_cancelled(self) -> bool:
        if self.cancelled is not None:
            try:
                if self.cancelled():
                    return True
            except Exception:
                pass
        return False

    def _deadline_exceeded(self) -> bool:
        return self._elapsed() > self.timeout

    def _outcome(self, outcome: str, message: str, source_url: str = "") -> ScholarRecoveryOutcome:
        return ScholarRecoveryOutcome(
            version=RESULT_VERSION,
            outcome=outcome,
            query=self.request.query,
            source_url=source_url,
            message=(message or ""),
        )

    # -- state 1: acquire lock ---------------------------------------------

    def _acquire_lock(self) -> RecoveryLock:
        lock = RecoveryLock()
        if not lock.acquire():
            raise RecoveryBusyError("Another Scholar recovery is already running.")
        return lock

    # -- state 2: check desktop --------------------------------------------

    def _check_desktop(self) -> None:
        self._report("Checking desktop")
        payload = self.client.doctor()
        capabilities = doctor_readiness(payload)
        if capabilities.blockers:
            raise BrowserRecoveryError(
                "Computer Use is not ready: " + "; ".join(capabilities.blockers)
            )
        if not (
            capabilities.can_register_mcp_tools
            and capabilities.can_build_accessibility_tree
            and capabilities.can_query_windows
            and capabilities.can_send_development_input
        ):
            raise BrowserRecoveryError(
                "Computer Use is missing a required desktop capability."
            )

    # -- state 3: snapshot windows -----------------------------------------

    def _snapshot_windows(self) -> set[int]:
        payload = self.client.list_windows()
        windows = payload.get("windows")
        if not isinstance(windows, list):
            return set()
        return {int(w.get("window_id")) for w in windows if isinstance(w.get("window_id"), int)}

    # -- state 4: open Scholar ---------------------------------------------

    def _open_scholar(self) -> str:
        self._report("Opening Scholar")
        url = build_scholar_case_search_url(self.request.query)
        self._handler_name, self._handler_desktop_id = launch_scholar_url(url)
        return url

    # -- state 5: find target window --------------------------------------

    def _find_target_window(self, prior: set[int]) -> tuple[int, str]:
        deadline = time.monotonic() + self.page_deadline()
        while time.monotonic() < deadline:
            if self._is_cancelled() or self._deadline_exceeded():
                break
            payload = self.client.list_windows()
            windows = payload.get("windows")
            if not isinstance(windows, list):
                windows = []
            for window in windows:
                window_id = window.get("window_id")
                if not isinstance(window_id, int):
                    continue
                title = str(window.get("title") or "")
                if "scholar" in title.casefold() or "google scholar" in title.casefold():
                    return int(window_id), title
                # A retitled/new window from the default handler that is Scholar.
                if int(window_id) not in prior and self._matches_handler(window):
                    if "scholar" in title.casefold():
                        return int(window_id), title
            time.sleep(0.5)
        raise BrowserRecoveryError("The Scholar window did not appear.")

    def _matches_handler(self, window: Mapping[str, Any]) -> bool:
        identity = (
            str(window.get("app_id") or "")
            + " "
            + str(window.get("wm_class") or "")
        ).casefold()
        handler = (
            self._handler_name + " " + self._handler_desktop_id
        ).casefold()
        if not handler:
            return True
        token = re.sub(r"[^a-z0-9]+", "", handler)
        haystack = re.sub(r"[^a-z0-9]+", "", identity)
        return bool(token) and (token in haystack or haystack in token)

    # -- state 6: observe results ------------------------------------------

    def _observe(self, window_id: int) -> tuple[list[Mapping[str, Any]], str, str]:
        payload = self.client.get_app_state(
            window_id=window_id,
            max_nodes=self.client.max_nodes,
            max_depth=self.client.max_depth,
        )
        tree = payload.get("accessibility_tree")
        if not isinstance(tree, list):
            tree = []
        title = ""
        context = payload.get("window_context")
        if isinstance(context, dict):
            title = str(context.get("title") or "")
        url = find_scholar_url(tree, tree)
        return list(tree), title, (url or "")

    # -- state 8: check barriers -------------------------------------------

    def _check_barriers(
        self, tree: list[Mapping[str, Any]], scoped: list[Mapping[str, Any]]
    ) -> str | None:
        return detect_barrier(tree, scoped)

    # -- run ---------------------------------------------------------------

    def page_deadline(self) -> float:
        return min(DEFAULT_PAGE_DEADLINE_SECONDS, max(15.0, self.timeout / 2.0))

    def run(self) -> ScholarRecoveryOutcome:
        lock = self._acquire_lock()
        try:
            if self.client is None:
                self.client = ComputerUseMCPClient(job_deadline=self.timeout)
                self.client.start()
            else:
                # An externally supplied client must already be started.
                if self.client.process is None:
                    self.client.start()

            self._check_desktop()
            prior = self._snapshot_windows()
            self._open_scholar()

            self._report("Finding matching case")
            window_id, title = self._find_target_window(prior)
            self._target_window_id = window_id
            self._target_title = title

            tree, observed_title, url = self._observe(window_id)
            frame_index = scope_frame_index(tree, observed_title or title)
            if frame_index is None:
                return self._outcome("not_found", "No matching Scholar frame was found.")
            scoped = [
                node
                for node in tree
                if int(node.get("index")) in _descendant_set(tree, frame_index)
            ]

            barrier = self._check_barriers(tree, scoped)
            if barrier:
                return self._outcome("blocked", f"Google Scholar showed {barrier}; leaving it visible.")

            expected_citation = self.request.expected_citation or self.request.query
            case_name = self.request.case_name

            link = find_result_link(tree, scoped, expected_citation, case_name)
            if link is None:
                return self._outcome("not_found", "No single corroborated Scholar result matched.")

            self._report("Opening opinion")
            try:
                self.client.perform_action(element_index=int(link.get("index")))
            except ComputerUseMCPError as exc:
                return self._outcome("failed", "Opening the Scholar result failed: " + str(exc))

            # Revalidate the opinion page on the same numeric window/frame.
            deadline = time.monotonic() + self.page_deadline()
            opinion_url = ""
            while time.monotonic() < deadline:
                if self._is_cancelled() or self._deadline_exceeded():
                    return self._outcome("failed", "Scholar recovery timed out.")
                tree, observed_title, url = self._observe(window_id)
                opinion_url = find_scholar_url(tree, tree)
                if opinion_url and is_scholar_case_url(opinion_url):
                    frame_index = scope_frame_index(tree, observed_title or title)
                    if frame_index is None:
                        return self._outcome("not_found", "No matching Scholar opinion frame was found.")
                    scoped = [
                        node
                        for node in tree
                        if int(node.get("index")) in _descendant_set(tree, frame_index)
                    ]
                    barrier = self._check_barriers(tree, scoped)
                    if barrier:
                        return self._outcome("blocked", f"Google Scholar showed {barrier}; leaving it visible.")
                    break
                time.sleep(0.5)
            else:
                return self._outcome("failed", "The Scholar opinion page did not load.")

            # Verify the opinion identifies the expected case.
            if case_name and normalize_match_token(case_name) not in normalize_match_token(
                observed_title
            ) + normalize_match_token(_tree_text(scoped)):
                return self._outcome("not_found", "The opened opinion did not match the expected case.")

            # The opinion title is now the fresh baseline for the copy
            # mutations; the earlier search-results title is intentionally
            # stale once we have navigated onto the opinion page.
            opinion_title = observed_title

            self._report("Copying opinion")
            self._revalidate_window(window_id, opinion_title)
            self.client.press_key(key="Ctrl+A", window_id=window_id)
            time.sleep(0.5)
            tree, after_select_title, _ = self._observe(window_id)
            self._revalidate_identity(window_id, opinion_title, after_select_title)

            self.client.press_key(key="Ctrl+C", window_id=window_id)

            return self._outcome("copied", "Copied the Scholar opinion.", source_url=opinion_url)
        except RecoveryBusyError:
            return self._outcome("failed", "Another Scholar recovery is already running.")
        except (BrowserRecoveryError, ComputerUseMCPError, OSError) as exc:
            return self._outcome("failed", str(exc))
        finally:
            lock.release()
            if self._owns_client and self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    self.client.terminate()

    def _revalidate_window(self, window_id: int, expected_title: str) -> None:
        windows = self.client.list_windows().get("windows") or []
        for window in windows:
            if window.get("window_id") == window_id:
                title = str(window.get("title") or "")
                if (
                    title
                    and expected_title
                    and normalize_match_token(title) != normalize_match_token(expected_title)
                ):
                    raise BrowserRecoveryError("The Scholar window title changed before input.")
                return
        raise BrowserRecoveryError("The Scholar window disappeared before input.")

    def _revalidate_identity(
        self, window_id: int, expected_title: str, observed_title: str
    ) -> None:
        if (
            observed_title
            and expected_title
            and normalize_match_token(observed_title) != normalize_match_token(expected_title)
        ):
            raise BrowserRecoveryError("The Scholar window title changed during copy.")

    def cancel(self) -> None:
        if self.client is not None:
            self.client.cancel()


def _tree_text(tree: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(node_full_text(node) for node in tree)


def run_scholar_recovery(
    request: ScholarRecoveryRequest,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> ScholarRecoveryOutcome:
    """Run the deterministic Scholar recovery state machine.

    This is the only desktop-recovery entry point. It returns one of the
    ``copied`` / ``not_found`` / ``blocked`` / ``failed`` outcomes without ever
    launching a model.
    """
    job = ScholarRecoveryJob(
        request,
        timeout=timeout,
        progress=progress,
        cancelled=cancelled,
    )
    return job.run()


__all__ = [
    "BrowserRecoveryError",
    "CancelCallback",
    "DEFAULT_TIMEOUT_SECONDS",
    "ProgressCallback",
    "RecoveryBusyError",
    "RecoveryLock",
    "ScholarRecoveryJob",
    "ScholarRecoveryOutcome",
    "ScholarRecoveryRequest",
    "detect_barrier",
    "find_result_link",
    "find_scholar_url",
    "is_scholar_case_url",
    "node_full_text",
    "node_name",
    "node_text",
    "normalize_match_token",
    "normalize_recovery_query",
    "request_from_query",
    "run_scholar_recovery",
    "scope_frame_index",
    "validate_recovery_result",
]
