"""Application resources and storage. Resolution never creates or migrates files.

Legacy is the compatibility default for existing maintained callers. Public
launchers MUST select standalone before importing any application modules.
"""
from __future__ import annotations

import os
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent.parent


def standalone() -> bool:
    mode = os.environ.get("OPEN_LAW_LENS_STORAGE", "legacy")
    if mode not in {"legacy", "standalone"}:
        raise ValueError("OPEN_LAW_LENS_STORAGE must be legacy or standalone")
    return mode == "standalone"


def xdg(kind: str) -> Path:
    defaults = {"config": ".config", "data": ".local/share", "cache": ".cache", "state": ".local/state"}
    value = os.environ.get(f"XDG_{kind.upper()}_HOME", "")
    base = Path(value) if value and Path(value).is_absolute() else Path.home() / defaults[kind]
    return base / "open-law-lens"


def config_path() -> Path:
    return Path(os.environ.get("OPEN_LAW_LENS_CONFIG") or
                (xdg("config") / "config.json" if standalone() else RESOURCE_ROOT / "config.json")).expanduser()


def data_root() -> Path:
    return xdg("data") if standalone() else RESOURCE_ROOT


def research_root() -> Path:
    # This store includes saved answers, highlights and selected research, NOT
    # just disposable HTTP responses. Never put it in XDG_CACHE_HOME.
    return Path(os.environ.get("OPEN_LAW_LENS_CACHE_DIR") or
                (data_root() / "research" if standalone() else RESOURCE_ROOT / "cache")).expanduser()


def library_path() -> Path:
    return Path(os.environ.get("OPEN_LAW_LENS_LIBRARY_DB") or
                data_root() / "library" / "open_law_lens.sqlite3").expanduser()


def pi_settings_path() -> Path:
    return xdg("config") / "pi" / "settings.json" if standalone() else RESOURCE_ROOT / ".pi" / "settings.json"


def workspace_root() -> Path:
    return xdg("state") / "agent-workspaces"


def runtime_root(*, create: bool = False) -> Path:
    import stat
    import tempfile
    configured = os.environ.get("XDG_RUNTIME_DIR", "")
    # New transient namespace avoids changing permissions of historical runtime
    # directories or disrupting sockets belonging to an already-running session.
    root = (Path(configured) / "open-law-lens-private" if configured and Path(configured).is_absolute()
            else Path(tempfile.gettempdir()) / f"open-law-lens-{os.getuid()}-private")
    if create:
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise OSError("Open Law Lens runtime directory must be a private owned directory, not a symlink")
    return root


def execution_env() -> dict[str, str]:
    import sys
    return {
        "OPEN_LAW_LENS_CLI_BIN": str(Path(sys.executable).parent / "open-law-lens"),
        "OPEN_LAW_LENS_STORAGE": "standalone" if standalone() else "legacy",
        "OPEN_LAW_LENS_CONFIG": str(config_path().absolute()),
        "OPEN_LAW_LENS_PI_SETTINGS": str(pi_settings_path().absolute()),
    }
