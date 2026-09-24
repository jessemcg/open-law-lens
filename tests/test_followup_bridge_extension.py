"""Load the real Open Law Lens follow-up bridge through Pi's jiti loader.

This exercises the TypeScript extension code itself with a deterministic fake
Pi API, so socket lifecycle, token checks, state transitions, duplicate
suppression, and literal-text dispatch are validated without a model.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from open_law_lens.app import AGENT_FOLLOWUP_EXTENSION


_HARNESS = r"""
import assert from "node:assert/strict";
import { createJiti } from "__JITI__";
import { mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import net from "node:net";

const runtime = mkdtempSync(join(tmpdir(), "oll-bridge-"));
const socketPath = join(runtime, "bridge.sock");
const token = "abcdefghijklmnopqrstuvwxyz0123456789";
process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_SOCKET = socketPath;
process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_RUNTIME_DIR = runtime;
process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_TOKEN = token;

const jiti = createJiti(import.meta.url);
const mod = await jiti.import("__EXTENSION__");
const handlers = {};
let idle = true;
const sent = [];
const pi = {
  on(name, handler) { handlers[name] = handler; },
  sendUserMessage(text, options) { sent.push({ text, options }); idle = false; },
};
const ctx = { isIdle: () => idle };
mod.default(pi);

await handlers.session_start({}, ctx);
assert.equal(statSync(socketPath).mode & 0o777, 0o600);

function request(frame) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath, () => {
      socket.write(JSON.stringify(frame) + "\n");
    });
    let data = "";
    socket.on("data", (chunk) => (data += chunk));
    socket.on("end", () => resolve(JSON.parse(data.trim())));
    socket.on("error", reject);
  });
}

const starting = await request({ v: 1, type: "status", id: "req00000001", token });
assert.deepEqual(starting, { v: 1, type: "status", id: "req00000001", ok: true, state: "starting" });

await handlers.agent_settled({}, ctx);
idle = true;
const ready = await request({ v: 1, type: "status", id: "req00000002", token });
assert.equal(ready.state, "ready");

const unauthorized = await request({ v: 1, type: "status", id: "req00000003", token: "wrong-token-wrong-token-wrong" });
assert.equal(unauthorized.ok, false);
assert.equal(unauthorized.error, "unauthorized");

const submitted = await request({ v: 1, type: "submit", id: "req00000004", token, text: "/bash rm -rf /" });
assert.equal(submitted.ok, true);
assert.equal(submitted.state, "busy");
assert.equal(sent.length, 1);
assert.equal(sent[0].text, "/bash rm -rf /");
assert.equal(sent[0].options.expandPromptTemplates, false);

const busy = await request({ v: 1, type: "submit", id: "req00000005", token, text: "again" });
assert.equal(busy.error, "busy");
assert.equal(sent.length, 1);

const duplicate = await request({ v: 1, type: "submit", id: "req00000004", token, text: "/bash rm -rf /" });
assert.equal(duplicate.ok, true);
assert.equal(duplicate.duplicate, true);
assert.equal(sent.length, 1);

await handlers.session_shutdown({}, ctx);
console.log("OK");
"""


def _find_jiti() -> str | None:
    pi = shutil.which("pi")
    if not pi:
        return None
    target = Path(pi).resolve()
    for parent in target.parents:
        candidate = (
            parent
            / "node_modules"
            / "@earendil-works"
            / "pi-coding-agent"
            / "node_modules"
            / "jiti"
            / "lib"
            / "jiti.mjs"
        )
        if candidate.is_file():
            return candidate.as_uri()
    return None


class FollowupBridgeExtensionTests(unittest.TestCase):
    def test_followup_bridge_extension_lifecycle(self) -> None:
        node = shutil.which("node")
        jiti = _find_jiti()
        if not node or jiti is None:
            self.skipTest("node and the Pi jiti loader are required for this check")
        if not AGENT_FOLLOWUP_EXTENSION.is_file():
            self.skipTest("follow-up bridge extension is not present")
        harness = _HARNESS.replace("__JITI__", jiti).replace(
            "__EXTENSION__", AGENT_FOLLOWUP_EXTENSION.as_uri()
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "harness.mjs"
            script.write_text(harness, encoding="utf-8")
            completed = subprocess.run(
                [node, str(script)],
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": temp_dir},
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
