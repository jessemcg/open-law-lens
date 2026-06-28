from __future__ import annotations

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
CONFIG_KEY_SEARCH_INCLUDE_UNPUBLISHED = "search_include_unpublished"
ENV_CONCORDANCE_FILE = "OPEN_LAW_LENS_CONCORDANCE_FILE"
DEFAULT_READER_FONT_SIZE_PT = 11
READER_FONT_FAMILY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Noto Serif", '"Noto Serif", "Liberation Serif", "DejaVu Serif", serif'),
    ("Georgia", 'Georgia, "Times New Roman", "Liberation Serif", serif'),
    ("Merriweather", '"Merriweather", "Noto Serif", "Liberation Serif", serif'),
    ("Source Sans 3", '"Source Sans 3", "Noto Sans", "Liberation Sans", sans-serif'),
    (
        "TeX Gyre Schola",
        '"TeX Gyre Schola", "New Century Schoolbook", '
        '"Century Schoolbook L", "URW Schoolbook L", serif',
    ),
)
DEFAULT_READER_FONT_FAMILY = READER_FONT_FAMILY_OPTIONS[0][0]
LEGACY_READER_FONT_FAMILY_ALIASES = {
    "Century Schoolbook": "TeX Gyre Schola",
}

DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use the CourtListener MCP server only for legal authority and legal research. Do not use local Open Law Lens cache files, the durable library database, local project files, web browsing, or shell commands as legal authority.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available.

Question:
{question}"""

DEFAULT_CASE_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Marked Research Cache Cases Agent.

Answer only from the selected cached cases exported into this workspace. Do not use CourtListener MCP, web browsing, or unselected Open Law Lens cases. If the exported cases do not answer the question, say that plainly.

In your answer, include short direct quotes from the record to highlight legally significant statements. Each quote should be only two to five words long, enclosed in quotation marks, and must include continuous phrases exactly as they appear in the source text.

Question:
{question}

Selected case manifest:
{case_manifest}

Selected case text directory:
{case_dir}

Selected case count: {case_count}"""


@dataclass(frozen=True)
class AppConfig:
    courtlistener_token: str = ""
    concordance_file_path: str = ""
    general_agent_prompt_template: str = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt_template: str = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
    reader_font_size_pt: int = DEFAULT_READER_FONT_SIZE_PT
    reader_font_family: str = DEFAULT_READER_FONT_FAMILY
    search_include_unpublished: bool = False


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
        search_include_unpublished=bool(raw.get(CONFIG_KEY_SEARCH_INCLUDE_UNPUBLISHED, False)),
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
        CONFIG_KEY_SEARCH_INCLUDE_UNPUBLISHED: bool(config.search_include_unpublished),
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
