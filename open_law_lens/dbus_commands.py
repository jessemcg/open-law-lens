from __future__ import annotations

from dataclasses import dataclass

from . import APP_ID


DEFAULT_DBUS_OBJECT_PATH = "/" + APP_ID.replace(".", "/")


@dataclass(frozen=True)
class DbusCommand:
    title: str
    description: str
    action_name: str


DBUS_COMMAND_GROUPS = (
    (
        "Speech Questions",
        (
            DbusCommand(
                title="Submit speech Law question",
                description="Read /dev/shm/speech.txt and submit it to the Law question mode.",
                action_name="submit_speech_law_question",
            ),
            DbusCommand(
                title="Submit speech Research Cache question",
                description="Read /dev/shm/speech.txt and submit it to the Research Cache mode.",
                action_name="submit_speech_cache_question",
            ),
            DbusCommand(
                title="Submit speech Prior Briefing question",
                description="Read /dev/shm/speech.txt and submit it to the Prior Brief mode.",
                action_name="submit_speech_brief_question",
            ),
        ),
    ),
)


def dbus_action_command(
    action_name: str,
    *,
    object_path: str = DEFAULT_DBUS_OBJECT_PATH,
) -> str:
    return (
        f"gdbus call --session --dest {APP_ID} --object-path {object_path} "
        f"--method org.gtk.Actions.Activate {action_name} '[]' '{{}}'"
    )
