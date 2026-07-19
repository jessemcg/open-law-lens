from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
WRAPPER = PROJECT_DIR / "scripts" / "open-law-lens-agent-vte.sh"


class AgentVteWrapperTests(unittest.TestCase):
    def _fixture(self, root: Path, *, bundle_web_search: bool) -> tuple[Path, Path, Path]:
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
        if bundle_web_search:
            package = project / ".pi" / "extensions" / "pi-web-search"
            (package / "src").mkdir(parents=True)
            (package / "src" / "index.ts").write_text("", encoding="utf-8")
            (package / "package.json").write_text(
                '{"name":"pi-web-search","version":"1.3.1"}',
                encoding="utf-8",
            )
        prompt.write_text("Research this issue.", encoding="utf-8")
        return project, workspace, prompt

    def _fake_pi(
        self,
        root: Path,
        *,
        with_sibling_node: bool = False,
    ) -> tuple[Path, Path]:
        executable = root / "pi"
        output = root / "pi-arguments.txt"
        executable.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n"
            "printf '%s\\n' \"$PI_CODING_AGENT_SESSION_DIR\" >> \"$CAPTURE_ARGS\"\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
        if with_sibling_node:
            node = root / "node"
            node.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n"
                "printf '%s\\n' \"$PI_CODING_AGENT_SESSION_DIR\" >> \"$CAPTURE_ARGS\"\n",
                encoding="utf-8",
            )
            node.chmod(0o755)
        return executable, output

    def _run(
        self,
        root: Path,
        mode: str,
        *,
        with_sibling_node: bool = False,
    ) -> list[str]:
        project, workspace, prompt = self._fixture(
            root,
            bundle_web_search=mode in {"general", "appeal"},
        )
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
                "CAPTURE_ARGS": str(output),
            }
        )
        subprocess.run(["bash", str(WRAPPER)], env=env, check=True)
        return output.read_text(encoding="utf-8").splitlines()

    def test_research_mode_loads_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = self._run(root, "general")
            self.assertIn("--skill", args)
            self.assertIn("--extension", args)
            extension_index = args.index("--extension")
            self.assertEqual(
                args[extension_index + 1],
                str(
                    root
                    / "workspace"
                    / ".pi"
                    / "extensions"
                    / "pi-web-search"
                    / "src"
                    / "index.ts"
                ),
            )
            self.assertIn("read,bash,grep,find,ls,web_search", args)
            self.assertNotIn("--thinking", args)
            self.assertTrue(any(item.startswith("/skill:legal-researcher") for item in args))
            self.assertEqual(args[-1], str(root / "workspace" / "pi-sessions"))

    def test_research_mode_uses_node_shipped_beside_pi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            args = self._run(
                root,
                "general",
                with_sibling_node=True,
            )

            self.assertEqual(args[0], str(root / "pi"))
            self.assertIn("--extension", args)
            self.assertIn("read,bash,grep,find,ls,web_search", args)

    def test_closed_corpus_mode_disables_skill_and_web_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            args = self._run(Path(temp_dir), "case")
            self.assertIn("--no-skills", args)
            self.assertIn("--no-extensions", args)
            self.assertNotIn("--skill", args)
            self.assertNotIn("--extension", args)
            self.assertIn("read,bash,grep,find,ls", args)
            self.assertNotIn("read,bash,grep,find,ls,web_search", args)

    def test_research_mode_reports_missing_bundled_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project, workspace, prompt = self._fixture(
                root,
                bundle_web_search=False,
            )
            pi, _output = self._fake_pi(root)
            env = os.environ.copy()
            env.update(
                {
                    "OPEN_LAW_LENS_AGENT_PROMPT_FILE": str(prompt),
                    "OPEN_LAW_LENS_AGENT_WORKSPACE": str(workspace),
                    "OPEN_LAW_LENS_AGENT_MODE": "general",
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
            self.assertIn(
                "Bundled pi-web-search extension not found:",
                result.stderr,
            )
            self.assertNotIn("pi install", result.stderr)

    def test_repository_bundles_pinned_web_search_source(self) -> None:
        settings = json.loads(
            (PROJECT_DIR / ".pi" / "settings.json").read_text(encoding="utf-8")
        )
        package = (
            PROJECT_DIR
            / ".pi"
            / "extensions"
            / "pi-web-search"
            / "package.json"
        )
        metadata = json.loads(package.read_text(encoding="utf-8"))

        self.assertNotIn("packages", settings)
        self.assertEqual(metadata["name"], "pi-web-search")
        self.assertEqual(metadata["version"], "1.3.1")
        self.assertTrue((package.parent / "src" / "index.ts").is_file())
        self.assertTrue((package.parent / "LICENSE").is_file())
