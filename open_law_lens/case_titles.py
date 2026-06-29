from __future__ import annotations

import re
from typing import Any


def normalize_case_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    normalized = re.sub(
        r"\s+et\s+al\.?(?=\s*(?:$|[,(]))",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"^in\s+re\b", "In re", normalized, count=1, flags=re.IGNORECASE)
    if not normalized.startswith("In re "):
        return normalized
    normalized = _normalize_in_re_name_words(normalized)
    normalized = re.sub(r"\b([A-Z])\.\s+([A-Z])\.(?=$|[\s,)])", r"\1.\2.", normalized)
    normalized = re.sub(
        r"^(In re )([A-Z]{2})\.?(?=$|[\s,(])",
        lambda match: f"{match.group(1)}{'.'.join(match.group(2))}.",
        normalized,
    )
    return re.sub(r"\s+CA\d+\s*$", "", normalized)


def _normalize_in_re_name_words(title: str) -> str:
    prefix = "In re "
    body = title.removeprefix(prefix)

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if len(word) <= 2:
            return word
        if re.fullmatch(r"[A-Z]\.[A-Z]\.", word):
            return word
        return word[0] + word[1:].lower()

    return prefix + re.sub(r"\b[A-Z]{2,}\b", replace, body)


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
    leading = re.split(
        r"\s*,?\s*a\s+Person\s+Coming\s+Under\b|,",
        normalized,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return normalize_case_title(leading)


def parenthetical_in_re_title(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    matches = re.findall(r"\((In re [^)]+)\)", normalized, flags=re.IGNORECASE)
    if not matches:
        return ""
    return normalize_case_title(matches[-1])


def is_superior_court_writ_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", title.strip())
    return bool(re.search(r"\bv\.\s+Superior Court\b", normalized))


def cluster_display_title_value(cluster: dict[str, Any]) -> str:
    full_value = cluster.get("case_name_full")
    full_in_re = leading_in_re_title(full_value) if isinstance(full_value, str) else ""
    short_value = cluster.get("case_name_short")
    short_title = normalize_case_title(short_value) if isinstance(short_value, str) else ""
    case_value = cluster.get("case_name")
    case_title = normalize_case_title(case_value) if isinstance(case_value, str) else ""

    if full_in_re:
        return full_in_re
    if short_title.startswith("In re "):
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
