from __future__ import annotations


AGENT_CLI_COMMAND_PREFIX = (
    '"$OPEN_LAW_LENS_PROJECT_DIR/../UvEnvironments/project-env" run OpenLawLens open-law-lens'
)


def agent_cli_command(arguments: str) -> str:
    arguments = arguments.strip()
    if not arguments:
        return AGENT_CLI_COMMAND_PREFIX
    return f"{AGENT_CLI_COMMAND_PREFIX} {arguments}"
