from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


class FactPatternError(RuntimeError):
    pass


@dataclass(frozen=True)
class FactPatternExport:
    source_path: Path
    source_copy_path: Path
    text_path: Path
    text: str


ODT_TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _clean_extracted_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    clean_lines: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if not previous_blank and clean_lines:
                clean_lines.append("")
            previous_blank = True
            continue
        clean_lines.append(line)
        previous_blank = False
    return "\n".join(clean_lines).strip()


def extract_odt_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            content = archive.read("content.xml")
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise FactPatternError(f"Could not read ODT text: {exc}") from exc
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise FactPatternError(f"Could not parse ODT text: {exc}") from exc
    paragraphs: list[str] = []
    for element in root.iter():
        if element.tag not in {f"{ODT_TEXT_NS}p", f"{ODT_TEXT_NS}h"}:
            continue
        text = "".join(element.itertext()).strip()
        if text:
            paragraphs.append(text)
    return _clean_extracted_text("\n\n".join(paragraphs))


def extract_pdf_text(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise FactPatternError("PDF extraction requires the pdftotext command.")
    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FactPatternError(f"Could not extract PDF text: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "pdftotext failed").strip()
        raise FactPatternError(f"Could not extract PDF text: {message}")
    return _clean_extracted_text(completed.stdout)


def extract_fact_pattern_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".odt":
        text = extract_odt_text(path)
    elif suffix == ".pdf":
        text = extract_pdf_text(path)
    else:
        raise FactPatternError("Fact pattern must be an ODT or PDF file.")
    if not text:
        raise FactPatternError("No extractable fact-pattern text was found.")
    return text


def export_fact_pattern(path: Path, output_dir: Path) -> FactPatternExport:
    source_path = path.expanduser()
    if not source_path.is_file():
        raise FactPatternError(f"Fact-pattern file not found: {source_path}")
    text = extract_fact_pattern_text(source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_copy_path = output_dir / source_path.name
    if source_path.resolve() != source_copy_path.resolve():
        shutil.copy2(source_path, source_copy_path)
    text_path = output_dir / f"{source_path.stem}_extracted.txt"
    text_path.write_text(text + "\n", encoding="utf-8")
    return FactPatternExport(
        source_path=source_path,
        source_copy_path=source_copy_path,
        text_path=text_path,
        text=text,
    )
