from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .cache import JsonCache
from .client import CourtListenerClient, CourtListenerError, opinion_text


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
        text = opinion_text(opinion)
        if text:
            print(text)
            return 0
    print("No opinion text found for first matching cluster.", file=sys.stderr)
    return 1


def _cmd_show_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    entries = cache.list_case_entries()
    if not entries:
        print("No cached cases.")
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


def _cmd_clear_cache(_args: argparse.Namespace) -> int:
    cache = JsonCache.default()
    cache.clear()
    print(f"Cleared cache: {cache.root}")
    return 0


def _cmd_cache_dir(_args: argparse.Namespace) -> int:
    print(JsonCache.default().root)
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

    cache_parser = subparsers.add_parser("show-cache", help="list cached cases")
    cache_parser.set_defaults(func=_cmd_show_cache)

    clear_cache_parser = subparsers.add_parser("clear-cache", help="delete cached case data")
    clear_cache_parser.set_defaults(func=_cmd_clear_cache)

    cache_dir_parser = subparsers.add_parser("cache-dir", help="print the cache directory")
    cache_dir_parser.set_defaults(func=_cmd_cache_dir)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (CourtListenerError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
