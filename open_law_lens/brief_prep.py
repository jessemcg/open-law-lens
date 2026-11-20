"""Read-only case discovery and private evidence staging for Brief Prep."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .source_artifacts import export_source_artifacts


@dataclass(frozen=True)
class Variant:
    label: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()


VARIANTS = {
    "reply": Variant("Reply Brief Prep", ("aob", "rb")),
    "respondent": Variant("Respondent’s Brief Prep", ("aob",)),
    "opposition": Variant("Opposition to Dismissal", ("mtd",), ("aob",)),
}
ROLES = {"aob": "appellant’s opening brief", "rb": "respondent’s brief",
         "mtd": "respondent’s motion to dismiss"}
CASE_NUMBER = re.compile(r"\b[A-H]\d{6}\b", re.I)
COVER_CASE = re.compile(r"\b([A-H])\s*[- ]?\s*(\d{6})\b", re.I)
ROLE_PATTERNS = {
    "aob": r"appellant(?:s|['’]s|s['’])?\s+opening\s+brief|opening\s+brief\s+(?:of|for)\s+(?:the\s+)?appellants?",
    "rb": r"respondent(?:s|['’]s|s['’])?\s+(?:answer(?:ing)?\s+)?brief|brief\s+(?:of|for)\s+(?:the\s+)?respondents?",
    "mtd": r"respondent(?:s|['’]s|s['’])?\s+(?:notice of\s+)?motion\s+to\s+dismiss(?:\s+(?:the\s+)?appeal)?",
}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
MAX_PDF_BYTES = 128 * 1024 * 1024
MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 128 * 1024 * 1024
MAX_PDFS = 1000


class PrepError(ValueError):
    pass


@dataclass(frozen=True)
class PrepProvenance:
    kind: str
    case_number: str

    def __post_init__(self) -> None:
        if self.kind not in VARIANTS or not CASE_NUMBER.fullmatch(self.case_number) or not self.case_number.isupper():
            raise PrepError("Invalid Brief Prep provenance.")

    @property
    def label(self) -> str:
        return f"{self.case_number} · {VARIANTS[self.kind].label}"

    def payload(self) -> dict[str, str]:
        return {"kind": self.kind, "case_number": self.case_number}

    @classmethod
    def from_payload(cls, value: object) -> PrepProvenance | None:
        if isinstance(value, dict):
            kind, case = value.get("kind"), value.get("case_number")
            if isinstance(kind, str) and isinstance(case, str):
                try:
                    return cls(kind, case)
                except PrepError:
                    pass
        return None


@contextmanager
def _directory(base: int | None, path: Path) -> Iterator[int]:
    fd = os.open("/", DIR_FLAGS) if base is None else os.dup(base)
    try:
        for part in (path.parts[1:] if base is None else path.parts):
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@dataclass(frozen=True)
class CaseRoot:
    path: Path
    identity: tuple[int, int]

    @contextmanager
    def open(self) -> Iterator[int]:
        with _directory(None, self.path) as fd:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) != self.identity:
                raise PrepError("The selected case folder changed. Request Brief Prep again.")
            yield fd


def validate_case_root(value: str | Path) -> CaseRoot:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or len(path.parts) < 2 or path.anchor != "/":
        raise PrepError("Choose an absolute case folder without parent traversal.")
    try:
        with _directory(None, path) as fd:
            st = os.fstat(fd)
    except OSError as exc:
        raise PrepError("The selected case folder is unavailable or contains a symbolic link.") from exc
    return CaseRoot(path, (st.st_dev, st.st_ino))


def _confined(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise PrepError("Invalid relative evidence path.")
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PrepError("Invalid relative evidence path.")
    return path


@contextmanager
def _file(parent: int, path: Path, limit: int):
    path = _confined(path.as_posix())
    with _directory(parent, path.parent) as directory:
        fd = os.open(path.name, FILE_FLAGS, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            st = os.fstat(handle.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
                raise PrepError("Evidence is not a bounded, regular case file.")
            yield handle


def _read(parent: int, path: Path, limit: int) -> str:
    with _file(parent, path, limit) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise PrepError("Evidence exceeds the text limit.")
    return data.decode("utf-8")


def _pdf_command(pdf: Path, *args: str) -> str:
    cmd = ["pdftotext", "-layout", "-enc", "UTF-8", *args, str(pdf), "-"]
    with tempfile.TemporaryFile(dir=pdf.parent) as output:
        subprocess.run(cmd, stdout=output, stderr=subprocess.DEVNULL, check=True, timeout=90)
        output.seek(0)
        data = output.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise PrepError("The filing exceeds the extracted text limit.")
    return data.decode("utf-8")


def _pages(text: str) -> list[str]:
    pages = text.split("\f")
    return pages[:-1] if pages and pages[-1] == "" else pages


def _scanned_sheets(pdf: Path, text: str) -> set[int]:
    pages = _pages(text)
    sparse = {i for i, page in enumerate(pages) if sum(c.isalnum() for c in page) < 20}
    if not sparse:
        return set()
    result = subprocess.run(["pdfimages", "-list", str(pdf)], capture_output=True,
                            check=True, text=True, timeout=30)
    scanned = set()
    for line in result.stdout.splitlines()[2:]:
        fields = line.split()
        if len(fields) >= 5 and fields[0].isdigit() and int(fields[0]) - 1 in sparse:
            if fields[2] == "image" and min(int(fields[3]), int(fields[4])) >= 350:
                scanned.add(int(fields[0]) - 1)
    return scanned


def _fill_scanned_sheets(pdf: Path, native_text: str, scanned: set[int]) -> str:
    native, recovered = _pages(native_text), _pages(_local_ocr(pdf))
    if len(native) != len(recovered) or any(not recovered[index].strip() for index in scanned):
        raise PrepError("Local OCR did not recover every scanned sheet. Provide a searchable PDF copy.")
    return "".join((recovered[index] if index in scanned else text) + "\f"
                   for index, text in enumerate(native))


def _local_ocr(pdf: Path) -> str:
    # Maintained provisioning only. A standalone checkout need not have this sibling.
    helper = Path(__file__).resolve().parents[2] / "UvEnvironments" / "project-env"
    unavailable = PrepError("Local LightOnOCR is unavailable or failed. Provide a searchable PDF copy.")
    if not shutil.which("nvidia-smi") or not helper.is_file():
        raise unavailable
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    lock = state / "pi-lightonocr" / "ocr.lock"
    args = [str(helper), "run", "LightOnOCR"]
    try:
        status = subprocess.run(
            [*args, "python", "-B", "-m", "lightonocr.diagnostics", "status", str(lock)],
            capture_output=True, check=True, timeout=15,
        )
        if json.loads(status.stdout).get("available") is not True:
            raise unavailable
        env = {**os.environ, "LIGHTONOCR_SUPERVISED": "1"}
        with subprocess.Popen([*args, "lightonocr", str(pdf), "--page-breaks"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env=env, start_new_session=True) as process:
            try:
                code = process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                raise unavailable
        if code:
            raise unavailable
        with pdf.with_suffix(".txt").open("rb") as handle:
            data = handle.read(MAX_TEXT_BYTES + 1)
        if len(data) > MAX_TEXT_BYTES or not data.strip() or not data.endswith(b"\f"):
            raise unavailable
        return data.decode("utf-8")
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError) as exc:
        raise unavailable from exc


def _cover(text: str) -> tuple[str, str] | None:
    # Limit corroboration to front matter (not citations in the argument).
    pages = _pages(text)
    for page in pages[:2]:
        if re.search(r"\b(?:TABLE OF (?:CONTENTS|AUTHORITIES)|ARGUMENT\s*$)\b", page, re.I | re.M):
            break
        compact = " ".join(page.split())[:5500]
        numbers = {a.upper() + b for a, b in COVER_CASE.findall(compact)}
        if len(numbers) != 1:
            continue
        if re.search(r"\b(?:draft|not for filing|sample|proposed order)\b", compact, re.I):
            continue
        # A reference to a brief in a court notice is not the filing's title.
        # Keep titles on their own line(s), while allowing normal PDF line wraps.
        lines = [" ".join(line.split()) for line in page[:8000].splitlines()]
        headings = [line for line in lines if line]
        headings.extend(f"{first} {second}" for first, second in zip(lines, lines[1:]) if first and second)

        def has_title(pattern: str) -> bool:
            return any(re.fullmatch(rf"(?:amended\s+|corrected\s+)?(?:{pattern})", title, re.I)
                       for title in headings)

        roles = {role for role, pattern in ROLE_PATTERNS.items() if has_title(pattern)}
        for role, title, party in (("aob", "opening brief", "appellants?"),
                                   ("rb", "responding brief", "respondents?"),
                                   ("mtd", r"motion to dismiss(?: the)? appeal", "respondents?")):
            if (has_title(title)
                    and re.search(rf"\b(?:attorneys?|counsel) for (?:the )?{party}\b", compact, re.I)):
                roles.add(role)
        if "mtd" in roles and re.search(
                r"\bappellant['’]s motion\b|\b(?:attorneys?|counsel) for (?:the )?appellants?\b", compact, re.I):
            continue
        if len(roles) == 1 and not re.search(
                r"\b(?:reply brief|petition for rehearing|request for extension|joinder|proof of service only|"
                r"(?:opposition|response|reply)\s+(?:in support of|to))\b", compact, re.I):
            return next(iter(roles)), next(iter(numbers))
    return None


def _hints(path: Path) -> set[str]:
    name = re.sub(r"[_-]+", " ", path.stem.lower())
    patterns = {"aob": r"\baob\b|opening", "rb": r"\brb\b|respondent.*brief", "mtd": r"dismiss|\bmtd\b"}
    return {role for role, pattern in patterns.items() if re.search(pattern, name)}


def _draft(path: Path) -> bool:
    return bool(re.search(r"(?:^|[ /_.-])(?:draft\w*|working|template|sample)(?:$|[ /_.-])",
                          path.as_posix(), re.I))


def _rank(path: Path, cover: str) -> tuple[bool, bool]:
    archive = bool(re.search(r"(?:^|/)(?:archive\w*|old(?:[ _-].*)?|copies|prep|backups)(?:/|$)",
                             path.parent.as_posix(), re.I))
    filed = bool(re.search(r"\belectronically filed\b|\bfiled on\b", cover, re.I) or re.search(
        r"(?:^|[ /_.-])(?:filed|conformed|accepted)(?:$|[ /_.-])", path.as_posix(), re.I))
    return (not archive, filed)


@dataclass(frozen=True)
class Filing:
    role: str
    case_number: str
    path: Path
    text: str
    ocr: bool
    rank: tuple[bool, bool]


@dataclass(frozen=True)
class Discovery:
    provenance: PrepProvenance
    choices: dict[str, tuple[Filing, ...]]
    optional_warning: str


def _inspect(root: int, relative: Path, work: Path, roles: set[str], allow_ocr: bool,
             expected: str | None) -> Filing | None:
    with tempfile.TemporaryDirectory(prefix="filing-", dir=work) as temp:
        pdf = Path(temp) / "filing.pdf"
        with _file(root, relative, MAX_PDF_BYTES) as source, pdf.open("xb") as dest:
            size = 0
            while data := source.read(1024 * 1024):
                size += len(data)
                if size > MAX_PDF_BYTES:
                    raise PrepError("Filing PDF exceeds the size limit.")
                dest.write(data)
        cover = _pdf_command(pdf, "-l", "2")
        identity = _cover(cover)
        ocr = False
        if identity is None and _hints(relative) & roles and _scanned_sheets(pdf, cover):
            if not allow_ocr:
                raise PrepError("The cover is scanned. Provide a searchable PDF copy or enable local OCR.")
            native = _pdf_command(pdf)
            cover = _fill_scanned_sheets(pdf, native, _scanned_sheets(pdf, native))
            identity = _cover(cover)
            ocr = True
        if identity is None or identity[0] not in roles:
            return None
        role, case_number = identity
        if expected and case_number != expected:
            raise PrepError(f"Cover identifies a different appeal ({case_number}).")
        text = cover if ocr else _pdf_command(pdf)
        if not ocr and (scanned := _scanned_sheets(pdf, text)):
            if not allow_ocr:
                raise PrepError("Some filing sheets are scanned. Provide a searchable PDF copy or enable local OCR.")
            text = _fill_scanned_sheets(pdf, text, scanned)
            ocr = True
        if not text.strip() or not text.endswith("\f"):
            raise PrepError("Full filing text could not be extracted with page boundaries.")
        return Filing(role, case_number, relative, text, ocr, _rank(relative, " ".join(cover[:5500].split())))


def discover(case: CaseRoot, kind: str, workspace: Path, *, allow_ocr: bool = False) -> Discovery:
    variant = VARIANTS[kind]
    roles = variant.required + variant.optional
    root_numbers = {n.upper() for n in CASE_NUMBER.findall(case.path.name.replace("_", " "))}
    if len(root_numbers) > 1:
        raise PrepError("The selected folder names more than one appeal. Choose a single case folder.")
    expected = next(iter(root_numbers), None)
    filings: list[Filing] = []
    issues: dict[str, list[str]] = {role: [] for role in roles}
    count = total_text = 0
    if not shutil.which("pdftotext") or not shutil.which("pdfimages"):
        raise PrepError("Brief Prep requires Poppler’s pdftotext and pdfimages commands.")
    with case.open() as fd:
        for base, dirs, names, _walk_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False):
            parent = Path(base)
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and parent / d != Path("0_record/case_bundle"))
            for name in sorted(names):
                relative = parent / name
                if relative.suffix.lower() != ".pdf" or name.startswith(".") or _draft(relative):
                    continue
                count += 1
                if count > MAX_PDFS:
                    raise PrepError("Too many PDFs in this folder. Choose a narrower case folder.")
                hints = _hints(relative) & set(roles)
                try:
                    filing = _inspect(fd, relative, workspace, set(roles), allow_ocr, expected)
                    if filing is not None:
                        filings.append(filing)
                        total_text += len(filing.text.encode("utf-8"))
                    elif hints:
                        raise PrepError("The cover does not corroborate the required filing type, party role and case number.")
                except (OSError, UnicodeError, PrepError, subprocess.SubprocessError) as exc:
                    reason = str(exc) if isinstance(exc, PrepError) else "Unreadable PDF or text extraction failed."
                    for role in hints:
                        issues[role].append(f"{relative}: {reason}")
                if total_text > 2 * MAX_TEXT_BYTES:
                    raise PrepError("Too much candidate filing text. Choose a narrower case folder.")
    numbers = {f.case_number for f in filings if f.role in variant.required}
    if expected is None and len(numbers) > 1:
        raise PrepError("Filing covers identify different appeals. Choose a folder for one appeal.")
    number = expected or next(iter(numbers), None)
    choices: dict[str, tuple[Filing, ...]] = {}
    warning = ""
    for role in roles:
        candidates = [f for f in filings if f.role == role and f.case_number == number]
        if not candidates:
            detail = "\n" + "\n".join(issues[role][:4]) if issues[role] else ""
            if role in variant.required:
                raise PrepError(f"Brief Prep needs the {ROLES[role]} for this appeal. No verified filing found.{detail}")
            warning = f"Optional {ROLES[role]} was not verified or available; proceed without it."
            continue
        best = max(f.rank for f in candidates)
        unique = {}
        for f in sorted(candidates, key=lambda f: (len(f.path.parts), f.path.as_posix().casefold())):
            if f.rank == best:
                unique.setdefault(hashlib.sha256(f.text.encode("utf-8")).digest(), f)
        choices[role] = tuple(unique.values())
    assert number is not None  # Every variant requires a corroborated cover.
    return Discovery(PrepProvenance(kind, number), choices, warning)


_RECORD_FILES = {
    "transcript_page_numbers": "artifacts/transcript_page_numbers.json",
    "transcript_page_number_series": "artifacts/transcript_page_number_series.md",
    "toc": "artifacts/toc.txt",
    "hearing_boundaries": "artifacts/hearing_boundaries.json",
    "report_boundaries": "artifacts/report_boundaries.json",
    **{key: f"artifacts/{key}.txt" for key in (
        "raw_hearings", "optimized_hearings", "raw_reports", "optimized_reports",
    )},
}
_PAGE_NAME = re.compile(r"\d{4,7}\.txt\Z")
_LABEL = re.compile(r"(?:\d+)?(?:A|S)?(?:RT|CT) \d+|(?:\d+)?AR \d+")


def _record_input(fd: int, value: object, default: str, *, allowed: tuple[str, ...]) -> str:
    for candidate in dict.fromkeys((value if isinstance(value, str) else default, default)):
        try:
            path = _confined(candidate)
            if path.name not in allowed or path.parts[0] != "artifacts":
                continue
            return _read(fd, path, 24 * 1024 * 1024)
        except (OSError, ValueError):
            continue
    return ""


def _stage_record(fd: int, workspace: Path) -> dict:
    dest = workspace / "record"
    dest.mkdir(mode=0o700)
    try:
        raw = json.loads(_read(fd, Path("manifest.json"), 2 * 1024 * 1024))
        config = raw.get("files", {}) if isinstance(raw, dict) else {}
        if not isinstance(config, dict):
            config = {}
    except (OSError, ValueError):
        config = {}
    artifacts = {}
    for key, default in _RECORD_FILES.items():
        value = config.get(key)
        # Same-purpose names only; never expose config or arbitrary manifest paths.
        text = _record_input(fd, value, default, allowed=(Path(default).name,))
        if text:
            artifacts[key] = text
    page_map = artifacts.pop("transcript_page_numbers", "")
    sources = {}
    for key, text in artifacts.items():
        exported = export_source_artifacts({"text": text}, dest / key, workspace=workspace)
        sources[key] = str(Path(exported["manifest_path"]).relative_to(workspace))
    page_dir = dest / "text_pages"
    page_dir.mkdir(mode=0o700)
    available: set[str] = set()
    size = omitted = 0
    try:
        with _directory(fd, Path("text_pages")) as pages_fd:
            for name in sorted(os.listdir(pages_fd)):
                if not _PAGE_NAME.fullmatch(name):
                    continue
                try:
                    text = _read(pages_fd, Path(name), 512 * 1024)
                    byte_count = len(text.encode("utf-8"))
                    if not text.strip() or size + byte_count > MAX_RECORD_BYTES or len(available) >= 16000:
                        omitted += 1
                        continue
                    (page_dir / name).write_text(text, encoding="utf-8")
                    available.add(name)
                    size += byte_count
                except (OSError, ValueError):
                    omitted += 1
    except OSError:
        pass
    entries = []
    try:
        raw_map = json.loads(page_map)
        if (isinstance(raw_map, dict) and raw_map.get("schema_version") == 2
                and isinstance(raw_map.get("entries"), list)):
            entries = [entry for entry in raw_map["entries"] if isinstance(entry, dict)]
    except ValueError:
        pass
    labels = Counter(e.get("citation_label") for e in entries if isinstance(e.get("citation_label"), str))
    files = Counter(e.get("file_name") for e in entries if isinstance(e.get("file_name"), str))
    verified = []
    for entry in entries:
        label, name = entry.get("citation_label"), entry.get("file_name")
        if (entry.get("status") == "selected" and entry.get("confidence") not in ("low", "ambiguous")
                and isinstance(label, str) and _LABEL.fullmatch(label)
                and isinstance(name, str) and name in available and labels[label] == files[name] == 1):
            verified.append(f"{label}\ttext_pages/{name}\n")
    if verified:
        exported = export_source_artifacts({"text": "".join(verified), "schema_version": 2,
                                            "columns": ["citation_label", "path relative to record/"]},
                                           dest / "selected_page_map", workspace=workspace)
        sources["selected_page_map"] = str(Path(exported["manifest_path"]).relative_to(workspace))
    return {"sources": sources, "text_pages": "record/text_pages/" if available else None,
            "page_count": len(available), "unmapped_or_ambiguous_pages": max(len(entries), len(available)) - len(verified),
            "omitted_text_pages": omitted}


def stage_evidence(case: CaseRoot, discovery: Discovery, chosen: dict[str, Filing], workspace: Path) -> Path:
    files = []
    for role, options in discovery.choices.items():
        selected = chosen.get(role)
        if not any(selected is option for option in options):
            raise PrepError(f"Select a verified {ROLES[role]} from this appeal.")
        assert selected is not None
        artifact = export_source_artifacts(
            {"text": selected.text, "case_relative_path": selected.path.as_posix(), "ocr": selected.ocr,
             "page_boundary": "form feed (U+000C) separates PDF sheets, not verified pinpoints"},
            workspace / role, workspace=workspace,
        )
        files.append({"role": role, "source": selected.path.as_posix(), "ocr": selected.ocr,
                      "parts": str(Path(artifact["manifest_path"]).relative_to(workspace))})
    record: dict = {"note": "No confined record bundle was available. Do not claim record verification."}
    with case.open() as root, ExitStack() as directories:
        try:
            fd = directories.enter_context(_directory(root, Path("0_record/case_bundle")))
        except OSError:
            pass  # Missing, unreadable or linked optional record bundle.
        else:
            record = _stage_record(fd, workspace)
    manifest = workspace / "brief-prep-manifest.json"
    manifest.write_text(json.dumps({**discovery.provenance.payload(), "filings": files,
                                    "context_note": discovery.optional_warning, "record": record},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
