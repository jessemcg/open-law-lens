from __future__ import annotations

import unittest
from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch

from open_law_lens.cli import build_parser, main
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


if __name__ == "__main__":
    unittest.main()
