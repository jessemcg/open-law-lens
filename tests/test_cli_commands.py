from __future__ import annotations

import json
import sqlite3
import unittest
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from open_law_lens.agent_commands import AGENT_CLI_COMMAND_PREFIX
from open_law_lens.authority_resolver import AuthorityResult
from open_law_lens.browser_recovery import ScholarRecoveryOutcome
from open_law_lens.cli import PROJECT_DIR, _activate_open_authority, build_parser, main
from open_law_lens.cli_commands import CLI_COMMANDS, build_cli_commands_text
from open_law_lens.client import CourtListenerClient, CourtListenerError
from open_law_lens.scholar_browser import ScholarClipboardImport
from open_law_lens.scholar_recovery_service import recover_official_copy


class CliCommandTests(unittest.TestCase):
    def test_command_text_lists_open_selected_without_global_alias(self) -> None:
        text = build_cli_commands_text()

        self.assertIn("open-selected", text)
        self.assertNotIn("global-router-selected", text)

    def test_parser_accepts_new_extract_and_open_commands(self) -> None:
        parser = build_parser()

        self.assertEqual(parser.parse_args(["extract", "13 Cal.4th 952"]).command, "extract")
        self.assertEqual(parser.parse_args(["extract-case", "13 Cal.4th 952"]).command, "extract-case")
        self.assertEqual(
            parser.parse_args(["extract-case", "--cluster-id", "6240402"]).cluster_id,
            "6240402",
        )
        self.assertEqual(parser.parse_args(["case-search", "ICWA"]).command, "case-search")
        self.assertEqual(
            parser.parse_args(["extract-slip-opinion", "A173218"]).command,
            "extract-slip-opinion",
        )
        self.assertEqual(
            parser.parse_args(["extract-slip-opinion", "--cluster-id", "42"]).cluster_id,
            "42",
        )
        self.assertEqual(
            parser.parse_args(
                ["published-citing-cases", "--cluster-id", "6240402", "--json"]
            ).command,
            "published-citing-cases",
        )
        self.assertEqual(parser.parse_args(["open", "13 Cal.4th 952"]).command, "open")
        self.assertEqual(parser.parse_args(["open-selected"]).command, "open-selected")
        self.assertEqual(parser.parse_args(["show-research-sets"]).command, "show-research-sets")
        self.assertEqual(
            parser.parse_args(["save-research-set", "Case_research"]).command,
            "save-research-set",
        )
        self.assertEqual(
            parser.parse_args(["load-research-set", "Case_research"]).command,
            "load-research-set",
        )
        self.assertTrue(
            parser.parse_args(["prune-library", "--missing-citation"]).missing_citation
        )
        self.assertEqual(
            parser.parse_args(["search-briefs", "ICWA", "--sort", "newest"]).command,
            "search-briefs",
        )
        self.assertEqual(
            parser.parse_args(["extract-brief", "a" * 64, "--text"]).command,
            "extract-brief",
        )
        self.assertEqual(parser.parse_args(["update-brief-library"]).command, "update-brief-library")
        self.assertEqual(
            parser.parse_args(["app", "--open-authority", "13 Cal.4th 952"]).open_authority,
            "13 Cal.4th 952",
        )

    def test_registry_contains_only_unique_names(self) -> None:
        names = [command.name for command in CLI_COMMANDS]

        self.assertEqual(len(names), len(set(names)))

    def test_extract_errors_are_json_by_default(self) -> None:
        output = StringIO()
        with (
            patch("open_law_lens.cli.extract_authority", side_effect=ValueError("bad cite")),
            redirect_stdout(output),
        ):
            status = main(["extract-statute", "bad cite"])

        self.assertEqual(status, 1)
        self.assertIn('"ok": false', output.getvalue())
        self.assertIn('"error": "bad cite"', output.getvalue())

    def test_extract_case_by_cluster_id_prints_json(self) -> None:
        result = MagicMock()
        result.ok = True
        result.text = "Opinion text"
        result.error = ""
        result.to_json.return_value = {
            "ok": True,
            "authority_type": "case",
            "identifier": "6240402",
            "text": "Opinion text",
            "text_length": 12,
        }
        output = StringIO()
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=result) as extract,
            redirect_stdout(output),
        ):
            status = main(["extract-case", "--cluster-id", "6240402"])

        self.assertEqual(status, 0)
        extract.assert_called_once_with("6240402", refresh=False)
        self.assertIn('"identifier": "6240402"', output.getvalue())

    def test_extract_case_uses_paginated_duplicate_without_scholar(self) -> None:
        citation = [{"volume": "128", "reporter": "Cal.App.4th", "page": "1051"}]
        older = {"id": 10, "case_name_short": "Example", "citations": citation}
        official = {"id": 20, "case_name": "In re Example", "citations": citation}
        opinions = {
            10: [{"id": 101, "plain_text": "[*88]Parallel reporter text."}],
            20: [{"id": 201, "plain_text": "[*1058]Official text. [*1059]Next page."}],
        }
        client = CourtListenerClient(cache=MagicMock(), library=MagicMock())
        client.library.read_opinion_display.return_value = None
        with (
            patch.object(CourtListenerClient, "default", return_value=client),
            patch.object(client, "lookup_citation", return_value=[{"clusters": [older, official]}]),
            patch.object(client, "fetch_cluster_opinions", side_effect=lambda c, **kw: opinions[c["id"]]),
            patch("open_law_lens.cli.recover_official_copy") as scholar,
            redirect_stdout(StringIO()) as out,
        ):
            code = main(["extract-case", "128 Cal.App.4th 1051", "--recover-official"])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["identifier"], "20")
        self.assertTrue(result["official_pagination"])
        self.assertIn("Official text.", result["text"])
        scholar.assert_not_called()

    def test_parser_accepts_repeated_find_with_extract_case(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            ["extract-case", "13 Cal.4th 952", "--find", "omega", "--find", "alpha"]
        )

        self.assertEqual(args.find, ["omega", "alpha"])

    def test_extract_case_find_and_text_are_mutually_exclusive(self) -> None:
        parser = build_parser()

        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["extract-case", "13 Cal.4th 952", "--find", "omega", "--text"]
            )

    def test_extract_case_find_omits_full_text(self) -> None:
        result = MagicMock()
        result.ok = True
        result.text = "The presumed father discussion."
        result.citation = "28 Cal.4th 56"
        result.official_pagination = False
        result.error = ""
        result.to_json.return_value = {
            "ok": True,
            "authority_type": "case",
            "citation": "28 Cal.4th 56",
            "text": "The presumed father discussion.",
            "text_length": 29,
        }
        output = StringIO()
        with (
            patch("open_law_lens.cli.extract_authority", return_value=result),
            redirect_stdout(output),
        ):
            status = main(
                ["extract-case", "28 Cal.4th 56", "--find", "presumed father"]
            )

        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertNotIn("text", payload)
        self.assertTrue(payload["text_omitted"])
        self.assertIn("passages", payload)
        self.assertEqual(payload["match_count"], 1)

    def test_extract_case_cluster_id_with_find_omits_full_text(self) -> None:
        result = MagicMock()
        result.ok = True
        result.text = "A presumed father may rebut."
        result.citation = ""
        result.official_pagination = False
        result.error = ""
        result.to_json.return_value = {
            "ok": True,
            "authority_type": "case",
            "identifier": "6240402",
            "text": "A presumed father may rebut.",
            "text_length": 28,
        }
        output = StringIO()
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=result),
            redirect_stdout(output),
        ):
            status = main(
                [
                    "extract-case",
                    "--cluster-id",
                    "6240402",
                    "--find",
                    "presumed father",
                ]
            )

        self.assertEqual(status, 0)
        payload = json.loads(output.getvalue())
        self.assertNotIn("text", payload)
        self.assertIn("passages", payload)

    def test_case_search_prints_structured_json(self) -> None:
        search_result = MagicMock()
        search_result.cluster_id = "6240402"
        search_result.opinion_ids = ("6107345",)
        search_result.case_name = "In re Caden C."
        search_result.citation = "11 Cal.5th 614"
        search_result.citations = ("11 Cal.5th 614",)
        search_result.court = "California Supreme Court"
        search_result.court_id = "cal"
        search_result.date_filed = "2021-05-27"
        search_result.status = "Published"
        search_result.cite_count = 100
        search_result.snippet = "beneficial relationship"
        page = MagicMock()
        page.count = 1
        page.next_url = ""
        page.results = [search_result]
        page.exclusions = ()
        page.coverage_warning = "Bounded upstream page; not exhaustive."
        client = MagicMock()
        client.search_cases.return_value = page
        client.case_search_api_query.return_value = "court_id:(cal) status:Published beneficial"
        output = StringIO()
        with (
            patch("open_law_lens.cli.CourtListenerClient.default", return_value=client),
            redirect_stdout(output),
        ):
            status = main(["case-search", "beneficial", "--court", "cal", "--limit", "3"])

        self.assertEqual(status, 0)
        client.search_cases.assert_called_once()
        self.assertIn('"cluster_id": "6240402"', output.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload["results"][0]["extract_command"],
            f"{AGENT_CLI_COMMAND_PREFIX} extract-case --cluster-id 6240402",
        )

    def test_extract_slip_opinion_prints_json(self) -> None:
        result = MagicMock()
        result.to_json.return_value = {
            "ok": True,
            "case_number": "A173218",
            "source_url": "https://www4.courts.ca.gov/opinions/archive/A173218.PDF",
            "text": "Slip text",
        }
        client = MagicMock()
        client.fetch_slip_opinion.return_value = result
        output = StringIO()
        with (
            patch("open_law_lens.cli.CourtListenerClient.default", return_value=client),
            redirect_stdout(output),
        ):
            status = main(["extract-slip-opinion", "A173218"])

        self.assertEqual(status, 0)
        client.fetch_slip_opinion.assert_called_once_with("A173218", refresh=False)
        self.assertIn('"case_number": "A173218"', output.getvalue())

    def test_extract_slip_opinion_by_cluster_prints_text(self) -> None:
        result = MagicMock()
        result.display.text = "Slip text"
        client = MagicMock()
        client.fetch_url.return_value = {"id": 42}
        client.fetch_cluster_slip_opinion.return_value = result
        output = StringIO()
        with (
            patch("open_law_lens.cli.CourtListenerClient.default", return_value=client),
            redirect_stdout(output),
        ):
            status = main(["extract-slip-opinion", "--cluster-id", "42", "--text"])

        self.assertEqual(status, 0)
        client.fetch_url.assert_called_once()
        client.fetch_cluster_slip_opinion.assert_called_once()
        self.assertEqual(output.getvalue(), "Slip text\n")

    def test_published_citing_cases_prints_json(self) -> None:
        search_result = MagicMock()
        search_result.cluster_id = "999"
        search_result.case_name = "Later Published Case"
        search_result.citation = "20 Cal.App.5th 1"
        search_result.date_filed = "2024-01-02"
        search_result.court = "California Court of Appeal"
        search_result.court_id = "calctapp"
        search_result.status = "Published"
        result = MagicMock()
        result.result = search_result
        result.score = 8
        result.cite_count = 2
        result.max_depth = 5
        result.rows_scanned = 25
        result.pages_scanned = 1
        client = MagicMock()
        client.fetch_url.return_value = {"id": 6240402}
        client.published_citing_cases.return_value = [result]
        output = StringIO()
        with (
            patch("open_law_lens.cli.CourtListenerClient.default", return_value=client),
            redirect_stdout(output),
        ):
            status = main([
                "published-citing-cases",
                "--cluster-id",
                "6240402",
                "--limit",
                "3",
                "--json",
            ])

        self.assertEqual(status, 0)
        client.fetch_url.assert_called_once()
        client.published_citing_cases.assert_called_once()
        self.assertIn('"target_cluster_id": "6240402"', output.getvalue())
        self.assertIn('"result_count": 1', output.getvalue())
        self.assertIn('"full_citation": "Later Published Case (2024) 20 Cal.App.5th 1"', output.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload["results"][0]["extract_command"],
            f"{AGENT_CLI_COMMAND_PREFIX} extract-case --cluster-id 999",
        )

    def test_open_dispatches_to_running_app_without_launching(self) -> None:
        with (
            patch("open_law_lens.cli._activate_open_authority", return_value=True) as activate,
            patch("open_law_lens.cli._start_app_detached") as launch,
        ):
            status = main(["open", "  13 Cal.4th 952  "])

        self.assertEqual(status, 0)
        activate.assert_called_once_with("13 Cal.4th 952")
        launch.assert_not_called()

    def test_open_fallback_starts_app_detached_with_authority_text(self) -> None:
        with (
            patch("open_law_lens.cli._activate_open_authority", return_value=False) as activate,
            patch("open_law_lens.cli.write_open_authority_request") as write_request,
            patch("open_law_lens.cli._launch_desktop_app", return_value=True) as desktop_launch,
            patch("open_law_lens.cli._start_app_detached") as direct_launch,
        ):
            status = main(["open", "13 Cal.4th 952"])

        self.assertEqual(status, 0)
        activate.assert_called_once_with("13 Cal.4th 952")
        write_request.assert_called_once_with("13 Cal.4th 952")
        desktop_launch.assert_called_once_with()
        direct_launch.assert_not_called()

    def test_open_fallback_uses_direct_launch_if_desktop_launch_fails(self) -> None:
        with (
            patch("open_law_lens.cli._activate_open_authority", return_value=False),
            patch("open_law_lens.cli.write_open_authority_request") as write_request,
            patch("open_law_lens.cli._launch_desktop_app", return_value=False),
            patch("open_law_lens.cli._start_app_detached", return_value=MagicMock()) as direct_launch,
        ):
            status = main(["open", "13 Cal.4th 952"])

        self.assertEqual(status, 0)
        write_request.assert_called_once_with("13 Cal.4th 952")
        direct_launch.assert_called_once_with()

    def test_detached_launch_uses_current_python_module_entrypoint(self) -> None:
        with patch("open_law_lens.cli.subprocess.Popen") as popen:
            popen.return_value = MagicMock()
            from open_law_lens.cli import _start_app_detached

            _start_app_detached()

        command = popen.call_args.args[0]
        self.assertEqual(command[1:], ["-m", "open_law_lens", "app"])
        self.assertEqual(popen.call_args.kwargs["cwd"], PROJECT_DIR)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_app_subcommand_forwards_internal_open_authority_option(self) -> None:
        with patch("open_law_lens.app.main", return_value=0) as app_main:
            status = main(["app", "--open-authority", "13 Cal.4th 952"])

        self.assertEqual(status, 0)
        app_main.assert_called_once_with(["--open-authority", "13 Cal.4th 952"])

    def test_open_fallback_reports_spawn_failure(self) -> None:
        error = StringIO()
        with (
            patch("open_law_lens.cli._activate_open_authority", return_value=False),
            patch("open_law_lens.cli.write_open_authority_request"),
            patch("open_law_lens.cli._launch_desktop_app", return_value=False),
            patch("open_law_lens.cli._start_app_detached", side_effect=OSError("boom")),
            patch("open_law_lens.cli.discard_open_authority_request") as discard_request,
            redirect_stderr(error),
        ):
            status = main(["open", "13 Cal.4th 952"])

        self.assertEqual(status, 1)
        self.assertIn("Unable to launch Open Law Lens: boom", error.getvalue())
        discard_request.assert_called_once_with()

    def test_open_selected_uses_shared_dispatch(self) -> None:
        with (
            patch("open_law_lens.cli.read_selected_text_from_os", return_value=("13 Cal.4th 952", "primary")),
            patch("open_law_lens.cli._open_authority_in_app", return_value=0) as open_authority,
        ):
            status = main(["open-selected"])

        self.assertEqual(status, 0)
        open_authority.assert_called_once_with("13 Cal.4th 952")

    def test_open_authority_dbus_call_uses_variant_string_parameter(self) -> None:
        completed = MagicMock(returncode=0)
        with patch("open_law_lens.cli.subprocess.run", return_value=completed) as run:
            self.assertTrue(_activate_open_authority(r"In re O'Brien \\ test"))

        command = run.call_args.args[0]
        self.assertIn("[<'In re O\\'Brien \\\\\\\\ test'>]", command)


class RecoverOfficialTests(unittest.TestCase):
    """Optional recovery may improve a baseline but must not erase it."""

    @staticmethod
    def _reconciled_result() -> AuthorityResult:
        return AuthorityResult(
            ok=True,
            authority_type="case",
            input="7856391",
            resolved_input="7856391",
            source="Library",
            title="In re S.H.",
            citation="82 Cal.App.5th 166",
            identifier="external-863c24eb9e52f74a",
            source_url="https://scholar.google.com/scholar_case?case=863c24eb9e52f74a",
            text="82 Cal.App.5th 166 (2022) OPINION [*170] As In re I.F. held, the presumption applies.",
            warnings=[],
            error="",
            official_pagination=True,
            pagination_marker_count=11,
        )

    @staticmethod
    def _unpaginated_result() -> AuthorityResult:
        return AuthorityResult(
            ok=True,
            authority_type="case",
            input="7856391",
            resolved_input="7856391",
            source="CourtListener API",
            title="In re S.H.",
            citation="82 Cal.App.5th 166",
            identifier="7856391",
            source_url="https://example.test/courtlistener/opinion/1",
            text="Baseline opinion: the presumption applies here.",
            warnings=["No embedded reporter page markers."],
            error="",
            official_pagination=False,
            pagination_marker_count=0,
        )

    def test_reconciled_result_recovers_nothing(self) -> None:
        result = self._reconciled_result()
        output, errors = StringIO(), StringIO()
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=result),
            patch("open_law_lens.cli.recover_official_copy") as recover,
            patch("open_law_lens.cli.CourtListenerClient.default") as default_client,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            status = main([
                "extract-case", "--cluster-id", "7856391", "--recover-official",
            ])

        self.assertEqual(status, 0)
        # A reconciled result is already officially paginated: recovery is a
        # complete no-op — no service call, no client, no lock, no browser, and
        # no recovery progress.
        recover.assert_not_called()
        default_client.assert_not_called()
        self.assertEqual(errors.getvalue(), "")
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["official_pagination"])
        self.assertEqual(payload["identifier"], "external-863c24eb9e52f74a")
        self.assertFalse(any("Scholar recovery" in w for w in payload["warnings"]))

    def test_reconciled_result_still_formats_bounded_find_passages(self) -> None:
        result = self._reconciled_result()
        output, errors = StringIO(), StringIO()
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=result),
            patch("open_law_lens.cli.recover_official_copy") as recover,
            redirect_stdout(output),
            redirect_stderr(errors),
        ):
            status = main([
                "extract-case", "--cluster-id", "7856391", "--recover-official",
                "--find", "In re I.F.",
            ])

        self.assertEqual(status, 0)
        recover.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertNotIn("text", payload)
        self.assertEqual(payload["match_count"], 1)
        self.assertIn("In re I.F.", payload["passages"][0]["text"])

    def _extract_find(self, *, recover: bool = True):
        args = ["extract-case", "--cluster-id", "7856391", "--find", "presumption applies"]
        if recover:
            args.append("--recover-official")
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(args)
        self.assertEqual(errors.getvalue(), "")
        self.assertTrue(output.getvalue(), "Expected a JSON result even if recovery failed")
        return status, json.loads(output.getvalue())

    def _assert_baseline_retained(self, payload, baseline, warning):
        self.assertEqual(baseline["match_count"], 1)
        self.assertFalse(baseline["official_pagination"])
        self.assertNotIn("text", baseline)
        passage, = baseline["passages"]
        self.assertEqual(passage["text"], self._unpaginated_result().text)
        self.assertEqual(passage["page"], "")
        match, = passage["matches"]
        self.assertEqual(match["start_page"], "")
        self.assertEqual(match["end_page"], "")
        self.assertEqual(match["pinpoint_status"], "unavailable")
        result = self._unpaginated_result()
        for field in ("source", "citation", "source_url", "identifier"):
            self.assertEqual(payload[field], getattr(result, field))
        warnings = payload["warnings"]
        self.assertEqual(len(warnings), len(baseline["warnings"]) + 1)
        self.assertEqual(warnings[:-1], baseline["warnings"])
        self.assertTrue(warnings[-1].startswith(warning), warnings[-1])
        self.assertNotIn("next step", warnings[-1])
        self.assertEqual(payload, {**baseline, "warnings": warnings})

    def test_optional_recovery_outcomes_preserve_or_improve_find_passage(self) -> None:
        service_module = "open_law_lens.scholar_recovery_service"
        recovered = self._reconciled_result()
        empty = AuthorityResult(False, "case", "82 Cal.App.5th 166", error="No opinion text.")
        for outcome, code, readback, warning in (
            ("blocked", "challenge_captcha", None, "Scholar recovery: blocked [challenge_captcha]"),
            ("not_found", "no_matching_result", None, "Scholar recovery: not_found"),
            ("copied", "", empty, "Scholar recovery: imported [reextract_failed]"),
            ("copied", "", recovered, ""),
        ):
            with (
                self.subTest(outcome=outcome, verified=readback is recovered),
                patch("open_law_lens.cli.extract_case_by_cluster_id",
                      side_effect=lambda *args, **kwargs: self._unpaginated_result()),
                patch("open_law_lens.cli.CourtListenerClient.default"),
                patch("open_law_lens.cli.recover_official_copy", wraps=recover_official_copy) as recover,
                patch(f"{service_module}.RecoveryLock"),
                patch(f"{service_module}.run_scholar_recovery", return_value=ScholarRecoveryOutcome(
                    1, outcome, "82 Cal.App.5th 166", recovered.source_url, "", reason_code=code,
                )) as browser,
                patch(f"{service_module}.read_regular_clipboard", return_value="Synthetic copy."),
                patch(f"{service_module}.import_scholar_text", return_value=ScholarClipboardImport(
                    "In re S.H.", "82 Cal.App.5th 166", recovered.identifier, "opinion-1", 11, True,
                )) as importer,
                patch("open_law_lens.authority_resolver.extract_case", return_value=readback) as extract,
            ):
                baseline_status, baseline = self._extract_find(recover=False)
                recover.assert_not_called()
                self.assertEqual(baseline_status, 0)
                status, payload = self._extract_find()
                self.assertEqual(status, 0)
                recover.assert_called_once()
                browser.assert_called_once()
                self.assertEqual(importer.call_count, int(outcome == "copied"))
                self.assertEqual(extract.call_count, int(outcome == "copied"))
                if warning:
                    self._assert_baseline_retained(payload, baseline, warning)
                else:
                    self.assertEqual(payload["source"], recovered.source)
                    self.assertEqual(payload["source_url"], recovered.source_url)
                    self.assertEqual(payload["match_count"], 1)
                    self.assertEqual(payload["passages"][0]["text"], recovered.text)
                    self.assertEqual(payload["passages"][0]["matches"][0]["start_page"], "170")

    def test_operational_errors_in_optional_recovery_preserve_find_passage(self) -> None:
        for failure_stage, failure in (
            ("setup", sqlite3.OperationalError("private database path")),
            ("lookup", CourtListenerError("private lookup details")),
            ("service", RuntimeError("private service details")),
            ("service", PermissionError("private lock path")),
        ):
            with (
                self.subTest(stage=failure_stage, exception=type(failure)),
                patch("open_law_lens.cli.extract_case_by_cluster_id",
                      side_effect=lambda *args, **kwargs: self._unpaginated_result()),
                patch("open_law_lens.cli.CourtListenerClient.default") as default_client,
                patch("open_law_lens.cli.recover_official_copy") as recover,
            ):
                target = {
                    "setup": default_client,
                    "lookup": default_client.return_value.fetch_url,
                    "service": recover,
                }[failure_stage]
                target.side_effect = failure
                _, baseline = self._extract_find(recover=False)
                status, payload = self._extract_find()
                self.assertEqual(status, 0)
                self.assertNotIn(str(failure), str(payload))
                self.assertNotIn("not_found", str(payload))
                self.assertNotIn("saved", str(payload))
                self._assert_baseline_retained(payload, baseline, "Scholar recovery: failed")
                target.assert_called_once()
                self.assertEqual(recover.call_count, int(failure_stage == "service"))

    def test_failed_recovery_does_not_make_empty_baseline_usable(self) -> None:
        result = AuthorityResult(False, "case", "7856391", error="No readable opinion text.")
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=result),
            patch("open_law_lens.cli.CourtListenerClient.default"),
            patch("open_law_lens.cli.recover_official_copy", side_effect=RuntimeError) as recover,
        ):
            status, payload = self._extract_find()
        recover.assert_called_once()
        self.assertEqual(status, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "No readable opinion text.")
        self.assertEqual(payload["match_count"], 0)

    def test_recovery_does_not_catch_keyboard_interrupt(self) -> None:
        with (
            patch("open_law_lens.cli.extract_case_by_cluster_id", return_value=self._unpaginated_result()),
            patch("open_law_lens.cli.CourtListenerClient.default"),
            patch("open_law_lens.cli.recover_official_copy", side_effect=KeyboardInterrupt) as recover,
            self.assertRaises(KeyboardInterrupt),
        ):
            self._extract_find()
        recover.assert_called_once()


if __name__ == "__main__":
    unittest.main()
