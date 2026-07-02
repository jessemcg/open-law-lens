from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from . import APP_ID
from .authority_resolver import extract_authority, read_selected_text_from_os
from .cache import JsonCache
from .cli_commands import build_cli_commands_text
from .client import CourtListenerClient, CourtListenerError
from .launch_request import discard_open_authority_request, write_open_authority_request
from .library import CaseLibrary, LibraryPruneCandidate
from .rules import CaliforniaRulesError
from .statutes import LegInfoError

PROJECT_DIR = Path(__file__).resolve().parent.parent
DBUS_ACTIVATE_TIMEOUT_SECONDS = 0.35
DESKTOP_APP_ID = APP_ID


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _cmd_app(args: argparse.Namespace) -> int:
    from .app import main as app_main

    open_authority = str(getattr(args, "open_authority", "") or "").strip()
    if open_authority:
        return app_main(["--open-authority", open_authority])
    return app_main()


def _cmd_lookup(args: argparse.Namespace) -> int:
    client = CourtListenerClient.default()
    result = client.lookup_citation(args.citation, refresh=args.refresh)
    if not args.text:
        _print_json(result)
        return 0
    clusters = client.clusters_from_lookup(result)
    if not clusters:
        print("No matching CourtListener case clusters.", file=sys.stderr)
        return 1
    opinions = client.reader_opinions(
        client.fetch_cluster_opinions(clusters[0], refresh=args.refresh)
    )
    for opinion in opinions:
        text = client.opinion_display(opinion).text
        if text:
            print(text)
            return 0
    print("No opinion text found for first matching cluster.", file=sys.stderr)
    return 1


def _print_authority_result(args: argparse.Namespace, authority_type: str) -> int:
    try:
        result = extract_authority(
            args.value,
            authority_type=authority_type,
            refresh=getattr(args, "refresh", False),
        )
    except (CourtListenerError, LegInfoError, CaliforniaRulesError, ValueError, RuntimeError) as exc:
        if getattr(args, "text", False):
            print(str(exc), file=sys.stderr)
            return 1
        _print_json(
            {
                "ok": False,
                "authority_type": authority_type,
                "input": args.value,
                "resolved_input": "",
                "source": "",
                "title": "",
                "citation": "",
                "identifier": "",
                "source_url": "",
                "text": "",
                "text_length": 0,
                "warnings": [],
                "error": str(exc),
            }
        )
        return 1
    if getattr(args, "text", False):
        if result.text:
            print(result.text)
            return 0
        if result.error:
            print(result.error, file=sys.stderr)
        return 1
    _print_json(result.to_json())
    return 0 if result.ok else 1


def _cmd_extract(args: argparse.Namespace) -> int:
    return _print_authority_result(args, "auto")


def _cmd_extract_case(args: argparse.Namespace) -> int:
    return _print_authority_result(args, "case")


def _cmd_extract_statute(args: argparse.Namespace) -> int:
    return _print_authority_result(args, "statute")


def _cmd_extract_rule(args: argparse.Namespace) -> int:
    return _print_authority_result(args, "rule")


def _cmd_commands(_args: argparse.Namespace) -> int:
    print(build_cli_commands_text(), end="")
    return 0


def _activate_open_authority(value: str, *, timeout: float = DBUS_ACTIVATE_TIMEOUT_SECONDS) -> bool:
    command = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        APP_ID,
        "--object-path",
        "/" + APP_ID.replace(".", "/"),
        "--method",
        "org.gtk.Actions.Activate",
        "open_authority",
        f"[<'{_dbus_quote(value)}'>]",
        "{}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _dbus_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _start_app_detached(open_text: str = "") -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "open_law_lens", "app"],
        cwd=PROJECT_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def _launch_desktop_app() -> bool:
    try:
        result = subprocess.run(
            ["gtk-launch", DESKTOP_APP_ID],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _open_authority_after_launch(value: str) -> int:
    try:
        write_open_authority_request(value)
        if _launch_desktop_app():
            return 0
        _start_app_detached()
    except OSError as exc:
        discard_open_authority_request()
        print(f"Unable to launch Open Law Lens: {exc}", file=sys.stderr)
        return 1
    return 0


def _open_authority_in_app(value: str) -> int:
    value = value.strip()
    if not value:
        print("No authority text provided.", file=sys.stderr)
        return 1
    if _activate_open_authority(value):
        return 0
    return _open_authority_after_launch(value)


def _cmd_open(args: argparse.Namespace) -> int:
    return _open_authority_in_app(args.value)


def _cmd_open_selected(_args: argparse.Namespace) -> int:
    value, _source = read_selected_text_from_os()
    return _open_authority_in_app(value)


def _cmd_lookup_statute(args: argparse.Namespace) -> int:
    client = CourtListenerClient.default()
    statute = client.lookup_statute(args.citation, refresh=args.refresh)
    if args.text:
        print(str(statute.get("text") or ""))
        return 0
    _print_json(statute)
    return 0


def _cmd_lookup_rule(args: argparse.Namespace) -> int:
    client = CourtListenerClient.default()
    rule = client.lookup_rule(args.citation, refresh=args.refresh)
    if args.text:
        print(str(rule.get("text") or ""))
        return 0
    _print_json(rule)
    return 0


def _cmd_show_library(_args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    entries = library.list_case_entries()
    if not entries:
        print("No saved library cases.")
        return 0
    for entry in entries:
        title = str(entry.get("title") or "Untitled case")
        citation = str(entry.get("citation_text") or "").strip()
        cluster_id = str(entry.get("cluster_id") or "").strip()
        opinion_ids = entry.get("opinion_ids")
        opinion_count = len(opinion_ids) if isinstance(opinion_ids, list) else 0
        citation_part = f" | {citation}" if citation else ""
        print(f"{title}{citation_part} | cluster {cluster_id} | {opinion_count} opinion(s)")
    return 0


def _cmd_show_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    entries = cache.list_case_entries()
    statutes = cache.list_statute_entries()
    rules = cache.list_rule_entries()
    if not entries and not statutes and not rules:
        print("No Research Cache authorities.")
        return 0
    for entry in entries:
        title = str(entry.get("title") or "Untitled case")
        citation = str(entry.get("citation_text") or "").strip()
        cluster_id = str(entry.get("cluster_id") or "").strip()
        opinion_ids = entry.get("opinion_ids")
        opinion_count = len(opinion_ids) if isinstance(opinion_ids, list) else 0
        citation_part = f" | {citation}" if citation else ""
        print(f"{title}{citation_part} | cluster {cluster_id} | {opinion_count} opinion(s)")
    for entry in statutes:
        title = str(entry.get("title") or "Untitled statute")
        citation = str(entry.get("citation") or "").strip()
        statute_id = str(entry.get("statute_id") or "").strip()
        citation_part = f" | {citation}" if citation else ""
        print(f"{title}{citation_part} | statute {statute_id}")
    for entry in rules:
        title = str(entry.get("title") or "Untitled rule")
        citation = str(entry.get("citation") or "").strip()
        rule_id = str(entry.get("rule_id") or "").strip()
        citation_part = f" | {citation}" if citation else ""
        print(f"{title}{citation_part} | rule {rule_id}")
    return 0


def _cmd_clear_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    cache.clear()
    print(f"Cleared Research Cache: {cache.root}")
    return 0


def _cmd_show_research_sets(_args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    research_sets = library.list_research_sets()
    if not research_sets:
        print("No saved research sets.")
        return 0
    for research_set in research_sets:
        print(
            f"{research_set.name} | id {research_set.set_id} | "
            f"{research_set.item_count} authorities "
            f"({research_set.case_count} cases, {research_set.statute_count} statutes, "
            f"{research_set.rule_count} rules) | updated {research_set.updated_at}"
        )
    return 0


def _cmd_save_research_set(args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    cache = JsonCache.default()
    research_set = library.save_research_set(args.name, cache, replace=args.replace)
    print(f"Saved research set: {research_set.name} ({research_set.item_count} authorities)")
    return 0


def _cmd_load_research_set(args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    cache = JsonCache.default()
    research_set = library.load_research_set_into_cache(args.name_or_id, cache)
    print(f"Loaded research set: {research_set.name} ({research_set.item_count} authorities)")
    return 0


def _cmd_cache_dir(_args: argparse.Namespace) -> int:
    print(JsonCache.default().root)
    return 0


def _cmd_library_db(_args: argparse.Namespace) -> int:
    print(CaseLibrary.default().path)
    return 0


def _print_prune_candidate(candidate: LibraryPruneCandidate) -> None:
    citation = candidate.official_citation or candidate.citation_text
    citation_part = f" | {citation}" if citation else ""
    reason_part = f" | {candidate.reason}" if candidate.reason else ""
    print(
        f"{candidate.title}{citation_part} | cluster {candidate.cluster_id} "
        f"| {candidate.opinion_count} opinion(s) | {candidate.marker_count} marker(s)"
        f"{reason_part}"
    )


def _cmd_prune_library(args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    if args.apply:
        result = library.prune_ineligible_official_pagination(create_backup=True)
        print(
            f"Pruned {len(result.pruned)} ineligible library case(s); "
            f"kept {result.kept_count} eligible case(s)."
        )
        if result.backup_path is not None:
            print(f"Backup: {result.backup_path}")
        return 0
    candidates = library.official_pagination_audit()
    ineligible = [candidate for candidate in candidates if not candidate.eligible]
    print(
        f"Dry run: {len(ineligible)} ineligible library case(s); "
        f"{len(candidates) - len(ineligible)} eligible case(s)."
    )
    for candidate in ineligible:
        _print_prune_candidate(candidate)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-law-lens")
    parser.add_argument(
        "--list-cli-commands",
        action="store_true",
        help="print available CLI authority commands and examples",
    )
    subparsers = parser.add_subparsers(dest="command")

    app_parser = subparsers.add_parser("app", help="launch the GTK app")
    app_parser.add_argument(
        "--open-authority",
        help=argparse.SUPPRESS,
    )
    app_parser.set_defaults(func=_cmd_app)

    lookup_parser = subparsers.add_parser("lookup-citation", help="look up a case citation")
    lookup_parser.add_argument("citation")
    lookup_parser.add_argument("--refresh", action="store_true", help="bypass cached lookup data")
    lookup_parser.add_argument("--text", action="store_true", help="print first matching opinion text")
    lookup_parser.set_defaults(func=_cmd_lookup)

    extract_parser = subparsers.add_parser("extract", help="detect and extract the first authority")
    extract_parser.add_argument("value")
    extract_parser.add_argument("--refresh", action="store_true", help="bypass saved lookup data where possible")
    extract_parser.add_argument("--text", action="store_true", help="print raw authority text")
    extract_parser.set_defaults(func=_cmd_extract)

    extract_case_parser = subparsers.add_parser("extract-case", help="extract a case")
    extract_case_parser.add_argument("value")
    extract_case_parser.add_argument("--refresh", action="store_true", help="bypass saved lookup data where possible")
    extract_case_parser.add_argument("--text", action="store_true", help="print raw case text")
    extract_case_parser.set_defaults(func=_cmd_extract_case)

    extract_statute_parser = subparsers.add_parser("extract-statute", help="extract a California statute")
    extract_statute_parser.add_argument("value")
    extract_statute_parser.add_argument("--refresh", action="store_true", help="accepted for compatibility")
    extract_statute_parser.add_argument("--text", action="store_true", help="print raw statute text")
    extract_statute_parser.set_defaults(func=_cmd_extract_statute)

    extract_rule_parser = subparsers.add_parser("extract-rule", help="extract a California Rule of Court")
    extract_rule_parser.add_argument("value")
    extract_rule_parser.add_argument("--refresh", action="store_true", help="accepted for compatibility")
    extract_rule_parser.add_argument("--text", action="store_true", help="print raw rule text")
    extract_rule_parser.set_defaults(func=_cmd_extract_rule)

    open_parser = subparsers.add_parser("open", help="open an authority in the GTK app")
    open_parser.add_argument("value")
    open_parser.set_defaults(func=_cmd_open)

    open_selected_parser = subparsers.add_parser(
        "open-selected",
        help="open the authority from OS selection or clipboard in the GTK app",
    )
    open_selected_parser.set_defaults(func=_cmd_open_selected)

    commands_parser = subparsers.add_parser("commands", help="list available CLI authority commands")
    commands_parser.set_defaults(func=_cmd_commands)

    statute_parser = subparsers.add_parser("lookup-statute", help="look up a California statute")
    statute_parser.add_argument("citation")
    statute_parser.add_argument("--refresh", action="store_true", help="accepted for compatibility")
    statute_parser.add_argument("--text", action="store_true", help="print statute text")
    statute_parser.set_defaults(func=_cmd_lookup_statute)

    rule_parser = subparsers.add_parser("lookup-rule", help="look up a California Rule of Court")
    rule_parser.add_argument("citation")
    rule_parser.add_argument("--refresh", action="store_true", help="accepted for compatibility")
    rule_parser.add_argument("--text", action="store_true", help="print rule text")
    rule_parser.set_defaults(func=_cmd_lookup_rule)

    library_parser = subparsers.add_parser("show-library", help="list saved library authorities")
    library_parser.set_defaults(func=_cmd_show_library)

    cache_parser = subparsers.add_parser("show-cache", help="list Research Cache authorities")
    cache_parser.set_defaults(func=_cmd_show_cache)

    clear_cache_parser = subparsers.add_parser("clear-cache", help="delete Research Cache data")
    clear_cache_parser.set_defaults(func=_cmd_clear_cache)

    show_research_sets_parser = subparsers.add_parser(
        "show-research-sets",
        help="list saved named Research Cache sets",
    )
    show_research_sets_parser.set_defaults(func=_cmd_show_research_sets)

    save_research_set_parser = subparsers.add_parser(
        "save-research-set",
        help="save the current Research Cache as a named set",
    )
    save_research_set_parser.add_argument("name")
    save_research_set_parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing research set with the same name",
    )
    save_research_set_parser.set_defaults(func=_cmd_save_research_set)

    load_research_set_parser = subparsers.add_parser(
        "load-research-set",
        help="replace the Research Cache with a saved research set",
    )
    load_research_set_parser.add_argument("name_or_id")
    load_research_set_parser.set_defaults(func=_cmd_load_research_set)

    cache_dir_parser = subparsers.add_parser("cache-dir", help="print the cache directory")
    cache_dir_parser.set_defaults(func=_cmd_cache_dir)

    library_db_parser = subparsers.add_parser("library-db", help="print the library database path")
    library_db_parser.set_defaults(func=_cmd_library_db)

    prune_library_parser = subparsers.add_parser(
        "prune-library",
        help="remove durable library cases that lack official reporter pagination",
    )
    prune_library_mode = prune_library_parser.add_mutually_exclusive_group()
    prune_library_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="list ineligible library cases without changing the database",
    )
    prune_library_mode.add_argument(
        "--apply",
        action="store_true",
        help="back up the database and remove ineligible library cases",
    )
    prune_library_parser.set_defaults(func=_cmd_prune_library)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_cli_commands:
        print(build_cli_commands_text(), end="")
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except (CourtListenerError, LegInfoError, CaliforniaRulesError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
