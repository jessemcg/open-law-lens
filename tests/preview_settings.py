"""Actual SettingsWindow, synthetic config/catalog/files only; no case or network.

Run through paired disposable project-env overrides. --auto checks state/save/
callbacks and exits. Otherwise a separate small controls window drives appearance,
refresh, failure and sizing while the real Settings window stays unmodified.
All process-local state is under the printed temporary root. No production saves.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(tempfile.mkdtemp(prefix='oll-settings-preview-'))
for key, name in {
    'OPEN_LAW_LENS_CONFIG': 'config.json', 'OPEN_LAW_LENS_CACHE_DIR': 'cache',
    'OPEN_LAW_LENS_LIBRARY_DB': 'library.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DB': 'briefs.sqlite3',
    'OPEN_LAW_LENS_PRIOR_BRIEFS_DIR': 'archive',
    'XDG_STATE_HOME': 'state', 'XDG_CACHE_HOME': 'xdg-cache',
}.items():
    os.environ[key] = str(ROOT / name)
os.environ.pop('COURTLISTENER_TOKEN', None)
os.environ['GSETTINGS_BACKEND'] = 'memory'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.config import AGENT_PROFILE_KEYS, load_config
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog, PiRuntimeError
from gi.repository import Gio

PROFILES = {key: {'provider': 'synthetic', 'model': f'model-{index}', 'thinking': 'high'}
            for index, key in enumerate(AGENT_PROFILE_KEYS)}
RETIRED = {'general_agent_prompt_template': '  Synthetic {broken} /skill:no  ',
           'later_treatment_agent_prompt_template': {'not': 'a template'},
           'subsequent_treatment_agent_prompt_template': None}
(ROOT / 'config.json').write_text(json.dumps({
    **RETIRED, 'courtlistener_token': 'synthetic-token',
    'agent_runtime_profiles_version': 2, 'agent_runtime_profiles': PROFILES}))
SOCF = ROOT / 'synthetic-socf.odt'
ALTERNATIVE = ROOT / 'synthetic-fact.pdf'
SOCF.write_text('Synthetic source path only; never extracted.')
ALTERNATIVE.write_text('Synthetic alternate source path only; never extracted.')
BRIEFS = ROOT / 'Synthetic briefs α'
BRIEFS.mkdir()
MODE = {'failure': False}
FAILURES: list[str] = []
MODELS = tuple(PiModel(provider='synthetic', model_id=f'model-{index}',
    name=('Very long synthetic model label with distinct identifiers and Unicode αβγ ' * 3
          if index == 2 else f'Synthetic model {index}'),
    supported_thinking_levels=('off', 'low', 'medium', 'high')) for index in range(4))
CATALOG = PiRuntimeCatalog(models=MODELS, default_model=MODELS[0], default_thinking_level='medium')


def catalog():
    time.sleep(0.35)
    if MODE['failure']:
        raise PiRuntimeError('Synthetic model query failure — configured values preserved.')
    return CATALOG


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def activate(application):
    parent = SimpleNamespace(get_application=lambda: application,
        _appeal_fact_pattern_path_override=None, reload_settings=lambda: None)
    settings = ui.SettingsWindow(parent)
    settings.set_title('Synthetic OpenLawLens Settings')
    settings.present()
    controls = ui.Adw.ApplicationWindow(application=application, title='Synthetic Settings Controls')
    box = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL, spacing=5)
    controls.set_content(box)
    result = ui.Gtk.Label(label=f'Synthetic only: {ROOT}', wrap=True)
    box.append(result)
    style = ui.Adw.StyleManager.get_default()
    provider = ui.Gtk.CssProvider()
    ui.Gtk.StyleContext.add_provider_for_display(ui.Gdk.Display.get_default(), provider, 800)

    def expand(*_):
        for category in settings.settings_categories.values():
            category.set_expanded(True)

    def refresh(failure):
        MODE['failure'] = failure
        settings._on_refresh_pi_models(None)

    def choose(*_):
        settings._on_appeal_fact_pattern_chosen(
            SimpleNamespace(open_finish=lambda _: Gio.File.new_for_path(str(ALTERNATIVE))), None)

    def size(width):
        settings.set_default_size(width, 760)

    for label, callback in (
        ('Expand all', expand),
        ('Collapse all', lambda *_: [row.set_expanded(False) for row in settings.settings_categories.values()]),
        ('900 × 760', lambda *_: size(900)), ('Narrow 620 × 760', lambda *_: size(620)),
        ('Light', lambda *_: style.set_color_scheme(ui.Adw.ColorScheme.FORCE_LIGHT)),
        ('Dark', lambda *_: style.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK)),
        ('Enlarge text', lambda *_: provider.load_from_string('* { font-size: 20px; }')),
        ('Normal text', lambda *_: provider.load_from_string('')),
        ('Refresh success', lambda *_: refresh(False)), ('Refresh failure', lambda *_: refresh(True)),
        ('Synthetic choose fact pattern', choose),
        ('Use Current Case SOCF', lambda *_: settings._on_reset_appeal_fact_pattern(None)),
    ):
        button = ui.Gtk.Button(label=label)
        button.connect('clicked', callback)
        box.append(button)
    if '--auto' not in sys.argv and '--matrix' not in sys.argv:
        controls.present()
    print(f'ROOT={ROOT}', flush=True)
    if '--matrix' in sys.argv:
        # Native widget snapshots work without altering/unlocking the desktop.
        # They are rendered previews, not evidence of compositor/keyboard input.
        stages = iter(('collapsed-light-900', 'expanded-light-900', 'expanded-dark-900',
                       'expanded-dark-620-large', 'bottom-dark-620-large'))
        stage = None

        def render():
            if not settings.pi_model_refresh_button.get_sensitive():
                return True
            nonlocal stage
            if stage is not None:
                snapshot = ui.Gtk.Snapshot()
                width, height = settings.get_width(), settings.get_height()
                assert (width, height) == (620 if '620' in stage else 900, 760), (
                    stage, width, height)
                ui.Gtk.WidgetPaintable.new(settings).snapshot(snapshot, width, height)
                node = snapshot.to_node()
                texture = settings.get_renderer().render_texture(node, None)
                texture.save_to_png(str(ROOT / f'{stage}.png'))
                assert settings.settings_scroller.get_hadjustment().get_upper() <= settings.settings_scroller.get_width() + 1
                print(f'RENDER {stage}: {width}x{height}; no horizontal scrolling', flush=True)
            try:
                stage = next(stages)
            except StopIteration:
                application.quit()
                return False
            if stage == 'collapsed-light-900':
                settings.unmaximize()
                settings.set_default_size(901, 761)
                size(900)
                style.set_color_scheme(ui.Adw.ColorScheme.FORCE_LIGHT)
            if stage == 'expanded-light-900':
                settings.settings_categories['General'].set_expanded(True)
                settings.settings_categories['Agent Models'].set_expanded(True)
            if stage == 'expanded-dark-900':
                style.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK)
            if stage == 'expanded-dark-620-large':
                size(620)
                provider.load_from_string('* { font-size: 20px; }')
            if stage == 'bottom-dark-620-large':
                adjustment = settings.settings_scroller.get_vadjustment()
                adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
            return True
        ui.GLib.timeout_add(900, render)
        return
    if '--auto' not in sys.argv:
        return

    initial_bytes = (ROOT / 'config.json').read_bytes()
    phase = 0
    unsaved = None

    def check():
        nonlocal phase, unsaved, settings
        try:
            if not settings.pi_model_refresh_button.get_sensitive():
                return True
            if phase == 0:
                assert list(settings.settings_categories) == ['General', 'Display', 'Highlights', 'Agent Models']
                assert not any(row.get_expanded() for row in settings.settings_categories.values()), {
                    title: row.get_expanded() for title, row in settings.settings_categories.items()}

                assert not hasattr(settings, '_settings_stack')
                assert not any(isinstance(widget, ui.Gtk.TextView) for widget in walk(settings))
                # Internal model popovers are toolkit-owned; all app content shares one scroller.
                for widget in (settings.token_row, settings.reader_font_family_row,
                               settings.prior_briefs_folder_row, settings.appeal_fact_pattern_entry,
                               *settings._pi_profile_model_rows.values()):
                    ancestor = widget.get_parent()
                    while ancestor is not None and not isinstance(ancestor, ui.Gtk.ScrolledWindow):
                        ancestor = ancestor.get_parent()
                    assert ancestor is settings.settings_scroller
                assert isinstance(settings.token_row, ui.Adw.PasswordEntryRow)
                categories = list(settings.settings_categories.values())
                category_list = categories[0].get_parent()
                assert isinstance(category_list, ui.Gtk.ListBox)
                assert category_list.has_css_class('boxed-list')
                assert all(row.get_parent() is category_list for row in categories), (
                    'All four categories must be rows of ONE shared boxed list, not separate cards')
                assert [category_list.get_row_at_index(i) for i in range(4)] == categories
                assert category_list.get_row_at_index(4) is None
                settings.prior_briefs_folder_row.set_text('relative/missing/folder')
                settings._on_save_clicked(None)
                assert 'Unable to set Prior Briefs Folder' in settings.status_label.get_text()
                assert (ROOT / 'config.json').read_bytes() == initial_bytes
                settings._on_prior_briefs_folder_chosen(SimpleNamespace(
                    select_folder_finish=lambda _: Gio.File.new_for_path(str(BRIEFS))), None)
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings._on_prior_briefs_folder_chosen(SimpleNamespace(
                    select_folder_finish=lambda _: None), None)
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings._on_prior_briefs_folder_chosen(SimpleNamespace(
                    select_folder_finish=Mock(side_effect=ui.GLib.Error('Synthetic dismissal'))), None)
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings._on_reset_prior_briefs_folder(None)
                assert settings.prior_briefs_folder_row.get_text() == str(ui.DEFAULT_PRIOR_BRIEFS_DIR)
                settings.prior_briefs_folder_row.set_text(str(BRIEFS))
                assert (ROOT / 'config.json').read_bytes() == initial_bytes
                assert settings.child_focus(ui.Gtk.DirectionType.TAB_FORWARD)
                assert settings.get_focus() is not None
                assert len(settings._pi_profile_model_rows) == len(settings._pi_profile_thinking_rows) == 5
                assert all(any(child is widget for child in walk(settings.settings_categories['General']))
                           for widget in (settings.prior_briefs_folder_row, settings.appeal_fact_pattern_entry))
                assert settings._selected_pi_profiles() == load_config().agent_runtime_profiles
                settings.settings_categories['General'].set_expanded(True)
                settings.settings_categories['Agent Models'].set_expanded(True)
                settings.token_row.set_text('unsaved synthetic token')
                settings.reader_font_size_row.set_value(17)
                row = settings._pi_profile_model_rows['law']
                row.set_selected(2)
                unsaved = settings._selected_pi_profiles()
                settings.settings_categories['Agent Models'].set_expanded(False)
                settings.settings_categories['Agent Models'].set_expanded(True)
                assert settings.token_row.get_text() == 'unsaved synthetic token'
                assert settings.settings_categories['General'].get_expanded()
                assert settings._selected_pi_profiles() == unsaved
                choose()
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                settings._on_reset_appeal_fact_pattern(None)
                assert parent._appeal_fact_pattern_path_override is None
                assert settings.appeal_fact_pattern_entry.get_text() == str(SOCF)
                assert (ROOT / 'config.json').read_bytes() == initial_bytes
                refresh(True)
                assert not settings.pi_model_refresh_button.get_sensitive()
                phase = 1
            elif phase == 1:
                assert not settings._pi_profiles_ready
                assert settings._pending_pi_profiles == unsaved
                with patch.object(ui, 'save_config', side_effect=OSError('synthetic write failure')):
                    settings._on_save_clicked(None)
                assert 'Unable to save settings: synthetic write failure' in settings.status_label.get_text()
                assert (ROOT / 'config.json').read_bytes() == initial_bytes
                settings._on_save_clicked(None)
                assert load_config().agent_runtime_profiles == unsaved
                assert load_config().retired_prompt_settings == RETIRED
                assert load_config().reader_font_size_pt == 17
                assert load_config().courtlistener_token == 'unsaved synthetic token'
                assert load_config().prior_briefs_folder == str(BRIEFS)
                print('PASS actual Settings: ONE shared boxed list/four collapsed categories/General paths/independent expansion/unsaved retention/loading/failure/save/compatibility/fact callbacks', flush=True)
                settings.close()
                settings = ui.SettingsWindow(parent)
                settings.set_title('Synthetic OpenLawLens Settings Reloaded')
                settings.present()
                phase = 2
            elif phase == 2:
                assert settings.token_row.get_text() == 'unsaved synthetic token'
                assert settings.reader_font_size_row.get_value() == 17
                saved = (ROOT / 'config.json').read_bytes()
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings.token_row.set_text('discard me')
                settings._on_reset_prior_briefs_folder(None)
                assert load_config().prior_briefs_folder == str(BRIEFS)
                choose()
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                settings._on_refresh_pi_models(None)
                generation = settings._pi_model_generation
                settings.close()
                assert settings._pi_model_closed and settings._pi_model_generation > generation
                assert (ROOT / 'config.json').read_bytes() == saved
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                print('PASS actual Settings: reload/close discards unsaved settings/session fact override/generation guard', flush=True)
                settings = ui.SettingsWindow(parent)
                settings.set_title('Synthetic OpenLawLens Settings Default Reset')
                settings.present()
                phase = 3
            else:
                settings._on_reset_prior_briefs_folder(None)
                settings._on_save_clicked(None)
                assert load_config().prior_briefs_folder == ''
                assert load_config().retired_prompt_settings == RETIRED
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                assert 'appeal_fact_pattern' not in (ROOT / 'config.json').read_text()
                print('PASS actual Settings: saved folder reset restores default; fact override remains session-only', flush=True)
                application.quit()
                return False
        except Exception as exc:
            print(f'FAIL phase {phase}: {exc!r}', flush=True)
            FAILURES.append(repr(exc))
            application.quit()
            raise
        return True
    ui.GLib.timeout_add(150, check)


application = ui.Adw.Application(application_id='com.mcglaw.OpenLawLens.SyntheticSettings',
    flags=Gio.ApplicationFlags.NON_UNIQUE)
with patch.object(ui, 'available_pi_runtime_catalog', side_effect=catalog), \
     patch.object(ui, 'current_case_socf_odt', return_value=SOCF):
    application.connect('activate', activate)
    exit_code = application.run([])
raise SystemExit(1 if FAILURES else exit_code)
