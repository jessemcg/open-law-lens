"""Acceptance-only I/O fixture adapter. Production CLI/parser/resolver stay in use."""
import json
import os
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, parse_qs
from urllib.error import URLError

ROOT = Path(os.environ['OLL_FIXTURE_ROOT'])

def install():
    import open_law_lens.client as client
    import open_law_lens.statutes as statutes
    import open_law_lens.cli as cli
    from open_law_lens.browser_recovery import ScholarRecoveryOutcome
    from open_law_lens.scholar_recovery_service import ScholarRecoveryServiceResult
    def request(self, req):
        if '/search/' not in req.full_url:
            raise client.CourtListenerError('Fixed public fixture has no additional API response.')
        return {'count':5,'next':None,'results':[
            {'cluster_id':6239336,'caseName':'In re Jonathan V.','citation':['19 Cal.App.5th 236'],'court_id':'calctapp','court':'California Court of Appeal','dateFiled':'2018-01-09','status':'Published','snippet':'Notice and opportunity to be heard before juvenile restraining order; service on counsel by mail.'},
            {'cluster_id':4850176,'caseName':'Searles v. Archangel','citation':['60 Cal.App.5th 43'],'court_id':'calctapp','court':'California Court of Appeal','dateFiled':'2021-01-22','status':'Published','snippet':'Personal service requirement under former CCP section 527.6; alternative electronic service requested.'},
            {'cluster_id':10637976,'caseName':'Yu v. Pozniak-Rice','citation':[],'court_id':'calctapp','court':'California Court of Appeal','dateFiled':'2025-07-21','status':'Published','snippet':'Legislature responded to Searles by enacting section 527.6(m)(2); prerequisites for alternative service.'},
            {'cluster_id':9999001,'caseName':'Synthetic Oklahoma exclusion control','citation':[],'court_id':'okla','status':'Published','snippet':'Synthetic nonauthority lead for scope validation.'},
            {'cluster_id':9999002,'caseName':'Synthetic Illinois exclusion control','citation':[],'court_id':'ill','status':'Published','snippet':'Synthetic nonauthority lead for scope validation.'},
        ]}
    def leginfo(req, **kwargs):
        q=parse_qs(urlparse(req.full_url).query)
        code=q.get('lawCode',[''])[0]; section=q.get('sectionNum',[''])[0]
        path=ROOT/f'{code}-{section}.json'
        if path.is_file(): return BytesIO(json.loads(path.read_text())['source_html'].encode())
        if (code, section) in [('WIC','527.6'),('FAM','6330')]:
            return BytesIO(f'<title>California Code, {code} {section}</title><nav>Home Bill Information California Law</nav>'.encode())
        raise URLError('Section unavailable in fixed public fixture.')
    def recovery(*args, **kwargs):
        return ScholarRecoveryServiceResult(outcome='not_found', recovery=ScholarRecoveryOutcome(1,'not_found','','','No further copy in fixed fixture.'), reason='No further copy in fixed public fixture.',stage='search',reason_code='no_matching_result')
    def audit(event):
        path = os.environ.get('OLL_FIXTURE_AUDIT')
        if path:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, (json.dumps(event) + '\n').encode())
            finally:
                os.close(fd)
    original_main = cli.main
    original_print = cli._print_json
    def main(argv=None):
        import sys
        audit({'type': 'cli_call', 'argv': argv if argv is not None else sys.argv[1:]})
        return original_main(argv)
    def print_json(payload):
        audit({'type': 'payload', 'payload': payload})
        return original_print(payload)
    cli.main = main
    cli._print_json = print_json
    client.CourtListenerClient._request_json=request
    statutes.urlopen=leginfo
    cli.recover_official_copy=recovery
    # Any unexpected network attempt fails rather than reaching outside corpus.
    import socket
    def blocked(*args, **kwargs): raise OSError('Network disabled for fixture CLI.')
    socket.socket.connect=blocked
    return cli

if __name__ == '__main__':
    import sys
    raise SystemExit(install().main(sys.argv[1:]))
