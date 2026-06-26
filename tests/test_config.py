from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.config import AppConfig, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_returns_empty_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load_config(Path(temp_dir) / "config.json").courtlistener_token, "")

    def test_save_and_load_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(courtlistener_token=" token-value "), path)
            self.assertEqual(load_config(path).courtlistener_token, "token-value")


if __name__ == "__main__":
    unittest.main()

