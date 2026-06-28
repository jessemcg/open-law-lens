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
            },
        )


if __name__ == "__main__":
    unittest.main()
