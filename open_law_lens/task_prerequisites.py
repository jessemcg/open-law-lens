"""Task-local readiness classifications; no GTK, network or preference writes."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from . import pi_runtime
from .config import PiAgentProfile


class Reason(StrEnum):
    TOKEN = "token_missing"
    PI_MISSING = "pi_missing"
    PI_START = "pi_start_failed"
    MODELS_EMPTY = "models_empty"
    MODEL = "model_unavailable"
    CATALOG = "catalog_failed"
    TERMINAL = "terminal_missing"
    LAUNCHER = "launcher_missing"


MESSAGES = {
    Reason.TOKEN: "CourtListener API token is missing. Add it in Settings → General.",
    Reason.PI_MISSING: "Pi is not installed. Install Pi to use Agent questions.",
    Reason.PI_START: "Pi could not start. Check your Pi installation.",
    Reason.MODELS_EMPTY: "No authorized Pi models are available. Open Pi and use /login to authorize a provider.",
    Reason.MODEL: "Choose an available model in Settings → Agent Model.",
    Reason.CATALOG: "Could not check Pi models. Check Pi setup and try again.",
    Reason.TERMINAL: "Agent questions need VTE terminal support. Install VTE for GTK 4.",
    Reason.LAUNCHER: "Agent support is incomplete. Repair the Open Law Lens installation.",
}


@dataclass(frozen=True)
class Result:
    reason: Reason | None = None

    @property
    def message(self) -> str:
        return MESSAGES[self.reason] if self.reason is not None else ""


def cheap_check(*, research: bool, token: str, terminal: bool, launcher: bool) -> Result:
    if research and not token.strip():
        return Result(Reason.TOKEN)
    try:
        pi_runtime.require_pi_executable()
    except pi_runtime.PiExecutableMissing:
        return Result(Reason.PI_MISSING)
    except pi_runtime.PiStartError:
        return Result(Reason.PI_START)
    if not terminal:
        return Result(Reason.TERMINAL)
    if not launcher:
        return Result(Reason.LAUNCHER)
    return Result()


def model_check(profile: PiAgentProfile | None) -> Result:
    try:
        catalog = pi_runtime.available_pi_runtime_catalog()
    except pi_runtime.PiStartError:
        return Result(Reason.PI_START)
    except Exception:
        # A query failure (including malformed output) says nothing about auth.
        return Result(Reason.CATALOG)
    if not catalog.models:
        return Result(Reason.MODELS_EMPTY)
    selected = (profile.provider, profile.model) if profile else (
        catalog.default_model.settings_key if catalog.default_model else None
    )
    if selected not in {model.settings_key for model in catalog.models}:
        return Result(Reason.MODEL)
    return Result()
