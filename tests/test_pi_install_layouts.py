"""Official Pi shell/managed-Node and legacy JS compatibility, fixture-only."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from open_law_lens import pi_runtime as runtime
from open_law_lens.computer_use_mcp import resolve_computer_use_command
import test_agent_vte_wrapper as wrapper_fixture


class PiInstallLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agent = self.root / 'agent space'
        self.data = self.root / 'custom-data'
        env = {'HOME': str(self.root), 'PATH': '/usr/bin:/bin', 'PI_CODING_AGENT_DIR': str(self.agent), 'XDG_DATA_HOME': str(self.data)}
        self.enterContext(patch.dict(os.environ, env, clear=True))
        self.enterContext(patch('shutil.which', return_value=None))

    def executable(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content); path.chmod(0o755); return path

    def test_official_shell_discovered_without_path_or_new_shell_and_rpc_runs_directly(self):
        pi = self.executable(self.agent / 'bin/pi', '#!/bin/sh\nread -r request\nprintf \'%s\\n\' \'{"type":"response","command":"get_available_models","success":true,"data":{"models":[]}}\'\n')
        node = self.executable(self.data / 'pi-node/current/bin/node', '#!/bin/sh\n# Never interpret the shell launcher as JS.\nexit 99\n')
        self.assertEqual(runtime.find_pi_executable(), str(pi))
        self.assertEqual(runtime.find_pi_node_executable(str(pi)), str(node))
        self.assertEqual(runtime.pi_command(), [str(pi)])
        shell_with_js_name = self.executable(self.agent / 'bin/shell.js', '#!/bin/sh\nexit 0\n')
        self.assertFalse(runtime.pi_is_javascript(str(shell_with_js_name)))
        with patch.object(runtime, 'standalone', return_value=True):
            self.assertEqual(runtime.available_pi_models(), [])
        self.assertFalse((self.root / '.pi').exists())

    def test_home_managed_node_fallback_and_independent_native_computer_use(self):
        pi = self.executable(self.agent / 'bin/pi', '#!/bin/sh\nexit 0\n')
        node = self.executable(self.root / '.local/share/pi-node/current/bin/node', '#!/bin/sh\nexit 0\n')
        native = self.executable(self.root / '.local/share/open-law-lens/tools/computer-use/computer-use-linux', '#!/bin/sh\nexit 0\n')
        self.assertEqual(runtime.find_pi_node_executable(str(pi)), str(node))
        self.assertEqual(resolve_computer_use_command(dict(os.environ)), [str(native)])

    def test_legacy_js_and_overrides(self):
        node = self.executable(self.root / 'legacy/bin/node', '#!/bin/sh\nexit 0\n')
        js = self.executable(self.root / 'legacy/lib/cli.js', '#!/usr/bin/env node\n')
        pi = self.root / 'legacy/bin/pi'; pi.symlink_to(js)
        with patch.dict(os.environ, OPEN_LAW_LENS_PI_BIN=str(pi)):
            self.assertEqual(runtime.pi_command(), [str(node), str(pi)])
        with patch.dict(os.environ, OPEN_LAW_LENS_PI_BIN='/explicit/pi', OPEN_LAW_LENS_PI_NODE_BIN='/explicit/node'):
            self.assertEqual(runtime.find_pi_executable(), '/explicit/pi')
            self.assertEqual(runtime.find_pi_node_executable('/explicit/pi'), '/explicit/node')

    def test_embedded_five_profiles_execute_shell_directly_with_managed_node_ready(self):
        harness = wrapper_fixture.AgentVteWrapperTests()
        self.enterContext(patch.dict(os.environ, OPEN_LAW_LENS_CLI_BIN='/bin/true'))
        for mode, workflow in [('general', 'law'), ('case', 'research_cache'), ('brief', 'prior_briefs'), ('appeal', 'assess_argument'), ('general', 'subsequent_treatment')]:
            with self.subTest(workflow=workflow), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pi = self.executable(root / 'official/bin/pi', '#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE_ARGS"\n')
                node = self.executable(root / 'managed/current/bin/node', '#!/bin/sh\nexit 99\n')
                args, _ = harness._run(root, mode, extra_env={
                    'OPEN_LAW_LENS_STORAGE': 'standalone', 'OPEN_LAW_LENS_PI_BIN': str(pi),
                    'OPEN_LAW_LENS_PI_NODE_BIN': str(node), 'OPEN_LAW_LENS_AGENT_PROFILE_KEY': workflow})
                self.assertEqual(args[0], '--approve')
                self.assertIn('--no-extensions', args); self.assertIn('--no-skills', args)
                tools = args[args.index('--tools') + 1]
                self.assertEqual(tools, 'read,bash,grep,find,ls')
                self.assertNotIn(str(pi), args)  # Would be first argv if blindly passed through Node.


if __name__ == '__main__': unittest.main()
