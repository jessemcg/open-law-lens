from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliCommand:
    name: str
    title: str
    description: str
    example: str


CLI_COMMANDS: tuple[CliCommand, ...] = (
    CliCommand(
        name="extract",
        title="Extract Authority",
        description="Detect the first case, statute, or rule in text and print JSON.",
        example='uv run open-law-lens extract "Welf. & Inst. Code, § 300"',
    ),
    CliCommand(
        name="extract-case",
        title="Extract Case",
        description="Look up a case citation, case-like query, or CourtListener cluster ID and print JSON.",
        example='uv run open-law-lens extract-case "13 Cal.4th 952"',
    ),
    CliCommand(
        name="case-search",
        title="Search Cases",
        description="Search CourtListener case law for California case-discovery leads and print JSON.",
        example='uv run open-law-lens case-search "beneficial relationship exception"',
    ),
    CliCommand(
        name="extract-statute",
        title="Extract Statute",
        description="Look up a supported California statute citation and print JSON.",
        example='uv run open-law-lens extract-statute "Welf. & Inst. Code, § 300"',
    ),
    CliCommand(
        name="extract-rule",
        title="Extract Rule",
        description="Look up a California Rule of Court and print JSON.",
        example='uv run open-law-lens extract-rule "Cal. Rules of Court, rule 8.1115"',
    ),
    CliCommand(
        name="open",
        title="Open Authority",
        description="Launch or focus Open Law Lens and display the detected authority.",
        example='uv run open-law-lens open "In re Caden C. (2021) 11 Cal.5th 614"',
    ),
    CliCommand(
        name="open-selected",
        title="Open Selected Authority",
        description="Read OS selection or clipboard text, then display the first detected authority.",
        example="uv run open-law-lens open-selected",
    ),
    CliCommand(
        name="commands",
        title="List CLI Commands",
        description="Print available Open Law Lens CLI commands and examples.",
        example="uv run open-law-lens commands",
    ),
    CliCommand(
        name="show-research-sets",
        title="Show Research Sets",
        description="List saved named Research Cache sets.",
        example="uv run open-law-lens show-research-sets",
    ),
    CliCommand(
        name="save-research-set",
        title="Save Research Set",
        description="Save the current Research Cache as a named set.",
        example='uv run open-law-lens save-research-set "Case Name_research"',
    ),
    CliCommand(
        name="load-research-set",
        title="Load Research Set",
        description="Replace the current Research Cache with a saved set.",
        example='uv run open-law-lens load-research-set "Case Name_research"',
    ),
)


def build_cli_commands_text() -> str:
    lines = [
        "Open Law Lens CLI",
        "",
        "Usage:",
        "  uv run open-law-lens <command> [value]",
        "",
        "Authority extraction defaults to JSON. Use --text for raw body text where supported.",
        "",
        "Commands:",
    ]
    for command in CLI_COMMANDS:
        lines.append(f"  {command.name}: {command.title}")
        lines.append(f"    {command.description}")
        lines.append(f"    command: {command.example}")
        lines.append("")
    lines.append("List commands:")
    lines.append("  uv run open-law-lens --list-cli-commands")
    return "\n".join(lines).rstrip() + "\n"
