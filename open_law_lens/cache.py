from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .case_titles import cluster_short_title_value
from .citation_model import (
    canonicalize_cluster_citations,
    canonicalize_lookup_result,
    official_citation_from_cluster,
)
from .external_import import repair_reporter_only_imported_cluster
from .reader_highlights import ReaderHighlight
from .storage import (
    cluster_id_from_cluster,
    normalize_citation,
    repair_lookup_result_clusters,
    resource_id_from_url,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_CACHE_DIR = PROJECT_ROOT / "cache"
OPINION_TEXT_FIELDS = (
    "html_with_citations",
    "plain_text",
    "html",
    "html_lawbox",
    "html_columbia",
    "html_anon_2020",
    "xml_harvard",
)


def cache_root() -> Path:
    root = os.environ.get("OPEN_LAW_LENS_CACHE_DIR")
    if root:
        return Path(root).expanduser()
    return PROJECT_CACHE_DIR


def citation_cache_key(citation: str) -> str:
    normalized = normalize_citation(citation).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _cache_sort_timestamp(entry: dict[str, Any]) -> str:
    return str(entry.get("loaded_at") or entry.get("added_at") or "")


def _agent_answer_title(text: str, mode: str) -> str:
    explicit_markers = ("# ", "## ", "### ")
    for line in text.splitlines():
        raw_title = line.strip()
        if not raw_title:
            continue
        is_explicit = raw_title.startswith(explicit_markers)
        title = re.sub(r"^[#>*`\s-]+", "", raw_title).strip()
        title = re.sub(r"^([*_]{1,3})(.+)\1$", r"\2", title).strip()
        title = re.sub(r"[*_`]+$", "", title).strip()
        title = re.sub(r"\s+", " ", title)
        if not title:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", title, maxsplit=1)[0]
        sentence = sentence.rstrip(".:;")
        words = sentence.split()
        max_words = 10 if is_explicit else 6
        short = " ".join(words[:max_words]).strip()
        if short:
            return short[:64].rstrip(" ,;:.")
    label = "Assessment" if mode == "appeal" else "Legal answer"
    return f"Saved {label}"


def _opinion_import_text(opinion: dict[str, Any]) -> str:
    for field in OPINION_TEXT_FIELDS:
        value = opinion.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _synchronized(method: Any) -> Any:
    def wrapper(self: "JsonCache", *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass
class JsonCache:
    root: Path
    _dirty_tracking_suppressed: bool = field(default=False, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @classmethod
    def default(cls) -> "JsonCache":
        return cls(cache_root())

    def ensure(self) -> None:
        for name in (
            "lookups",
            "clusters",
            "opinions",
            "statutes",
            "rules",
            "prior_briefs",
            "agent_answers",
            "slip_opinions",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.repair_reporter_only_imported_case_names()

    def case_index_path(self) -> Path:
        return self.root / "cases_index.json"

    def statute_index_path(self) -> Path:
        return self.root / "statutes_index.json"

    def rule_index_path(self) -> Path:
        return self.root / "rules_index.json"

    def agent_answer_index_path(self) -> Path:
        return self.root / "agent_answers_index.json"

    def prior_brief_index_path(self) -> Path:
        return self.root / "prior_briefs_index.json"

    def metadata_path(self) -> Path:
        return self.root / "metadata.json"

    def reader_positions_path(self) -> Path:
        return self.root / "reader_positions.json"

    def reader_highlights_path(self) -> Path:
        return self.root / "reader_highlights.json"

    def current_case_context_path(self) -> Path:
        return self.root / "current_case_context.json"

    def lookup_path(self, citation: str) -> Path:
        return self.root / "lookups" / f"{citation_cache_key(citation)}.json"

    def resource_path(self, kind: str, resource_id: str) -> Path:
        return self.root / kind / f"{resource_id}.json"

    def cluster_path(self, cluster_id: str) -> Path:
        return self.resource_path("clusters", cluster_id)

    def opinion_path(self, opinion_id: str) -> Path:
        return self.resource_path("opinions", opinion_id)

    def statute_path(self, statute_id: str) -> Path:
        return self.resource_path("statutes", statute_id.replace(":", "_"))

    def rule_path(self, rule_id: str) -> Path:
        return self.resource_path("rules", rule_id.replace(":", "_"))

    def agent_answer_path(self, answer_id: str) -> Path:
        return self.resource_path("agent_answers", answer_id)

    def prior_brief_path(self, brief_id: str) -> Path:
        return self.resource_path("prior_briefs", brief_id)

    def slip_opinion_payload_path(self, case_number: str) -> Path:
        clean_case_number = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(case_number or "").strip().upper())
        return self.root / "slip_opinions" / f"{clean_case_number}.json"

    def read_json(self, path: Path) -> Any | None:
        with self._lock:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                return None

    def write_json(self, path: Path, value: Any) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                temp_path.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)

    def read_metadata(self) -> dict[str, Any]:
        data = self.read_json(self.metadata_path())
        return data if isinstance(data, dict) else {}

    def write_metadata(self, metadata: dict[str, Any]) -> None:
        self.write_json(self.metadata_path(), metadata)

    def read_reader_positions(self) -> dict[str, dict[str, int]]:
        data = self.read_json(self.reader_positions_path())
        raw_positions = data.get("positions") if isinstance(data, dict) else None
        if not isinstance(raw_positions, dict):
            return {}
        positions: dict[str, dict[str, int]] = {}
        for item_type in ("case", "statute", "rule", "prior_brief", "agent_answer", "socf"):
            raw_items = raw_positions.get(item_type)
            if not isinstance(raw_items, dict):
                continue
            clean_items = {
                str(authority_id): offset
                for authority_id, offset in raw_items.items()
                if str(authority_id).strip()
                and isinstance(offset, int)
                and not isinstance(offset, bool)
                and offset >= 0
            }
            if clean_items:
                positions[item_type] = clean_items
        return positions

    def reader_position(self, item_type: str, authority_id: str) -> int | None:
        clean_type = str(item_type or "").strip()
        clean_id = str(authority_id or "").strip()
        if not clean_type or not clean_id:
            return None
        return self.read_reader_positions().get(clean_type, {}).get(clean_id)

    @_synchronized
    def set_reader_position(self, item_type: str, authority_id: str, offset: int) -> None:
        clean_type = str(item_type or "").strip()
        clean_id = str(authority_id or "").strip()
        if clean_type not in {"case", "statute", "rule", "prior_brief", "agent_answer", "socf"} or not clean_id:
            return
        try:
            clean_offset = max(0, int(offset))
        except (TypeError, ValueError):
            return
        positions = self.read_reader_positions()
        if positions.get(clean_type, {}).get(clean_id) == clean_offset:
            return
        positions.setdefault(clean_type, {})[clean_id] = clean_offset
        self.write_json(
            self.reader_positions_path(),
            {"version": 1, "positions": positions},
        )

    @_synchronized
    def remove_reader_position(self, item_type: str, authority_id: str) -> None:
        clean_type = str(item_type or "").strip()
        clean_id = str(authority_id or "").strip()
        positions = self.read_reader_positions()
        items = positions.get(clean_type)
        if not isinstance(items, dict) or clean_id not in items:
            return
        items.pop(clean_id, None)
        if not items:
            positions.pop(clean_type, None)
        if positions:
            self.write_json(
                self.reader_positions_path(),
                {"version": 1, "positions": positions},
            )
        else:
            self.reader_positions_path().unlink(missing_ok=True)

    def selected_current_case_contexts(self) -> set[str]:
        data = self.read_json(self.current_case_context_path())
        raw_names = data.get("selected_case_names") if isinstance(data, dict) else None
        if not isinstance(raw_names, list):
            return set()
        return {
            str(case_name).strip()
            for case_name in raw_names
            if str(case_name).strip()
        }

    def is_current_case_context_selected(self, case_name: str) -> bool:
        clean_name = str(case_name or "").strip()
        return bool(clean_name and clean_name in self.selected_current_case_contexts())

    @_synchronized
    def set_current_case_context_selected(self, case_name: str, selected: bool) -> None:
        clean_name = str(case_name or "").strip()
        if not clean_name:
            return
        selected_names = self.selected_current_case_contexts()
        if selected:
            selected_names.add(clean_name)
        else:
            selected_names.discard(clean_name)
        if not selected_names:
            self.current_case_context_path().unlink(missing_ok=True)
            return
        self.write_json(
            self.current_case_context_path(),
            {
                "version": 1,
                "selected_case_names": sorted(selected_names, key=str.casefold),
            },
        )

    def read_reader_highlights(self) -> dict[str, dict[str, list[ReaderHighlight]]]:
        data = self.read_json(self.reader_highlights_path())
        raw_highlights = data.get("highlights") if isinstance(data, dict) else None
        if not isinstance(raw_highlights, dict):
            return {}
        highlights: dict[str, dict[str, list[ReaderHighlight]]] = {}
        for item_type in ("case", "statute", "rule", "prior_brief"):
            raw_items = raw_highlights.get(item_type)
            if not isinstance(raw_items, dict):
                continue
            clean_items: dict[str, list[ReaderHighlight]] = {}
            for authority_id, raw_entries in raw_items.items():
                clean_id = str(authority_id).strip()
                if not clean_id or not isinstance(raw_entries, list):
                    continue
                entries = [
                    highlight
                    for value in raw_entries
                    if (highlight := ReaderHighlight.from_mapping(value)) is not None
                ]
                if entries:
                    clean_items[clean_id] = entries
            if clean_items:
                highlights[item_type] = clean_items
        return highlights

    def reader_highlights(self, item_type: str, authority_id: str) -> list[ReaderHighlight]:
        clean_type = str(item_type or "").strip()
        clean_id = str(authority_id or "").strip()
        if not clean_type or not clean_id:
            return []
        return list(self.read_reader_highlights().get(clean_type, {}).get(clean_id, []))

    @_synchronized
    def set_reader_highlights(
        self,
        item_type: str,
        authority_id: str,
        entries: list[ReaderHighlight],
    ) -> None:
        clean_type = str(item_type or "").strip()
        clean_id = str(authority_id or "").strip()
        if clean_type not in {"case", "statute", "rule", "prior_brief"} or not clean_id:
            return
        highlights = self.read_reader_highlights()
        if entries:
            highlights.setdefault(clean_type, {})[clean_id] = list(entries)
        else:
            items = highlights.get(clean_type)
            if isinstance(items, dict):
                items.pop(clean_id, None)
                if not items:
                    highlights.pop(clean_type, None)
        if not highlights:
            self.reader_highlights_path().unlink(missing_ok=True)
            return
        payload = {
            item_type_key: {
                item_id: [entry.to_mapping() for entry in item_entries]
                for item_id, item_entries in items.items()
            }
            for item_type_key, items in highlights.items()
        }
        self.write_json(
            self.reader_highlights_path(),
            {"version": 1, "highlights": payload},
        )

    def remove_reader_highlights(self, item_type: str, authority_id: str) -> None:
        self.set_reader_highlights(item_type, authority_id, [])

    @_synchronized
    def active_research_set_metadata(self) -> dict[str, Any] | None:
        metadata = self.read_metadata()
        set_id = metadata.get("active_research_set_id")
        name = str(metadata.get("active_research_set_name") or "").strip()
        if set_id is None or not name:
            return None
        try:
            clean_set_id = int(set_id)
        except (TypeError, ValueError):
            return None
        return {
            "active_research_set_id": clean_set_id,
            "active_research_set_name": name,
            "dirty": bool(metadata.get("dirty")),
            "updated_at": str(metadata.get("updated_at") or ""),
        }

    @_synchronized
    def set_active_research_set(self, set_id: int, name: str, *, dirty: bool = False) -> None:
        clean_name = str(name or "").strip()
        if not clean_name:
            self.clear_active_research_set()
            return
        self.write_metadata(
            {
                "active_research_set_id": int(set_id),
                "active_research_set_name": clean_name,
                "dirty": bool(dirty),
                "updated_at": _utc_now(),
            }
        )

    @_synchronized
    def clear_active_research_set(self) -> None:
        self.metadata_path().unlink(missing_ok=True)

    @_synchronized
    def mark_active_research_set_dirty(self) -> None:
        if self._dirty_tracking_suppressed:
            return
        metadata = self.active_research_set_metadata()
        if metadata is None:
            return
        if metadata.get("dirty"):
            return
        self.set_active_research_set(
            int(metadata["active_research_set_id"]),
            str(metadata["active_research_set_name"]),
            dirty=True,
        )

    def suppress_dirty_tracking(self) -> "_DirtyTrackingSuppression":
        return _DirtyTrackingSuppression(self)

    def read_lookup(self, citation: str) -> Any | None:
        return canonicalize_lookup_result(self.read_json(self.lookup_path(citation)))

    def write_lookup(self, citation: str, value: Any) -> None:
        self.write_json(self.lookup_path(citation), canonicalize_lookup_result(value))

    def read_resource(self, kind: str, resource_id: str) -> Any | None:
        return self.read_json(self.resource_path(kind, resource_id))

    def write_resource(self, kind: str, resource_id: str, value: Any) -> None:
        if kind == "clusters" and isinstance(value, dict):
            value = canonicalize_cluster_citations(value)
        self.write_json(self.resource_path(kind, resource_id), value)

    def list_lookups(self) -> list[Path]:
        lookup_dir = self.root / "lookups"
        if not lookup_dir.exists():
            return []
        return sorted(lookup_dir.glob("*.json"))

    def read_case_index(self) -> dict[str, dict[str, Any]]:
        data = self.read_json(self.case_index_path())
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def write_case_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.write_json(self.case_index_path(), index)

    def read_statute_index(self) -> dict[str, dict[str, Any]]:
        data = self.read_json(self.statute_index_path())
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def write_statute_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.write_json(self.statute_index_path(), index)

    def read_rule_index(self) -> dict[str, dict[str, Any]]:
        data = self.read_json(self.rule_index_path())
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def write_rule_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.write_json(self.rule_index_path(), index)

    def read_agent_answer_index(self) -> dict[str, dict[str, Any]]:
        data = self.read_json(self.agent_answer_index_path())
        if not isinstance(data, dict):
            return {}
        return {str(key): value for key, value in data.items() if isinstance(value, dict)}

    def write_agent_answer_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.write_json(self.agent_answer_index_path(), index)

    def read_slip_opinion_payload(self, case_number: str) -> dict[str, Any] | None:
        data = self.read_json(self.slip_opinion_payload_path(case_number))
        return data if isinstance(data, dict) else None

    def write_slip_opinion_payload(
        self,
        case_number: str,
        payload: dict[str, Any],
        *,
        mark_dirty: bool = True,
    ) -> None:
        if not str(case_number or "").strip():
            return
        with self._lock:
            self.write_json(self.slip_opinion_payload_path(case_number), payload)
            if mark_dirty:
                self.mark_active_research_set_dirty()

    @_synchronized
    def upsert_cluster(
        self,
        cluster: dict[str, Any],
        *,
        mark_dirty: bool = True,
    ) -> str:
        cluster = canonicalize_cluster_citations(cluster)
        cluster_id = cluster_id_from_cluster(cluster)
        if not cluster_id:
            return ""
        self.write_resource("clusters", cluster_id, cluster)
        index = self.read_case_index()
        now = _utc_now()
        existing = index.get(cluster_id, {})
        citations = cluster.get("citations")
        existing_opinion_ids = existing.get("opinion_ids")
        index[cluster_id] = {
            **existing,
            "cluster_id": cluster_id,
            "title": _cluster_title(cluster),
            "citation_text": _cluster_citation_line(cluster),
            "citations": citations if isinstance(citations, list) else [],
            "cluster_path": str(self.cluster_path(cluster_id)),
            "opinion_ids": existing_opinion_ids if isinstance(existing_opinion_ids, list) else [],
            "agent_selected": bool(existing.get("agent_selected", False)),
            "added_at": existing.get("added_at", now),
            "loaded_at": now,
            "last_accessed": now,
        }
        self.write_case_index(index)
        if mark_dirty:
            self.mark_active_research_set_dirty()
        return cluster_id

    @_synchronized
    def update_case_opinions(
        self,
        cluster: dict[str, Any],
        opinion_ids: list[str],
        *,
        mark_dirty: bool = True,
    ) -> None:
        cluster_id = self.upsert_cluster(cluster, mark_dirty=mark_dirty)
        if not cluster_id:
            return
        index = self.read_case_index()
        entry = index.get(cluster_id)
        if not isinstance(entry, dict):
            return
        stored_opinion_ids = entry.get("opinion_ids")
        existing = [
            str(value)
            for value in stored_opinion_ids
            if str(value).strip()
        ] if isinstance(stored_opinion_ids, list) else []
        merged = list(dict.fromkeys([*existing, *opinion_ids]))
        entry["opinion_ids"] = merged
        entry["last_accessed"] = _utc_now()
        index[cluster_id] = entry
        self.write_case_index(index)
        if mark_dirty:
            self.mark_active_research_set_dirty()

    def list_case_entries(self) -> list[dict[str, Any]]:
        entries = list(self.read_case_index().values())
        normalized_entries: list[dict[str, Any]] = []
        for entry in entries:
            cluster_id = str(entry.get("cluster_id", "")).strip()
            cluster = self.read_cached_cluster(cluster_id) if cluster_id else None
            if cluster is not None:
                entry = {**entry, "title": _cluster_title(cluster)}
            normalized_entries.append(entry)
        normalized_entries.sort(
            key=lambda item: (
                str(item.get("title", "")).casefold(),
                str(item.get("citation_text", "")).casefold(),
                str(item.get("cluster_id", "")),
            )
        )
        normalized_entries.sort(key=_cache_sort_timestamp, reverse=True)
        return normalized_entries

    def read_cached_cluster(self, cluster_id: str) -> dict[str, Any] | None:
        data = self.read_resource("clusters", cluster_id)
        return canonicalize_cluster_citations(data) if isinstance(data, dict) else None

    @_synchronized
    def repair_reporter_only_imported_case_names(self) -> int:
        repaired_clusters: dict[str, dict[str, Any]] = {}
        index = self.read_case_index()
        for cluster_id, entry in index.items():
            cluster = self.read_cached_cluster(cluster_id)
            if cluster is None:
                continue
            opinion_ids = entry.get("opinion_ids")
            if not isinstance(opinion_ids, list):
                continue
            for opinion_id in opinion_ids:
                opinion = self.read_resource("opinions", str(opinion_id))
                if not isinstance(opinion, dict):
                    continue
                repaired = repair_reporter_only_imported_cluster(cluster, _opinion_import_text(opinion))
                if repaired is None:
                    continue
                repaired_clusters[cluster_id] = repaired
                self.upsert_cluster(repaired)
                break
        if not repaired_clusters:
            return 0
        self._repair_lookup_clusters(repaired_clusters)
        return len(repaired_clusters)

    def _repair_lookup_clusters(self, repaired_clusters: dict[str, dict[str, Any]]) -> None:
        for lookup_path in self.list_lookups():
            data = self.read_json(lookup_path)
            repaired_data = repair_lookup_result_clusters(data, repaired_clusters)
            if repaired_data is not None:
                self.write_json(lookup_path, repaired_data)

    def is_agent_selected(self, cluster_id: str) -> bool:
        entry = self.read_case_index().get(cluster_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

    @_synchronized
    def set_agent_selected(self, cluster_id: str, selected: bool) -> None:
        if not cluster_id:
            return
        index = self.read_case_index()
        entry = index.get(cluster_id)
        if not isinstance(entry, dict):
            return
        entry["agent_selected"] = bool(selected)
        entry["last_accessed"] = _utc_now()
        index[cluster_id] = entry
        self.write_case_index(index)
        self.mark_active_research_set_dirty()

    @_synchronized
    def remove_case(self, cluster_id: str) -> bool:
        if not cluster_id:
            return False
        index = self.read_case_index()
        entry = index.pop(cluster_id, None)
        if not isinstance(entry, dict):
            return False
        removed_opinion_ids = {
            str(value).strip()
            for value in entry.get("opinion_ids", [])
            if str(value).strip()
        } if isinstance(entry.get("opinion_ids"), list) else set()
        shared_opinion_ids = {
            str(value).strip()
            for other in index.values()
            if isinstance(other.get("opinion_ids"), list)
            for value in other.get("opinion_ids", [])
            if str(value).strip()
        }
        for opinion_id in removed_opinion_ids - shared_opinion_ids:
            self.opinion_path(opinion_id).unlink(missing_ok=True)
        self.cluster_path(cluster_id).unlink(missing_ok=True)
        self.write_case_index(index)
        self.remove_reader_position("case", cluster_id)
        self.remove_reader_highlights("case", cluster_id)
        self.mark_active_research_set_dirty()
        return True

    def selected_case_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_case_entries()
            if bool(entry.get("agent_selected"))
        ]

    @_synchronized
    def upsert_statute(self, statute: dict[str, Any]) -> str:
        statute_id = str(statute.get("statute_id") or "").strip()
        if not statute_id:
            law_code = str(statute.get("law_code") or "").strip().upper()
            section = str(statute.get("section") or "").strip()
            statute_id = f"{law_code}:{section}" if law_code and section else ""
        if not statute_id:
            return ""
        self.write_json(self.statute_path(statute_id), statute)
        index = self.read_statute_index()
        now = _utc_now()
        existing = index.get(statute_id, {})
        index[statute_id] = {
            **existing,
            "statute_id": statute_id,
            "title": str(statute.get("title") or ""),
            "citation": str(statute.get("citation") or ""),
            "law_code": str(statute.get("law_code") or ""),
            "section": str(statute.get("section") or ""),
            "statute_path": str(self.statute_path(statute_id)),
            "agent_selected": bool(existing.get("agent_selected", False)),
            "added_at": existing.get("added_at", now),
            "loaded_at": now,
            "last_accessed": now,
        }
        self.write_statute_index(index)
        self.mark_active_research_set_dirty()
        return statute_id

    def list_statute_entries(self) -> list[dict[str, Any]]:
        entries = list(self.read_statute_index().values())
        entries.sort(
            key=lambda item: (
                str(item.get("title", "")).casefold(),
                str(item.get("citation", "")).casefold(),
                str(item.get("statute_id", "")),
            )
        )
        entries.sort(key=_cache_sort_timestamp, reverse=True)
        return entries

    def read_cached_statute(self, statute_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.statute_path(statute_id))
        return data if isinstance(data, dict) else None

    def is_statute_agent_selected(self, statute_id: str) -> bool:
        entry = self.read_statute_index().get(statute_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

    @_synchronized
    def set_statute_agent_selected(self, statute_id: str, selected: bool) -> None:
        if not statute_id:
            return
        index = self.read_statute_index()
        entry = index.get(statute_id)
        if not isinstance(entry, dict):
            return
        entry["agent_selected"] = bool(selected)
        entry["last_accessed"] = _utc_now()
        index[statute_id] = entry
        self.write_statute_index(index)
        self.mark_active_research_set_dirty()

    def selected_statute_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_statute_entries()
            if bool(entry.get("agent_selected"))
        ]

    @_synchronized
    def remove_statute(self, statute_id: str) -> bool:
        if not statute_id:
            return False
        index = self.read_statute_index()
        entry = index.pop(statute_id, None)
        if not isinstance(entry, dict):
            return False
        self.statute_path(statute_id).unlink(missing_ok=True)
        self.write_statute_index(index)
        self.remove_reader_position("statute", statute_id)
        self.remove_reader_highlights("statute", statute_id)
        self.mark_active_research_set_dirty()
        return True

    @_synchronized
    def upsert_rule(self, rule: dict[str, Any]) -> str:
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            rule_number = str(rule.get("rule_number") or "").strip()
            rule_id = f"CRC:{rule_number}" if rule_number else ""
        if not rule_id:
            return ""
        self.write_json(self.rule_path(rule_id), rule)
        index = self.read_rule_index()
        now = _utc_now()
        existing = index.get(rule_id, {})
        index[rule_id] = {
            **existing,
            "rule_id": rule_id,
            "title": str(rule.get("title") or ""),
            "citation": str(rule.get("citation") or ""),
            "rule_number": str(rule.get("rule_number") or ""),
            "rule_slug": str(rule.get("rule_slug") or ""),
            "title_slug": str(rule.get("title_slug") or ""),
            "rule_path": str(self.rule_path(rule_id)),
            "agent_selected": bool(existing.get("agent_selected", False)),
            "added_at": existing.get("added_at", now),
            "loaded_at": now,
            "last_accessed": now,
        }
        self.write_rule_index(index)
        self.mark_active_research_set_dirty()
        return rule_id

    def list_rule_entries(self) -> list[dict[str, Any]]:
        entries = list(self.read_rule_index().values())
        entries.sort(
            key=lambda item: (
                str(item.get("title", "")).casefold(),
                str(item.get("citation", "")).casefold(),
                str(item.get("rule_id", "")),
            )
        )
        entries.sort(key=_cache_sort_timestamp, reverse=True)
        return entries

    def read_cached_rule(self, rule_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.rule_path(rule_id))
        return data if isinstance(data, dict) else None

    def is_rule_agent_selected(self, rule_id: str) -> bool:
        entry = self.read_rule_index().get(rule_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

    @_synchronized
    def set_rule_agent_selected(self, rule_id: str, selected: bool) -> None:
        if not rule_id:
            return
        index = self.read_rule_index()
        entry = index.get(rule_id)
        if not isinstance(entry, dict):
            return
        entry["agent_selected"] = bool(selected)
        entry["last_accessed"] = _utc_now()
        index[rule_id] = entry
        self.write_rule_index(index)
        self.mark_active_research_set_dirty()

    def selected_rule_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_rule_entries()
            if bool(entry.get("agent_selected"))
        ]

    @_synchronized
    def remove_rule(self, rule_id: str) -> bool:
        if not rule_id:
            return False
        index = self.read_rule_index()
        entry = index.pop(rule_id, None)
        if not isinstance(entry, dict):
            return False
        self.rule_path(rule_id).unlink(missing_ok=True)
        self.write_rule_index(index)
        self.remove_reader_position("rule", rule_id)
        self.remove_reader_highlights("rule", rule_id)
        self.mark_active_research_set_dirty()
        return True

    def read_prior_brief_index(self) -> dict[str, dict[str, Any]]:
        data = self.read_json(self.prior_brief_index_path())
        return data if isinstance(data, dict) else {}

    def write_prior_brief_index(self, index: dict[str, dict[str, Any]]) -> None:
        self.write_json(self.prior_brief_index_path(), index)

    @_synchronized
    def upsert_prior_brief(self, brief: dict[str, Any]) -> str:
        brief_id = str(brief.get("brief_id") or "").strip()
        text = str(brief.get("text") or "").strip()
        if not brief_id or not text:
            return ""
        self.write_json(self.prior_brief_path(brief_id), brief)
        index = self.read_prior_brief_index()
        existing = index.get(brief_id, {})
        index[brief_id] = {
            "brief_id": brief_id,
            "title": str(brief.get("title") or "Untitled prior brief"),
            "case_number": str(brief.get("case_number") or ""),
            "document_type": str(brief.get("document_type") or "Prior brief"),
            "document_date": str(brief.get("document_date") or ""),
            "date_source": str(brief.get("date_source") or ""),
            "relative_path": str(brief.get("relative_path") or ""),
            "brief_path": str(self.prior_brief_path(brief_id)),
            "agent_selected": bool(existing.get("agent_selected", False)),
            "added_at": str(existing.get("added_at") or _utc_now()),
            "loaded_at": _utc_now(),
        }
        self.write_prior_brief_index(index)
        self.mark_active_research_set_dirty()
        return brief_id

    def list_prior_brief_entries(self) -> list[dict[str, Any]]:
        entries = list(self.read_prior_brief_index().values())
        entries.sort(
            key=lambda item: (
                str(item.get("document_date") or ""),
                str(item.get("title") or "").casefold(),
            ),
            reverse=True,
        )
        return entries

    def read_prior_brief(self, brief_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.prior_brief_path(brief_id))
        return data if isinstance(data, dict) else None

    def is_prior_brief_agent_selected(self, brief_id: str) -> bool:
        entry = self.read_prior_brief_index().get(brief_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

    @_synchronized
    def set_prior_brief_agent_selected(self, brief_id: str, selected: bool) -> None:
        index = self.read_prior_brief_index()
        entry = index.get(brief_id)
        if not isinstance(entry, dict):
            return
        entry["agent_selected"] = bool(selected)
        index[brief_id] = entry
        self.write_prior_brief_index(index)
        self.mark_active_research_set_dirty()

    def selected_prior_brief_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_prior_brief_entries()
            if bool(entry.get("agent_selected"))
        ]

    @_synchronized
    def remove_prior_brief(self, brief_id: str) -> bool:
        index = self.read_prior_brief_index()
        entry = index.pop(brief_id, None)
        if not isinstance(entry, dict):
            return False
        self.prior_brief_path(brief_id).unlink(missing_ok=True)
        self.write_prior_brief_index(index)
        self.remove_reader_position("prior_brief", brief_id)
        self.remove_reader_highlights("prior_brief", brief_id)
        self.mark_active_research_set_dirty()
        return True

    @_synchronized
    def save_agent_answer(self, text: str, *, mode: str = "", title: str = "") -> str:
        clean_text = text.strip()
        if not clean_text:
            return ""
        answer_id = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()[:24]
        now = _utc_now()
        index = self.read_agent_answer_index()
        existing = index.get(answer_id, {})
        resolved_title = title.strip() or _agent_answer_title(clean_text, mode)
        answer = {
            "answer_id": answer_id,
            "title": resolved_title,
            "mode": mode.strip(),
            "text": clean_text,
            "saved_at": existing.get("saved_at", now),
            "last_accessed": now,
        }
        self.write_json(self.agent_answer_path(answer_id), answer)
        index[answer_id] = {
            **existing,
            "answer_id": answer_id,
            "title": resolved_title,
            "mode": mode.strip(),
            "answer_path": str(self.agent_answer_path(answer_id)),
            "agent_selected": bool(existing.get("agent_selected", False)),
            "added_at": existing.get("added_at", now),
            "loaded_at": now,
            "last_accessed": now,
        }
        self.write_agent_answer_index(index)
        self.mark_active_research_set_dirty()
        return answer_id

    def list_agent_answer_entries(self) -> list[dict[str, Any]]:
        entries = list(self.read_agent_answer_index().values())
        entries.sort(
            key=lambda item: (
                str(item.get("title", "")).casefold(),
                str(item.get("answer_id", "")),
            )
        )
        entries.sort(key=_cache_sort_timestamp, reverse=True)
        return entries

    @_synchronized
    def read_agent_answer(self, answer_id: str) -> dict[str, Any] | None:
        data = self.read_json(self.agent_answer_path(answer_id))
        if not isinstance(data, dict):
            return None
        index = self.read_agent_answer_index()
        entry = index.get(answer_id)
        if isinstance(entry, dict):
            entry["last_accessed"] = _utc_now()
            index[answer_id] = entry
            self.write_agent_answer_index(index)
        return data

    def is_agent_answer_selected(self, answer_id: str) -> bool:
        entry = self.read_agent_answer_index().get(answer_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

    @_synchronized
    def set_agent_answer_selected(self, answer_id: str, selected: bool) -> None:
        if not answer_id:
            return
        index = self.read_agent_answer_index()
        entry = index.get(answer_id)
        if not isinstance(entry, dict):
            return
        entry["agent_selected"] = bool(selected)
        entry["last_accessed"] = _utc_now()
        index[answer_id] = entry
        self.write_agent_answer_index(index)
        self.mark_active_research_set_dirty()

    def selected_agent_answer_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_agent_answer_entries()
            if bool(entry.get("agent_selected"))
        ]

    @_synchronized
    def remove_agent_answer(self, answer_id: str) -> bool:
        if not answer_id:
            return False
        index = self.read_agent_answer_index()
        entry = index.pop(answer_id, None)
        if not isinstance(entry, dict):
            return False
        self.agent_answer_path(answer_id).unlink(missing_ok=True)
        self.write_agent_answer_index(index)
        self.remove_reader_position("agent_answer", answer_id)
        self.mark_active_research_set_dirty()
        return True

    @_synchronized
    def clear(
        self,
        *,
        preserve_reader_positions: bool = False,
        preserve_reader_highlights: bool = False,
    ) -> None:
        trash_path = self.detach_for_clear(
            preserve_reader_positions=preserve_reader_positions,
            preserve_reader_highlights=preserve_reader_highlights,
        )
        if trash_path is not None:
            shutil.rmtree(trash_path)

    @_synchronized
    def detach_for_clear(
        self,
        *,
        preserve_reader_positions: bool = False,
        preserve_reader_highlights: bool = False,
    ) -> Path | None:
        self.root.mkdir(parents=True, exist_ok=True)
        trash_path = self.root / f".clear-trash-{_utc_now().replace(':', '-')}-{uuid.uuid4().hex}"
        moved: list[tuple[Path, Path]] = []
        try:
            sources = [
                self.root / "lookups",
                self.root / "clusters",
                self.root / "opinions",
                self.root / "statutes",
                self.root / "rules",
                self.root / "prior_briefs",
                self.root / "agent_answers",
                self.case_index_path(),
                self.statute_index_path(),
                self.rule_index_path(),
                self.prior_brief_index_path(),
                self.agent_answer_index_path(),
                self.metadata_path(),
            ]
            if not preserve_reader_positions:
                sources.append(self.reader_positions_path())
            if not preserve_reader_highlights:
                sources.append(self.reader_highlights_path())
            for source in sources:
                if not source.exists():
                    continue
                trash_path.mkdir(parents=True, exist_ok=True)
                target = trash_path / source.name
                source.rename(target)
                moved.append((source, target))
            self.ensure()
        except Exception:
            for source, target in reversed(moved):
                if not target.exists():
                    continue
                if source.exists() and source.is_dir() and not any(source.iterdir()):
                    source.rmdir()
                if not source.exists():
                    target.rename(source)
            if trash_path.exists():
                shutil.rmtree(trash_path, ignore_errors=True)
            raise
        return trash_path if moved else None


class _DirtyTrackingSuppression:
    def __init__(self, cache: JsonCache) -> None:
        self.cache = cache
        self.previous = False

    def __enter__(self) -> None:
        self.previous = self.cache._dirty_tracking_suppressed
        self.cache._dirty_tracking_suppressed = True

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.cache._dirty_tracking_suppressed = self.previous


def _cluster_title(cluster: dict[str, Any]) -> str:
    title = cluster_short_title_value(cluster)
    if title:
        return title
    cluster_id = cluster_id_from_cluster(cluster)
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def _cluster_citation_line(cluster: dict[str, Any]) -> str:
    return official_citation_from_cluster(cluster)
