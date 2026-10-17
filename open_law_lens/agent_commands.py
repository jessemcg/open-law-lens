from __future__ import annotations


AGENT_CLI_COMMAND_PREFIX = '"$OPEN_LAW_LENS_CLI_BIN"'


def agent_cli_command(arguments: str) -> str:
    arguments = arguments.strip()
    if not arguments:
        return AGENT_CLI_COMMAND_PREFIX
    return f"{AGENT_CLI_COMMAND_PREFIX} {arguments}"
