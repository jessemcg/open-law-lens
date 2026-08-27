"""Tests for the deterministic Scholar recovery state-machine helpers.

These tests exercise the pure accessibility-tree helpers and the recovery lock
with synthetic trees only; they never contact Scholar or the real desktop.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from open_law_lens.browser_recovery import (
    RecoveryBusyError,
    RecoveryLock,
    ScholarRecoveryRequest,
    detect_barrier,
    find_result_link,
    find_scholar_url,
    is_scholar_case_url,
    normalize_match_token,
    normalize_recovery_query,
    request_from_query,
    scope_frame_index,
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


if __name__ == "__main__":
    unittest.main()
