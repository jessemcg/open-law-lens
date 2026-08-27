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
    normalize_match_token,
    normalize_recovery_query,
    request_from_query,
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


if __name__ == "__main__":
    unittest.main()
