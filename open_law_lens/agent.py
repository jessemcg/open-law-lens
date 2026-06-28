from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import cluster_id_from_cluster
from .client import cluster_citation_line, cluster_title


CODEX_SESSION_LOG_GLOB = "20*/**/rollout-*.jsonl"
QUOTE_RE = re.compile(r'"([^"\n]{1,160})"|“([^”\n]{1,160})”')


@dataclass(frozen=True)
class QuoteTarget:
    phrase: str
    cluster_id: str
    opinion_id: str
    title: str
    citation: str
    text_path: str
    offset: int


@dataclass(frozen=True)
class CaseTextSource:
    cluster_id: str
    opinion_id: str
    title: str
    citation: str
    text_path: str
    text: str


@dataclass(frozen=True)
class CaseExport:
    manifest_path: Path
    case_dir: Path
    case_count: int
    text_sources: list[CaseTextSource]


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
        if 2 <= word_count <= 5:
            group_index = 1 if match.group(1) is not None else 2
            spans.append((match.start(group_index), match.end(group_index), phrase))
    return spans


def resolve_quote_target(phrase: str, sources: list[CaseTextSource]) -> QuoteTarget | None:
    if not phrase:
        return None
    for source in sources:
        offset = source.text.find(phrase)
        if offset >= 0:
            return QuoteTarget(
                phrase=phrase,
                cluster_id=source.cluster_id,
                opinion_id=source.opinion_id,
                title=source.title,
                citation=source.citation,
                text_path=source.text_path,
                offset=offset,
            )
    return None


def export_selected_cases(
    client: Any,
    clusters: list[dict[str, Any]],
    case_dir: Path,
) -> CaseExport:
    case_dir.mkdir(parents=True, exist_ok=True)
    manifest_cases: list[dict[str, Any]] = []
    text_sources: list[CaseTextSource] = []

    for cluster in clusters:
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            continue
        title = cluster_title(cluster)
        citation = cluster_citation_line(cluster)
        opinions = client.fetch_cluster_opinions(cluster)
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

    manifest = {
        "cases": manifest_cases,
        "instructions": (
            "Use only these selected Open Law Lens Research Cache cases. "
            "Quote exact continuous phrases from the text files."
        ),
    }
    manifest_path = case_dir / "manifest.json"
    manifest_path.write_text(_json_dumps(manifest) + "\n", encoding="utf-8")
    return CaseExport(
        manifest_path=manifest_path,
        case_dir=case_dir,
        case_count=len(manifest_cases),
        text_sources=text_sources,
    )
