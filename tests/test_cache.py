from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache, citation_cache_key, normalize_citation, resource_id_from_url


class CacheTests(unittest.TestCase):
    def test_normalize_citation_collapses_spaces(self) -> None:
        self.assertEqual(normalize_citation("  576   U.S.   644  "), "576 U.S. 644")

    def test_citation_cache_key_is_case_insensitive(self) -> None:
        self.assertEqual(citation_cache_key("576 U.S. 644"), citation_cache_key("576 u.s. 644"))

    def test_resource_id_from_url(self) -> None:
        self.assertEqual(
            resource_id_from_url("https://www.courtlistener.com/api/rest/v4/opinions/9969234/"),
            "9969234",
        )

    def test_json_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_lookup("576 U.S. 644", [{"status": 200}])
            self.assertEqual(cache.read_lookup("576 U.S. 644"), [{"status": 200}])


if __name__ == "__main__":
    unittest.main()

