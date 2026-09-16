"""Disposable GUI check; synthetic sources, no model or network. Auto-closes."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='oll-prior-gui-'))
for key, name in {
    'OPEN_LAW_LENS_CONFIG': 'config.json',
    'OPEN_LAW_LENS_CACHE_DIR': 'cache',
    'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': 'archive',
    'XDG_STATE_HOME': 'state',
}.items():
    os.environ[key] = str(ROOT / name)
os.environ.pop('COURTLISTENER_TOKEN', None)
(ROOT / 'config.json').write_text('{}')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.agent import CaseTextSource
from gi.repository import Gio
from run_prior_brief_acceptance import seed

library = seed(ROOT)
brief = next(b for b in library.list_briefs() if 'AOB_Dependent' in b.title)
answer = ('# Dependent Child Inclusion Briefs\n*Qualified advocacy only*\n\n'
          f'[{brief.title}](open-law-lens://prior-brief/{brief.brief_id}) '
          'argues for children “who witnessed the threats” and acknowledges an adverse restrictive position.')


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass


def activate(app):
    window = Preview(app)
    window.set_title('Synthetic Prior Brief Quality Acceptance')
    window.present()
    window._agent_mode = ui.AGENT_MODE_BRIEF
    window._case_agent_text_sources = [CaseTextSource(
        '', '', brief.title, '', '', brief.text,
        authority_type='prior_brief', prior_brief_id=brief.brief_id)]
    answer_id = window.client.cache.save_agent_answer(answer, mode='brief')
    window._open_agent_answer({'answer_id': answer_id})
    # Independently verify the existing Agent-panel navigation against saved text.
    window._render_agent_answer(window.client.cache.read_agent_answer(answer_id)['text'])
    targets = list(window._agent_link_lookup.values())
    quote = next(t for t in targets if t.phrase == 'who witnessed the threats')
    title = next(t for t in targets if t.phrase == brief.title)
    print('PASS saved answer readback; Agent panel title and short quote targets', flush=True)

    def title_check():
        window._open_quote_target(title)
        assert window._selected_prior_brief.brief_id == brief.brief_id
        print('PASS source target opened indexed brief', flush=True)
        return False

    def quote_check():
        window._open_quote_target(quote)
        assert 'who witnessed the threats' in window._reader_text
        print('PASS short quote target dispatched to source reader', flush=True)
        return False

    ui.GLib.timeout_add_seconds(20, title_check)
    ui.GLib.timeout_add_seconds(35, quote_check)
    ui.GLib.timeout_add_seconds(65, lambda: (app.quit(), False)[1])
    print('READY', os.getpid(), ROOT, flush=True)


def blocked(*args, **kwargs):
    raise AssertionError('Network forbidden in synthetic GUI')


with patch.object(socket.socket, 'connect', blocked):
    app = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.PriorQualityPreview',
                            flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect('activate', activate)
    app.run([])
