from __future__ import annotations

from pathlib import Path


DEFAULT_SPEECH_QUESTION_FILE = Path("/dev/shm/speech.txt")


def normalize_speech_question_text(text: str) -> str:
    return " ".join(text.split())
