from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import open_law_lens.scholar_browser
import subprocess
import threading
from open_law_lens.cache import JsonCache
from open_law_lens.import_text import clean_imported_opinion_text
from open_law_lens.library import CaseLibrary
from open_law_lens.scholar_browser import (
    CLIPBOARD_COMMAND_TIMEOUT_SECONDS,
    CLIPBOARD_MAX_BYTES,
    ScholarBrowserError,
    ScholarSourceUrlError,
    build_scholar_case_search_url,
    import_scholar_text,
    read_regular_clipboard,
    require_official_citation,
    validate_scholar_source_url,
)

CADEN_CITATION = "11 Cal.5th 614"
CADEN_CASE_URL = "https://scholar.google.com/scholar_case?case=123456789"

CADEN_OPINION = """\
11 Cal.5th 614 (2021)

In re Caden C., a Person Coming Under the Juvenile Court Law.

OPINION

*625 The juvenile court sustained the petition.

*626 We affirm the orders of the juvenile court.

*627 The order is affirmed.
"""


SEARLES_CITATION = "60 Cal.App.5th 43"
SEARLES_CASE_URL = "https://scholar.google.com/scholar_case?case=1733697791252697933"

SEARLES_OPINION = """\
60 Cal.App.5th 43 (2021)

Searles v. Archangel

OPINION

*45 The mother appeals the termination of her parental rights.

*46 She argues the court erred in finding the boys adoptable.

*47 The juvenile court removed the children from her custody.

*48 We recount the proceedings below.

*49 The petition was sustained.

*50 Reunification services were ordered.

*51 The mother did not reconcile with the children.

*52 The court terminated her parental rights.

*53 The children were adopted by their foster parents.

*54 The mother filed a timely notice of appeal.

*55 We review the findings for substantial evidence.

*56 Substantial evidence supports the findings.

*57 The judgment is affirmed.
"""


class _PipeProc:
    """A subprocess stand-in whose stdout is a real os.pipe.

    Data is fed from a background writer thread so payloads larger than the
    kernel pipe buffer work. ``hold_open=True`` keeps the write end open
    without writing, simulating a stalled clipboard reader that must be
    killed at the read deadline.
    """

    def __init__(self, data: bytes = b"", *, hold_open: bool = False):
        self.returncode = 0
        self.killed = False
        self._write_fd: int | None = None
        read_fd, write_fd = os.pipe()
        if hold_open:
            self._write_fd = write_fd
        elif data:
            threading.Thread(target=self._feed, args=(write_fd, data), daemon=True).start()
        else:
            os.close(write_fd)
        self.stdout = os.fdopen(read_fd, "rb")

    @staticmethod
    def _feed(write_fd: int, data: bytes) -> None:
        try:
            view = memoryview(data)
            while view:
                written = os.write(write_fd, view[:4096])
                view = view[written:]
        except OSError:
            pass
        finally:
            try:
                os.close(write_fd)
            except OSError:
                pass

    def poll(self) -> int | None:
        return None if self._write_fd is not None else self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self._write_fd is not None:
            # The process is still alive: a real bounded wait expires.
            raise subprocess.TimeoutExpired(cmd="wl-paste", timeout=timeout or 0)
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        if self._write_fd is not None:
            try:
                os.close(self._write_fd)
            except OSError:
                pass
            self._write_fd = None


def _client(temp_dir: str) -> SimpleNamespace:
    library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
    library.ensure()
    cache = JsonCache(Path(temp_dir) / "cache")
    cache.ensure()
    return SimpleNamespace(library=library, cache=cache)


class CitationAndUrlTests(unittest.TestCase):
    def test_require_official_citation_accepts_and_normalizes(self) -> None:
        self.assertEqual(require_official_citation("11 Cal.5th 614"), "11 Cal.5th 614")
        self.assertEqual(require_official_citation("  11 Cal.5th 614  "), "11 Cal.5th 614")

    def test_require_official_citation_rejects_unofficial(self) -> None:
        with self.assertRaises(ScholarBrowserError):
            require_official_citation("99 F.3d 123")
        with self.assertRaises(ScholarBrowserError):
            require_official_citation("")
        with self.assertRaises(ScholarBrowserError):
            require_official_citation("Just some words")

    def test_build_scholar_case_search_url(self) -> None:
        url = build_scholar_case_search_url(CADEN_CITATION)
        self.assertIn("scholar.google.com/scholar", url)
        self.assertIn("q=", url)
        self.assertIn("11+Cal.5th+614", url)

    def test_validate_scholar_source_url_rejects_non_scholar(self) -> None:
        for bad in (
            "http://scholar.google.com/scholar_case?case=1",
            "https://example.com/scholar_case?case=1",
            "https://scholar.google.com/other?case=1",
            "https://scholar.google.com/scholar?case=1",
            "https://user:pass@scholar.google.com/scholar_case?case=1",
            "not-a-url",
        ):
            with self.assertRaises(ScholarSourceUrlError, msg=bad):
                validate_scholar_source_url(bad)

    def test_validate_scholar_source_url_accepts_valid(self) -> None:
        self.assertEqual(
            validate_scholar_source_url(CADEN_CASE_URL),
            CADEN_CASE_URL,
        )


class ClipboardTests(unittest.TestCase):
    def test_read_regular_clipboard_returns_text(self) -> None:
        proc = _PipeProc(b"hello scholar\n")
        with patch("open_law_lens.scholar_browser.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "open_law_lens.scholar_browser.subprocess.Popen", return_value=proc
        ) as popen:
            text = read_regular_clipboard()
        self.assertEqual(text, "hello scholar")
        popen.assert_called_once_with(("wl-paste", "--no-newline"), stdout=-1, stderr=-3)
        self.assertFalse(proc.killed)

    def test_read_regular_clipboard_empty_fails_closed(self) -> None:
        proc = _PipeProc(b"   \n")
        with patch("open_law_lens.scholar_browser.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "open_law_lens.scholar_browser.subprocess.Popen", return_value=proc
        ):
            with self.assertRaises(ScholarBrowserError):
                read_regular_clipboard()

    def test_read_regular_clipboard_oversize_fails(self) -> None:
        # Use a small cap so the payload fits the OS pipe buffer while still
        # exceeding the configured limit.
        proc = _PipeProc(b"x" * 2048)
        with patch("open_law_lens.scholar_browser.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "open_law_lens.scholar_browser.subprocess.Popen", return_value=proc
        ):
            with self.assertRaises(ScholarBrowserError):
                read_regular_clipboard(max_bytes=1024)

    def test_read_regular_clipboard_no_utility(self) -> None:
        with patch("open_law_lens.scholar_browser.shutil.which", return_value=None):
            with self.assertRaises(ScholarBrowserError):
                read_regular_clipboard()

    def test_stalled_reader_is_killed_at_the_deadline(self) -> None:
        # A reader that never produces output and never exits must be killed
        # by the bounded streaming read instead of blocking forever before the
        # process timeout applies.
        proc = _PipeProc(hold_open=True)
        started = time.monotonic()
        with patch(
            "open_law_lens.scholar_browser.shutil.which", return_value="/usr/bin/wl-paste"
        ), patch(
            "open_law_lens.scholar_browser.subprocess.Popen", return_value=proc
        ), patch.object(
            open_law_lens.scholar_browser,
            "CLIPBOARD_COMMAND_TIMEOUT_SECONDS",
            0.3,
        ):
            with self.assertRaises(ScholarBrowserError):
                read_regular_clipboard()
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertTrue(proc.killed)

    def test_large_payload_is_read_across_chunks(self) -> None:
        # Output larger than one 64 KiB chunk is fully consumed within the cap.
        payload = (b"scholar opinion line\n") * 9000  # ~180 KiB
        proc = _PipeProc(payload)
        with patch("open_law_lens.scholar_browser.shutil.which", return_value="/usr/bin/wl-paste"), patch(
            "open_law_lens.scholar_browser.subprocess.Popen", return_value=proc
        ):
            text = read_regular_clipboard(max_bytes=CLIPBOARD_MAX_BYTES)
        self.assertEqual(len(text), len(payload.strip()))


class DiscoveredCitationImportTests(unittest.TestCase):
    """The copied opinion must carry the citation selected from the result."""

    def test_exact_citation_import_rejects_mismatched_discovered_citation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation=CADEN_CITATION,
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                    case_name="In re Caden C.",
                    discovered_citation="12 Cal.5th 700",
                )
            # No Library or Research Cache write on a selection mismatch.
            self.assertEqual(client.library.list_case_entries(), [])

    def test_exact_mode_accepts_matching_discovered_citation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=CADEN_CITATION,
                source_url=CADEN_CASE_URL,
                clipboard_text=CADEN_OPINION,
                case_name="In re Caden C.",
                discovered_citation="11 Cal.5th 614",
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, CADEN_CITATION)

    def test_identity_only_import_rejects_mismatched_discovered_citation(
        self,
    ) -> None:
        existing = {
            "id": "8509982",
            "case_name": "In re E.C.",
            "case_name_full": "In re E.C.",
            "date_filed": "2022-11-14",
            "docket": {"docket_number": "F084030"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                    existing_cluster=existing,
                    discovered_citation="86 Cal.App.5th 999",
                )
            self.assertEqual(client.library.list_case_entries(), [])

    def test_identity_only_import_requires_discovered_citation_match(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "In re Caden C.",
            "case_name_full": "In re Caden C.",
            "date_filed": "2021-06-01",
            "docket": {"docket_number": "H049921"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            # The selected result's metadata carried 85 Cal.App.5th 123 but the
            # copied opinion derives 11 Cal.5th 614: reject before persistence.
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                    existing_cluster=existing,
                    discovered_citation="12 Cal.5th 614",
                )
            self.assertEqual(client.library.list_case_entries(), [])


class ImportTests(unittest.TestCase):
    def test_wrong_citation_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="20 Cal.4th 1135",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                )
            self.assertEqual(client.library.list_case_entries(), [])

    def test_search_result_text_without_markers_is_rejected(self) -> None:
        snippet = (
            "11 Cal.5th 614 - In re Caden C. - California Supreme Court\n"
            "Cited by 42 | Related articles | All 3 versions\n"
            "This is a search result snippet, not an opinion body.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation=CADEN_CITATION,
                    source_url=CADEN_CASE_URL,
                    clipboard_text=snippet,
                )
            self.assertEqual(client.library.list_case_entries(), [])

    def test_insufficient_markers_is_rejected(self) -> None:
        text = "11 Cal.5th 614 (2021)\n\nIn re Caden C.\n\nOpinion with a single sentence and no page markers.\n"
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation=CADEN_CITATION,
                    source_url=CADEN_CASE_URL,
                    clipboard_text=text,
                )
            self.assertEqual(client.library.list_case_entries(), [])

    def test_malformed_source_url_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarSourceUrlError):
                import_scholar_text(
                    client,
                    citation=CADEN_CITATION,
                    source_url="https://example.com/opinion",
                    clipboard_text=CADEN_OPINION,
                )
            self.assertEqual(client.library.list_case_entries(), [])

    def test_valid_import_persists_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=CADEN_CITATION,
                source_url=CADEN_CASE_URL,
                clipboard_text=CADEN_OPINION,
                case_name="In re Caden C.",
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, CADEN_CITATION)
            self.assertEqual(result.case_name, "In re Caden C.")
            self.assertTrue(result.cluster_id.startswith("external-"))
            self.assertGreaterEqual(result.marker_count, 3)

            entries = client.library.list_case_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["citation_text"], CADEN_CITATION)
            self.assertIn(result.opinion_id, entries[0]["opinion_ids"])

            opinion = client.library.read_opinion(result.opinion_id)
            self.assertIsNotNone(opinion)
            self.assertEqual(opinion["source_provider"], "google_scholar")
            self.assertEqual(opinion["retrieval_mode"], "browser_clipboard")
            self.assertEqual(opinion["source_url"], CADEN_CASE_URL)

            display = client.library.read_opinion_display(result.opinion_id)
            self.assertIsNotNone(display)
            self.assertGreaterEqual(len(display.page_markers), 3)

    def test_united_states_supreme_court_import_persists_and_round_trips(self) -> None:
        opinion = (
            "499 U.S. 279 (1991)\n\n"
            "Arizona v. Fulminante\n\n"
            "OPINION\n\n"
            "[*280]The judgment of the Court of Appeals is reversed.\n\n"
            "[*281]It is so ordered.\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation="499 U.S. 279",
                source_url=CADEN_CASE_URL,
                clipboard_text=opinion,
                case_name="Arizona v. Fulminante",
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, "499 U.S. 279")
            self.assertEqual(result.case_name, "Arizona v. Fulminante")

            entries = client.library.list_case_entries()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["citation_text"], "499 U.S. 279")

    def test_united_states_reporter_bracketed_markers_are_normalized(self) -> None:
        from open_law_lens.import_text import normalize_external_reporter_markers

        text = "499 U.S. 279 (1991)\n\n[499 U.S. 280]First page.\n\n[499 U.S. 281]Second page."
        normalized = normalize_external_reporter_markers(text, "499 U.S. 279")

        self.assertIn("[*280]", normalized)
        self.assertIn("[*281]", normalized)
        self.assertNotIn("[499 U.S. 280]", normalized)

    def test_existing_cluster_association_preserves_cluster_id(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "In re Caden C.",
            "case_name_full": "In re Caden C.",
            "citations": [{"volume": "278", "reporter": "Cal.Rptr.3d", "page": "872"}],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=CADEN_CITATION,
                source_url=CADEN_CASE_URL,
                clipboard_text=CADEN_OPINION,
                case_name="In re Caden C.",
                existing_cluster=existing,
            )
            self.assertEqual(result.cluster_id, "6240402")
            self.assertTrue(result.eligible)

    def test_identity_only_import_derives_citation_and_corroborates(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "In re Caden C.",
            "case_name_full": "In re Caden C.",
            "date_filed": "2021-06-01",
            "docket": {"docket_number": "H049921"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation="",
                source_url=CADEN_CASE_URL,
                clipboard_text=CADEN_OPINION,
                existing_cluster=existing,
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, CADEN_CITATION)
            self.assertEqual(result.cluster_id, "6240402")

    def test_identity_only_import_requires_existing_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                )

    def test_identity_only_import_stays_attached_to_courtlistener_cluster(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "In re Caden C.",
            "case_name_full": "In re Caden C.",
            "date_filed": "2021-06-01",
            "docket": {"docket_number": "H049921"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation="",
                source_url=CADEN_CASE_URL,
                clipboard_text=CADEN_OPINION,
                case_name="In re Caden C.",
                existing_cluster=existing,
            )
            # The identity-only import stays attached to the CourtListener
            # cluster in both the durable Library and the Research Cache.
            self.assertEqual(result.cluster_id, "6240402")
            entries = client.library.list_case_entries()
            self.assertEqual([entry["cluster_id"] for entry in entries], ["6240402"])
            cached = client.cache.read_cached_cluster("6240402")
            self.assertIsNotNone(cached)
            self.assertEqual(cached["official_citation"], CADEN_CITATION)

    def test_identity_only_import_rejects_wrong_year_and_docket(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "In re Caden C.",
            "case_name_full": "In re Caden C.",
            # The copied opinion names the right case but carries a different
            # year and no matching docket number.
            "date_filed": "1999-01-01",
            "docket": {"docket_number": "S999999"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                    existing_cluster=existing,
                )
            # No Library or Research Cache write on a discriminator mismatch.
            self.assertEqual(client.library.list_case_entries(), [])
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                )

    def test_identity_only_import_rejects_mismatched_identity(self) -> None:
        existing = {
            "id": "6240402",
            "case_name": "People v. Wrong",
            "case_name_full": "People v. Wrong",
            "date_filed": "1999-01-01",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            with self.assertRaises(ScholarBrowserError):
                import_scholar_text(
                    client,
                    citation="",
                    source_url=CADEN_CASE_URL,
                    clipboard_text=CADEN_OPINION,
                    existing_cluster=existing,
                )

    def test_browser_and_account_chrome_is_cleaned(self) -> None:
        noisy = (
            "How cited\n"
            "Save\n"
            "Cite\n"
            "Cited by\n"
            + CADEN_OPINION
        )
        cleaned = clean_imported_opinion_text(noisy)
        self.assertNotIn("How cited", cleaned)
        self.assertNotIn("Cited by", cleaned)
        self.assertNotIn("Save", cleaned)
        self.assertIn(CADEN_CITATION, cleaned)

        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=CADEN_CITATION,
                source_url=CADEN_CASE_URL,
                clipboard_text=noisy,
                case_name="In re Caden C.",
            )
            opinion = client.library.read_opinion(result.opinion_id)
            self.assertIsNotNone(opinion)
            persisted_text = opinion.get("plain_text", "")
            self.assertNotIn("How cited", persisted_text)
            self.assertNotIn("Cited by", persisted_text)
            self.assertNotIn("Save", persisted_text)


class SearlesImportTests(unittest.TestCase):
    """The reported Searles page imports with its 45-57 marker range.

    The live page was the correctly paginated opinion; the import must
    preserve its exact citation, markers 45-57, and Scholar provenance.
    """

    def test_searles_opinion_imports_with_markers_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=SEARLES_CITATION,
                source_url=SEARLES_CASE_URL,
                clipboard_text=SEARLES_OPINION,
                case_name="Searles v. Archangel",
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, SEARLES_CITATION)
            self.assertGreaterEqual(result.marker_count, 13)

            opinion = client.library.read_opinion(result.opinion_id)
            self.assertIsNotNone(opinion)
            self.assertEqual(opinion["source_provider"], "google_scholar")
            self.assertEqual(opinion["retrieval_mode"], "browser_clipboard")
            self.assertEqual(opinion["source_url"], SEARLES_CASE_URL)

            display = client.library.read_opinion_display(result.opinion_id)
            self.assertIsNotNone(display)
            labels = [marker.page_label for marker in display.page_markers]
            self.assertEqual(labels, [str(page) for page in range(45, 58)])

    def test_searles_prose_containing_consent_still_imports(self) -> None:
        # The opinion's "electronic delivery with consent" prose must never
        # affect import: validation checks identity and pagination, not
        # barrier substrings.
        text = SEARLES_OPINION.replace(
            "*46 She argues the court erred in finding the boys adoptable.",
            "*46 The father's electronic delivery with consent of the summons "
            "satisfied due process, and his consent was implied.",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            client = _client(temp_dir)
            result = import_scholar_text(
                client,
                citation=SEARLES_CITATION,
                source_url=SEARLES_CASE_URL,
                clipboard_text=text,
                case_name="Searles v. Archangel",
            )
            self.assertTrue(result.eligible)
            self.assertEqual(result.official_citation, SEARLES_CITATION)


if __name__ == "__main__":
    unittest.main()
