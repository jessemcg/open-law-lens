from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.agent_commands import AGENT_CLI_COMMAND_PREFIX
from open_law_lens.config import (
    AGENT_PROFILE_LAW,
    AGENT_PROFILE_PRIOR_BRIEFS,
    AGENT_PROFILE_SUBSEQUENT_TREATMENT,
    AGENT_RUNTIME_PROFILES_VERSION,
    AppConfig,
    DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_APPEAL_ISSUE_LABELS,
    DEFAULT_APPEAL_ISSUE_PRESETS,
    LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES,
    DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE,
    DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    DEFAULT_BARE_STATUTE_LAW_CODE,
    DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
    DEFAULT_READER_FONT_FAMILY,
    DEFAULT_READER_FONT_SIZE_PT,
    PiAgentProfile,
    READER_FONT_FAMILY_OPTIONS,
    load_config,
    save_config,
)


class ConfigTests(unittest.TestCase):
    def test_missing_config_returns_empty_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = load_config(Path(temp_dir) / "config.json")
            self.assertEqual(config.courtlistener_token, "")
            self.assertEqual(config.concordance_file_path, "")
            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
            self.assertEqual(
                config.appeal_issue_agent_prompt_template,
                DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            )
            self.assertEqual(
                config.later_treatment_agent_prompt_template,
                DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
            )
            self.assertIn(
                "You are the Open Law Lens General California Law Agent",
                config.general_agent_prompt_template,
            )
            self.assertIn(
                "Confine research to California state law",
                config.general_agent_prompt_template,
            )
            self.assertIn("Question:\n{question}", config.general_agent_prompt_template)
            self.assertNotIn("case-search", config.general_agent_prompt_template)
            self.assertEqual(config.appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))
            self.assertEqual(config.appeal_issue_labels, list(DEFAULT_APPEAL_ISSUE_LABELS))
            self.assertEqual(config.reader_font_size_pt, DEFAULT_READER_FONT_SIZE_PT)
            self.assertEqual(config.reader_font_family, DEFAULT_READER_FONT_FAMILY)
            self.assertEqual(config.default_bare_statute_law_code, DEFAULT_BARE_STATUTE_LAW_CODE)

    def test_save_and_load_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    courtlistener_token=" token-value ",
                    concordance_file_path=" /tmp/Concordance_File.sdi ",
                    general_agent_prompt_template=" General {question} ",
                    case_agent_prompt_template=" Case {question} ",
                    appeal_issue_agent_prompt_template=" Appeal {issue} ",
                    later_treatment_agent_prompt_template=" Subsequent {cluster_id} ",
                    appeal_issue_presets=[" Issue One ", "Issue Two", "Issue One"],
                    appeal_issue_labels=[" One ", "Two"],
                    agent_runtime_profiles={
                        AGENT_PROFILE_LAW: PiAgentProfile(
                            provider="openai-codex",
                            model="gpt-5.6-sol",
                            thinking="max",
                        ),
                        AGENT_PROFILE_PRIOR_BRIEFS: PiAgentProfile(
                            provider="fireworks",
                            model="accounts/fireworks/routers/glm-fast",
                            thinking="low",
                        ),
                        AGENT_PROFILE_SUBSEQUENT_TREATMENT: PiAgentProfile(
                            provider="google",
                            model="gemini-3.6-flash",
                            thinking="high",
                        ),
                    },
                    reader_font_size_pt=14,
                    reader_font_family="Caladea",
                    default_bare_statute_law_code="FAM",
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.courtlistener_token, "token-value")
            self.assertEqual(config.concordance_file_path, "/tmp/Concordance_File.sdi")
            self.assertEqual(config.general_agent_prompt_template, "General {question}")
            self.assertEqual(config.case_agent_prompt_template, "Case {question}")
            self.assertEqual(config.appeal_issue_agent_prompt_template, "Appeal {issue}")
            self.assertEqual(
                config.later_treatment_agent_prompt_template,
                "Subsequent {cluster_id}",
            )
            self.assertEqual(config.appeal_issue_presets, ["Issue One", "Issue Two"])
            self.assertEqual(config.appeal_issue_labels, ["One", "Two"])
            self.assertEqual(
                config.agent_runtime_profiles[AGENT_PROFILE_LAW],
                PiAgentProfile(
                    provider="openai-codex",
                    model="gpt-5.6-sol",
                    thinking="max",
                ),
            )
            self.assertEqual(
                config.agent_runtime_profiles[AGENT_PROFILE_PRIOR_BRIEFS].thinking,
                "low",
            )
            self.assertEqual(
                config.agent_runtime_profiles[AGENT_PROFILE_SUBSEQUENT_TREATMENT],
                PiAgentProfile(
                    provider="google",
                    model="gemini-3.6-flash",
                    thinking="high",
                ),
            )
            self.assertEqual(config.reader_font_size_pt, 14)
            self.assertEqual(config.reader_font_family, "Caladea")
            self.assertEqual(config.default_bare_statute_law_code, "FAM")

    def test_legacy_xhigh_settings_are_ignored_and_removed_on_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "general_agent_xhigh_reasoning": True,
                        "case_agent_xhigh_reasoning": True,
                        "brief_agent_xhigh_reasoning": True,
                        "appeal_issue_xhigh_reasoning": True,
                        "later_treatment_xhigh_reasoning": True,
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)
            save_config(config, path)
            saved = json.loads(path.read_text(encoding="utf-8"))

            self.assertFalse(
                any("xhigh_reasoning" in key for key in saved)
            )

    def test_invalid_or_incomplete_agent_profiles_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "agent_runtime_profiles": {
                            AGENT_PROFILE_LAW: {
                                "provider": "openai-codex",
                                "model": "gpt-5.6-sol",
                                "thinking": "turbo",
                            },
                            AGENT_PROFILE_PRIOR_BRIEFS: {
                                "provider": "fireworks",
                                "thinking": "low",
                            },
                            AGENT_PROFILE_SUBSEQUENT_TREATMENT: {
                                "provider": "google",
                                "model": "gemini-3.6-flash",
                            },
                            "unknown": {
                                "provider": "test",
                                "model": "test",
                                "thinking": "medium",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(load_config(path).agent_runtime_profiles, {})

    def test_invalid_subsequent_treatment_profile_falls_back_to_pi_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "agent_runtime_profiles": {
                            AGENT_PROFILE_LAW: {
                                "provider": "openai-codex",
                                "model": "gpt-5.6-sol",
                                "thinking": "max",
                            },
                            AGENT_PROFILE_SUBSEQUENT_TREATMENT: {
                                "provider": "google",
                                "model": "gemini-3.6-flash",
                                "thinking": "turbo",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            profiles = load_config(path).agent_runtime_profiles
            self.assertEqual(
                profiles.get(AGENT_PROFILE_LAW),
                PiAgentProfile(
                    provider="openai-codex",
                    model="gpt-5.6-sol",
                    thinking="max",
                ),
            )
            self.assertNotIn(AGENT_PROFILE_SUBSEQUENT_TREATMENT, profiles)

    def test_legacy_law_profile_clones_into_subsequent_treatment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "agent_runtime_profiles": {
                            AGENT_PROFILE_LAW: {
                                "provider": "openai-codex",
                                "model": "gpt-5.6-sol",
                                "thinking": "max",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            profiles = load_config(path).agent_runtime_profiles
            self.assertEqual(
                profiles.get(AGENT_PROFILE_SUBSEQUENT_TREATMENT),
                PiAgentProfile(
                    provider="openai-codex",
                    model="gpt-5.6-sol",
                    thinking="max",
                ),
            )

            # Migration stays in memory until the next ordinary save.
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("agent_runtime_profiles_version", saved)

            save_config(AppConfig(agent_runtime_profiles=profiles), path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved.get("agent_runtime_profiles_version"),
                AGENT_RUNTIME_PROFILES_VERSION,
            )
            self.assertIn(AGENT_PROFILE_SUBSEQUENT_TREATMENT, saved["agent_runtime_profiles"])

    def test_legacy_config_without_law_profile_leaves_subsequent_treatment_on_defaults(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "agent_runtime_profiles": {
                            AGENT_PROFILE_PRIOR_BRIEFS: {
                                "provider": "fireworks",
                                "model": "accounts/fireworks/routers/glm-fast",
                                "thinking": "low",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            profiles = load_config(path).agent_runtime_profiles
            self.assertIn(AGENT_PROFILE_PRIOR_BRIEFS, profiles)
            self.assertNotIn(AGENT_PROFILE_SUBSEQUENT_TREATMENT, profiles)

    def test_preexisting_subsequent_treatment_profile_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            subsequent = PiAgentProfile(
                provider="google",
                model="gemini-3.6-flash",
                thinking="low",
            )
            path.write_text(
                json.dumps(
                    {
                        "agent_runtime_profiles": {
                            AGENT_PROFILE_LAW: {
                                "provider": "openai-codex",
                                "model": "gpt-5.6-sol",
                                "thinking": "max",
                            },
                            AGENT_PROFILE_SUBSEQUENT_TREATMENT: {
                                "provider": subsequent.provider,
                                "model": subsequent.model,
                                "thinking": subsequent.thinking,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_config(path).agent_runtime_profiles[
                    AGENT_PROFILE_SUBSEQUENT_TREATMENT
                ],
                subsequent,
            )

    def test_version2_absent_subsequent_treatment_is_intentional_pi_defaults(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    agent_runtime_profiles={
                        AGENT_PROFILE_LAW: PiAgentProfile(
                            provider="openai-codex",
                            model="gpt-5.6-sol",
                            thinking="max",
                        ),
                    }
                ),
                path,
            )
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["agent_runtime_profiles_version"],
                AGENT_RUNTIME_PROFILES_VERSION,
            )
            self.assertNotIn(
                AGENT_PROFILE_SUBSEQUENT_TREATMENT,
                saved["agent_runtime_profiles"],
            )

            # Reloading must not re-clone Query Law into Subsequent Treatment.
            self.assertNotIn(
                AGENT_PROFILE_SUBSEQUENT_TREATMENT,
                load_config(path).agent_runtime_profiles,
            )

    def test_legacy_general_prompt_migrates_to_new_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "general_agent_prompt_template": (
                            "You are the Open Law Lens General California Law Agent.\n\n"
                            "Answer only legal questions about California law. "
                            "Use the CourtListener "
                            "MCP server only for legal authority and legal research. "
                            "Do not use local Open Law Lens cache files, the durable "
                            "library database, local project files, web browsing, or "
                            "shell commands as legal authority.\n\n"
                            "Confine research to California state law unless the user's "
                            "question explicitly requires federal law. Prefer published "
                            "California Supreme Court and California Court of Appeal "
                            "authority when available.\n\n"
                            "Question:\n{question}"
                        )
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertNotIn("CourtListener " + "MCP server only", config.general_agent_prompt_template)

    def test_prior_default_general_prompt_migrates_to_no_backtick_guidance(self) -> None:
        previous_default = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

For California case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `uv run open-law-lens extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

Use Google Scholar or Codex web search only as a fallback to verify or fill in an official reporter citation or official text when CourtListener metadata is missing or suspect. State when a citation remains uncertain.

Question:
{question}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"general_agent_prompt_template": previous_default}),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertNotIn("backticks", config.general_agent_prompt_template)

    def test_prior_default_general_prompt_migrates_to_recent_slip_guidance(self) -> None:
        previous_default = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

For California case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `uv run open-law-lens extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

Use Google Scholar or Codex web search only as a fallback to verify or fill in an official reporter citation or official text when CourtListener metadata is missing or suspect. State when a citation remains uncertain.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Do not wrap legal authorities or citations in backticks. Reserve backticks only for CLI commands, file paths, and other literal technical text.

Question:
{question}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"general_agent_prompt_template": previous_default}),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.general_agent_prompt_template, DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE)
            self.assertNotIn("case-search", config.general_agent_prompt_template)

    def test_stored_general_prompt_migrates_to_short_default(self) -> None:
        stored_prompt = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research. Do not use the CourtListener MCP server.

For California case-law discovery, start with `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

Use Google Scholar or Codex web search only as a fallback to verify or fill in an official reporter citation or official text when CourtListener metadata is missing or suspect. State when a citation remains uncertain.

Question:
{question}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"general_agent_prompt_template": stored_prompt}),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(
                config.general_agent_prompt_template,
                DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
            )
            self.assertNotIn("case-search", config.general_agent_prompt_template)

    def test_superseded_tracked_default_migrates_to_short_default(self) -> None:
        superseded_default = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

For California case-law discovery, start with `$OLL case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `$OLL extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

For a recent published California slip opinion or any case missing Cal.5th or Cal.App.5th reporter markers, `extract-case` already runs the official-copy cascade through CourtListener, California Courts slip text, Scholar, and cached native Tavily discovery. Inspect its `official_pagination`, `pagination_marker_count`, and warnings; usable unpaginated text may still be returned. Use Pi's web search only for unresolved open-ended verification after that cascade. State when a citation remains uncertain.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Do not wrap legal authorities or citations in backticks. Reserve backticks only for CLI commands, file paths, and other literal technical text.

Question:
{question}""".replace("$OLL", AGENT_CLI_COMMAND_PREFIX)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"general_agent_prompt_template": superseded_default}),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(
                config.general_agent_prompt_template,
                DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
            )
            self.assertNotIn("case-search", config.general_agent_prompt_template)

    def test_default_agent_prompts_use_workspace_safe_command_prefix(self) -> None:
        for prompt in (
            DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
            DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE,
            DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
        ):
            self.assertNotIn("uv run open-law-lens", prompt)
            self.assertNotIn("uv run --no-sync open-law-lens", prompt)
        self.assertIn(AGENT_CLI_COMMAND_PREFIX, DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE)
        # The later-treatment default receives app-generated commands through
        # placeholders; it must not hand-write any CLI syntax itself.
        for placeholder in (
            "{published_citing_cases_command}",
            "{citation_search_command}",
            "{case_name_search_command}",
            "{compact_extract_command}",
            "{recover_official_extract_command}",
            "{full_extract_command}",
        ):
            self.assertIn(placeholder, DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("case-search", DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("extract-case", DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("published-citing-cases", DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE)
        # Appeal research routing lives solely in the preloaded Legal Researcher
        # skill; the runtime prompt must not duplicate CLI commands.
        self.assertNotIn(
            AGENT_CLI_COMMAND_PREFIX,
            DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
        )
        self.assertNotIn("case-search", DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("extract-case", DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("extract-statute", DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE)
        self.assertNotIn("Scholar", DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE)

    def test_custom_general_prompt_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(general_agent_prompt_template="Custom {question}"), path)

            self.assertEqual(load_config(path).general_agent_prompt_template, "Custom {question}")

    def test_legacy_commands_in_custom_agent_prompts_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "general_agent_prompt_template": (
                            "Run `uv run open-law-lens case-search \"<query>\"`.\n\n"
                            "Question: {question}"
                        ),
                        "brief_agent_prompt_template": (
                            "Run `uv run --no-sync open-law-lens extract-brief <brief_id>`."
                        ),
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertIn(
            f'{AGENT_CLI_COMMAND_PREFIX} case-search "<query>"',
            config.general_agent_prompt_template,
        )
        self.assertIn(
            f"{AGENT_CLI_COMMAND_PREFIX} extract-brief <brief_id>",
            config.brief_agent_prompt_template,
        )

    def test_save_normalizes_legacy_agent_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    general_agent_prompt_template=(
                        "Run uv run open-law-lens case-search test. {question}"
                    )
                ),
                path,
            )
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertIn(
            f"{AGENT_CLI_COMMAND_PREFIX} case-search test",
            raw["general_agent_prompt_template"],
        )

    def test_legacy_case_prompt_migrates_to_new_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "case_agent_prompt_template": (
                            "You are the Open Law Lens Marked Research Cache Authorities Agent.\n\n"
                            "Answer only from the selected cached authorities exported into this workspace. "
                            "Do not use web browsing or unselected Open Law Lens authorities. If the exported "
                            "authorities do not answer the question, say that plainly.\n\n"
                            "In your answer, include short direct quotes from the record to highlight legally "
                            "significant statements. Each quote should be only two to five words long, enclosed "
                            "in quotation marks, and must include continuous phrases exactly as they appear in "
                            "the source text.\n\n"
                            "Question:\n"
                            "{question}"
                        )
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
            self.assertIn("saved agent answers as prior analysis", config.case_agent_prompt_template)
            self.assertIn("not as legal authority", config.case_agent_prompt_template)

    def test_prior_default_case_prompt_migrates_to_current_case_guidance(self) -> None:
        prior_default = """You are the Open Law Lens Marked Research Cache Agent.

Answer only from the selected Research Cache materials exported into this workspace. Do not use web browsing or unselected Open Law Lens materials. Treat cases, statutes, and rules as legal authority. Treat saved agent answers as prior analysis for context only, not as legal authority. If the exported materials do not answer the question, say that plainly.

In your answer, include short direct quotes from the record to highlight legally significant statements. Each quote should be only two to five words long, enclosed in quotation marks, and must include continuous phrases exactly as they appear in the source text.

Question:
{question}

Selected authority manifest:
{case_manifest}

Selected authority text directory:
{case_dir}

Selected authority count: {case_count}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"case_agent_prompt_template": prior_default}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
        self.assertIn("current-case factual context", config.case_agent_prompt_template)

    def test_automatic_socf_case_prompt_migrates_to_opt_in_wording(self) -> None:
        previous_default = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE.replace(
            "Answer only from the selected Research Cache materials and any current-case factual context explicitly selected for this run.",
            "Answer only from the selected Research Cache materials and current-case factual context exported into this workspace.",
        ).replace(
            "Treat any current-case fact pattern as factual context only",
            "Treat the current-case fact pattern as factual context only",
        ).replace(
            "When current-case factual context is provided and the question calls for comparison,",
            "When the question calls for comparison,",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"case_agent_prompt_template": previous_default}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
        self.assertIn("explicitly selected", config.case_agent_prompt_template)

    def test_original_cases_agent_prompt_migrates_to_authority_quote_guidance(self) -> None:
        prior_default = """You are the Open Law Lens Marked Research Cache Cases Agent.

Answer only from the selected cached cases exported into this workspace. Do not use CourtListener MCP, web browsing, or unselected Open Law Lens cases. If the exported cases do not answer the question, say that plainly.

In your answer, include short direct quotes from the record to highlight legally significant statements. Each quote should be only two to five words long, enclosed in quotation marks, and must include continuous phrases exactly as they appear in the source text.

Question:
{question}

Selected case manifest:
{case_manifest}

Selected case text directory:
{case_dir}

Selected case count: {case_count}"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"case_agent_prompt_template": prior_default}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.case_agent_prompt_template, DEFAULT_CASE_AGENT_PROMPT_TEMPLATE)
        self.assertIn("selected cases, statutes, and rules", config.case_agent_prompt_template)
        self.assertIn("same paragraph", config.case_agent_prompt_template)

    def test_legacy_appeal_prompt_migrates_to_new_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_agent_prompt_template": (
                            "You are the Open Law Lens Appeal Issue Assessment Agent.\n\n"
                            "Assess one possible California appellate issue against the user's "
                            "fact pattern. Use Open Law Lens CLI commands tied directly to "
                            "CourtListener APIs for legal authority and legal research.\n\n"
                            "Read the extracted fact-pattern text first:\n"
                            "{fact_pattern_path}\n\n"
                            "Original fact-pattern file:\n"
                            "{fact_pattern_source_path}\n\n"
                            "Issue to assess:\n"
                            "{issue}\n\n"
                            "Research California law with Open Law Lens CLI commands. For "
                            "case-law discovery, start with `uv run open-law-lens case-search "
                            "\"<query>\"`. Treat search results as leads only. Extract the "
                            "most relevant candidate opinions with `uv run open-law-lens "
                            "extract-case --cluster-id <cluster_id>` before relying on a case. "
                            "Use `uv run open-law-lens extract-statute \"<citation>\"` and "
                            "`uv run open-law-lens extract-rule \"<citation>\"` when statutes "
                            "or rules matter.\n\n"
                            "Confine research to California state law unless the issue "
                            "explicitly requires federal law. Prefer published California "
                            "Supreme Court and California Court of Appeal authority. Use "
                            "unpublished cases only for context, not as controlling authority.\n\n"
                            "Analyze preservation, standard of review, factual support, "
                            "governing law, prejudice, likely respondent arguments, and "
                            "missing record facts that could change the assessment.\n\n"
                            "End with a rating line exactly in this form:\n"
                            "Rating: Strong, Medium, Weak, or Frivolous\n\n"
                            "Use Frivolous only when the issue is clearly foreclosed or lacks "
                            "any nonfrivolous factual or legal basis. Otherwise choose Strong, "
                            "Medium, or Weak."
                        )
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(
                config.appeal_issue_agent_prompt_template,
                DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            )
            self.assertIn("Record citation format", config.appeal_issue_agent_prompt_template)
            self.assertIn("Legal question to decide", config.appeal_issue_agent_prompt_template)
            self.assertIn("Conclusion:", config.appeal_issue_agent_prompt_template)
            self.assertIn("Confidence:", config.appeal_issue_agent_prompt_template)
            self.assertNotIn("Argument to assess", config.appeal_issue_agent_prompt_template)
            self.assertNotIn("Issue to assess", config.appeal_issue_agent_prompt_template)
            self.assertNotIn(
                "Rating: Strong, Medium, Weak, or Frivolous",
                config.appeal_issue_agent_prompt_template,
            )

    def test_prior_default_appeal_prompt_migrates_to_recent_slip_guidance(self) -> None:
        previous_default = """You are the Open Law Lens Appeal Issue Assessment Agent.

Assess one possible California appellate argument against the user's fact pattern. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

Read the extracted fact-pattern text first:
{fact_pattern_path}

Original fact-pattern file:
{fact_pattern_source_path}

Record citation format for final answers:
- Cite factual claims using record citations from the fact-pattern text, the way an appellate lawyer would, such as `(CT 335-343.)`, `(RT 6, 34; CT 140, 190.)`, or `(RT 22-34; CRT 17-22; CT 295-301.)`.
- Do not cite local paths, extracted-text filenames, raw file pages, or line numbers in the final answer. Use those only as internal search leads.
- Put record citations in the same sentence or paragraph as the factual claim they support.
- Combine multiple record citations into one parenthetical only when they support the same point.
- If the fact-pattern text does not include a usable record citation for an important fact, say that the citation is missing or uncertain instead of inventing one.

Argument to assess:
{issue}

Research California law with Open Law Lens CLI commands. For case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. When a promising search result has an official citation or recognizable case name, try `uv run open-law-lens extract-case "<official citation or case name>"` first so saved durable-library text can be reused. Use `uv run open-law-lens extract-case --cluster-id <cluster_id>` only when citation/name extraction fails or no reliable citation/name is available. Use `uv run open-law-lens extract-statute "<citation>"` and `uv run open-law-lens extract-rule "<citation>"` when statutes or rules matter.

Confine research to California state law unless the argument explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority. Use unpublished cases only for context, not as controlling authority.

Analyze preservation, standard of review, factual support, governing law, prejudice, likely respondent arguments, and missing record facts that could change the assessment.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Reserve backticks for CLI commands, file paths, and other literal technical text.

End with a rating line exactly in this form:
Rating: Strong, Medium, Weak, or Frivolous"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"appeal_issue_agent_prompt_template": previous_default}),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(
                config.appeal_issue_agent_prompt_template,
                DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
            )
            self.assertIn(
                "Treat the supplied fact pattern as the complete factual record",
                config.appeal_issue_agent_prompt_template,
            )
            self.assertNotIn(
                "recent published California slip opinion",
                config.appeal_issue_agent_prompt_template,
            )
            self.assertNotIn("Scholar", config.appeal_issue_agent_prompt_template)

    def test_immediately_preceding_appeal_prompt_migrates_to_new_default(self) -> None:
        previous_default = """You are the Open Law Lens Appeal Issue Assessment Agent.

Assess one possible California appellate argument against the user's fact pattern. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

Read the extracted fact-pattern text first:
{fact_pattern_path}

Original fact-pattern file:
{fact_pattern_source_path}

Record citation format for final answers:
- Cite factual claims using record citations from the fact-pattern text, the way an appellate lawyer would, such as `(CT 335-343.)`, `(RT 6, 34; CT 140, 190.)`, or `(RT 22-34; CRT 17-22; CT 295-301.)`.
- Do not cite local paths, extracted-text filenames, raw file pages, or line numbers in the final answer. Use those only as internal search leads.
- Put record citations in the same sentence or paragraph as the factual claim they support.
- Combine multiple record citations into one parenthetical only when they support the same point.
- If the fact-pattern text does not include a usable record citation for an important fact, say that the citation is missing or uncertain instead of inventing one.

Treat the supplied fact pattern as the complete factual record for this assessment. Base the factual analysis only on facts it contains. Do not speculate that unprovided facts or a more complete record could alter the assessment, and do not add a generic record-completeness caveat. If the supplied text is internally ambiguous, contradictory, or lacks a usable record citation, identify that specific issue only where it affects the analysis.

Argument to assess:
{issue}

Research California law with Open Law Lens CLI commands. Extract the current controlling enactment first with `$OLL extract-statute "<citation>"` and `$OLL extract-rule "<citation>"`. For a known material case, direct-extract it with `$OLL extract-case "<official citation or case name>"`, using `--find "<term>"` for a narrow bounded proposition. Use `$OLL extract-case --cluster-id <cluster_id>` only when citation or name extraction fails. Run a focused `$OLL case-search "<query>" --limit 5` only when no reliable citation or case name is known, then extract the best published result. Treat search results as leads only.

For a recent published California slip opinion or any published case still missing Cal.5th or Cal.App.5th reporter markers, `extract-case` supplies the Library/CourtListener/slip baseline text. If a relied-on case remains unpaginated, perform one confined default-browser Google Scholar recovery and import the official copy; on no result or no qualifying markers, stop and rely on the baseline with a disclosed pagination limitation. Never fall back to Tavily, direct HTTP Scholar, alternate opinion sites, or generic web search for an official copy.

Confine research to California state law unless the argument explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority. Use unpublished cases only for context, not as controlling authority.

Analyze preservation, standard of review, factual support, governing law, prejudice, and likely respondent arguments based on the supplied complete fact pattern.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Reserve backticks for CLI commands, file paths, and other literal technical text.

End with a rating line exactly in this form:
Rating: Strong, Medium, Weak, or Frivolous""".replace("$OLL", AGENT_CLI_COMMAND_PREFIX)
        prompt_hash = hashlib.sha256(previous_default.strip().encode()).hexdigest()
        self.assertIn(prompt_hash, LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES)
        self.assertNotEqual(previous_default, DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"appeal_issue_agent_prompt_template": previous_default}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(
            config.appeal_issue_agent_prompt_template,
            DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
        )
        self.assertIn(
            "complete factual record",
            config.appeal_issue_agent_prompt_template,
        )
        self.assertIn("Legal question to decide", config.appeal_issue_agent_prompt_template)
        self.assertNotIn("Argument to assess", config.appeal_issue_agent_prompt_template)
        self.assertNotIn(
            "Rating: Strong, Medium, Weak, or Frivolous",
            config.appeal_issue_agent_prompt_template,
        )

    def test_local_legacy_appeal_prompt_migrates_to_new_default(self) -> None:
        legacy_prompt = """You are the Open Law Lens Appeal Issue Assessment Agent.

Assess one possible California appellate argument against the user's fact pattern. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

Read the extracted fact-pattern text first:
{fact_pattern_path}

Original fact-pattern file:
{fact_pattern_source_path}

Record citation format for final answers:
- Cite factual claims using record citations from the fact-pattern text, the way an appellate lawyer would, such as `(CT 335-343.)`, `(RT 6, 34; CT 140, 190.)`, or `(RT 22-34; CRT 17-22; CT 295-301.)`.
- Do not cite local paths, extracted-text filenames, raw file pages, or line numbers in the final answer. Use those only as internal search leads.
- Put record citations in the same sentence or paragraph as the factual claim they support.
- Combine multiple record citations into one parenthetical only when they support the same point.
- If the fact-pattern text does not include a usable record citation for an important fact, say that the citation is missing or uncertain instead of inventing one.

Treat the supplied fact pattern as the complete factual record for this assessment. Base the factual analysis only on facts it contains. Do not speculate that unprovided facts or a more complete record could alter the assessment, and do not add a generic record-completeness caveat. If the supplied text is internally ambiguous, contradictory, or lacks a usable record citation, identify that specific issue only where it affects the analysis.

Argument to assess:
{issue}

Research California law with Open Law Lens CLI commands. For case-law discovery, start with `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens case-search "<query>"`. Treat search results as leads only. When a promising search result has an official citation or recognizable case name, try `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case "<official citation or case name>"` first so saved durable-library text can be reused. Use `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case --cluster-id <cluster_id>` only when citation/name extraction fails or no reliable citation/name is available. Use `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-statute "<citation>"` and `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-rule "<citation>"` when statutes or rules matter.

For a recent published California slip opinion with no official reporter citation, a placeholder like `___ Cal.App.5th ___`, or only a docket number, run targeted Google Scholar or web searches using the case name, docket number, filed date, and `Cal.App.5th`. If an official citation is found, retry `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case "<official citation>"` and rely on the extracted text, source, warnings, and reporter markers.

Confine research to California state law unless the argument explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority. Use unpublished cases only for context, not as controlling authority.

Analyze preservation, standard of review, factual support, governing law, prejudice, and likely respondent arguments based on the supplied complete fact pattern.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Reserve backticks for CLI commands, file paths, and other literal technical text.

End with a rating line exactly in this form:
Rating: Strong, Medium, Weak, or Frivolous"""
        prompt_hash = hashlib.sha256(legacy_prompt.strip().encode()).hexdigest()
        self.assertIn(prompt_hash, LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"appeal_issue_agent_prompt_template": legacy_prompt}),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(
            config.appeal_issue_agent_prompt_template,
            DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
        )
        self.assertIn("Legal question to decide", config.appeal_issue_agent_prompt_template)
        self.assertNotIn("Scholar", config.appeal_issue_agent_prompt_template)

    def test_new_default_appeal_prompt_is_neutral_legal_question_assessment(self) -> None:
        prompt = DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE

        self.assertIn("objective California appellate assessment", prompt)
        self.assertIn("bench memorandum", prompt)
        self.assertIn("not an advocate for any party", prompt)
        self.assertIn("Do not presume an answer from the wording of the question", prompt)
        self.assertIn("Legal question to decide:\n{issue}", prompt)
        self.assertIn("Legal Researcher workflow preloaded", prompt)
        self.assertIn("Question Presented", prompt)
        self.assertIn("Short Answer", prompt)
        self.assertIn("Governing Law/Standard of Review", prompt)
        self.assertIn("strongest material reasoning supporting each possible answer", prompt)
        self.assertIn(
            "address it expressly", prompt,
        )
        self.assertIn("ancestry with a particular tribe", prompt)
        self.assertIn(
            "End the answer with these two lines exactly in this form:", prompt,
        )
        self.assertIn(
            "Conclusion: <direct answer to the legal question>", prompt,
        )
        self.assertIn(
            "Confidence: <High, Medium, or Low> — <brief basis tied to the law and record>",
            prompt,
        )
        self.assertIn("High: controlling law", prompt)
        self.assertIn("Medium: one conclusion is better supported", prompt)
        self.assertIn("Low: the issue is close or unsettled", prompt)
        self.assertIn("complete factual record", prompt)
        self.assertIn("do not add a generic record-completeness caveat", prompt)
        self.assertIn("{fact_pattern_path}", prompt)
        self.assertIn("{fact_pattern_source_path}", prompt)
        self.assertIn("normal legal prose for case names", prompt)
        self.assertNotIn("Argument to assess", prompt)
        self.assertNotIn("Rating: Strong, Medium, Weak, or Frivolous", prompt)
        self.assertNotIn("Scholar", prompt)
        self.assertNotIn("web search", prompt)

    def test_default_appeal_issue_presets_are_neutral_questions(self) -> None:
        for preset in DEFAULT_APPEAL_ISSUE_PRESETS:
            self.assertTrue(preset.endswith("?"), preset)
            self.assertNotIn("In re ", preset)
            self.assertNotIn("Cal.5th", preset)
            self.assertNotIn("Cal.App.4th", preset)
            self.assertNotIn("Cal.App.5th", preset)

        self.assertEqual(
            list(DEFAULT_APPEAL_ISSUE_PRESETS),
            [
                "Did substantial evidence support the challenged finding?",
                "Did the trial court abuse its discretion in making the challenged order?",
                "Did the trial court apply the correct legal standard?",
                "Did the proceedings afford the appellant due process, including "
                "adequate notice and a meaningful opportunity to be heard?",
                "If error occurred, was it prejudicial under the applicable appellate standard?",
            ],
        )

    def test_generic_default_appeal_issue_presets_map_to_questions(self) -> None:
        legacy_defaults = [
            "Substantial evidence does not support the challenged finding.",
            "The trial court abused its discretion in making the challenged order.",
            "The trial court applied the wrong legal standard.",
            "The appellant was denied due process, notice, or a meaningful opportunity to be heard.",
            "The error was prejudicial and not harmless under the applicable appellate standard.",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_presets": legacy_defaults,
                        "appeal_issue_labels": list(DEFAULT_APPEAL_ISSUE_LABELS),
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))
        self.assertEqual(config.appeal_issue_labels, list(DEFAULT_APPEAL_ISSUE_LABELS))

    def test_dependency_appeal_issue_presets_map_exactly_preserving_order(self) -> None:
        legacy_presets = [
            "Substantial evidence did not support the order asserting dependency jurisdiction over the child[ren] under Welfare and Institutions Code section 300.",
            "Substantial evidence did not support the order removing the child[ren] from parental custody under Welfare and Institutions Code section 361, subdivision (c)(1).",
            "The juvenile court abused its discretion in finding that the child welfare agency conducted an adequate Cal-ICWA inquiry. (Welf. & Inst. Code, § 224.2; In re Dezi C. (2024) 16 Cal.5th 1112, 1141.)",
            "The juvenile court erred in failing to apply the beneficial relationship exception. (Welf. & Inst. Code, § 366.26, subd. (c)(1)(B)(i); In re Caden C. (2021) 11 Cal.5th 614, 636.)",
            "Clear and convincing evidence did not support a finding that the child was likely to be adopted within a reasonable time. (Welf. & Inst. Code, § 366.26, subd. (c)(1); In re Sarah M. (1994) 22 Cal.App.4th 1642, 1649.)",
            "The juvenile court erred in denying the parent's section 388 petition after an evidentiary hearing. (Welf. & Inst. Code, § 388, subd. (a)(1); In re J.M. (2020) 50 Cal.App.5th 833, 846.)",
            "The juvenile court erred in summarily denying the parent's section 388 petition without an evidentiary hearing. (Welf. & Inst. Code, § 388, subd. (a)(1); In re Edward H. (1996) 43 Cal.App.4th 584, 593.)",
            "The juvenile court erred in failing to grant the request for replacement counsel under People v. Marsden. (In re Z.N. (2010) 181 Cal.App.4th 282, 294.)",
            "The juvenile court abused its discretion in denying the request to continue the matter. (Welf. & Inst. Code, § 352, subd. (a); In re Giovanni F. (2010) 184 Cal.App.4th 594, 605.)",
        ]
        legacy_labels = [
            "Suff. of Evid. for Jurisdiction",
            "Suff. of Evid. for Removal",
            "Cal-ICWA Inquiry",
            "Beneficial Relationship Exception",
            "Adoptability",
            "Denial of Section 388 Petition",
            "Summary Denial of Section 388 Petition",
            "Marsden Error",
            "Denial of Continuance Request",
        ]
        expected_questions = [
            "Did substantial evidence support the juvenile court's exercise of dependency jurisdiction over the child or children under Welfare and Institutions Code section 300?",
            "Did substantial evidence support the juvenile court's order removing the child or children from parental custody under Welfare and Institutions Code section 361, subdivision (c)(1)?",
            "Did the juvenile court abuse its discretion in finding that the child welfare agency conducted an adequate Cal-ICWA inquiry under Welfare and Institutions Code section 224.2?",
            "Did the juvenile court err in finding that the beneficial relationship exception to termination of parental rights did not apply under Welfare and Institutions Code section 366.26, subdivision (c)(1)(B)(i)?",
            "Did clear and convincing evidence support the juvenile court's finding that the child was likely to be adopted within a reasonable time under Welfare and Institutions Code section 366.26, subdivision (c)(1)?",
            "Did the juvenile court err in denying the parent's Welfare and Institutions Code section 388 petition after an evidentiary hearing?",
            "Did the juvenile court err in summarily denying the parent's Welfare and Institutions Code section 388 petition without an evidentiary hearing?",
            "Did the juvenile court err in denying the request for replacement counsel under People v. Marsden?",
            "Did the juvenile court abuse its discretion in denying the request to continue the matter under Welfare and Institutions Code section 352?",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_presets": list(legacy_presets),
                        "appeal_issue_labels": list(legacy_labels),
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.appeal_issue_presets, expected_questions)
        self.assertEqual(config.appeal_issue_labels, legacy_labels)

    def test_unknown_custom_appeal_issue_presets_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            custom = [
                "Was the hearsay ruling correct?",
                "Was the juvenile court's evidentiary ruling an abuse of discretion?",
            ]
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_presets": custom,
                        "appeal_issue_labels": ["Hearsay", "Evidence"],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.appeal_issue_presets, custom)
        self.assertEqual(config.appeal_issue_labels, ["Hearsay", "Evidence"])

    def test_custom_appeal_prompt_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(appeal_issue_agent_prompt_template="Custom appeal {issue}"),
                path,
            )

            self.assertEqual(
                load_config(path).appeal_issue_agent_prompt_template,
                "Custom appeal {issue}",
            )

    def test_custom_later_treatment_prompt_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    later_treatment_agent_prompt_template="Custom later {cluster_id}"
                ),
                path,
            )

            self.assertEqual(
                load_config(path).later_treatment_agent_prompt_template,
                "Custom later {cluster_id}",
            )

    def test_default_later_treatment_prompt_is_bounded(self) -> None:
        prompt = DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
        # Fixed discovery ceiling: one graph command, at most two searches.
        self.assertIn("exactly once", prompt)
        self.assertIn("at most these two non-paginated CourtListener searches", prompt)
        self.assertIn("Only if still needed, one exact case-name search", prompt)
        self.assertIn("{published_citing_cases_command}", prompt)
        self.assertIn("{citation_search_command}", prompt)
        self.assertIn("{case_name_search_command}", prompt)
        self.assertIn("{compact_extract_command}", prompt)
        self.assertIn("{recover_official_extract_command}", prompt)
        self.assertIn("{full_extract_command}", prompt)
        self.assertIn("stop and report that subsequent-treatment coverage is limited", prompt)
        # Recovery contract: parallel compact baselines, one sequential
        # recovery-enabled extraction per case, one full extraction, no
        # second recovery, and a linked unpaginated fallback.
        self.assertIn("Issue compact baseline extractions", prompt)
        self.assertIn("exactly one sequential recovery-enabled extraction", prompt)
        self.assertIn("single Scholar attempt", prompt)
        self.assertIn("Never run a second recovery attempt for the same case", prompt)
        self.assertIn("one ordinary full extraction", prompt)
        self.assertIn("official_pagination", prompt)
        self.assertIn("source_url", prompt)
        self.assertIn("Three to five cases is a ceiling and a preference, not a quota", prompt)
        self.assertIn("use fewer when only fewer can be verified", prompt)
        self.assertIn("disclose incomplete CourtListener coverage", prompt)
        self.assertIn("link the case name or citation to the `source_url`", prompt)
        self.assertIn("When no source URL was returned, say so", prompt)
        self.assertIn("Omit any treatment characterization the extracted text does not support", prompt)
        self.assertIn("Rely on the best citation returned by the bounded sources", prompt)
        self.assertIn("State plainly when a citation remains uncertain", prompt)
        # No generic-web, manual Scholar, alternate-site, or manual slip
        # fallback is permitted anywhere in the mode.
        self.assertIn("Never use generic web search, Pi `web_search`", prompt)
        self.assertIn("never manually call `extract-slip-opinion` or `lookup-citation`", prompt)
        self.assertIn("Never orchestrate Scholar or any browser step yourself", prompt)
        self.assertIn("alternate opinion sites", prompt)
        self.assertIn("Never use unpublished cases as controlling treatment", prompt)
        self.assertNotIn("Codex web search", prompt)
        self.assertNotIn("as a fallback to verify or fill in", prompt)
        # Commands arrive as app-supplied placeholders; no hand-written syntax.
        self.assertNotIn("case-search", prompt)
        self.assertNotIn("--json", prompt)

    def test_stale_later_treatment_prompts_migrate_to_new_default(self) -> None:
        superseded_default = (
            (
            """
You are the Open Law Lens Subsequent Treatment Agent.

Analyze how subsequent published California cases treated the currently viewed case. Use Open Law Lens CLI commands for CourtListener-backed discovery and extraction, but use judgment about which commands and searches will best answer the treatment question.

Target case: {target_title}
Target official citation: {target_citation}
CourtListener cluster id: {cluster_id}

Start with this Open Law Lens citing-cases command when the cluster id is accepted:
{published_citing_cases_command}

If that command fails, returns no useful leads, or the cluster id appears to be a local external id, recover with targeted Open Law Lens case searches using the target case name, official citation, and distinctive citation phrases. Treat search results as leads only.

Choose only the most significant published subsequent cases, usually 3 to 5 when that many exist. Before relying on any selected case, extract it with:
$OLL extract-case --cluster-id <cluster_id>

Rely first on enhanced `extract-case`, which supplies the CourtListener/slip baseline. If a relied-on published case is still unpaginated, perform one confined default-browser Google Scholar recovery; on no result or no qualifying markers, rely on the baseline with a disclosed pagination limitation. Never use generic web search as an official-copy fallback. State when a citation remains uncertain.

For each selected subsequent case, explain how it used the target case: agreed with it, distinguished it, limited it, extended it to a different fact pattern, criticized it, or used it in another identifiable way. If a citation lead exists but extracted or verified text does not support a treatment characterization, say that plainly.

Prefer California Supreme Court and published California Court of Appeal decisions. Do not use unpublished cases as controlling treatment. Keep the answer concise and include the official citation for each later case. In the final answer, use normal legal prose for case names and citations; reserve backticks for CLI commands, file paths, and other literal technical text.
            """
        ).replace(
                "$OLL", AGENT_CLI_COMMAND_PREFIX
            )
        )
        stale_local = (
            (
            """
You are the Open Law Lens Subsequent Treatment Agent.

Analyze how subsequent published California cases treated the currently viewed case. Use Open Law Lens CLI commands for CourtListener-backed discovery and extraction, but use judgment about which commands and searches will best answer the treatment question.

Target case: {target_title}
Target official citation: {target_citation}
CourtListener cluster id: {cluster_id}

Start with this Open Law Lens citing-cases command when the cluster id is accepted:
{published_citing_cases_command}

If that command fails, returns no useful leads, or the cluster id appears to be a local external id, recover with targeted Open Law Lens case searches using the target case name, official citation, and distinctive citation phrases. Treat search results as leads only.

Choose only the most significant published subsequent cases, usually 3 to 5 when that many exist. Before relying on any selected case, extract it with:
uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case --cluster-id <cluster_id>

If CourtListener extraction lacks an official reporter citation or official text for a selected subsequent case, use Google Scholar, California Courts, or Codex web search only as a fallback to verify or fill in that citation/text. State when a citation remains uncertain.

For each selected subsequent case, explain how it used the target case: agreed with it, distinguished it, limited it, extended it to a different fact pattern, criticized it, or used it in another identifiable way. If a citation lead exists but extracted or verified text does not support a treatment characterization, say that plainly.

Do not use unpublished cases as controlling treatment. Keep the answer concise and include the official citation for each later case.
            """
        )
        )
        for legacy in (superseded_default, stale_local):
            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "config.json"
                path.write_text(
                    json.dumps(
                        {
                            "subsequent_treatment_agent_prompt_template": legacy,
                            "courtlistener_token": "token-value",
                        }
                    ),
                    encoding="utf-8",
                )
                config = load_config(path)
                self.assertEqual(
                    config.later_treatment_agent_prompt_template,
                    DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
                )
                self.assertEqual(config.courtlistener_token, "token-value")

    def test_saved_default_later_treatment_prompt_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    courtlistener_token="token-value",
                    later_treatment_agent_prompt_template=(
                        DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
                    ),
                    reader_font_size_pt=13,
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(
                config.later_treatment_agent_prompt_template,
                DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
            )
            self.assertEqual(config.courtlistener_token, "token-value")
            self.assertEqual(config.reader_font_size_pt, 13)

    def test_legacy_later_treatment_prompt_key_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "later_treatment_agent_prompt_template": (
                            "Legacy later {cluster_id}"
                        )
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                load_config(path).later_treatment_agent_prompt_template,
                "Legacy later {cluster_id}",
            )

    def test_bare_statute_law_code_falls_back_to_wic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(default_bare_statute_law_code="unsupported"), path)

            self.assertEqual(load_config(path).default_bare_statute_law_code, "WIC")

    def test_appeal_issue_presets_fall_back_when_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"appeal_issue_presets": ["", "   "]}),
                encoding="utf-8",
            )

            self.assertEqual(load_config(path).appeal_issue_presets, list(DEFAULT_APPEAL_ISSUE_PRESETS))
            self.assertEqual(load_config(path).appeal_issue_labels, list(DEFAULT_APPEAL_ISSUE_LABELS))

    def test_appeal_issue_labels_align_with_presets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "appeal_issue_presets": ["Argument one.", "Argument two."],
                        "appeal_issue_labels": ["One"],
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.appeal_issue_presets, ["Argument one.", "Argument two."])
            self.assertEqual(config.appeal_issue_labels, ["One", ""])

    def test_custom_appeal_issue_presets_do_not_inherit_default_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(appeal_issue_presets=["Custom argument."]), path)

            config = load_config(path)

            self.assertEqual(config.appeal_issue_presets, ["Custom argument."])
            self.assertEqual(config.appeal_issue_labels, [""])

    def test_reader_font_settings_are_coerced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(
                AppConfig(
                    reader_font_size_pt=100,
                    reader_font_family="Century Schoolbook",
                ),
                path,
            )
            config = load_config(path)
            self.assertEqual(config.reader_font_size_pt, 48)
            self.assertEqual(config.reader_font_family, "Century Schoolbook")

    def test_century_schoolbook_reader_font_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(reader_font_family="Century Schoolbook"), path)

            self.assertEqual(load_config(path).reader_font_family, "Century Schoolbook")

    def test_reader_font_options_include_installed_readability_choices(self) -> None:
        names = [name for name, _css in READER_FONT_FAMILY_OPTIONS]

        self.assertEqual(
            names,
            [
                "Noto Serif",
                "Bitstream Charter",
                "Linux Libertine O",
                "Caladea",
                "Gentium Book Basic",
                "DejaVu Serif",
                "Century Schoolbook",
                "TeX Gyre Schola",
                "Lato",
            ],
        )

    def test_removed_reader_fonts_migrate_to_installed_alternatives(self) -> None:
        replacements = {
            "Georgia": "Caladea",
            "Merriweather": "Bitstream Charter",
            "Source Sans 3": "Lato",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            for removed, replacement in replacements.items():
                path.write_text(json.dumps({"reader_font_family": removed}))
                self.assertEqual(load_config(path).reader_font_family, replacement)

    def test_environment_concordance_path_overrides_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            save_config(AppConfig(concordance_file_path="/saved/path.sdi"), path)
            with patch.dict(os.environ, {"OPEN_LAW_LENS_CONCORDANCE_FILE": "/env/path.sdi"}):
                self.assertEqual(load_config(path).concordance_file_path, "/env/path.sdi")


if __name__ == "__main__":
    unittest.main()
