from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from open_law_lens.agent import (
    CaseTextSource,
    codex_session_log_matches_cwd,
    export_selected_authorities,
    export_selected_cases,
    extract_latest_codex_final_answer_from_jsonl,
    extract_quoted_phrases,
    find_latest_codex_session_log_for_cwd,
    resolve_quote_target,
)
from open_law_lens.library import DisplayText


def _write_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row) + "\n")


class DummyClient:
    def fetch_cluster_opinions(self, _cluster: dict[str, object]) -> list[dict[str, object]]:
        return [{"id": 10, "plain_text": "The juvenile court found active risk today."}]

    def opinion_display(self, opinion: dict[str, object]) -> DisplayText:
        return DisplayText(
            text=str(opinion["plain_text"]),
            source_field="plain_text",
            page_markers=[],
        )


class AgentTests(unittest.TestCase):
    def test_extract_latest_codex_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rollout.jsonl"
            _write_jsonl(
                path,
                [
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "phase": "commentary",
                            "content": [{"type": "output_text", "text": "working"}],
                        },
                    },
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "phase": "final_answer",
                            "content": [{"type": "output_text", "text": "final answer"}],
                        },
                    },
                ],
            )
            self.assertEqual(extract_latest_codex_final_answer_from_jsonl(path), "final answer")

    def test_find_latest_codex_session_log_for_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "sessions"
            workspace = Path(temp_dir) / "workspace"
            old_log = root / "2026" / "06" / "27" / "rollout-old.jsonl"
            new_log = root / "2026" / "06" / "27" / "rollout-new.jsonl"
            other_log = root / "2026" / "06" / "27" / "rollout-other.jsonl"
            _write_jsonl(old_log, [{"type": "session_meta", "payload": {"cwd": str(workspace)}}])
            _write_jsonl(new_log, [{"type": "session_meta", "payload": {"cwd": str(workspace)}}])
            _write_jsonl(other_log, [{"type": "session_meta", "payload": {"cwd": str(Path(temp_dir) / "other")}}])
            os.utime(old_log, (1, 1))
            os.utime(new_log, (3, 3))
            os.utime(other_log, (2, 2))
            self.assertTrue(codex_session_log_matches_cwd(new_log, workspace))
            self.assertEqual(find_latest_codex_session_log_for_cwd(root, workspace), new_log)

    def test_extract_quoted_phrases_limits_to_two_to_five_words(self) -> None:
        spans = extract_quoted_phrases('Use "active risk today" and skip "one" and "too many words in this quote".')
        self.assertEqual([span[2] for span in spans], ["active risk today"])

    def test_resolve_quote_target_uses_first_exact_source_match(self) -> None:
        sources = [
            CaseTextSource(
                cluster_id="42",
                opinion_id="10",
                title="Example",
                citation="1 Cal. 2",
                text_path="/tmp/source.txt",
                text="The juvenile court found active risk today.",
            )
        ]
        target = resolve_quote_target("active risk today", sources)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.cluster_id, "42")
        self.assertEqual(target.offset, 25)

    def test_export_selected_cases_writes_manifest_and_text_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = export_selected_cases(
                DummyClient(),
                [
                    {
                        "id": 42,
                        "case_name": "Example v. State",
                        "citations": [{"volume": "1", "reporter": "Cal.", "page": "2"}],
                    }
                ],
                Path(temp_dir) / "selected_cases",
            )
            self.assertEqual(export.case_count, 1)
            self.assertEqual(len(export.text_sources), 1)
            manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["cases"][0]["cluster_id"], "42")
            self.assertIn("active risk today", Path(export.text_sources[0].text_path).read_text())

    def test_export_selected_authorities_writes_statutes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = export_selected_authorities(
                DummyClient(),
                [],
                [
                    {
                        "statute_id": "WIC:300",
                        "title": "Welfare and Institutions Code section 300",
                        "citation": "Welf. & Inst. Code, § 300",
                        "source_url": "https://example.test",
                        "text": "300. A child comes within jurisdiction.",
                    }
                ],
                Path(temp_dir) / "selected_authorities",
            )

            self.assertEqual(export.case_count, 0)
            self.assertEqual(export.statute_count, 1)
            self.assertEqual(export.authority_count, 1)
            manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["statutes"][0]["statute_id"], "WIC:300")
            self.assertIn("300. A child", Path(export.text_sources[0].text_path).read_text())


if __name__ == "__main__":
    unittest.main()
