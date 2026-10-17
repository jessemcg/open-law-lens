"""Interactive SYNTHETIC terminal acceptance; no host installation or network.

Run from disposable source: python tests/preview_source_install.py
Only local fixture Git and desktop-file-validate execute for real. All paths are
under a temporary HOME. Enter path/native/Pi offers; Ctrl+C optionally.
The synthetic checkout/runtime/desktop files are removed when this exits.
"""
import json
from unittest.mock import patch

from test_source_installer import InstallerSandbox, m


def main():
    approve = m.approve
    prompt = m.continue_pi_install
    native_install = m.Packages.install
    sandbox = InstallerSandbox()
    sandbox.setUp()
    try:
        sandbox.fixture_install()
        pi = sandbox.home / '.pi/agent/bin/pi'

        def install_pi(env):
            print('[ACTION] SYNTHETIC official Pi installer fixture (no download)', flush=True)
            pi.parent.mkdir(parents=True, exist_ok=True)
            pi.write_text('#!/bin/sh\nexit 0\n')
            pi.chmod(0o755)

        print('SYNTHETIC Open Law Lens installer acceptance — temporary HOME, no real installation.', flush=True)
        with patch.object(m, 'approve', approve), patch.object(m, 'continue_pi_install', prompt), patch.object(m.Packages, 'install', native_install), patch.object(m.Packages, 'preview', return_value='SYNTHETIC preview'), patch.object(m.Packages, 'missing', return_value=['synthetic-native']), patch.object(m, 'install_optional_pi', side_effect=install_pi), patch.object(m, 'discover_pi', side_effect=lambda *args: [str(pi)] if pi.exists() else []):
            result = m.install(sandbox.args)
        receipt = sandbox.receipt()
        assert result == 0 and receipt['phase'] == 'complete'
        print('SYNTHETIC ACCEPTANCE: application phase=complete; optional outcomes=' + json.dumps(receipt.get('optional_setup', {})), flush=True)
        input('Synthetic preview finished. Press Enter to close and clean temporary data. ')
    finally:
        sandbox.doCleanups()


if __name__ == '__main__': main()
