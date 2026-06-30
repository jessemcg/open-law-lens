from __future__ import annotations

import unittest
from unittest.mock import patch

from open_law_lens import scholar_search


SCHOLAR_RESULTS_HTML = """
<html><body>
<div class="gs_ocr">
  <h3 class="gs_rt"><a id="gs_oci_title0" href="/scholar_case?case=123456789&q=in+re+caden">In re Caden C.</a></h3>
  <div class="gs_a">11 Cal.5th 614 - Supreme Court 2021</div>
</div>
<div class="gs_ocr">
  <h3 class="gs_rt"><a href="https://scholar.google.com/scholar_case?case=987654321&q=other">Other v. Party</a></h3>
</div>
</body></html>
"""


CAPTCHA_HTML = """
<html><body>
<form>Our systems have detected unusual traffic from your computer network.
Please show you're not a robot.</form>
<div class="g-recaptcha"></div>
</body></html>
"""


NO_CASE_HTML = """
<html><body>
<div class="gs_ocr"><h3><a href="/scholar?q=something">Not a case</a></h3></div>
</body></html>
"""


class ScholarSearchUrlTests(unittest.TestCase):
    def test_builds_case_law_scoped_url(self) -> None:
        url = scholar_search.build_scholar_search_url("11 Cal.5th 614")
        self.assertIn("as_sdt=6,33", url)
        self.assertIn("q=11+Cal.5th+614", url)

    def test_collapses_whitespace_and_encodes(self) -> None:
        url = scholar_search.build_scholar_search_url("In   re  Caden")
        self.assertIn("q=In+re+Caden", url)
        self.assertNotIn("In+++re", url)

    def test_rejects_empty_query(self) -> None:
        with self.assertRaises(scholar_search.ScholarSearchError):
            scholar_search.build_scholar_search_url("   ")


class FirstCaseUrlTests(unittest.TestCase):
    def test_returns_first_case_anchor_absolute_url(self) -> None:
        result = scholar_search.first_case_url_from_html(SCHOLAR_RESULTS_HTML)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.url, "https://scholar.google.com/scholar_case?case=123456789&q=in+re+caden")
        self.assertEqual(result.title, "In re Caden C.")

    def test_keeps_already_absolute_url_without_fragment(self) -> None:
        result = scholar_search.first_case_url_from_html(
            '<a href="https://scholar.google.com/scholar_case?case=987#p10">X</a>'
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.url, "https://scholar.google.com/scholar_case?case=987")
        self.assertEqual(result.title, "X")

    def test_returns_none_when_no_case_link(self) -> None:
        self.assertIsNone(scholar_search.first_case_url_from_html(NO_CASE_HTML))

    def test_returns_none_for_empty_html(self) -> None:
        self.assertIsNone(scholar_search.first_case_url_from_html(""))

    def test_skips_non_scholar_case_anchors(self) -> None:
        html = '<a href="/scholar?q=cite">Citation</a><a href="/scholar_case?case=1">Case</a>'
        result = scholar_search.first_case_url_from_html(html)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.url, "https://scholar.google.com/scholar_case?case=1")

    def test_skips_absolute_non_scholar_case_anchors(self) -> None:
        html = (
            '<a href="https://example.com/scholar_case?case=bad">Bad</a>'
            '<a href="/scholar_case?case=1">Case</a>'
        )
        result = scholar_search.first_case_url_from_html(html)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.url, "https://scholar.google.com/scholar_case?case=1")


class CaptchaDetectionTests(unittest.TestCase):
    def test_detects_unusual_traffic(self) -> None:
        self.assertTrue(scholar_search.looks_like_captcha_page(CAPTCHA_HTML))

    def test_detects_recaptcha_marker(self) -> None:
        self.assertTrue(scholar_search.looks_like_captcha_page("<div>recaptcha</div>"))

    def test_clean_results_page_is_not_captcha(self) -> None:
        self.assertFalse(scholar_search.looks_like_captcha_page(SCHOLAR_RESULTS_HTML))

    def test_empty_string_is_not_captcha(self) -> None:
        self.assertFalse(scholar_search.looks_like_captcha_page(""))


class SearchFirstCaseDirectTests(unittest.TestCase):
    def test_success_returns_first_case_url(self) -> None:
        with patch.object(scholar_search, "fetch_url_html", return_value=SCHOLAR_RESULTS_HTML) as fetch:
            result = scholar_search.search_first_case_direct("11 Cal.5th 614")
        self.assertEqual(result.url, "https://scholar.google.com/scholar_case?case=123456789&q=in+re+caden")
        self.assertEqual(result.title, "In re Caden C.")
        self.assertIn("q=11+Cal.5th+614", fetch.call_args.args[0])

    def test_captcha_raises(self) -> None:
        with patch.object(scholar_search, "fetch_url_html", return_value=CAPTCHA_HTML):
            with self.assertRaises(scholar_search.ScholarCaptchaError):
                scholar_search.search_first_case_direct("11 Cal.5th 614")

    def test_no_result_raises(self) -> None:
        with patch.object(scholar_search, "fetch_url_html", return_value=NO_CASE_HTML):
            with self.assertRaises(scholar_search.ScholarNoResultError):
                scholar_search.search_first_case_direct("11 Cal.5th 614")

    def test_fetch_error_raises_search_error(self) -> None:
        with patch.object(scholar_search, "fetch_url_html", side_effect=RuntimeError("HTTP 429")):
            with self.assertRaisesRegex(scholar_search.ScholarSearchError, "HTTP 429"):
                scholar_search.search_first_case_direct("11 Cal.5th 614")


if __name__ == "__main__":
    unittest.main()
