from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from open_law_lens.cache import JsonCache
from open_law_lens.import_text import normalize_external_reporter_markers
from open_law_lens.library import CaseLibrary
from open_law_lens.official_copy import resolve_with_tavily
from open_law_lens.tavily import TavilyResult


class OfficialCopyTests(unittest.TestCase):
    def test_expected_citation_marker_normalization_is_scoped(self) -> None:
        source = (
            "[20 Cal.4th 1140] one\n"
            "\\[20 Cal.4th 1141\\] two\n"
            "**[20 Cal.4th 1142]** three\n"
            "[21 Cal.4th 1143] parallel"
        )
        normalized = normalize_external_reporter_markers(source, "20 Cal.4th 1135")
        self.assertIn("[*1140]", normalized)
        self.assertIn("[*1141]", normalized)
        self.assertIn("[*1142]", normalized)
        self.assertIn("[21 Cal.4th 1143]", normalized)

    def test_unpublished_case_skips_tavily(self) -> None:
        client = MagicMock()
        tavily = MagicMock()
        result = resolve_with_tavily(
            client,
            {"id": "1", "precedential_status": "Unpublished"},
            tavily_client=tavily,
        )
        self.assertEqual(result.category, "unpublished")
        tavily.search.assert_not_called()

    def test_validation_outcome_is_cached_and_refresh_bypasses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = SimpleNamespace(library=library, cache=JsonCache(Path(temp_dir) / "cache"))
            client.cache.ensure()
            cluster = {
                "id": "42",
                "case_name": "Example v. State",
                "precedential_status": "Published",
                "citations": [{"volume": "20", "reporter": "Cal.4th", "page": "1135"}],
            }
            tavily = MagicMock()
            tavily.search.return_value = [TavilyResult("https://example.com/case", raw_content="short snippet")]
            with patch("open_law_lens.official_copy.extract_webpage_text", side_effect=RuntimeError("blocked")), patch(
                "open_law_lens.official_copy._validate_public_destination",
                return_value="https://example.com/case",
            ):
                first = resolve_with_tavily(client, cluster, tavily_client=tavily)
                second = resolve_with_tavily(client, cluster, tavily_client=tavily)
                third = resolve_with_tavily(client, cluster, refresh=True, tavily_client=tavily)
            self.assertEqual(first.category, "validation")
            self.assertTrue(second.cached)
            self.assertFalse(third.cached)
            self.assertEqual(tavily.search.call_count, 2)


if __name__ == "__main__":
    unittest.main()
