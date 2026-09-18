"""Research prompt contracts; no real settings, network, desktop, or models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from open_law_lens.cli_commands import CLI_COMMANDS
from open_law_lens.config import (
    DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
    LEGACY_LATER_TREATMENT_AGENT_PROMPT_SHA256ES,
    load_config,
)

PROJECT = Path(__file__).resolve().parents[1]


class ResearchExecutionContractTests(unittest.TestCase):
    def test_skill_bounds_execution_without_weakening_routes(self):
        text = " ".join(
            (PROJECT / ".pi/skills/legal-researcher/SKILL.md").read_text().split()
        )
        for phrase in (
            "timeout: 180",
            "--recover-official --timeout 120 --progress",
            "complete JSON stdout and separate stderr",
            "One attempt per authority across",
            "suspend further Scholar attempts for this run",
            "not semantic question answering",
            "query_accounting",
            "pinpoint_status",
            "resolved_input",
            "identifier",
            "Never use Computer Use",
            "mandatory enactment-plus-case route",
            "at least one leading published California case",
            "Never retry network timeouts",
            "Never use `web_search` in Subsequent Treatment mode",
        ):
            self.assertIn(phrase, text)

    def test_system_has_no_obsolete_browser_permission(self):
        text = " ".join((PROJECT / ".pi/SYSTEM.md").read_text().split())
        self.assertIn("No desktop-control tools or browser-recovery bridge", text)
        self.assertNotIn("Desktop-control tools are available", text)
        self.assertIn("save complete Open Law Lens JSON", text)
        self.assertIn("Closed-corpus modes remain closed", text)

    def test_cli_catalog_advertises_bounded_recovery(self):
        command = next(c for c in CLI_COMMANDS if c.name == "extract-case")
        self.assertIn("--timeout 120 --progress", command.example)
        self.assertIn("not semantic questions", command.description)
        self.assertIn("separate from stderr", command.description)

    def test_previous_exact_default_upgrades_in_memory_only(self):
        # Reconstruct the immediately preceding tracked default, anchored by
        # its independent SHA256. Customized prompts must not match this hash.
        lines = DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE.splitlines()
        prefixes = (
            "Apply the preloaded Legal Researcher's bounded execution rules",
            "Use the selected case's known official citation",
            "- A supplied pinpoint or a page quoted by another opinion",
        )
        old_lines = []
        skip_blank = False
        for line in lines:
            if line.startswith(prefixes):
                skip_blank = line.startswith(prefixes[0])
                continue
            if skip_blank and not line:
                skip_blank = False
                continue
            old_lines.append(line)
        old = "\n".join(old_lines)
        digest = hashlib.sha256(old.strip().encode()).hexdigest()
        self.assertEqual(
            digest, "ad5d943b604828e7ded91cf31ccc3cdf09eb1d5b3e8ae40e7e85b96dd57b3070"
        )
        self.assertIn(digest, LEGACY_LATER_TREATMENT_AGENT_PROMPT_SHA256ES)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for prompt, expected in (
                (old, DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE),
                (old + "\nCustom instruction.", old + "\nCustom instruction."),
            ):
                with self.subTest(custom=prompt != old):
                    path.write_text(json.dumps({
                        "subsequent_treatment_agent_prompt_template": prompt,
                        "unknown_private_setting": "synthetic-preserve-me",
                    }))
                    before = path.read_bytes()
                    config = load_config(path)
                    self.assertEqual(config.later_treatment_agent_prompt_template, expected)
                    self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
