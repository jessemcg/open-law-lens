from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
PROJECT_PI_SETTINGS_PATH = PROJECT_DIR / ".pi" / "settings.json"
PI_MODEL_DISCOVERY_TIMEOUT_SECONDS = 10


class PiRuntimeError(RuntimeError):
    pass


class PiSettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PiModel:
    provider: str
    model_id: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} — {self.provider}"

    @property
    def settings_key(self) -> tuple[str, str]:
        return self.provider, self.model_id


def _executable_path(value: str) -> Path | None:
    candidate = Path(value).expanduser()
    if "/" in value:
        return candidate if candidate.is_file() else None
    discovered = shutil.which(value)
    return Path(discovered) if discovered else None


def find_pi_executable() -> str:
    override = os.environ.get("OPEN_LAW_LENS_PI_BIN", "").strip()
    if override:
        return override
    discovered = shutil.which("pi")
    if discovered:
        return discovered
    local_bin = Path.home() / ".local" / "bin" / "pi"
    if local_bin.is_file():
        return str(local_bin)
    candidates = sorted(
        (Path.home() / ".local" / "share" / "pi-node").glob("node-*/bin/pi"),
        reverse=True,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "pi"


def find_pi_node_executable(pi_executable: str) -> str:
    override = os.environ.get("OPEN_LAW_LENS_PI_NODE_BIN", "").strip()
    if override:
        return override
    pi_path = _executable_path(pi_executable)
    if pi_path is None:
        return ""
    current = pi_path
    for _attempt in range(8):
        sibling_node = current.parent / "node"
        if sibling_node.is_file() and os.access(sibling_node, os.X_OK):
            return str(sibling_node)
        if not current.is_symlink():
            break
        target = os.readlink(current)
        current = Path(target) if os.path.isabs(target) else current.parent / target
    return ""


def pi_command() -> list[str]:
    pi_executable = find_pi_executable()
    pi_node = find_pi_node_executable(pi_executable)
    if pi_node:
        return [pi_node, pi_executable]
    return [pi_executable]


def _pi_rpc_response(
    command: list[str],
    request: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise PiRuntimeError(f"Unable to start Pi model query: {exc}") from exc
    output_lines: list[str] = []
    response: dict[str, Any] | None = None
    timed_out = False
    io_error: OSError | ValueError | None = None
    try:
        if process.stdin is None or process.stdout is None:
            raise PiRuntimeError("Unable to open Pi RPC input and output.")
        process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + timeout
        while response is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _writable, _errors = select.select(
                [process.stdout],
                [],
                [],
                remaining,
            )
            if not ready:
                timed_out = True
                break
            line = process.stdout.readline()
            if not line:
                break
            output_lines.append(line.rstrip())
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(payload, dict)
                and payload.get("type") == "response"
                and payload.get("command") == request.get("type")
            ):
                response = payload
    except (OSError, ValueError) as exc:
        io_error = exc
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if timed_out and process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdout is not None and not process.stdout.closed:
            try:
                remainder = process.stdout.read()
            except OSError as exc:
                if io_error is None:
                    io_error = exc
            else:
                if remainder:
                    output_lines.extend(remainder.splitlines())
            process.stdout.close()

    if timed_out:
        raise PiRuntimeError(f"Pi model query timed out after {timeout} seconds.")
    if io_error is not None:
        raise PiRuntimeError(
            f"Pi model query communication failed: {io_error}"
        ) from io_error
    if response is not None:
        return response
    detail = "\n".join(output_lines).strip()
    if len(detail) > 500:
        detail = detail[-500:]
    if process.returncode:
        raise PiRuntimeError(
            f"Pi model query failed with exit code {process.returncode}"
            + (f": {detail}" if detail else ".")
        )
    raise PiRuntimeError("Pi did not return an available-model response.")


def available_pi_models(
    *,
    timeout: float = PI_MODEL_DISCOVERY_TIMEOUT_SECONDS,
) -> list[PiModel]:
    command = [
        *pi_command(),
        "--mode",
        "rpc",
        "--offline",
        "--no-session",
        "--approve",
        "--no-tools",
        "--no-skills",
        "--no-extensions",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
    ]
    response = _pi_rpc_response(
        command,
        {"type": "get_available_models"},
        timeout=timeout,
    )
    if response.get("success") is not True:
        error = str(response.get("error") or "unknown RPC error").strip()
        raise PiRuntimeError(f"Pi could not list available models: {error}")
    data = response.get("data")
    raw_models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(raw_models, list):
        raise PiRuntimeError("Pi returned an invalid available-model response.")

    models: dict[tuple[str, str], PiModel] = {}
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        provider = str(raw_model.get("provider") or "").strip()
        model_id = str(raw_model.get("id") or "").strip()
        if not provider or not model_id:
            continue
        name = str(raw_model.get("name") or model_id).strip() or model_id
        model = PiModel(provider=provider, model_id=model_id, name=name)
        models[model.settings_key] = model
    return sorted(
        models.values(),
        key=lambda model: (
            model.provider.casefold(),
            model.name.casefold(),
            model.model_id.casefold(),
        ),
    )


def _read_pi_settings(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PiSettingsError(f"Pi project settings not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PiSettingsError(f"Unable to read Pi project settings: {exc}") from exc
    if not isinstance(raw, dict):
        raise PiSettingsError("Pi project settings must contain a JSON object.")
    return raw


def current_project_pi_model(
    path: Path = PROJECT_PI_SETTINGS_PATH,
) -> tuple[str, str] | None:
    settings = _read_pi_settings(path)
    provider = str(settings.get("defaultProvider") or "").strip()
    model_id = str(settings.get("defaultModel") or "").strip()
    if not provider or not model_id:
        return None
    return provider, model_id


def save_project_pi_model(
    model: PiModel,
    path: Path = PROJECT_PI_SETTINGS_PATH,
) -> None:
    settings = _read_pi_settings(path)
    settings["defaultProvider"] = model.provider
    settings["defaultModel"] = model.model_id
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(settings, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    except OSError as exc:
        raise PiSettingsError(f"Unable to save Pi project settings: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
