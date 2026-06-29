from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary, opinion_display_text


class LibraryTests(unittest.TestCase):
    def test_upsert_cluster_and_lookup_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {
                "id": 42,
                "case_name": "Example v. State",
                "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}],
            }
            library.upsert_cluster(cluster)

            result = library.read_lookup("1 Cal. 2")

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result[0]["clusters"][0]["case_name"], "Example v. State")

    def test_library_case_index_uses_extracted_in_re_initial_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 5607709,
                    "case_name": "Vlasta Z. v. San Bernardino County Welfare Department",
                    "case_name_full": "In re B. G., Persons Coming Under the Juvenile Court Law.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "In re B.G.")

    def test_json_cache_case_index_uses_extracted_in_re_initial_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 5608115,
                    "case_name": "Kings County Human Services Agency v. J.C.",
                    "case_name_full": "In re K.C., a Person Coming Under the Juvenile Court Law.",
                    "case_name_short": "J.C.",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re K.C.")

    def test_library_case_index_uses_extracted_adoption_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 2607287,
                    "case_name": "Steven A. v. Rickie M.",
                    "case_name_full": (
                        "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                        "v. RICKIE M., Objector and Respondent."
                    ),
                    "case_name_short": "Kelsey S.",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "Adoption of Kelsey S.")

    def test_json_cache_case_index_uses_extracted_adoption_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 2607287,
                    "case_name": "Steven A. v. Rickie M.",
                    "case_name_full": (
                        "Adoption of KELSEY S., STEVEN A., Petitioner and Appellant, "
                        "v. RICKIE M., Objector and Respondent."
                    ),
                    "case_name_short": "Kelsey S.",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "Adoption of Kelsey S.")

    def test_library_case_index_normalizes_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            library.upsert_cluster(
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(library.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.upsert_cluster(
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_stale_habeas_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_resource(
                "clusters",
                "6239044",
                {
                    "id": 6239044,
                    "case_name": "In re Jesse Barber On Habeas Corpus",
                    "case_name_full": "IN RE Jesse BARBER on Habeas Corpus.",
                    "case_name_short": "",
                },
            )
            cache.write_case_index(
                {
                    "6239044": {
                        "cluster_id": "6239044",
                        "title": "In re Jesse Barber on Habeas Corpus.",
                        "citation_text": "15 Cal. App. 5th 368",
                    }
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re Barber")

    def test_json_cache_case_index_normalizes_stale_title_from_cluster_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache = JsonCache(Path(temp_dir))
            cache.ensure()
            cache.write_resource(
                "clusters",
                "2802799",
                {
                    "id": 2802799,
                    "case_name_full": "In Re D.P., a Person Coming Under the Juvenile Court Law.",
                    "case_name_short": "In re D.P. CA6",
                },
            )
            cache.write_case_index(
                {
                    "2802799": {
                        "cluster_id": "2802799",
                        "title": "In re D.P. CA6",
                        "citation_text": "237 Cal. App. 4th 911",
                    }
                }
            )

            self.assertEqual(cache.list_case_entries()[0]["title"], "In re D.P.")

    def test_upsert_lookup_preserves_raw_lookup_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
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

            self.assertEqual(library.read_lookup("1   Cal. 2"), lookup)

    def test_opinion_display_text_preserves_explicit_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                '<p id="b368-1">First <page-number label="373">*373</page-number>'
                "Second</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "First [*373]Second")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "373")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*373]")

    def test_opinion_display_text_keeps_pretty_printed_inline_citation_together(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>"
                "jurisdiction is supported by substantial evidence."
                "\n  <em>\n   (In re Alexis E.\n  </em>\n"
                '  (2009) <span class="citation">'
                '<a href="/opinion/2256739/in-re-alexis-e/#451">'
                "171 Cal.App.4th 438, 451</a></span>"
                " [90 Cal.Rptr.3d 44].)"
                "</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "jurisdiction is supported by substantial evidence. "
                "(In re Alexis E. (2009) 171 Cal.App.4th 438, 451 "
                "[90 Cal.Rptr.3d 44].)"
            ),
        )

    def test_opinion_display_text_keeps_pretty_printed_star_pagination_inline(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>serious emotional\n"
                '  <span citation-index="1" class="star-pagination" label="913"> \n'
                "   *913\n"
                "   </span>\n"
                "  damage.</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "serious emotional [*913] damage.")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "913")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*913]")

    def test_opinion_display_text_normalizes_page_word_star_pagination(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": '<p>Text <span class="star-pagination">*Page 1566</span> continues.</p>',
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Text [*1566] continues.")
        self.assertEqual(len(display.page_markers), 1)
        marker = display.page_markers[0]
        self.assertEqual(marker.page_label, "1566")
        self.assertEqual(display.text[marker.start_offset:marker.end_offset], "[*1566]")

    def test_opinion_display_text_decodes_cp1252_em_dash_control(self) -> None:
        opinion = {"id": 10, "html_with_citations": "<p>Alpha \u0097 beta.</p>"}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha \u2014 beta.")

    def test_plain_opinion_display_text_decodes_cp1252_em_dash_control(self) -> None:
        opinion = {"id": 10, "plain_text": "Alpha \u0097 beta."}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha \u2014 beta.")

    def test_plain_opinion_display_text_normalizes_raw_star_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "plain_text": (
                "*513C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under *514Welfare and Institutions Code section 300.\n\n"
                "*323Once the Agency located D.R., it set a special hearing."
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "[*513]C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under [*514]Welfare and Institutions Code section 300.\n\n"
                "[*323]Once the Agency located D.R., it set a special hearing."
            ),
        )
        self.assertEqual(
            [marker.page_label for marker in display.page_markers],
            ["513", "514", "323"],
        )
        for marker in display.page_markers:
            self.assertEqual(display.text[marker.start_offset:marker.end_offset], marker.marker_text)

    def test_opinion_display_text_preserves_bracketed_star_page_markers(self) -> None:
        opinion = {"id": 10, "plain_text": "Alpha [*513] beta *514Gamma."}

        display = opinion_display_text(opinion)

        self.assertEqual(display.text, "Alpha [*513] beta [*514]Gamma.")
        self.assertEqual([marker.page_label for marker in display.page_markers], ["513", "514"])
        for marker in display.page_markers:
            self.assertEqual(display.text[marker.start_offset:marker.end_offset], marker.marker_text)

    def test_html_opinion_display_text_normalizes_untagged_raw_star_page_markers(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                "<p>*513C.T. and D.A. appeal the juvenile court's order.</p>"
                "<p>The Agency filed a petition under *514Welfare and Institutions Code section 300.</p>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "[*513]C.T. and D.A. appeal the juvenile court's order.\n\n"
                "The Agency filed a petition under [*514]Welfare and Institutions Code section 300."
            ),
        )
        self.assertEqual(
            [marker.page_label for marker in display.page_markers],
            ["513", "514"],
        )

    def test_opinion_display_text_preserves_reporter_header_lines(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": (
                '<div><center><b><span class="citation">51 Cal.3d 368</span> '
                "(1990)</b></center>"
                '<center><b><span class="citation">795 P.2d 1244</span></b></center>'
                '<center><b><span class="citation">272 Cal. Rptr. 787</span></b></center>'
                "<center><h1>In re MALINDA S.<br>v.<br>RUSSELL S.</h1></center></div>"
            ),
        }

        display = opinion_display_text(opinion)

        self.assertEqual(
            display.text,
            (
                "51 Cal.3d 368 (1990)\n\n"
                "795 P.2d 1244\n\n"
                "272 Cal. Rptr. 787\n\n"
                "In re MALINDA S.\n\n"
                "v.\n\n"
                "RUSSELL S."
            ),
        )

    def test_opinion_display_text_does_not_infer_paragraph_page_ids(self) -> None:
        opinion = {
            "id": 10,
            "html_with_citations": '<p id="b368-1">First paragraph.</p><p id="b369-2">Second.</p>',
        }

        display = opinion_display_text(opinion)

        self.assertEqual(display.page_markers, [])
        self.assertNotIn("[*368]", display.text)

    def test_opinion_storage_keeps_page_marker_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            cluster = {"id": 42, "case_name": "Example v. State"}
            opinion = {
                "id": 10,
                "cluster_id": 42,
                "html_with_citations": 'Alpha <page-number label="373">*373</page-number> beta.',
            }

            library.upsert_cluster(cluster)
            library.upsert_opinion(opinion, cluster=cluster)
            display = library.read_opinion_display("10")

            self.assertIsNotNone(display)
            assert display is not None
            self.assertEqual(display.text, "Alpha [*373] beta.")
            self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*373]")

    def test_read_opinion_display_regenerates_from_stored_opinion_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = CaseLibrary(Path(temp_dir) / "library.sqlite3")
            library.ensure()
            opinion = {
                "id": 10,
                "cluster_id": 42,
                "html_with_citations": (
                    '<p>Alpha <span class="star-pagination" label="913"> *913 </span> beta.</p>'
                ),
            }
            with library.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO opinions(
                        opinion_id, cluster_id, opinion_json, display_text, source_field, added_at, last_accessed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "10",
                        "42",
                        json.dumps(opinion),
                        "stale display text",
                        "html_with_citations",
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )

            display = library.read_opinion_display("10")

            self.assertIsNotNone(display)
            assert display is not None
            self.assertEqual(display.text, "Alpha [*913] beta.")
            self.assertEqual(display.text[display.page_markers[0].start_offset:display.page_markers[0].end_offset], "[*913]")


if __name__ == "__main__":
    unittest.main()
