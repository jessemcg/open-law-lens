"""Conservative, source-independent styling hints for opinion text.

The inference in this module deliberately prefers missed headings to styled
body text.  Source-aware callers should still make the primary trust decision:
do not call the inference path for flattened PDF or ``<pre>`` opinion text.
They may pass trusted semantic spans (for example, spans derived from h2-h4
elements) without asking this module to infer additional structure.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DisplayStyleSpan:
    """A half-open range in display text that should receive a named style."""

    kind: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class _Paragraph:
    start_offset: int
    end_offset: int
    text: str


@dataclass(frozen=True)
class _OutlineCandidate:
    paragraph_index: int
    outline_kind: str
    value: int
    paragraph: _Paragraph
    independently_styled: bool = False


_PARAGRAPH_SEPARATOR_RE = re.compile(r"(?:\r?\n[ \t]*){2,}")
_LEADING_PAGE_MARKER_RE = re.compile(r"\[\*[^\]\r\n]+\][ \t]*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\N{RIGHT SINGLE QUOTATION MARK}-]*")

_CANONICAL_HEADINGS = {
    "analysis",
    "applicable law",
    "background",
    "conclusion",
    "contentions",
    "dependency context",
    "discussion",
    "disposition",
    "facts",
    "facts and procedural background",
    "facts and procedural history",
    "facts and proceedings",
    "facts and proceedings below",
    "factual and procedural background",
    "factual and procedural histories",
    "factual and procedural history",
    "factual background",
    "general principles",
    "governing law",
    "introduction",
    "issues on appeal",
    "legal principles",
    "opinion",
    "overview",
    "procedural background",
    "procedural history",
    "procedural history and facts",
    "procedure",
    "relevant law and standard of review",
    "ruling",
    "scope and standard of review",
    "standard of review",
    "statement of case and facts",
    "statement of facts",
    "statement of the case",
    "statement of the case and facts",
    "statutory framework",
    "statutory history and framework",
    "summary",
    "the case",
    "the evidence",
    "the facts",
}

# These terms came from headings that recur in the stored California opinions.
# They are anchors, not sufficient proof: length, presentation, metadata, and
# following-body checks must also pass.
_LEGAL_HEADING_ANCHOR_RE = re.compile(
    r"\b(?:"
    r"analysis|appealability|appeal|application|appointment|background|bonding|claims?|"
    r"conclusion|construction|contentions?|cross-examination|custody|"
    r"dependency|detention|detriment|discussion|disposition(?:al)?|due\s+process|"
    r"evidence|evidentiary|exceptions?|facts?|findings?|framework|governing|"
    r"hearings?|history|icwa|interpretation|issues?|jurisdiction(?:al)?|law|legal|misconduct|"
    r"offense|orders?|parental\s+rights|parole|petition(?:s|er(?:'s|\N{RIGHT SINGLE QUOTATION MARK}s)?)?|"
    r"placement|preference|presumed\s+parent|procedure|procedural|proceedings?|"
    r"reports?|review|rulings?|section|services|standard|standing|statutory|"
    r"termination|trial\s+court|visitation|writ"
    r")\b",
    flags=re.IGNORECASE,
)

_CAPTION_ROLE_RE = re.compile(
    r",\s*(?:plaintiffs?|defendants?|petitioners?|respondents?|appellants?|"
    r"real\s+part(?:y|ies)\s+in\s+interest)(?:\s+and\s+\w+)?\s*,?\s*$",
    flags=re.IGNORECASE,
)
_REPORTER_CITATION_RE = re.compile(
    r"\b\d+\s+(?:Cal\.(?:App\.)?(?:2d|3d|4th|5th)?|P\.\d+d|"
    r"Cal\.\s*Rptr\.(?:2d|3d)?)\s+\d+\b",
    flags=re.IGNORECASE,
)
_DOCKET_RE = re.compile(
    r"(?:\bdocket\s+no\.?|\b(?:super\.\s*ct\.\s*)?no(?:s)?\.|"
    r"^\(?[A-Z]\d{5,8}\)?$)",
    flags=re.IGNORECASE,
)
_JUDGE_SIGNATURE_RE = re.compile(
    r"(?:\b(?:chief\s+justice|justice|judge)\b|"
    r"(?:^|,\s*)(?:acting\s+)?(?:c\.\s*j\.|p\.\s*j\.|j\.)(?:\s*[\N{EM DASH}-])?$|"
    r"\bconcurred\.?$|^we\s+concur)",
    flags=re.IGNORECASE,
)
_PUBLICATION_RE = re.compile(
    r"(?:certified\s+for\s+publication|not\s+to\s+be\s+published|"
    r"not\s+certified\s+for\s+publication|official\s+reports|"
    r"california\s+rules\s+of\s+court,?\s+rule\s+8\.1115|"
    r"^filed\s+\d{1,2}/\d{1,2}/\d{2,4})",
    flags=re.IGNORECASE,
)
_COURT_OR_CAPTION_RE = re.compile(
    r"(?:^in\s+the\s+(?:supreme\s+)?court|^court\s+of\s+appeal|"
    r"^supreme\s+court\s+of|^superior\s+court\s+of|"
    r"\bappellate\s+district\b|^in\s+re\b|\bv\.\s*$)",
    flags=re.IGNORECASE,
)
_COUNSEL_RE = re.compile(
    r"(?:^counsel$|\bunder\s+appointment\s+by\b|"
    r"\bfor\s+(?:plaintiffs?|defendants?|petitioners?|respondents?|appellants?|"
    r"real\s+part(?:y|ies)\s+in\s+interest)\b|\bno\s+appearance\s+for\b)",
    flags=re.IGNORECASE,
)
_QUOTE_STARTS = ('"', "'", "`", "\N{LEFT DOUBLE QUOTATION MARK}", "\N{LEFT SINGLE QUOTATION MARK}")

_OUTLINE_WITH_TITLE_RE = re.compile(
    r"^(?P<label>(?:[IVXLCDM]+|[A-Za-z]|\d{1,2}))[.)]\s+(?P<title>\S.*)$",
    flags=re.IGNORECASE,
)
_PUNCTUATED_BARE_OUTLINE_RE = re.compile(
    r"^(?P<label>(?:[IVXLCDM]+|[A-Za-z]))[.)]$",
    flags=re.IGNORECASE,
)
_BARE_OUTLINE_RE = re.compile(r"^(?P<label>(?:[IVXLCDM]+|[A-Za-z]|\d{1,2}))$", re.IGNORECASE)


def infer_opinion_heading_spans(
    text: str,
    semantic_spans: Iterable[DisplayStyleSpan] = (),
) -> list[DisplayStyleSpan]:
    """Return trusted and conservatively inferred heading spans for ``text``.

    ``semantic_spans`` are assumed to come from trusted structural elements.
    Invalid ranges are discarded, and a leading reporter page marker is never
    included in a returned style range.
    """

    trusted = _normalize_semantic_spans(text, semantic_spans)
    if not text.strip():
        return trusted

    paragraphs = _paragraphs(text)
    # Flattened PDF/<pre> text commonly arrives as one enormous block.  This
    # check is a backstop; callers with source metadata should skip inference.
    if len(paragraphs) == 1 and len(paragraphs[0].text) >= 1_200:
        return trusted

    inferred: list[DisplayStyleSpan] = []
    outline_candidates: list[_OutlineCandidate] = []
    notes_index = _notes_section_index(paragraphs)

    for index, paragraph in enumerate(paragraphs):
        candidate = _candidate_text(paragraph.text)
        if not candidate or _is_metadata(candidate):
            continue
        outline = _parse_outline(candidate)
        if outline is not None:
            outline_kind, value, title, is_punctuated = outline
            if notes_index is not None and index > notes_index:
                continue
            if title and not _is_heading_phrase(title):
                continue
            if not _has_following_body(paragraphs, index):
                continue
            outline_candidates.append(
                _OutlineCandidate(
                    index,
                    outline_kind,
                    value,
                    paragraph,
                    independently_styled=(
                        is_punctuated and outline_kind in {"roman", "letter"}
                    ),
                )
            )
            continue
        if not _is_heading_phrase(candidate):
            continue
        if not _has_following_body(paragraphs, index):
            continue
        inferred.append(_heading_span(paragraph))

    coherent_outline_indexes = _coherent_outline_indexes(outline_candidates)
    inferred.extend(
        _heading_span(candidate.paragraph)
        for candidate in outline_candidates
        if (
            candidate.independently_styled
            or candidate.paragraph_index in coherent_outline_indexes
        )
    )

    return _merge_spans(trusted, inferred)


def _normalize_semantic_spans(
    text: str,
    spans: Iterable[DisplayStyleSpan],
) -> list[DisplayStyleSpan]:
    normalized: list[DisplayStyleSpan] = []
    for span in spans:
        if not isinstance(span, DisplayStyleSpan) or not span.kind:
            continue
        start = span.start_offset
        end = span.end_offset
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(text)
        ):
            continue
        styled_range = _normalized_range(text, start, end)
        if styled_range is None:
            continue
        candidate = _candidate_text(text[styled_range[0]:styled_range[1]])
        if _is_metadata(candidate):
            continue
        normalized.append(DisplayStyleSpan(span.kind, *styled_range))
    return _deduplicate_spans(normalized)


def _paragraphs(text: str) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    start = 0
    for separator in _PARAGRAPH_SEPARATOR_RE.finditer(text):
        paragraph = _paragraph(text, start, separator.start())
        if paragraph is not None:
            paragraphs.append(paragraph)
        start = separator.end()
    paragraph = _paragraph(text, start, len(text))
    if paragraph is not None:
        paragraphs.append(paragraph)
    return paragraphs


def _paragraph(text: str, start: int, end: int) -> _Paragraph | None:
    styled_range = _normalized_range(text, start, end)
    if styled_range is None:
        return None
    normalized_start, normalized_end = styled_range
    return _Paragraph(normalized_start, normalized_end, text[normalized_start:normalized_end])


def _normalized_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    marker = _LEADING_PAGE_MARKER_RE.match(text, start, end)
    if marker is not None:
        start = marker.end()
        while start < end and text[start].isspace():
            start += 1
    if start >= end:
        return None
    return start, end


def _candidate_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _heading_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.rstrip(" :*\t").strip()).casefold()


def _is_heading_phrase(text: str) -> bool:
    if not text or "\n" in text or "\r" in text:
        return False
    if len(text) > 125 or text[-1:] in ".?!;":
        return False
    words = _WORD_RE.findall(text)
    if not words or len(words) > 18:
        return False
    key = _heading_key(text)
    if key in _CANONICAL_HEADINGS:
        return True
    if _LEGAL_HEADING_ANCHOR_RE.search(text) is None:
        return False
    return _is_all_caps_heading(text) or _is_title_like(text)


def _is_all_caps_heading(text: str) -> bool:
    letters = [character for character in text if character.isalpha()]
    return bool(letters) and all(not character.islower() for character in letters)


def _is_title_like(text: str) -> bool:
    words = _WORD_RE.findall(text)
    if not words:
        return False
    minor_words = {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "under",
        "with",
    }
    significant = [word for word in words if word.casefold() not in minor_words]
    if not significant:
        return False
    capitalized = sum(word[:1].isupper() or word.isupper() for word in significant)
    return capitalized / len(significant) >= 0.75


def _is_metadata(
    text: str,
    *,
    reporter_citation_is_metadata: bool = True,
) -> bool:
    stripped = text.strip()
    lower = stripped.casefold()
    if stripped.startswith(_QUOTE_STARTS):
        return True
    if _CAPTION_ROLE_RE.search(stripped):
        return True
    if reporter_citation_is_metadata and _REPORTER_CITATION_RE.search(stripped):
        return True
    if _DOCKET_RE.search(stripped) or _JUDGE_SIGNATURE_RE.search(stripped):
        return True
    if _PUBLICATION_RE.search(stripped) or _COURT_OR_CAPTION_RE.search(stripped):
        return True
    if _COUNSEL_RE.search(stripped):
        return True
    if lower in {"notes", "footnotes", "*", "-oooo-", "-ooooo-"}:
        return True
    return False


def _has_following_body(paragraphs: list[_Paragraph], index: int) -> bool:
    for paragraph in paragraphs[index + 1:index + 5]:
        candidate = _candidate_text(paragraph.text)
        if _looks_like_body(candidate):
            return True
    return False


def _looks_like_body(text: str) -> bool:
    if len(text) < 35 or _is_metadata(
        text,
        reporter_citation_is_metadata=False,
    ):
        return False
    words = _WORD_RE.findall(text)
    if len(words) < 6:
        return False
    lowercase_words = sum(any(character.islower() for character in word) for word in words)
    return lowercase_words >= max(3, len(words) // 3)


def _parse_outline(text: str) -> tuple[str, int, str, bool] | None:
    titled_match = _OUTLINE_WITH_TITLE_RE.fullmatch(text)
    title = ""
    if titled_match is not None:
        match = titled_match
        title = match.group("title").strip()
        is_punctuated = True
    else:
        match = _PUNCTUATED_BARE_OUTLINE_RE.fullmatch(text)
        is_punctuated = match is not None
    if match is None:
        match = _BARE_OUTLINE_RE.fullmatch(text)
        if match is None:
            return None
    label = match.group("label")
    if label.isdigit():
        if not title:
            return None
        value = int(label)
        return ("number", value, title, is_punctuated) if value > 0 else None
    upper = label.upper()
    if len(upper) > 1 or upper in {"I", "V", "X"}:
        value = _roman_value(upper)
        return ("roman", value, title, is_punctuated) if value is not None else None
    return "letter", ord(upper) - ord("A") + 1, title, is_punctuated


def _roman_value(label: str) -> int | None:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1_000}
    total = 0
    previous = 0
    for character in reversed(label):
        value = values.get(character)
        if value is None:
            return None
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total if _roman_text(total) == label else None


def _roman_text(value: int) -> str:
    parts: list[str] = []
    for number, label in (
        (1_000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ):
        while value >= number:
            parts.append(label)
            value -= number
    return "".join(parts)


def _coherent_outline_indexes(candidates: list[_OutlineCandidate]) -> set[int]:
    coherent: set[int] = set()
    for outline_kind in {candidate.outline_kind for candidate in candidates}:
        siblings = [
            candidate
            for candidate in candidates
            if candidate.outline_kind == outline_kind
        ]
        for left, right in zip(siblings, siblings[1:]):
            if right.value == left.value + 1:
                coherent.add(left.paragraph_index)
                coherent.add(right.paragraph_index)
    return coherent


def _notes_section_index(paragraphs: list[_Paragraph]) -> int | None:
    for index, paragraph in enumerate(paragraphs):
        if _heading_key(_candidate_text(paragraph.text)) in {"notes", "footnotes"}:
            return index
    return None


def _heading_span(paragraph: _Paragraph) -> DisplayStyleSpan:
    return DisplayStyleSpan("heading", paragraph.start_offset, paragraph.end_offset)


def _merge_spans(
    trusted: list[DisplayStyleSpan],
    inferred: list[DisplayStyleSpan],
) -> list[DisplayStyleSpan]:
    merged = list(trusted)
    for candidate in inferred:
        if any(_ranges_overlap(candidate, existing) for existing in trusted):
            continue
        merged.append(candidate)
    return _deduplicate_spans(merged)


def _ranges_overlap(left: DisplayStyleSpan, right: DisplayStyleSpan) -> bool:
    return left.start_offset < right.end_offset and right.start_offset < left.end_offset


def _deduplicate_spans(spans: Iterable[DisplayStyleSpan]) -> list[DisplayStyleSpan]:
    unique = {
        (span.kind, span.start_offset, span.end_offset): span
        for span in spans
    }
    return sorted(
        unique.values(),
        key=lambda span: (span.start_offset, span.end_offset, span.kind),
    )


# --- Display-only paragraph regrouping for structurally flat text ---------
#
# Flat CourtListener text (a single ``plain_text`` blob or a ``<pre>`` opinion)
# is often one enormous run with no paragraph structure. The conservative
# formatter below groups such text into readable paragraphs *without changing
# the underlying words or punctuation* (modulo whitespace). It is display-only:
# callers regenerate the display text from raw ``opinion_json`` on read, so raw
# text is never rewritten.

MIN_REGROUP_CHARS = 1200
MIN_USEFUL_BLOCK_CHARS = 100
TARGET_PARAGRAPH_CHARS = 800
HARD_PARAGRAPH_CHARS = 1200
MAX_STRUCTURED_BLOCK_CHARS = 4000

# Abbreviations whose trailing period must not introduce a sentence boundary.
# Ordered longest-first so multi-word reporter forms are protected wholly.
_PROTECTED_ABBREVIATIONS = (
    "F.Supp.", "F.3d", "F.2d", "L.Ed.", "S.Ct.", "Cal.App.5th", "Cal.App.4th",
    "Cal.App.3d", "Cal.5th", "Cal.4th", "Cal.3d", "Cal.2d", "Cal.Rptr.",
    "P.3d", "P.2d", "e.g.", "i.e.", "cf.", "U.S.", "No.", "Nos.", "vs.",
    "etc.", "id.", "ibid.", "al.", "pp.", "subd.", "art.", "fn.", "Ct.",
    "App.", "Cal.", "Supp.", "Dept.", "Gov.", "Corp.", "Inc.", "Co.",
    "Ltd.", "Jr.", "Sr.", "Rep.", "Sen.", "Assn.", "Bros.", "St.",
    "Mt.", "Ave.", "Blvd.", "Dr.", "Rev.", "Op.", "Dist.",
)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])[ \t\r\n]+(?=[A-Z\u201c\u2018\'\"])")


def is_flat_opinion_text(text: str) -> bool:
    """Return whether *text* is structurally flat (needs paragraph regrouping)."""
    if len(text) < MIN_REGROUP_CHARS:
        return False
    blocks = [block for block in re.split(r"\n[ \t]*\n", text) if block.strip()]
    useful = [block for block in blocks if len(_candidate_text(block)) >= MIN_USEFUL_BLOCK_CHARS]
    if useful and len(useful) >= 3 and max(len(block) for block in blocks) <= MAX_STRUCTURED_BLOCK_CHARS:
        return False
    return True


def _protect_abbreviations(text: str) -> str:
    for abbreviation in _PROTECTED_ABBREVIATIONS:
        text = text.replace(abbreviation, abbreviation.replace(".", "\u0000"))
    return text


def _restore_abbreviations(text: str) -> str:
    return text.replace("\u0000", ".")


def _split_sentences(text: str) -> list[str]:
    protected = _protect_abbreviations(text)
    pieces = [piece.strip() for piece in _SENTENCE_END_RE.split(protected) if piece.strip()]
    return [_restore_abbreviations(piece) for piece in pieces]


def _group_pieces_into_paragraphs(pieces: list[str]) -> list[str]:
    paragraphs: list[str] = []
    current = ""
    for piece in pieces:
        added = f"{current} {piece}" if current else piece
        if len(added) > TARGET_PARAGRAPH_CHARS:
            if current:
                paragraphs.append(current)
            current = piece
            if len(piece) >= HARD_PARAGRAPH_CHARS:
                paragraphs.append(piece)
                current = ""
        else:
            current = added
        if len(current) >= HARD_PARAGRAPH_CHARS:
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    return paragraphs


def regroup_flat_opinion_text(text: str) -> str | None:
    """Return paragraph-regrouped text for structurally flat opinion text.

    Returns ``None`` when *text* is already structured enough (fewer than three
    useful blocks and no oversized block, or under ``MIN_REGROUP_CHARS``).
    Otherwise it preserves every word and punctuation mark (modulo whitespace),
    honours existing blank-line and single-newline boundaries, keeps recognized
    opinion headings as their own paragraphs, and otherwise groups sentence
    boundaries into roughly 400-1000 character paragraphs with a 1200-character
    whitespace-only hard break.
    """
    if not is_flat_opinion_text(text):
        return None

    raw_blocks = [block for block in re.split(r"\n[ \t]*\n", text.strip()) if block.strip()]
    paragraphs: list[str] = []
    for block in raw_blocks:
        # Respect existing single-newline boundaries first (one idea per line),
        # then apply sentence grouping only to a very long line.
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        current = ""
        for line in lines:
            candidate = _candidate_text(line)
            if _is_heading_phrase(candidate):
                if current:
                    paragraphs.append(current)
                    current = ""
                paragraphs.append(candidate)
                continue
            if len(candidate) >= HARD_PARAGRAPH_CHARS:
                if current:
                    paragraphs.append(current)
                    current = ""
                paragraphs.extend(_group_pieces_into_paragraphs(_split_sentences(candidate)))
                continue
            if current:
                current = f"{current} {candidate}"
            else:
                current = candidate
            if len(current) >= HARD_PARAGRAPH_CHARS:
                paragraphs.append(current)
                current = ""
        if current:
            paragraphs.append(current)

    normalized = "\n\n".join(paragraphs)
    return normalized if normalized != text else None
