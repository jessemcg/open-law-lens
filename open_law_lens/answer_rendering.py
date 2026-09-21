"""Widget-free preparation for final answers. Never call GTK from this module."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .agent import CaseTextSource, QuoteTarget, resolved_agent_quote_spans
from .citation_links import citation_italic_spans, collect_authority_links, CitationContext
from .rules import RuleLink
from .statutes import StatuteLink


@dataclass(frozen=True)
class AnswerStyle:
    start: int
    end: int
    kind: str
    target: Any = None


@dataclass(frozen=True)
class PreparedAnswer:
    text: str
    styles: tuple[AnswerStyle, ...]


def prepare_answer(
    text: str,
    mode: str,
    sources: list[CaseTextSource],
    format_text: Callable[[str], tuple[str, list[tuple[int, int, str]], list[int]]],
    external_links: Callable[[str], list[tuple[int, int, str]]],
) -> PreparedAnswer:
    """Resolve source/quote scans and parse markup using immutable input snapshots."""
    quotes = resolved_agent_quote_spans(text, sources) if mode in {'case', 'brief'} else []
    rendered, markdown, offset_map = format_text(text)
    styles = [AnswerStyle(start, end, 'markdown', kind) for start, end, kind in markdown]
    if mode == 'brief':
        occupied: list[tuple[int, int]] = []
        for source in sorted((s for s in sources if s.authority_type == 'prior_brief'
                              and s.prior_brief_id and s.title),
                             key=lambda s: len(s.title), reverse=True):
            for match in re.finditer(re.escape(source.title), rendered, re.IGNORECASE):
                start, end = match.span()
                if any(start < b and end > a for a, b in occupied):
                    continue
                target = QuoteTarget(match.group(), '', '', source.title, source.citation,
                                     source.text_path, 0, 0, authority_type='prior_brief',
                                     prior_brief_id=source.prior_brief_id)
                styles.append(AnswerStyle(start, end, 'title', target))
                occupied.append((start, end))
    styles.extend(AnswerStyle(s.start_offset, s.end_offset, 'italic')
                  for s in citation_italic_spans(rendered))
    for span in quotes:
        if span.target is not None:
            styles.append(AnswerStyle(offset_map[span.start_offset],
                                      offset_map[span.end_offset], 'quote', span.target))
    external = external_links(rendered)
    occupied = [(s.start, s.end) for s in styles if s.kind in {'quote', 'title'}]
    occupied.extend((start, end) for start, end, _url in external)
    kinds = ('case', 'statute', 'rule') if mode in {'general', 'appeal'} else ('statute', 'rule')
    for link in collect_authority_links(rendered, context=CitationContext(
            california=True, declaration_source=text),
                                        kinds=kinds, occupied_ranges=occupied):
        kind = 'statute' if isinstance(link, StatuteLink) else 'rule' if isinstance(link, RuleLink) else 'citation'
        styles.append(AnswerStyle(link.start_offset, link.end_offset, kind, link))
    styles.extend(AnswerStyle(start, end, 'external', url)
                  for start, end, url in external)
    return PreparedAnswer(rendered, tuple(styles))
