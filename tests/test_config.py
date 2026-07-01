from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.config import (
    AppConfig,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
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
            self.assertEqual(config.reader_font_size_pt, DEFAULT_READER_FONT_SIZE_PT)
            self.assertEqual(config.reader_font_family, DEFAULT_READER_FONT_FAMILY)
            self.assertEqual(config.default_bare_statute_law_code, DEFAULT_BARE_STATUTE_LAW_CODE)

    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    courtlistener_token=" token-value ",
                    concordance_file_path=" /tmp/Concordance_File.sdi ",
                    general_agent_prompt_template=" General {question} ",
                    case_agent_prompt_template=" Case {question} ",
                    reader_font_size_pt=14,
                    reader_font_family="Georgia",
                    default_bare_statute_law_code="FAM",
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.courtlistener_token, "token-value")
            self.assertEqual(config.concordance_file_path, "/tmp/Concordance_File.sdi")
            self.assertEqual(config.general_agent_prompt_template, "General {question}")
            self.assertEqual(config.case_agent_prompt_template, "Case {question}")
            self.assertEqual(config.reader_font_size_pt, 14)
            self.assertEqual(config.reader_font_family, "Georgia")
            self.assertEqual(config.default_bare_statute_law_code, "FAM")

    def test_bare_statute_law_code_falls_back_to_wic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(default_bare_statute_law_code="unsupported"), path)

            self.assertEqual(load_config(path).default_bare_statute_law_code, "WIC")

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
