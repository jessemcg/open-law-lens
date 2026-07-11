from __future__ import annotations

import unittest

from open_law_lens.dbus_commands import (
    DEFAULT_DBUS_OBJECT_PATH,
    DBUS_COMMAND_GROUPS,
    dbus_action_command,
)


class DbusCommandTests(unittest.TestCase):
    def test_dbus_action_command_uses_application_action_format(self) -> None:
        self.assertEqual(
            dbus_action_command("submit_speech_law_question"),
            (
                "gdbus call --session --dest com.mcglaw.OpenLawLens "
                f"--object-path {DEFAULT_DBUS_OBJECT_PATH} "
                "--method org.gtk.Actions.Activate submit_speech_law_question '[]' '{}'"
            ),
        )

    def test_speech_commands_are_listed(self) -> None:
        action_names = {
            command.action_name
            for _group_title, commands in DBUS_COMMAND_GROUPS
            for command in commands
        }
        self.assertEqual(
            action_names,
            {
                "submit_speech_law_question",
                "submit_speech_cache_question",
                "submit_speech_brief_question",
            },
        )

    def test_prior_brief_speech_command_matches_existing_format(self) -> None:
        command = next(
            command
            for _group_title, commands in DBUS_COMMAND_GROUPS
            for command in commands
            if command.action_name == "submit_speech_brief_question"
        )

        self.assertEqual(command.title, "Submit speech Prior Briefing question")
        self.assertEqual(
            command.description,
            "Read /dev/shm/speech.txt and submit it to the Prior Brief mode.",
        )
        self.assertEqual(
            dbus_action_command(command.action_name),
            (
                "gdbus call --session --dest com.mcglaw.OpenLawLens "
                f"--object-path {DEFAULT_DBUS_OBJECT_PATH} "
                "--method org.gtk.Actions.Activate submit_speech_brief_question '[]' '{}'"
            ),
        )


if __name__ == "__main__":
    unittest.main()
