#!/usr/bin/env python3
"""Record/check explicit standalone provisioning; never installs anything."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid


def contract() -> dict:
    source = Path(__file__).resolve().parent.parent
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "uv.lock"):
        digest.update((source / name).read_bytes())
    return {"schema": 1, "source": str(source), "environment": sys.prefix,
            "dependency_sha256": digest.hexdigest(), "python": list(sys.version_info[:2])}


def main() -> int:
    receipt = Path(sys.prefix) / ".open-law-lens-runtime.json"
    try:
        expected = contract()
        source = Path(expected["source"])
        if sys.prefix == sys.base_prefix or sys.version_info[:2] != (3, 13) or not os.access(Path(sys.prefix) / "bin/open-law-lens", os.X_OK):
            raise ValueError("Expected a provisioned Python 3.13 Open Law Lens environment")
        import open_law_lens
        if Path(open_law_lens.__file__).resolve().parent.parent != source:
            raise ValueError("Environment must select this complete source installation")
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk, Adw
        import trafilatura  # noqa: F401
        from open_law_lens.diagnostics import RESOURCES
        if not hasattr(Gtk, "FileDialog") or not hasattr(Adw, "SpinRow") or not hasattr(Adw, "ToolbarView"):
            raise ValueError("Core GTK/Libadwaita APIs are unavailable")
        if not all((source / name).is_file() and (source / name).stat().st_size for name in RESOURCES):
            raise ValueError("Incomplete source resources")
        if sys.argv[1:] == ["--record"]:
            os.umask(0o077)
            temporary = receipt.with_name(f".{receipt.name}.{uuid.uuid4().hex}.tmp")
            try:
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as stream:
                    json.dump(expected, stream, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, receipt)
            finally:
                temporary.unlink(missing_ok=True)
            return 0
        if sys.argv[1:] != ["--check"] or json.loads(receipt.read_text()) != expected:
            raise ValueError("Missing or stale provisioning receipt")
        return 0
    except (OSError, ValueError, ImportError):
        print("Open Law Lens standalone environment is missing, stale, or lacks required GTK/resources. Explicitly provision the locked environment, then run its Python with scripts/standalone-runtime.py --record. See docs/portability.md. Launch never installs dependencies.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
