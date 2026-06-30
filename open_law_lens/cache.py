from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .case_titles import cluster_short_title_value

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_CACHE_DIR = PROJECT_ROOT / "cache"


def normalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def cache_root() -> Path:
    root = os.environ.get("OPEN_LAW_LENS_CACHE_DIR")
    if root:
        return Path(root).expanduser()
    return PROJECT_CACHE_DIR


def citation_cache_key(citation: str) -> str:
    normalized = normalize_citation(citation).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resource_id_from_url(url: str) -> str:
    stripped = url.rstrip("/")
    return stripped.rsplit("/", 1)[-1]


def cluster_id_from_cluster(cluster: dict[str, Any]) -> str:
    value = cluster.get("id")
    if value is not None and str(value).strip():
        return str(value).strip()
    for key in ("resource_uri", "absolute_url", "cluster_url"):
        url = cluster.get(key)
        if isinstance(url, str) and url.strip():
            return resource_id_from_url(url)
    return ""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass
class JsonCache:
    root: Path

    @classmethod
    def default(cls) -> "JsonCache":
        return cls(cache_root())

    def ensure(self) -> None:
        for name in ("lookups", "clusters", "opinions"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def case_index_path(self) -> Path:
        return self.root / "cases_index.json"

    def lookup_path(self, citation: str) -> Path:
        return self.root / "lookups" / f"{citation_cache_key(citation)}.json"

    def resource_path(self, kind: str, resource_id: str) -> Path:
        return self.root / kind / f"{resource_id}.json"

    def cluster_path(self, cluster_id: str) -> Path:
        return self.resource_path("clusters", cluster_id)

    def opinion_path(self, opinion_id: str) -> Path:
        return self.resource_path("opinions", opinion_id)

    def read_json(self, path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def read_lookup(self, citation: str) -> Any | None:
        return self.read_json(self.lookup_path(citation))

    def write_lookup(self, citation: str, value: Any) -> None:
        self.write_json(self.lookup_path(citation), value)

    def read_resource(self, kind: str, resource_id: str) -> Any | None:
        return self.read_json(self.resource_path(kind, resource_id))

    def write_resource(self, kind: str, resource_id: str, value: Any) -> None:
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

    def upsert_cluster(self, cluster: dict[str, Any]) -> str:
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
            "last_accessed": now,
        }
        self.write_case_index(index)
        return cluster_id

    def update_case_opinions(self, cluster: dict[str, Any], opinion_ids: list[str]) -> None:
        cluster_id = self.upsert_cluster(cluster)
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
        normalized_entries.sort(key=lambda item: str(item.get("added_at", "")), reverse=True)
        return normalized_entries

    def read_cached_cluster(self, cluster_id: str) -> dict[str, Any] | None:
        data = self.read_resource("clusters", cluster_id)
        return data if isinstance(data, dict) else None

    def is_agent_selected(self, cluster_id: str) -> bool:
        entry = self.read_case_index().get(cluster_id)
        return bool(entry.get("agent_selected")) if isinstance(entry, dict) else False

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
        return True

    def selected_case_entries(self) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.list_case_entries()
            if bool(entry.get("agent_selected"))
        ]

    def clear(self) -> None:
        trash_path = self.detach_for_clear()
        if trash_path is not None:
            shutil.rmtree(trash_path)

    def detach_for_clear(self) -> Path | None:
        self.root.mkdir(parents=True, exist_ok=True)
        trash_path = self.root / f".clear-trash-{_utc_now().replace(':', '-')}-{uuid.uuid4().hex}"
        moved: list[tuple[Path, Path]] = []
        try:
            for source in (
                self.root / "lookups",
                self.root / "clusters",
                self.root / "opinions",
                self.case_index_path(),
            ):
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


def _cluster_title(cluster: dict[str, Any]) -> str:
    title = cluster_short_title_value(cluster)
    if title:
        return title
    cluster_id = cluster_id_from_cluster(cluster)
    return f"Cluster {cluster_id}" if cluster_id else "Untitled case"


def _cluster_citation_line(cluster: dict[str, Any]) -> str:
    citations = cluster.get("citations")
    if not isinstance(citations, list):
        return ""
    rendered: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        pieces = [
            str(piece).strip()
            for piece in (citation.get("volume"), citation.get("reporter"), citation.get("page"))
            if str(piece).strip()
        ]
        if pieces:
            rendered.append(" ".join(pieces))
    return "; ".join(rendered)
