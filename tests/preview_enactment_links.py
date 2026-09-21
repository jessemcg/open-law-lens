"""Isolated manual acceptance: uv run python tests/preview_enactment_links.py.

Synthetic documents only. Each launch owns fresh temporary config/cache/library.
Government-source retrieval is real and ON CLICK only. No case lookup or agent.
F5 case, F6 saved answer, F7 no default, F8 juvenile rule, F9 rapid navigation,
F10 controlled source failure, F11 report assertions, F12 quit.
"""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(tempfile.mkdtemp(prefix='oll-enactment-preview-'))
for key, value in {
    'OPEN_LAW_LENS_CONFIG': 'config.json', 'OPEN_LAW_LENS_CACHE_DIR': 'cache',
    'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
}.items():
    os.environ[key] = str(ROOT / value)
os.environ.pop('COURTLISTENER_TOKEN', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.library import DisplayText
from open_law_lens.statutes import LegInfoError
from gi.repository import Gio

TEXT = '''SYNTHETIC CITATION FIXTURE — not legal advice

( Government Code section 815.6); Probate Code sections 100 and 102;
Health and Safety Code section 1200.

Welf. & Inst. Code, §§ 300, 361.5, and 366.26.
Cal. Rules of Court, rules 8.450 and 8.452; CRC 5.112.1.

All further statutory references are to the Welfare and Institutions Code unless otherwise indicated.
Section 300(b)(1); sections 361.5 and 366.26.

Do not link: Nevada Civil Code section 300; Local rule 3.10;
Rules of Professional Conduct, rule 3.3; former rule 39.
'''
CLUSTER = {'id': 'synthetic-1', 'case_name': 'Synthetic Citation Case',
           'court_id': 'cal', 'citations': [], 'date_filed': '2026-01-01'}


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        return None

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass

    def _case_worker(self, *args, **kwargs):
        raise AssertionError('Case network access forbidden in this preview')


def activate(app):
    window = Preview(app)
    window.set_title('Synthetic Enactment Links — isolated acceptance')
    window.client.cache.save_agent_answer(TEXT, mode='general', title='Synthetic Citation Answer')
    answer = window.client.cache.list_agent_answer_entries()[0]
    window._load_cached_cases()

    def case(default=True):
        generation = window._begin_case_load(CLUSTER)
        text = TEXT if default else 'SYNTHETIC WITHOUT DEFAULT\n\nsection 300; section 361.5; Government Code § 815.6; rule 8.204.'
        payload = ui.build_case_reader_payload(CLUSTER, [DisplayText(text, '', [], [])],
                                               generation=generation,
                                               cache_generation=window._research_cache_generation)
        window._start_reader_payload_render(payload)

    def report():
        assert window.client.library.list_case_entries() == []
        print('REPORT', len(window._reader_statute_link_lookup), 'statute links',
              len(window._reader_rule_link_lookup), 'rule links;',
              len(window.client.cache.list_statute_entries()), 'cached statutes',
              len(window.client.cache.list_rule_entries()), 'cached rules; durable cases=0', flush=True)

    def rapid():
        original = window.client.lookup_statute
        before = window.client.cache.list_statute_entries()
        entered = threading.Event()
        def delayed(*args, **kwargs):
            entered.set()
            time.sleep(.8)
            return dict(statute_id='GOV:999999', law_code='GOV', section='999999',
                        citation='GOV § 999999', text='SYNTHETIC delayed result')
        window.client.lookup_statute = delayed
        window._start_statute_lookup('GOV § 999999')
        assert entered.wait(1)
        window._open_agent_answer(answer)
        window.client.lookup_statute = original
        def verify():
            assert window.client.cache.list_statute_entries() == before
            assert 'SYNTHETIC CITATION FIXTURE' in window._reader_text
            print('RAPID stale result discarded before cache write PASS', flush=True)
            return False
        ui.GLib.timeout_add(1200, verify)

    def failure():
        before = window.client.cache.list_statute_entries()
        original = window.client.lookup_statute
        entered = threading.Event()
        def failed(*args, **kwargs):
            entered.set()
            raise LegInfoError('Synthetic source failure: no authority was cached.')
        window.client.lookup_statute = failed
        window._start_statute_lookup('GOV § 999999')
        assert entered.wait(1)
        window.client.lookup_statute = original
        def verify():
            assert window.client.cache.list_statute_entries() == before
            assert window.client.library.list_case_entries() == []
            print('FAILURE no cache/library insertion PASS', flush=True)
            return False
        ui.GLib.timeout_add(600, verify)

    actions = {
        'F4': lambda: window._open_statute_in_reader(dict(
            statute_id='GOV:815.6', law_code='GOV', section='815.6',
            code_label='Government Code', citation='Gov. Code, § 815.6',
            text='SYNTHETIC HEADER CHECK — no government retrieval.')),
        'F5': lambda: case(), 'F6': lambda: window._open_agent_answer(answer),
        'F7': lambda: case(False), 'F8': lambda: window._start_rule_lookup('CRC 5.502'),
        'F9': rapid, 'F10': failure, 'F11': report, 'F12': app.quit,
    }
    toolbar = ui.Gtk.Box(spacing=6)
    for key, title in [('F5', 'Case'), ('F6', 'Saved answer'), ('F7', 'No default'),
                       ('F8', 'Juvenile rule'), ('F9', 'Rapid navigation'),
                       ('F10', 'Source failure'), ('F11', 'Verify')]:
        button = ui.Gtk.Button(label=title)
        button.connect('clicked', lambda _button, key=key: actions[key]())
        toolbar.append(button)
    old = window.get_content()
    window.set_content(None)
    box = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL)
    box.append(toolbar)
    box.append(old)
    window.set_content(box)
    controller = ui.Gtk.EventControllerKey()
    controller.set_propagation_phase(ui.Gtk.PropagationPhase.CAPTURE)
    def keypress(_controller, keyval, *_args):
        action = actions.get(ui.Gdk.keyval_name(keyval))
        if action:
            action()
            return True
        return False
    controller.connect('key-pressed', keypress)
    window.add_controller(controller)
    window.present()
    case()
    print('READY', os.getpid(), ROOT, flush=True)


app = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.EnactmentPreview',
                        flags=Gio.ApplicationFlags.NON_UNIQUE)
app.connect('activate', activate)
app.run([])
