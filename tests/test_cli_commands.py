from __future__ import annotations

import unittest
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from open_law_lens.cli import PROJECT_DIR, _activate_open_authority, build_parser, main
from open_law_lens.cli_commands import CLI_COMMANDS, build_cli_commands_text


class CliCommandTests(unittest.TestCase):
    def test_command_text_lists_open_selected_without_global_alias(self) -> None:
        text = build_cli_commands_text()

        self.assertIn("open-selected", text)
        self.assertNotIn("global-router-selected", text)

    def test_parser_accepts_new_extract_and_open_commands(self) -> None:
        parser = build_parser()

        self.assertEqual(parser.parse_args(["extract", "13 Cal.4th 952"]).command, "extract")
        self.assertEqual(parser.parse_args(["extract-case", "13 Cal.4th 952"]).command, "extract-case")
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


if __name__ == "__main__":
    unittest.main()
