from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_law_lens import web_import
from open_law_lens.library import opinion_display_text


SCHOLAR_OPINION_HTML = """<html><body><div id="gs_opinion">
<center><b>115 Cal.App.5th 76 (2025)</b></center>
<center><h3 id="gsl_case_name">In re CLAUDIA R. et al., Persons Coming Under the Juvenile Court Law.<br>
LOS ANGELES COUNTY DEPARTMENT OF CHILDREN AND FAMILY SERVICES, Plaintiff and Respondent,<br>
v.<br>
WENDY C., Defendant and Appellant.</h3></center>
<center><a href="/scholar?scidkt=13235132917208305410&amp;as_sdt=2&amp;hl=en">No. B344660.</a></center>
<p><a class="gsl_pagenum" href="#p80">80</a><a class="gsl_pagenum2" id="p80" href="#p80">*80</a> APPEAL from orders of the Superior Court.</p>
<p></p><h2>OPINION</h2><p></p>
<p>FEUER, J.—</p>
<p><a class="gsl_pagenum" href="#p81">81</a><a class="gsl_pagenum2" id="p81" href="#p81">*81</a> This appeal raises the question.</p>
<p></p><h2><a class="gsl_pagenum" href="#p82">82</a><a class="gsl_pagenum2" id="p82" href="#p82">*82</a> FACTUAL AND PROCEDURAL BACKGROUND</h2><p></p>
<p id="gs_dont_print">Save trees - read court opinions online on Google Scholar.</p>
</div></body></html>"""


class WebImportTests(unittest.TestCase):
    def test_validated_http_url_removes_fragment(self) -> None:
        self.assertEqual(
            web_import.validated_http_url(" https://example.com/case#top "),
            "https://example.com/case",
        )

    def test_validated_http_url_rejects_non_http(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "URL must start"):
            web_import.validated_http_url("file:///tmp/case.html")

    def test_extract_webpage_text_uses_trafilatura_and_metadata(self) -> None:
        fake_trafilatura = SimpleNamespace(
            extract=lambda html, **_kwargs: "In re Test C.\r\n1 Cal.5th 100 (2024)\n\n\n100\n*100 OPINION",
            extract_metadata=lambda html, default_url: SimpleNamespace(title="In re Test C."),
        )

        with patch.object(web_import, "fetch_url_html", return_value="<html>case</html>"):
            with patch.dict(sys.modules, {"trafilatura": fake_trafilatura}):
                result = web_import.extract_webpage_text("https://example.com/case#opinion")

        self.assertEqual(result.url, "https://example.com/case")
        self.assertEqual(result.title, "In re Test C.")
        self.assertIn("1 Cal.5th 100 (2024)", result.text)
        self.assertIn("*100 OPINION", result.text)
        self.assertNotIn("\r", result.text)
        self.assertNotIn("\n\n\n", result.text)

    def test_extract_webpage_text_rejects_empty_extraction(self) -> None:
        fake_trafilatura = SimpleNamespace(
            extract=lambda html, **_kwargs: " ",
            extract_metadata=lambda html, default_url: None,
        )

        with patch.object(web_import, "fetch_url_html", return_value="<html>empty</html>"):
            with patch.dict(sys.modules, {"trafilatura": fake_trafilatura}):
                with self.assertRaisesRegex(RuntimeError, "No readable opinion text"):
                    web_import.extract_webpage_text("https://example.com/empty")

    def test_extract_google_scholar_opinion_text_preserves_left_column_page_markers(self) -> None:
        result = web_import.extract_google_scholar_opinion_text(SCHOLAR_OPINION_HTML)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result.title,
            "In re CLAUDIA R. et al., Persons Coming Under the Juvenile Court Law. "
            "LOS ANGELES COUNTY DEPARTMENT OF CHILDREN AND FAMILY SERVICES, Plaintiff and Respondent, "
            "v. WENDY C., Defendant and Appellant.",
        )
        self.assertIn("115 Cal.App.5th 76 (2025)", result.text)
        self.assertIn("*80 APPEAL", result.text)
        self.assertIn("*81 This appeal", result.text)
        self.assertIn("*82 FACTUAL AND PROCEDURAL BACKGROUND", result.text)
        self.assertNotIn("80*80", result.text)
        self.assertNotIn("Save trees", result.text)

        display = opinion_display_text({"plain_text": result.text})
        self.assertEqual([marker.page_label for marker in display.page_markers], ["80", "81", "82"])

    def test_extract_webpage_text_prefers_google_scholar_opinion_parser(self) -> None:
        with patch.object(web_import, "fetch_url_html", return_value=SCHOLAR_OPINION_HTML):
            result = web_import.extract_webpage_text("https://scholar.google.com/scholar_case?case=1")

        self.assertIn("*80 APPEAL", result.text)
        self.assertEqual(
            result.title,
            "In re CLAUDIA R. et al., Persons Coming Under the Juvenile Court Law. "
            "LOS ANGELES COUNTY DEPARTMENT OF CHILDREN AND FAMILY SERVICES, Plaintiff and Respondent, "
            "v. WENDY C., Defendant and Appellant.",
        )


if __name__ == "__main__":
    unittest.main()
