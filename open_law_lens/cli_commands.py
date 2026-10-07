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
        example='project-env run OpenLawLens open-law-lens extract "Welf. & Inst. Code, § 300"',
    ),
    CliCommand(
        name="extract-case",
        title="Extract Case",
        description="Look up a case citation, case-like query, or CourtListener cluster ID and print JSON. Use --find QUERY (repeatable short source phrases, not semantic questions) for bounded verified passages instead of full text. Add --recover-official --timeout 120 --progress for one sequential default-browser Google Scholar recovery when official pagination is missing. Keep complete JSON stdout separate from stderr progress; bound the entire command externally too. For full inspection, --output-dir ABSOLUTE_NEW_DIRECTORY exports private lossless bounded source parts plus metadata/manifest; mutually exclusive with --find and --text.",
        example='project-env run OpenLawLens open-law-lens extract-case "13 Cal.4th 952" --recover-official --timeout 120 --progress --find "presumed father"',
    ),
    CliCommand(
        name="case-search",
        title="Search Cases",
        description="Search CourtListener case law for California case-discovery leads and print JSON.",
        example='project-env run OpenLawLens open-law-lens case-search "beneficial relationship exception" --limit 5 --compact',
    ),
    CliCommand(
        name="extract-slip-opinion",
        title="Extract Slip Opinion",
        description="Download a California Courts slip opinion PDF by case number and print extracted text or JSON.",
        example="project-env run OpenLawLens open-law-lens extract-slip-opinion A173218 --text",
    ),
    CliCommand(
        name="published-citing-cases",
        title="Published Citing Cases",
        description="List ranked published citing cases from the first CourtListener cited-by page.",
        example="project-env run OpenLawLens open-law-lens published-citing-cases --cluster-id 6240402 --limit 10 --json",
    ),
    CliCommand(
        name="extract-statute",
        title="Extract Statute",
        description="Look up a supported California statute citation and print JSON.",
        example='project-env run OpenLawLens open-law-lens extract-statute "Welf. & Inst. Code, § 300"',
    ),
    CliCommand(
        name="extract-rule",
        title="Extract Rule",
        description="Look up a California Rule of Court and print JSON.",
        example='project-env run OpenLawLens open-law-lens extract-rule "Cal. Rules of Court, rule 8.1115"',
    ),
    CliCommand(
        name="open",
        title="Open Authority",
        description="Launch or focus Open Law Lens and display the detected authority.",
        example='project-env run OpenLawLens open-law-lens open "In re Caden C. (2021) 11 Cal.5th 614"',
    ),
    CliCommand(
        name="open-selected",
        title="Open Selected Authority",
        description="Read OS selection or clipboard text, then display the first detected authority.",
        example="project-env run OpenLawLens open-law-lens open-selected",
    ),
    CliCommand(
        name="open-scholar-browser",
        title="Open Scholar in Default Browser",
        description="Open Google Scholar case law for a California case citation or query through the current default HTTPS browser.",
        example='project-env run OpenLawLens open-law-lens open-scholar-browser "11 Cal.5th 614"',
    ),
    CliCommand(
        name="import-scholar-clipboard",
        title="Import Scholar Clipboard",
        description="Validate and import an officially paginated Google Scholar opinion copied to the regular clipboard.",
        example='project-env run OpenLawLens open-law-lens import-scholar-clipboard --citation "11 Cal.5th 614" --source-url "https://scholar.google.com/scholar_case?case=..."',
    ),
    CliCommand(
        name="recover-scholar",
        title="Recover Scholar Copy",
        description="Perform one deterministic default-browser Google Scholar recovery, validation, and import for a California case and print a bounded JSON result.",
        example="project-env run OpenLawLens open-law-lens recover-scholar \"11 Cal.5th 614\" --citation \"11 Cal.5th 614\" --case-name \"In re Caden C.\"",
    ),
    CliCommand(
        name="commands",
        title="List CLI Commands",
        description="Print available Open Law Lens CLI commands and examples.",
        example="project-env run OpenLawLens open-law-lens commands",
    ),
    CliCommand(
        name="show-research-sets",
        title="Show Research Sets",
        description="List saved named Research Cache sets.",
        example="project-env run OpenLawLens open-law-lens show-research-sets",
    ),
    CliCommand(
        name="save-research-set",
        title="Save Research Set",
        description="Save the current Research Cache as a named set.",
        example='project-env run OpenLawLens open-law-lens save-research-set "Case Name_research"',
    ),
    CliCommand(
        name="load-research-set",
        title="Load Research Set",
        description="Replace the current Research Cache with a saved set.",
        example='project-env run OpenLawLens open-law-lens load-research-set "Case Name_research"',
    ),
    CliCommand(
        name="update-brief-library",
        title="Update Prior Brief Library",
        description="Incrementally index the local ODT prior brief archive without embeddings.",
        example="project-env run OpenLawLens open-law-lens update-brief-library",
    ),
    CliCommand(
        name="search-briefs",
        title="Search Prior Briefs",
        description="Search indexed prior briefs and print linked result metadata and snippets.",
        example='project-env run OpenLawLens open-law-lens search-briefs "adequate ICWA inquiry"',
    ),
    CliCommand(
        name="extract-brief",
        title="Extract Prior Brief",
        description="Print metadata and full text for an indexed prior brief ID. Use --output-dir ABSOLUTE_NEW_DIRECTORY for private lossless bounded parts and metadata/manifest; read every part before relying on the brief. Mutually exclusive with --text.",
        example="project-env run OpenLawLens open-law-lens extract-brief <brief_id>",
    ),
    CliCommand(
        name="show-briefs",
        title="Show Prior Briefs",
        description="List indexed prior brief metadata without printing full text.",
        example="project-env run OpenLawLens open-law-lens show-briefs",
    ),
    CliCommand(
        name="brief-library-db",
        title="Show Prior Brief Database",
        description="Print the active prior brief SQLite database path.",
        example="project-env run OpenLawLens open-law-lens brief-library-db",
    ),
)


def build_cli_commands_text() -> str:
    lines = [
        "Open Law Lens CLI",
        "",
        "Usage:",
        "  project-env run OpenLawLens open-law-lens <command> [value]",
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
    lines.append("  project-env run OpenLawLens open-law-lens --list-cli-commands")
    return "\n".join(lines).rstrip() + "\n"
