"""Loaded only by the disposable SDK test's synthetic CLI process."""
import io
import json
import os
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from open_law_lens import client
from open_law_lens.library import CaseLibrary


class Response(io.BytesIO):
    status = 200

    def __init__(self, body):
        super().__init__(body if isinstance(body, bytes) else json.dumps(body).encode())


calls = 0


def trace(event):
    with open(os.environ['TEST_REQUEST_TRACE'], 'a') as f:
        f.write(event + '\n')


def fake_http(request, **_):
    global calls
    calls += 1
    parsed = urlsplit(request.full_url)
    assert parsed.netloc == 'www.courtlistener.com'
    assert 'CANARY' in request.headers.get('Authorization', '')
    if parsed.path.endswith('/search/'):
        query = parse_qs(parsed.query)['q'][0]
        if 'exhausted' in query:
            trace('503')
            raise HTTPError(request.full_url, 503, 'CANARY exception', {}, io.BytesIO(b'{}'))
        if 'malformed' in query:
            trace('decode')
            return Response(b'CANARY invalid json')
        if 'shape' in query:
            trace('shape')
            return Response({'results': 'CANARY wrong type'})
        if 'retry' in query and calls == 1:
            trace('429')
            raise HTTPError(request.full_url, 429, 'CANARY exception', {},
                            io.BytesIO(b'{"detail":"Request was throttled. Expected available in 1 second."}'))
        outside = {'cluster_id': 84, 'caseName': 'CANARY out of scope', 'court_id': 'scotus', 'status': 'Published'}
        inside = {'cluster_id': 85, 'caseName': 'CANARY in scope', 'court_id': 'cal', 'status': 'Published'}
        rows = [] if 'empty' in query else [outside, inside] if 'mixed' in query else [outside]
        trace('search')
        return Response({'count': 900, 'results': rows, 'next': None})
    if parsed.path.endswith('/clusters/42/'):
        trace('cluster')
        return Response({'id': 42, 'case_name': 'CANARY case', 'sub_opinions': ['/api/rest/v4/opinions/43/']})
    if parsed.path.endswith('/opinions/43/'):
        trace('opinion')
        return Response({'id': 43, 'plain_text': 'CANARY baseline text without the requested term.'})
    raise AssertionError('unexpected fake HTTP request')


def fake_sleep(seconds):
    trace(f'sleep:{seconds}')


def library_result(_self, _query):
    return []


def slip_not_in_fixture(*_, **__):
    raise ValueError('CANARY no slip')


def load():
    fixture = os.path.dirname(os.environ['TEST_REQUEST_TRACE'])
    os.environ['OPEN_LAW_LENS_LIBRARY_DB'] = os.path.join(fixture, f'library-{os.getpid()}.sqlite3')
    os.environ['OPEN_LAW_LENS_CACHE_DIR'] = os.path.join(fixture, f'cache-{os.getpid()}')
    client.urlopen = fake_http
    client.time.sleep = fake_sleep
    client.CourtListenerClient.fetch_cluster_slip_opinion = slip_not_in_fixture
    CaseLibrary.read_lookup = library_result
    # The synthetic token never reaches a network or the test machine's settings.
    client.courtlistener_token = lambda: 'CANARY-auth-token'
