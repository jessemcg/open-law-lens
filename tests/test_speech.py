from __future__ import annotations

import unittest

from open_law_lens.speech import normalize_speech_question_text


class SpeechTests(unittest.TestCase):
    def test_normalize_speech_question_text_trims_and_collapses_whitespace(self) -> None:
        self.assertEqual(
            normalize_speech_question_text("  What is\n\nCalifornia   law?  "),
            "What is California law?",
        )

    def test_normalize_speech_question_text_preserves_punctuation_and_case(self) -> None:
        self.assertEqual(
            normalize_speech_question_text('Did the court say, "detriment"?'),
            'Did the court say, "detriment"?',
        )

    def test_normalize_speech_question_text_empty_input(self) -> None:
        self.assertEqual(normalize_speech_question_text(" \n\t "), "")


if __name__ == "__main__":
    unittest.main()
