from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("OPEN_LAW_LENS_CONFIG", str(PROJECT_DIR / "config.json")))
CONFIG_KEY_COURTLISTENER_TOKEN = "courtlistener_token"
CONFIG_KEY_CONCORDANCE_FILE_PATH = "concordance_file_path"
CONFIG_KEY_PRIOR_BRIEFS_FOLDER = "prior_briefs_folder"
# Opaque, inactive compatibility data. Never interpret, normalize, or insert defaults.
RETIRED_PROMPT_KEYS: tuple[str, ...] = (
    "general_agent_prompt_template",
    "case_agent_prompt_template",
    "brief_agent_prompt_template",
    "appeal_issue_agent_prompt_template",
    "subsequent_treatment_agent_prompt_template",
    "later_treatment_agent_prompt_template",
)
CONFIG_KEY_APPEAL_ISSUE_PRESETS = "appeal_issue_presets"
CONFIG_KEY_APPEAL_ISSUE_LABELS = "appeal_issue_labels"
CONFIG_KEY_AGENT_RUNTIME_PROFILES = "agent_runtime_profiles"
CONFIG_KEY_AGENT_RUNTIME_PROFILES_VERSION = "agent_runtime_profiles_version"
CONFIG_KEY_READER_FONT_SIZE_PT = "reader_font_size_pt"
CONFIG_KEY_READER_FONT_FAMILY = "reader_font_family"
CONFIG_KEY_SEARCH_MATCH_COLOR = "search_match_color"
CONFIG_KEY_LINKED_TEXT_COLOR = "linked_text_color"
CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE = "default_bare_statute_law_code"
ENV_CONCORDANCE_FILE = "OPEN_LAW_LENS_CONCORDANCE_FILE"
AGENT_PROFILE_LAW = "law"
AGENT_PROFILE_RESEARCH_CACHE = "research_cache"
AGENT_PROFILE_PRIOR_BRIEFS = "prior_briefs"
AGENT_PROFILE_ASSESS_ARGUMENT = "assess_argument"
AGENT_PROFILE_SUBSEQUENT_TREATMENT = "subsequent_treatment"
AGENT_PROFILE_KEYS: tuple[str, ...] = (
    AGENT_PROFILE_LAW,
    AGENT_PROFILE_RESEARCH_CACHE,
    AGENT_PROFILE_PRIOR_BRIEFS,
    AGENT_PROFILE_ASSESS_ARGUMENT,
    AGENT_PROFILE_SUBSEQUENT_TREATMENT,
)
# Version 2 introduced the independent Subsequent Treatment profile. Legacy
# configs clone Query Law once; version 2 absent means Use Pi defaults.
AGENT_RUNTIME_PROFILES_VERSION = 2
PI_THINKING_LEVELS: tuple[str, ...] = (
    "off", "minimal", "low", "medium", "high", "xhigh", "max",
)
DEFAULT_READER_FONT_SIZE_PT = 11
DEFAULT_SEARCH_MATCH_COLOR = "#fff3b0"
DEFAULT_LINKED_TEXT_COLOR = "#fff0a6"
# Retired preference: retained only for backward-compatible config round trips.
# No parser, lookup dispatcher, or reader may use this value to infer a code.
DEFAULT_BARE_STATUTE_LAW_CODE = "WIC"
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
    ("Bitstream Charter", '"Bitstream Charter", Charter, serif'),
    ("Linux Libertine O", '"Linux Libertine O", "Linux Libertine", serif'),
    ("Caladea", 'Caladea, Cambria, "Liberation Serif", serif'),
    ("Gentium Book Basic", '"Gentium Book Basic", Gentium, serif'),
    ("DejaVu Serif", '"DejaVu Serif", "Liberation Serif", serif'),
    ("Century Schoolbook", '"Century Schoolbook", "C059", "TeX Gyre Schola", serif'),
    (
        "TeX Gyre Schola",
        '"TeX Gyre Schola", "New Century Schoolbook", '
        '"Century Schoolbook L", "URW Schoolbook L", serif',
    ),
    ("Lato", 'Lato, Carlito, "Noto Sans", "Liberation Sans", sans-serif'),
)
DEFAULT_READER_FONT_FAMILY = READER_FONT_FAMILY_OPTIONS[0][0]
LEGACY_READER_FONT_FAMILY_ALIASES: dict[str, str] = {
    "Georgia": "Caladea",
    "Merriweather": "Bitstream Charter",
    "Source Sans 3": "Lato",
}

DEFAULT_APPEAL_ISSUE_PRESETS: tuple[str, ...] = (
    "Did substantial evidence support the challenged finding?",
    "Did the trial court abuse its discretion in making the challenged order?",
    "Did the trial court apply the correct legal standard?",
    "Did the proceedings afford the appellant due process, including adequate notice and a meaningful opportunity to be heard?",
    "If error occurred, was it prejudicial under the applicable appellate standard?",
)

# Inert preset compatibility only; never used to populate the composer.
LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS: dict[str, str] = {
    "Substantial evidence does not support the challenged finding.": (
        "Did substantial evidence support the challenged finding?"
    ),
    "The trial court abused its discretion in making the challenged order.": (
        "Did the trial court abuse its discretion in making the challenged order?"
    ),
    "The trial court applied the wrong legal standard.": (
        "Did the trial court apply the correct legal standard?"
    ),
    "The appellant was denied due process, notice, or a meaningful opportunity to be heard.": (
        "Did the proceedings afford the appellant due process, including adequate "
        "notice and a meaningful opportunity to be heard?"
    ),
    "The error was prejudicial and not harmless under the applicable appellate standard.": (
        "If error occurred, was it prejudicial under the applicable appellate standard?"
    ),
    "Substantial evidence did not support the order asserting dependency jurisdiction over the child[ren] under Welfare and Institutions Code section 300.": (
        "Did substantial evidence support the juvenile court's exercise of "
        "dependency jurisdiction over the child or children under Welfare and "
        "Institutions Code section 300?"
    ),
    "Substantial evidence did not support the order removing the child[ren] from parental custody under Welfare and Institutions Code section 361, subdivision (c)(1).": (
        "Did substantial evidence support the juvenile court's order removing the "
        "child or children from parental custody under Welfare and Institutions "
        "Code section 361, subdivision (c)(1)?"
    ),
    "The juvenile court abused its discretion in finding that the child welfare agency conducted an adequate Cal-ICWA inquiry. (Welf. & Inst. Code, § 224.2; In re Dezi C. (2024) 16 Cal.5th 1112, 1141.)": (
        "Did the juvenile court abuse its discretion in finding that the child "
        "welfare agency conducted an adequate Cal-ICWA inquiry under Welfare and "
        "Institutions Code section 224.2?"
    ),
    "The juvenile court erred in failing to apply the beneficial relationship exception. (Welf. & Inst. Code, § 366.26, subd. (c)(1)(B)(i); In re Caden C. (2021) 11 Cal.5th 614, 636.)": (
        "Did the juvenile court err in finding that the beneficial relationship "
        "exception to termination of parental rights did not apply under Welfare "
        "and Institutions Code section 366.26, subdivision (c)(1)(B)(i)?"
    ),
    "Clear and convincing evidence did not support a finding that the child was likely to be adopted within a reasonable time. (Welf. & Inst. Code, § 366.26, subd. (c)(1); In re Sarah M. (1994) 22 Cal.App.4th 1642, 1649.)": (
        "Did clear and convincing evidence support the juvenile court's finding "
        "that the child was likely to be adopted within a reasonable time under "
        "Welfare and Institutions Code section 366.26, subdivision (c)(1)?"
    ),
    "The juvenile court erred in denying the parent's section 388 petition after an evidentiary hearing. (Welf. & Inst. Code, § 388, subd. (a)(1); In re J.M. (2020) 50 Cal.App.5th 833, 846.)": (
        "Did the juvenile court err in denying the parent's Welfare and "
        "Institutions Code section 388 petition after an evidentiary hearing?"
    ),
    "The juvenile court erred in summarily denying the parent's section 388 petition without an evidentiary hearing. (Welf. & Inst. Code, § 388, subd. (a)(1); In re Edward H. (1996) 43 Cal.App.4th 584, 593.)": (
        "Did the juvenile court err in summarily denying the parent's Welfare and "
        "Institutions Code section 388 petition without an evidentiary hearing?"
    ),
    "The juvenile court erred in failing to grant the request for replacement counsel under People v. Marsden. (In re Z.N. (2010) 181 Cal.App.4th 282, 294.)": (
        "Did the juvenile court err in denying the request for replacement counsel "
        "under People v. Marsden?"
    ),
    "The juvenile court abused its discretion in denying the request to continue the matter. (Welf. & Inst. Code, § 352, subd. (a); In re Giovanni F. (2010) 184 Cal.App.4th 594, 605.)": (
        "Did the juvenile court abuse its discretion in denying the request to "
        "continue the matter under Welfare and Institutions Code section 352?"
    ),
}
DEFAULT_APPEAL_ISSUE_LABELS: tuple[str, ...] = (
    "Substantial evidence", "Abuse of discretion", "Wrong legal standard",
    "Due process", "Prejudice",
)


@dataclass(frozen=True, slots=True)
class PiAgentProfile:
    provider: str
    model: str
    thinking: str


@dataclass(frozen=True)
class AppConfig:
    courtlistener_token: str = ""
    concordance_file_path: str = ""
    prior_briefs_folder: str = ""
    retired_prompt_settings: dict[str, Any] = field(default_factory=dict, repr=False)
    appeal_issue_presets: list[str] = field(default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_PRESETS))
    appeal_issue_labels: list[str] = field(default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_LABELS))
    agent_runtime_profiles: dict[str, PiAgentProfile] = field(default_factory=dict)
    reader_font_size_pt: int = DEFAULT_READER_FONT_SIZE_PT
    reader_font_family: str = DEFAULT_READER_FONT_FAMILY
    search_match_color: str = DEFAULT_SEARCH_MATCH_COLOR
    linked_text_color: str = DEFAULT_LINKED_TEXT_COLOR
    default_bare_statute_law_code: str = DEFAULT_BARE_STATUTE_LAW_CODE


def coerce_reader_font_size(value: Any, default: int = DEFAULT_READER_FONT_SIZE_PT) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return default
    return min(48, max(8, size))


def normalize_search_color(value: Any, default: str) -> str:
    """Accept opaque hex colors only; never put arbitrary config into GTK tags."""
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
        return value.strip().lower()
    return default


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


def normalize_appeal_issue_presets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_APPEAL_ISSUE_PRESETS)
    presets: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "")
        replacement = LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS.get(
            text
        ) or LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS.get(text.strip())
        if replacement is not None:
            text = replacement
        text = text.strip()
        key = text.casefold()
        if text and key not in seen:
            presets.append(text)
            seen.add(key)
    return presets or list(DEFAULT_APPEAL_ISSUE_PRESETS)


def normalize_appeal_issue_labels(value: Any, presets: list[str]) -> list[str]:
    presets_are_defaults = (
        len(presets) == len(DEFAULT_APPEAL_ISSUE_PRESETS)
        and all(left == right for left, right in zip(presets, DEFAULT_APPEAL_ISSUE_PRESETS))
    )
    if value is None and presets_are_defaults:
        return list(DEFAULT_APPEAL_ISSUE_LABELS)
    raw_labels = value if isinstance(value, list) else []
    labels = [str(item or "").strip() for item in raw_labels[: len(presets)]]
    labels.extend([""] * (len(presets) - len(labels)))
    return labels


def normalize_agent_runtime_profiles(value: Any) -> dict[str, PiAgentProfile]:
    if not isinstance(value, dict):
        return {}
    profiles: dict[str, PiAgentProfile] = {}
    for key in AGENT_PROFILE_KEYS:
        raw_profile = value.get(key)
        if not isinstance(raw_profile, dict):
            continue
        provider = str(raw_profile.get("provider") or "").strip()
        model = str(raw_profile.get("model") or "").strip()
        thinking = str(raw_profile.get("thinking") or "").strip().lower()
        if provider and model and thinking in PI_THINKING_LEVELS:
            profiles[key] = PiAgentProfile(provider=provider, model=model, thinking=thinking)
    return profiles


def stored_agent_runtime_profiles_version(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def migrate_agent_runtime_profiles(
    profiles: dict[str, PiAgentProfile],
    raw_profiles: Any,
    schema_version: int = 1,
) -> dict[str, PiAgentProfile]:
    """Clone legacy Query Law once, without overriding known/default selections."""
    if schema_version >= AGENT_RUNTIME_PROFILES_VERSION:
        return profiles
    if AGENT_PROFILE_SUBSEQUENT_TREATMENT in profiles:
        return profiles
    if isinstance(raw_profiles, dict) and AGENT_PROFILE_SUBSEQUENT_TREATMENT in raw_profiles:
        return profiles
    law_profile = profiles.get(AGENT_PROFILE_LAW)
    if law_profile is None:
        return profiles
    migrated = dict(profiles)
    migrated[AGENT_PROFILE_SUBSEQUENT_TREATMENT] = PiAgentProfile(
        provider=law_profile.provider, model=law_profile.model, thinking=law_profile.thinking,
    )
    return migrated


def reader_font_css(font_family: str) -> str:
    normalized = normalize_reader_font_family(font_family)
    for name, css in READER_FONT_FAMILY_OPTIONS:
        if normalized == name:
            return css
    return READER_FONT_FAMILY_OPTIONS[0][1]


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    """Read settings only; retired prompt JSON stays opaque, including both aliases."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()
    token = raw.get(CONFIG_KEY_COURTLISTENER_TOKEN, "")
    concordance_path = os.environ.get(ENV_CONCORDANCE_FILE, raw.get(CONFIG_KEY_CONCORDANCE_FILE_PATH, ""))
    appeal_issue_presets = normalize_appeal_issue_presets(raw.get(CONFIG_KEY_APPEAL_ISSUE_PRESETS))
    return AppConfig(
        courtlistener_token=str(token).strip(),
        concordance_file_path=str(concordance_path).strip(),
        prior_briefs_folder=(
            raw[CONFIG_KEY_PRIOR_BRIEFS_FOLDER].strip()
            if isinstance(raw.get(CONFIG_KEY_PRIOR_BRIEFS_FOLDER), str) else ""
        ),
        retired_prompt_settings={key: raw[key] for key in RETIRED_PROMPT_KEYS if key in raw},
        appeal_issue_presets=appeal_issue_presets,
        appeal_issue_labels=normalize_appeal_issue_labels(
            raw.get(CONFIG_KEY_APPEAL_ISSUE_LABELS), appeal_issue_presets,
        ),
        agent_runtime_profiles=migrate_agent_runtime_profiles(
            normalize_agent_runtime_profiles(raw.get(CONFIG_KEY_AGENT_RUNTIME_PROFILES)),
            raw.get(CONFIG_KEY_AGENT_RUNTIME_PROFILES),
            stored_agent_runtime_profiles_version(raw.get(CONFIG_KEY_AGENT_RUNTIME_PROFILES_VERSION)),
        ),
        reader_font_size_pt=coerce_reader_font_size(raw.get(CONFIG_KEY_READER_FONT_SIZE_PT)),
        reader_font_family=normalize_reader_font_family(raw.get(CONFIG_KEY_READER_FONT_FAMILY)),
        search_match_color=normalize_search_color(raw.get(CONFIG_KEY_SEARCH_MATCH_COLOR), DEFAULT_SEARCH_MATCH_COLOR),
        linked_text_color=normalize_search_color(raw.get(CONFIG_KEY_LINKED_TEXT_COLOR), DEFAULT_LINKED_TEXT_COLOR),
        default_bare_statute_law_code=normalize_bare_statute_law_code(raw.get(CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE)),
    )


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    appeal_issue_presets = normalize_appeal_issue_presets(config.appeal_issue_presets)
    appeal_issue_labels = list(config.appeal_issue_labels)
    if (
        appeal_issue_labels == list(DEFAULT_APPEAL_ISSUE_LABELS)
        and appeal_issue_presets != list(DEFAULT_APPEAL_ISSUE_PRESETS)
    ):
        appeal_issue_labels = []
    data: dict[str, Any] = {
        CONFIG_KEY_COURTLISTENER_TOKEN: config.courtlistener_token.strip(),
        CONFIG_KEY_CONCORDANCE_FILE_PATH: config.concordance_file_path.strip(),
        CONFIG_KEY_PRIOR_BRIEFS_FOLDER: config.prior_briefs_folder.strip(),
        CONFIG_KEY_APPEAL_ISSUE_PRESETS: appeal_issue_presets,
        CONFIG_KEY_APPEAL_ISSUE_LABELS: normalize_appeal_issue_labels(appeal_issue_labels, appeal_issue_presets),
        CONFIG_KEY_AGENT_RUNTIME_PROFILES_VERSION: AGENT_RUNTIME_PROFILES_VERSION,
        CONFIG_KEY_AGENT_RUNTIME_PROFILES: {
            key: {"provider": profile.provider, "model": profile.model, "thinking": profile.thinking}
            for key, profile in config.agent_runtime_profiles.items()
            if key in AGENT_PROFILE_KEYS
            and profile.provider.strip()
            and profile.model.strip()
            and profile.thinking in PI_THINKING_LEVELS
        },
        CONFIG_KEY_READER_FONT_SIZE_PT: coerce_reader_font_size(config.reader_font_size_pt),
        CONFIG_KEY_READER_FONT_FAMILY: normalize_reader_font_family(config.reader_font_family),
        CONFIG_KEY_SEARCH_MATCH_COLOR: normalize_search_color(config.search_match_color, DEFAULT_SEARCH_MATCH_COLOR),
        CONFIG_KEY_LINKED_TEXT_COLOR: normalize_search_color(config.linked_text_color, DEFAULT_LINKED_TEXT_COLOR),
        CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE: normalize_bare_statute_law_code(config.default_bare_statute_law_code),
    }
    data.update({key: config.retired_prompt_settings[key] for key in RETIRED_PROMPT_KEYS if key in config.retired_prompt_settings})
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(
            json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


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
