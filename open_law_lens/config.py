from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_commands import AGENT_CLI_COMMAND_PREFIX, normalize_agent_prompt_commands


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
CONFIG_KEY_APPEAL_ISSUE_PRESETS = "appeal_issue_presets"
CONFIG_KEY_APPEAL_ISSUE_LABELS = "appeal_issue_labels"
CONFIG_KEY_AGENT_RUNTIME_PROFILES = "agent_runtime_profiles"
CONFIG_KEY_READER_FONT_SIZE_PT = "reader_font_size_pt"
CONFIG_KEY_READER_FONT_FAMILY = "reader_font_family"
CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE = "default_bare_statute_law_code"
ENV_CONCORDANCE_FILE = "OPEN_LAW_LENS_CONCORDANCE_FILE"
AGENT_PROFILE_LAW = "law"
AGENT_PROFILE_RESEARCH_CACHE = "research_cache"
AGENT_PROFILE_PRIOR_BRIEFS = "prior_briefs"
AGENT_PROFILE_ASSESS_ARGUMENT = "assess_argument"
AGENT_PROFILE_KEYS: tuple[str, ...] = (
    AGENT_PROFILE_LAW,
    AGENT_PROFILE_RESEARCH_CACHE,
    AGENT_PROFILE_PRIOR_BRIEFS,
    AGENT_PROFILE_ASSESS_ARGUMENT,
)
PI_THINKING_LEVELS: tuple[str, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
DEFAULT_READER_FONT_SIZE_PT = 11
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

LEGACY_GENERAL_AGENT_PROMPT_SHA256ES = (
    "a168fd313f71015a9a730bd2912aba0d1a9e51bfdeb28ecdaed039707e07d92a",
    "50a9928018ec7d3b06b322db9e5a211e56c7a155b09537d1f7057906fb6a14e4",
    "5d787ed00945b45a32f60026679908a718fc7d174080951f5f3bbe5e70921dc6",
    "e8da4e994bce96bd6acc337c1361fa225adf62a6cc5f5044ff42ed17c1d14aec",
    # Historical default that retained case-search/extract-case workflow text.
    "34f68d9555ec52349ee41209d9e3a85359b1b71613a141df01c1caef9156ac59",
    # Prompt as stored on disk before the workflow text moved into the skill.
    "0d41e7db6fdb921685d704da391bbe8b2341118fae09f3a96e4534eba07210f0",
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
    "395b6ae8e9fb01913bc839e5715e0c499c9714708561beba9841ea3487dbb1ce",
    "b57fb338bb6148eaa4937be89de687884b1f42f2ef2d966d9d4a21cb3816d338",
    "89f0c0d29553434588a1060de8d979d91c9a15ca27b214ee16ff3498209b6089",
    "825b58f274b81af60c7fdd0fb2a55e9a6ad43c8bbd31f6d51f0c632d2c7a5599",
    "cc5c2ba125d0ee0ff42d65db1b58f0d9e7fc281ad1a12d3693f82caca551af24",
    "148e132f9bf9440d84437f2116cb2f2bcc7bbc4654d1508d2644ea8a9dbb3614",
    "5efdaaf4380c89a75ed1073d8a6476511cd59d58c54837e6d741f8dfa386e8a2",
    # Retained case-search-first research paragraph before the skill's route
    # gate was aligned into the Appeal prompt.
    "6e12830dcbf441e0a75670284678eeeebe193d27e33574eeed87f01a1af461bb",
    # Default that still referred to the removed Tavily/direct-HTTP Scholar
    # official-copy cascade.
    "cb07bcae20bd7e440cf1bb061f2abba0fa8b7a58fe008d1c7edc17739a78b2ab",
    # Immediately preceding tracked default, framed as advocacy with a
    # Strong/Medium/Weak/Frivolous rating line.
    "a6826775cff0c970339ba4153aa1cf72f15904b9047032f3beee7f3ecd2adec8",
    # Older stored local prompt with generic Scholar/web-search guidance and an
    # argument-strength rating, predating the routed research workflow.
    "dee4354a0630d199daf29e40ead8fb1d3dc44feb4ae248309b4adfc3b9bddc3b",
)
LEGACY_LATER_TREATMENT_AGENT_PROMPT_SHA256ES = (
    "e73fc8abadd94b2affb966c126dfb0c2416e0fc86c1994baa486b01deb5d1834",
    "53b08107f87f27b6cd70b895eef4d43522ca311e4c2f40f47aa6cd92b640469e",
    # Immediately preceding tracked default, with judgment-based case-search
    # recovery and an unconditional official-citation requirement.
    "f159d1a8fbe1f02f3ece3e82d0a4f7f49770f1a58f3a29929c8846176104af08",
    # Older stored local prompt that explicitly allowed Scholar, California
    # Courts, and Codex web search as official-copy/citation fallbacks.
    "b43665a83f9b32a9cca092b06ddd7aa8b00d4dabf3a510d0d6a834b7afca1a00",
)

DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens General California Law Agent.

Answer only legal questions about California law. Confine research to California state law unless the user's question explicitly requires federal law.

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
`$OLL search-briefs "<terms>" --match all`
Try related wording, phrase, and any-term searches when the first search is incomplete. Use `--sort newest` when recency matters. Read a candidate with:
`$OLL extract-brief <brief_id>`

Identify every discussed source with the exact Markdown link returned by search, in this form: `[Exact indexed title](open-law-lens://prior-brief/<brief_id>)`. Put that linked title close to the discussion and any quote from that brief. Include useful direct quotes of only two to ten words, copied as exact continuous phrases. If the archive does not answer the question, say so plainly.

Distinguish opening briefs, reply briefs, respondent's briefs, oppositions, Phoenix H. memos, and other documents. For a request for the most recent document, use the indexed document date and explain when it is a file-date fallback.

Question:
{question}

Prior brief database snapshot:
{brief_database}

Indexed brief count: {brief_count}""".replace("$OLL", AGENT_CLI_COMMAND_PREFIX)

DEFAULT_APPEAL_ISSUE_PRESETS: tuple[str, ...] = (
    "Did substantial evidence support the challenged finding?",
    "Did the trial court abuse its discretion in making the challenged order?",
    "Did the trial court apply the correct legal standard?",
    "Did the proceedings afford the appellant due process, including adequate notice and a meaningful opportunity to be heard?",
    "If error occurred, was it prejudicial under the applicable appellate standard?",
)

# Exact legacy preset statements that upgrade to the neutral legal-question
# wording. Matching is per entry and exact, so genuine custom entries are
# preserved and list order and labels are untouched.
LEGACY_APPEAL_ISSUE_PRESET_REPLACEMENTS: dict[str, str] = {
    # Generic tracked defaults through this release.
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
    # Dependency-specific local presets with embedded outcome-anchoring case
    # citations removed; statutory references stay to define the question.
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
    "Substantial evidence",
    "Abuse of discretion",
    "Wrong legal standard",
    "Due process",
    "Prejudice",
)

DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Legal Question Assessment Agent.

Prepare an objective California appellate assessment of the legal question below, in the manner of a bench memorandum written for an appellate court deciding that question. You are not an advocate for any party. Do not presume an answer from the wording of the question, and do not treat the question's phrasing as indicating the outcome.

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

Treat the supplied fact pattern as the complete factual record for this assessment. Base the factual analysis only on facts it contains. Do not speculate that unprovided facts or a more complete record could alter the assessment, and do not add a generic record-completeness caveat. If the supplied text is internally ambiguous, contradictory, or lacks a usable record citation, identify that specific issue only where it affects the analysis.

Legal question to decide:
{issue}

Research current California law by following the Legal Researcher workflow preloaded into this workspace, including its command routing, authority-verification rules, and official-copy recovery. Do not restate or duplicate that workflow here. Disclose any concrete verification gap rather than inventing support, and lower confidence accordingly when a material gap remains.

If the question embeds an issue-specific focus or instruction, address it expressly. For example, when a Cal-ICWA inquiry question asks about the significance of no one claiming ancestry with a particular tribe, analyze that point directly rather than answering the inquiry question only in general.

Write the assessment as a concise bench memorandum. After the system-required title and subtitle, structure the answer with these sections:
- Question Presented
- Short Answer
- Governing Law/Standard of Review
- Analysis
- Conclusion

Apply the law neutrally to the supplied facts, and address the strongest material reasoning supporting each possible answer, including the reasoning that does not favor the premise implicit in the question. Address preservation, prejudice, harmless error, and remedy where they are legally material to the question, not as a mechanical checklist.

Answer the question directly, even when the answer is adverse to the position a party might have advanced. If a binary answer is not supportable on the law and record, state the best available disposition and the material uncertainty that prevents a binary answer.

In the final answer, use normal legal prose for case names, statutes, rules, and citations.

End the answer with these two lines exactly in this form:
Conclusion: <direct answer to the legal question>
Confidence: <High, Medium, or Low> — <brief basis tied to the law and record>

Calibrate Confidence to the stated conclusion only; it is not argument strength, a party's likelihood of success, or generic model certainty. High: controlling law and the material record strongly point in the same direction, with no meaningful unresolved conflict. Medium: one conclusion is better supported, but a substantial counterargument, factual ambiguity, or authority tension remains. Low: the issue is close or unsettled, or a material source or record ambiguity prevents a firm conclusion."""

DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE = """You are the Open Law Lens Subsequent Treatment Agent.

Analyze how subsequent published California cases treated the currently viewed case. Discovery and extraction are hard-bounded: follow the fixed workflow below exactly and stop where it says to stop. Use only the Open Law Lens commands supplied in this prompt. Never use generic web search, Pi `web_search`, Google Scholar, California Courts pages, or alternate opinion sites, and never manually call `extract-slip-opinion` or `lookup-citation`, to discover later cases or to obtain pagination, reporter metadata, links, or official copies. Never orchestrate Scholar or any browser step yourself.

Target case: {target_title}
Target official citation: {target_citation}
CourtListener cluster id: {cluster_id}

Discovery limits:
1. Run this citing-cases command exactly once:
{published_citing_cases_command}

2. If that command fails, returns no useful leads, or the cluster id is a local external id, run at most these two non-paginated CourtListener searches and no others. First, one exact official-citation phrase search:
{citation_search_command}

3. Only if still needed, one exact case-name search:
{case_name_search_command}

Do not retry network timeouts, paginate with `--next`, broaden or rewrite queries, use semantic search, or invoke any web search. The only permitted retry is the single retry of one command that fails with a transient SQLite `database is locked` error. If bounded discovery still yields no usable leads, stop and report that subsequent-treatment coverage is limited or unavailable; do not continue searching.

Treat search results as leads only. Select the most significant published subsequent California cases. Three to five cases is a ceiling and a preference, not a quota: use fewer when only fewer can be verified, and disclose incomplete CourtListener coverage in the final answer. Never use unpublished cases as controlling treatment.

Extraction for the selected cases:
- Issue compact baseline extractions for independent selected cases in parallel in the same tool round:
{compact_extract_command}

- Inspect `official_pagination`, `source_url`, and `warnings` in each result.
- For each selected case that still lacks official pagination, make exactly one sequential recovery-enabled extraction, letting Open Law Lens perform its internal baseline and single Scholar attempt:
{recover_official_extract_command}

- If compact passages are inadequate for a relied-on case, you may perform one ordinary full extraction for it:
{full_extract_command}
Never run a second recovery attempt for the same case.

Citation, fallback, and disclosure rules:
- Rely on the best citation returned by the bounded sources; do not delay the answer to hunt for an official reporter citation they did not return. State plainly when a citation remains uncertain.
- If a recovery returns no qualifying copy, is blocked, times out, or fails validation, immediately rely on the best unpaginated baseline Open Law Lens returned, disclose the missing official pagination, and link the case name or citation to the `source_url` that extraction returned. When no source URL was returned, say so; do not search elsewhere for one.

For each selected subsequent case, explain how it used the target case: agreed with it, distinguished it, limited it, extended it to a different fact pattern, criticized it, or used it in another identifiable way. Omit any treatment characterization the extracted text does not support rather than inferring one. If a citation lead exists but no bounded source produced verifiable text, omit that case and disclose the gap. Keep the answer concise. In the final answer, use normal legal prose for case names and citations; reserve backticks for CLI commands, file paths, and other literal technical text."""


@dataclass(frozen=True, slots=True)
class PiAgentProfile:
    provider: str
    model: str
    thinking: str


@dataclass(frozen=True)
class AppConfig:
    courtlistener_token: str = ""
    concordance_file_path: str = ""
    general_agent_prompt_template: str = DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
    case_agent_prompt_template: str = DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
    brief_agent_prompt_template: str = DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
    appeal_issue_agent_prompt_template: str = DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
    later_treatment_agent_prompt_template: str = DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
    appeal_issue_presets: list[str] = field(
        default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_PRESETS)
    )
    appeal_issue_labels: list[str] = field(
        default_factory=lambda: list(DEFAULT_APPEAL_ISSUE_LABELS)
    )
    agent_runtime_profiles: dict[str, PiAgentProfile] = field(default_factory=dict)
    reader_font_size_pt: int = DEFAULT_READER_FONT_SIZE_PT
    reader_font_family: str = DEFAULT_READER_FONT_FAMILY
    default_bare_statute_law_code: str = DEFAULT_BARE_STATUTE_LAW_CODE


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
    if (
        value is None
        and presets_are_defaults
    ):
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
            profiles[key] = PiAgentProfile(
                provider=provider,
                model=model,
                thinking=thinking,
            )
    return profiles


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
    later_treatment_prompt_hash = hashlib.sha256(
        str(later_treatment_agent_prompt).strip().encode()
    ).hexdigest()
    if later_treatment_prompt_hash in LEGACY_LATER_TREATMENT_AGENT_PROMPT_SHA256ES:
        later_treatment_agent_prompt = DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
    appeal_prompt_hash = hashlib.sha256(
        str(appeal_issue_agent_prompt).strip().encode()
    ).hexdigest()
    if (
        appeal_prompt_hash in LEGACY_APPEAL_ISSUE_AGENT_PROMPT_SHA256ES
        or (
            "Open Law Lens Appeal Issue Assessment Agent" in str(appeal_issue_agent_prompt)
            and "missing record facts that could change the assessment" in str(appeal_issue_agent_prompt)
        )
    ):
        appeal_issue_agent_prompt = DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
    appeal_issue_presets = normalize_appeal_issue_presets(
        raw.get(CONFIG_KEY_APPEAL_ISSUE_PRESETS)
    )
    return AppConfig(
        courtlistener_token=str(token).strip(),
        concordance_file_path=str(concordance_path).strip(),
        general_agent_prompt_template=(
            normalize_agent_prompt_commands(str(general_agent_prompt).strip())
            or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
        ),
        case_agent_prompt_template=(
            normalize_agent_prompt_commands(str(case_agent_prompt).strip())
            or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
        ),
        brief_agent_prompt_template=(
            normalize_agent_prompt_commands(str(brief_agent_prompt).strip())
            or DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
        ),
        appeal_issue_agent_prompt_template=(
            normalize_agent_prompt_commands(str(appeal_issue_agent_prompt).strip())
            or DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
        ),
        later_treatment_agent_prompt_template=(
            normalize_agent_prompt_commands(str(later_treatment_agent_prompt).strip())
            or DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
        ),
        appeal_issue_presets=appeal_issue_presets,
        appeal_issue_labels=normalize_appeal_issue_labels(
            raw.get(CONFIG_KEY_APPEAL_ISSUE_LABELS),
            appeal_issue_presets,
        ),
        agent_runtime_profiles=normalize_agent_runtime_profiles(
            raw.get(CONFIG_KEY_AGENT_RUNTIME_PROFILES)
        ),
        reader_font_size_pt=coerce_reader_font_size(raw.get(CONFIG_KEY_READER_FONT_SIZE_PT)),
        reader_font_family=normalize_reader_font_family(raw.get(CONFIG_KEY_READER_FONT_FAMILY)),
        default_bare_statute_law_code=normalize_bare_statute_law_code(
            raw.get(CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE)
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
            normalize_agent_prompt_commands(config.general_agent_prompt_template.strip())
            or DEFAULT_GENERAL_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_CASE_AGENT_PROMPT_TEMPLATE: (
            normalize_agent_prompt_commands(config.case_agent_prompt_template.strip())
            or DEFAULT_CASE_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_BRIEF_AGENT_PROMPT_TEMPLATE: (
            normalize_agent_prompt_commands(config.brief_agent_prompt_template.strip())
            or DEFAULT_BRIEF_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE: (
            normalize_agent_prompt_commands(
                config.appeal_issue_agent_prompt_template.strip()
            )
            or DEFAULT_APPEAL_ISSUE_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE: (
            normalize_agent_prompt_commands(
                config.later_treatment_agent_prompt_template.strip()
            )
            or DEFAULT_LATER_TREATMENT_AGENT_PROMPT_TEMPLATE
        ),
        CONFIG_KEY_APPEAL_ISSUE_PRESETS: appeal_issue_presets,
        CONFIG_KEY_APPEAL_ISSUE_LABELS: normalize_appeal_issue_labels(
            appeal_issue_labels,
            appeal_issue_presets,
        ),
        CONFIG_KEY_AGENT_RUNTIME_PROFILES: {
            key: {
                "provider": profile.provider,
                "model": profile.model,
                "thinking": profile.thinking,
            }
            for key, profile in config.agent_runtime_profiles.items()
            if key in AGENT_PROFILE_KEYS
            and profile.provider.strip()
            and profile.model.strip()
            and profile.thinking in PI_THINKING_LEVELS
        },
        CONFIG_KEY_READER_FONT_SIZE_PT: coerce_reader_font_size(config.reader_font_size_pt),
        CONFIG_KEY_READER_FONT_FAMILY: normalize_reader_font_family(config.reader_font_family),
        CONFIG_KEY_DEFAULT_BARE_STATUTE_LAW_CODE: normalize_bare_statute_law_code(
            config.default_bare_statute_law_code
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
