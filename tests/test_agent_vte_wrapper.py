from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-agent-vte.sh"
LEGAL_RESEARCHER_SKILL = (
    PROJECT_DIR / ".pi" / "skills" / "legal-researcher" / "SKILL.md"
)


class AgentVteWrapperTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        project = root / "project"
        workspace = root / "workspace"
        prompt = root / "prompt.txt"
        skill = project / ".pi" / "skills" / "legal-researcher" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: legal-researcher\ndescription: Test.\n---\n", encoding="utf-8")
        (project / ".pi" / "settings.json").write_text(
            json.dumps(
                {
                    "defaultProvider": "openai-codex",
                    "defaultModel": "gpt-5.6-sol",
                }
            ),
            encoding="utf-8",
        )
        (project / ".pi" / "SYSTEM.md").write_text(
            "Open Law Lens legal knowledge work", encoding="utf-8"
        )
        prompt.write_text("Research this issue.", encoding="utf-8")
        return project, workspace, prompt

    @staticmethod
    def _install_web_access(root: Path) -> Path:
        package = root / "pi-agent" / "npm" / "node_modules" / "pi-web-access"
        package.mkdir(parents=True)
        (package / "index.ts").write_text("", encoding="utf-8")
        (package / "package.json").write_text(
            '{"name":"pi-web-access","version":"0.19.0"}',
            encoding="utf-8",
        )
        return package

    def _fake_pi(
        self,
        root: Path,
        *,
        with_sibling_node: bool = False,
    ) -> tuple[Path, Path]:
        executable = root / "pi"
        output = root / "pi-arguments.txt"
        fake_script = (
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n"
            "printf '%s\\n' \"$PI_CODING_AGENT_SESSION_DIR\" >> \"$CAPTURE_ARGS\"\n"
            "printf '%s\\n' \"$PWD\" >> \"$CAPTURE_ARGS\"\n"
        )
        executable.write_text(fake_script, encoding="utf-8")
        executable.chmod(0o755)
        if with_sibling_node:
            node = root / "node"
            node.write_text(fake_script, encoding="utf-8")
            node.chmod(0o755)
        return executable, output

    def _run(
        self,
        root: Path,
        mode: str,
        *,
        with_sibling_node: bool = False,
        profile: tuple[str, str, str] | None = None,
    ) -> tuple[list[str], str]:
        project, workspace, prompt = self._fixture(root)
        if mode in {"general", "appeal"}:
            self._install_web_access(root)
        pi, output = self._fake_pi(
            root,
            with_sibling_node=with_sibling_node,
        )
        env = os.environ.copy()
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                "OPEN_LAW_LENS_AGENT_MODE": mode,
                "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                "OPEN_LAW_LENS_PI_BIN": str(pi),
                "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
                "CAPTURE_ARGS": str(output),
            }
        )
        if profile is not None:
            env.update(
                {
                    "OPEN_LAW_LENS_PI_PROVIDER": profile[0],
                    "OPEN_LAW_LENS_PI_MODEL": profile[1],
                    "OPEN_LAW_LENS_PI_THINKING": profile[2],
                }
            )
        completed = subprocess.run(
            ["bash", str(WRAPPER)], env=env, check=True,
            capture_output=True, text=True,
        )
        return output.read_text(encoding="utf-8").splitlines(), completed.stderr

    def test_research_mode_loads_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args, stderr = self._run(root, "general")
            for flag in (
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-themes",
                "--no-context-files",
            ):
                self.assertIn(flag, args)
            self.assertNotIn("--skill", args)
            self.assertFalse(any(item.startswith("/skill:legal-researcher") for item in args))
            self.assertEqual(args.count("--extension"), 1)
            self.assertNotIn("capture", stderr.lower())
            system_prompt_path = Path(args[args.index("--system-prompt") + 1])
            self.assertEqual(
                str(system_prompt_path),
                str(root / "workspace" / ".pi" / "SYSTEM.md"),
            )
            system_prompt = system_prompt_path.read_text(encoding="utf-8")
            self.assertEqual(system_prompt.count("name: legal-researcher"), 1)
            self.assertIn("Open Law Lens legal knowledge work", system_prompt)
            extension_index = args.index("--extension")
            self.assertEqual(
                args[extension_index + 1],
                str(
                    root
                    / "pi-agent"
                    / "npm"
                    / "node_modules"
                    / "pi-web-access"
                    / "index.ts"
                ),
            )
            self.assertIn("read,bash,grep,find,ls,web_search", args)
            self.assertNotIn("--thinking", args)
            self.assertEqual(args[-2], str(root / "workspace" / "pi-sessions"))
            self.assertEqual(args[-1], str(root / "workspace"))

    def test_explicit_runtime_profile_is_passed_to_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args, stderr = self._run(
                Path(temp_dir),
                "brief",
                profile=(
                    "fireworks",
                    "accounts/fireworks/routers/glm-fast",
                    "low",
                ),
            )

        self.assertEqual(args[args.index("--provider") + 1], "fireworks")
        self.assertEqual(
            args[args.index("--model") + 1],
            "accounts/fireworks/routers/glm-fast",
        )
        self.assertEqual(args[args.index("--thinking") + 1], "low")

    def test_incomplete_runtime_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, workspace, prompt = self._fixture(root)
            pi, _output = self._fake_pi(root)
            env = os.environ.copy()
            env.update(
                {
                    "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                    "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                    "OPEN_LAW_LENS_AGENT_MODE": "brief",
                    "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                    "OPEN_LAW_LENS_PI_BIN": str(pi),
                    "OPEN_LAW_LENS_PI_PROVIDER": "fireworks",
                }
            )

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("requires provider, model, and thinking", result.stderr)

    def test_research_mode_uses_node_shipped_beside_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args, stderr = self._run(
                root,
                "general",
                with_sibling_node=True,
            )

            self.assertEqual(args[0], str(root / "pi"))
            self.assertIn("--extension", args)
            self.assertIn("read,bash,grep,find,ls,web_search", args)

    def test_appeal_mode_preloads_legal_researcher_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args, stderr = self._run(root, "appeal")

            self.assertNotIn("--skill", args)
            self.assertFalse(any(item.startswith("/skill:legal-researcher") for item in args))
            system_prompt = Path(args[args.index("--system-prompt") + 1]).read_text(
                encoding="utf-8"
            )
            self.assertEqual(system_prompt.count("name: legal-researcher"), 1)

    def test_closed_corpus_mode_disables_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args, stderr = self._run(Path(temp_dir), "case")
            for flag in (
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-themes",
                "--no-context-files",
            ):
                self.assertIn(flag, args)
            self.assertNotIn("--skill", args)
            self.assertNotIn("--extension", args)
            self.assertNotIn("capture", stderr.lower())
            system_prompt = Path(args[args.index("--system-prompt") + 1]).read_text(
                encoding="utf-8"
            )
            self.assertEqual(
                args[args.index("--system-prompt") + 1],
                str(Path(temp_dir) / "workspace" / ".pi" / "SYSTEM.md"),
            )
            self.assertNotIn("name: legal-researcher", system_prompt)
            self.assertIn("read,bash,grep,find,ls", args)
            self.assertNotIn("read,bash,grep,find,ls,web_search", args)

    def test_research_mode_reports_missing_user_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, workspace, prompt = self._fixture(root)
            pi, _output = self._fake_pi(root)
            env = os.environ.copy()
            env.update(
                {
                    "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                    "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                    "OPEN_LAW_LENS_AGENT_MODE": "general",
                    "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                    "OPEN_LAW_LENS_PI_BIN": str(pi),
                    "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
                }
            )

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "User-level pi-web-access extension not found:",
                result.stderr,
            )
            self.assertIn("pi install npm:pi-web-access", result.stderr)

    def test_wrapper_rejects_missing_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, workspace, prompt = self._fixture(root)
            (project / ".pi" / "SYSTEM.md").unlink()
            pi, _output = self._fake_pi(root)
            env = os.environ.copy()
            env.update(
                {
                    "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                    "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                    "OPEN_LAW_LENS_AGENT_MODE": "case",
                    "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                    "OPEN_LAW_LENS_PI_BIN": str(pi),
                }
            )

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Pi system prompt not found or empty", result.stderr)

    def test_repository_does_not_vendor_web_access(self) -> None:
        settings = json.loads(
            (PROJECT_DIR / ".pi" / "settings.json").read_text(encoding="utf-8")
        )

        self.assertNotIn("packages", settings)
        self.assertFalse((PROJECT_DIR / ".pi" / "extensions").exists())
        system_prompt = (PROJECT_DIR / ".pi" / "SYSTEM.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("California legal researcher", system_prompt)
        self.assertIn("not a coding assistant", system_prompt)
        self.assertIn("private, disposable runtime workspace", system_prompt)

    def test_appeal_skill_requires_issue_specific_heading_and_complete_record(
        self,
    ) -> None:
        text = LEGAL_RESEARCHER_SKILL.read_text(encoding="utf-8")

        self.assertIn("For Appeal Issue research", text)
        self.assertIn("make the required H1 title issue-specific", text)
        self.assertIn("`# Assessment`", text)
        self.assertIn("treat the supplied fact pattern as the complete", text)
        self.assertIn("do not add a generic record-completeness caveat", text)
        self.assertIn("missing record citation only where it affects", text)
        self.assertIn("material gaps in\n  the available legal sources", text)
        self.assertIn(
            'uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync '
            "open-law-lens <command>",
            text,
        )

    def test_skill_contract_case_floor_and_audit_and_no_h1_h2_conflict(
        self,
    ) -> None:
        text = LEGAL_RESEARCHER_SKILL.read_text(encoding="utf-8")
        system = (PROJECT_DIR / ".pi" / "SYSTEM.md").read_text(encoding="utf-8")

        # An explicit two-route gate replaces the discretionary "ask whether;
        # if so" formulation. The old wording must not survive.
        self.assertIn("Route gate", text)
        self.assertIn("Route A", text)
        self.assertIn("Route B", text)
        self.assertNotIn("ask whether", text.lower())
        self.assertNotIn("; if so", text)

        # Legal-status and term-of-art questions are explicitly case-required.
        self.assertIn(
            "mandatory enactment-plus-case route",
            text,
        )
        self.assertIn(
            "definition\nor explanation of a legal status, doctrine, test, standard, or term of art",
            text,
        )
        self.assertIn("least one leading published California case", text)

        # The presumed-father example is explicitly outside the enactment-only
        # exception.
        self.assertIn("presumed father", text)
        self.assertIn(
            "mandatory-case (Route B) example, not a purely textual definition",
            text,
        )

        # The enactment-only exception is limited to requests that remain
        # entirely textual.
        self.assertIn("narrow enactment-only exception", text)
        self.assertIn("confined to that text", text)
        self.assertIn("Do not define a", text)
        self.assertIn(
            "legal status, doctrine, test, standard, or term of art inside this route",
            text,
        )

        # A mandatory route requires successful extraction and a final
        # citation, and refuses silent downgrade to enactment-only.
        self.assertIn(
            "successfully extract and cite",
            text,
        )
        self.assertIn(
            "Do not silently decide that the statutes are \"enough\"",
            text,
        )
        self.assertIn(
            "disclose the case-law verification gap and confine",
            text,
        )

        # Direct bounded extraction and same-round parallelism remain preferred
        # over broad discovery.
        self.assertIn(
            'extract-case "<citation>" --find "<term>"',
            text,
        )
        self.assertIn(
            "independent statute/rule and known-case extractions in the same tool",
            text,
        )
        self.assertIn(
            "Stop after the current enactment and the minimum case authority",
            text,
        )
        self.assertIn("run exactly one focused search", text)

        # The pre-answer audit is a source gate: every mandatory trigger needs
        # a case extraction plus a normalized citation in the body, and each
        # proposition must trace to a directly extracted case.
        self.assertIn("audit the title, subtitle, and body", text)
        self.assertIn("successful\n  case extraction and a corresponding normalized case citation", text)
        self.assertIn("Reconcile opening clauses", text)
        self.assertIn(
            'Preserve every material "except," "unless," "may," "must," and "only"',
            text,
        )
        self.assertIn(
            "Do not cite a case mentioned inside another opinion",
            text,
        )
        self.assertIn("regardless of biology", text)
        self.assertIn(
            'An amendment note proves an effective date, not that an amendment changed',
            text,
        )

        # The merged prompt contains no H1/H2 conflict: the skill defers to the
        # system's required H1 title and no longer prescribes a level-two
        # heading for the Appeal answer.
        self.assertIn("# Specific Issue Title", system)
        self.assertIn("*Short disposition*", system)
        self.assertIn("make the required H1 title issue-specific", text)
        self.assertIn("`# Cal-ICWA Inquiry`", text)
        self.assertNotIn("level-two", text)
        self.assertNotIn("`## Cal-ICWA Inquiry`", text)
        self.assertNotIn("`## Assessment`", text)

    def _minimal_env(self, root: Path, mode: str = "case") -> dict[str, str]:
        project, workspace, prompt = self._fixture(root)
        pi, output = self._fake_pi(root)
        env = os.environ.copy()
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                "OPEN_LAW_LENS_AGENT_MODE": mode,
                "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                "OPEN_LAW_LENS_PI_BIN": str(pi),
                "CAPTURE_ARGS": str(output),
                "PATH": "/usr/bin:/bin",
            }
        )
        return env

    @staticmethod
    def _write_executable(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    def test_missing_uv_fails_before_pi_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = self._minimal_env(root)
            env["HOME"] = str(root / "no-uv-home")
            (root / "no-uv-home").mkdir(parents=True)

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 127)
        self.assertIn("requires the uv executable", result.stderr)

    def test_uv_resolved_from_home_local_bin_on_minimal_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = self._minimal_env(root)
            home = root / "home"
            self._write_executable(home / ".local" / "bin" / "uv")
            env["HOME"] = str(home)

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_uv_override_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = self._minimal_env(root)
            override = root / "uv-override"
            self._write_executable(override)
            env["OPEN_LAW_LENS_UV_BIN"] = str(override)

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
