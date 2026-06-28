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
    leading = normalized.split(",", 1)[0]
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


def cluster_title_value(cluster: dict[str, Any]) -> str:
    for key in ("case_name", "case_name_full", "case_name_short"):
        value = cluster.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_case_title(value)
    return ""


def cluster_short_title_value(cluster: dict[str, Any]) -> str:
    full_value = cluster.get("case_name_full")
    full_in_re = leading_in_re_title(full_value) if isinstance(full_value, str) else ""
    case_value = cluster.get("case_name")
    case_title = normalize_case_title(case_value) if isinstance(case_value, str) else ""
    short_value = cluster.get("case_name_short")
    if isinstance(short_value, str) and short_value.strip():
        short_title = normalize_case_title(short_value)
        if full_in_re and is_bare_initial_title(short_title):
            return full_in_re
        if case_title and is_superior_court_writ_title(case_title) and not short_title.startswith("In re "):
            return case_title
        return short_title
    if full_in_re:
        return full_in_re
    if case_title:
        return case_title
    for key in ("case_name_full",):
        value = cluster.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_case_title(value)
    return ""
