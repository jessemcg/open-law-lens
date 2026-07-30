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
PI_THINKING_LEVELS: tuple[str, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)


class PiRuntimeError(RuntimeError):
    pass


class PiSettingsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PiModel:
    provider: str
    model_id: str
    name: str
    supported_thinking_levels: tuple[str, ...] = PI_THINKING_LEVELS[:5]

    @property
    def label(self) -> str:
        return f"{self.name} — {self.provider}"

    @property
    def settings_key(self) -> tuple[str, str]:
        return self.provider, self.model_id


@dataclass(frozen=True, slots=True)
class PiRuntimeCatalog:
    models: tuple[PiModel, ...]
    default_model: PiModel | None
    default_thinking_level: str


def clamp_pi_thinking_level(model: PiModel, level: str) -> str:
    supported = model.supported_thinking_levels or ("off",)
    if level in supported:
        return level
    try:
        requested_index = PI_THINKING_LEVELS.index(level)
    except ValueError:
        return supported[0]
    for candidate in PI_THINKING_LEVELS[requested_index:]:
        if candidate in supported:
            return candidate
    for candidate in reversed(PI_THINKING_LEVELS[:requested_index]):
        if candidate in supported:
            return candidate
    return supported[0]


def _supported_thinking_levels(raw_model: dict[str, Any]) -> tuple[str, ...]:
    if raw_model.get("reasoning") is False:
        return ("off",)
    raw_map = raw_model.get("thinkingLevelMap")
    thinking_map = raw_map if isinstance(raw_map, dict) else {}
    levels: list[str] = []
    for level in PI_THINKING_LEVELS:
        if level in thinking_map and thinking_map[level] is None:
            continue
        if level in {"xhigh", "max"} and level not in thinking_map:
            continue
        levels.append(level)
    return tuple(levels) or ("off",)


def _pi_model_from_json(raw_model: Any) -> PiModel | None:
    if not isinstance(raw_model, dict):
        return None
    provider = str(raw_model.get("provider") or "").strip()
    model_id = str(raw_model.get("id") or "").strip()
    if not provider or not model_id:
        return None
    name = str(raw_model.get("name") or model_id).strip() or model_id
    return PiModel(
        provider=provider,
        model_id=model_id,
        name=name,
        supported_thinking_levels=_supported_thinking_levels(raw_model),
    )


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


def _pi_rpc_command() -> list[str]:
    return [
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
    request_type = str(request.get("type") or "requested").replace("_", " ")
    raise PiRuntimeError(f"Pi did not return a {request_type} response.")


def available_pi_models(
    *,
    timeout: float = PI_MODEL_DISCOVERY_TIMEOUT_SECONDS,
) -> list[PiModel]:
    command = _pi_rpc_command()
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
        model = _pi_model_from_json(raw_model)
        if model is None:
            continue
        models[model.settings_key] = model
    return sorted(
        models.values(),
        key=lambda model: (
            model.provider.casefold(),
            model.name.casefold(),
            model.model_id.casefold(),
        ),
    )


def current_pi_runtime_defaults(
    *,
    timeout: float = PI_MODEL_DISCOVERY_TIMEOUT_SECONDS,
) -> tuple[PiModel | None, str]:
    response = _pi_rpc_response(
        _pi_rpc_command(),
        {"type": "get_state"},
        timeout=timeout,
    )
    if response.get("success") is not True:
        error = str(response.get("error") or "unknown RPC error").strip()
        raise PiRuntimeError(f"Pi could not report its current model: {error}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise PiRuntimeError("Pi returned an invalid current-state response.")
    model = _pi_model_from_json(data.get("model"))
    thinking = str(data.get("thinkingLevel") or "medium").strip().lower()
    if thinking not in PI_THINKING_LEVELS:
        thinking = "medium"
    if model is not None:
        thinking = clamp_pi_thinking_level(model, thinking)
    return model, thinking


def available_pi_runtime_catalog(
    *,
    timeout: float = PI_MODEL_DISCOVERY_TIMEOUT_SECONDS,
) -> PiRuntimeCatalog:
    models = available_pi_models(timeout=timeout)
    default_model, default_thinking_level = current_pi_runtime_defaults(
        timeout=timeout
    )
    return PiRuntimeCatalog(
        models=tuple(models),
        default_model=default_model,
        default_thinking_level=default_thinking_level,
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
