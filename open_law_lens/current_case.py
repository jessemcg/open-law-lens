from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


CURRENT_CASE_FILE = Path(
    "/home/jesse/Dropbox/MCGLAW/config_files/scripts/misc/currently_selected_case"
)
OPEN_CASES_ROOT = Path("/home/jesse/Dropbox/MCGLAW/OPEN_CASES")
CLOSED_CASES_ROOT = Path("/home/jesse/Dropbox/MCGLAW/CLOSED_CASES")
CASE_NUMBER_RE = re.compile(r"[BDGE]\d{6}")


class CurrentCaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class CurrentCaseSocf:
    case_name: str
    case_dir: Path
    path: Path


def clean_case_name(case_name: str) -> str:
    cleaned = case_name.replace("\r", "").strip()
    if not cleaned:
        raise CurrentCaseError("Current case is empty.")
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise CurrentCaseError(f"Invalid current case name: {case_name!r}")
    return cleaned


def normalize_root(root: Path) -> Path:
    return Path(os.path.normpath(str(root))).expanduser()


def read_current_case(case_file: Path = CURRENT_CASE_FILE) -> str:
    if not case_file.is_file():
        raise CurrentCaseError(f"Current case file not found: {case_file}")
    return clean_case_name(case_file.read_text(encoding="utf-8"))


def resolve_case_dir(
    case_name: str,
    roots: list[Path] | None = None,
) -> Path:
    roots = roots or [OPEN_CASES_ROOT, CLOSED_CASES_ROOT]
    cleaned = clean_case_name(case_name)
    for root in roots:
        target = normalize_root(root) / cleaned
        if target.is_dir():
            return target.resolve(strict=False)
    roots_text = ", ".join(str(root) for root in roots)
    raise CurrentCaseError(f"Selected case {cleaned!r} not found in {roots_text}.")


def case_number_from_case_dir(case_dir: Path) -> str:
    match = CASE_NUMBER_RE.search(case_dir.name)
    if match is None:
        match = CASE_NUMBER_RE.search(str(case_dir))
    if match is None:
        raise CurrentCaseError(f"Unable to infer case number from case directory: {case_dir}")
    return match.group(0)


def find_socf_odt(case_dir: Path) -> Path:
    case_number = case_number_from_case_dir(case_dir)
    socf_dir = case_dir / "SOCF"
    if not socf_dir.is_dir():
        raise CurrentCaseError(f"SOCF directory not found: {socf_dir}")
    matches = sorted(
        path
        for path in socf_dir.glob(f"{case_number}_SOCF_*.odt")
        if path.is_file()
    )
    if not matches:
        raise CurrentCaseError(f"SOCF ODT not found in {socf_dir}")
    return matches[0].resolve(strict=False)


def current_case_socf_odt(
    *,
    case_file: Path = CURRENT_CASE_FILE,
    roots: list[Path] | None = None,
) -> Path:
    return current_case_socf(case_file=case_file, roots=roots).path


def current_case_socf(
    *,
    case_file: Path = CURRENT_CASE_FILE,
    roots: list[Path] | None = None,
) -> CurrentCaseSocf:
    case_name = read_current_case(case_file)
    case_dir = resolve_case_dir(case_name, roots)
    return CurrentCaseSocf(
        case_name=case_name,
        case_dir=case_dir,
        path=find_socf_odt(case_dir),
    )
