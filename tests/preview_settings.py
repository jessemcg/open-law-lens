"""Owned SettingsWindow with synthetic config/catalog/files, no Pi/network.

Run from a tracked-source disposable copy with paired project-env overrides and
isolated HOME/XDG/Pi roots. --auto exercises state/save/refresh then exits;
otherwise the separate controls window drives synthetic discovery failures.
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
from open_law_lens.config import AGENT_PROFILE_KEYS, PiAgentProfile, load_config
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog, PiRuntimeError
from gi.repository import Gio

PROFILES = {key: {'provider': 'synthetic', 'model': f'model-{index}', 'thinking': 'high'}
            for index, key in enumerate(AGENT_PROFILE_KEYS)}
RETIRED = {'general_agent_prompt_template': '  Synthetic {broken} /skill:no  ',
           'later_treatment_agent_prompt_template': {'not': 'a template'},
           'subsequent_treatment_agent_prompt_template': None}
CONFIG = ROOT / 'config.json'
CONFIG.write_text(json.dumps({**RETIRED, 'courtlistener_token': 'synthetic-token',
    'agent_runtime_profiles_version': {'opaque': 2}, 'agent_runtime_profiles': PROFILES}))
SOCF = ROOT / 'synthetic-socf.odt'
ALTERNATIVE = ROOT / 'synthetic-fact.pdf'
SOCF.write_text('Synthetic source path only; never extracted.')
ALTERNATIVE.write_text('Synthetic alternate source path only; never extracted.')
BRIEFS = ROOT / 'Synthetic briefs α'
BRIEFS.mkdir()
MODE = {'failure': False, 'missing': False}
FAILURES = []
MODELS = tuple(PiModel(provider='synthetic', model_id=f'model-{index}',
    name=('Very long synthetic model label with distinct identifiers and Unicode αβγ ' * 3
          if index == 2 else f'Synthetic model {index}'),
    supported_thinking_levels=(('off',) if index == 3 else ('off', 'low', 'medium', 'high')))
    for index in range(4))
CATALOG = PiRuntimeCatalog(MODELS, MODELS[0], 'medium')


def catalog():
    time.sleep(0.35)
    if MODE['failure']:
        raise PiRuntimeError('Synthetic model query failure — configured values preserved.')
    return PiRuntimeCatalog(MODELS[:1], MODELS[0], 'medium') if MODE['missing'] else CATALOG


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def activate(application):
    parent = SimpleNamespace(get_application=lambda: application,
        _appeal_fact_pattern_path_override=None, reload_settings=Mock())
    settings = ui.SettingsWindow(parent)
    settings.set_title('Synthetic OpenLawLens Shared Agent Settings')
    settings.present()
    controls = ui.Adw.ApplicationWindow(application=application, title='Synthetic Settings Controls')
    box = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL, spacing=5)
    controls.set_content(box)
    box.append(ui.Gtk.Label(label=f'Synthetic only: {ROOT}', wrap=True))
    style = ui.Adw.StyleManager.get_default()
    provider = ui.Gtk.CssProvider()
    ui.Gtk.StyleContext.add_provider_for_display(ui.Gdk.Display.get_default(), provider, 800)

    def refresh(failure=False, missing=False):
        MODE.update(failure=failure, missing=missing)
        settings._on_refresh_pi_models(None)

    def choose():
        settings._on_appeal_fact_pattern_chosen(
            SimpleNamespace(open_finish=lambda _: Gio.File.new_for_path(str(ALTERNATIVE))), None)

    for label, callback in (
        ('Agent Model only', lambda: [row.set_expanded(title == 'Agent Model')
                                     for title, row in settings.settings_categories.items()]),
        ('Expand all', lambda: [row.set_expanded(True) for row in settings.settings_categories.values()]),
        ('Collapse all', lambda: [row.set_expanded(False) for row in settings.settings_categories.values()]),
        ('900 × 760', lambda: settings.set_default_size(900, 760)),
        ('620 × 760', lambda: settings.set_default_size(620, 760)),
        ('520 × 620', lambda: settings.set_default_size(520, 620)),
        ('469 × 620', lambda: settings.set_default_size(469, 620)),
        ('Light', lambda: style.set_color_scheme(ui.Adw.ColorScheme.FORCE_LIGHT)),
        ('Dark', lambda: style.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK)),
        ('Enlarge text', lambda: provider.load_from_string('* { font-size: 20px; }')),
        ('Normal text', lambda: provider.load_from_string('')),
        ('Refresh success', lambda: refresh()), ('Refresh failure', lambda: refresh(True)),
        ('Unavailable model catalog', lambda: refresh(missing=True)),
        ('Synthetic choose fact pattern', choose),
    ):
        button = ui.Gtk.Button(label=label)
        button.connect('clicked', lambda _button, callback=callback: callback())
        box.append(button)
    print(f'ROOT={ROOT} PID={os.getpid()}', flush=True)
    if '--matrix' in sys.argv:
        ui.Gtk.Settings.get_default().set_property('gtk-enable-animations', False)
        stages = iter(
            [(theme, width, large, 'loaded')
             for theme in ('light', 'dark') for width in (900, 520, 469)
             for large in (False, True)]
            + [('dark', 520, False, state)
               for state in ('loading', 'unavailable', 'failure')]
        )
        stage = None
        size_attempts = 0
        paintable = ui.Gtk.WidgetPaintable.new(settings)

        def render():
            nonlocal stage, settings, paintable, size_attempts
            if not settings.pi_model_refresh_button.get_sensitive() and (stage is None or stage[3] != 'loading'):
                return True
            if stage is not None:
                theme, expected_width, large, state = stage
                adjustment = settings.settings_scroller.get_vadjustment()
                bottom = max(0, adjustment.get_upper() - adjustment.get_page_size())
                if adjustment.get_value() < bottom - 1:
                    adjustment.set_value(bottom)
                    return True
                size = 'large' if large else 'normal'
                name = f'agent-{theme}-{expected_width}-{size}-{state}'
                snapshot = ui.Gtk.Snapshot()
                width, height = settings.get_width(), settings.get_height()
                expected_height = 760 if expected_width == 900 else 620
                if (width, height) != (expected_width, expected_height):
                    # X11 includes client-decoration extents in default_size.
                    # Measure them rather than hardcoding a shadow allowance.
                    assert size_attempts < 3, (stage, width, height)
                    surface = settings.get_surface()
                    settings.set_default_size(
                        expected_width + surface.get_width() - width,
                        expected_height + surface.get_height() - height)
                    size_attempts += 1
                    return True
                paintable.snapshot(snapshot, width, height)
                node = snapshot.to_node()
                assert node is not None
                texture = settings.get_renderer().render_texture(node, None)
                texture.save_to_png(str(ROOT / f'{name}.png'))
                assert settings.settings_scroller.get_hadjustment().get_upper() <= settings.settings_scroller.get_width() + 1
                assert settings.settings_categories['Agent Model'].get_expanded()
                assert settings.pi_model_row.get_mapped()
                assert settings.pi_model_row.get_parent().has_css_class('boxed-list')
                if state in ('loading', 'failure'):
                    assert not settings.pi_model_row.get_sensitive()
                if state == 'unavailable':
                    assert 'unavailable' in settings.pi_model_row.get_subtitle()
                    assert not settings.pi_thinking_row.get_sensitive()
                print(f'RENDER {name}: {width}x{height}; no horizontal scrolling', flush=True)
            try:
                stage = next(stages)
            except StopIteration:
                application.quit()
                return False
            theme, width, large, state = stage
            size_attempts = 0
            settings.destroy()
            style.set_color_scheme(ui.Adw.ColorScheme.FORCE_LIGHT if theme == 'light'
                                   else ui.Adw.ColorScheme.FORCE_DARK)
            provider.load_from_string('* { font-size: 20px; }' if large else '')
            # Fresh windows avoid compositor/backend resize policy contaminating
            # the requested content-size matrix.
            settings = ui.SettingsWindow(parent)
            settings.set_title('Synthetic OpenLawLens Shared Agent Settings')
            settings.set_default_size(width, 760 if width == 900 else 620)
            settings.present()
            paintable = ui.Gtk.WidgetPaintable.new(settings)
            for title, row in settings.settings_categories.items():
                row.set_expanded(title == 'Agent Model')
            if state == 'loading':
                # Hold the synthetic loading view by ignoring its worker result.
                settings._pi_model_generation += 1
                settings.pi_model_row.set_sensitive(False)
                settings.pi_thinking_row.set_sensitive(False)
                settings.pi_model_refresh_button.set_sensitive(False)
                settings.pi_model_row.set_subtitle('Loading models authorized in Pi...')
            elif state in ('unavailable', 'failure'):
                settings._pi_model_generation += 1
                settings.pi_model_refresh_button.set_sensitive(True)
                settings._finish_pi_model_load(
                    settings._pi_model_generation,
                    PiRuntimeCatalog(MODELS[:1], MODELS[0], 'medium') if state == 'unavailable' else None,
                    'Synthetic refresh failure' if state == 'failure' else '',
                    PiAgentProfile(provider='synthetic', model='model-2', thinking='high'))
            return True

        def checked_render():
            try:
                return render()
            except Exception as exc:
                FAILURES.append(repr(exc))
                print(f'FAIL render {stage}: {exc!r}', flush=True)
                application.quit()
                return False

        ui.GLib.timeout_add(900, checked_render)
        return
    if '--auto' not in sys.argv:
        if '--agent' in sys.argv:
            settings.settings_categories['Agent Model'].set_expanded(True)
        controls.present()
        return

    initial_bytes = CONFIG.read_bytes()
    phase = 0
    unsaved = None
    saved_bytes = None

    def check():
        nonlocal phase, unsaved, settings, saved_bytes
        try:
            if not settings.pi_model_refresh_button.get_sensitive():
                return True
            if phase == 0:
                assert list(settings.settings_categories) == ['General', 'Display', 'Highlights', 'Agent Model']
                assert not any(row.get_expanded() for row in settings.settings_categories.values())
                rows = list(settings.settings_categories.values())
                category_list = rows[0].get_parent()
                assert category_list.has_css_class('boxed-list')
                assert all(row.get_parent() is category_list for row in rows)
                assert category_list.get_row_at_index(4) is None
                agent = settings.settings_categories['Agent Model']
                assert agent.get_subtitle() == 'One model and thinking effort for all Agent tasks'
                combos = [w for w in walk(agent) if isinstance(w, ui.Adw.ComboRow)]
                assert [w.get_title() for w in combos] == ['Model', 'Thinking Effort']
                assert isinstance(settings.pi_model_row.get_parent(), ui.Gtk.ListBox)
                assert settings.pi_model_row.get_parent() is settings.pi_thinking_row.get_parent()
                assert not any(isinstance(w, ui.Gtk.TextView) for w in walk(settings))
                assert isinstance(settings.token_row, ui.Adw.PasswordEntryRow)
                for widget in (settings.token_row, settings.pi_model_row, settings.pi_thinking_row,
                               settings.prior_briefs_folder_row, settings.appeal_fact_pattern_entry):
                    ancestor = widget.get_parent()
                    while ancestor and not isinstance(ancestor, ui.Gtk.ScrolledWindow):
                        ancestor = ancestor.get_parent()
                    assert ancestor is settings.settings_scroller
                assert settings._selected_pi_profile() == PiAgentProfile(**PROFILES['law'])
                assert CONFIG.read_bytes() == initial_bytes
                settings.prior_briefs_folder_row.set_text('relative/missing')
                settings._on_save_clicked(None)
                assert 'Unable to set Prior Briefs Folder' in settings.status_label.get_text()
                assert CONFIG.read_bytes() == initial_bytes
                settings._on_prior_briefs_folder_chosen(SimpleNamespace(
                    select_folder_finish=lambda _: Gio.File.new_for_path(str(BRIEFS))), None)
                settings._on_prior_briefs_folder_chosen(SimpleNamespace(select_folder_finish=lambda _: None), None)
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings.settings_categories['General'].set_expanded(True)
                agent.set_expanded(True)
                settings.token_row.set_text('unsaved synthetic token')
                settings.reader_font_size_row.set_value(17)
                settings.pi_model_row.set_selected(3)  # Long synthetic model label.
                unsaved = settings._selected_pi_profile()
                choose()
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                settings._on_reset_appeal_fact_pattern(None)
                assert parent._appeal_fact_pattern_path_override is None
                assert settings.appeal_fact_pattern_entry.get_text() == str(SOCF)
                refresh()
                # Saving while discovery is in flight must preserve the unsaved pair.
                settings._on_save_clicked(None)
                assert load_config().agent_runtime_profile == unsaved
                assert 'Agent model changes apply to new sessions.' in settings.status_label.get_text()
                phase = 1
            elif phase == 1:
                assert settings._selected_pi_profile() == unsaved
                assert settings.token_row.get_text() == 'unsaved synthetic token'
                assert settings.settings_categories['General'].get_expanded()
                refresh(True)
                phase = 2
            elif phase == 2:
                assert not settings._pi_profiles_ready
                assert settings._pending_pi_profile == unsaved
                before = CONFIG.read_bytes()
                with patch.object(ui, 'save_config', side_effect=OSError('synthetic write failure')):
                    settings._on_save_clicked(None)
                assert 'Unable to save settings' in settings.status_label.get_text()
                assert CONFIG.read_bytes() == before
                settings._on_save_clicked(None)
                assert load_config().agent_runtime_profile == unsaved
                refresh(missing=True)
                phase = 3
            elif phase == 3:
                assert settings._selected_pi_profile() == unsaved
                assert 'unavailable' in settings.pi_model_row.get_subtitle()
                assert not settings.pi_thinking_row.get_sensitive()
                settings._on_save_clicked(None)
                assert load_config().agent_runtime_profile == unsaved
                refresh()
                phase = 4
            elif phase == 4:
                assert settings._selected_pi_profile() == unsaved
                assert settings.pi_thinking_row.get_sensitive()
                settings.pi_model_row.set_selected(4)  # Non-reasoning model.
                assert settings._selected_pi_thinking() == 'off'
                assert 'unsupported' in settings.pi_thinking_row.get_subtitle()
                settings.pi_model_row.set_selected(0)
                assert settings._selected_pi_profile() is None
                assert settings._selected_pi_thinking() == 'medium'
                assert not settings.pi_thinking_row.get_sensitive()
                settings._on_save_clicked(None)
                raw = json.loads(CONFIG.read_text())
                assert raw['agent_runtime_profile'] is None
                assert raw['agent_runtime_profiles'] == PROFILES
                assert raw['agent_runtime_profiles_version'] == {'opaque': 2}
                assert load_config().retired_prompt_settings == RETIRED
                saved_bytes = CONFIG.read_bytes()
                settings.close()
                settings = ui.SettingsWindow(parent)
                settings.set_title('Synthetic OpenLawLens Shared Agent Settings Reopened')
                settings.present()
                phase = 5
            else:
                assert settings._selected_pi_profile() is None
                assert settings.token_row.get_text() == 'unsaved synthetic token'
                assert settings.reader_font_size_row.get_value() == 17
                assert settings.prior_briefs_folder_row.get_text() == str(BRIEFS)
                settings.token_row.set_text('discard me')
                settings.pi_model_row.set_selected(2)
                choose()
                refresh()
                generation = settings._pi_model_generation
                settings.close()
                assert not settings._pi_model_closed
                settings._session.dialog.response('discard')
                assert settings._pi_model_closed and settings._pi_model_generation > generation
                assert not settings._finish_pi_model_load(generation, CATALOG, '', unsaved)
                assert CONFIG.read_bytes() == saved_bytes
                assert parent._appeal_fact_pattern_path_override == ALTERNATIVE
                assert 'appeal_fact_pattern' not in CONFIG.read_text()
                print('PASS actual Settings: shared boxed categories/single pair/Law fallback/read-only load/'
                      'Save during loading/unsaved refresh/failure/recovery/unavailable retention/'
                      'nonreasoning clamp/defaults/save-reopen/legacy compatibility/close guards/'
                      'other controls/session-only facts', flush=True)
                application.quit()
                return False
        except Exception as exc:
            FAILURES.append(repr(exc))
            print(f'FAIL phase {phase}: {exc!r}', flush=True)
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
