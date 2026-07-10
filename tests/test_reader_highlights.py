from __future__ import annotations

import unittest

from open_law_lens.reader_highlights import (
    ReaderHighlight,
    make_reader_highlight,
    resolve_reader_highlight,
    toggle_reader_highlight,
)


class ReaderHighlightTests(unittest.TestCase):
    def test_mapping_validation_and_round_trip(self) -> None:
        highlight = ReaderHighlight.from_mapping(
            {
                "start_offset": 4,
                "end_offset": 9,
                "text": "alpha",
                "prefix": "pre",
                "suffix": "post",
            }
        )

        self.assertIsNotNone(highlight)
        assert highlight is not None
        self.assertEqual(
            ReaderHighlight.from_mapping(highlight.to_mapping()),
            highlight,
        )
        self.assertIsNone(ReaderHighlight.from_mapping({"start_offset": -1}))
        self.assertIsNone(
            ReaderHighlight.from_mapping(
                {"start_offset": 3, "end_offset": 3, "text": "x"}
            )
        )

    def test_resolve_uses_context_when_offsets_change_and_text_repeats(self) -> None:
        original = "First holding. The rule applies. Second holding. The rule applies. End."
        second_start = original.rfind("The rule applies.")
        highlight = make_reader_highlight(
            original,
            second_start,
            second_start + len("The rule applies."),
        )
        assert highlight is not None
        changed = "New introduction. " + original

        resolved = resolve_reader_highlight(changed, highlight)

        self.assertEqual(
            resolved,
            (
                changed.rfind("The rule applies."),
                changed.rfind("The rule applies.") + len("The rule applies."),
            ),
        )

    def test_unresolved_highlight_is_retained_when_adding_another(self) -> None:
        stale = ReaderHighlight(10, 17, "missing")

        updated, action = toggle_reader_highlight("Alpha beta gamma", [stale], 0, 5)

        self.assertEqual(action, "added")
        self.assertIn(stale, updated)
        self.assertEqual(len(updated), 2)

    def test_selection_inside_highlight_removes_whole_highlight(self) -> None:
        text = "Alpha beta gamma."
        highlight = make_reader_highlight(text, 0, 10)
        assert highlight is not None

        updated, action = toggle_reader_highlight(text, [highlight], 2, 7)

        self.assertEqual(action, "removed")
        self.assertEqual(updated, [])

    def test_overlapping_and_contiguous_highlights_merge(self) -> None:
        text = "Alpha beta gamma delta."
        first = make_reader_highlight(text, 0, 5)
        assert first is not None

        updated, action = toggle_reader_highlight(text, [first], 5, 10)

        self.assertEqual(action, "added")
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0].text, "Alpha beta")

    def test_disjoint_highlights_remain_separate(self) -> None:
        text = "Alpha beta gamma."
        first = make_reader_highlight(text, 0, 5)
        assert first is not None

        updated, action = toggle_reader_highlight(text, [first], 11, 16)

        self.assertEqual(action, "added")
        self.assertEqual([entry.text for entry in updated], ["Alpha", "gamma"])


if __name__ == "__main__":
    unittest.main()
