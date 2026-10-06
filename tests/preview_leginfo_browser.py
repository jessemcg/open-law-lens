"""Live default-browser acceptance with disposable GUI/cache/library state.

Run with project-env run OpenLawLens python tests/preview_leginfo_browser.py.
Retrieves GOV 815.6, verifies the displayed result and cache/library separation,
then leaves the synthetic window visible for inspection (close it normally).
Never uses production config, current-case files, or authority storage.
"""
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(tempfile.mkdtemp(prefix="oll-leginfo-preview-"))
for key, name in {
    "OPEN_LAW_LENS_CONFIG": "config.json",
    "OPEN_LAW_LENS_CACHE_DIR": "cache",
    "OPEN_LAW_LENS_LIBRARY_DB": "library.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DB": "briefs.sqlite3",
}.items():
    os.environ[key] = str(ROOT / name)
os.environ.pop("COURTLISTENER_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from gi.repository import Gio

COLD = '--cold' in sys.argv
CITATION = 'WIC 300' if COLD else 'Gov. Code, § 815.6'
STATUTE_ID = 'WIC:300' if COLD else 'GOV:815.6'
EXPECTED_TEXT = 'child' if COLD else 'mandatory duty'
if COLD:
    # Deliberately slow only the synthetic library source. Use the production
    # asynchronous index loader, partial publisher and entry submission path.
    concordance = ROOT / 'concordance.csv'
    concordance.write_text('WIC 300;WIC 300;Statutes\n')
    ui.concordance_file_path = lambda: concordance
    def slow_library(_library):
        time.sleep(4)
        return []
    ui.case_suggestions_from_library = slow_library


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        if COLD:
            return super()._refresh_case_suggestion_index_async(*args, **kwargs)
        return None


def activate(app):
    window = Preview(app)
    window.set_title("Synthetic LegInfo Browser — isolated acceptance")
    window.present()
    started = time.monotonic()

    ticks = []
    def heartbeat():
        ticks.append(time.monotonic())
        return True
    ui.GLib.timeout_add(50, heartbeat)

    if COLD:
        window.citation_entry.grab_focus()
        window.citation_entry.set_text(CITATION)

    def begin():
        if COLD:
            assert not window._case_suggestions_loaded
            assert window._citation_entry_has_focus()
            assert window._case_completion_results_scroller.get_visible()
            assert window._case_completion_matches[0].statute_id == STATUTE_ID
            before = time.monotonic()
            window._on_lookup_clicked(window.citation_entry)
            elapsed = time.monotonic() - before
            assert elapsed < 0.25, elapsed
            print(f'PASS: cold completion visible; Enter returned in {elapsed:.3f}s while library still loading', flush=True)
        else:
            window._start_statute_lookup(CITATION)
        return False

    def verify():
        cached = window.client.cache.read_cached_statute(STATUTE_ID)
        if cached:
            assert EXPECTED_TEXT in window._reader_text
            assert EXPECTED_TEXT in cached["text"]
            assert window.client.library.list_case_entries() == []
            gaps = [b - a for a, b in zip(ticks, ticks[1:])]
            print('PASS: GUI reader + temporary Research Cache; durable library empty; max heartbeat gap', round(max(gaps, default=0), 3), flush=True)
            return False
        if time.monotonic() - started > 110:
            print("FAIL: GUI lookup did not complete", flush=True)
            app.quit()
            return False
        return True

    ui.GLib.timeout_add(800, begin)
    ui.GLib.timeout_add(1000, verify)
    print("READY", os.getpid(), ROOT, flush=True)


app = ui.Adw.Application(
    application_id="com.mcglaw.OpenLawLens.LegInfoPreview",
    flags=Gio.ApplicationFlags.NON_UNIQUE,
)
app.connect("activate", activate)
app.run([])
