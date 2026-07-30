from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.pi_runtime import (
    PiModel,
    PiRuntimeError,
    PiSettingsError,
    _pi_rpc_response,
    available_pi_models,
    available_pi_runtime_catalog,
    clamp_pi_thinking_level,
    current_pi_runtime_defaults,
    current_project_pi_model,
    find_pi_node_executable,
    save_project_pi_model,
)


class PiRuntimeTests(unittest.TestCase):
    def test_available_models_uses_rpc_and_sorts_deduplicated_models(self) -> None:
        response = {
            "type": "response",
            "command": "get_available_models",
            "success": True,
            "data": {
                "models": [
                    {
                        "provider": "openai-codex",
                        "id": "gpt-5.6-sol",
                        "name": "GPT-5.6 Sol",
                        "reasoning": True,
                        "thinkingLevelMap": {
                            "xhigh": "xhigh",
                            "max": "max",
                        },
                    },
                    {
                        "provider": "fireworks",
                        "id": "accounts/fireworks/models/glm-5p2",
                        "name": "GLM 5.2",
                        "reasoning": False,
                    },
                    {
                        "provider": "fireworks",
                        "id": "accounts/fireworks/models/glm-5p2",
                        "name": "GLM 5.2",
                        "reasoning": False,
                    },
                    {"provider": "", "id": "invalid"},
                ]
            },
        }
        with (
            patch(
                "open_law_lens.pi_runtime.pi_command",
                return_value=["/runtime/node", "/runtime/pi"],
            ),
            patch(
                "open_law_lens.pi_runtime._pi_rpc_response",
                return_value=response,
            ) as rpc,
        ):
            models = available_pi_models()

        self.assertEqual(
            [model.settings_key for model in models],
            [
                ("fireworks", "accounts/fireworks/models/glm-5p2"),
                ("openai-codex", "gpt-5.6-sol"),
            ],
        )
        self.assertEqual(models[1].label, "GPT-5.6 Sol — openai-codex")
        self.assertEqual(models[0].supported_thinking_levels, ("off",))
        self.assertEqual(
            models[1].supported_thinking_levels[-2:],
            ("xhigh", "max"),
        )
        command = rpc.call_args.args[0]
        self.assertEqual(command[:2], ["/runtime/node", "/runtime/pi"])
        self.assertIn("--mode", command)
        self.assertIn("--offline", command)
        self.assertIn("--no-extensions", command)
        self.assertEqual(
            rpc.call_args.args[1],
            {"type": "get_available_models"},
        )

    def test_current_runtime_defaults_use_rpc_state_and_clamp_thinking(self) -> None:
        response = {
            "type": "response",
            "command": "get_state",
            "success": True,
            "data": {
                "model": {
                    "provider": "fireworks",
                    "id": "fast-model",
                    "name": "Fast Model",
                    "reasoning": False,
                },
                "thinkingLevel": "max",
            },
        }
        with (
            patch("open_law_lens.pi_runtime._pi_rpc_command", return_value=["pi"]),
            patch(
                "open_law_lens.pi_runtime._pi_rpc_response",
                return_value=response,
            ) as rpc,
        ):
            model, thinking = current_pi_runtime_defaults()

        self.assertEqual(model.settings_key, ("fireworks", "fast-model"))
        self.assertEqual(thinking, "off")
        self.assertEqual(rpc.call_args.args[1], {"type": "get_state"})

    def test_runtime_catalog_combines_models_and_effective_defaults(self) -> None:
        model = PiModel(
            provider="openai-codex",
            model_id="gpt-5.6-sol",
            name="GPT-5.6 Sol",
        )
        with (
            patch(
                "open_law_lens.pi_runtime.available_pi_models",
                return_value=[model],
            ),
            patch(
                "open_law_lens.pi_runtime.current_pi_runtime_defaults",
                return_value=(model, "high"),
            ),
        ):
            catalog = available_pi_runtime_catalog()

        self.assertEqual(catalog.models, (model,))
        self.assertEqual(catalog.default_model, model)
        self.assertEqual(catalog.default_thinking_level, "high")

    def test_clamp_thinking_uses_nearest_supported_pi_level(self) -> None:
        model = PiModel(
            provider="fireworks",
            model_id="fast-model",
            name="Fast Model",
            supported_thinking_levels=("off", "low", "high"),
        )

        self.assertEqual(clamp_pi_thinking_level(model, "medium"), "high")
        self.assertEqual(clamp_pi_thinking_level(model, "max"), "high")

    def test_available_models_reports_process_failure(self) -> None:
        with (
            patch("open_law_lens.pi_runtime.pi_command", return_value=["pi"]),
            patch(
                "open_law_lens.pi_runtime._pi_rpc_response",
                side_effect=PiRuntimeError("authentication failed"),
            ),
        ):
            with self.assertRaisesRegex(PiRuntimeError, "authentication failed"):
                available_pi_models()

    def test_rpc_keeps_stdin_open_until_response(self) -> None:
        response = _pi_rpc_response(
            [
                sys.executable,
                "-c",
                (
                    "import json,sys;"
                    "request=json.loads(sys.stdin.readline());"
                    "print(json.dumps({'type':'response','command':request['type'],"
                    "'success':True,'data':{'models':[]}}),flush=True);"
                    "sys.stdin.read()"
                ),
            ],
            {"type": "get_available_models"},
            timeout=2,
        )

        self.assertTrue(response["success"])

    def test_rpc_reports_timeout(self) -> None:
        with self.assertRaisesRegex(PiRuntimeError, "timed out"):
            _pi_rpc_response(
                [
                    sys.executable,
                    "-c",
                    "import sys,time;sys.stdin.readline();time.sleep(5)",
                ],
                {"type": "get_available_models"},
                timeout=0.05,
            )

    def test_available_models_rejects_missing_rpc_response(self) -> None:
        with self.assertRaisesRegex(PiRuntimeError, "did not return"):
            _pi_rpc_response(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json,sys;"
                        "sys.stdin.readline();"
                        "print(json.dumps({'type':'response','command':'get_state',"
                        "'success':True}),flush=True)"
                    ),
                ],
                {"type": "get_available_models"},
                timeout=2,
            )

    def test_finds_node_shipped_beside_pi_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime_bin = root / "runtime" / "bin"
            runtime_bin.mkdir(parents=True)
            pi = runtime_bin / "pi"
            node = runtime_bin / "node"
            pi.write_text("", encoding="utf-8")
            node.write_text("", encoding="utf-8")
            node.chmod(0o755)
            launcher_dir = root / "launcher"
            launcher_dir.mkdir()
            launcher = launcher_dir / "pi"
            launcher.symlink_to(pi)

            self.assertEqual(find_pi_node_executable(str(launcher)), str(node))

    def test_reads_and_atomically_updates_project_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "defaultProvider": "openai-codex",
                        "defaultModel": "gpt-5.6-sol",
                        "enableSkillCommands": True,
                        "futureSetting": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                current_project_pi_model(path),
                ("openai-codex", "gpt-5.6-sol"),
            )
            save_project_pi_model(
                PiModel(
                    provider="fireworks",
                    model_id="accounts/fireworks/models/glm-5p2",
                    name="GLM 5.2",
                ),
                path,
            )

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["defaultProvider"], "fireworks")
            self.assertEqual(
                saved["defaultModel"],
                "accounts/fireworks/models/glm-5p2",
            )
            self.assertTrue(saved["enableSkillCommands"])
            self.assertEqual(saved["futureSetting"], {"enabled": True})
            self.assertEqual(list(path.parent.glob(".settings.json.*.tmp")), [])

    def test_invalid_project_settings_are_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("{invalid", encoding="utf-8")

            with self.assertRaises(PiSettingsError):
                save_project_pi_model(
                    PiModel(
                        provider="openai-codex",
                        model_id="gpt-5.6-sol",
                        name="GPT-5.6 Sol",
                    ),
                    path,
                )

            self.assertEqual(path.read_text(encoding="utf-8"), "{invalid")
