from __future__ import annotations


AGENT_CLI_COMMAND_PREFIX = (
    'uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens'
)
_LEGACY_AGENT_CLI_COMMAND_PREFIXES = (
    "uv run --no-sync open-law-lens",
    "uv run open-law-lens",
)


def agent_cli_command(arguments: str) -> str:
    arguments = arguments.strip()
    if not arguments:
        return AGENT_CLI_COMMAND_PREFIX
    return f"{AGENT_CLI_COMMAND_PREFIX} {arguments}"


def normalize_agent_prompt_commands(prompt: str) -> str:
    """Make Open Law Lens commands deterministic from disposable workspaces."""
    for prefix in _LEGACY_AGENT_CLI_COMMAND_PREFIXES:
        prompt = prompt.replace(prefix, AGENT_CLI_COMMAND_PREFIX)
    return prompt
