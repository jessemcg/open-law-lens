"""Isolated embedded-launch/render acceptance; fake Pi, no legal/model network.

Run with uv run python tests/preview_general_law_quality.py. The window closes
in 90 seconds. All writes, including populated settings, stay in a temp tree.
"""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-quality-gui-"))
for key, value in {
    "OPEN_LAW_LENS_CONFIG": "config.json", "OPEN_LAW_LENS_CACHE_DIR": "cache",
    "OPEN_LAW_LENS_LIBRARY_DB": "library.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DB": "briefs.sqlite3",
    "PI_CODING_AGENT_DIR": "pi-agent",
}.items():
    os.environ[key] = str(ROOT / value)
os.environ.pop("COURTLISTENER_TOKEN", None)
(ROOT / "config.json").write_text(json.dumps({"reader_font_size_pt": 14}))
package = ROOT / "pi-agent/npm/node_modules/pi-web-access"
package.mkdir(parents=True)
(package / "index.ts").write_text("")
(package / "package.json").write_text('{"name":"pi-web-access","version":"0.19.0"}')
computer_use = ROOT / "pi-agent/npm/node_modules/@agent-sh/computer-use-linux/npm/bin/computer-use-linux.js"
computer_use.parent.mkdir(parents=True)
computer_use.write_text("")
fake = ROOT / "pi"
fake.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(os.environ['OPEN_LAW_LENS_AGENT_WORKSPACE'])
(root / 'captured-argv.json').write_text(json.dumps(sys.argv))
sessions = root / 'pi-sessions'
sessions.mkdir(exist_ok=True)
answer = '# Synthetic Service Argument\\n## Material premise unresolved\\n\\nRequired notice does not by itself establish mandatory personal service. This is synthetic rendering data, not legal advice or verified research.\\n\\n- **Express text:** preserve opening conditions and exceptions.\\n- **Proposed inference:** identify the missing bridge.\\n- Ambiguous reporter markers: cite the source without guessing a pinpoint.\\n'
entries = [{'type':'session','version':3,'id':'synthetic-quality','cwd':str(root)}, {'type':'message','id':'answer','parentId':None,'message':{'role':'assistant','content':[{'type':'text','text':answer}],'stopReason':'stop'}}]
(sessions / 'synthetic.jsonl').write_text('\\n'.join(json.dumps(e) for e in entries)+'\\n')
print('Synthetic Pi completed; no model called.', flush=True)
""")
fake.chmod(0o755)
os.environ["OPEN_LAW_LENS_PI_BIN"] = str(fake)
os.environ["OPEN_LAW_LENS_PI_NODE_BIN"] = str(fake)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from gi.repository import Gio


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass


def activate(app):
    window = Preview(app)
    window.set_title("Synthetic General Law Quality Acceptance")
    window.present()
    workspace = ROOT / "workspace"
    workspace.mkdir()
    prompt = ROOT / "prompt.txt"
    prompt.write_text("Public hypothetical service question; synthetic acceptance only.")
    window._launch_agent_with_prompt(prompt, workspace, "general")

    def verify():
        try:
            assert "Required notice" in window._agent_last_answer_text
            staged = (workspace / ".pi/SYSTEM.md").read_text()
            assert staged.count("name: legal-researcher") == 1
            assert "--limit 5 --compact" in staged
            assert "missing" in staged
            assert not window._agent_failure_visible
            print("PASS populated startup, VTE wrapper launch, preloaded skill, final answer rendering", flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            print("FAIL", repr(exc), flush=True)
        return False

    ui.GLib.timeout_add_seconds(6, verify)
    ui.GLib.timeout_add_seconds(90, lambda: (app.quit(), False)[1])
    print("READY", os.getpid(), ROOT, flush=True)


def blocked(*args, **kwargs):
    raise AssertionError("Network forbidden in synthetic GUI acceptance")


with patch.object(socket.socket, "connect", blocked):
    app = ui.Adw.Application(application_id="com.mcglaw.OpenLawLens.QualityPreview", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    app.run([])
