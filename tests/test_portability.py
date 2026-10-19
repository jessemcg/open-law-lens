"""Standalone contracts using fresh subprocesses, synthetic HOME and no services."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens import paths
from open_law_lens.agent_commands import agent_cli_command

PROJECT = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def fresh(self, root, code, **extra):
        env = dict(os.environ, HOME=str(root / "home"), OPEN_LAW_LENS_STORAGE="standalone",
                   XDG_CONFIG_HOME=str(root / "config"), XDG_DATA_HOME=str(root / "data"),
                   XDG_CACHE_HOME=str(root / "cache"), XDG_STATE_HOME=str(root / "state"),
                   PI_CODING_AGENT_DIR=str(root / "pi"), OPEN_LAW_LENS_PI_BIN="/nonexistent/pi",
                   OPEN_LAW_LENS_PI_NODE_BIN="", PYTHONDONTWRITEBYTECODE="1")
        for key in ("OPEN_LAW_LENS_CONFIG", "OPEN_LAW_LENS_CACHE_DIR", "OPEN_LAW_LENS_LIBRARY_DB",
                    "OPEN_LAW_LENS_PRIOR_BRIEFS_DIR", "OPEN_LAW_LENS_PRIOR_BRIEFS_DB",
                    "OPEN_LAW_LENS_CURRENT_CASE_FILE", "OPEN_LAW_LENS_CASE_ROOTS", "COURTLISTENER_TOKEN"):
            env.pop(key, None)
        env.update(extra)
        return subprocess.run([sys.executable, "-c", code], env=env, cwd=PROJECT,
                              capture_output=True, text=True, timeout=20, check=True)

    def test_public_paths_and_explicit_legacy_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.fresh(root, """
import json
from open_law_lens.config import CONFIG_PATH
from open_law_lens.cache import cache_root
from open_law_lens.library import library_db_path
from open_law_lens.prior_briefs import DEFAULT_PRIOR_BRIEFS_DIR, DEFAULT_PRIOR_BRIEFS_DB
from open_law_lens.pi_runtime import PROJECT_PI_SETTINGS_PATH
from open_law_lens.paths import execution_env, workspace_root
print(json.dumps([str(p) for p in [CONFIG_PATH, cache_root(), library_db_path(), DEFAULT_PRIOR_BRIEFS_DIR, DEFAULT_PRIOR_BRIEFS_DB, PROJECT_PI_SETTINGS_PATH, workspace_root()]]))
""")
            values = json.loads(result.stdout)
            self.assertTrue(all(value.startswith(str(root)) for value in values), values)
            self.assertIn("/data/open-law-lens/research", values[1])
            self.assertNotIn("/cache/", values[1])
            self.assertEqual(list(root.iterdir()), [])  # resolution alone is read-only
        with patch.dict(os.environ, {"OPEN_LAW_LENS_STORAGE": "legacy"}):
            self.assertEqual(paths.data_root(), PROJECT)

    def test_doctor_redacts_and_does_not_create_state_or_run_pi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.fresh(root, """
import json
from unittest.mock import patch
from open_law_lens.diagnostics import report
with patch('open_law_lens.pi_runtime.available_pi_runtime_catalog', side_effect=AssertionError('must not run')):
    print(json.dumps(report()))
""", COURTLISTENER_TOKEN="synthetic-secret-never-report")
            self.assertNotIn("synthetic-secret", result.stdout)
            value = json.loads(result.stdout)
            self.assertEqual(value["capabilities"]["courtlistener"]["checks"][0]["status"], "ready")
            self.assertEqual(value["capabilities"]["agent_workflows"]["status"], "missing")
            self.assertEqual(value["capabilities"]["core_gui"]["status"], "ready")
            self.assertEqual(list(root.iterdir()), [])

    def test_unconfigured_current_case_is_optional_and_manual_fact_pattern_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fresh(Path(directory), """
from open_law_lens.current_case import read_current_case, CurrentCaseError
from open_law_lens.config import load_config
try:
    read_current_case()
except CurrentCaseError as error:
    assert 'not configured' in str(error) and '/home/jesse' not in str(error)
else:
    raise AssertionError('personal integration must be off')
assert load_config().agent_runtime_profile is None
""")

    def test_config_and_library_roundtrip_no_source_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fresh(root, """
import os
from open_law_lens.config import AppConfig, save_config, load_config, CONFIG_PATH
from open_law_lens.library import CaseLibrary
from open_law_lens.cache import JsonCache
save_config(AppConfig(courtlistener_token='synthetic', retired_prompt_settings={'general_agent_prompt_template': {'opaque': True}}))
assert load_config().retired_prompt_settings == {'general_agent_prompt_template': {'opaque': True}}
assert CONFIG_PATH.stat().st_mode & 0o777 == 0o600
CaseLibrary.default().ensure()
JsonCache.default().ensure()
""")
            self.assertTrue((root / "config/open-law-lens/config.json").is_file())
            self.assertTrue((root / "data/open-law-lens/library/open_law_lens.sqlite3").is_file())

    def test_clear_public_cache_preserves_saved_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fresh(Path(directory), """
from open_law_lens.cache import JsonCache
cache = JsonCache.default()
cache.ensure()
answer = cache.root / 'agent_answers/synthetic.json'
answer.write_text('{"synthetic":true}')
cache.agent_answer_index_path().write_text('[]')
cache.clear()
assert answer.is_file()
assert cache.agent_answer_index_path().is_file()
""")

    def test_generated_commands_work_from_arbitrary_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="oll commands ") as directory:
            root = Path(directory)
            launcher = root / "installed cli"
            launcher.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            launcher.chmod(0o700)
            for command in ("case-search", "extract-case", "extract-brief", "extract-statute", "published-citing-cases"):
                result = subprocess.run(["bash", "-c", agent_cli_command(f"{command} 'literal spaces; $(false)'" )],
                                        cwd=root, env={**os.environ, "OPEN_LAW_LENS_CLI_BIN": str(launcher)},
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.splitlines(), [command, "literal spaces; $(false)"])

    def test_public_wrapper_all_workflows_without_siblings_uv_or_browser(self):
        import test_agent_vte_wrapper as fixtures
        for mode, workflow in (("general", "law"), ("case", "research_cache"), ("brief", "prior_briefs"),
                               ("appeal", "assess_argument"), ("general", "subsequent_treatment")):
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory(prefix="oll wrapper ") as directory:
                root = Path(directory)
                fixture = fixtures.AgentVteWrapperTests()
                env = fixture._minimal_env(root, mode)
                env.update(OPEN_LAW_LENS_CLI_BIN="/bin/true", OPEN_LAW_LENS_STORAGE="standalone",
                           OPEN_LAW_LENS_AGENT_PROFILE_KEY=workflow,
                           OPEN_LAW_LENS_PI_SETTINGS=str(root / "no-personal-settings"),
                           PI_CODING_AGENT_DIR=str(root / "pi-agent"), HOME=str(root / "empty-home"))
                result = subprocess.run(["bash", str(fixtures.WRAPPER)], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("metrics", result.stderr.lower())
                self.assertEqual(json.loads((root / "workspace/.pi/settings.json").read_text()), {})
                self.assertEqual((root / "workspace").stat().st_mode & 0o777, 0o700)

    def test_standalone_rpc_never_uses_tracked_model_defaults(self):
        from open_law_lens import pi_runtime
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"OPEN_LAW_LENS_STORAGE": "standalone", "XDG_CONFIG_HOME": str(root)}):
                def check(command, request, *, timeout, cwd):
                    self.assertNotEqual(cwd, PROJECT)
                    self.assertFalse((cwd / ".pi/settings.json").exists())
                    return {"success": True}
                with patch.object(pi_runtime, "_pi_rpc_response_in", side_effect=check):
                    pi_runtime._pi_rpc_response([], {}, timeout=1)

    def test_relative_xdg_uses_home_and_explicit_storage_overrides_win(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fresh(root, """
import os
from pathlib import Path
from open_law_lens.paths import config_path, data_root, research_root, library_path
home = Path.home()
assert config_path() == home / '.config/open-law-lens/config.json'
assert data_root() == home / '.local/share/open-law-lens'
os.environ['OPEN_LAW_LENS_CONFIG'] = str(home / 'explicit/config.json')
os.environ['OPEN_LAW_LENS_CACHE_DIR'] = str(home / 'explicit/research')
os.environ['OPEN_LAW_LENS_LIBRARY_DB'] = str(home / 'explicit/library.sqlite3')
assert config_path() == home / 'explicit/config.json'
assert research_root() == home / 'explicit/research'
assert library_path() == home / 'explicit/library.sqlite3'
""", XDG_CONFIG_HOME="relative", XDG_DATA_HOME="relative")
            self.assertEqual(list(root.iterdir()), [])

    def test_runtime_rejects_symlinks_and_public_directories_without_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            runtime.mkdir()
            target = root / "unrelated"
            target.mkdir(mode=0o700)
            private = runtime / "open-law-lens-private"
            private.symlink_to(target, target_is_directory=True)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                with self.assertRaises(OSError):
                    paths.runtime_root(create=True)
                self.assertTrue(private.is_symlink())
                private.unlink()
                private.mkdir(mode=0o755)
                private.chmod(0o755)
                with self.assertRaises(OSError):
                    paths.runtime_root(create=True)
                self.assertEqual(private.stat().st_mode & 0o777, 0o755)
                private.chmod(0o700)
                self.assertEqual(paths.runtime_root(create=True), private)

    def test_missing_optional_tools_do_not_disable_core_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fresh(Path(directory), """
import gi
from unittest.mock import patch
from open_law_lens.diagnostics import report
original = gi.require_version
def require(namespace, version):
    if namespace == 'Vte':
        raise ValueError('synthetic VTE absence')
    return original(namespace, version)
with patch('shutil.which', return_value=None), patch.object(gi, 'require_version', side_effect=require):
    value = report()
assert value['capabilities']['core_gui']['status'] == 'ready'
assert 'agent_web_research' not in value['capabilities']
for capability in ('agent_workflows', 'pdf_extraction', 'prior_brief_indexing', 'selection_lookup'):
    assert value['capabilities'][capability]['status'] == 'missing', capability
""")

    def test_runtime_directory_is_private_and_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(root)}):
                runtime = paths.runtime_root(create=True)
                self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
                runtime.rmdir()
                runtime.symlink_to(root, target_is_directory=True)
                with self.assertRaises(OSError):
                    paths.runtime_root(create=True)

    def test_public_model_gate_never_substitutes_an_unavailable_override(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from open_law_lens import app as ui
        from open_law_lens.config import AppConfig, PiAgentProfile
        from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog
        catalog = PiRuntimeCatalog((PiModel('other', 'paid', 'Other'),),
                                   PiModel('other', 'paid', 'Other'), 'medium')
        configured = AppConfig(agent_runtime_profile=PiAgentProfile('chosen', 'missing', 'high'))
        parent = SimpleNamespace(_set_status=Mock(), _launch_agent_with_prompt_ready=Mock(), get_visible=lambda: True)
        class InlineThread:
            def __init__(self, *, target, daemon): self.target = target
            def start(self): self.target()
        with patch.object(ui, 'standalone', return_value=True), \
             patch.object(ui, 'available_pi_runtime_catalog', return_value=catalog), \
             patch.object(ui, 'load_config', return_value=configured), \
             patch.object(ui.threading, 'Thread', InlineThread), \
             patch.object(ui.GLib, 'idle_add', side_effect=lambda callback: callback()):
            ui.OpenLawLensWindow._launch_agent_with_prompt(parent, Path('/synthetic/prompt'), Path('/synthetic/workspace'), 'general')
        parent._launch_agent_with_prompt_ready.assert_not_called()
        self.assertIn('will not choose a provider', parent._set_status.call_args.args[0])

    def test_public_launcher_missing_environment_never_installs(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["bash", str(PROJECT / "scripts/open-law-lens-standalone.sh"), "doctor"],
                                    env={**os.environ, "OPEN_LAW_LENS_ENVIRONMENT": str(Path(directory) / "missing")},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("never installs", result.stderr)
