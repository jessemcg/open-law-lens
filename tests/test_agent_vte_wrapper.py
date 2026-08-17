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
            "{\n"
            "  printf '%s\\n' \"${PI_PLANNER_REVIEW_CAPTURE_APP:-}\"\n"
            "  printf '%s\\n' \"${PI_PLANNER_REVIEW_CAPTURE_WORKFLOW:-}\"\n"
            "  printf '%s\\n' \"${PI_PLANNER_REVIEW_CAPTURE_PROJECT_ROOT:-}\"\n"
            "} > \"$CAPTURE_ENV\"\n"
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
        capture_extension: Path | None = None,
    ) -> tuple[list[str], list[str]]:
        project, workspace, prompt = self._fixture(root)
        if mode in {"general", "appeal"}:
            self._install_web_access(root)
        pi, output = self._fake_pi(
            root,
            with_sibling_node=with_sibling_node,
        )
        env_output = root / "pi-capture-env.txt"
        env = os.environ.copy()
        env.update(
            {
                "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                "OPEN_LAW_LENS_AGENT_MODE": mode,
                "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                "OPEN_LAW_LENS_PI_BIN": str(pi),
                "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
                # Guarantee the default PiPlanner capture path is absent so
                # tests never depend on the host machine's installation state.
                "XDG_DATA_HOME": str(root / "data-home"),
                "CAPTURE_ARGS": str(output),
                "CAPTURE_ENV": str(env_output),
            }
        )
        if capture_extension is not None:
            env["PI_PLANNER_REVIEW_CAPTURE_EXTENSION"] = str(capture_extension)
        if profile is not None:
            env.update(
                {
                    "OPEN_LAW_LENS_PI_PROVIDER": profile[0],
                    "OPEN_LAW_LENS_PI_MODEL": profile[1],
                    "OPEN_LAW_LENS_PI_THINKING": profile[2],
                }
            )
        subprocess.run(["bash", str(WRAPPER)], env=env, check=True)
        return (
            output.read_text(encoding="utf-8").splitlines(),
            env_output.read_text(encoding="utf-8").splitlines(),
        )

    def test_research_mode_loads_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args, _env = self._run(root, "general")
            for flag in (
                "--no-extensions",
                "--no-skills",
                "--no-prompt-templates",
                "--no-themes",
                "--no-context-files",
            ):
                self.assertIn(flag, args)
            self.assertIn("--skill", args)
            self.assertIn("--extension", args)
            self.assertEqual(
                args[args.index("--system-prompt") + 1],
                str(root / "workspace" / ".pi" / "SYSTEM.md"),
            )
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
            self.assertTrue(any(item.startswith("/skill:legal-researcher") for item in args))
            self.assertEqual(args[-2], str(root / "workspace" / "pi-sessions"))
            self.assertEqual(args[-1], str(root / "workspace"))

    def test_explicit_runtime_profile_is_passed_to_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args, _env = self._run(
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
            args, _env = self._run(
                root,
                "general",
                with_sibling_node=True,
            )

            self.assertEqual(args[0], str(root / "pi"))
            self.assertIn("--extension", args)
            self.assertIn("read,bash,grep,find,ls,web_search", args)

    def test_appeal_mode_loads_legal_researcher_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args, _env = self._run(Path(temp_dir), "appeal")

        self.assertIn("--skill", args)
        self.assertTrue(any(item.startswith("/skill:legal-researcher") for item in args))

    def test_closed_corpus_mode_disables_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args, _env = self._run(Path(temp_dir), "case")
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
            self.assertEqual(
                args[args.index("--system-prompt") + 1],
                str(Path(temp_dir) / "workspace" / ".pi" / "SYSTEM.md"),
            )
            self.assertIn("read,bash,grep,find,ls", args)
            self.assertNotIn("read,bash,grep,find,ls,web_search", args)

    def test_capture_extension_added_alongside_web_access_in_research_mode(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture = root / "run-review-capture.ts"
            capture.write_text("// capture only\n", encoding="utf-8")
            args, capture_env = self._run(
                root, "general", capture_extension=capture
            )

            extension_paths = [
                args[index + 1]
                for index, flag in enumerate(args)
                if flag == "--extension"
            ]
            self.assertEqual(
                extension_paths,
                [
                    str(capture),
                    str(
                        root
                        / "pi-agent"
                        / "npm"
                        / "node_modules"
                        / "pi-web-access"
                        / "index.ts"
                    ),
                ],
            )
            # The capture extension loads directly after --no-extensions.
            no_extensions = args.index("--no-extensions")
            self.assertEqual(args[no_extensions + 1], "--extension")
            self.assertEqual(args[no_extensions + 2], str(capture))
            # Capture registers no tools; the allowlist is unchanged.
            self.assertIn("read,bash,grep,find,ls,web_search", args)
            self.assertEqual(
                capture_env,
                ["open-law-lens", "general", str(root / "project")],
            )

    def test_capture_extension_added_in_closed_corpus_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capture = root / "run-review-capture.ts"
            capture.write_text("// capture only\n", encoding="utf-8")
            args, capture_env = self._run(
                root, "brief", capture_extension=capture
            )

            extension_paths = [
                args[index + 1]
                for index, flag in enumerate(args)
                if flag == "--extension"
            ]
            self.assertEqual(extension_paths, [str(capture)])
            self.assertIn("read,bash,grep,find,ls", args)
            self.assertNotIn("read,bash,grep,find,ls,web_search", args)
            self.assertEqual(
                capture_env,
                ["open-law-lens", "brief", str(root / "project")],
            )

    def test_capture_absent_warns_and_still_launches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, workspace, prompt = self._fixture(root)
            pi, output = self._fake_pi(root)
            env = os.environ.copy()
            env.update(
                {
                    "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                    "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                    "OPEN_LAW_LENS_AGENT_MODE": "case",
                    "OPEN_LAW_LENS_PROJECT_DIR": str(project),
                    "OPEN_LAW_LENS_PI_BIN": str(pi),
                    "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
                    "XDG_DATA_HOME": str(root / "data-home"),
                    "CAPTURE_ARGS": str(output),
                    "CAPTURE_ENV": str(root / "pi-capture-env.txt"),
                }
            )

            result = subprocess.run(
                ["bash", str(WRAPPER)],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn(
                "Open Law Lens review capture unavailable:", result.stderr
            )
            args = output.read_text(encoding="utf-8").splitlines()
            self.assertIn("--no-extensions", args)
            self.assertNotIn("--extension", args)

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
        self.assertIn("names the specific appellate", text)
        self.assertIn("`## Assessment`", text)
        self.assertIn("treat the supplied fact pattern as the complete", text)
        self.assertIn("do not add a generic record-completeness caveat", text)
        self.assertIn("missing record citation only where it affects", text)
        self.assertIn("material gaps in\n  the available legal sources", text)
        self.assertIn(
            'uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync '
            "open-law-lens <command>",
            text,
        )
