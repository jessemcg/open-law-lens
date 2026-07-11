from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import cluster_id_from_cluster, normalize_citation
from .citation_links import cited_case_links
from .client import cluster_citation_line, cluster_title
from .rules import cited_rule_links, parse_rule_citation
from .statutes import cited_statute_links, parse_statute_citation


CODEX_SESSION_LOG_GLOB = "20*/**/rollout-*.jsonl"
QUOTE_RE = re.compile(r'"([^"\n]{1,160})"|“([^”\n]{1,160})”')
REPORTER_PAGE_MARKER_RE = re.compile(r"\[\*\d+\]")


@dataclass(frozen=True)
class QuoteTarget:
    phrase: str
    cluster_id: str
    opinion_id: str
    title: str
    citation: str
    text_path: str
    offset: int
    end_offset: int
    authority_type: str = "case"
    statute_id: str = ""
    rule_id: str = ""
    prior_brief_id: str = ""


@dataclass(frozen=True)
class CaseTextSource:
    cluster_id: str
    opinion_id: str
    title: str
    citation: str
    text_path: str
    text: str
    authority_type: str = "case"
    statute_id: str = ""
    rule_id: str = ""
    agent_answer_id: str = ""
    prior_brief_id: str = ""


@dataclass(frozen=True)
class AgentQuoteSpan:
    start_offset: int
    end_offset: int
    phrase: str
    target: QuoteTarget | None = None


@dataclass(frozen=True)
class _CitationHint:
    start_offset: int
    end_offset: int
    authority_key: tuple[str, str]


@dataclass(frozen=True)
class CaseExport:
    manifest_path: Path
    case_dir: Path
    case_count: int
    text_sources: list[CaseTextSource]
    statute_count: int = 0
    rule_count: int = 0
    agent_answer_count: int = 0
    prior_brief_count: int = 0

    @property
    def authority_count(self) -> int:
        return (
            self.case_count
            + self.statute_count
            + self.rule_count
            + self.agent_answer_count
            + self.prior_brief_count
        )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _codex_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def extract_latest_codex_final_answer_from_jsonl(path: Path) -> str:
    latest = ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("type") == "event_msg":
            event = payload.get("payload")
            if isinstance(event, dict) and event.get("type") == "task_complete":
                text = event.get("last_agent_message")
                if isinstance(text, str) and text.strip():
                    latest = text.strip()
            continue
        if not isinstance(payload, dict) or payload.get("type") != "response_item":
            continue
        item = payload.get("payload")
        if not isinstance(item, dict):
            continue
        if (
            item.get("type") != "message"
            or item.get("role") != "assistant"
            or item.get("phase") != "final_answer"
        ):
            continue
        text = _codex_text_from_content(item.get("content"))
        if text:
            latest = text
    return latest


def codex_session_log_matches_cwd(path: Path, cwd: Path) -> bool:
    wanted = str(cwd)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict) or payload.get("type") != "session_meta":
                    continue
                meta = payload.get("payload")
                return isinstance(meta, dict) and meta.get("cwd") == wanted
    except OSError:
        return False
    return False


def find_latest_codex_session_log_for_cwd(sessions_root: Path, cwd: Path) -> Path | None:
    if not sessions_root.is_dir():
        return None
    try:
        candidates = sorted(
            sessions_root.glob(CODEX_SESSION_LOG_GLOB),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in candidates:
        if candidate.is_file() and codex_session_log_matches_cwd(candidate, cwd):
            return candidate
    return None


def extract_quoted_phrases(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in QUOTE_RE.finditer(text):
        phrase = (match.group(1) or match.group(2) or "").strip()
        if not phrase:
            continue
        word_count = len(re.findall(r"\b[\w'-]+\b", phrase))
        if 2 <= word_count <= 10:
            group_index = 1 if match.group(1) is not None else 2
            spans.append((match.start(group_index), match.end(group_index), phrase))
    return spans


def quote_match_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    """Find a direct quote while tolerating display-only punctuation differences."""
    phrase = phrase.rstrip(" \t\r\n.,;:!?")
    canonical_phrase, _ = _canonical_quote_text(phrase)
    if not canonical_phrase:
        return []
    canonical_text, text_offsets = _canonical_quote_text(text)
    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        index = canonical_text.find(canonical_phrase, cursor)
        if index < 0:
            break
        end_index = index + len(canonical_phrase)
        if _canonical_match_has_word_boundaries(canonical_text, index, end_index):
            spans.append((text_offsets[index][0], text_offsets[end_index - 1][1]))
        cursor = index + 1
    return spans


def resolve_quote_target(
    phrase: str,
    sources: list[CaseTextSource],
    *,
    preferred_authority_key: tuple[str, str] | None = None,
) -> QuoteTarget | None:
    if not phrase:
        return None
    matches: dict[tuple[str, str], list[tuple[CaseTextSource, int, int]]] = {}
    for source in sources:
        authority_key = _source_authority_key(source)
        if authority_key is None:
            continue
        source_spans = quote_match_spans(source.text, phrase)
        if source_spans:
            matches.setdefault(authority_key, []).extend(
                (source, start, end) for start, end in source_spans
            )
    selected_key: tuple[str, str] | None = None
    if preferred_authority_key in matches:
        selected_key = preferred_authority_key
    elif len(matches) == 1:
        selected_key = next(iter(matches))
    if selected_key is None:
        return None
    source, start, end = matches[selected_key][0]
    return QuoteTarget(
        phrase=phrase,
        cluster_id=source.cluster_id,
        opinion_id=source.opinion_id,
        title=source.title,
        citation=source.citation,
        text_path=source.text_path,
        offset=start,
        end_offset=end,
        authority_type=source.authority_type,
        statute_id=source.statute_id,
        rule_id=source.rule_id,
        prior_brief_id=source.prior_brief_id,
    )


def resolved_agent_quote_spans(
    text: str,
    sources: list[CaseTextSource],
) -> list[AgentQuoteSpan]:
    hints = _authority_citation_hints(text, sources)
    spans: list[AgentQuoteSpan] = []
    for start, end, phrase in extract_quoted_phrases(text):
        preferred_key = _preferred_quote_authority_key(text, start, end, hints)
        spans.append(
            AgentQuoteSpan(
                start_offset=start,
                end_offset=end,
                phrase=phrase,
                target=resolve_quote_target(
                    phrase,
                    sources,
                    preferred_authority_key=preferred_key,
                ),
            )
        )
    return spans


def _canonical_quote_text(text: str) -> tuple[str, list[tuple[int, int]]]:
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        marker = REPORTER_PAGE_MARKER_RE.match(text, index)
        if marker is not None:
            index = marker.end()
            continue
        raw_char = text[index]
        if raw_char in {'"', "\u201c", "\u201d"}:
            index += 1
            continue
        normalized = unicodedata.normalize("NFKC", raw_char)
        normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")
        if normalized.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append((index, index + 1))
            elif chars and offsets:
                offsets[-1] = (offsets[-1][0], index + 1)
            index += 1
            continue
        for char in normalized.casefold():
            chars.append(char)
            offsets.append((index, index + 1))
        index += 1
    while chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()
    return "".join(chars), offsets


def _canonical_match_has_word_boundaries(text: str, start: int, end: int) -> bool:
    if start > 0 and text[start].isalnum() and text[start - 1].isalnum():
        return False
    if end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        return False
    return True


def _source_authority_key(source: CaseTextSource) -> tuple[str, str] | None:
    if source.authority_type == "case" and source.cluster_id:
        return ("case", source.cluster_id)
    if source.authority_type == "statute" and source.statute_id:
        return ("statute", source.statute_id)
    if source.authority_type == "rule" and source.rule_id:
        return ("rule", source.rule_id)
    if source.authority_type == "prior_brief" and source.prior_brief_id:
        return ("prior_brief", source.prior_brief_id)
    return None


def _case_citation_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_citation(value).casefold())


def _authority_citation_hints(
    text: str,
    sources: list[CaseTextSource],
) -> list[_CitationHint]:
    case_keys: dict[str, set[tuple[str, str]]] = {}
    statute_keys: dict[str, set[tuple[str, str]]] = {}
    rule_keys: dict[str, set[tuple[str, str]]] = {}
    for source in sources:
        authority_key = _source_authority_key(source)
        if authority_key is None:
            continue
        if source.authority_type == "case":
            key = _case_citation_key(source.citation)
            if key:
                case_keys.setdefault(key, set()).add(authority_key)
        elif source.authority_type == "statute":
            statute_keys.setdefault(source.statute_id, set()).add(authority_key)
        elif source.authority_type == "rule":
            rule_keys.setdefault(source.rule_id, set()).add(authority_key)

    prior_brief_keys = {
        source.prior_brief_id: ("prior_brief", source.prior_brief_id)
        for source in sources
        if source.authority_type == "prior_brief" and source.prior_brief_id
    }

    hints: list[_CitationHint] = []
    for link in cited_case_links(text):
        keys = case_keys.get(_case_citation_key(link.lookup_text), set())
        if len(keys) == 1:
            hints.append(_CitationHint(link.start_offset, link.end_offset, next(iter(keys))))
    for link in cited_statute_links(text):
        citation = parse_statute_citation(link.lookup_text)
        keys = statute_keys.get(citation.statute_id, set()) if citation is not None else set()
        if len(keys) == 1:
            hints.append(_CitationHint(link.start_offset, link.end_offset, next(iter(keys))))
    for link in cited_rule_links(text):
        citation = parse_rule_citation(link.lookup_text)
        keys = rule_keys.get(citation.rule_id, set()) if citation is not None else set()
        if len(keys) == 1:
            hints.append(_CitationHint(link.start_offset, link.end_offset, next(iter(keys))))
    for match in re.finditer(
        r"\[[^\]\n]+\]\(open-law-lens://prior-brief/([a-fA-F0-9]{16,64})\)",
        text,
    ):
        key = prior_brief_keys.get(match.group(1))
        if key is not None:
            hints.append(_CitationHint(match.start(), match.end(), key))
    for source in sources:
        if source.authority_type != "prior_brief" or not source.prior_brief_id:
            continue
        for match in re.finditer(re.escape(source.title), text, flags=re.IGNORECASE):
            hints.append(
                _CitationHint(
                    match.start(),
                    match.end(),
                    ("prior_brief", source.prior_brief_id),
                )
            )
    return sorted(hints, key=lambda hint: hint.start_offset)


def _preferred_quote_authority_key(
    text: str,
    quote_start: int,
    quote_end: int,
    hints: list[_CitationHint],
) -> tuple[str, str] | None:
    paragraph_start = text.rfind("\n\n", 0, quote_start) + 2
    paragraph_end = text.find("\n\n", quote_end)
    if paragraph_end < 0:
        paragraph_end = len(text)
    same_paragraph = [
        hint
        for hint in hints
        if hint.start_offset >= paragraph_start and hint.end_offset <= paragraph_end
    ]
    following = [hint for hint in same_paragraph if hint.start_offset >= quote_end]
    if following:
        return min(following, key=lambda hint: hint.start_offset).authority_key
    preceding = [hint for hint in same_paragraph if hint.end_offset <= quote_start]
    if preceding:
        return max(preceding, key=lambda hint: hint.end_offset).authority_key
    nearby_prior_briefs = [
        hint
        for hint in hints
        if hint.authority_key[0] == "prior_brief"
        and (
            0 <= quote_start - hint.end_offset <= 600
            or 0 <= hint.start_offset - quote_end <= 300
        )
    ]
    nearby_preceding = [
        hint for hint in nearby_prior_briefs if hint.end_offset <= quote_start
    ]
    if nearby_preceding:
        return max(nearby_preceding, key=lambda hint: hint.end_offset).authority_key
    if nearby_prior_briefs:
        return min(nearby_prior_briefs, key=lambda hint: hint.start_offset).authority_key
    return None


def export_selected_cases(
    client: Any,
    clusters: list[dict[str, Any]],
    case_dir: Path,
) -> CaseExport:
    return export_selected_authorities(client, clusters, [], [], case_dir)


def export_selected_authorities(
    client: Any,
    clusters: list[dict[str, Any]],
    statutes: list[dict[str, Any]],
    rules: list[dict[str, Any]] | None,
    case_dir: Path,
    agent_answers: list[dict[str, Any]] | None = None,
    prior_briefs: list[dict[str, Any]] | None = None,
) -> CaseExport:
    case_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases: list[dict[str, Any]] = []
    manifest_statutes: list[dict[str, Any]] = []
    manifest_rules: list[dict[str, Any]] = []
    manifest_agent_answers: list[dict[str, Any]] = []
    manifest_prior_briefs: list[dict[str, Any]] = []
    text_sources: list[CaseTextSource] = []
    rules = rules or []
    agent_answers = agent_answers or []
    prior_briefs = prior_briefs or []

    for cluster in clusters:
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            continue
        title = cluster_title(cluster)
        citation = cluster_citation_line(cluster)
        opinions = client.reader_opinions(client.fetch_cluster_opinions(cluster))
        opinion_entries: list[dict[str, Any]] = []
        for opinion in opinions:
            opinion_id = str(opinion.get("id") or "").strip()
            if not opinion_id:
                continue
            display = client.opinion_display(opinion)
            if not display.text:
                continue
            filename = f"cluster_{cluster_id}_opinion_{opinion_id}.txt"
            text_path = case_dir / filename
            header = (
                f"Title: {title}\n"
                f"Citation: {citation}\n"
                f"Cluster ID: {cluster_id}\n"
                f"Opinion ID: {opinion_id}\n"
                f"Source field: {display.source_field}\n\n"
            )
            text_path.write_text(header + display.text, encoding="utf-8")
            opinion_entries.append(
                {
                    "opinion_id": opinion_id,
                    "text_path": str(text_path),
                    "source_field": display.source_field,
                }
            )
            text_sources.append(
                CaseTextSource(
                    cluster_id=cluster_id,
                    opinion_id=opinion_id,
                    title=title,
                    citation=citation,
                    text_path=str(text_path),
                    text=display.text,
                )
            )
        if opinion_entries:
            manifest_cases.append(
                {
                    "cluster_id": cluster_id,
                    "title": title,
                    "citation": citation,
                    "opinions": opinion_entries,
                }
            )

    for statute in statutes:
        statute_id = str(statute.get("statute_id") or "").strip()
        title = str(statute.get("title") or "").strip()
        citation = str(statute.get("citation") or "").strip()
        text = str(statute.get("text") or "").strip()
        if not statute_id or not text:
            continue
        filename = f"statute_{re.sub(r'[^A-Za-z0-9_.-]+', '_', statute_id)}.txt"
        text_path = case_dir / filename
        header = (
            f"Title: {title}\n"
            f"Citation: {citation}\n"
            f"Statute ID: {statute_id}\n"
            f"Source URL: {statute.get('source_url') or ''}\n\n"
        )
        text_path.write_text(header + text, encoding="utf-8")
        manifest_statutes.append(
            {
                "statute_id": statute_id,
                "title": title,
                "citation": citation,
                "text_path": str(text_path),
                "source_url": str(statute.get("source_url") or ""),
            }
        )
        text_sources.append(
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title=title,
                citation=citation,
                text_path=str(text_path),
                text=text,
                authority_type="statute",
                statute_id=statute_id,
            )
        )

    for rule in rules:
        rule_id = str(rule.get("rule_id") or "").strip()
        title = str(rule.get("title") or "").strip()
        citation = str(rule.get("citation") or "").strip()
        text = str(rule.get("text") or "").strip()
        if not rule_id or not text:
            continue
        filename = f"rule_{re.sub(r'[^A-Za-z0-9_.-]+', '_', rule_id)}.txt"
        text_path = case_dir / filename
        header = (
            f"Title: {title}\n"
            f"Citation: {citation}\n"
            f"Rule ID: {rule_id}\n"
            f"Source URL: {rule.get('source_url') or ''}\n\n"
        )
        text_path.write_text(header + text, encoding="utf-8")
        manifest_rules.append(
            {
                "rule_id": rule_id,
                "title": title,
                "citation": citation,
                "text_path": str(text_path),
                "source_url": str(rule.get("source_url") or ""),
            }
        )
        text_sources.append(
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title=title,
                citation=citation,
                text_path=str(text_path),
                text=text,
                authority_type="rule",
                rule_id=rule_id,
            )
        )

    for answer in agent_answers:
        answer_id = str(answer.get("answer_id") or "").strip()
        title = str(answer.get("title") or "").strip()
        mode = str(answer.get("mode") or "").strip()
        text = str(answer.get("text") or "").strip()
        if not answer_id or not text:
            continue
        filename = f"agent_answer_{re.sub(r'[^A-Za-z0-9_.-]+', '_', answer_id)}.txt"
        text_path = case_dir / filename
        header = (
            f"Title: {title or 'Saved agent answer'}\n"
            f"Agent answer ID: {answer_id}\n"
            f"Agent mode: {mode}\n"
            f"Saved at: {answer.get('saved_at') or answer.get('added_at') or ''}\n"
            "Source type: saved agent answer, not legal authority\n\n"
        )
        text_path.write_text(header + text, encoding="utf-8")
        manifest_agent_answers.append(
            {
                "answer_id": answer_id,
                "title": title,
                "mode": mode,
                "text_path": str(text_path),
                "saved_at": str(answer.get("saved_at") or answer.get("added_at") or ""),
                "source_type": "saved_agent_answer",
            }
        )
        text_sources.append(
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title=title,
                citation="Saved agent answer",
                text_path=str(text_path),
                text=text,
                authority_type="agent_answer",
                agent_answer_id=answer_id,
            )
        )

    for brief in prior_briefs:
        brief_id = str(brief.get("brief_id") or "").strip()
        title = str(brief.get("title") or "Untitled prior brief").strip()
        text = str(brief.get("text") or "").strip()
        if not brief_id or not text:
            continue
        filename = f"prior_brief_{re.sub(r'[^A-Za-z0-9_.-]+', '_', brief_id)}.txt"
        text_path = case_dir / filename
        header = (
            f"Title: {title}\n"
            f"Prior brief ID: {brief_id}\n"
            f"Document type: {brief.get('document_type') or 'Prior brief'}\n"
            f"Document date: {brief.get('document_date') or ''}\n"
            "Source type: prior advocacy, not legal authority\n\n"
        )
        text_path.write_text(header + text, encoding="utf-8")
        manifest_prior_briefs.append(
            {
                "brief_id": brief_id,
                "title": title,
                "document_type": str(brief.get("document_type") or "Prior brief"),
                "document_date": str(brief.get("document_date") or ""),
                "text_path": str(text_path),
                "source_type": "prior_advocacy",
            }
        )
        text_sources.append(
            CaseTextSource(
                cluster_id="",
                opinion_id="",
                title=title,
                citation=str(brief.get("document_date") or "Prior brief"),
                text_path=str(text_path),
                text=text,
                authority_type="prior_brief",
                prior_brief_id=brief_id,
            )
        )

    manifest = {
        "cases": manifest_cases,
        "statutes": manifest_statutes,
        "rules": manifest_rules,
        "agent_answers": manifest_agent_answers,
        "prior_briefs": manifest_prior_briefs,
        "instructions": (
            "Use only these selected Open Law Lens Research Cache materials. "
            "Quote exact continuous phrases only from selected cases, statutes, rules, and "
            "prior briefs. "
            "Saved agent answers are prior analysis for context, not legal authority or a "
            "source of direct quotations. Prior briefs are prior advocacy, not legal authority; "
            "they may be quoted only when clearly identified as prior briefing."
        ),
    }
    manifest_path = case_dir / "manifest.json"
    manifest_path.write_text(_json_dumps(manifest) + "\n", encoding="utf-8")
    return CaseExport(
        manifest_path=manifest_path,
        case_dir=case_dir,
        case_count=len(manifest_cases),
        statute_count=len(manifest_statutes),
        rule_count=len(manifest_rules),
        agent_answer_count=len(manifest_agent_answers),
        prior_brief_count=len(manifest_prior_briefs),
        text_sources=text_sources,
    )
