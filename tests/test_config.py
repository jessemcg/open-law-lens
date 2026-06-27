from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_returns_empty_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(Path(temp_dir) / "config.json")
            self.assertEqual(config.courtlistener_token, "")
            self.assertEqual(config.concordance_file_path, "")

    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    courtlistener_token=" token-value ",
                    concordance_file_path=" /tmp/Concordance_File.sdi ",
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.courtlistener_token, "token-value")
            self.assertEqual(config.concordance_file_path, "/tmp/Concordance_File.sdi")

    def test_environment_concordance_path_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(concordance_file_path="/saved/path.sdi"), path)
            with patch.dict(os.environ, {"OPEN_LAW_LENS_CONCORDANCE_FILE": "/env/path.sdi"}):
                self.assertEqual(load_config(path).concordance_file_path, "/env/path.sdi")


if __name__ == "__main__":
    unittest.main()
