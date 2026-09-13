"""Opt-in paid acceptance against pre-staged source trees and public fixtures.

Usage: python tests/run_general_law_acceptance.py STAGE_ROOT FIXTURE_ROOT
STAGE_ROOT must contain baseline/ and candidate/ source snapshots with usable
.venv links; FIXTURE_ROOT contains public-library.sqlite3, public-cache/, and
LegInfo CODE-SECTION.json HTTP fixtures. See docs/general-law-quality-acceptance.md.
Never pass a real user library/cache here. This runner neither obtains credentials
nor changes profiles: Pi uses existing auth with an explicit model and high.
"""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

STAGES = Path(sys.argv[1]).resolve()
FIXTURES = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(STAGES / "candidate"))
from open_law_lens.pi_runtime import pi_command, _pi_rpc_command, _pi_rpc_response
from open_law_lens.config import DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE

QUESTION = """Public hypothetical: In a pending California juvenile dependency case,
a parent seeks a long-term restraining order under Welfare and Institutions Code
section 213.5 against another represented parent. The application and notice of
hearing were mailed to counsel but not personally served on the proposed restrained
parent. What is the best argument that personal service of the application is
required before the noticed hearing? Address material contrary law and distinguish
service of the application from service of an issued order."""
FIXTURE_NOTICE = """
Acceptance environment: use only the canonical Open Law Lens CLI prefix supplied
in the preloaded skill. It is installed and ready. Fixed public-authority I/O is
provided to the production CLI; unavailable items return explicit fixture gaps.
Do not read local configuration or source code, use other shell commands, or use
external research services. The fixture includes Jonathan V., Searles v. Archangel,
and Yu v. Pozniak-Rice, plus relevant statutes; discovery is bounded to that corpus.
No further Scholar copy is available in this fixture. Do not assume this corpus
is exhaustive. Return the legal answer, not an account of this acceptance test.
"""

# Catalog verified 2026-09-13: 1M input at $0.22/M + 384k output at $0.66/M
# costs at most $0.47344 per request, conservatively counting both maxima.
# Stop at $0.50 completed cumulative usage, reserving another full request below
# the $1 cap even if Pi starts it before the termination is processed.
catalog = _pi_rpc_response(_pi_rpc_command(), {"type": "get_available_models"}, timeout=15)
models = [m for m in catalog.get("data", {}).get("models", [])
          if m.get("provider") == "fireworks" and m.get("id") == "accounts/fireworks/models/deepseek-v4p1-flash"]
if (len(models) != 1 or models[0].get("contextWindow") != 1000000
        or models[0].get("maxTokens") != 384000
        or models[0].get("cost", {}).get("input") != 0.22
        or models[0].get("cost", {}).get("output") != 0.66):
    raise SystemExit("Stop: model availability or budget assumptions changed; no substitution.")
spent = 0.00003212  # preliminary access probe, included in cumulative budget
summaries = []
for variant in ("baseline", "candidate"):
    project = STAGES / variant
    for number in range(1, 4):
        if spent >= 0.50:
            raise SystemExit("Stopped: cumulative budget reserve reached.")
        run = STAGES / f"{variant}-{number}"
        run.mkdir(exist_ok=False)
        workspace = run / "workspace"
        workspace.mkdir()
        shutil.copytree(FIXTURES / "public-cache", run / "cache")
        shutil.copy2(FIXTURES / "public-library.sqlite3", run / "library.sqlite3")
        (run / "empty-concordance.csv").write_text("")
        (run / "config.json").write_text(json.dumps({"reader_font_size_pt": 14,
            "concordance_file_path": str(run / "empty-concordance.csv")}))
        hooks = run / "hooks"
        hooks.mkdir()
        shutil.copy2(Path(__file__).with_name("general_law_fixture_io.py"), hooks / "fixture_io.py")
        (hooks / "sitecustomize.py").write_text("from fixture_io import install\ninstall()\n")
        system = (project / ".pi/SYSTEM.md").read_text() + "\n" + (project / ".pi/skills/legal-researcher/SKILL.md").read_text()
        prompt = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE.format(question=QUESTION) + FIXTURE_NOTICE
        env = os.environ.copy()
        env.update({"OPEN_LAW_LENS_PROJECT_DIR": str(project),
                    "OPEN_LAW_LENS_CONFIG": str(run / "config.json"),
                    "OPEN_LAW_LENS_CACHE_DIR": str(run / "cache"),
                    "OPEN_LAW_LENS_LIBRARY_DB": str(run / "library.sqlite3"),
                    "OLL_FIXTURE_ROOT": str(FIXTURES),
                    "OLL_FIXTURE_AUDIT": str(run / "cli-audit.jsonl"),
                    "PYTHONPATH": str(hooks) + os.pathsep + str(project)})
        env.pop("COURTLISTENER_TOKEN", None)
        command = [*pi_command(), "--offline", "--no-session", "--no-extensions",
                   "--no-skills", "--no-context-files", "--no-prompt-templates",
                   "--no-themes", "--tools", "bash", "--provider", "fireworks",
                   "--model", "accounts/fireworks/models/deepseek-v4p1-flash",
                   "--thinking", "high", "--mode", "json", "--system-prompt", system,
                   "-p", prompt]
        started = time.monotonic()
        metrics = {"variant": variant, "run": number, "cost": 0, "generated_tokens": 0,
                   "tool_result_chars": 0, "tool_calls": 0, "searches": 0,
                   "research_rounds": 0, "status": "running"}
        with (run / "stderr.log").open("w") as err, (run / "events.jsonl").open("wb") as log:
            proc = subprocess.Popen(command, cwd=workspace, env=env, stdout=subprocess.PIPE,
                                    stderr=err, start_new_session=True)
            buffer = b""
            try:
                while True:
                    if time.monotonic() - started > 300 or spent >= 0.50:
                        metrics["status"] = "timeout_or_budget_stop"
                        os.killpg(proc.pid, signal.SIGTERM)
                        break
                    if not select.select([proc.stdout], [], [], 0.1)[0]:
                        continue
                    chunk = os.read(proc.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    log.write(chunk)
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        if e.get("type") == "message_end":
                            m = e["message"]
                            if m.get("role") == "assistant":
                                cost = m.get("usage", {}).get("cost", {}).get("total", 0)
                                spent += cost
                                metrics["cost"] += cost
                                metrics["generated_tokens"] += m.get("usage", {}).get("output", 0)
                                calls = [c for c in m.get("content", []) if c.get("type") == "toolCall"]
                                if calls:
                                    metrics["research_rounds"] += 1
                                elif m.get("stopReason") == "stop":
                                    answer = "\n".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
                                    (run / "answer.md").write_text(answer)
                                    metrics["status"] = "complete"
                                if m.get("stopReason") == "error":
                                    metrics["status"] = "provider_error"
                            elif m.get("role") == "toolResult":
                                metrics["tool_result_chars"] += sum(len(c.get("text", "")) for c in m.get("content", []))
                        elif e.get("type") == "tool_execution_start":
                            metrics["tool_calls"] += 1

                proc.wait(timeout=5)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        audit = run / "cli-audit.jsonl"
        if audit.exists():
            calls = [json.loads(line) for line in audit.read_text().splitlines()]
            metrics["searches"] = sum(e.get("type") == "cli_call" and e.get("argv", [None])[0] == "case-search" for e in calls)
        metrics["latency_seconds"] = round(time.monotonic() - started, 2)
        metrics["cumulative_cost"] = spent
        summaries.append(metrics)
        (STAGES / "metrics.json").write_text(json.dumps(summaries, indent=2))
        print(json.dumps(metrics), flush=True)
        if metrics["status"] == "provider_error":
            raise SystemExit("Stopped: provider error; no substitution.")
