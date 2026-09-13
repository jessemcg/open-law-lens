"""Network-free regression acceptance; never opens real config/cache/library."""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from open_law_lens.authority_passages import build_authority_passages, _normalize_query
from open_law_lens.authority_resolver import AuthorityResult
from open_law_lens.cache import JsonCache
from open_law_lens.client import CourtListenerClient
from open_law_lens.cli import main
from open_law_lens.library import CaseLibrary
from open_law_lens.statutes import (
    CODE_LABELS, LegInfoError, StatuteCitation, cited_statute_links,
    extract_leginfo_text, parse_statute_citation,
)


def authority(text, **kwargs):
    return AuthorityResult(ok=True, authority_type="case", input="28 Cal.4th 56",
                           citation="28 Cal.4th 56", text=text,
                           official_pagination=kwargs.get("official_pagination", True))


class StatuteIdentityTests(unittest.TestCase):
    def test_codes_and_links_share_aliases(self):
        for code, label in CODE_LABELS.items():
            for prefix in (code, label):
                with self.subTest(prefix=prefix):
                    self.assertEqual(parse_statute_citation(prefix + " § 527.6").law_code, code)
        for prefix in ("Cal. Civ. Proc. Code", "Civ. Proc. Code", "Code Civ. Proc.",
                       "California Code of Civil Procedure"):
            citation = prefix + ", § 527.6"
            self.assertEqual(parse_statute_citation(citation).law_code, "CCP")
            self.assertEqual(cited_statute_links(citation)[0].lookup_text, citation)
        for bare in ("§ 300", "section 300", "sec. 300", "sections 300, subd. (b)(1)"):
            self.assertEqual(parse_statute_citation(bare).law_code, "WIC")

    def test_unsupported_conflicting_and_malformed_fail_closed(self):
        for citation in ("Probate Code § 300", "Cal. Prob. Code § 300",
                         "Unknown Code section 300", "CCP WIC § 300",
                         "Family Code / Penal Code § 300", "CCP § 300 garbage",
                         "CCP § 300 / 301", "Civ. Proc. § 300", "CCP § 300.1.2",
                         "CCP §", "discussion of section 300", "300"):
            with self.subTest(citation=citation):
                self.assertIsNone(parse_statute_citation(citation))

    def test_short_body_links_and_chrome(self):
        raw = ('<title>California Code, CCP 527.6</title>'
               '<nav>Home Bill Information</nav><div id="single_law_section">'
               '<h4>Code of Civil Procedure - CCP</h4><div>527.6. '
               'This applies to <a href="other">all persons</a>.</div></div>'
               '<div>Footer navigation</div>')
        self.assertEqual(extract_leginfo_text(raw, StatuteCitation("CCP", "527.6")),
                         "527.6. This applies to all persons.")

    def test_named_section_headings(self):
        for heading in ("Section 527.6", "SECTION 527.6."):
            text = extract_leginfo_text(f"<h2>{heading}</h2><p>All persons qualify.</p>",
                                        StatuteCitation("CCP", "527.6"))
            self.assertIn("All persons qualify.", text)

    def test_missing_wrong_and_conflicting_bodies(self):
        for raw in ('<nav>527.6. Home Bill Information</nav>',
                    '<title>California Code, CCP 527.6</title><div>Home Bill Information</div>',
                    '<div>527.60. This applies to all persons.</div>',
                    '<div>527.6.</div><div>History</div>',
                    '<div>Family Code</div><div>527.6. This applies to all persons.</div>',
                    '<div>PROBATE CODE - PROB</div><div>527.6. All persons qualify.</div>',
                    '<title>California Code, WIC 527.6</title><div>527.6. All persons qualify.</div>',
                    '<title>California Code, CCP 527</title><div>527.6. All persons qualify.</div>',
                    '<div id="single_law_section"></div><div>527.6. Home Bill Information</div>'):
            with self.subTest(raw=raw), self.assertRaises(LegInfoError):
                extract_leginfo_text(raw, StatuteCitation("CCP", "527.6"))

    def test_failed_fetch_and_extraction_never_cache_and_cli_error_is_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = CourtListenerClient(cache=JsonCache(Path(tmp) / "cache"),
                                         library=CaseLibrary(Path(tmp) / "library.sqlite3"))
            for failure in (URLError("synthetic unavailable"), TimeoutError(), None):
                with patch("open_law_lens.statutes.urlopen") as fetch, \
                     patch.object(client.cache, "upsert_statute") as upsert:
                    if failure:
                        fetch.side_effect = failure
                    else:
                        fetch.return_value = BytesIO(b"<div>Home Bill Information</div>")
                    with self.assertRaises(LegInfoError):
                        client.lookup_statute("CCP § 527.6", refresh=True)
                    upsert.assert_not_called()
            with patch("open_law_lens.cli.CourtListenerClient.default", return_value=client), \
                 patch("open_law_lens.statutes.urlopen", return_value=BytesIO(b"<nav>Menu</nav>")), \
                 patch.object(client.cache, "upsert_statute") as upsert:
                output = StringIO()
                with redirect_stdout(output):
                    status = main(["extract-statute", "CCP § 527.6"])
                self.assertNotEqual(status, 0)
                self.assertFalse(json.loads(output.getvalue())["ok"])
                upsert.assert_not_called()


class PassageTruthTests(unittest.TestCase):
    def verify(self, text, queries):
        payload = build_authority_passages(authority(text), queries)
        self.assertNotIn("text", payload)
        self.assertLessEqual(len(payload["passages"]), 6)
        self.assertLessEqual(sum(len(p["text"]) for p in payload["passages"]), 12000)
        returned = [0] * len(queries)
        for passage in payload["passages"]:
            self.assertLessEqual(len(passage["text"]), 2000)
            self.assertEqual(passage["text"], text[passage["start_offset"]:passage["end_offset"]])
            for match in passage["matches"]:
                self.assertLessEqual(passage["start_offset"], match["start_offset"])
                self.assertLessEqual(match["end_offset"], passage["end_offset"])
                self.assertEqual(_normalize_query(text[match["start_offset"]:match["end_offset"]]),
                                 _normalize_query(match["query"]))
                returned[match["query_index"]] += 1
        self.assertEqual(payload["match_count"], sum(returned))
        for i, row in enumerate(payload["query_accounting"]):
            self.assertEqual(row["returned_matches"], returned[i])
            self.assertLessEqual(returned[i], 2)
            self.assertEqual(row["omitted_matches"], row["total_matches"] - returned[i])
        return payload

    def test_overlapping_overlimit_windows_retain_both_matches(self):
        text = "x" * 1100 + "alpha" + "x" * 1700 + "beta" + "x" * 1100
        result = self.verify(text, ["alpha", "beta"])
        self.assertEqual(result["match_count"], 2)
        self.assertEqual(len(result["passages"]), 2)

    def test_first_query_round_precedes_second_occurrences(self):
        queries = [f"topic{i}" for i in range(7)]
        text = ("x" * 3000).join(q for q in queries for _ in range(2))
        result = self.verify(text, queries)
        self.assertEqual([r["returned_matches"] for r in result["query_accounting"]], [1] * 6 + [0])
        self.assertEqual(result["unmatched_queries"], [])
        self.assertIn("passage_count_limit", result["truncation_reasons"])

    def test_unicode_whitespace_boundary_and_oversized_queries(self):
        self.verify("x" * 1998 + " Straße\n\tＦＯＯ  finish " + "x" * 3000,
                    ["STRASSE foo", "finish", "absent"])
        result = self.verify("x" * 2100, ["x" * 2100])
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(result["unmatched_queries"], [])
        self.assertIn("match_exceeds_passage_limit", result["truncation_reasons"])
        self.assertEqual(self.verify("ß", ["s"])["match_count"], 0)

    def test_deterministic_window_accounting_stress(self):
        import random
        rng = random.Random(5276)
        queries = [f"needle{i}" for i in range(9)]
        for _ in range(40):
            text = "".join("x" * rng.randrange(2500) + rng.choice(queries)
                           for _ in range(20))
            payload = self.verify(text, queries)
            self.assertEqual(payload, self.verify(text, queries))

    def test_reporter_sequences_and_match_pages(self):
        for text, status in (("[*56] first [*57] second", "available"),
                             ("first second", "unavailable"),
                             ("[*56] first [*163] parallel [*57] second", "ambiguous"),
                             ("[*57] first [*56] second", "ambiguous"),
                             ("[*55] first [*56] second", "ambiguous")):
            result = self.verify(text, ["second"])
            self.assertEqual(result["pinpoint_status"], status)
            passage = result["passages"][0]
            self.assertEqual(passage["page"], "56" if status == "available" else "")
            self.assertEqual(passage["matches"][0]["start_page"], "57" if status == "available" else "")
        result = self.verify("[*56] first [*57] second", ["first [*57] second"])
        match = result["passages"][0]["matches"][0]
        self.assertEqual((match["start_page"], match["end_page"]), ("56", "57"))


class SearchScopeTests(unittest.TestCase):
    def test_scope_policy_compact_json_and_overrides(self):
        rows = [dict(cluster_id=i, caseName=f"Synthetic {i}", court_id=court, status=status,
                     dateFiled="2026-01-01", snippet='A "quoted" lead\n' * 200)
                for i, (court, status) in enumerate([
                    ("cal", "Published"), ("calctapp", "Published"),
                    ("okla", "Published"), ("ill", "Published"),
                    ("", "Published"), ("cal", ""), ("cal", "Unpublished"),
                ], 1)]
        with tempfile.TemporaryDirectory() as tmp:
            client = CourtListenerClient(cache=JsonCache(Path(tmp) / "cache"),
                                         library=CaseLibrary(Path(tmp) / "library.sqlite3"))
            with patch.object(client, "_request_json", return_value={"results": rows, "count": 99, "next": "next"}) as fetch:
                for semantic in (False, True):
                    page = client.search_cases("test", semantic=semantic)
                    self.assertEqual([r.cluster_id for r in page.results], ["1", "2"])
                    self.assertEqual(sum(dict(page.exclusions).values()), 5)
                    self.assertEqual(page.count, 99)
                    self.assertIn("not exhaustive", page.coverage_warning)
                self.assertEqual(len(client.search_cases("test", courts=(), include_unpublished=True).results), 7)
                self.assertEqual(len(client.search_cases("test", courts=()).results), 5)
                self.assertEqual([r.cluster_id for r in client.search_cases("test", courts=("okla",)).results], ["3"])
                for flags, expected in ((["--compact", "--limit", "5"], 2),
                                        (["--all-courts", "--include-unpublished", "--limit", "10"], 7),
                                        (["--court", "ill"], 1)):
                    output = StringIO()
                    with patch("open_law_lens.cli.CourtListenerClient.default", return_value=client), redirect_stdout(output):
                        self.assertEqual(main(["case-search", "test", *flags]), 0)
                    payload = json.loads(output.getvalue())
                    self.assertEqual(payload["result_count"], expected)
                    self.assertEqual(payload["total_count_scope"], "upstream_unverified")
                    for row in payload["results"]:
                        if "--compact" in flags:
                            self.assertLessEqual(len(row["snippet"]), 1200)
                            self.assertTrue(row["snippet_truncated"])
                        else:
                            self.assertGreater(len(row["snippet"]), 1200)
                self.assertEqual(fetch.call_count, 8)  # exactly one page per call


if __name__ == "__main__":
    unittest.main()
