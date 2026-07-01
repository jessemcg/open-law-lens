from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


REQUEST_MAX_AGE_SECONDS = 30.0


def request_path() -> Path:
    root = os.environ.get("OPEN_LAW_LENS_REQUEST_DIR", "").strip()
    if root:
        return Path(root).expanduser() / "open_authority_request.json"
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if runtime_dir:
        return Path(runtime_dir) / "open-law-lens" / "open_authority_request.json"
    return Path("/tmp") / f"open-law-lens-{os.getuid()}" / "open_authority_request.json"


def write_open_authority_request(text: str) -> None:
    path = request_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": uuid.uuid4().hex,
        "created_at": time.time(),
        "text": text,
    }
    temp_path = path.with_suffix(f".{payload['id']}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    temp_path.replace(path)


def discard_open_authority_request() -> None:
    try:
        request_path().unlink()
    except FileNotFoundError:
        pass


def pop_open_authority_request() -> str:
    path = request_path()
    try:
        raw = path.read_text(encoding="utf-8")
        path.unlink()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    created_at = payload.get("created_at")
    try:
        age = time.time() - float(created_at)
    except (TypeError, ValueError):
        return ""
    if age > REQUEST_MAX_AGE_SECONDS:
        return ""
    return str(payload.get("text") or "").strip()
