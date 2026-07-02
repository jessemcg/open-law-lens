from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("OPEN_LAW_LENS_CONFIG", str(PROJECT_DIR / "config.json")))
CONFIG_KEY_COURTLISTENER_TOKEN = "courtlistener_token"
CONFIG_KEY_CONCORDANCE_FILE_PATH = "concordance_file_path"
CONFIG_KEY_GENERAL_AGENT_PROMPT_TEMPLATE = "general_agent_prompt_template"
CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE = "case_agent_prompt_template"
CONFIG_KEY_READER_FONT_SIZE_PT = "reader_font_size_pt"
CONFIG_KEY_READER_FONT_FAMILY = "reader_font_family"
CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE = "default_bare_statute_law_code"
CONFIG_KEY_AGENT_PERMISSION_MODE = "agent_permission_mode"
ENV_CONCORDANCE_FILE = "OPEN_LAW_LENS_CONCORDANCE_FILE"
DEFAULT_READER_FONT_SIZE_PT = 11
DEFAULT_BARE_STATUTE_LAW_CODE = "WIC"
AGENT_PERMISSION_MODE_SANDBOXED = "sandboxed"
AGENT_PERMISSION_MODE_FULL_ACCESS = "full_access"
DEFAULT_AGENT_PERMISSION_MODE = AGENT_PERMISSION_MODE_SANDBOXED
AGENT_PERMISSION_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    (AGENT_PERMISSION_MODE_SANDBOXED, "Sandboxed"),
    (AGENT_PERMISSION_MODE_FULL_ACCESS, "Full access"),
)
BARE_STATUTE_LAW_CODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("WIC", "Welfare and Institutions Code"),
    ("EVID", "Evidence Code"),
    ("CIV", "Civil Code"),
    ("CCP", "Code of Civil Procedure"),
    ("FAM", "Family Code"),
    ("PEN", "Penal Code"),
)
READER_FONT_FAMILY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Noto Serif", '"Noto Serif", "Liberation Serif", "DejaVu Serif", serif'),
    ("Georgia", 'Georgia, "Times New Roman", "Liberation Serif", serif'),
    ("Merriweather", '"Merriweather", "Noto Serif", "Liberation Serif", serif'),
    ("Century Schoolbook", '"Century Schoolbook", "C059", "TeX Gyre Schola", serif'),
    ("Source Sans 3", '"Source Sans 3", "Noto Sans", "Liberation Sans", sans-serif'),
    (
        "TeX Gyre Schola",
        '"TeX Gyre Schola", "New Century Schoolbook", '
        '"Century Schoolbook L", "URW Schoolbook L", serif',
    ),
)
DEFAULT_READER_FONT_FAMILY = READER_FONT_FAMILY_OPTIONS[0][0]
LEGACY_READER_FONT_FAMILY_ALIASES: dict[str, str] = {}

LEGACY_GENERAL_AGENT_PROMPT_SHA256 = "50a9928018ec7d3b06b322db9e5a211e56c7a155b09537d1f7057906fb6a14e4"

DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

For California case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `uv run open-law-lens extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

Use Google Scholar or Codex web search only as a fallback to verify or fill in an official reporter citation or official text when CourtListener metadata is missing or suspect. State when a citation remains uncertain.

Question:
{question}"""

DEFAULT_CASE_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Marked Research Cache Authorities Agent.

Answer only from the selected cached authorities exported into this workspace. Do not use web browsing or unselected Open Law Lens authorities. If the exported authorities do not answer the question, say that plainly.

In your answer, include short direct quotes from the record to highlight legally significant statements. Each quote should be only two to five words long, enclosed in quotation marks, and must include continuous phrases exactly as they appear in the source text.

Question:
{question}

Selected authority manifest:
{case_manifest}

Selected authority text directory:
{case_dir}

Selected authority count: {case_count}"""


@dataclass(frozen=True)
class AppConfig:
    courtlistener_token: str = ""
    concordance_file_path: str = ""
    general_agent_prompt_template: str = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt_template: str = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
    reader_font_size_pt: int = DEFAULT_READER_FONT_SIZE_PT
    reader_font_family: str = DEFAULT_READER_FONT_FAMILY
    default_bare_statute_law_code: str = DEFAULT_BARE_STATUTE_LAW_CODE
    agent_permission_mode: str = DEFAULT_AGENT_PERMISSION_MODE


def coerce_reader_font_size(value: Any, default: int = DEFAULT_READER_FONT_SIZE_PT) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return min(48, max(8, size))


def normalize_reader_font_family(value: Any) -> str:
    normalized = str(value or "").strip()
    normalized = LEGACY_READER_FONT_FAMILY_ALIASES.get(normalized, normalized)
    for name, _css in READER_FONT_FAMILY_OPTIONS:
        if normalized == name:
            return name
    return DEFAULT_READER_FONT_FAMILY


def normalize_bare_statute_law_code(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    for code, _label in BARE_STATUTE_LAW_CODE_OPTIONS:
        if normalized == code:
            return code
    return DEFAULT_BARE_STATUTE_LAW_CODE


def normalize_agent_permission_mode(value: Any) -> str:
    normalized = str(value or "").strip()
    for mode, _label in AGENT_PERMISSION_MODE_OPTIONS:
        if normalized == mode:
            return mode
    return DEFAULT_AGENT_PERMISSION_MODE


def reader_font_css(font_family: str) -> str:
    normalized = normalize_reader_font_family(font_family)
    for name, css in READER_FONT_FAMILY_OPTIONS:
        if normalized == name:
            return css
    return READER_FONT_FAMILY_OPTIONS[0][1]


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppConfig()
    except (json.JSONDecodeError, OSError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    token = raw.get(CONFIG_KEY_COURTLISTENER_TOKEN, "")
    concordance_path = os.environ.get(ENV_CONCORDANCE_FILE, raw.get(CONFIG_KEY_CONCORDANCE_FILE_PATH, ""))
    general_agent_prompt = raw.get(
        CONFIG_KEY_GENERAL_AGENT_PROMPT_TEMPLATE,
        DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE,
    )
    prompt_hash = hashlib.sha256(str(general_agent_prompt).strip().encode()).hexdigest()
    if prompt_hash == LEGACY_GENERAL_AGENT_PROMPT_SHA256:
        general_agent_prompt = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt = raw.get(
        CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE,
        DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    )
    return AppConfig(
        courtlistener_token=str(token).strip(),
        concordance_file_path=str(concordance_path).strip(),
        general_agent_prompt_template=(
            str(general_agent_prompt).strip() or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
        ),
        case_agent_prompt_template=(
            str(case_agent_prompt).strip() or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
        ),
        reader_font_size_pt=coerce_reader_font_size(raw.get(CONFIG_KEY_READER_FONT_SIZE_PT)),
        reader_font_family=normalize_reader_font_family(raw.get(CONFIG_KEY_READER_FONT_FAMILY)),
        default_bare_statute_law_code=normalize_bare_statute_law_code(
            raw.get(CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE)
        ),
        agent_permission_mode=normalize_agent_permission_mode(
            raw.get(CONFIG_KEY_AGENT_PERMISSION_MODE)
        ),
    )


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    data: dict[str, Any] = {
        CONFIG_KEY_COURTLISTENER_TOKEN: config.courtlistener_token.strip(),
        CONFIG_KEY_CONCORDANCE_FILE_PATH: config.concordance_file_path.strip(),
        CONFIG_KEY_GENERAL_AGENT_PROMPT_TEMPLATE: (
            config.general_agent_prompt_template.strip() or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE: (
            config.case_agent_prompt_template.strip() or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_READER_FONT_SIZE_PT: coerce_reader_font_size(config.reader_font_size_pt),
        CONFIG_KEY_READER_FONT_FAMILY: normalize_reader_font_family(config.reader_font_family),
        CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE: normalize_bare_statute_law_code(
            config.default_bare_statute_law_code
        ),
        CONFIG_KEY_AGENT_PERMISSION_MODE: normalize_agent_permission_mode(
            config.agent_permission_mode
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def courtlistener_token() -> str:
    env_token = os.environ.get("COURTLISTENER_TOKEN", "").strip()
    if env_token:
        return env_token
    return load_config().courtlistener_token


def concordance_file_path() -> Path | None:
    path = load_config().concordance_file_path
    if not path:
        return None
    return Path(path).expanduser()
