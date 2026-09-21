"""Pure, conservative California enactment recognition in rendered character offsets.

No personal bare-lookup preference is used here. Call once per opinion, never on
an assembly of majority and separate opinions. Context is an immutable snapshot.
"""
from bisect import bisect_right
from dataclasses import dataclass
import re

from .california_codes import CODE_RE, CODE_LABELS, match_code
from .statutes import StatuteLink, parse_statute_citation
from .rules import RuleLink, parse_rule_citation


@dataclass(frozen=True)
class CitationContext:
    california: bool = False
    owning_code: str = ''
    official_rule: str = ''
    # Markdown/direct-quote rendering may remove quote delimiters. Resolve only
    # declarations from the pre-render source, never offsets or link spans.
    declaration_source: str | None = None


# CRC 5.502(36), Title Five Division 3, Juvenile Rules. Membership is deliberately
# an explicit snapshot of active Division 3 entries verified 2026-09-20;
# repealed entries and unlisted numbers are omitted. Other Title Five divisions are
# NOT evidence of a statutory default.
# https://courts.ca.gov/cms/rules/index/five
# https://courts.ca.gov/cms/rules/index/five/rule5_502
JUVENILE_RULE_SOURCE = 'https://courts.ca.gov/cms/rules/index/five/rule5_502'
JUVENILE_RULES = frozenset('5.' + n for n in '''
500 501 502 504 505 510 512 514 516 518 520 522 523 524 526
530 531 532 534 536 538 540 542 544 546 548 550 551 552 553 555
560 565 570 575 580 585 590 595 605 610 612 613 614 616 618 619
620 625 630 632 635 637 640 642 643 645 647 649 650 651 652
655 660 661 662 663 664 667 668 670 672 674 676 678 682 684
690 695 697 700 705 706 707 708 710 715 720 722 725 726 727 728
730 735 740 752 754 756 758 760 762 764 766 768 770 774 776 778
780 782 785 790 795 800 804 806 807 808 810 811 812 813 814 815
820 825 830 840 850 860 900 903 906
'''.split())

SPACE = r'[ \t\u00a0]*(?:\n[ \t\u00a0]*)?'
SECTION = r'\d+[a-zA-Z]*(?:\.\d+[a-zA-Z]*)?(?![\w]|\.\d)'
NUMBER = r'(?:10|[1-9])\.\d+(?:\.\d+)?(?![\w]|\.\d)'
SUB = r'(?:\([A-Za-z0-9]+\))+'
SUB_JOIN = rf'(?:{SPACE},?{SPACE}(?:and|&)\s+|{SPACE},\s*|{SPACE}[-–]{SPACE})'
SUBS = rf'(?:{SPACE},?{SPACE}(?:(?:subds?\.?|subdivisions?){SPACE})?{SUB}(?:{SUB_JOIN}{SUB})*)?'
SECTION_RE = re.compile(rf'(?P<number>{SECTION})(?P<sub>{SUBS})', re.I)
BARE_RE = re.compile(rf'(?<!\w)(?:§{{1,2}}|sections?\b|secs?\.){SPACE}(?P<number>{SECTION})(?P<sub>{SUBS})', re.I)
RULE_PREFIX = r'(?:Cal(?:ifornia)?\.?\s+Rules\s+of\s+Court|CRC|Cal\.\s*R\.\s*Ct\.|Cal\.\s*R\.)'
RULE_RE = re.compile(rf'(?<!\w)(?P<family>{RULE_PREFIX})?{SPACE}[:,]?{SPACE}(?P<marker>rules?\s+)?(?P<number>{NUMBER})(?P<sub>{SUBS})', re.I)
JOIN_RE = re.compile(rf'{SPACE}(?:,\s*(?:(?:and|&)\s+)?|(?:and|&)\s+|[–—-]{SPACE}|to\s+)', re.I)
BAD_PREFIX = re.compile(r'\b(?:Nevada|Arizona|New York|Texas|Florida|Oregon|Washington|federal|local|municipal|former|formerly|renumbered|repealed|obsolete|U\.S\.|U\.S\.C\.|C\.F\.R\.|Constitution|regulations?|treatise|Witkin|Professional Conduct)(?:[^;\n]*?)$', re.I)
BAD_SUFFIX = re.compile(r'^\s*(?:,?\s*of\s+(?:the\s+)?(?:United States|Federal|Nevada|local|Constitution)|U\.S\.C\.|C\.F\.R\.)', re.I)


def _blocked(text: str, start: int, end: int) -> bool:
    # Restrict to the current clause; no suffix salvage of excluded authorities.
    raw_prefix = text[max(0, start - 160):start]
    prefix = re.split(r';|\n[ \t]*\n|(?<=[.!?])\s+(?=[A-Z])', raw_prefix)[-1]
    prefix = re.sub(r'\s+', ' ', prefix)
    clause = re.sub(r'\s+', ' ', re.split(r';|\n[ \t]*\n', raw_prefix)[-1])
    foreign = re.search(r'\b(?:Alabama|Alaska|Arkansas|Colorado|Connecticut|Delaware|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|New Hampshire|New Jersey|New Mexico|North Carolina|North Dakota|Ohio|Oklahoma|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Utah|Vermont|Virginia|West Virginia|Wisconsin|Wyoming|Canadian|French|British|English|Puerto Rico|District of Columbia|Fed\.|F\.R\.|Restatement|Treatise|Title\s+\d+|USC\b|CFR\b|CCR\b|C\.C\.R\.|Regs\.|Stats\.|Const\.|tit\.\s*\d+|Code\s*/|(?:Superior|Super\.|District|Dist\.)\s+(?:Court|Ct\.)|County|Los\s+Angeles|L\.A\.|Nev\.|Ariz\.|N\.Y\.|Tex\.|Fla\.|Or\.|Wash\.)', clause, re.I)
    # Unknown capitalized jurisdiction names directly qualifying a citation
    # cannot be discarded merely because its suffix resembles a California code.
    qualifier = re.search(r"(?<!\w)([A-Z][a-z]+)(?:['’]s)?\s+$", clause)
    unknown_qualifier = qualifier and qualifier[1] not in {
        'See', 'The', 'Under', 'In', 'And', 'Or', 'Compare', 'Accord',
        'But', 'Also', 'Thus', 'Here', 'Discussion', 'Conclusion',
    }
    foreign_abbreviation = re.search(r'(?<!\w)(?:[A-Z]\.){2,4}\s*$', clause)
    history = re.match(r'\s*(?:[([]|,\s*)(?:former|renumbered|repealed)\b', text[end:], re.I)
    trimmed = prefix.rstrip(' /,\t\n\u00a0')
    conflicting_code = any(m.end() == len(trimmed) for m in CODE_RE.finditer(trimmed))
    return bool(foreign or unknown_qualifier or foreign_abbreviation or history
                or conflicting_code or BAD_PREFIX.search(prefix)
                or BAD_SUFFIX.search(text[end:end+100]))


def _quoted_ranges(text: str) -> list[tuple[int, int]]:
    pattern = (r'''“[^”]*(?:”|$)|"[^"]*(?:"|$)|‘[^’]*(?:’|$)|'''
               r'''(?<!\w)'[^']*(?:'(?!\w)|$)|`[^`]*(?:`|$)|'''
               r'(?m:^>[^\n]*(?:\n>[^\n]*)*)')
    return [match.span() for match in re.finditer(pattern, text)]


def _default_code(text: str, context: CitationContext) -> str:
    defaults = set()
    text = context.declaration_source if context.declaration_source is not None else text
    text = re.sub(r'[*_]', '', text)
    quotes = _quoted_ranges(text)
    declaration = re.compile(r'\b(?:all\s+)?(?:(?:further|subsequent|undesignated|unqualified|other)\s+)*(?:statutory\s+references|section\s+references|references\s+to\s+(?:(?:code|statutory)\s+)?sections|references)(?:\s+(?:herein|in\s+this\s+opinion))?\s+(?:are|will be)\s+to\s+(?:the\s+)?', re.I)
    for match in declaration.finditer(text):
        if any(a <= match.start() < b for a, b in quotes):
            continue
        code = CODE_RE.match(text, match.end())
        if code:
            defaults.add(match_code(code))
        else:
            defaults.add('')
    if len(defaults) > 1:
        return ''
    if defaults:
        return next(iter(defaults))
    if context.owning_code in CODE_LABELS:
        return context.owning_code
    if context.official_rule in JUVENILE_RULES:
        return 'WIC'
    return ''


def enactment_links(text: str, context: CitationContext) -> list[StatuteLink | RuleLink]:
    links: list[StatuteLink | RuleLink] = []
    covered: list[tuple[int, int]] = []
    explicit: list[tuple[int, int, str, str]] = []
    default = _default_code(text, context)
    paragraph_starts = [-1] + [m.end() for m in re.finditer(r'\n[ \t]*\n', text)]

    def add(start: int, end: int, number: str, code: str = '', rule: bool = False) -> bool:
        if _blocked(text, start, end) or re.search(r'\n[ \t]*\n', text[start:end]):
            return False
        target = f'Cal. Rules of Court, rule {number}' if rule else f'{code} § {number}'
        original = re.sub(r'\s+', ' ', text[start:end]).strip()
        parsed = parse_rule_citation(original) if rule else parse_statute_citation(original)
        if parsed and (re.match(RULE_PREFIX, original, re.I) if rule else CODE_RE.match(original)):
            target = original
        links.append((RuleLink if rule else StatuteLink)(start, end, target))
        covered.append((start, end))
        return True

    def following(end: int, code: str = '', rule: bool = False,
                  *, remember: bool = False) -> None:
        pattern = re.compile(rf'(?P<number>{NUMBER if rule else SECTION})(?P<sub>{SUBS})', re.I)
        while (join := JOIN_RE.match(text, end)):
            if re.search(r'\n[ \t]*\n', join.group()):
                break
            member = pattern.match(text, join.end())
            if not member:
                break
            # Years and page numbers without section markers are not list members.
            if re.match(r'\s*(?:pages?\b|pp?\.|Cal\.|U\.S\.|[A-Za-z]+\s+Code\b)', text[member.end():], re.I):
                break
            if re.fullmatch(r'(?:19|20)\d{2}', member['number']):
                break
            if not add(member.start(), member.end(), member['number'], code, rule):
                break
            if remember:
                explicit.append((member.start(), member.end(), member['number'], code))
            end = member.end()

    for code_match in CODE_RE.finditer(text):
        code = match_code(code_match)
        tail = re.match(rf'{SPACE}[:,]?{SPACE}(?:(?:§{{1,2}}|sections?\b|secs?\.){SPACE})?', text[code_match.end():], re.I)
        start = code_match.end() + tail.end()
        section = SECTION_RE.match(text, start)
        if section and add(code_match.start(), section.end(), section['number'], code):
            explicit.append((code_match.start(), section.end(), section['number'], code))
            following(section.end(), code, remember=True)
    # Reverse form is fully qualified; include the owning code in the span.
    for bare in BARE_RE.finditer(text):
        reverse = re.match(rf'{SPACE},?{SPACE}of\s+the\s+', text[bare.end():], re.I)
        if not reverse:
            continue
        code_match = CODE_RE.match(text, bare.end() + reverse.end())
        if code_match and add(bare.start(), code_match.end(), bare['number'], match_code(code_match)):
            explicit.append((bare.start(), code_match.end(), bare['number'], match_code(code_match)))
    explicit.sort(key=lambda item: item[0])
    for bare in BARE_RE.finditer(text):
        if any(bare.start() < b and bare.end() > a for a, b in covered):
            continue
        # Unknown/foreign code before a bare marker is never a document default.
        prefix = text[max(text.rfind('\n\n', 0, bare.start()), bare.start()-100, 0):bare.start()]
        if re.search(r'(?:\bCode|\bAct|\bConstitution|\bRegulations?)\s*,?\s*$', prefix, re.I):
            continue
        if re.match(r'\s*,?\s*of\s+', text[bare.end():], re.I):
            continue
        paragraph = paragraph_starts[bisect_right(paragraph_starts, bare.start()) - 1]
        prior = [item for item in explicit if paragraph <= item[0] and item[1] <= bare.start()]
        code = default
        if prior and prior[-1][2] == bare['number']:
            between = text[prior[-1][1]:bare.start()]
            if not re.search(r'\b(?:Code|rules?|CRC|Constitution)\b|U\.S\.|C\.F\.R\.|Cal\.', between, re.I):
                code = prior[-1][3]
        if code and add(bare.start(), bare.end(), bare['number'], code) and default:
            following(bare.end(), code)
    statewide = context.california or bool(re.search(RULE_PREFIX, text, re.I))
    for rule in RULE_RE.finditer(text):
        if not rule['family'] and not (statewide and rule['marker']):
            continue
        start = rule.start('family') if rule['family'] else rule.start('marker')
        if add(start, rule.end(), rule['number'], rule=True):
            following(rule.end(), rule=True)
    result = []
    for link in sorted(links, key=lambda v: (v.start_offset, -v.end_offset)):
        if not result or result[-1].end_offset <= link.start_offset:
            result.append(link)
    return result
