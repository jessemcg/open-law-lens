from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .cache import JsonCache
from .client import CourtListenerClient, CourtListenerError
from .library import CaseLibrary, LibraryPruneCandidate
from .statutes import LegInfoError


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _cmd_app(_args: argparse.Namespace) -> int:
    from .app import main as app_main

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
    opinions = client.fetch_cluster_opinions(clusters[0], refresh=args.refresh)
    for opinion in opinions:
        text = client.opinion_display(opinion).text
        if text:
            print(text)
            return 0
    print("No opinion text found for first matching cluster.", file=sys.stderr)
    return 1


def _cmd_lookup_statute(args: argparse.Namespace) -> int:
    client = CourtListenerClient.default()
    statute = client.lookup_statute(args.citation, refresh=args.refresh)
    if args.text:
        print(str(statute.get("text") or ""))
        return 0
    _print_json(statute)
    return 0


def _cmd_show_library(_args: argparse.Namespace) -> int:
    library = CaseLibrary.default()
    entries = library.list_case_entries()
    statutes = library.list_statute_entries()
    if not entries and not statutes:
        print("No saved library authorities.")
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
    return 0


def _cmd_show_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    entries = cache.list_case_entries()
    statutes = cache.list_statute_entries()
    if not entries and not statutes:
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
    return 0


def _cmd_clear_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    cache.clear()
    print(f"Cleared Research Cache: {cache.root}")
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
    subparsers = parser.add_subparsers(dest="command", required=True)

    app_parser = subparsers.add_parser("app", help="launch the GTK app")
    app_parser.set_defaults(func=_cmd_app)

    lookup_parser = subparsers.add_parser("lookup-citation", help="look up a case citation")
    lookup_parser.add_argument("citation")
    lookup_parser.add_argument("--refresh", action="store_true", help="bypass cached lookup data")
    lookup_parser.add_argument("--text", action="store_true", help="print first matching opinion text")
    lookup_parser.set_defaults(func=_cmd_lookup)

    statute_parser = subparsers.add_parser("lookup-statute", help="look up a California statute")
    statute_parser.add_argument("citation")
    statute_parser.add_argument("--refresh", action="store_true", help="bypass saved statute data")
    statute_parser.add_argument("--text", action="store_true", help="print statute text")
    statute_parser.set_defaults(func=_cmd_lookup_statute)

    library_parser = subparsers.add_parser("show-library", help="list saved library authorities")
    library_parser.set_defaults(func=_cmd_show_library)

    cache_parser = subparsers.add_parser("show-cache", help="list Research Cache authorities")
    cache_parser.set_defaults(func=_cmd_show_cache)

    clear_cache_parser = subparsers.add_parser("clear-cache", help="delete Research Cache data")
    clear_cache_parser.set_defaults(func=_cmd_clear_cache)

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
    try:
        return int(args.func(args))
    except (CourtListenerError, LegInfoError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
