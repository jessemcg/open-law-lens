"""Confined default-browser Google Scholar recovery job.

This module owns the process lifecycle for the *one* non-desktop fallback that
remains after the deterministic CourtListener -> California Courts slip
baseline: a visible default-browser Google Scholar attempt driven by the
confined first-party Pi extension. The app is the only caller and always the
single reader/writer of the isolated result.

The job is deliberately small and side-effect constrained:

* It runs a private ``pi --print --no-session`` subprocess in its own process
  group, with a purpose-specific system prompt and extension/skill/context
  discovery disabled.
* Only ``mcp``, ``mcpScript``, the existing Scholar-window authorization tool,
  and the two fixed job tools are exposed. ``bash``, filesystem tools, and
  ``web_search`` are unavailable, so the model cannot reach any other
  opinion-discovery service.
* The launch tool runs the fixed request query through ``uv ... open-scholar-browser``
  using argv execution (never a shell) and rejects any other query.
* The completion tool writes a one-shot, machine-readable result file with
  private permissions. No opinion text or clipboard content is logged.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .config import load_config
from .pi_runtime import find_pi_node_executable, find_pi_executable
from .scholar_browser import SCHOLAR_NETLOC, validate_scholar_source_url

RESULT_VERSION = 1
VALID_OUTCOMES = ("copied", "not_found", "blocked", "failed")

REQUEST_FILENAME = "request.json"
RESULT_FILENAME = "result.json"
PROMPT_FILENAME = "prompt.txt"

ENV_REQUEST_QUERY = "OPEN_LAW_LENS_SCHOLAR_QUERY"
ENV_RESULT_PATH = "OPEN_LAW_LENS_SCHOLAR_RESULT_PATH"
ENV_RECOVERY_DIR = "OPEN_LAW_LENS_SCHOLAR_RECOVERY_DIR"

DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_OUTPUT_BYTES = 256 * 1024


class BrowserRecoveryError(RuntimeError):
    """Base error for default-browser Scholar recovery."""


@dataclass(frozen=True)
class ScholarRecoveryRequest:
    query: str
    expected_citation: str = ""
    cluster_id: str = ""
    case_name: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "expected_citation": self.expected_citation,
            "cluster_id": self.cluster_id,
            "case_name": self.case_name,
        }


@dataclass(frozen=True)
class ScholarRecoveryOutcome:
    version: int
    outcome: str
    query: str
    source_url: str
    message: str

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "outcome": self.outcome,
            "query": self.query,
            "source_url": self.source_url,
            "message": self.message,
        }


def normalize_recovery_query(query: str) -> str:
    return re.sub(r"\s+", " ", query or "").strip()


def is_scholar_case_url(url: str) -> bool:
    try:
        validate_scholar_source_url(url)
    except RuntimeError:
        return False
    return True


def validate_recovery_result(payload: Any) -> ScholarRecoveryOutcome | None:
    """Return a validated outcome, or ``None`` if the payload is not a valid result."""
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != RESULT_VERSION:
        return None
    outcome = str(payload.get("outcome") or "")
    if outcome not in VALID_OUTCOMES:
        return None
    query = normalize_recovery_query(str(payload.get("query") or ""))
    source_url = str(payload.get("source_url") or "").strip()
    message = re.sub(r"\s+", " ", str(payload.get("message") or "")).strip()
    if outcome == "copied":
        if not source_url or not is_scholar_case_url(source_url):
            return None
    else:
        source_url = ""
    return ScholarRecoveryOutcome(
        version=RESULT_VERSION,
        outcome=outcome,
        query=query,
        source_url=source_url,
        message=message,
    )


def request_from_query(
    query: str,
    *,
    expected_citation: str = "",
    cluster_id: str = "",
    case_name: str = "",
) -> ScholarRecoveryRequest:
    clean_query = normalize_recovery_query(query)
    if not clean_query:
        raise BrowserRecoveryError("A Scholar recovery query is required.")
    return ScholarRecoveryRequest(
        query=clean_query,
        expected_citation=re.sub(r"\s+", " ", expected_citation or "").strip(),
        cluster_id=str(cluster_id or "").strip(),
        case_name=re.sub(r"\s+", " ", case_name or "").strip(),
    )


def recovery_environment(
    *,
    runtime_dir: Path,
    request: ScholarRecoveryRequest,
    project_dir: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[ENV_RECOVERY_DIR] = str(runtime_dir)
    env[ENV_REQUEST_QUERY] = request.query
    env[ENV_RESULT_PATH] = str(runtime_dir / RESULT_FILENAME)
    env["OPEN_LAW_LENS_PROJECT_DIR"] = str(project_dir)
    return env


def recovery_system_prompt(request: ScholarRecoveryRequest) -> str:
    expected = request.expected_citation or request.query
    return f"""You are recovering the exact officially paginated Google Scholar copy of one
California published case using the user's current default HTTPS browser.

Target query: {request.query}
Expected official citation: {expected}

Your only job is to drive the confined desktop tools to open Scholar, select the
exact matching case, copy its full opinion text, and record a machine-readable
result. Follow these rules exactly and do nothing else:

1. Run the computer-use doctor once and confirm readiness before any desktop
   action. If it fails, record outcome "failed".
2. Call `open_law_lens_launch_scholar_query` exactly once with the target query
   to open Scholar in the default browser. Never substitute a different query.
3. Identify the Scholar browser window by exact window_id and title/URL through
   list_windows/focused_window/get_app_state (no screenshots, no app-id
   targeting, no coordinates).
4. Authorize only an observed scholar.google.com window, then use mcpScript to
   find the result whose nearby text contains the expected citation, activate it
   by element_index, and re-observe to confirm the Scholar opinion page.
5. Copy the full opinion with only Ctrl+A then Ctrl+C (re-observing between
   actions). Screenshots, typing, scrolling, clicking coordinates, login, and
   CAPTCHA automation are forbidden.
6. If a CAPTCHA or robot check appears, record outcome "blocked" and stop.
7. If no matching case is found, record outcome "not_found".
8. If the opinion copied successfully, record outcome "copied" with the exact
   Scholar case URL (a https scholar.google.com/scholar_case URL).
9. Always finish by calling `open_law_lens_complete_scholar_recovery` exactly
   once with your outcome. Do not use bash, filesystem tools, or web_search.
"""


def recovery_pi_command(
    *,
    project_dir: Path,
    prompt_path: Path,
    profile: tuple[str, str, str] | None,
) -> list[str]:
    pi_executable = find_pi_executable()
    node_executable = find_pi_node_executable(pi_executable)
    args: list[str] = []
    if node_executable:
        args.append(node_executable)
    args.append(pi_executable)
    args.extend(
        [
            "--print",
            "--no-session",
            "--approve",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--tools",
            "mcp,mcpScript,open_law_lens_authorize_scholar_window,"
            "open_law_lens_launch_scholar_query,open_law_lens_complete_scholar_recovery",
        ]
    )
    if profile is not None:
        provider, model, thinking = profile
        if provider and model and thinking:
            args.extend(["--provider", provider, "--model", model, "--thinking", thinking])
    args.append(str(prompt_path))
    return args


def query_law_profile() -> tuple[str, str, str] | None:
    """Return the configured Query Law profile, or ``None`` for Pi defaults."""
    profiles = load_config().agent_runtime_profiles
    profile = profiles.get("law")
    if profile is None:
        return None
    provider = profile.provider.strip()
    model = profile.model.strip()
    thinking = profile.thinking.strip().lower()
    if not (provider and model and thinking):
        return None
    return provider, model, thinking


class ScholarRecoveryJob:
    """Owns the lifecycle of one running recovery subprocess.

    The subprocess runs in its own session (process group) so it can be
    terminated as a unit. Output is bounded; the authoritative result is the
    one-shot ``result.json`` written by the completion tool.
    """

    def __init__(
        self,
        *,
        runtime_dir: Path,
        request: ScholarRecoveryRequest,
        project_dir: Path,
        profile: tuple[str, str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.request = request
        self.project_dir = project_dir
        self.profile = profile
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.process: subprocess.Popen[str] | None = None
        self.result_path = runtime_dir / RESULT_FILENAME
        self.stdout_bytes = 0
        self._done = False

    def prepare(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        (self.runtime_dir / REQUEST_FILENAME).write_text(
            json.dumps(self.request.to_json(), ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        prompt_path = self.runtime_dir / PROMPT_FILENAME
        prompt_path.write_text(recovery_system_prompt(self.request), encoding="utf-8")
        # A stale result from an earlier attempt must never leak into this run.
        self.result_path.unlink(missing_ok=True)
        self.env = recovery_environment(
            runtime_dir=self.runtime_dir,
            request=self.request,
            project_dir=self.project_dir,
        )
        self.command = recovery_pi_command(
            project_dir=self.project_dir,
            prompt_path=prompt_path,
            profile=self.profile,
        )

    def start(self) -> None:
        if self.process is not None:
            raise BrowserRecoveryError("Recovery job already started.")
        try:
            self.process = subprocess.Popen(
                self.command,
                cwd=self.project_dir,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        except OSError as exc:
            raise BrowserRecoveryError(f"Unable to start Scholar recovery: {exc}") from exc

    def wait(self, timeout: float | None = None) -> ScholarRecoveryOutcome:
        if self.process is None:
            raise BrowserRecoveryError("Recovery job is not running.")
        remaining = self.timeout if timeout is None else timeout
        try:
            assert self.process.stdout is not None
            # Drain bounded output while the process runs so the pipe cannot
            # fill and deadlock the model.
            self._drain_output(budget=remaining)
        except Exception:
            self.terminate()
            raise
        outcome = self._read_result()
        if outcome is not None:
            self._done = True
            return outcome
        self._done = True
        return ScholarRecoveryOutcome(
            version=RESULT_VERSION,
            outcome="failed",
            query=self.request.query,
            source_url="",
            message="Scholar recovery produced no valid result.",
        )

    def _drain_output(self, *, budget: float) -> None:
        import time

        assert self.process is not None and self.process.stdout is not None
        deadline = time.monotonic() + budget
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.terminate()
                break
            import select

            ready, _w, _e = select.select([self.process.stdout], [], [], min(remaining, 1.0))
            if ready:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                self._consume_output(chunk)
            else:
                # Check whether the process exited without producing output.
                if self.process.poll() is not None:
                    # Drain any remaining buffered output.
                    try:
                        chunk = self.process.stdout.read()
                        if chunk:
                            self._consume_output(chunk)
                    except OSError:
                        pass
                    break
        if self.process.poll() is None:
            self.terminate()

    def _consume_output(self, chunk: str) -> None:
        self.stdout_bytes += len(chunk.encode("utf-8", errors="replace"))
        if self.stdout_bytes > self.max_output_bytes:
            self.terminate()

    def read_result(self) -> ScholarRecoveryOutcome | None:
        return self._read_result()

    def _read_result(self) -> ScholarRecoveryOutcome | None:
        if not self.result_path.exists():
            return None
        try:
            payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return validate_recovery_result(payload)

    def terminate(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.wait()

    def cancel(self) -> None:
        self.terminate()
        self._done = True


def run_scholar_recovery(
    request: ScholarRecoveryRequest,
    *,
    project_dir: Path,
    runtime_dir: Path,
    profile: tuple[str, str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ScholarRecoveryOutcome:
    job = ScholarRecoveryJob(
        runtime_dir=runtime_dir,
        request=request,
        project_dir=project_dir,
        profile=profile,
        timeout=timeout,
    )
    job.prepare()
    job.start()
    return job.wait()
