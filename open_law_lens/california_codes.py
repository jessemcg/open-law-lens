"""California LegInfo identifiers and CSM § 2:8 names (no runtime state).

Identifiers: https://leginfo.legislature.ca.gov/faces/codes.xhtml
Style: https://sdap.org/wp-content/uploads/downloads/Style-Manual.pdf
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class CaliforniaCode:
    identifier: str
    name: str
    abbreviation: str
    aliases: tuple[str, ...] = ()


CODES = (
    CaliforniaCode('BPC', 'Business and Professions Code', 'Bus. & Prof. Code'),
    CaliforniaCode('CIV', 'Civil Code', 'Civ. Code'),
    CaliforniaCode('CCP', 'Code of Civil Procedure', 'Code Civ. Proc.', ('Civ. Proc. Code', 'Civil Procedure Code', 'Civil Proc. Code', 'Civ. Procedure Code')),
    CaliforniaCode('COM', 'Commercial Code', 'Cal. U. Com. Code',
                   ('Com. Code', 'California Uniform Commercial Code', 'U. Com. Code')),
    CaliforniaCode('CORP', 'Corporations Code', 'Corp. Code'),
    CaliforniaCode('EDC', 'Education Code', 'Ed. Code', ('Educ. Code',)),
    CaliforniaCode('ELEC', 'Elections Code', 'Elec. Code'),
    CaliforniaCode('EVID', 'Evidence Code', 'Evid. Code'),
    CaliforniaCode('FAM', 'Family Code', 'Fam. Code'),
    CaliforniaCode('FIN', 'Financial Code', 'Fin. Code'),
    CaliforniaCode('FGC', 'Fish and Game Code', 'Fish & G. Code', ('Fish & Game Code',)),
    CaliforniaCode('FAC', 'Food and Agricultural Code', 'Food & Agr. Code'),
    CaliforniaCode('GOV', 'Government Code', 'Gov. Code', ('Gov’t Code', "Gov't Code")),
    CaliforniaCode('HNC', 'Harbors and Navigation Code', 'Harb. & Nav. Code'),
    CaliforniaCode('HSC', 'Health and Safety Code', 'Health & Saf. Code'),
    CaliforniaCode('INS', 'Insurance Code', 'Ins. Code'),
    CaliforniaCode('LAB', 'Labor Code', 'Lab. Code'),
    CaliforniaCode('MVC', 'Military and Veterans Code', 'Mil. & Vet. Code'),
    CaliforniaCode('PEN', 'Penal Code', 'Pen. Code'),
    CaliforniaCode('PROB', 'Probate Code', 'Prob. Code'),
    CaliforniaCode('PCC', 'Public Contract Code', 'Pub. Contract Code'),
    CaliforniaCode('PRC', 'Public Resources Code', 'Pub. Resources Code'),
    CaliforniaCode('PUC', 'Public Utilities Code', 'Pub. Util. Code'),
    CaliforniaCode('RTC', 'Revenue and Taxation Code', 'Rev. & Tax. Code'),
    CaliforniaCode('SHC', 'Streets and Highways Code', 'Sts. & Hy. Code'),
    CaliforniaCode('UIC', 'Unemployment Insurance Code', 'Unemp. Ins. Code'),
    CaliforniaCode('VEH', 'Vehicle Code', 'Veh. Code'),
    CaliforniaCode('WAT', 'Water Code', 'Wat. Code'),
    CaliforniaCode('WIC', 'Welfare and Institutions Code', 'Welf. & Inst. Code', ('W&I',)),
)

# Whitespace may wrap once, but cannot bridge paragraphs.
SPACE = r'[\t \u00a0]*(?:\n[\t \u00a0]*)?'
GAP = r'[\t \u00a0]+(?:\n[\t \u00a0]*)?|\n[\t \u00a0]*'


def alias_pattern(alias: str) -> str:
    if alias == 'W&I':
        return rf'(?i:W{SPACE}&{SPACE}I)'
    tokens = re.split(r'\s+', alias)
    result = ''
    separator = ''
    for token in tokens:
        if token in {'and', '&'}:
            separator = rf'(?:{SPACE}&{SPACE}|(?:{GAP})and(?:{GAP}))'
            continue
        result += separator + re.escape(token).replace(r'\.', r'\.?')
        separator = '(?:' + GAP + ')'
    return '(?i:' + result + ')'


CODE_LABELS = {c.identifier: c.name for c in CODES}
CODE_SHORT_LABELS = {c.identifier: c.abbreviation for c in CODES}
CODE_PATTERNS = tuple(
    (c.identifier, '|'.join([alias_pattern(a) for a in
                            (c.name, c.abbreviation, *c.aliases)]
                           + [f'(?-i:{c.identifier})']))
    for c in sorted(CODES, key=lambda c: len(c.name), reverse=True)
)
CODE_PATTERN = r'(?:(?i:Cal(?:ifornia)?\.?)(?:' + GAP + r'))?(?:' + '|'.join(
    f'(?P<{code}>{pattern})' for code, pattern in CODE_PATTERNS
) + r')(?!\w)'
CODE_RE = re.compile(r'(?<!\w)' + CODE_PATTERN)


def match_code(match: re.Match) -> str:
    return next(code for code, _ in CODE_PATTERNS if match.groupdict().get(code))
