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
  matches exactly one qualifying result selected from that result's own
  primary reporter/court metadata (never a snippet, the search box, or another
  result).
* It only ever performs a targeted ``perform_action`` (semantic element index)
  and targeted ``Ctrl+A`` / ``Ctrl+C`` key presses with an exact numeric
  ``window_id``, revalidating window/frame/title/URL around every mutation.
* When recovery ends, it returns focus to the exact window that initiated the
  job only if the Scholar window still has focus. It never steals focus back
  after the user switches elsewhere, and it leaves barriers visible.
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
from urllib.parse import parse_qs, urlparse

from .computer_use_mcp import (
    ComputerUseMCPClient,
    ComputerUseMCPError,
    doctor_readiness,
)
from .external_import import normalize_official_citation
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

# A genuine Scholar "no results"/"not found" notice is a short standalone
# element. Loaded opinions routinely contain the same words inside ordinary
# prose (e.g. "there were no results indicating whether he was the biological
# father"), so a whole-page substring match would misclassify a successfully
# opened opinion as a missing page. Missing-page detection therefore only
# fires on short standalone nodes.
_MISSING_PAGE_NODE_MAX_CHARS = 240
_MISSING_PAGE_PREFIX_PATTERNS = ("no results", "page not found")
_MISSING_PAGE_CONTAINED_PATTERNS = (
    "did not match any",
    "no articles found",
    "no results were found",
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
    filing_year: str = ""
    docket_number: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "expected_citation": self.expected_citation,
            "cluster_id": self.cluster_id,
            "case_name": self.case_name,
            "filing_year": self.filing_year,
            "docket_number": self.docket_number,
        }


@dataclass(frozen=True)
class ScholarRecoveryOutcome:
    version: int
    outcome: str
    query: str
    source_url: str
    message: str
    # Backward-compatible optional field (result version stays 1): the official
    # California reporter citation discovered from the selected result's own
    # primary metadata. Old callers/tests may omit it; it defaults to empty.
    official_citation: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "outcome": self.outcome,
            "query": self.query,
            "source_url": self.source_url,
            "message": self.message,
            "official_citation": self.official_citation,
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
    official_citation = normalize_official_citation(
        str(payload.get("official_citation") or "")
    )
    if outcome == "copied":
        if not source_url or not is_scholar_case_url(source_url):
            return None
    else:
        source_url = ""
        official_citation = ""
    return ScholarRecoveryOutcome(
        version=RESULT_VERSION,
        outcome=outcome,
        query=query,
        source_url=source_url,
        message=message,
        official_citation=official_citation,
    )


def request_from_query(
    query: str,
    *,
    expected_citation: str = "",
    cluster_id: str = "",
    case_name: str = "",
    filing_year: str = "",
    docket_number: str = "",
) -> ScholarRecoveryRequest:
    clean_query = normalize_recovery_query(query)
    if not clean_query:
        raise BrowserRecoveryError("A Scholar recovery query is required.")
    return ScholarRecoveryRequest(
        query=clean_query,
        expected_citation=re.sub(r"\s+", " ", expected_citation or "").strip(),
        cluster_id=str(cluster_id or "").strip(),
        case_name=re.sub(r"\s+", " ", case_name or "").strip(),
        filing_year=re.sub(r"\s+", "", filing_year or ""),
        docket_number=re.sub(r"\s+", " ", docket_number or "").strip(),
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


@dataclass(frozen=True)
class ScholarResultMatch:
    """One qualifying Scholar search result.

    ``link`` is the semantic title link to activate; ``heading_text`` and
    ``primary_metadata`` hold the result's own heading and reporter/court
    metadata text; ``official_citation`` is the official California reporter
    citation discovered in that primary metadata — never from a snippet, the
    search box, or another result.
    """

    link: Mapping[str, Any]
    heading_text: str
    primary_metadata: str
    official_citation: str

    def to_json(self) -> dict[str, Any]:
        return {
            "heading_text": self.heading_text,
            "primary_metadata": self.primary_metadata,
            "official_citation": self.official_citation,
        }


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


def scope_selected_document(
    tree: Sequence[Mapping[str, Any]], scoped_frame: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Confine page content to the selected tab's top-level web document.

    Firefox exposes every tab in a window under one frame. Hidden tabs can
    contain unrelated results, login text, or barriers, so frame-only scoping
    is insufficient even when the numeric window and address bar are exact.
    During search -> opinion navigation the address bar can also update before
    the new tab's document gains its AT-SPI ``showing``/``focused`` states, and
    Firefox can leave a background tab's document ``focused``. Selection
    therefore prefers the document under a showing internal-frame/scroll-pane
    ancestor (the actually displayed tab), then correlates the single selected
    ``page tab``'s title with the candidate document's title, then focus and
    the ``showing`` state itself.
    """
    frame_indexes = {int(node.get("index")) for node in scoped_frame}
    by_index: dict[int, Mapping[str, Any]] = {
        int(node.get("index")): node for node in tree
    }
    candidates = [
        node
        for node in scoped_frame
        if node_role(node) == "document web"
        and int(node.get("index")) in frame_indexes
        and "visible" in (node.get("states") or [])
    ]
    if not candidates:
        return list(scoped_frame)

    selected_tabs = [
        node
        for node in scoped_frame
        if node_role(node) == "page tab"
        and "selected" in (node.get("states") or [])
        and node_name(node)
    ]
    tab_norm = (
        normalize_match_token(node_name(selected_tabs[0]))
        if len(selected_tabs) == 1
        else ""
    )

    def _ancestor_chain_showing(node: Mapping[str, Any]) -> bool:
        current = node
        for _ in range(64):
            pid = current.get("parent_index")
            try:
                parent = by_index[int(pid)]
            except (KeyError, TypeError, ValueError):
                return False
            if node_role(parent) not in ("internal frame", "scroll pane"):
                return False
            if "showing" in (parent.get("states") or []):
                return True
            current = parent
        return False

    def rank(node: Mapping[str, Any]) -> tuple[Any, ...]:
        name_norm = normalize_match_token(node_name(node))
        tab_match = bool(tab_norm) and (
            tab_norm == name_norm or tab_norm in name_norm or name_norm in tab_norm
        )
        states = node.get("states") or []
        return (
            0 if _ancestor_chain_showing(node) else 1,
            0 if tab_match else 1,
            0 if "focused" in states else 1,
            0 if "showing" in states else 1,
            int(node.get("depth") or 0),
            int(node.get("index")),
        )

    candidates.sort(key=rank)
    document_index = int(candidates[0].get("index"))
    content_indexes = _descendant_set(tree, document_index)
    return [node for node in scoped_frame if int(node.get("index")) in content_indexes]


def scholar_search_url_matches(url: str, expected_url: str) -> bool:
    """Return whether two Scholar search URLs carry the same query."""
    try:
        observed = urlparse(url)
        expected = urlparse(expected_url)
    except ValueError:
        return False
    if observed.scheme != "https" or expected.scheme != "https":
        return False
    if observed.hostname != SCHOLAR_NETLOC or expected.hostname != SCHOLAR_NETLOC:
        return False
    if observed.path.rstrip("/") != "/scholar" or expected.path.rstrip("/") != "/scholar":
        return False
    observed_query = parse_qs(observed.query).get("q", [""])[0]
    expected_query = parse_qs(expected.query).get("q", [""])[0]
    return bool(observed_query) and normalize_match_token(observed_query) == normalize_match_token(
        expected_query
    )


def scholar_case_url_matches(url: str, expected_url: str) -> bool:
    """Return whether two Scholar opinion URLs identify the same case."""
    try:
        observed = urlparse(url)
        expected = urlparse(expected_url)
    except ValueError:
        return False
    if observed.scheme != "https" or expected.scheme != "https":
        return False
    if observed.hostname != SCHOLAR_NETLOC or expected.hostname != SCHOLAR_NETLOC:
        return False
    if not (
        observed.path.startswith("/scholar_case")
        and expected.path.startswith("/scholar_case")
    ):
        return False
    observed_case = parse_qs(observed.query).get("case", [""])[0]
    expected_case = parse_qs(expected.query).get("case", [""])[0]
    return bool(observed_case) and observed_case == expected_case


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
    """Return a barrier reason if the scoped page is blocked, else ``None``.

    Interaction barriers (CAPTCHA, robot checks, login, consent) are matched
    as substrings of the scoped page because stopping early is always safe. A
    "missing page" verdict, by contrast, is only derived from short standalone
    notice elements so ordinary opinion prose containing phrases like "no
    results" can never masquerade as a missing page.
    """
    text = " ".join(node_full_text(node) for node in scoped).casefold()
    for patterns in _BARRIER_PATTERNS:
        for pattern in patterns:
            if pattern in text:
                return pattern
    for node in scoped:
        notice = re.sub(r"\s+", " ", node_full_text(node)).strip()
        if not notice or len(notice) > _MISSING_PAGE_NODE_MAX_CHARS:
            continue
        lowered = notice.casefold()
        if any(lowered.startswith(p) for p in _MISSING_PAGE_PREFIX_PATTERNS):
            return "missing page"
        if any(p in lowered for p in _MISSING_PAGE_CONTAINED_PATTERNS):
            return "missing page"
    return None


_RESULT_BLOCK_MAX_SCANNED = 160
_RESULT_BLOCK_MAX_TEXT_NODES = 2
_RESULT_BLOCK_MAX_CHARS = 400


@dataclass(frozen=True)
class ScholarResultText:
    """The bounded text zones of one Scholar search result.

    ``heading`` is the result title, ``primary_metadata`` is the result's own
    reporter/court metadata line, and ``snippet`` is ellipsis-prefixed quoted
    text. Only the first two may ever corroborate a candidate; a snippet can
    quote the target citation while describing a different case, so it is
    tracked separately and never matched against.
    """

    heading: str
    primary_metadata: str
    snippet: str


def split_result_block(
    tree: Sequence[Mapping[str, Any]],
    scoped_indexes: set[int],
    heading: Mapping[str, Any],
) -> ScholarResultText:
    """Separate one Scholar result's heading, primary metadata, and snippet.

    Starting at a result-title heading, this collects the heading text plus up
    to two short meaningful text nodes that live inside the result container
    (the heading's parent) or the heading itself, walking the tree in index
    order and always stopping at the next heading. This covers the reporter
    metadata whether AT-SPI exposes it as a direct sibling of the heading or
    nested inside a sibling container, while text in another result's snippet,
    the page footer, or the search box (which echoes the query) can never
    corroborate the candidate. Text beginning with an ellipsis is classified
    as the snippet and is returned separately; it can never corroborate a
    candidate.
    """
    by_index: dict[int, Mapping[str, Any]] = {
        int(node.get("index")): node for node in tree
    }
    heading_index = int(heading.get("index"))
    try:
        position = next(
            i for i, node in enumerate(tree) if int(node.get("index")) == heading_index
        )
    except StopIteration:
        return ScholarResultText(
            heading=node_full_text(heading), primary_metadata="", snippet=""
        )

    allowed_roots = {heading_index}
    try:
        block_root = int(heading.get("parent_index"))
    except (TypeError, ValueError):
        block_root = None
    if block_root is not None:
        allowed_roots.add(block_root)

    def within_block(node: Mapping[str, Any]) -> bool:
        current = int(node.get("index"))
        for _ in range(64):
            if current in allowed_roots:
                return True
            holder = by_index.get(current)
            if holder is None:
                return False
            try:
                current = int(holder.get("parent_index"))
            except (TypeError, ValueError):
                return False
        return False

    heading_text = node_full_text(heading)
    metadata_parts: list[str] = []
    snippet_parts: list[str] = []
    collected_chars = len(heading_text)
    additional = 0
    scanned = 0
    snippet_chars = 0
    for node in tree[position + 1 :]:
        scanned += 1
        if scanned > _RESULT_BLOCK_MAX_SCANNED:
            break
        if int(node.get("index")) not in scoped_indexes:
            continue
        if node_role(node) == "heading":
            break
        if not within_block(node):
            continue
        text = re.sub(r"\s+", " ", node_full_text(node)).strip()
        if not text or text.startswith(("…", "...")):
            if text:
                snippet_parts.append(text)
                snippet_chars += len(text)
                if snippet_chars >= _RESULT_BLOCK_MAX_CHARS:
                    break
            continue
        if not re.search(r"[a-z0-9]", text.casefold()):
            continue
        metadata_parts.append(text)
        additional += 1
        collected_chars += len(text)
        if (
            additional >= _RESULT_BLOCK_MAX_TEXT_NODES
            or collected_chars >= _RESULT_BLOCK_MAX_CHARS
        ):
            break
    return ScholarResultText(
        heading=heading_text,
        primary_metadata=" ".join(metadata_parts),
        snippet=" ".join(snippet_parts),
    )


def result_block_text(
    tree: Sequence[Mapping[str, Any]],
    scoped_indexes: set[int],
    heading: Mapping[str, Any],
) -> str:
    """Return the bounded heading-plus-primary-metadata text for one result.

    Snippet-style text is excluded; see :func:`split_result_block` for the
    full zone separation.
    """
    text = split_result_block(tree, scoped_indexes, heading)
    return f"{text.heading} {text.primary_metadata}".strip()


def _metadata_docket_confirmed(docket_number: str, primary_metadata: str) -> bool:
    """Whether the result's primary metadata exposes the expected docket."""
    if not docket_number:
        return False
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(docket_number)}(?![A-Za-z0-9])",
            primary_metadata,
            re.IGNORECASE,
        )
    )


def _metadata_docket_conflicts(docket_number: str, primary_metadata: str) -> bool:
    """Whether the primary metadata exposes some other California case number."""
    if not re.search(r"\b[A-Z]\d{6}\b", primary_metadata):
        return False
    return not re.search(
        rf"(?<![A-Za-z0-9]){re.escape(docket_number)}(?![A-Za-z0-9])",
        primary_metadata,
        re.IGNORECASE,
    )


def _discovered_citation(expected_citation: str, primary_metadata: str) -> str:
    """Prefer the parsed official citation from the primary metadata; keep the
    explicit expected citation when the metadata does not parse."""
    derived = normalize_official_citation(primary_metadata)
    return derived or normalize_official_citation(expected_citation)


def find_result_matches(
    tree: Sequence[Mapping[str, Any]],
    scoped: Sequence[Mapping[str, Any]],
    expected_citation: str,
    case_name: str,
    *,
    docket_number: str = "",
    filing_year: str = "",
) -> list[ScholarResultMatch]:
    """Return every qualifying visible result link, in tree order.

    When an expected official citation is known, the link must match the name
    and its result's primary metadata must carry exactly that citation. When
    only a citation is known, a citation-only fallback is permitted, but the
    caller must still reject multiple candidates (never a guess) in both
    modes.

    Citation-less recovery never treats the free-form search query as a
    citation. It requires a trustworthy case name plus a discriminator — the
    docket number when available, otherwise the filing year — and matches only
    results whose primary metadata carries an official California reporter
    citation plus that discriminator. Title alone is never enough to click a
    result, and a snippet, the search box, or another result can never
    corroborate a candidate.
    """
    by_index: dict[int, Mapping[str, Any]] = {
        int(n.get("index")): n for n in tree
    }
    scoped_indexes = {int(n.get("index")) for n in scoped}

    citation_norm = normalize_match_token(expected_citation)
    case_norm = normalize_match_token(case_name)
    docket_norm = normalize_match_token(docket_number)
    docket_raw = re.sub(r"\s+", " ", docket_number or "").strip()
    year = validated_filing_year(filing_year)
    if not citation_norm:
        # Citation-less identity: an exact case name plus at least one
        # discriminator (docket or filing year) is required. A name-only
        # match is never sufficient to click a result.
        if not case_norm or not (docket_norm or year):
            return []

    def heading_for_link(link: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Walk up from a result link to its containing heading."""
        current = link
        for _ in range(32):
            pid = current.get("parent_index")
            if pid is None:
                return None
            try:
                parent = by_index[int(pid)]
            except (KeyError, TypeError, ValueError):
                return None
            if node_role(parent) == "heading":
                return parent
            current = parent
        return None

    visible_links = [
        node
        for node in scoped
        if node_role(node) == "link"
        and node_is_visible(node)
        and node_name(node)
    ]

    matches: list[ScholarResultMatch] = []
    for link in visible_links:
        heading = heading_for_link(link)
        if heading is None:
            continue
        text = split_result_block(tree, scoped_indexes, heading)
        primary_raw = f"{text.heading} {text.primary_metadata}"
        if citation_norm:
            derived = normalize_official_citation(text.primary_metadata)
            if derived:
                if normalize_match_token(derived) != citation_norm:
                    continue
            elif citation_norm not in normalize_match_token(primary_raw):
                continue
            if case_norm:
                link_norm = normalize_match_token(node_name(link))
                if not (case_norm in link_norm or link_norm in case_norm):
                    continue
            discovered = _discovered_citation(expected_citation, derived)
        else:
            # Citation-less identity: the link must carry the exact case name
            # (punctuation-only differences such as ``S.H.`` versus ``SH``
            # normalize away), the primary metadata must parse as an official
            # California reporter citation, and the docket — or, when the
            # metadata omits it, the filing year — must corroborate. Snippets
            # and other results can never corroborate a candidate.
            if normalize_match_token(node_name(link)) != case_norm:
                continue
            discovered = normalize_official_citation(primary_raw)
            if not discovered:
                continue
            docket_ok = _metadata_docket_confirmed(docket_raw, primary_raw)
            year_in_metadata = _year_in_metadata(primary_raw, year)
            if docket_norm:
                # A docket-constrained result whose metadata omits the docket
                # may still qualify on title + citation + year, but only when
                # the metadata exposes no different case number.
                if not docket_ok and not (
                    year_in_metadata
                    and not _metadata_docket_conflicts(docket_raw, primary_raw)
                ):
                    continue
            elif not year_in_metadata:
                continue
        matches.append(
            ScholarResultMatch(
                link=link,
                heading_text=text.heading,
                primary_metadata=text.primary_metadata,
                official_citation=discovered,
            )
        )

    # Deduplicate by link index; the caller decides whether one match is
    # unique enough to click.
    unique: dict[int, ScholarResultMatch] = {}
    for match in matches:
        unique[int(match.link.get("index"))] = match
    return list(unique.values())


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
        self._origin_window_id: int | None = None
        self._target_window_id: int | None = None
        self._target_title: str = ""
        self._final_outcome = ""
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

    def _outcome(
        self,
        outcome: str,
        message: str,
        source_url: str = "",
        official_citation: str = "",
    ) -> ScholarRecoveryOutcome:
        self._final_outcome = outcome
        return ScholarRecoveryOutcome(
            version=RESULT_VERSION,
            outcome=outcome,
            query=self.request.query,
            source_url=source_url,
            message=(message or ""),
            official_citation=normalize_official_citation(official_citation),
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

    def _capture_origin_window(self) -> None:
        try:
            payload = self.client.focused_window()
        except (ComputerUseMCPError, OSError):
            return
        focused = payload.get("focused_window")
        if not isinstance(focused, Mapping):
            return
        window_id = focused.get("window_id")
        if isinstance(window_id, int) and window_id > 0:
            self._origin_window_id = window_id

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

    def _find_target_window(
        self, prior: set[int], expected_search_url: str
    ) -> tuple[int, str]:
        """Find the window whose scoped address bar has our exact search query.

        The default browser may reuse an existing Scholar window or open a new
        tab in an existing process. A Scholar-looking title alone can therefore
        identify a stale page or the wrong Scholar window.
        """
        deadline = time.monotonic() + self.page_deadline()
        while time.monotonic() < deadline:
            if self._is_cancelled() or self._deadline_exceeded():
                break
            payload = self.client.list_windows()
            windows = payload.get("windows")
            if not isinstance(windows, list):
                windows = []
            ordered = sorted(
                windows,
                key=lambda window: int(window.get("window_id") in prior),
            )
            for window in ordered:
                window_id = window.get("window_id")
                if not isinstance(window_id, int):
                    continue
                title = str(window.get("title") or "")
                looks_like_scholar = "scholar" in title.casefold()
                is_new_handler_window = window_id not in prior and self._matches_handler(window)
                if not (looks_like_scholar or is_new_handler_window):
                    continue
                try:
                    _tree, observed_title, observed_url = self._observe(window_id)
                except ComputerUseMCPError:
                    continue
                if scholar_search_url_matches(observed_url, expected_search_url):
                    return window_id, observed_title or title
            time.sleep(0.5)
        raise BrowserRecoveryError("The Scholar search page did not appear.")

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
        frame_index = scope_frame_index(tree, title)
        scoped = (
            [
                node
                for node in tree
                if int(node.get("index")) in _descendant_set(tree, frame_index)
            ]
            if frame_index is not None
            else []
        )
        url = find_scholar_url(tree, scoped)
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
            self._capture_origin_window()
            prior = self._snapshot_windows()
            search_url = self._open_scholar()

            self._report("Finding matching case")
            window_id, title = self._find_target_window(prior, search_url)
            self._target_window_id = window_id
            self._target_title = title

            expected_citation = self.request.expected_citation
            case_name = self.request.case_name
            search_deadline = time.monotonic() + self.page_deadline()
            match: ScholarResultMatch | None = None
            saw_search_page = False
            saw_result_structure = False
            multiple_qualifying = False
            while time.monotonic() < search_deadline:
                if self._is_cancelled() or self._deadline_exceeded():
                    return self._outcome("failed", "Scholar recovery timed out.")
                tree, observed_title, url = self._observe(window_id)
                frame_index = scope_frame_index(tree, observed_title or title)
                if frame_index is None or not scholar_search_url_matches(url, search_url):
                    time.sleep(0.5)
                    continue
                saw_search_page = True
                scoped_frame = [
                    node
                    for node in tree
                    if int(node.get("index")) in _descendant_set(tree, frame_index)
                ]
                scoped = scope_selected_document(tree, scoped_frame)
                barrier = self._check_barriers(tree, scoped)
                if barrier == "missing page":
                    return self._outcome("not_found", "Google Scholar returned no matching case.")
                if barrier:
                    return self._outcome("blocked", f"Google Scholar showed {barrier}; leaving it visible.")
                if any(
                    node_role(node) == "heading" and node_name(node)
                    for node in scoped
                ):
                    saw_result_structure = True
                matches = find_result_matches(
                    tree,
                    scoped,
                    expected_citation,
                    case_name,
                    docket_number=self.request.docket_number,
                    filing_year=self.request.filing_year,
                )
                if len(matches) == 1:
                    match = matches[0]
                    break
                if len(matches) > 1:
                    multiple_qualifying = True
                    break
                time.sleep(0.5)
            if match is None:
                if not saw_search_page:
                    return self._outcome(
                        "not_found", "The Scholar search results page did not load."
                    )
                if not saw_result_structure:
                    return self._outcome(
                        "not_found",
                        "The Scholar page loaded but showed no parseable result structure.",
                    )
                if multiple_qualifying:
                    return self._outcome(
                        "not_found",
                        "Multiple qualifying Scholar results matched; recovery stopped "
                        "without selecting one.",
                    )
                if not expected_citation.strip():
                    return self._outcome(
                        "not_found",
                        "No exact-title California reporter result matched the recovery identity.",
                    )
                return self._outcome("not_found", "No single corroborated Scholar result matched.")

            self._report("Opening opinion")
            try:
                self.client.perform_action(element_index=int(match.link.get("index")))
            except ComputerUseMCPError as exc:
                return self._outcome("failed", "Opening the Scholar result failed: " + str(exc))

            # Revalidate the opinion page on the same numeric window/frame.
            deadline = time.monotonic() + self.page_deadline()
            opinion_url = ""
            saw_opinion_url = False
            identity_confirmed = False
            while time.monotonic() < deadline:
                if self._is_cancelled() or self._deadline_exceeded():
                    return self._outcome("failed", "Scholar recovery timed out.")
                tree, observed_title, url = self._observe(window_id)
                opinion_url = url
                if not (opinion_url and is_scholar_case_url(opinion_url)):
                    time.sleep(0.5)
                    continue
                saw_opinion_url = True
                frame_index = scope_frame_index(tree, observed_title or title)
                if frame_index is None:
                    time.sleep(0.5)
                    continue
                scoped_frame = [
                    node
                    for node in tree
                    if int(node.get("index")) in _descendant_set(tree, frame_index)
                ]
                scoped = scope_selected_document(tree, scoped_frame)
                barrier = self._check_barriers(tree, scoped)
                if barrier == "missing page":
                    return self._outcome(
                        "not_found", "The Scholar opinion page was not found."
                    )
                if barrier:
                    return self._outcome("blocked", f"Google Scholar showed {barrier}; leaving it visible.")
                # The opened opinion must identify the expected case before
                # anything is copied: by name plus official citation when one
                # is known, or by case name plus the citation discovered from
                # the selected result plus docket/filing-year evidence for
                # citation-less recovery. Only bounded front-matter text is
                # inspected. A transiently mis-scoped tab simply retries until
                # the selected tab's document settles.
                if opinion_identity_confirmed(
                    expected_citation=expected_citation,
                    case_name=case_name,
                    docket_number=self.request.docket_number,
                    filing_year=self.request.filing_year,
                    observed_title=observed_title,
                    page_text=front_matter_text(scoped),
                    official_citation="" if expected_citation else match.official_citation,
                ):
                    identity_confirmed = True
                    break
                time.sleep(0.5)
            if not identity_confirmed:
                if saw_opinion_url:
                    return self._outcome(
                        "not_found", "The opened opinion did not match the expected case."
                    )
                return self._outcome("failed", "The Scholar opinion page did not load.")

            self._report("Copying opinion")
            # The compositor title can update before get_app_state's context
            # title after search -> opinion navigation. Confirm the exact
            # numeric window still exists, then use the stronger Scholar case
            # URL identity after selection instead of comparing lagging titles.
            self._revalidate_window(window_id)
            self.client.press_key(key="Ctrl+A", window_id=window_id)
            time.sleep(0.5)
            _tree, _after_select_title, after_select_url = self._observe(window_id)
            if not scholar_case_url_matches(after_select_url, opinion_url):
                raise BrowserRecoveryError("The Scholar opinion changed during copy.")

            self.client.press_key(key="Ctrl+C", window_id=window_id)

            return self._outcome(
                "copied",
                "Copied the Scholar opinion.",
                source_url=opinion_url,
                official_citation=match.official_citation,
            )
        except RecoveryBusyError:
            return self._outcome("failed", "Another Scholar recovery is already running.")
        except (BrowserRecoveryError, ComputerUseMCPError, OSError) as exc:
            return self._outcome("failed", str(exc))
        finally:
            self._return_focus_if_appropriate()
            lock.release()
            if self._owns_client and self.client is not None:
                try:
                    self.client.close()
                except Exception:
                    self.client.terminate()

    def _return_focus_if_appropriate(self) -> None:
        """Return to the initiator without overriding a deliberate switch."""
        if (
            self.client is None
            or self._final_outcome == "blocked"
            or self._origin_window_id is None
            or self._target_window_id is None
            or self._origin_window_id == self._target_window_id
        ):
            return
        try:
            payload = self.client.focused_window()
            focused = payload.get("focused_window")
            if not isinstance(focused, Mapping):
                return
            if focused.get("window_id") != self._target_window_id:
                return
            self.client.activate_window(window_id=self._origin_window_id)
        except (ComputerUseMCPError, OSError):
            # Focus restoration is best-effort and must never change the
            # recovery/import outcome.
            return

    def _revalidate_window(self, window_id: int) -> str:
        windows = self.client.list_windows().get("windows") or []
        for window in windows:
            if window.get("window_id") == window_id:
                return str(window.get("title") or "")
        raise BrowserRecoveryError("The Scholar window disappeared before input.")

    def cancel(self) -> None:
        if self.client is not None:
            self.client.cancel()


def _tree_text(tree: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(node_full_text(node) for node in tree)


_FRONT_MATTER_NODE_LIMIT = 48
_FRONT_MATTER_MAX_CHARS = 600


def front_matter_text(tree: Sequence[Mapping[str, Any]]) -> str:
    """Return bounded front-matter identity text from a scoped page.

    Opinion identity is corroborated from the front matter only — the first
    short run of meaningful nodes (title, reporter line, docket, filing date)
    — so deep opinion body text can never influence, or be exposed by, the
    validation. The text is used for matching only and is never logged.
    """
    parts: list[str] = []
    collected = 0
    for node in tree:
        text = re.sub(r"\s+", " ", node_full_text(node)).strip()
        if not text:
            continue
        parts.append(text)
        collected += len(text)
        if (
            len(parts) >= _FRONT_MATTER_NODE_LIMIT
            or collected >= _FRONT_MATTER_MAX_CHARS
        ):
            break
    return " ".join(parts)


def validated_filing_year(value: str) -> str:
    """Return the value when it is exactly four digits, else an empty string."""
    return value if re.fullmatch(r"\d{4}", value or "") else ""


def opinion_identity_confirmed(
    *,
    expected_citation: str,
    case_name: str,
    docket_number: str,
    filing_year: str,
    observed_title: str,
    page_text: str,
    official_citation: str = "",
) -> bool:
    """Corroborate an opened opinion against the explicit recovery identity.

    With a known citation, both the case name (when supplied) and the exact
    normalized citation must appear — the historical behavior. For
    citation-less recovery the free-form query is never treated as a
    citation: the opened page must instead identify the exact case name, the
    official citation that was discovered in the selected result's primary
    metadata, and the docket number or (when the identity carries no docket)
    the filing year. With no usable identity the match can never be confirmed
    (fail closed).
    """
    """Corroborate an opened opinion against the explicit recovery identity.

    With a known citation, both the case name (when supplied) and the exact
    normalized citation must appear — the historical behavior. For
    citation-less recovery the free-form query is never treated as a
    citation: the bounded front-matter text must identify the exact case
    name, the official citation discovered in the selected result's primary
    metadata, and the docket number when the page exposes it, or the filing
    year otherwise (real Scholar pages often show the year but render the
    docket beyond the bounded front matter). With no usable identity the
    match can never be confirmed (fail closed).
    """
    identity_norm = normalize_match_token(observed_title) + normalize_match_token(page_text)
    raw_identity = f"{observed_title} {page_text}"
    case_norm = normalize_match_token(case_name)
    if case_norm and case_norm not in identity_norm:
        return False
    citation_norm = normalize_match_token(expected_citation)
    if citation_norm:
        return citation_norm in identity_norm
    selected_norm = normalize_match_token(official_citation)
    if not selected_norm or selected_norm not in identity_norm:
        # Citation-less recovery requires the citation selected from the
        # result's primary metadata to be confirmed on the opened page.
        return False
    docket_norm = normalize_match_token(docket_number)
    if docket_norm and docket_norm in identity_norm:
        return True
    year = validated_filing_year(filing_year)
    if year and re.search(rf"(?<![0-9]){year}(?![0-9])", raw_identity):
        return True
    return False


def _year_in_metadata(primary_metadata: str, year: str) -> bool:
    """Whether the validated four-digit year appears in raw metadata text."""
    if not year:
        return False
    return bool(re.search(rf"(?<![0-9]){year}(?![0-9])", primary_metadata))


def find_result_link(
    tree: Sequence[Mapping[str, Any]],
    scoped: Sequence[Mapping[str, Any]],
    expected_citation: str,
    case_name: str,
    *,
    docket_number: str = "",
    filing_year: str = "",
) -> Mapping[str, Any] | None:
    """Backward-compatible wrapper around :func:`find_result_matches`.

    Returns the single qualifying result's semantic link, or ``None`` when no
    result — or more than one — qualifies.
    """
    matches = find_result_matches(
        tree,
        scoped,
        expected_citation,
        case_name,
        docket_number=docket_number,
        filing_year=filing_year,
    )
    return matches[0].link if len(matches) == 1 else None


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
    "find_result_matches",
    "find_scholar_url",
    "is_scholar_case_url",
    "node_full_text",
    "node_name",
    "node_text",
    "normalize_match_token",
    "normalize_recovery_query",
    "request_from_query",
    "result_block_text",
    "run_scholar_recovery",
    "scholar_case_url_matches",
    "scholar_search_url_matches",
    "scope_frame_index",
    "scope_selected_document",
    "validated_filing_year",
    "validate_recovery_result",
]
