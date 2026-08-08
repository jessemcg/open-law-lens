from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

TAVILY_API_URL = "https://api.tavily.com/search"
COMMAND_TIMEOUT_SECONDS = 5
MAX_CREDENTIAL_BYTES = 16_384
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 60
_ENV_SOURCE_RE = re.compile(r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$")
_COMMAND_ENV_NAMES = (
    "HOME", "USER", "LOGNAME", "PATH", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TMPDIR", "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS", "SSH_AUTH_SOCK", "WSL_DISTRO_NAME", "WSL_INTEROP",
)


class TavilyError(RuntimeError):
    category = "unknown"


class TavilyConfigurationError(TavilyError):
    category = "configuration"


class TavilyAuthenticationError(TavilyError):
    category = "authentication"


class TavilyNetworkError(TavilyError):
    category = "network"


@dataclass(frozen=True)
class TavilyResult:
    url: str
    title: str = ""
    content: str = ""
    raw_content: str = ""


def web_search_config_path(environment: Mapping[str, str] | None = None) -> Path:
    env = environment if environment is not None else os.environ
    if env.get("PI_CODING_AGENT_DIR"):
        return Path(env["PI_CODING_AGENT_DIR"]).expanduser() / "web-search.json"
    if env.get("XDG_CONFIG_HOME"):
        return Path(env["XDG_CONFIG_HOME"]).expanduser() / "pi" / "web-search.json"
    return Path(env.get("HOME") or Path.home()).expanduser() / ".pi" / "web-search.json"


def _command_environment(environment: Mapping[str, str]) -> dict[str, str]:
    result = {name: environment[name] for name in _COMMAND_ENV_NAMES if name in environment}
    result.update(
        (name, value)
        for name, value in environment.items()
        if re.fullmatch(r"OP_SESSION_[A-Za-z0-9_]+", name)
    )
    return result


def resolve_credential_source(
    configured_value: object,
    environment_value: object = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    env = environment if environment is not None else os.environ
    source = configured_value.strip() if isinstance(configured_value, str) else ""
    env_value = environment_value.strip() if isinstance(environment_value, str) else ""
    if source.startswith("$$") or source.startswith("$!"):
        return source[1:]
    if source.startswith("!"):
        command = source[1:].strip()
        if not command:
            raise TavilyConfigurationError("Tavily credential resolution failed: invalid-source")
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                env=_command_environment(env),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-timeout") from exc
        except OSError as exc:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-failed") from exc
        if len(completed.stdout) > MAX_CREDENTIAL_BYTES:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-output-too-large")
        if completed.returncode != 0:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-failed")
        try:
            value = completed.stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-invalid-output") from exc
        if not value:
            raise TavilyConfigurationError("Tavily credential resolution failed: command-empty")
        if re.search(r"[\x00-\x1f\x7f]", value):
            raise TavilyConfigurationError("Tavily credential resolution failed: command-invalid-output")
        return value
    match = _ENV_SOURCE_RE.fullmatch(source)
    if source.startswith("$") and match is None:
        raise TavilyConfigurationError("Tavily credential resolution failed: invalid-source")
    if match is not None:
        value = str(env.get(match.group(1) or match.group(2)) or "").strip()
        if not value:
            raise TavilyConfigurationError("Tavily credential resolution failed: environment-empty")
        return value
    return env_value or source or None


def tavily_api_key(environment: Mapping[str, str] | None = None) -> str | None:
    env = environment if environment is not None else os.environ
    path = web_search_config_path(env)
    configured: object = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TavilyConfigurationError(f"Could not parse Tavily configuration at {path}.") from exc
        if not isinstance(data, dict):
            raise TavilyConfigurationError(f"Tavily configuration at {path} must be a JSON object.")
        configured = data.get("tavilyApiKey")
    return resolve_credential_source(
        configured,
        env.get("TAVILY_API_KEY"),
        environment=env,
    )


def _redacted(text: str, secret: str) -> str:
    return text.replace(secret, "[redacted]") if secret else text


class TavilyClient:
    def __init__(self, api_key: str | None = None, *, environment: Mapping[str, str] | None = None):
        self._api_key = api_key
        self._environment = environment

    def search(self, query: str) -> list[TavilyResult]:
        api_key = self._api_key or tavily_api_key(self._environment)
        if not api_key:
            raise TavilyConfigurationError("Tavily API key not found in Pi Web Access configuration.")
        body = json.dumps({
            "query": re.sub(r"\s+", " ", query).strip(),
            "search_depth": "basic",
            "max_results": 10,
            "include_answer": "basic",
            "include_raw_content": "markdown",
        }).encode("utf-8")
        request = urllib.request.Request(
            TAVILY_API_URL,
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=SEARCH_TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            message = _redacted(str(exc), api_key)
            if exc.code in {401, 403}:
                raise TavilyAuthenticationError(f"Tavily authentication failed (HTTP {exc.code}).") from exc
            if exc.code == 429 or exc.code >= 500:
                raise TavilyNetworkError(f"Tavily request failed temporarily (HTTP {exc.code}).") from exc
            raise TavilyError(f"Tavily request failed: {message}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TavilyNetworkError(_redacted("Tavily network request failed.", api_key)) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise TavilyNetworkError("Tavily response exceeded the safe size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TavilyNetworkError("Tavily returned an invalid response.") from exc
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []
        results: list[TavilyResult] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            parsed = urllib.parse.urlparse(url)
            dedupe_url = urllib.parse.urlunparse(
                parsed._replace(
                    scheme=parsed.scheme.casefold(),
                    netloc=parsed.netloc.casefold(),
                    fragment="",
                )
            )
            if dedupe_url in seen:
                continue
            seen.add(dedupe_url)
            url = dedupe_url
            results.append(TavilyResult(
                url=url,
                title=str(row.get("title") or "").strip(),
                content=str(row.get("content") or "").strip(),
                raw_content=str(row.get("raw_content") or "").strip(),
            ))
            if len(results) >= 10:
                break
        return results
