"""Missing preferences are live inheritance, never a shipped personal default."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from open_law_lens import pi_runtime as pi
from open_law_lens.config import normalize_agent_runtime_profile, PiAgentProfile


class InheritanceTests(unittest.TestCase):
    def test_missing_checkout_and_model_only_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'pi/settings.json'
            self.assertIsNone(pi.current_project_pi_model(path))
            self.assertFalse(path.parent.exists())
            pi.save_project_pi_model(pi.PiModel('synthetic', 'model', 'Model'), path)
            self.assertEqual(json.loads(path.read_text()), {'defaultProvider': 'synthetic', 'defaultModel': 'model'})

    def test_new_model_only_profile_has_no_reasoning_override(self):
        self.assertEqual(normalize_agent_runtime_profile({'provider': 'synthetic', 'model': 'model'}),
                         PiAgentProfile('synthetic', 'model', ''))
        self.assertIsNone(normalize_agent_runtime_profile({'provider': 'synthetic', 'model': 'model', 'thinking': 'invalid'}))

    def test_staging_inherits_live_global_changes_and_rejects_unsafe_preferences(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/stage-pi-settings.py'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefs = root / 'absent/settings.json'
            global_dir = root / 'global'
            global_dir.mkdir()
            stage = root / 'staged.json'
            for model in ('first', 'changed'):
                (global_dir / 'settings.json').write_text(json.dumps({'defaultModel': model, 'defaultThinkingLevel': 'high', 'enableSkillCommands': False}))
                subprocess.run([sys.executable, str(script), str(prefs), str(stage)], check=True,
                               env=dict(os.environ, PI_CODING_AGENT_DIR=str(global_dir)))
                self.assertEqual(json.loads(stage.read_text()), {})
                self.assertFalse(prefs.parent.exists())
            prefs.parent.mkdir()
            prefs.write_text('[]')
            before = stage.read_bytes()
            result = subprocess.run([sys.executable, str(script), str(prefs), str(stage)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stage.read_bytes(), before)
            prefs.unlink()
            prefs.symlink_to(root / 'missing')
            with self.assertRaises(pi.PiSettingsError):
                pi.current_project_pi_model(prefs)
