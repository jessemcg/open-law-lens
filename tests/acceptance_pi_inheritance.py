"""Native Settings inheritance acceptance; synthetic state/catalog only.
Run from disposable tracked-source-only source/environment; --auto is unattended.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.umask(0o077)
ROOT = Path(tempfile.mkdtemp(prefix='oll-inheritance-'))
for key, directory in {'HOME': 'home', 'XDG_CONFIG_HOME': 'config', 'XDG_DATA_HOME': 'data',
                       'XDG_STATE_HOME': 'state', 'XDG_CACHE_HOME': 'cache',
                       'PI_CODING_AGENT_DIR': 'pi', 'OPEN_LAW_LENS_CONFIG': 'config.json',
                       'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3',
                       'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
                       'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': 'archive'}.items():
    os.environ[key] = str(ROOT / directory)
os.environ['OPEN_LAW_LENS_STORAGE'] = 'standalone'
os.environ['GSETTINGS_BACKEND'] = 'memory'
os.environ.pop('COURTLISTENER_TOKEN', None)
from open_law_lens import app as ui
from open_law_lens.config import PiAgentProfile
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog
CONFIG = ROOT / 'config.json'
CONFIG.write_text(json.dumps({'synthetic_unknown': ['keep']}))
MODEL = PiModel('synthetic', 'chosen', 'Synthetic choice')
CATALOG = PiRuntimeCatalog((MODEL,), MODEL, 'high')
app = ui.Adw.Application(application_id='org.synthetic.OpenLawLens.PiInheritance')
patches = []


def activate(application):
    parent = SimpleNamespace(get_application=lambda: application,
                             _appeal_fact_pattern_path_override=None, reload_settings=Mock())
    p = patch.object(ui.SettingsWindow, '_load_pi_models', lambda self: None)
    p.start(); patches.append(p)
    windows = []
    def reopen():
        if windows: windows.pop().destroy()
        w = ui.SettingsWindow(parent)
        w.set_title('Synthetic OpenLawLens Pi inheritance')
        w._finish_pi_model_load(0, CATALOG, '', w._original_pi_profile)
        w.settings_categories['Agent Model'].set_expanded(True)
        windows.append(w); w.present()
        return w
    reopen()
    controls = ui.Adw.ApplicationWindow(application=application, title='OpenLawLens inheritance controls')
    box = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL, spacing=8)
    controls.set_content(box)
    def inherited_save():
        w = windows[0]
        assert w._selected_pi_profile() is None
        w.reader_font_size_row.set_value(15)
        w._on_save_clicked(None)
        saved = json.loads(CONFIG.read_text())
        assert saved.get('agent_runtime_profile') is None
        assert saved['reader_font_size_pt'] == 15
        assert saved['synthetic_unknown'] == ['keep']
        assert not (ROOT / 'config/open-law-lens/pi/settings.json').exists()
        print('PASS inherited/unrelated Save', flush=True)
    def choose_and_fail():
        w = windows[0]; w.pi_model_row.set_selected(1)
        assert w._selected_pi_profile() == PiAgentProfile('synthetic', 'chosen', '')
        w._finish_pi_model_load(0, None, 'Synthetic refresh failure; draft retained', w._selected_pi_profile())
        assert w._pending_pi_profile == PiAgentProfile('synthetic', 'chosen', '')
        print('PASS explicit draft survives refresh failure', flush=True)
    def save_reopen():
        windows[0]._on_save_clicked(None)
        assert json.loads(CONFIG.read_text())['agent_runtime_profile'] == {'provider': 'synthetic', 'model': 'chosen'}
        w = reopen()
        assert w._selected_pi_profile() == PiAgentProfile('synthetic', 'chosen', '')
        assert json.loads(CONFIG.read_text())['synthetic_unknown'] == ['keep']
        print('PASS model-only Save/reopen; reasoning inherited', flush=True)
    steps = [inherited_save, choose_and_fail, save_reopen]
    for label, callback in zip(('1 Save inherited', '2 Choose and fail refresh', '3 Save and reopen'), steps):
        button = ui.Gtk.Button(label=label)
        button.connect('clicked', lambda _, f=callback: f()); box.append(button)
    done = ui.Gtk.Button(label='Finish acceptance')
    done.connect('clicked', lambda _: application.quit()); box.append(done)
    controls.present()
    print(f'ROOT={ROOT} PID={os.getpid()}', flush=True)
    if '--auto' in sys.argv:
        def run():
            for step in steps: step()
            application.quit(); return False
        ui.GLib.timeout_add(500, run)


app.connect('activate', activate)
app.run([])
