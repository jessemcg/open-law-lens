from __future__ import annotations

import re
from typing import Any


ESTATE_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "deceased"}
ESTATE_SURNAME_PARTICLES = {
    "da",
    "de",
    "del",
    "della",
    "di",
    "du",
    "la",
    "le",
    "st",
    "van",
    "von",
}


def normalize_case_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    normalized = re.sub(
        r"\s+et\s+al\.?(?=\s*(?:$|[,(]))",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^in\s+re\b", "In re", normalized, count=1, flags=re.IGNORECASE)
    normalized = re.sub(
        r"^adoption\s+of\b",
        "Adoption of",
        normalized,
        count=1,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^conservatorship\s+of\b",
        "Conservatorship of",
        normalized,
        count=1,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^estate\s+of\b",
        "Estate of",
        normalized,
        count=1,
        flags=re.IGNORECASE,
    )
    if normalized.startswith("In re "):
        normalized = _trim_dependency_caption_tail(normalized)
        normalized = _normalize_leading_name_words(normalized, "In re ")
    elif normalized.startswith("Adoption of "):
        normalized = _normalize_leading_name_words(normalized, "Adoption of ")
    elif normalized.startswith("Conservatorship of "):
        normalized = _normalize_conservatorship_title(normalized)
    elif normalized.startswith("Estate of "):
        normalized = _normalize_estate_title(normalized)
    else:
        return _normalize_civil_case_title(normalized)
    normalized = _normalize_initial_spacing(normalized)
    normalized = re.sub(
        r"^((?:In re|Adoption of|Conservatorship of|Estate of) )([A-Z]{2})\.?(?=$|[\s,(])",
        lambda match: f"{match.group(1)}{'.'.join(match.group(2))}.",
        normalized,
    )
    normalized = _normalize_habeas_title(normalized)
    return re.sub(r"\s+CA\d+\s*$", "", normalized)


def _trim_dependency_caption_tail(title: str) -> str:
    match = re.match(
        r"^(?P<leading>In re .+?)[\s,.;]+(?:a\s+Person|Persons)\s+Coming\s+Under\b.*$",
        title,
        flags=re.IGNORECASE,
    )
    if match is None:
        return title
    leading = match.group("leading").rstrip(" ,;")
    if re.search(r"\b[A-Z]$", leading):
        leading = f"{leading}."
    return leading


def _normalize_leading_name_words(title: str, prefix: str) -> str:
    body = title.removeprefix(prefix)

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) <= 2:
            return word
        if re.fullmatch(r"[A-Z]\.[A-Z]\.", word):
            return word
        return word[0] + word[1:].lower()

    return prefix + re.sub(r"\b[A-Z]{2,}\b", replace, body)


def _normalize_conservatorship_title(title: str) -> str:
    body = title.removeprefix("Conservatorship of ")
    body = re.sub(
        r"^(?:the\s+)?Person\s+of\s+",
        "",
        body,
        count=1,
        flags=re.IGNORECASE,
    )
    return _normalize_leading_name_words(f"Conservatorship of {body}", "Conservatorship of ")


def _normalize_estate_title(title: str) -> str:
    body = title.removeprefix("Estate of ")

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if re.fullmatch(r"(?:[A-Z]\.){1,3}", word):
            return word
        return "-".join(
            "'".join(piece[:1] + piece[1:].lower() for piece in part.split("'"))
            for part in word.split("-")
        )

    return "Estate of " + re.sub(r"\b[A-Z][A-Z'-]*\b", replace, body)


def _normalize_civil_case_title(title: str) -> str:
    parts = re.split(r"(\s+v\.\s+)", title, maxsplit=1)
    if len(parts) != 3:
        return title
    return "".join(
        (
            _normalize_personal_party_title(_strip_party_role_tail(parts[0])),
            parts[1],
            _normalize_personal_party_title(_strip_party_role_tail(parts[2])),
        )
    )


def _strip_party_role_tail(party: str) -> str:
    role = (
        r"(?:Petitioners?|Respondents?|Plaintiffs?|Defendants?|Appellants?"
        r"|Real Part(?:y|ies) in Interest)"
    )
    normalized = re.sub(
        rf",?\s+{role}(?:\s+and\s+{role})*[,]?\s*$",
        "",
        party,
        flags=re.IGNORECASE,
    )
    return normalized.rstrip(" ,")


def _normalize_personal_party_title(party: str) -> str:
    normalized = re.sub(
        r"\b(?P<name>[A-Z][A-Z'-]{2,})(?=\s+(?:[A-Z]\.){1,3}(?:$|[\s,]))",
        lambda match: _titlecase_name_word(match.group("name")),
        party,
    )
    normalized = re.sub(
        r"(?<=\b(?:[A-Z]\.)\s)(?P<name>[A-Z][A-Z'-]{2,})\b",
        lambda match: _titlecase_name_word(match.group("name")),
        normalized,
    )
    if re.fullmatch(r"(?:the\s+)?superior\s+court", normalized, flags=re.IGNORECASE):
        return "Superior Court"
    return normalized


def _titlecase_name_word(word: str) -> str:
    return "-".join(piece[:1] + piece[1:].lower() for piece in word.split("-"))


def _normalize_initial_spacing(title: str) -> str:
    return re.sub(r"\b([A-Z])\.\s+([A-Z])\.(?=$|[\s,)])", r"\1.\2.", title)


def _normalize_habeas_title(title: str) -> str:
    match = re.match(
        r"^(In re )(?P<name>.+?)\s+on\s+habeas\s+corpus\.?(?=$|[\s,)])",
        title,
        flags=re.IGNORECASE,
    )
    if match is None:
        return title
    name_words = re.findall(r"[A-Za-z][A-Za-z.'-]*", match.group("name"))
    if not name_words:
        return title
    return f"{match.group(1)}{name_words[-1].strip('.').strip()}"


def is_bare_initial_title(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title.strip())
    return bool(re.fullmatch(r"[A-Z](?:\.?[A-Z]){1,3}\.?", normalized))


def leading_in_re_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    if not re.match(r"^in\s+re\s+", normalized, flags=re.IGNORECASE):
        return ""
    malformed_dependency_match = re.search(
        r"\s+v\.\s+a\s+Person\s+Coming\s+Under\b",
        normalized,
        flags=re.IGNORECASE,
    )
    if malformed_dependency_match is not None:
        leading = f"{normalized[:malformed_dependency_match.start()].rstrip()} V."
        return normalize_case_title(leading)
    if re.search(
        r"[\s,.;]+(?:a\s+Person|Persons)\s+Coming\s+Under\b",
        normalized,
        flags=re.IGNORECASE,
    ):
        return normalize_case_title(normalized)
    leading = re.split(
        r",",
        normalized,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return normalize_case_title(leading)


def leading_adoption_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    if not re.match(r"^adoption\s+of\s+", normalized, flags=re.IGNORECASE):
        return ""
    leading = re.split(r",", normalized, maxsplit=1)[0]
    return normalize_case_title(leading)


def leading_estate_title(title: str, short_title: str = "") -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    match = re.match(r"^estate\s+of\s+(?P<subject>.+)$", normalized, flags=re.IGNORECASE)
    if match is None:
        return ""
    subject = match.group("subject").split(",", 1)[0].strip(" .")
    if not subject:
        return ""
    short_name = _estate_short_name(short_title, subject)
    if not short_name:
        short_name = _estate_surname(subject)
    return normalize_case_title(f"Estate of {short_name}") if short_name else ""


def _estate_short_name(short_title: str, subject: str) -> str:
    normalized = normalize_case_title(short_title) if short_title.strip() else ""
    if normalized.startswith("Estate of "):
        normalized = normalized.removeprefix("Estate of ")
    if not normalized or " v. " in f" {normalized.casefold()} ":
        return ""
    short_words = _estate_name_words(normalized)
    subject_words = _estate_name_words(subject)
    if not short_words or len(short_words) > len(subject_words):
        return ""
    if subject_words[-len(short_words):] != short_words:
        return ""
    return normalized


def _estate_surname(subject: str) -> str:
    tokens = re.findall(r"[A-Za-z][A-Za-z.'-]*", subject)
    while tokens and tokens[-1].rstrip(".").casefold() in ESTATE_NAME_SUFFIXES:
        tokens.pop()
    if not tokens or len(tokens[-1].rstrip(".")) < 2:
        return ""
    start = len(tokens) - 1
    while start > 0 and tokens[start - 1].rstrip(".").casefold() in ESTATE_SURNAME_PARTICLES:
        start -= 1
    return " ".join(tokens[start:])


def _estate_name_words(value: str) -> list[str]:
    return [
        word.rstrip(".").casefold()
        for word in re.findall(r"[A-Za-z][A-Za-z.'-]*", value)
        if word.rstrip(".")
    ]


def parenthetical_in_re_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    matches = re.findall(r"\((In re [^)]+)\)", normalized, flags=re.IGNORECASE)
    if not matches:
        return ""
    return normalize_case_title(matches[-1])


def parenthetical_adoption_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    matches = re.findall(r"\((Adoption of [^)]+)\)", normalized, flags=re.IGNORECASE)
    if not matches:
        return ""
    return normalize_case_title(matches[-1])


def is_superior_court_writ_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title.strip())
    return bool(re.search(r"\bv\.\s+Superior Court\b", normalized))


def cluster_display_title_value(cluster: dict[str, Any]) -> str:
    full_value = cluster.get("case_name_full")
    full_in_re = leading_in_re_title(full_value) if isinstance(full_value, str) else ""
    full_adoption = leading_adoption_title(full_value) if isinstance(full_value, str) else ""
    short_value = cluster.get("case_name_short")
    short_title = normalize_case_title(short_value) if isinstance(short_value, str) else ""
    full_estate = (
        leading_estate_title(full_value, short_title)
        if isinstance(full_value, str)
        else ""
    )
    case_value = cluster.get("case_name")
    case_title = normalize_case_title(case_value) if isinstance(case_value, str) else ""

    if full_adoption:
        return full_adoption
    if full_in_re:
        return full_in_re
    if full_estate:
        return full_estate
    if short_title.startswith(("In re ", "Adoption of ")):
        return short_title
    if case_title:
        return case_title
    if isinstance(full_value, str) and full_value.strip():
        return normalize_case_title(full_value)
    return short_title


def cluster_title_value(cluster: dict[str, Any]) -> str:
    return cluster_display_title_value(cluster)


def cluster_short_title_value(cluster: dict[str, Any]) -> str:
    return cluster_display_title_value(cluster)
