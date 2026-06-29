from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from open_law_lens.cache import JsonCache
from open_law_lens.client import (
    CourtListenerClient,
    RATE_LIMIT_RETRY_BUFFER_SECONDS,
    CourtListenerSearchResult,
    cluster_short_title,
    cluster_citation_line,
    cluster_title,
    dedupe_case_clusters,
    format_official_california_citation,
    html_to_text,
    official_california_reporter_citation_from_text,
    official_california_reporter_citation,
    opinion_text,
    search_result_full_citation,
    us_long_date,
)
from open_law_lens.case_titles import normalize_case_title
from open_law_lens.library import CaseLibrary


class ClientTests(unittest.TestCase):
    def test_request_json_retries_courtlistener_rate_limit(self) -> None:
        class FakeResponse:
            def __init__(self, payload: bytes) -> None:
                self.payload = payload

            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
                return False

            def read(self) -> bytes:
                return self.payload

        rate_limit_error = HTTPError(
            "https://example.test/api/",
            429,
            "Too Many Requests",
            {},
            BytesIO(
                b'{"detail": "Request was throttled. Rate limit exceeded: '
                b'20/min. Expected available in 2 seconds."}'
            ),
        )
        responses = [rate_limit_error, FakeResponse(b'{"ok": true}')]

        def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = CourtListenerClient(
                cache=JsonCache(temp_path / "cache"),
                library=CaseLibrary(temp_path / "library.sqlite3"),
            )

            with (
                patch("open_law_lens.client.urlopen", fake_urlopen),
                patch("open_law_lens.client.time.sleep") as sleep_mock,
            ):
                result = client._request_json(Request("https://example.test/api/"))

        self.assertEqual(result, {"ok": True})
        sleep_mock.assert_called_once_with(2 + RATE_LIMIT_RETRY_BUFFER_SECONDS)

    def test_html_to_text_keeps_paragraph_breaks(self) -> None:
        self.assertEqual(html_to_text("<p>First</p><p>Second <b>line</b></p>"), "First\n\nSecond line")

    def test_html_to_text_decodes_cp1252_em_dash_control(self) -> None:
        self.assertEqual(html_to_text("<p>Alpha \u0097 beta.</p>"), "Alpha \u2014 beta.")

    def test_opinion_text_prefers_html_with_citations(self) -> None:
        opinion = {
            "html_with_citations": "<p>Preferred</p>",
            "plain_text": "Fallback",
        }
        self.assertEqual(opinion_text(opinion), "Preferred")

    def test_cluster_title_and_citation_line(self) -> None:
        cluster = {
            "case_name": "Obergefell v. Hodges",
            "citations": [{"volume": 576, "reporter": "U.S.", "page": "644"}],
        }
        self.assertEqual(cluster_title(cluster), "Obergefell v. Hodges")
        self.assertEqual(cluster_citation_line(cluster), "576 U.S. 644")

    def test_cluster_short_title_prefers_case_name_short(self) -> None:
        cluster = {
            "case_name": "Los Angeles County Department of Children & Family Services v. Elizabeth D.",
            "case_name_short": "In re Emily D.",
        }

        self.assertEqual(cluster_short_title(cluster), "In re Emily D.")

    def test_case_title_normalizes_leading_in_re_only(self) -> None:
        self.assertEqual(normalize_case_title(" In Re Emily D. "), "In re Emily D.")
        self.assertEqual(normalize_case_title("IN RE Malinda S."), "In re Malinda S.")
        self.assertEqual(normalize_case_title("In re MADISON S."), "In re Madison S.")
        self.assertEqual(normalize_case_title("In re MIGUEL S."), "In re Miguel S.")
        self.assertEqual(normalize_case_title("In re D.H."), "In re D.H.")
        self.assertEqual(normalize_case_title("In re KC"), "In re K.C.")
        self.assertEqual(normalize_case_title("In re KC."), "In re K.C.")
        self.assertEqual(normalize_case_title("In re BG (1974)"), "In re B.G. (1974)")
        self.assertEqual(normalize_case_title("In re B. G."), "In re B.G.")
        self.assertEqual(normalize_case_title("In re D.P. CA6"), "In re D.P.")
        self.assertEqual(normalize_case_title("In re Abbigail A. Et Al."), "In re Abbigail A.")
        self.assertEqual(
            normalize_case_title("In re Abbigail A. Et Al. (2016)"),
            "In re Abbigail A. (2016)",
        )
        self.assertEqual(normalize_case_title("People v. In Re Holdings"), "People v. In Re Holdings")
        self.assertEqual(normalize_case_title("People v. KC Holdings"), "People v. KC Holdings")
        self.assertEqual(normalize_case_title("In re Marriage of Smith"), "In re Marriage of Smith")

    def test_case_title_normalizes_habeas_title_to_last_name(self) -> None:
        self.assertEqual(normalize_case_title("In re Jesse Barber on Habeas Corpus."), "In re Barber")
        self.assertEqual(normalize_case_title("IN RE Jesse BARBER on Habeas Corpus."), "In re Barber")
        self.assertEqual(
            normalize_case_title("In Re Gregory Dwayne Reed on Habeas Corpus."),
            "In re Reed",
        )
        self.assertEqual(
            normalize_case_title("In re Stephenson on Habeas Corpus"),
            "In re Stephenson",
        )

    def test_case_title_normalizes_leading_adoption_of_title(self) -> None:
        self.assertEqual(normalize_case_title(" ADOPTION OF KELSEY S. "), "Adoption of Kelsey S.")
        self.assertEqual(normalize_case_title("Adoption of AB"), "Adoption of A.B.")
        self.assertEqual(normalize_case_title("Adoption of A. B."), "Adoption of A.B.")
        self.assertEqual(
            normalize_case_title("Steven A. v. Adoption of Kelsey S."),
            "Steven A. v. Adoption of Kelsey S.",
        )

    def test_cluster_title_normalizes_in_re_casing(self) -> None:
        cluster = {"case_name": "In Re Emily D.", "case_name_short": "In Re Emily D."}

        self.assertEqual(cluster_title(cluster), "In re Emily D.")
        self.assertEqual(cluster_short_title(cluster), "In re Emily D.")

    def test_cluster_short_title_falls_back_to_case_name(self) -> None:
        cluster = {"case_name": "Example v. State"}

        self.assertEqual(cluster_short_title(cluster), "Example v. State")

    def test_cluster_short_title_prefers_case_name_over_non_dependency_short_name(self) -> None:
        cluster = {
            "case_name": "DKN Holdings LLC v. Faerber",
            "case_name_full": "DKN HOLDINGS LLC, Plaintiff and Appellant, v. WADE FAERBER, Defendant and Respondent",
            "case_name_short": "Faerber",
        }

        self.assertEqual(cluster_title(cluster), "DKN Holdings LLC v. Faerber")
        self.assertEqual(cluster_short_title(cluster), "DKN Holdings LLC v. Faerber")

    def test_cluster_short_title_keeps_superior_court_writ_case_name(self) -> None:
        cluster = {
            "case_name": "Cesar V. v. Superior Court",
            "case_name_short": "Cesar",
        }

        self.assertEqual(cluster_short_title(cluster), "Cesar V. v. Superior Court")

    def test_cluster_short_title_uses_full_in_re_title_for_bare_initial_short_name(self) -> None:
        cluster = {
            "case_name": "Kings County Human Services Agency v. J.C.",
            "case_name_full": (
                "In re K.C., a Person Coming Under the Juvenile Court Law. "
                "KINGS COUNTY HUMAN SERVICES AGENCY, and v. J.C., and"
            ),
            "case_name_short": "J.C.",
        }

        self.assertEqual(cluster_short_title(cluster), "In re K.C.")

    def test_cluster_short_title_trims_malformed_dependency_boilerplate(self) -> None:
        cluster = {
            "case_name": "In Re Baby Boy",
            "case_name_full": (
                "In Re Baby Boy v. a Person Coming Under the Juvenile Court Law. "
                "Los Angeles County Department of Children and Family Services, "
                "and v. Jesus H., And"
            ),
            "case_name_short": "In Re Baby Boy",
        }

        self.assertEqual(cluster_short_title(cluster), "In re Baby Boy V.")

    def test_cluster_short_title_extracts_full_in_re_title_when_short_name_missing(self) -> None:
        cluster = {
            "case_name": "Vlasta Z. v. San Bernardino County Welfare Department",
            "case_name_full": (
                "In re B. G., Persons Coming Under the Juvenile Court Law. "
                "VLASTA Z., and v. SAN BERNARDINO COUNTY WELFARE DEPARTMENT, and"
            ),
            "case_name_short": "",
        }

        self.assertEqual(cluster_short_title(cluster), "In re B.G.")

    def test_cluster_short_title_removes_trailing_appellate_district_marker(self) -> None:
        cluster = {
            "case_name": "Santa Clara County Department of Family and Children's Services v. M.H.",
            "case_name_full": (
                "In Re D.P., a Person Coming Under the Juvenile Court Law. "
                "SANTA CLARA COUNTY DEPARTMENT OF FAMILY AND CHILDREN'S SERVICES, "
                "Plaintiff and Respondent, v. M.H., Defendant and Appellant"
            ),
            "case_name_short": "In re D.P. CA6",
        }

        self.assertEqual(cluster_short_title(cluster), "In re D.P.")

    def test_cluster_short_title_removes_et_al_from_in_re_title(self) -> None:
        cluster = {
            "case_name": "Sacramento County Department of Health & Human Services v. Joseph A.",
            "case_name_full": "In re ABBIGAIL A. et al., Persons Coming Under the Juvenile Court Law.",
            "case_name_short": "In re Abbigail A. Et Al.",
        }

        self.assertEqual(cluster_short_title(cluster), "In re Abbigail A.")

    def test_cluster_short_title_extracts_full_adoption_title(self) -> None:
        cluster = {
            "case_name": "Steven A. v. Rickie M.",
            "case_name_full": (
                "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                "v. RICKIE M., Objector and Respondent."
            ),
            "case_name_short": "Kelsey S.",
        }

        self.assertEqual(cluster_short_title(cluster), "Adoption of Kelsey S.")

    def test_cluster_short_title_normalizes_habeas_title(self) -> None:
        cluster = {
            "case_name": "In re Jesse Barber On Habeas Corpus",
            "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
            "case_name_short": "",
        }

        self.assertEqual(cluster_short_title(cluster), "In re Barber")

    def test_official_california_reporter_citation_prefers_official_reporter(self) -> None:
        cluster = {
            "citations": [
                {"volume": "795", "reporter": "P.2d", "page": "1244"},
                {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                {"volume": "272", "reporter": "Cal. Rptr.", "page": "787"},
            ],
        }

        self.assertEqual(official_california_reporter_citation(cluster), "51 Cal.3d 368")

    def test_official_california_reporter_citation_supports_newer_appellate_reporters(self) -> None:
        reporters = {
            "Cal. 4th": "Cal.4th",
            "Cal. 5th": "Cal.5th",
            "Cal.App.4th": "Cal.App.4th",
            "Cal.App.5th": "Cal.App.5th",
        }
        for reporter, expected in reporters.items():
            with self.subTest(reporter=reporter):
                cluster = {"citations": [{"volume": "1", "reporter": reporter, "page": "2"}]}
                self.assertEqual(official_california_reporter_citation(cluster), f"1 {expected} 2")

    def test_official_california_reporter_citation_returns_empty_for_unofficial_reporter(self) -> None:
        cluster = {"citations": [{"volume": "1", "reporter": "Cal. Rptr.", "page": "2"}]}

        self.assertEqual(official_california_reporter_citation(cluster), "")

    def test_format_official_california_citation_italicizes_case_name_in_html(self) -> None:
        cluster = {
            "case_name": "Smith & Jones v. State",
            "date_filed": "2024-02-03",
            "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "2"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "Smith & Jones v. State (2024) 1 Cal.5th 2")
        self.assertEqual(citation.html_text, "<i>Smith &amp; Jones v. State</i> (2024) 1 Cal.5th 2")

    def test_format_official_california_citation_uses_short_name(self) -> None:
        cluster = {
            "case_name": "Los Angeles County Department of Children & Family Services v. Elizabeth D.",
            "case_name_short": "In Re Emily D.",
            "date_filed": "2015-02-17",
            "citations": [{"volume": "234", "reporter": "Cal. App. 4th", "page": "438"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Emily D. (2015) 234 Cal.App.4th 438")
        self.assertEqual(official_california_reporter_citation(cluster), "234 Cal.App.4th 438")

    def test_format_official_california_citation_uses_case_name_over_civil_short_name(self) -> None:
        cluster = {
            "case_name": "DKN Holdings LLC v. Faerber",
            "case_name_full": "DKN HOLDINGS LLC, Plaintiff and Appellant, v. WADE FAERBER, Defendant and Respondent",
            "case_name_short": "Faerber",
            "date_filed": "2015-07-13",
            "citations": [{"volume": "61", "reporter": "Cal. 4th", "page": "813"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(
            citation.plain_text,
            "DKN Holdings LLC v. Faerber (2015) 61 Cal.4th 813",
        )

    def test_format_official_california_citation_keeps_superior_court_writ_case_name(self) -> None:
        cluster = {
            "case_name": "Cesar V. v. Superior Court",
            "case_name_short": "Cesar",
            "date_filed": "2001-08-30",
            "citations": [{"volume": "91", "reporter": "Cal. App. 4th", "page": "1023"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(
            citation.plain_text,
            "Cesar V. v. Superior Court (2001) 91 Cal.App.4th 1023",
        )

    def test_format_official_california_citation_uses_extracted_in_re_initial_title(self) -> None:
        cluster = {
            "case_name": "Kings County Human Services Agency v. J.C.",
            "case_name_full": "In re K.C., a Person Coming Under the Juvenile Court Law.",
            "case_name_short": "J.C.",
            "date_filed": "2011-07-21",
            "citations": [{"volume": "52", "reporter": "Cal. 4th", "page": "231"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re K.C. (2011) 52 Cal.4th 231")

    def test_format_official_california_citation_trims_malformed_dependency_title(self) -> None:
        cluster = {
            "case_name": "In Re Baby Boy",
            "case_name_full": (
                "In Re Baby Boy v. a Person Coming Under the Juvenile Court Law. "
                "Los Angeles County Department of Children and Family Services, "
                "and v. Jesus H., And"
            ),
            "case_name_short": "In Re Baby Boy",
            "date_filed": "2006-06-28",
            "citations": [{"volume": "140", "reporter": "Cal. App. 4th", "page": "1108"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Baby Boy V. (2006) 140 Cal.App.4th 1108")

    def test_format_official_california_citation_removes_appellate_district_marker(self) -> None:
        cluster = {
            "case_name": "Santa Clara County Department of Family and Children's Services v. M.H.",
            "case_name_full": "In Re D.P., a Person Coming Under the Juvenile Court Law.",
            "case_name_short": "In re D.P. CA6",
            "date_filed": "2015-05-21",
            "citations": [{"volume": "237", "reporter": "Cal. App. 4th", "page": "911"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re D.P. (2015) 237 Cal.App.4th 911")

    def test_format_official_california_citation_removes_et_al_from_title(self) -> None:
        cluster = {
            "case_name_short": "In re Abbigail A. Et Al.",
            "date_filed": "2016-07-14",
            "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "83"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Abbigail A. (2016) 1 Cal.5th 83")

    def test_format_official_california_citation_uses_extracted_adoption_title(self) -> None:
        cluster = {
            "case_name": "Steven A. v. Rickie M.",
            "case_name_full": (
                "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                "v. RICKIE M., Objector and Respondent."
            ),
            "case_name_short": "Kelsey S.",
            "date_filed": "1992-05-14",
            "citations": [{"volume": "1", "reporter": "Cal. 4th", "page": "816"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "Adoption of Kelsey S. (1992) 1 Cal.4th 816")

    def test_format_official_california_citation_normalizes_habeas_title(self) -> None:
        cluster = {
            "case_name": "In re Jesse Barber On Habeas Corpus",
            "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
            "case_name_short": "",
            "date_filed": "2017-09-14",
            "citations": [{"volume": "15", "reporter": "Cal. App. 5th", "page": "368"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "In re Barber (2017) 15 Cal.App.5th 368")

    def test_dedupe_case_clusters_prefers_cleaner_official_citation_match(self) -> None:
        duplicate_with_lexis = {
            "id": 5607930,
            "case_name": "San Diego County Department of Social Services v. Rusell S.",
            "case_name_short": "",
            "citation_count": 1,
            "citations": [
                {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                {"volume": "1990", "reporter": "Cal. LEXIS", "page": "4024"},
            ],
        }
        canonical = {
            "id": 2606148,
            "case_name": "In Re Malinda S.",
            "case_name_short": "In Re Malinda S.",
            "citation_count": 210,
            "citations": [{"volume": "51", "reporter": "Cal. 3d", "page": "368"}],
        }

        self.assertEqual(dedupe_case_clusters([duplicate_with_lexis, canonical]), [canonical])
        self.assertEqual(cluster_short_title(dedupe_case_clusters([duplicate_with_lexis, canonical])[0]), "In re Malinda S.")

    def test_dedupe_case_clusters_keeps_different_official_citations(self) -> None:
        clusters = [
            {
                "id": 1,
                "case_name_short": "First",
                "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "1"}],
            },
            {
                "id": 2,
                "case_name_short": "Second",
                "citations": [{"volume": "2", "reporter": "Cal. 5th", "page": "1"}],
            },
        ]

        self.assertEqual(dedupe_case_clusters(clusters), clusters)

    def test_dedupe_case_clusters_keeps_clusters_without_official_citations(self) -> None:
        clusters = [
            {"id": 1, "case_name_short": "First", "citations": [{"volume": "1", "reporter": "P.2d", "page": "1"}]},
            {"id": 2, "case_name_short": "Second", "citations": [{"volume": "1", "reporter": "P.2d", "page": "1"}]},
        ]

        self.assertEqual(dedupe_case_clusters(clusters), clusters)

    def test_format_official_california_citation_omits_missing_year(self) -> None:
        cluster = {
            "case_name": "Example v. State",
            "citations": [{"volume": "1", "reporter": "Cal.App.5th", "page": "2"}],
        }

        citation = format_official_california_citation(cluster)

        self.assertIsNotNone(citation)
        assert citation is not None
        self.assertEqual(citation.plain_text, "Example v. State 1 Cal.App.5th 2")

    def test_official_california_reporter_citation_from_text_filters_unofficial(self) -> None:
        self.assertEqual(
            official_california_reporter_citation_from_text("215 Cal. Rptr. 3d 858"),
            "",
        )
        self.assertEqual(
            official_california_reporter_citation_from_text("10 Cal. App. 5th 130"),
            "10 Cal.App.5th 130",
        )

    def test_citing_opinions_returns_later_case_metadata(self) -> None:
        class FakeCitingClient(CourtListenerClient):
            def __init__(self) -> None:
                self.request_urls: list[str] = []

            def _headers(self) -> dict[str, str]:
                return {}

            def fetch_cluster_opinions(self, cluster, *, refresh=False):  # type: ignore[no-untyped-def]
                return [{"id": 10}]

            def fetch_url(self, url, *, kind, refresh=False):  # type: ignore[no-untyped-def]
                if kind == "opinions":
                    return {"id": 20, "cluster": "/api/rest/v4/clusters/200/"}
                return {
                    "id": 200,
                    "case_name": "Later v. Case",
                    "date_filed": "2024-01-02",
                    "precedential_status": "Published",
                    "citations": [{"volume": "1", "reporter": "Cal. 5th", "page": "2"}],
                }

            def _request_json(self, request):  # type: ignore[no-untyped-def]
                self.request_urls.append(request.full_url)
                return {
                    "count": (
                        "https://www.courtlistener.com/api/rest/v4/"
                        "opinions-cited/?count=on"
                    ),
                    "next": "",
                    "results": [
                        {
                            "citing_opinion": "/api/rest/v4/opinions/20/",
                            "cited_opinion": "/api/rest/v4/opinions/10/",
                            "depth": 2,
                        }
                    ],
                }

        client = FakeCitingClient()

        page = client.citing_opinions(
            {"id": 100, "sub_opinions": ["/api/rest/v4/opinions/10/"]}
        )

        self.assertEqual(len(page.results), 1)
        self.assertEqual(page.count, 1)
        self.assertIn("cited_opinion=10", client.request_urls[0])
        self.assertEqual(len(client.request_urls), 1)
        self.assertEqual(page.results[0].case_name, "Later v. Case")
        self.assertEqual(page.results[0].citation, "1 Cal.5th 2")
        self.assertEqual(page.results[0].date_filed, "2024-01-02")
        self.assertEqual(page.results[0].status, "Published")
        self.assertEqual(page.results[0].snippet, "Citation depth: 2")

    def test_citing_opinions_merges_sub_opinions_and_dedupes_clusters(self) -> None:
        class FakeCitingClient(CourtListenerClient):
            def __init__(self) -> None:
                self.request_urls: list[str] = []

            def _headers(self) -> dict[str, str]:
                return {}

            def fetch_cluster_opinions(self, cluster, *, refresh=False):  # type: ignore[no-untyped-def]
                return [{"id": 10}, {"id": 11}]

            def fetch_url(self, url, *, kind, refresh=False):  # type: ignore[no-untyped-def]
                if kind == "opinions":
                    opinion_id = "20" if str(url).endswith("/20/") else "21"
                    return {
                        "id": int(opinion_id),
                        "cluster": f"/api/rest/v4/clusters/{opinion_id}0/",
                    }
                cluster_id = "200" if str(url).endswith("/200/") else "210"
                return {
                    "id": int(cluster_id),
                    "case_name": f"Later {cluster_id}",
                    "date_filed": (
                        "2024-01-02" if cluster_id == "200" else "2025-01-02"
                    ),
                    "precedential_status": (
                        "Published" if cluster_id == "200" else "Unpublished"
                    ),
                }

            def _request_json(self, request):  # type: ignore[no-untyped-def]
                self.request_urls.append(request.full_url)
                if "cited_opinion=10" in request.full_url:
                    rows = [
                        {"citing_opinion": "/api/rest/v4/opinions/20/", "depth": 1},
                        {"citing_opinion": "/api/rest/v4/opinions/20/", "depth": 3},
                    ]
                else:
                    rows = [{"citing_opinion": "/api/rest/v4/opinions/21/", "depth": 1}]
                return {"count": len(rows), "next": "", "results": rows}

        page = FakeCitingClient().citing_opinions({"id": 100})

        self.assertEqual(
            [result.cluster_id for result in page.results],
            ["200", "210"],
        )
        self.assertEqual(
            [result.status for result in page.results],
            ["Published", "Unpublished"],
        )
        self.assertEqual(page.count, 3)

    def test_citing_opinions_returns_empty_page_without_sub_opinions(self) -> None:
        class FakeCitingClient(CourtListenerClient):
            def __init__(self) -> None:
                pass

            def fetch_cluster_opinions(  # type: ignore[no-untyped-def]
                self,
                cluster,
                *,
                refresh=False,
            ):
                return []

        page = FakeCitingClient().citing_opinions({"id": 100})

        self.assertEqual(page.results, [])
        self.assertEqual(page.count, 0)
        self.assertEqual(page.next_url, "")

    def test_search_result_full_citation_uses_year_and_official_reporter(self) -> None:
        result = CourtListenerSearchResult(
            cluster_id="4378636",
            case_name="In re Example",
            citation="10 Cal.App.5th 130",
            court="California Court of Appeal",
            court_id="calctapp",
            date_filed="2017-03-27",
            status="Published",
        )

        self.assertEqual(
            search_result_full_citation(result),
            "In re Example (2017) 10 Cal.App.5th 130",
        )

    def test_search_result_full_citation_marks_missing_official_reporter(self) -> None:
        result = CourtListenerSearchResult(
            cluster_id="4378637",
            case_name="C.C. v. L.B.",
            citation="",
            court="California Court of Appeal",
            court_id="calctapp",
            date_filed="2024-11-26",
            status="Published",
        )

        self.assertEqual(
            search_result_full_citation(result),
            "C.C. v. L.B. (2024) [official reporter unavailable]",
        )

    def test_us_long_date_formats_iso_date(self) -> None:
        self.assertEqual(us_long_date("2017-03-27"), "March 27, 2017")
        self.assertEqual(us_long_date("not-a-date"), "not-a-date")

    def test_lookup_uses_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cached_lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                        }
                    ],
                }
            ]
            cache.write_lookup("576 U.S. 644", cached_lookup)
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            self.assertEqual(client.lookup_citation("576   U.S. 644"), cached_lookup)
            self.assertEqual(client.last_lookup_source, "Research Cache")
            self.assertEqual(client.cached_clusters()[0]["case_name"], "Example v. State")
            self.assertEqual(library.saved_clusters(), [])

    def test_cached_clusters_hides_existing_duplicate_official_citation_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 5607930,
                    "case_name": "San Diego County Department of Social Services v. Rusell S.",
                    "case_name_short": "",
                    "citation_count": 1,
                    "citations": [
                        {"volume": "51", "reporter": "Cal. 3d", "page": "368"},
                        {"volume": "1990", "reporter": "Cal. LEXIS", "page": "4024"},
                    ],
                }
            )
            cache.upsert_cluster(
                {
                    "id": 2606148,
                    "case_name": "In Re Malinda S.",
                    "case_name_short": "In Re Malinda S.",
                    "citation_count": 210,
                    "citations": [{"volume": "51", "reporter": "Cal. 3d", "page": "368"}],
                }
            )
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)

            clusters = client.cached_clusters()

            self.assertEqual(len(clusters), 1)
            self.assertEqual(clusters[0]["id"], 2606148)

    def test_fetch_cluster_opinions_updates_case_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.write_resource("opinions", "10", {"id": 10, "plain_text": "Opinion text"})
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "sub_opinions": ["/api/rest/v4/opinions/10/"],
            }
            opinions = client.fetch_cluster_opinions(cluster)
            self.assertEqual(opinions, [{"id": 10, "plain_text": "Opinion text"}])
            self.assertEqual(cache.list_case_entries()[0]["opinion_ids"], ["10"])

    def test_fetch_cluster_opinions_saves_eligible_official_paginated_case_to_library(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.write_resource(
                "opinions",
                "10",
                {"id": 10, "cluster_id": 42, "plain_text": "[*25]Opening.\n\n[*26]Next."},
            )
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
                "sub_opinions": ["/api/rest/v4/opinions/10/"],
            }

            client.fetch_cluster_opinions(cluster)

            self.assertEqual(library.saved_clusters()[0]["case_name"], "Example v. State")
            self.assertEqual(library.read_case_opinion_ids("42"), ["10"])

    def test_fetch_cluster_opinions_keeps_ineligible_case_out_of_library(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.write_resource(
                "opinions",
                "10",
                {"id": 10, "cluster_id": 42, "plain_text": "Opening without reporter markers."},
            )
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=cache, library=library)
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": "10", "reporter": "Cal.App.5th", "page": "25"}],
                "sub_opinions": ["/api/rest/v4/opinions/10/"],
            }

            client.fetch_cluster_opinions(cluster)

            self.assertEqual(library.saved_clusters(), [])

    def test_lookup_rejects_empty_citation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = CourtListenerClient(cache=JsonCache(Path(temp_dir)), library=library)
            with self.assertRaises(ValueError):
                client.lookup_citation("   ")

    def test_lookup_uses_library_without_json_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            lookup = [
                {
                    "status": 200,
                    "clusters": [
                        {
                            "id": 42,
                            "case_name": "Example v. State",
                            "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                        }
                    ],
                }
            ]
            library.upsert_lookup("1 Cal. 2", lookup)
            client = CourtListenerClient(cache=cache, library=library)

            self.assertEqual(client.lookup_citation("1 Cal. 2"), lookup)
            self.assertEqual(client.last_lookup_source, "Library")
            self.assertEqual(client.cached_clusters()[0]["case_name"], "Example v. State")

    def test_lookup_ignores_stale_external_import_body_citation_alias(self) -> None:
        class FakeClient(CourtListenerClient):
            def _request_json(self, _request: Request):  # type: ignore[override]
                return [
                    {
                        "status": 200,
                        "clusters": [
                            {
                                "id": 76,
                                "case_name": "In re Antonio R.",
                                "citations": [
                                    {"volume": "76", "reporter": "Cal.App.5th", "page": "421"},
                                ],
                            }
                        ],
                    }
                ]

        stale_cluster = {
            "id": "external-claudia",
            "case_name": "In re Claudia R.",
            "source_type": "user_imported_external_case",
            "citations": [
                {"volume": "115", "reporter": "Cal.App.5th", "page": "76"},
                {"volume": "76", "reporter": "Cal.App.5th", "page": "421"},
            ],
        }
        stale_lookup = [{"status": 200, "clusters": [stale_cluster]}]
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.write_lookup("76 Cal.App.5th 421", stale_lookup)
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            client = FakeClient(cache=cache, library=library)

            result = client.lookup_citation("76 Cal.App.5th 421")

            self.assertEqual(client.last_lookup_source, "CourtListener API")
            self.assertEqual(result[0]["clusters"][0]["case_name"], "In re Antonio R.")
            self.assertEqual(
                cache.read_lookup("76 Cal.App.5th 421")[0]["clusters"][0]["case_name"],
                "In re Antonio R.",
            )

    def test_clear_cache_hides_research_cache_and_preserves_library_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir) / "cache")
            cache.ensure()
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 42,
                    "case_name": "Example v. State",
                    "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                }
            )
            cache.upsert_cluster(
                {
                    "id": 42,
                    "case_name": "Example v. State",
                    "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
                }
            )
            client = CourtListenerClient(cache=cache, library=library)

            cache.clear()

            self.assertEqual(client.cached_clusters(), [])
            self.assertEqual(library.saved_clusters()[0]["case_name"], "Example v. State")


if __name__ == "__main__":
    unittest.main()
