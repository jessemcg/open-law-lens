"""Literal, GTK-independent run requests. Workflow instructions live in .pi/skills.

No configuration or resource loading belongs here. Values are inserted once as
literal data, never interpreted as templates or shell source.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from .agent_commands import agent_cli_command


def current_case_context(export: Any | None, selected: bool, warning: str = "") -> str:
    heading = "Current-case factual context for this run:\n"
    if not selected:
        return f"{heading}Not selected."
    if export is None:
        return f"{heading}Selected; unavailable: {warning or 'Current case SOCF was not available.'}"
    return (
        f"{heading}Selected; available.\n"
        f"Extracted fact-pattern text: {export.text_path}\n"
        f"Copied source file: {export.source_copy_path}"
    )


def law_request(
    question: str, current_case_export: Any | None = None,
    current_case_selected: bool = False, current_case_warning: str = "",
) -> str:
    return f"Question:\n{question}\n\n{current_case_context(current_case_export, current_case_selected, current_case_warning)}"


def cache_request(
    question: str, export: Any, current_case_export: Any | None = None,
    current_case_selected: bool = False, current_case_warning: str = "",
) -> str:
    count = getattr(export, "authority_count", None)
    if count is None:
        count = export.case_count
    return (
        f"Question:\n{question}\n\n"
        f"Selected authority manifest:\n{export.manifest_path}\n\n"
        f"Selected authority text directory:\n{export.case_dir}\n\n"
        f"Selected authority count: {count}\n\n"
        f"{current_case_context(current_case_export, current_case_selected, current_case_warning)}"
    )


def briefs_request(
    question: str, database_path: Path, brief_count: int,
    current_case_export: Any | None = None, current_case_selected: bool = False,
    current_case_warning: str = "",
) -> str:
    return (
        f"Question:\n{question}\n\n"
        f"Prior brief database snapshot:\n{database_path}\n\n"
        f"Indexed brief count: {brief_count}\n\n"
        f"{current_case_context(current_case_export, current_case_selected, current_case_warning)}"
    )


def assessment_request(issue: str, export: Any) -> str:
    return (
        f"Legal question to decide:\n{issue}\n\n"
        f"Extracted fact-pattern text:\n{export.text_path}\n\n"
        f"Original fact-pattern file (workspace copy):\n{export.source_copy_path}\n\n"
        f"Fact-pattern original path: {export.source_path}"
    )


def treatment_request(target_title: str, cluster_id: str, target_citation: str) -> str:
    def exact_search(text: str) -> str:
        phrase = json.dumps(text.strip(), ensure_ascii=False)
        return agent_cli_command(f"case-search {shlex.quote(phrase)} --limit 10 --compact")

    commands = {
        "published_citing_cases_command": agent_cli_command(
            f"published-citing-cases --cluster-id {shlex.quote(cluster_id)} --limit 10 --json"
        ),
        "citation_search_command": exact_search(target_citation),
        "case_name_search_command": exact_search(target_title),
        "compact_extract_command": agent_cli_command(
            'extract-case --cluster-id <cluster_id> --find "<term>" --find "<term>"'
        ),
        "recover_official_extract_command": agent_cli_command(
            'extract-case "<official citation>" --recover-official --timeout 120'
            ' --progress --find "<term>"'
        ),
        "full_extract_command": agent_cli_command("extract-case --cluster-id <cluster_id>"),
    }
    return (
        f"Target case: {target_title}\nTarget official citation: {target_citation}\n"
        f"CourtListener cluster id: {cluster_id}\n\n"
        + "\n\n".join(f"{name}:\n{command}" for name, command in commands.items())
    )
