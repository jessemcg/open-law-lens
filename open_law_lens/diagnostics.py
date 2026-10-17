"""Content-free, non-provisioning capability diagnostics shared by GUI and CLI."""
from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .paths import RESOURCE_ROOT, standalone

RESOURCES = (
    "scripts/open-law-lens-agent-vte.sh", "scripts/open-law-lens-standalone.sh", "scripts/standalone-runtime.py",
    ".pi/SYSTEM.md", ".pi/extensions/open-law-lens-followup-bridge.ts",
    *[f".pi/skills/{name}/SKILL.md" for name in (
        "legal-researcher", "law-question", "research-cache", "prior-briefs",
        "case-assessment", "subsequent-treatment")],
    "open-law-lens-icon.png", "open-law-lens-icon.svg", "open-law-lens-icon-symbolic.svg",
    "scripts/open-law-lens.desktop.in",
    *[f"open_law_lens/icons/hicolor/scalable/actions/{name}-symbolic.svg" for name in (
        "cafe", "clipboard", "file-cabinet", "highlighter", "library", "license")],
)


def version_info() -> dict[str, str]:
    try:
        version = importlib.metadata.version("open-law-lens")
    except importlib.metadata.PackageNotFoundError:
        version = "0.1.0 (source)"
    revision = "unknown"
    try:
        result = subprocess.run(["git", "-C", str(RESOURCE_ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=2, check=False)
        value = result.stdout.strip()
        if result.returncode == 0 and value and all(c in "0123456789abcdef" for c in value):
            revision = value
    except (OSError, subprocess.SubprocessError):
        pass
    return {"version": version, "revision": revision}


def report(*, agent_check: bool = False, connectivity: bool = False) -> dict:
    """No network, Pi execution, browser or desktop interactions by default.

    Explicit agent_check performs offline model enumeration (no prompt/model
    calls). Connectivity contacts only CourtListener; never returns headers,
    credentials, response text, document paths or raw exception messages.
    """
    capabilities: dict[str, dict] = {}

    def capability(name: str, checks: list[tuple[str, str, str]]) -> None:
        statuses = [status for _, status, _ in checks]
        status = "missing" if "missing" in statuses else ("not_checked" if "not_checked" in statuses else "ready")
        capabilities[name] = {"status": status, "checks": [
            {"name": label, "status": state, "detail": detail} for label, state, detail in checks
        ]}

    def binary(name: str, explanation: str = "") -> tuple[str, str, str]:
        available = bool(shutil.which(name))
        return name, "ready" if available else "missing", explanation or ("Executable available." if available else f"Install {name} to enable this feature.")

    gtk_ok = adw_ok = vte_ok = False
    gtk_version = adw_version = "unavailable"
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk, Adw
        gtk_version = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
        adw_version = f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
        gtk_ok = hasattr(Gtk, "FileDialog")
        adw_ok = hasattr(Adw, "SpinRow") and hasattr(Adw, "ToolbarView")
        try:
            gi.require_version("Vte", "3.91")
            from gi.repository import Vte  # noqa: F401
            vte_ok = True
        except (ImportError, ValueError):
            pass
    except (ImportError, ValueError):
        pass
    capability("core_gui", [
        ("Python >=3.13", "ready" if sys.version_info >= (3, 13) else "missing", "Use the explicitly provisioned environment."),
        ("GTK >=4.10", "ready" if gtk_ok else "missing", gtk_version),
        ("Libadwaita >=1.4", "ready" if adw_ok else "missing", adw_version),
        ("Bundled resources", "ready" if all((RESOURCE_ROOT / path).is_file() and (RESOURCE_ROOT / path).stat().st_size for path in RESOURCES) else "missing", "A complete source installation is required."),
    ])
    from .config import courtlistener_token
    try:
        token = courtlistener_token()
        token_status = "ready" if token else "missing"
    except (OSError, ValueError):
        token = ""
        token_status = "missing"
    court_checks = [("API token", token_status, "Set COURTLISTENER_TOKEN or save it in Settings; value is never reported.")]
    if connectivity:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        try:
            headers = {"Authorization": f"Token {token}"} if token else {}
            with urlopen(Request("https://www.courtlistener.com/api/rest/v4/", headers=headers), timeout=5) as response:
                success = response.status == 200
            detail = "CourtListener responded successfully."
        except HTTPError as exc:
            success = False
            detail = f"CourtListener returned HTTP {exc.code}."
        except Exception:
            success = False
            detail = "CourtListener connection failed; check network and token."
        court_checks.append(("Connectivity", "ready" if success else "missing", detail))
    else:
        court_checks.append(("Connectivity", "not_checked", "Opt in with doctor --connectivity."))
    capability("courtlistener", court_checks)

    from .pi_runtime import find_pi_executable, find_pi_node_executable, available_pi_runtime_catalog
    pi = find_pi_executable()
    node = find_pi_node_executable(pi)
    node_ok = False
    if node:
        try:
            result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=2, check=False)
            parts = tuple(int(part) for part in result.stdout.strip().lstrip("v").split("."))
            node_ok = result.returncode == 0 and parts >= (22, 19, 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent"))).expanduser()
    web = Path(os.environ.get("OPEN_LAW_LENS_WEB_ACCESS_EXTENSION", str(agent_dir / "npm/node_modules/pi-web-access/index.ts")))
    model_status, model_detail = "not_checked", "Authorize models in Pi. Opt in to offline enumeration with doctor --agent-check."
    if agent_check:
        try:
            catalog = available_pi_runtime_catalog()
            model_status = "ready" if catalog.models and catalog.default_model and catalog.default_model.settings_key in {m.settings_key for m in catalog.models} else "missing"
            model_detail = "Offline authorization/default check completed; no model calls. Select workflow overrides in Settings if needed."
        except Exception:
            model_status, model_detail = "missing", "Pi setup query failed; install Pi and authorize your chosen provider there."
    capability("agent_workflows", [
        ("VTE 3.91", "ready" if vte_ok else "missing", "Required only for the embedded terminal."),
        ("Pi", "ready" if shutil.which(pi) else "missing", "Install and authorize Pi separately."),
        ("Pi Node >=22.19", "ready" if node_ok else "missing", "Use the supported Node beside the selected Pi executable."),
        ("Authorized default model", model_status, model_detail),
    ])
    capability("agent_web_research", [
        ("pi-web-access", "ready" if web.is_file() else "missing", "Additionally required for Law, Assessment and Treatment. Closed-corpus workflows do not need this extension."),
    ])
    capability("pdf_extraction", [binary("pdftotext")])
    capability("prior_brief_indexing", [binary("pandoc")])
    from .computer_use_mcp import resolve_computer_use_command, ComputerUseMCPError
    try:
        computer_use_available = bool(resolve_computer_use_command())
    except ComputerUseMCPError:
        computer_use_available = False
    browser_available = False
    try:
        from gi.repository import Gio
        browser_available = Gio.AppInfo.get_default_for_uri_scheme("https") is not None
    except (ImportError, ValueError):
        pass
    capability("browser_recovery", [
        ("Computer Use", "ready" if computer_use_available else "missing", "Install @agent-sh/computer-use-linux separately."),
        ("Default HTTPS browser", "ready" if browser_available else "missing", "Configure a default browser with accessible document content; no browser was opened."),
        ("Desktop readiness and exact targeting", "not_checked", "Run computer-use-linux doctor explicitly; supported default HTTPS browser, accessibility and exact window targeting are required. No permission changes or browser actions were attempted."),
        ("Regular clipboard", "ready" if any(shutil.which(tool) for tool in ("wl-paste", "xclip", "xsel")) else "missing", "Requires a clipboard reader supported by this desktop."),
    ])
    capability("selection_lookup", [
        ("Selection/clipboard reader", "ready" if any(shutil.which(tool) for tool in ("wl-paste", "xclip", "xsel")) else "missing", "Install wl-clipboard (Wayland) or xclip/xsel (X11). Availability does not prove compositor access."),
    ])
    return {"schema_version": 1, **version_info(), "storage": "standalone" if standalone() else "legacy", "capabilities": capabilities}


def format_report(value: dict) -> str:
    lines = [f"Open Law Lens {value['version']} / {value['revision']} ({value['storage']})"]
    for name, capability in value["capabilities"].items():
        lines.append(f"\n{name.replace('_', ' ').title()}: {capability['status']}")
        for check in capability["checks"]:
            lines.append(f"  [{check['status']}] {check['name']}: {check['detail']}")
    return "\n".join(lines)
