from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.config import (
    AGENT_PERMISSION_MODE_FULL_ACCESS,
    AppConfig,
    DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_APPEAL_ISSUE_PRESETS,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_AGENT_PERMISSION_MODE,
    DEFAULT_BARE_STATUTE_LAW_CODE,
    DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    DEFAULT_READER_FONT_FAMILY,
    DEFAULT_READER_FONT_SIZE_PT,
    load_config,
    save_config,
)


class ConfigTests(unittest.TestCase):
    def test_missing_config_returns_empty_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(Path(temp_dir) / "config.json")
            self.assertEqual(config.courtlistener_token, "")
            self.assertEqual(config.concordance_file_path, "")
            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
            self.assertEqual(
                config.appeal_issue_agent_prompt_template,
                DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            )
            self.assertEqual(config.appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))
            self.assertEqual(config.reader_font_size_pt, DEFAULT_READER_FONT_SIZE_PT)
            self.assertEqual(config.reader_font_family, DEFAULT_READER_FONT_FAMILY)
            self.assertEqual(config.default_bare_statute_law_code, DEFAULT_BARE_STATUTE_LAW_CODE)
            self.assertEqual(config.agent_permission_mode, DEFAULT_AGENT_PERMISSION_MODE)

    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    courtlistener_token=" token-value ",
                    concordance_file_path=" /tmp/Concordance_File.sdi ",
                    general_agent_prompt_template=" General {question} ",
                    case_agent_prompt_template=" Case {question} ",
                    appeal_issue_agent_prompt_template=" Appeal {issue} ",
                    appeal_issue_presets=[" Issue One ", "Issue Two", "Issue One"],
                    reader_font_size_pt=14,
                    reader_font_family="Georgia",
                    default_bare_statute_law_code="FAM",
                    agent_permission_mode=AGENT_PERMISSION_MODE_FULL_ACCESS,
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.courtlistener_token, "token-value")
            self.assertEqual(config.concordance_file_path, "/tmp/Concordance_File.sdi")
            self.assertEqual(config.general_agent_prompt_template, "General {question}")
            self.assertEqual(config.case_agent_prompt_template, "Case {question}")
            self.assertEqual(config.appeal_issue_agent_prompt_template, "Appeal {issue}")
            self.assertEqual(config.appeal_issue_presets, ["Issue One", "Issue Two"])
            self.assertEqual(config.reader_font_size_pt, 14)
            self.assertEqual(config.reader_font_family, "Georgia")
            self.assertEqual(config.default_bare_statute_law_code, "FAM")
            self.assertEqual(config.agent_permission_mode, AGENT_PERMISSION_MODE_FULL_ACCESS)

    def test_legacy_general_prompt_migrates_to_new_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "general_agent_prompt_template": (
                            "You are the Open Law Lens General California Law Agent.\n\n"
                            "Answer only legal questions about California law. "
                            "Use the CourtListener "
                            "MCP server only for legal authority and legal research. "
                            "Do not use local Open Law Lens cache files, the durable "
                            "library database, local project files, web browsing, or "
                            "shell commands as legal authority.\n\n"
                            "Confine research to California state law unless the user's "
                            "question explicitly requires federal law. Prefer published "
                            "California Supreme Court and California Court of Appeal "
                            "authority when available.\n\n"
                            "Question:\n{question}"
                        )
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertNotIn("CourtListener " + "MCP server only", config.general_agent_prompt_template)

    def test_custom_general_prompt_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(general_agent_prompt_template="Custom {question}"), path)

            self.assertEqual(load_config(path).general_agent_prompt_template, "Custom {question}")

    def test_legacy_appeal_prompt_migrates_to_new_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_agent_prompt_template": (
                            "You are the Open Law Lens Appeal Issue Assessment Agent.\n\n"
                            "Assess one possible California appellate issue against the user's "
                            "fact pattern. Use Open Law Lens CLI commands tied directly to "
                            "CourtListener APIs for legal authority and legal research.\n\n"
                            "Read the extracted fact-pattern text first:\n"
                            "{fact_pattern_path}\n\n"
                            "Original fact-pattern file:\n"
                            "{fact_pattern_source_path}\n\n"
                            "Issue to assess:\n"
                            "{issue}\n\n"
                            "Research California law with Open Law Lens CLI commands. For "
                            "case-law discovery, start with `uv run open-law-lens case-search "
                            "\"<query>\"`. Treat search results as leads only. Extract the "
                            "most relevant candidate opinions with `uv run open-law-lens "
                            "extract-case --cluster-id <cluster_id>` before relying on a case. "
                            "Use `uv run open-law-lens extract-statute \"<citation>\"` and "
                            "`uv run open-law-lens extract-rule \"<citation>\"` when statutes "
                            "or rules matter.\n\n"
                            "Confine research to California state law unless the issue "
                            "explicitly requires federal law. Prefer published California "
                            "Supreme Court and California Court of Appeal authority. Use "
                            "unpublished cases only for context, not as controlling authority.\n\n"
                            "Analyze preservation, standard of review, factual support, "
                            "governing law, prejudice, likely respondent arguments, and "
                            "missing record facts that could change the assessment.\n\n"
                            "End with a rating line exactly in this form:\n"
                            "Rating: Strong, Medium, Weak, or Frivolous\n\n"
                            "Use Frivolous only when the issue is clearly foreclosed or lacks "
                            "any nonfrivolous factual or legal basis. Otherwise choose Strong, "
                            "Medium, or Weak."
                        )
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(
                config.appeal_issue_agent_prompt_template,
                DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            )
            self.assertIn("Record citation format", config.appeal_issue_agent_prompt_template)

    def test_custom_appeal_prompt_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(appeal_issue_agent_prompt_template="Custom appeal {issue}"),
                path,
            )

            self.assertEqual(
                load_config(path).appeal_issue_agent_prompt_template,
                "Custom appeal {issue}",
            )

    def test_bare_statute_law_code_falls_back_to_wic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(default_bare_statute_law_code="unsupported"), path)

            self.assertEqual(load_config(path).default_bare_statute_law_code, "WIC")

    def test_agent_permission_mode_falls_back_to_sandboxed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(agent_permission_mode="unsupported"), path)

            self.assertEqual(load_config(path).agent_permission_mode, DEFAULT_AGENT_PERMISSION_MODE)

    def test_appeal_issue_presets_fall_back_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"appeal_issue_presets": ["", "   "]}),
                encoding="utf-8",
            )

            self.assertEqual(load_config(path).appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))

    def test_reader_font_settings_are_coerced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    reader_font_size_pt=100,
                    reader_font_family="Century Schoolbook",
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.reader_font_size_pt, 48)
            self.assertEqual(config.reader_font_family, "Century Schoolbook")

    def test_century_schoolbook_reader_font_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(reader_font_family="Century Schoolbook"), path)

            self.assertEqual(load_config(path).reader_font_family, "Century Schoolbook")

    def test_environment_concordance_path_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(concordance_file_path="/saved/path.sdi"), path)
            with patch.dict(os.environ, {"OPEN_LAW_LENS_CONCORDANCE_FILE": "/env/path.sdi"}):
                self.assertEqual(load_config(path).concordance_file_path, "/env/path.sdi")


if __name__ == "__main__":
    unittest.main()
