from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.launch_request import (
    pop_open_authority_request,
    request_path,
    write_open_authority_request,
)


class LaunchRequestTests(unittest.TestCase):
    def test_write_and_pop_open_authority_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPEN_LAW_LENS_REQUEST_DIR": temp_dir}):
                write_open_authority_request("  Welf. & Inst. Code, § 300  ")

                self.assertEqual(
                    pop_open_authority_request(),
                    "Welf. & Inst. Code, § 300",
                )
                self.assertEqual(pop_open_authority_request(), "")

    def test_pop_ignores_stale_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPEN_LAW_LENS_REQUEST_DIR": temp_dir}):
                path = request_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps({"created_at": time.time() - 999, "text": "300"}),
                    encoding="utf-8",
                )

                self.assertEqual(pop_open_authority_request(), "")


if __name__ == "__main__":
    unittest.main()
