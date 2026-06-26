from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def normalize_citation(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def cache_root() -> Path:
    root = os.environ.get("OPEN_LAW_LENS_CACHE_DIR")
    if root:
        return Path(root).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "open-law-lens"
    return Path.home() / ".cache" / "open-law-lens"


def citation_cache_key(citation: str) -> str:
    normalized = normalize_citation(citation).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resource_id_from_url(url: str) -> str:
    stripped = url.rstrip("/")
    return stripped.rsplit("/", 1)[-1]


@dataclass
class JsonCache:
    root: Path

    @classmethod
    def default(cls) -> "JsonCache":
        return cls(cache_root())

    def ensure(self) -> None:
        for name in ("lookups", "clusters", "opinions"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def lookup_path(self, citation: str) -> Path:
        return self.root / "lookups" / f"{citation_cache_key(citation)}.json"

    def resource_path(self, kind: str, resource_id: str) -> Path:
        return self.root / kind / f"{resource_id}.json"

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

