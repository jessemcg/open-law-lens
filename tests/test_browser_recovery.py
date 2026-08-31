"""Tests for the deterministic Scholar recovery state-machine helpers.

These tests exercise the pure accessibility-tree helpers and the recovery lock
with synthetic trees only; they never contact Scholar or the real desktop.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from open_law_lens.browser_recovery import (
    RecoveryBusyError,
    RecoveryLock,
    ScholarRecoveryJob,
    ScholarRecoveryRequest,
    detect_barrier,
    find_result_link,
    find_scholar_url,
    is_scholar_case_url,
    node_name,
    normalize_match_token,
    normalize_recovery_query,
    request_from_query,
    result_block_text,
    scholar_case_url_matches,
    scholar_search_url_matches,
    scope_frame_index,
    scope_selected_document,
    validate_recovery_result,
)


def node(
    index: int,
    role: str,
    name: str | None = None,
    text: Any = None,
    states: list[str] | None = None,
    parent: int | None = None,
) -> dict[str, Any]:
    return {
        "index": index,
        "role": role,
        "name": name,
        "text": text,
        "states": states or [],
        "parent_index": parent,
        "depth": 0,
    }


def scholar_search_tree() -> list[dict[str, Any]]:
    """A synthetic Scholar search-results tree with one corroborated result."""
    return [
        node(0, "application", "Firefox"),
        node(1, "frame", "Google Scholar", states=["showing", "visible"], parent=0),
        node(
            2,
            "combo box",
            name="scholar.google.com/scholar?q=11+Cal.5th+614",
            text={"content": "https://scholar.google.com/scholar?q=11+Cal.5th+614"},
            parent=1,
        ),
        node(3, "panel", "page", states=["showing", "visible"], parent=1),
        node(4, "block", "result-block", parent=3),
        node(5, "heading", "In re Caden C.", parent=4),
        node(
            6,
            "link",
            "In re Caden C.",
            states=["showing", "visible"],
            parent=5,
        ),
        node(7, "static text", "11 Cal.5th 614", parent=4),
    ]


class NormalizeTests(unittest.TestCase):
    def test_normalize_recovery_query(self) -> None:
        self.assertEqual(normalize_recovery_query("  11   Cal.5th  614  "), "11 Cal.5th 614")
        self.assertEqual(normalize_recovery_query(""), "")

    def test_normalize_match_token(self) -> None:
        self.assertEqual(normalize_match_token("11 Cal.5th 614"), "11cal5th614")
        self.assertEqual(normalize_match_token("In re Caden C."), "inrecadenc")


class RequestAndOutcomeTests(unittest.TestCase):
    def test_request_from_query(self) -> None:
        request = request_from_query(
            "  11 Cal.5th 614 ", expected_citation="11 Cal.5th 614", cluster_id="42", case_name="In re C.L."
        )
        self.assertEqual(request.query, "11 Cal.5th 614")
        self.assertEqual(request.expected_citation, "11 Cal.5th 614")
        self.assertEqual(request.cluster_id, "42")

    def test_request_requires_query(self) -> None:
        from open_law_lens.browser_recovery import BrowserRecoveryError

        with self.assertRaises(BrowserRecoveryError):
            request_from_query("   ")

    def test_validate_recovery_result_copied(self) -> None:
        outcome = validate_recovery_result(
            {
                "version": 1,
                "outcome": "copied",
                "query": "11 Cal.5th 614",
                "source_url": "https://scholar.google.com/scholar_case?case=1",
                "message": "found",
            }
        )
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.outcome, "copied")
        self.assertEqual(outcome.source_url, "https://scholar.google.com/scholar_case?case=1")

    def test_validate_recovery_result_rejects_non_scholar(self) -> None:
        self.assertIsNone(
            validate_recovery_result(
                {"version": 1, "outcome": "copied", "query": "q", "source_url": "https://example.com/x", "message": "m"}
            )
        )

    def test_validate_recovery_result_non_copied_ignores_url(self) -> None:
        outcome = validate_recovery_result(
            {"version": 1, "outcome": "blocked", "query": "q", "source_url": "junk", "message": "captcha"}
        )
        assert outcome is not None
        self.assertEqual(outcome.outcome, "blocked")
        self.assertEqual(outcome.source_url, "")

    def test_validate_recovery_result_bad_version_or_outcome(self) -> None:
        self.assertIsNone(validate_recovery_result({"version": 2, "outcome": "copied", "query": "q"}))
        self.assertIsNone(validate_recovery_result({"version": 1, "outcome": "bogus", "query": "q"}))

    def test_is_scholar_case_url(self) -> None:
        self.assertTrue(is_scholar_case_url("https://scholar.google.com/scholar_case?case=1"))
        self.assertFalse(is_scholar_case_url("https://scholar.google.com/scholar?q=x"))
        self.assertFalse(is_scholar_case_url("http://scholar.google.com/scholar_case?case=1"))


class TreeScopeTests(unittest.TestCase):
    def test_scope_frame_matches_title(self) -> None:
        tree = scholar_search_tree()
        self.assertEqual(scope_frame_index(tree, "Google Scholar"), 1)

    def test_scope_frame_prefers_exact_single_match(self) -> None:
        tree = scholar_search_tree()
        tree.append(node(8, "frame", "Gmail - Inbox", parent=0))
        # Only the single "Google Scholar" frame matches.
        self.assertEqual(scope_frame_index(tree, "Google Scholar"), 1)

    def test_scope_frame_no_match(self) -> None:
        self.assertIsNone(scope_frame_index([], "Google Scholar"))

    def test_selected_document_excludes_hidden_tab_content(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", states=["showing", "visible"], parent=0),
            node(2, "internal frame", parent=1),
            node(3, "document web", "Hidden tab", states=["visible"], parent=2),
            node(4, "static text", "Log in to an unrelated site", parent=3),
            node(5, "internal frame", parent=1),
            node(
                6,
                "document web",
                "Google Scholar",
                states=["focused", "showing", "visible"],
                parent=5,
            ),
            node(7, "static text", "In re Y.W. 70 Cal.App.5th 542", parent=6),
        ]

        selected = scope_selected_document(tree, tree[1:])

        self.assertEqual([item["index"] for item in selected], [6, 7])
        self.assertIsNone(detect_barrier(tree, selected))

    def test_find_scholar_url(self) -> None:
        tree = scholar_search_tree()
        url = find_scholar_url(tree, tree[1:])
        self.assertEqual(url, "https://scholar.google.com/scholar?q=11+Cal.5th+614")

    def test_find_scholar_url_rejects_non_scholar(self) -> None:
        tree = [
            node(0, "application", "Browser"),
            node(1, "frame", "Example", parent=0),
            node(2, "combo box", name="example.com", text={"content": "https://example.com/"}, parent=1),
        ]
        self.assertIsNone(find_scholar_url(tree, tree[1:]))

    def test_search_url_match_uses_decoded_query_not_parameter_order(self) -> None:
        self.assertTrue(
            scholar_search_url_matches(
                "https://scholar.google.com/scholar?hl=en&q=55+Cal.App.5th+558&as_sdt=6%2C33",
                "https://scholar.google.com/scholar?as_sdt=6%2C33&q=55%20Cal.App.5th%20558",
            )
        )
        self.assertFalse(
            scholar_search_url_matches(
                "https://scholar.google.com/scholar?q=81+Cal.App.5th+309",
                "https://scholar.google.com/scholar?q=55+Cal.App.5th+558",
            )
        )
        self.assertFalse(
            scholar_search_url_matches(
                "https://scholar.google.com/scholar_case?case=1&q=55+Cal.App.5th+558",
                "https://scholar.google.com/scholar?q=55+Cal.App.5th+558",
            )
        )

    def test_case_url_match_uses_stable_case_identifier(self) -> None:
        self.assertTrue(
            scholar_case_url_matches(
                "https://scholar.google.com/scholar_case?q=x&case=123&hl=en",
                "https://scholar.google.com/scholar_case?case=123&q=y",
            )
        )
        self.assertFalse(
            scholar_case_url_matches(
                "https://scholar.google.com/scholar_case?case=123",
                "https://scholar.google.com/scholar_case?case=456",
            )
        )


class BarrierTests(unittest.TestCase):
    def _tree_with_text(self, text: str) -> list[dict[str, Any]]:
        return [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", parent=0),
            node(2, "static text", text, parent=1),
        ]

    def test_captcha(self) -> None:
        tree = self._tree_with_text("Please complete the CAPTCHA to continue.")
        self.assertEqual(detect_barrier(tree, tree[1:]), "captcha")

    def test_robot_check(self) -> None:
        tree = self._tree_with_text("Confirm you are not a robot.")
        self.assertEqual(detect_barrier(tree, tree[1:]), "not a robot")

    def test_unusual_traffic(self) -> None:
        tree = self._tree_with_text("Our systems detected unusual traffic.")
        self.assertEqual(detect_barrier(tree, tree[1:]), "unusual traffic")

    def test_login(self) -> None:
        tree = self._tree_with_text("Please log in to continue.")
        self.assertEqual(detect_barrier(tree, tree[1:]), "log in")

    def test_consent(self) -> None:
        tree = self._tree_with_text("Choose your country before you continue.")
        self.assertIsNotNone(detect_barrier(tree, tree[1:]))

    def test_no_barrier(self) -> None:
        tree = self._tree_with_text("In re Caden C. 11 Cal.5th 614")
        self.assertIsNone(detect_barrier(tree, tree[1:]))


class ResultLinkTests(unittest.TestCase):
    def test_single_corroborated_result(self) -> None:
        tree = scholar_search_tree()
        scoped = tree[1:]
        link = find_result_link(tree, scoped, "11 Cal.5th 614", "In re Caden C.")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(link["index"], 6)

    def test_wrong_case_name_rejected(self) -> None:
        tree = scholar_search_tree()
        link = find_result_link(tree, tree[1:], "11 Cal.5th 614", "In re Wrong Case")
        self.assertIsNone(link)

    def test_wrong_citation_rejected(self) -> None:
        tree = scholar_search_tree()
        link = find_result_link(tree, tree[1:], "99 Cal.5th 999", "In re Caden C.")
        self.assertIsNone(link)

    def test_citation_only_fallback(self) -> None:
        tree = scholar_search_tree()
        link = find_result_link(tree, tree[1:], "11 Cal.5th 614", "")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(link["index"], 6)

    def test_citation_only_uses_result_metadata_not_other_result_snippets(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", states=["showing", "visible"], parent=0),
            node(2, "panel", "page", parent=1),
            node(3, "section", "results", parent=2),
            node(4, "heading", "In re Y.W.", parent=3),
            node(5, "link", "In re Y.W.", states=["showing", "visible"], parent=4),
            node(6, "section", "70 Cal.App.5th 542, 285 Cal.Rptr.3d 498", parent=3),
            node(7, "section", "The first result's snippet.", parent=3),
            node(8, "heading", "In re Later Case", parent=3),
            node(9, "link", "In re Later Case", states=["showing", "visible"], parent=8),
            node(10, "section", "75 Cal.App.5th 500, 290 Cal.Rptr.3d 1", parent=3),
            node(11, "section", "This snippet cites 70 Cal.App.5th 542.", parent=3),
        ]

        link = find_result_link(tree, tree[1:], "70 Cal.App.5th 542", "")

        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(link["index"], 5)

    def test_duplicate_candidates_rejected(self) -> None:
        tree = scholar_search_tree()
        # Add a second identical corroborated result.
        tree.extend(
            [
                node(8, "block", "result-block-2", parent=3),
                node(9, "heading", "In re Caden C.", parent=8),
                node(10, "link", "In re Caden C.", states=["showing", "visible"], parent=9),
                node(11, "static text", "11 Cal.5th 614", parent=8),
            ]
        )
        link = find_result_link(tree, tree[1:], "11 Cal.5th 614", "In re Caden C.")
        self.assertIsNone(link)

    def test_wrong_frame_link_ignored(self) -> None:
        tree = scholar_search_tree()
        # A second frame holds a tempting link/citation that must not match.
        tree.extend(
            [
                node(8, "frame", "Other Tab", states=["showing", "visible"], parent=0),
                node(9, "block", "other-block", parent=8),
                node(10, "heading", "In re Caden C.", parent=9),
                node(11, "link", "In re Caden C.", states=["showing", "visible"], parent=10),
                node(12, "static text", "11 Cal.5th 614", parent=9),
            ]
        )
        # Scope to the Scholar frame (index 1) and its descendants.
        from open_law_lens.browser_recovery import _descendant_set

        scoped_indexes = _descendant_set(tree, 1)
        scoped = [n for n in tree if n["index"] in scoped_indexes]
        link = find_result_link(tree, scoped, "11 Cal.5th 614", "In re Caden C.")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(link["index"], 6)


class RecoveryLockTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory(prefix="recovery-lock-")
        self.env = {"XDG_RUNTIME_DIR": self._tmp.name}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lock_contention_and_release(self) -> None:
        first = RecoveryLock(environment=self.env)
        self.assertTrue(first.acquire())

        second = RecoveryLock(environment=self.env)
        self.assertFalse(second.acquire())

        with self.assertRaises(RecoveryBusyError):
            with RecoveryLock(environment=self.env):
                pass

        first.release()

        third = RecoveryLock(environment=self.env)
        self.assertTrue(third.acquire())
        third.release()

    def test_lock_context_manager(self) -> None:
        with RecoveryLock(environment=self.env):
            other = RecoveryLock(environment=self.env)
            self.assertFalse(other.acquire())


class _FakeLock:
    """No-op recovery lock so state-machine tests never touch the real dir."""

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass


class _FakeClient:
    """A scripted in-memory Computer Use client for the state machine.

    ``perform_action`` flips ``navigated``, which changes both the window title
    (search -> opinion) and the accessibility tree (search results -> opinion),
    reproducing the real navigation that previously tripped title revalidation.
    """

    SEARCH_TITLE = "Google Scholar"
    OPINION_TITLE = "In re Rylei S. - Google Scholar"

    def __init__(self) -> None:
        self.max_nodes = 1000
        self.max_depth = 14
        self.process = object()  # truthy so run() skips start()
        self.navigated = False
        self.pressed: list[tuple[str, int]] = []
        self.focused_window_id = 3
        self.activated: list[int] = []

    def doctor(self) -> dict[str, Any]:
        return {
            "readiness": {
                "can_register_mcp_tools": True,
                "can_build_accessibility_tree": True,
                "can_query_windows": True,
                "can_send_development_input": True,
                "blockers": [],
            }
        }

    def list_windows(self) -> dict[str, Any]:
        title = self.OPINION_TITLE if self.navigated else self.SEARCH_TITLE
        return {"windows": [{"window_id": 7, "title": title}]}

    def focused_window(self) -> dict[str, Any]:
        return {"focused_window": {"window_id": self.focused_window_id}}

    def activate_window(self, *, window_id: int) -> dict[str, Any]:
        self.activated.append(window_id)
        self.focused_window_id = window_id
        return {"ok": True}

    def get_app_state(
        self, *, window_id: int, max_nodes: int, max_depth: int
    ) -> dict[str, Any]:
        if self.navigated:
            return {
                "accessibility_tree": self._opinion_tree(),
                "window_context": {"title": self.OPINION_TITLE},
            }
        return {
            "accessibility_tree": self._search_tree(),
            "window_context": {"title": self.SEARCH_TITLE},
        }

    def perform_action(self, *, element_index: int) -> dict[str, Any]:
        self.navigated = True
        self.focused_window_id = 7
        return {"ok": True, "element_index": element_index}

    def press_key(self, *, key: str, window_id: int) -> dict[str, Any]:
        self.pressed.append((key, window_id))
        return {"ok": True}

    @staticmethod
    def _search_tree() -> list[dict[str, Any]]:
        return [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", states=["showing", "visible"], parent=0),
            node(
                2,
                "combo box",
                text={"content": "https://scholar.google.com/scholar?q=81+Cal.App.5th+309"},
                parent=1,
            ),
            node(3, "panel", "page", parent=1),
            node(4, "group", "result-block", parent=3),
            node(5, "heading", "In re Rylei S.", parent=4),
            node(6, "link", "In re Rylei S.", states=["showing", "visible"], parent=5),
            node(7, "static text", "81 Cal.App.5th 309", parent=4),
        ]

    @staticmethod
    def _opinion_tree() -> list[dict[str, Any]]:
        return [
            node(0, "application", "Firefox"),
            node(1, "frame", "In re Rylei S. - Google Scholar", states=["showing", "visible"], parent=0),
            node(
                2,
                "combo box",
                text={"content": "https://scholar.google.com/scholar_case?case=123"},
                parent=1,
            ),
            node(3, "panel", "page", parent=1),
            node(4, "static text", "81 Cal.App.5th 309 (2022) OPINION", parent=3),
        ]


class _StaleOpinionContextTitleClient(_FakeClient):
    """Keep app-state title stale after the opinion URL has loaded."""

    def get_app_state(
        self, *, window_id: int, max_nodes: int, max_depth: int
    ) -> dict[str, Any]:
        payload = super().get_app_state(
            window_id=window_id, max_nodes=max_nodes, max_depth=max_depth
        )
        if self.navigated:
            payload["window_context"] = {"title": self.SEARCH_TITLE}
        return payload


class _InitiallyStaleClient(_FakeClient):
    """Expose the previous opinion once before the launched search is ready."""

    def __init__(self) -> None:
        super().__init__()
        self.observations = 0

    def get_app_state(
        self, *, window_id: int, max_nodes: int, max_depth: int
    ) -> dict[str, Any]:
        if not self.navigated:
            self.observations += 1
            if self.observations == 1:
                return {
                    "accessibility_tree": self._opinion_tree(),
                    "window_context": {"title": self.OPINION_TITLE},
                }
        return super().get_app_state(
            window_id=window_id, max_nodes=max_nodes, max_depth=max_depth
        )


class TitleChangeStateMachineTests(unittest.TestCase):
    """Regression: navigating search -> opinion changes the title but must not
    abort the copy step."""

    def test_copy_proceeds_after_title_changes_from_search_to_opinion(self) -> None:
        client = _FakeClient()
        request = ScholarRecoveryRequest(
            query="81 Cal.App.5th 309",
            expected_citation="81 Cal.App.5th 309",
            case_name="In re Rylei S.",
        )
        job = ScholarRecoveryJob(request, client=client)

        with mock.patch(
            "open_law_lens.browser_recovery.RecoveryLock", return_value=_FakeLock()
        ), mock.patch(
            "open_law_lens.browser_recovery.launch_scholar_url",
            return_value=("Firefox", "firefox.desktop"),
        ):
            outcome = job.run()

        self.assertEqual(outcome.outcome, "copied")
        self.assertEqual(outcome.source_url, "https://scholar.google.com/scholar_case?case=123")
        self.assertEqual(client.pressed, [("Ctrl+A", 7), ("Ctrl+C", 7)])
        self.assertEqual(client.activated, [3])

    def test_does_not_restore_focus_after_user_switches_elsewhere(self) -> None:
        client = _FakeClient()
        job = ScholarRecoveryJob(
            ScholarRecoveryRequest(query="81 Cal.App.5th 309"), client=client
        )
        job._origin_window_id = 3
        job._target_window_id = 7
        job._final_outcome = "copied"
        client.focused_window_id = 9

        job._return_focus_if_appropriate()

        self.assertEqual(client.activated, [])

    def test_leaves_blocked_scholar_window_focused(self) -> None:
        client = _FakeClient()
        job = ScholarRecoveryJob(
            ScholarRecoveryRequest(query="81 Cal.App.5th 309"), client=client
        )
        job._origin_window_id = 3
        job._target_window_id = 7
        job._final_outcome = "blocked"
        client.focused_window_id = 7

        job._return_focus_if_appropriate()

        self.assertEqual(client.activated, [])

    def test_copy_uses_case_url_when_opinion_context_title_lags(self) -> None:
        client = _StaleOpinionContextTitleClient()
        request = ScholarRecoveryRequest(
            query="81 Cal.App.5th 309",
            expected_citation="81 Cal.App.5th 309",
            case_name="In re Rylei S.",
        )
        job = ScholarRecoveryJob(request, client=client)

        with mock.patch(
            "open_law_lens.browser_recovery.RecoveryLock", return_value=_FakeLock()
        ), mock.patch(
            "open_law_lens.browser_recovery.launch_scholar_url",
            return_value=("Firefox", "firefox.desktop"),
        ):
            outcome = job.run()

        self.assertEqual(outcome.outcome, "copied")
        self.assertEqual(client.pressed, [("Ctrl+A", 7), ("Ctrl+C", 7)])

    def test_reused_window_waits_past_stale_opinion_for_launched_search(self) -> None:
        client = _InitiallyStaleClient()
        request = ScholarRecoveryRequest(
            query="81 Cal.App.5th 309",
            expected_citation="81 Cal.App.5th 309",
            case_name="In re Rylei S.",
        )
        job = ScholarRecoveryJob(request, client=client)

        with mock.patch(
            "open_law_lens.browser_recovery.RecoveryLock", return_value=_FakeLock()
        ), mock.patch(
            "open_law_lens.browser_recovery.launch_scholar_url",
            return_value=("Firefox", "firefox.desktop"),
        ):
            outcome = job.run()

        self.assertGreaterEqual(client.observations, 2)
        self.assertEqual(outcome.outcome, "copied")
        self.assertEqual(client.pressed, [("Ctrl+A", 7), ("Ctrl+C", 7)])


class _FakeTime:
    """A monotonic clock that advances only when the job sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(float(seconds), 0.0)


class _UnconfirmedResultClient(_FakeClient):
    """The title matches but the result metadata carries another citation."""

    @staticmethod
    def _search_tree() -> list[dict[str, Any]]:
        tree = _FakeClient._search_tree()
        for item in tree:
            if (item.get("role") or "").casefold() == "static text":
                item["name"] = "99 Cal.App.5th 999"
        return tree


class _NoResultStructureClient(_FakeClient):
    """The search page loads but exposes no result blocks at all."""

    @staticmethod
    def _search_tree() -> list[dict[str, Any]]:
        return [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", states=["showing", "visible"], parent=0),
            node(
                2,
                "combo box",
                text={"content": "https://scholar.google.com/scholar?q=81+Cal.App.5th+309"},
                parent=1,
            ),
            node(3, "panel", "page", parent=1),
            node(4, "static text", "Results area is still rendering", parent=3),
        ]


class _BarrierSearchClient(_FakeClient):
    """The search page is an unusual-traffic barrier."""

    @staticmethod
    def _search_tree() -> list[dict[str, Any]]:
        tree = _FakeClient._search_tree()
        tree.append(
            node(
                8,
                "static text",
                "Our systems have detected unusual traffic from your computer network.",
                parent=3,
            )
        )
        return tree


class _CitationlessOpinionClient(_FakeClient):
    """The opened opinion names the case but never shows the citation."""

    @staticmethod
    def _opinion_tree() -> list[dict[str, Any]]:
        tree = _FakeClient._opinion_tree()
        for item in tree:
            if (item.get("role") or "").casefold() == "static text":
                item["name"] = "SOME OPINION"
        return tree


class CorroborationStateMachineTests(unittest.TestCase):
    """No click until title and citation match; no copy without both identities."""

    def _run(self, client: _FakeClient, case_name: str = "In re Rylei S.") -> Any:
        request = ScholarRecoveryRequest(
            query="81 Cal.App.5th 309",
            expected_citation="81 Cal.App.5th 309",
            case_name=case_name,
        )
        job = ScholarRecoveryJob(request, client=client)
        fake_time = _FakeTime()
        with mock.patch("open_law_lens.browser_recovery.time", fake_time), mock.patch(
            "open_law_lens.browser_recovery.RecoveryLock", return_value=_FakeLock()
        ), mock.patch(
            "open_law_lens.browser_recovery.launch_scholar_url",
            return_value=("Firefox", "firefox.desktop"),
        ):
            return job.run()

    def test_no_click_when_result_is_not_corroborated(self) -> None:
        client = _UnconfirmedResultClient()
        outcome = self._run(client)
        self.assertEqual(outcome.outcome, "not_found")
        self.assertEqual(outcome.message, "No single corroborated Scholar result matched.")
        self.assertFalse(client.navigated)
        self.assertEqual(client.pressed, [])

    def test_parse_failure_reason_when_no_result_structure_loads(self) -> None:
        client = _NoResultStructureClient()
        outcome = self._run(client)
        self.assertEqual(outcome.outcome, "not_found")
        self.assertEqual(
            outcome.message,
            "The Scholar page loaded but showed no parseable result structure.",
        )
        self.assertFalse(client.navigated)
        self.assertEqual(client.pressed, [])

    def test_barrier_page_blocks_without_interaction(self) -> None:
        client = _BarrierSearchClient()
        outcome = self._run(client)
        self.assertEqual(outcome.outcome, "blocked")
        self.assertIn("unusual traffic", outcome.message)
        self.assertFalse(client.navigated)
        self.assertEqual(client.pressed, [])

    def test_no_copy_when_opinion_lacks_the_citation(self) -> None:
        client = _CitationlessOpinionClient()
        outcome = self._run(client)
        self.assertEqual(outcome.outcome, "not_found")
        self.assertEqual(outcome.message, "The opened opinion did not match the expected case.")
        self.assertTrue(client.navigated)
        self.assertEqual(client.pressed, [])


def firefox_scholar_search_tree(
    query: str,
    results: list[dict[str, Any]],
    *,
    selected_tab: str = "",
) -> list[dict[str, Any]]:
    """A reduced Firefox-style Scholar search-results tree.

    The topology mirrors the real Firefox AT-SPI capture: one frame holding a
    page-tab list whose selected tab names the results page, a visible
    ``document web`` under a showing internal frame, and a results container
    where each result is a heading (its title link is a child appearing later
    in index order) followed by a sibling reporter-metadata ``section``, an
    ellipsis-prefixed snippet ``section``, and a link container. The search
    box below the results echoes the query.

    ``results`` entries: ``{"title", "metadata", "snippet", "cited_by"}``;
    when ``metadata`` is a tuple it is rendered nested inside a sibling
    container instead of as a direct sibling of the heading.
    """
    tab_title = selected_tab or f"{query} - Google Scholar"
    url = f"https://scholar.google.com/scholar?hl=en&as_sdt=6,33&q={query.replace(' ', '+')}"
    nodes: list[dict[str, Any]] = [
        node(0, "application", "Firefox"),
        node(1, "frame", tab_title, states=["showing", "visible"], parent=0),
        node(2, "tool bar", "Browser tabs", states=["showing", "visible"], parent=1),
        node(3, "page tab list", states=["showing", "visible"], parent=2),
        node(4, "page tab", tab_title, states=["selected", "showing", "visible"], parent=3),
        node(5, "panel", states=["showing", "visible"], parent=1),
        node(
            6,
            "combo box",
            name="Search with DuckDuckGo or enter address",
            text={"content": url},
            states=["showing", "visible"],
            parent=5,
        ),
        node(7, "panel", states=["showing", "visible"], parent=1),
        node(8, "scroll pane", states=["showing", "visible"], parent=7),
        node(9, "internal frame", states=["showing", "visible"], parent=8),
        node(
            10,
            "document web",
            tab_title,
            states=["focused", "showing", "visible"],
            parent=9,
        ),
        node(11, "section", states=["showing", "visible"], parent=10),
    ]
    next_index = 12
    results_root = next_index
    nodes.append(node(next_index, "section", states=["showing", "visible"], parent=11))
    next_index += 1
    headings: list[tuple[int, dict[str, Any]]] = []
    link_containers: list[tuple[int, dict[str, Any]]] = []
    for result in results:
        heading_index = next_index
        nodes.append(
            node(next_index, "heading", result["title"], states=["showing", "visible"], parent=results_root)
        )
        headings.append((heading_index, result))
        next_index += 1
        metadata = result["metadata"]
        if isinstance(metadata, tuple):
            container_index = next_index
            nodes.append(
                node(next_index, "section", text={"content": "\ufeff\ufeff"}, states=["showing", "visible"], parent=results_root)
            )
            next_index += 1
            nodes.append(
                node(next_index, "section", metadata[0], states=["showing", "visible"], parent=container_index)
            )
            next_index += 1
        else:
            nodes.append(
                node(next_index, "section", metadata, states=["showing", "visible"], parent=results_root)
            )
            next_index += 1
        nodes.append(
            node(next_index, "section", result.get("snippet", "…"), states=["showing", "visible"], parent=results_root)
        )
        next_index += 1
        container_index = next_index
        nodes.append(
            node(next_index, "section", text={"content": "\ufeff\ufeff"}, states=["showing", "visible"], parent=results_root)
        )
        link_containers.append((container_index, result))
        next_index += 1
    # Deeper nodes (children) appear after the results, mirroring the capture.
    title_links: list[tuple[int, dict[str, Any]]] = []
    for heading_index, result in headings:
        title_links.append((next_index, result))
        nodes.append(
            node(next_index, "link", result["title"], states=["showing", "visible"], parent=heading_index)
        )
        next_index += 1
    for container_index, result in link_containers:
        cited = str(result.get("cited_by", "Cited by 1"))
        nodes.append(
            node(next_index, "link", cited, states=["showing", "visible"], parent=container_index)
        )
        next_index += 1
    # The search box echoes the query and must never corroborate a result.
    nodes.append(node(next_index, "section", states=["showing", "visible"], parent=11))
    next_index += 1
    nodes.append(
        node(next_index, "entry", f"Search {query}", states=["showing", "visible"], parent=next_index - 1)
    )
    return nodes


def firefox_sh_results() -> list[dict[str, Any]]:
    return [
        {
            "title": "In re SH",
            "metadata": "82 Cal. App. 5th 166, 298 Cal. Rptr. 3d 253 - Cal: Court of Appeal, 1st Appellate Dist., 1st Div. 2022 - Google Scholar",
            "snippet": "… App.4th at p. 1282; contra, Nicole K., supra, 146 Cal.App.4th at p. 785.",
            "cited_by": "Cited by 132",
        },
        {
            "title": "In re Dominick D.",
            "metadata": "82 Cal. App. 5th 560, 298 Cal. Rptr. 3d 897 - Cal: Court of Appeal, 4th Dist. 2022 - Google Scholar",
            "snippet": "… (In re SH (2022) 82 Cal.App.5th 166, 177-180.)",
            "cited_by": "Cited by 147",
        },
    ]


def firefox_tr_results() -> list[dict[str, Any]]:
    return [
        {
            "title": "In re TR",
            "metadata": ("87 Cal. App. 5th 1140, 303 Cal. Rptr. 3d 559 - Cal: Court of Appeal, 4th Dist., 2nd Div. 2023 - Google Scholar",),
            "snippet": "… (In re SH (2022) 82 Cal.App.5th 166, 179.)",
            "cited_by": "Cited by 48",
        },
        {
            "title": "In re Baby Girl M.",
            "metadata": "83 Cal. App. 5th 635, 299 Cal. Rptr. 3d 826 - Cal: Court of Appeal, 2nd Dist. 2022 - Google Scholar",
            "snippet": "… (In re TR (2023) 87 Cal.App.5th 1140, 1148.)",
            "cited_by": "Cited by 64",
        },
    ]


def _scoped_search(tree: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from open_law_lens.browser_recovery import _descendant_set

    frame = scope_frame_index(tree, node_name(tree[1]))
    assert frame is not None
    scoped_frame = [n for n in tree if int(n["index"]) in _descendant_set(tree, frame)]
    return scope_selected_document(tree, scoped_frame)


class FirefoxResultLinkTests(unittest.TestCase):
    """Regressions for the reported In re S.H. / In re T.R. recoveries.

    The fixtures reduce the real Firefox accessibility capture to public case
    identities: Scholar renders ``In re S.H.`` as ``In re SH`` (initials lose
    punctuation) and spaces the reporter as ``Cal. App. 5th``.
    """

    def test_in_re_sh_resolves_exactly_one_link(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        link = find_result_link(tree, scoped, "82 Cal.App.5th 166", "In re S.H.")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(node_name(link), "In re SH")

    def test_in_re_sh_citation_only_resolves_exactly_one_link(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        link = find_result_link(tree, scoped, "82 Cal.App.5th 166", "")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(node_name(link), "In re SH")

    def test_in_re_tr_resolves_exactly_one_link_with_nested_metadata(self) -> None:
        tree = firefox_scholar_search_tree("87 Cal.App.5th 1140", firefox_tr_results())
        scoped = _scoped_search(tree)
        link = find_result_link(tree, scoped, "87 Cal.App.5th 1140", "In re T.R.")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(node_name(link), "In re TR")

    def test_in_re_tr_citation_only_resolves_exactly_one_link(self) -> None:
        tree = firefox_scholar_search_tree("87 Cal.App.5th 1140", firefox_tr_results())
        scoped = _scoped_search(tree)
        link = find_result_link(tree, scoped, "87 Cal.App.5th 1140", "")
        self.assertIsNotNone(link)
        assert link is not None
        self.assertEqual(node_name(link), "In re TR")

    def test_snippet_quoting_target_citation_creates_no_ambiguity(self) -> None:
        # In re Baby Girl M.'s snippet quotes the T.R. citation; only the
        # result whose own metadata carries the citation may match.
        tree = firefox_scholar_search_tree("87 Cal.App.5th 1140", firefox_tr_results())
        scoped = _scoped_search(tree)
        link = find_result_link(tree, scoped, "87 Cal.App.5th 1140", "")
        assert link is not None
        self.assertEqual(node_name(link), "In re TR")

    def test_search_box_echo_never_corroborates_last_result(self) -> None:
        # The entry echoing the query lives outside the result container, so
        # the last result must not become a citation-only candidate through it.
        tree = firefox_scholar_search_tree(
            "82 Cal.App.5th 166",
            [{"title": "Unrelated Case", "metadata": "1 Cal. App. 5th 1 - Google Scholar"}],
        )
        scoped = _scoped_search(tree)
        self.assertIsNone(find_result_link(tree, scoped, "82 Cal.App.5th 166", ""))

    def test_wrong_citation_rejected(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        self.assertIsNone(find_result_link(tree, scoped, "83 Cal.App.5th 635", "In re S.H."))

    def test_wrong_title_rejected(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        self.assertIsNone(find_result_link(tree, scoped, "82 Cal.App.5th 166", "In re Wrong"))

    def test_duplicate_candidates_rejected(self) -> None:
        results = firefox_sh_results() + [dict(firefox_sh_results()[0])]
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", results)
        scoped = _scoped_search(tree)
        self.assertIsNone(find_result_link(tree, scoped, "82 Cal.App.5th 166", "In re S.H."))


class ResultBlockTextTests(unittest.TestCase):
    def _heading(self, tree: list[dict[str, Any]]) -> dict[str, Any]:
        return next(n for n in tree if (n.get("role") or "").casefold() == "heading")

    def test_direct_sibling_metadata_included(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        heading = self._heading(tree)
        text = result_block_text(tree, {int(n["index"]) for n in scoped}, heading)
        self.assertIn(normalize_match_token("82 Cal. App. 5th 166"), normalize_match_token(text))
        self.assertNotIn("Nicole K.", text)

    def test_nested_metadata_included(self) -> None:
        tree = firefox_scholar_search_tree("87 Cal.App.5th 1140", firefox_tr_results())
        scoped = _scoped_search(tree)
        heading = self._heading(tree)
        text = result_block_text(tree, {int(n["index"]) for n in scoped}, heading)
        self.assertIn(normalize_match_token("87 Cal. App. 5th 1140"), normalize_match_token(text))

    def test_ellipsis_snippet_excluded(self) -> None:
        tree = firefox_scholar_search_tree("82 Cal.App.5th 166", firefox_sh_results())
        scoped = _scoped_search(tree)
        heading = self._heading(tree)
        text = result_block_text(tree, {int(n["index"]) for n in scoped}, heading)
        self.assertNotIn("146 Cal.App.4th", text)


class FirefoxBarrierTests(unittest.TestCase):
    """Regressions: opinion prose must not read as a missing page."""

    def test_opinion_prose_containing_no_results_is_not_a_barrier(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "In re SH - Google Scholar", states=["showing", "visible"], parent=0),
            node(2, "document web", "In re SH", states=["focused", "showing", "visible"], parent=1),
            node(
                3,
                "paragraph",
                text={"content": (
                    "He missed a scheduled paternity test and, as of the time of the "
                    "disposition hearing, there were no results indicating whether he "
                    "was the biological father. He is not a party to this appeal."
                )},
                parent=2,
            ),
        ]
        self.assertIsNone(detect_barrier(tree, tree[2:]))

    def test_short_standalone_no_results_notice_is_missing_page(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", parent=0),
            node(2, "static text", "No results found for '82 Cal.App.5th 1660'", parent=1),
        ]
        self.assertEqual(detect_barrier(tree, tree[1:]), "missing page")

    def test_short_did_not_match_any_notice_is_missing_page(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", parent=0),
            node(
                2,
                "static text",
                "Your search - 82 Cal.App.5th 1660 - did not match any articles.",
                parent=1,
            ),
        ]
        self.assertEqual(detect_barrier(tree, tree[1:]), "missing page")

    def test_short_page_not_found_is_missing_page(self) -> None:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "Google Scholar", parent=0),
            node(2, "heading", "Page not found", parent=1),
        ]
        self.assertEqual(detect_barrier(tree, tree[1:]), "missing page")


class FirefoxTabScopingTests(unittest.TestCase):
    """Regressions: the wrong tab's document must never be inspected."""

    @staticmethod
    def _multitab_tree() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "In re TR - Google Scholar", states=["showing", "visible"], parent=0),
            node(2, "tool bar", "Browser tabs", states=["showing", "visible"], parent=1),
            node(3, "page tab list", states=["showing", "visible"], parent=2),
            node(4, "page tab", "In re SH - Google Scholar", states=["showing", "visible"], parent=3),
            node(5, "page tab", "In re TR - Google Scholar", states=["selected", "showing", "visible"], parent=3),
            node(6, "panel", states=["showing", "visible"], parent=1),
            node(
                7,
                "combo box",
                text={"content": "scholar.google.com/scholar_case?case=6771804449855125536"},
                states=["showing", "visible"],
                parent=6,
            ),
            node(8, "scroll pane", states=["visible"], parent=1),
            node(9, "internal frame", states=["visible"], parent=8),
            node(10, "document web", "In re SH - Google Scholar", states=["showing", "visible"], parent=9),
            node(
                11,
                "paragraph",
                text={"content": (
                    "He missed a scheduled paternity test and, as of the time of the "
                    "disposition hearing, there were no results indicating whether he "
                    "was the biological father."
                )},
                parent=10,
            ),
            node(12, "scroll pane", states=["showing", "visible"], parent=1),
            node(13, "internal frame", states=["showing", "visible"], parent=12),
            node(
                14,
                "document web",
                "In re TR - Google Scholar",
                # Deliberately missing focused/showing: the transient state that
                # let the hidden S.H. tab poison the real T.R. recovery.
                states=["visible"],
                parent=13,
            ),
            node(15, "heading", "In re TR, 87 Cal. App. 5th 1140", parent=14),
        ]
        scoped_frame = tree[1:]
        return tree, scoped_frame

    def test_selected_page_tab_beats_stale_showing_document(self) -> None:
        tree, scoped_frame = self._multitab_tree()
        scoped = scope_selected_document(tree, scoped_frame)
        indexes = {int(n["index"]) for n in scoped}
        self.assertIn(14, indexes)
        self.assertIn(15, indexes)
        self.assertNotIn(11, indexes)
        self.assertIsNone(detect_barrier(tree, scoped))

    def test_hidden_tab_prose_cannot_block_visible_opinion(self) -> None:
        tree, scoped_frame = self._multitab_tree()
        scoped = scope_selected_document(tree, scoped_frame)
        # The S.H. paragraph (11) contains "no results" but is out of scope.
        self.assertIsNone(detect_barrier(tree, scoped))

    def test_duplicate_named_tabs_pick_the_showing_tab_not_the_focused_one(self) -> None:
        # Real Firefox regression: launching the same search twice left the
        # old tab's document "focused" (with no showing ancestor) while the
        # new selected tab's document was "showing". The displayed tab must
        # win even though both tabs carry the same title.
        tree = [
            node(0, "application", "Firefox"),
            node(1, "frame", "82 Cal.App.5th 166 - Google Scholar", states=["showing", "visible"], parent=0),
            node(2, "tool bar", "Browser tabs", states=["showing", "visible"], parent=1),
            node(3, "page tab list", states=["showing", "visible"], parent=2),
            node(4, "page tab", "82 Cal.App.5th 166 - Google Scholar", states=["showing", "visible"], parent=3),
            node(
                5,
                "page tab",
                "82 Cal.App.5th 166 - Google Scholar",
                states=["selected", "showing", "visible"],
                parent=3,
            ),
            node(6, "panel", states=["showing", "visible"], parent=1),
            node(
                7,
                "combo box",
                text={"content": "scholar.google.com/scholar?hl=en&as_sdt=6,33&q=82+Cal.App.5th+166"},
                states=["showing", "visible"],
                parent=6,
            ),
            node(8, "scroll pane", states=["visible"], parent=1),
            node(9, "internal frame", states=["visible"], parent=8),
            node(
                10,
                "document web",
                "82 Cal.App.5th 166 - Google Scholar",
                states=["focused", "visible"],
                parent=9,
            ),
            node(11, "section", text={"content": "\ufeff\ufeff"}, states=["visible"], parent=10),
            node(12, "scroll pane", states=["showing", "visible"], parent=1),
            node(13, "internal frame", states=["showing", "visible"], parent=12),
            node(
                14,
                "document web",
                "82 Cal.App.5th 166 - Google Scholar",
                states=["showing", "visible"],
                parent=13,
            ),
            node(15, "section", states=["showing", "visible"], parent=14),
        ]
        scoped = scope_selected_document(tree, tree[1:])
        indexes = {int(n["index"]) for n in scoped}
        self.assertIn(14, indexes)
        self.assertIn(15, indexes)
        self.assertNotIn(11, indexes)


if __name__ == "__main__":
    unittest.main()
