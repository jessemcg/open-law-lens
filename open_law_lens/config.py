from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("OPEN_LAW_LENS_CONFIG", str(PROJECT_DIR / "config.json")))
CONFIG_KEY_COURTLISTENER_TOKEN = "courtlistener_token"
CONFIG_KEY_CONCORDANCE_FILE_PATH = "concordance_file_path"
CONFIG_KEY_GENERAL_AGENT_PROMPT_TEMPLATE = "general_agent_prompt_template"
CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE = "case_agent_prompt_template"
CONFIG_KEY_BRIEF_AGENT_PROMPT_TEMPLATE = "brief_agent_prompt_template"
CONFIG_KEY_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE = "appeal_issue_agent_prompt_template"
CONFIG_KEY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE = "subsequent_treatment_agent_prompt_template"
CONFIG_KEY_LEGACY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE = "later_treatment_agent_prompt_template"
CONFIG_KEY_GENERAL_AGENT_XHIGH_REASONING = "general_agent_xhigh_reasoning"
CONFIG_KEY_CASE_AGENT_XHIGH_REASONING = "case_agent_xhigh_reasoning"
CONFIG_KEY_BRIEF_AGENT_XHIGH_REASONING = "brief_agent_xhigh_reasoning"
CONFIG_KEY_APPEAL_ISSUE_XHIGH_REASONING = "appeal_issue_xhigh_reasoning"
CONFIG_KEY_LATER_TREATMENT_XHIGH_REASONING = "later_treatment_xhigh_reasoning"
CONFIG_KEY_APPEAL_ISSUE_PRESETS = "appeal_issue_presets"
CONFIG_KEY_APPEAL_ISSUE_LABELS = "appeal_issue_labels"
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

LEGACY_GENERAL_AGENT_PROMPT_SHA256ES = (
    "50a9928018ec7d3b06b322db9e5a211e56c7a155b09537d1f7057906fb6a14e4",
    "5d787ed00945b45a32f60026679908a718fc7d174080951f5f3bbe5e70921dc6",
    "e8da4e994bce96bd6acc337c1361fa225adf62a6cc5f5044ff42ed17c1d14aec",
)
LEGACY_CASE_AGENT_PROMPT_SHA256ES = (
    "90bd5ba6984eb91b4b7c72c3a33617896ed2b6279ce3bdd5592f07f15fc73f9b",
    "58395b3951138bf6ebdc383a5f52366ca7f7c81e0fcd6b1b75b6095c36a5f3d8",
    "21f8d2e20a04a17942009d9bb12957263ed4461f58cf46d7d62e40aa8da7d604",
    "5c11542ccdffaef4e88e0fa568bc1dc9b35204cb3d4cf2d1983db829217596a9",
    "b34a8f1ffb8ae9e574c5caf791739d2745ed330013c420b85fb30c384d15123f",
    "11b5512669311cff769c62e9e91f7ed27ef2793042a2807584375d36fba64cdb",
    "e33c90f7bb6f972b9ed934f155420a51c51dd8e64b613ca41cbda250fe37847a",
)
LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES = (
    "b57fb338bb6148eaa4937be89de687884b1f42f2ef2d966d9d4a21cb3816d338",
    "89f0c0d29553434588a1060de8d979d91c9a15ca27b214ee16ff3498209b6089",
    "825b58f274b81af60c7fdd0fb2a55e9a6ad43c8bbd31f6d51f0c632d2c7a5599",
    "cc5c2ba125d0ee0ff42d65db1b58f0d9e7fc281ad1a12d3693f82caca551af24",
    "148e132f9bf9440d84437f2116cb2f2bcc7bbc4654d1508d2644ea8a9dbb3614",
    "5efdaaf4380c89a75ed1073d8a6476511cd59d58c54837e6d741f8dfa386e8a2",
)

DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

For California case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. Extract the most relevant candidate opinions with `uv run open-law-lens extract-case --cluster-id <cluster_id>` before relying on a case in the answer.

Confine research to California state law unless the user's question explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority when available. Use `case-search --include-unpublished` only when unpublished cases are useful for context, not as controlling authority.

Use Google Scholar or Codex web search only as a fallback to verify or fill in an official reporter citation or official text when CourtListener metadata is missing or suspect. State when a citation remains uncertain.

For a recent published California slip opinion with no official reporter citation, a placeholder like `___ Cal.App.5th ___`, or only a docket number, run targeted Google Scholar or web searches using the case name, docket number, filed date, and `Cal.App.5th`. If an official citation is found, retry `uv run open-law-lens extract-case "<official citation>"` and rely on the extracted text, source, warnings, and reporter markers.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Do not wrap legal authorities or citations in backticks. Reserve backticks only for CLI commands, file paths, and other literal technical text.

Question:
{question}"""

DEFAULT_CASE_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Marked Research Cache Agent.

Answer only from the selected Research Cache materials and any current-case factual context explicitly selected for this run. Do not use web browsing or unselected Open Law Lens materials. Treat cases, statutes, and rules as legal authority. Treat prior briefs as prior advocacy that may supply argument language but is not legal authority. Treat any current-case fact pattern as factual context only, not as legal authority. Treat saved agent answers as prior analysis for context only, not as legal authority. If the exported materials do not answer the question, say that plainly.

When current-case factual context is provided and the question calls for comparison, compare the current case with the selected authorities using legally significant facts, procedural posture, legal issues, and governing standards. Cite current-case facts with the record citations already present in the fact pattern. Do not cite local paths, filenames, or line numbers.

In your answer, include short direct quotes from selected cases, statutes, and rules, and from selected prior briefs when useful. Do not use the current-case fact pattern or saved agent answers as the source of these quotes. Each quote should be only two to five words long, enclosed in quotation marks, and must include continuous phrases exactly as they appear in the source text. Put a full identifying case, statute, rule, or prior-brief title in the same paragraph as each quote; one identifier may support multiple quotes from the same source. Clearly label prior-brief quotations as prior advocacy rather than law.

Question:
{question}

Selected authority manifest:
{case_manifest}

Selected authority text directory:
{case_dir}

Selected authority count: {case_count}"""

DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Prior Brief Agent.

Answer only from the indexed prior brief archive and any current-case factual context explicitly selected for this run. Do not browse the web, research CourtListener, or treat prior advocacy as legal authority. Use the Open Law Lens CLI iteratively to find candidate briefs, then inspect the full text of every brief relied upon.

Start with focused searches such as:
`uv run --no-sync open-law-lens search-briefs "<terms>" --match all`
Try related wording, phrase, and any-term searches when the first search is incomplete. Use `--sort newest` when recency matters. Read a candidate with:
`uv run --no-sync open-law-lens extract-brief <brief_id>`

Identify every discussed source with the exact Markdown link returned by search, in this form: `[Exact indexed title](open-law-lens://prior-brief/<brief_id>)`. Put that linked title close to the discussion and any quote from that brief. Include useful direct quotes of only two to ten words, copied as exact continuous phrases. If the archive does not answer the question, say so plainly.

Distinguish opening briefs, reply briefs, respondent's briefs, oppositions, Phoenix H. memos, and other documents. For a request for the most recent document, use the indexed document date and explain when it is a file-date fallback.

Question:
{question}

Prior brief database snapshot:
{brief_database}

Indexed brief count: {brief_count}"""

DEFAULT_APPEAL_ISSUE_PRESETS: tuple[str, ...] = (
    "Substantial evidence does not support the challenged finding.",
    "The trial court abused its discretion in making the challenged order.",
    "The trial court applied the wrong legal standard.",
    "The appellant was denied due process, notice, or a meaningful opportunity to be heard.",
    "The error was prejudicial and not harmless under the applicable appellate standard.",
)
DEFAULT_APPEAL_ISSUE_LABELS: tuple[str, ...] = (
    "Substantial evidence",
    "Abuse of discretion",
    "Wrong legal standard",
    "Due process",
    "Prejudice",
)

DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Appeal Issue Assessment Agent.

Assess one possible California appellate argument against the user's fact pattern. Use Open Law Lens CLI commands tied directly to CourtListener APIs for legal authority and legal research.

Read the extracted fact-pattern text first:
{fact_pattern_path}

Original fact-pattern file:
{fact_pattern_source_path}

Record citation format for final answers:
- Cite factual claims using record citations from the fact-pattern text, the way an appellate lawyer would, such as `(CT 335-343.)`, `(RT 6, 34; CT 140, 190.)`, or `(RT 22-34; CRT 17-22; CT 295-301.)`.
- Do not cite local paths, extracted-text filenames, raw file pages, or line numbers in the final answer. Use those only as internal search leads.
- Put record citations in the same sentence or paragraph as the factual claim they support.
- Combine multiple record citations into one parenthetical only when they support the same point.
- If the fact-pattern text does not include a usable record citation for an important fact, say that the citation is missing or uncertain instead of inventing one.

Argument to assess:
{issue}

Research California law with Open Law Lens CLI commands. For case-law discovery, start with `uv run open-law-lens case-search "<query>"`. Treat search results as leads only. When a promising search result has an official citation or recognizable case name, try `uv run open-law-lens extract-case "<official citation or case name>"` first so saved durable-library text can be reused. Use `uv run open-law-lens extract-case --cluster-id <cluster_id>` only when citation/name extraction fails or no reliable citation/name is available. Use `uv run open-law-lens extract-statute "<citation>"` and `uv run open-law-lens extract-rule "<citation>"` when statutes or rules matter.

For a recent published California slip opinion with no official reporter citation, a placeholder like `___ Cal.App.5th ___`, or only a docket number, run targeted Google Scholar or web searches using the case name, docket number, filed date, and `Cal.App.5th`. If an official citation is found, retry `uv run open-law-lens extract-case "<official citation>"` and rely on the extracted text, source, warnings, and reporter markers.

Confine research to California state law unless the argument explicitly requires federal law. Prefer published California Supreme Court and California Court of Appeal authority. Use unpublished cases only for context, not as controlling authority.

Analyze preservation, standard of review, factual support, governing law, prejudice, likely respondent arguments, and missing record facts that could change the assessment.

In the final answer, use normal legal prose for case names, statutes, rules, and citations. Reserve backticks for CLI commands, file paths, and other literal technical text.

End with a rating line exactly in this form:
Rating: Strong, Medium, Weak, or Frivolous"""

DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Subsequent Treatment Agent.

Analyze how subsequent published California cases treated the currently viewed case. Use Open Law Lens CLI commands for CourtListener-backed discovery and extraction, but use judgment about which commands and searches will best answer the treatment question.

Target case: {target_title}
Target official citation: {target_citation}
CourtListener cluster id: {cluster_id}

Start with this Open Law Lens citing-cases command when the cluster id is accepted:
{published_citing_cases_command}

If that command fails, returns no useful leads, or the cluster id appears to be a local external id, recover with targeted Open Law Lens case searches using the target case name, official citation, and distinctive citation phrases. Treat search results as leads only.

Choose only the most significant published subsequent cases, usually 3 to 5 when that many exist. Before relying on any selected case, extract it with:
uv run --no-sync open-law-lens extract-case --cluster-id <cluster_id>

If CourtListener extraction lacks an official reporter citation or official text for a selected subsequent case, use Google Scholar, California Courts, or Codex web search only as a fallback to verify or fill in that citation/text. State when a citation remains uncertain.

For each selected subsequent case, explain how it used the target case: agreed with it, distinguished it, limited it, extended it to a different fact pattern, criticized it, or used it in another identifiable way. If a citation lead exists but extracted or verified text does not support a treatment characterization, say that plainly.

Prefer California Supreme Court and published California Court of Appeal decisions. Do not use unpublished cases as controlling treatment. Keep the answer concise and include the official citation for each later case. In the final answer, use normal legal prose for case names and citations; reserve backticks for CLI commands, file paths, and other literal technical text."""


@dataclass(frozen=True)
class AppConfig:
    courtlistener_token: str = ""
    concordance_file_path: str = ""
    general_agent_prompt_template: str = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt_template: str = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
    brief_agent_prompt_template: str = DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
    appeal_issue_agent_prompt_template: str = DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
    later_treatment_agent_prompt_template: str = DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
    general_agent_xhigh_reasoning: bool = False
    case_agent_xhigh_reasoning: bool = False
    brief_agent_xhigh_reasoning: bool = False
    appeal_issue_xhigh_reasoning: bool = False
    later_treatment_xhigh_reasoning: bool = False
    appeal_issue_presets: list[str] = field(
        default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_PRESETS)
    )
    appeal_issue_labels: list[str] = field(
        default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_LABELS)
    )
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


def normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def normalize_appeal_issue_presets(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(DEFAULT_APPEAL_ISSUE_PRESETS)
    presets: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
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
    if (
        value is None
        and presets_are_defaults
    ):
        return list(DEFAULT_APPEAL_ISSUE_LABELS)
    raw_labels = value if isinstance(value, list) else []
    labels = [str(item or "").strip() for item in raw_labels[: len(presets)]]
    labels.extend([""] * (len(presets) - len(labels)))
    return labels


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
    if prompt_hash in LEGACY_GENERAL_AGENT_PROMPT_SHA256ES:
        general_agent_prompt = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt = raw.get(
        CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE,
        DEFAULT_CASE_AGENT_PROMPT_TEMPLATE,
    )
    case_prompt_hash = hashlib.sha256(str(case_agent_prompt).strip().encode()).hexdigest()
    if (
        case_prompt_hash in LEGACY_CASE_AGENT_PROMPT_SHA256ES
        or "current-case factual context exported into this workspace."
        in str(case_agent_prompt)
    ):
        case_agent_prompt = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
    brief_agent_prompt = raw.get(
        CONFIG_KEY_BRIEF_AGENT_PROMPT_TEMPLATE,
        DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE,
    )
    if (
        "Open Law Lens Prior Brief Agent" in str(brief_agent_prompt)
        and "direct quotes of only two to five words" in str(brief_agent_prompt)
    ):
        brief_agent_prompt = DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
    appeal_issue_agent_prompt = raw.get(
        CONFIG_KEY_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
        DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE,
    )
    later_treatment_agent_prompt = raw.get(
        CONFIG_KEY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
        raw.get(
            CONFIG_KEY_LEGACY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
            DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE,
        ),
    )
    appeal_prompt_hash = hashlib.sha256(
        str(appeal_issue_agent_prompt).strip().encode()
    ).hexdigest()
    if appeal_prompt_hash in LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES:
        appeal_issue_agent_prompt = DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
    appeal_issue_presets = normalize_appeal_issue_presets(
        raw.get(CONFIG_KEY_APPEAL_ISSUE_PRESETS)
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
        brief_agent_prompt_template=(
            str(brief_agent_prompt).strip() or DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
        ),
        appeal_issue_agent_prompt_template=(
            str(appeal_issue_agent_prompt).strip()
            or DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
        ),
        later_treatment_agent_prompt_template=(
            str(later_treatment_agent_prompt).strip()
            or DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
        ),
        general_agent_xhigh_reasoning=normalize_bool(
            raw.get(CONFIG_KEY_GENERAL_AGENT_XHIGH_REASONING),
            False,
        ),
        case_agent_xhigh_reasoning=normalize_bool(
            raw.get(CONFIG_KEY_CASE_AGENT_XHIGH_REASONING),
            False,
        ),
        brief_agent_xhigh_reasoning=normalize_bool(
            raw.get(CONFIG_KEY_BRIEF_AGENT_XHIGH_REASONING),
            False,
        ),
        appeal_issue_xhigh_reasoning=normalize_bool(
            raw.get(CONFIG_KEY_APPEAL_ISSUE_XHIGH_REASONING),
            False,
        ),
        later_treatment_xhigh_reasoning=normalize_bool(
            raw.get(CONFIG_KEY_LATER_TREATMENT_XHIGH_REASONING),
            False,
        ),
        appeal_issue_presets=appeal_issue_presets,
        appeal_issue_labels=normalize_appeal_issue_labels(
            raw.get(CONFIG_KEY_APPEAL_ISSUE_LABELS),
            appeal_issue_presets,
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
        CONFIG_KEY_GENERAL_AGENT_PROMPT_TEMPLATE: (
            config.general_agent_prompt_template.strip() or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE: (
            config.case_agent_prompt_template.strip() or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_BRIEF_AGENT_PROMPT_TEMPLATE: (
            config.brief_agent_prompt_template.strip() or DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE: (
            config.appeal_issue_agent_prompt_template.strip()
            or DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE: (
            config.later_treatment_agent_prompt_template.strip()
            or DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_GENERAL_AGENT_XHIGH_REASONING: bool(config.general_agent_xhigh_reasoning),
        CONFIG_KEY_CASE_AGENT_XHIGH_REASONING: bool(config.case_agent_xhigh_reasoning),
        CONFIG_KEY_BRIEF_AGENT_XHIGH_REASONING: bool(config.brief_agent_xhigh_reasoning),
        CONFIG_KEY_APPEAL_ISSUE_XHIGH_REASONING: bool(config.appeal_issue_xhigh_reasoning),
        CONFIG_KEY_LATER_TREATMENT_XHIGH_REASONING: bool(config.later_treatment_xhigh_reasoning),
        CONFIG_KEY_APPEAL_ISSUE_PRESETS: appeal_issue_presets,
        CONFIG_KEY_APPEAL_ISSUE_LABELS: normalize_appeal_issue_labels(
            appeal_issue_labels,
            appeal_issue_presets,
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
