from __future__ import annotations

import unittest

from open_law_lens.storage import (
    displayed_case_source_provider,
    imported_source_provider,
    source_payload_with_default,
    source_provider_label,
    tagged_lookup_result,
)


class SourceProviderTests(unittest.TestCase):
    def test_imported_provider_uses_source_host(self) -> None:
        self.assertEqual(
            imported_source_provider("https://scholar.google.com/scholar_case?case=1"),
            "google_scholar",
        )
        self.assertEqual(
            imported_source_provider("https://www4.courts.ca.gov/opinions/archive/A1.PDF"),
            "california_courts",
        )
        self.assertEqual(imported_source_provider(""), "manual_import")

    def test_displayed_opinion_provider_takes_precedence_over_cluster(self) -> None:
        provider = displayed_case_source_provider(
            {"source_provider": "courtlistener"},
            [{"source_provider": "california_courts"}],
        )

        self.assertEqual(provider, "california_courts")

    def test_default_provider_preserves_explicit_import_provider(self) -> None:
        payload = source_payload_with_default(
            {"id": "external-1", "source_provider": "google_scholar"},
            "courtlistener",
        )

        self.assertEqual(payload["source_provider"], "google_scholar")

    def test_lookup_tagging_does_not_modify_original_payload(self) -> None:
        original = [{"status": 200, "clusters": [{"id": 42}]}]

        tagged = tagged_lookup_result(original, "courtlistener")

        self.assertNotIn("source_provider", original[0]["clusters"][0])
        self.assertEqual(
            tagged[0]["clusters"][0]["source_provider"],
            "courtlistener",
        )

    def test_provider_labels_include_visible_unknown(self) -> None:
        self.assertEqual(source_provider_label("google_scholar"), "Google Scholar")
        self.assertEqual(source_provider_label("unexpected"), "Unknown source")


if __name__ == "__main__":
    unittest.main()
