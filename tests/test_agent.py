from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from open_law_lens.agent import (
    CaseTextSource,
    pi_session_log_matches_cwd,
    export_selected_authorities,
    export_selected_cases,
    extract_latest_pi_final_answer_from_jsonl,
    extract_quoted_phrases,
    find_latest_pi_session_log_for_cwd,
    quote_match_spans,
    resolve_quote_target,
    resolved_agent_quote_spans,
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

    def reader_opinions(
        self,
        opinions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return opinions

    def opinion_display(self, opinion: dict[str, object]) -> DisplayText:
        return DisplayText(
            text=str(opinion["plain_text"]),
            source_field="plain_text",
            page_markers=[],
        )


class AgentTests(unittest.TestCase):
    def test_extract_latest_pi_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rollout.jsonl"
            _write_jsonl(
                path,
                [
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "stopReason": "toolUse",
                            "content": [{"type": "text", "text": "working"}],
                        },
                    },
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "stopReason": "stop",
                            "content": [{"type": "text", "text": "final answer"}],
                        },
                    },
                ],
            )
            self.assertEqual(extract_latest_pi_final_answer_from_jsonl(path), "final answer")

    def test_find_latest_pi_session_log_for_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "sessions"
            workspace = Path(temp_dir) / "workspace"
            old_log = root / "old.jsonl"
            new_log = root / "new.jsonl"
            other_log = root / "other.jsonl"
            _write_jsonl(old_log, [{"type": "session", "cwd": str(workspace)}])
            _write_jsonl(new_log, [{"type": "session", "cwd": str(workspace)}])
            _write_jsonl(other_log, [{"type": "session", "cwd": str(Path(temp_dir) / "other")}])
            os.utime(old_log, (1, 1))
            os.utime(new_log, (3, 3))
            os.utime(other_log, (2, 2))
            self.assertTrue(pi_session_log_matches_cwd(new_log, workspace))
            self.assertEqual(find_latest_pi_session_log_for_cwd(root, workspace), new_log)

    def test_extract_quoted_phrases_limits_to_two_to_ten_words(self) -> None:
        spans = extract_quoted_phrases(
            'Use "active risk today" and "reasonable, credible, and of solid value"; '
            'skip "one" and "this quotation contains far too many words to remain a short direct quotation".'
        )
        self.assertEqual(
            [span[2] for span in spans],
            ["active risk today", "reasonable, credible, and of solid value"],
        )

    def test_resolve_quote_target_uses_first_canonical_source_match(self) -> None:
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

    def test_quote_match_spans_tolerate_observed_display_differences(self) -> None:
        source = (
            'Mother\'s "emotions [were] out of control." She "couldn\'t relax" '
            'and was being "very negative" because of her condition.'
        )

        phrases = (
            "emotions [were] out of control,",
            "couldn’t relax,",
            "being very negative.",
        )

        matches = [quote_match_spans(source, phrase) for phrase in phrases]
        self.assertTrue(all(match for match in matches))
        self.assertEqual(
            [source[start:end] for (start, end), in matches],
            [
                "emotions [were] out of control",
                "couldn't relax",
                'being "very negative',
            ],
        )

    def test_quote_match_spans_ignore_reporter_page_marker(self) -> None:
        source = "The court found active [*1214] risk today."
        spans = quote_match_spans(source, "active risk today")
        self.assertEqual(len(spans), 1)
        self.assertEqual(source[slice(*spans[0])], "active [*1214] risk today")

    def test_resolved_quote_uses_following_citation_to_disambiguate(self) -> None:
        sources = [
            CaseTextSource(
                cluster_id="1",
                opinion_id="10",
                title="First v. State",
                citation="1 Cal.App.5th 10",
                text_path="/tmp/first.txt",
                text="The court found active risk today.",
            ),
            CaseTextSource(
                cluster_id="2",
                opinion_id="20",
                title="Second v. State",
                citation="2 Cal.App.5th 20",
                text_path="/tmp/second.txt",
                text="The court also found active risk today.",
            ),
        ]
        answer = 'The court found “active risk today.” (Second v. State (2024) 2 Cal.App.5th 20.)'

        spans = resolved_agent_quote_spans(answer, sources)

        self.assertEqual(len(spans), 1)
        self.assertIsNotNone(spans[0].target)
        assert spans[0].target is not None
        self.assertEqual(spans[0].target.cluster_id, "2")

    def test_resolved_quote_uses_prior_brief_markdown_link_hint(self) -> None:
        brief_id = "a" * 64
        sources = [
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title="B353817_AOB_Joseph_A",
                citation="2026-07-09",
                text_path="/tmp/brief.odt",
                text="The court found the inquiry was inadequate.",
                authority_type="prior_brief",
                prior_brief_id=brief_id,
            )
        ]
        answer = (
            'The argument used "inquiry was inadequate" in '
            f"[B353817_AOB_Joseph_A](open-law-lens://prior-brief/{brief_id})."
        )

        spans = resolved_agent_quote_spans(answer, sources)

        self.assertEqual(spans[0].target.prior_brief_id, brief_id)

    def test_resolved_quote_uses_nearby_plain_prior_brief_title_across_paragraphs(self) -> None:
        wanted_id = "a" * 64
        other_id = "b" * 64
        phrase = "reasonable, credible, and of solid value"
        sources = [
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title="B348009_RB_Breana_R",
                citation="2026-06-08",
                text_path="/tmp/wanted.odt",
                text=f"The evidence was {phrase}.",
                authority_type="prior_brief",
                prior_brief_id=wanted_id,
            ),
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title="Older_AOB",
                citation="2025-01-01",
                text_path="/tmp/other.odt",
                text=f"Evidence must be {phrase}.",
                authority_type="prior_brief",
                prior_brief_id=other_id,
            ),
        ]
        answer = (
            "The latest is B348009_RB_Breana_R, dated June 8, 2026.\n\n"
            f'It described the test as asking whether evidence was "{phrase}."'
        )

        spans = resolved_agent_quote_spans(answer, sources)

        self.assertEqual(spans[0].target.prior_brief_id, wanted_id)

    def test_resolved_quote_leaves_cross_authority_ambiguity_unlinked(self) -> None:
        sources = [
            CaseTextSource("1", "10", "First", "1 Cal.App.5th 10", "/tmp/1", "active risk today"),
            CaseTextSource("2", "20", "Second", "2 Cal.App.5th 20", "/tmp/2", "active risk today"),
        ]

        spans = resolved_agent_quote_spans('Both discuss “active risk today.”', sources)

        self.assertEqual(len(spans), 1)
        self.assertIsNone(spans[0].target)

    def test_resolved_quote_uses_statute_citation_hint(self) -> None:
        sources = [
            CaseTextSource(
                "1",
                "10",
                "Example",
                "1 Cal.App.5th 10",
                "/tmp/case",
                "The best interests of child control.",
            ),
            CaseTextSource(
                "",
                "",
                "Welfare and Institutions Code section 300",
                "Welf. & Inst. Code, § 300",
                "/tmp/statute",
                "The best interests of child control.",
                authority_type="statute",
                statute_id="WIC:300",
            ),
        ]
        answer = (
            'The standard protects “best interests of child.” '
            '(Welf. & Inst. Code, § 300.)'
        )

        spans = resolved_agent_quote_spans(answer, sources)

        self.assertIsNotNone(spans[0].target)
        assert spans[0].target is not None
        self.assertEqual(spans[0].target.statute_id, "WIC:300")

    def test_resolved_quote_ignores_saved_agent_answer_source(self) -> None:
        source = CaseTextSource(
            cluster_id="",
            opinion_id="",
            title="Prior answer",
            citation="Saved agent answer",
            text_path="/tmp/answer.txt",
            text="active risk today",
            authority_type="agent_answer",
            agent_answer_id="abc",
        )

        spans = resolved_agent_quote_spans('Prior analysis said “active risk today.”', [source])

        self.assertEqual(len(spans), 1)
        self.assertIsNone(spans[0].target)

    def test_resolve_quote_target_preserves_statute_and_rule_identity(self) -> None:
        statute = CaseTextSource(
            "",
            "",
            "Welfare and Institutions Code section 300",
            "Welf. & Inst. Code, § 300",
            "/tmp/statute",
            "A child comes within jurisdiction.",
            authority_type="statute",
            statute_id="WIC:300",
        )
        rule = CaseTextSource(
            "",
            "",
            "California Rules of Court, rule 8.11",
            "Cal. Rules of Court, rule 8.11",
            "/tmp/rule",
            "This rule governs computing time.",
            authority_type="rule",
            rule_id="CRC:8.11",
        )

        statute_target = resolve_quote_target("comes within jurisdiction", [statute, rule])
        rule_target = resolve_quote_target("governs computing time", [statute, rule])

        self.assertIsNotNone(statute_target)
        self.assertIsNotNone(rule_target)
        assert statute_target is not None and rule_target is not None
        self.assertEqual(
            (statute_target.authority_type, statute_target.statute_id),
            ("statute", "WIC:300"),
        )
        self.assertEqual(
            (rule_target.authority_type, rule_target.rule_id),
            ("rule", "CRC:8.11"),
        )

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
                [],
                Path(temp_dir) / "selected_authorities",
            )

            self.assertEqual(export.case_count, 0)
            self.assertEqual(export.statute_count, 1)
            self.assertEqual(export.authority_count, 1)
            manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["statutes"][0]["statute_id"], "WIC:300")
            self.assertIn("300. A child", Path(export.text_sources[0].text_path).read_text())

    def test_export_selected_authorities_writes_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = export_selected_authorities(
                DummyClient(),
                [],
                [],
                [
                    {
                        "rule_id": "CRC:8.11",
                        "title": "California Rules of Court, rule 8.11",
                        "citation": "Cal. Rules of Court, rule 8.11",
                        "source_url": "https://example.test",
                        "text": "Rule 8.11. Scope.",
                    }
                ],
                Path(temp_dir) / "selected_authorities",
            )

            self.assertEqual(export.case_count, 0)
            self.assertEqual(export.rule_count, 1)
            self.assertEqual(export.authority_count, 1)
            manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["rules"][0]["rule_id"], "CRC:8.11")
            self.assertIn("Rule 8.11.", Path(export.text_sources[0].text_path).read_text())

    def test_export_selected_authorities_writes_agent_answers_as_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export = export_selected_authorities(
                DummyClient(),
                [],
                [],
                [],
                Path(temp_dir) / "selected_authorities",
                [
                    {
                        "answer_id": "abc123",
                        "title": "Removal assessment",
                        "mode": "appeal",
                        "text": "The removal issue is strong.",
                        "saved_at": "2026-07-06T12:00:00+00:00",
                    }
                ],
            )

            self.assertEqual(export.agent_answer_count, 1)
            self.assertEqual(export.authority_count, 1)
            self.assertEqual(export.text_sources[0].authority_type, "agent_answer")
            self.assertEqual(export.text_sources[0].agent_answer_id, "abc123")
            manifest = json.loads(export.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["agent_answers"][0]["answer_id"], "abc123")
            self.assertEqual(manifest["agent_answers"][0]["source_type"], "saved_agent_answer")
            self.assertIn("not legal authority", manifest["instructions"])
            answer_text = Path(export.text_sources[0].text_path).read_text(encoding="utf-8")
            self.assertIn("Source type: saved agent answer, not legal authority", answer_text)
            self.assertIn("The removal issue is strong.", answer_text)


if __name__ == "__main__":
    unittest.main()
