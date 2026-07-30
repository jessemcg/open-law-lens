from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree


class FactPatternError(RuntimeError):
    pass


@dataclass(frozen=True)
class FactPatternExport:
    source_path: Path
    source_copy_path: Path
    text_path: Path
    text: str


@dataclass(frozen=True)
class FactPatternHeading:
    level: int
    text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class FactPatternDocument:
    text: str
    headings: tuple[FactPatternHeading, ...] = ()


ODT_TEXT_URI = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODT_STYLE_URI = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
ODT_TEXT_NS = f"{{{ODT_TEXT_URI}}}"
ODT_STYLE_NS = f"{{{ODT_STYLE_URI}}}"
ODT_TEXT_PARAGRAPH = f"{ODT_TEXT_NS}p"
ODT_TEXT_HEADING = f"{ODT_TEXT_NS}h"
ODT_TEXT_STYLE_NAME = f"{ODT_TEXT_NS}style-name"
ODT_TEXT_OUTLINE_LEVEL = f"{ODT_TEXT_NS}outline-level"
ODT_STYLE_STYLE = f"{ODT_STYLE_NS}style"
ODT_STYLE_NAME = f"{ODT_STYLE_NS}name"
ODT_STYLE_DISPLAY_NAME = f"{ODT_STYLE_NS}display-name"
ODT_STYLE_PARENT_NAME = f"{ODT_STYLE_NS}parent-style-name"
ODT_HEADING_STYLE_RE = re.compile(
    r"^Heading(?:\s+|_20_)(10|[1-9])$",
    re.IGNORECASE,
)


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


def _heading_level(value: str) -> int | None:
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level if 1 <= level <= 10 else None


def _odt_styles(
    content_root: ElementTree.Element,
    styles_content: bytes | None,
) -> dict[str, tuple[str, str]]:
    roots = [content_root]
    if styles_content:
        try:
            roots.append(ElementTree.fromstring(styles_content))
        except ElementTree.ParseError:
            pass
    styles: dict[str, tuple[str, str]] = {}
    for root in roots:
        for element in root.iter(ODT_STYLE_STYLE):
            name = element.get(ODT_STYLE_NAME, "").strip()
            if not name:
                continue
            styles[name] = (
                element.get(ODT_STYLE_DISPLAY_NAME, "").strip(),
                element.get(ODT_STYLE_PARENT_NAME, "").strip(),
            )
    return styles


def _heading_level_from_style(
    style_name: str,
    styles: Mapping[str, tuple[str, str]],
) -> int | None:
    visited: set[str] = set()
    current = style_name
    while current and current not in visited:
        visited.add(current)
        display_name, parent_name = styles.get(current, ("", ""))
        for candidate in (display_name, current):
            match = ODT_HEADING_STYLE_RE.fullmatch(candidate.strip())
            if match is not None:
                return int(match.group(1))
        current = parent_name
    return None


def _element_heading_level(
    element: ElementTree.Element,
    styles: Mapping[str, tuple[str, str]],
) -> int | None:
    style_level = _heading_level_from_style(
        element.get(ODT_TEXT_STYLE_NAME, "").strip(),
        styles,
    )
    if element.tag == ODT_TEXT_HEADING:
        return (
            _heading_level(element.get(ODT_TEXT_OUTLINE_LEVEL, "").strip())
            or style_level
            or 1
        )
    return style_level


def extract_odt_document(path: Path) -> FactPatternDocument:
    try:
        with zipfile.ZipFile(path) as archive:
            content = archive.read("content.xml")
            try:
                styles_content = archive.read("styles.xml")
            except KeyError:
                styles_content = None
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise FactPatternError(f"Could not read ODT text: {exc}") from exc
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise FactPatternError(f"Could not parse ODT text: {exc}") from exc
    styles = _odt_styles(root, styles_content)
    parts: list[str] = []
    headings: list[FactPatternHeading] = []
    text_length = 0
    for element in root.iter():
        if element.tag not in {ODT_TEXT_PARAGRAPH, ODT_TEXT_HEADING}:
            continue
        paragraph = _clean_extracted_text("".join(element.itertext()).strip())
        if not paragraph:
            continue
        if parts:
            parts.append("\n\n")
            text_length += 2
        start_offset = text_length
        parts.append(paragraph)
        text_length += len(paragraph)
        level = _element_heading_level(element, styles)
        if level is not None:
            headings.append(
                FactPatternHeading(
                    level=level,
                    text=paragraph,
                    start_offset=start_offset,
                    end_offset=text_length,
                )
            )
    return FactPatternDocument(
        text="".join(parts),
        headings=tuple(headings),
    )


def extract_odt_text(path: Path) -> str:
    return extract_odt_document(path).text


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


def extract_fact_pattern_document(path: Path) -> FactPatternDocument:
    suffix = path.suffix.casefold()
    if suffix == ".odt":
        document = extract_odt_document(path)
    elif suffix == ".pdf":
        document = FactPatternDocument(text=extract_pdf_text(path))
    else:
        raise FactPatternError("Fact pattern must be an ODT or PDF file.")
    if not document.text:
        raise FactPatternError("No extractable fact-pattern text was found.")
    return document


def extract_fact_pattern_text(path: Path) -> str:
    return extract_fact_pattern_document(path).text


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
