"""Isolated native masthead acceptance: uv run python tests/preview_reader_masthead.py.

Fresh temporary state; no discovery, network or models. Uses the production
window's masthead, reparented into a narrow synthetic window. --auto runs the
layout matrix and exits; otherwise retains the last example for inspection.
Use ADW_DEBUG_HIGH_CONTRAST=1 for native high contrast, OLL_PREVIEW_LARGE=1
for process-local enlarged fonts, OLL_PREVIEW_DARK=1 for dark appearance.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="oll-masthead-preview-"))
for key, value in {
    "OPEN_LAW_LENS_CONFIG": "config.json",
    "OPEN_LAW_LENS_CACHE_DIR": "cache",
    "OPEN_LAW_LENS_LIBRARY_DB": "library.sqlite3",
    "OPEN_LAW_LENS_PRIOR_BRIEFS_DB": "briefs.sqlite3",
}.items():
    os.environ[key] = str(ROOT / value)
os.environ.pop("COURTLISTENER_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from open_law_lens import app as ui
from open_law_lens.storage import SOURCE_PROVIDER_LABELS
from gi.repository import Gio


def blocked(*args, **kwargs):
    raise AssertionError("Network/model work forbidden in synthetic preview")


class Preview(ui.OpenLawLensWindow):
    def _refresh_current_case_context(self):
        pass

    def _refresh_case_suggestion_index_async(self, *args, **kwargs):
        pass


EXAMPLES = [
    ("In re Example", "(2026) 1 Cal.5th 2", provider)
    for provider in SOURCE_PROVIDER_LABELS
] + [
    ("Association of Synthetic Long Named Petitioners v. Department of Example Services",
     "(2026) 123 Cal.App.5th 456", "google_scholar"),
    ("Welfare and Institutions Code", "§ 300, subdivision (b)(1)", None),
    ("California Rules of Court", "Rule 8.1115", None),
    ("Saved answer", "Likely reversible error", None),
    ("Prior brief — synthetic appeal", "Opening brief", None),
    ("Title only", "", None),
    ("UnbrokenIdentifier" * 8, "LongIdentifier" * 8, None),
]


def activate(app):
    manager = ui.Adw.StyleManager.get_default()
    manager.set_color_scheme(ui.Adw.ColorScheme.FORCE_DARK if os.getenv("OLL_PREVIEW_DARK")
                             else ui.Adw.ColorScheme.FORCE_LIGHT)
    owner = Preview(app)
    if os.getenv("OLL_PREVIEW_LARGE"):
        css = ui.Gtk.CssProvider()
        css.load_from_data(b"label.reader-masthead-title { font-size: 19.5pt; } label.reader-masthead-metadata { font-size: 15.75pt; } label.reader-masthead-source { font-size: 14.25pt; }")
        ui.Gtk.StyleContext.add_provider_for_display(owner.get_display(), css, 801)
    header = owner.reader_header_box
    header.get_parent().remove(header)
    window = ui.Gtk.ApplicationWindow(application=app, title="Synthetic Masthead — isolated acceptance")
    window.set_decorated(False)
    box = ui.Gtk.Box(orientation=ui.Gtk.Orientation.VERTICAL)
    box.append(header)
    box.append(ui.Gtk.Label(label="Synthetic reader — isolated acceptance"))
    window.set_child(box)
    actions = [owner.reader_clipboard_button, owner.reader_subsequent_treatment_button,
               owner.reader_find_paginated_button, owner.reader_save_prior_brief_button,
               owner.reader_cache_prior_brief_button]
    matrix = iter((width, example, count) for width in (420, 580, 880)
                  for example in EXAMPLES for count in (0, 1, 3))
    total = 0
    current = None
    minimum_width_growth = set()

    def advance():
        nonlocal current
        try:
            current = next(matrix)
        except StopIteration:
            print(f"PASS {total} native layouts; dark={manager.get_dark()} high_contrast={manager.get_high_contrast()} large={bool(os.getenv('OLL_PREVIEW_LARGE'))}; minimum width growth={sorted(minimum_width_growth)}", flush=True)
            if "--auto" in sys.argv:
                app.quit()
            else:
                owner._set_reader_header("In re Example", subtitle="(2026) 1 Cal.5th 2")
                owner._set_reader_source_provider("google_scholar")
                for i, action in enumerate(actions):
                    action.set_visible(i < 2)
                    action.set_sensitive(True)
                window.set_default_size(580, 240)
            return False
        width, (title, metadata, provider), count = current
        owner._set_reader_header(title, subtitle=metadata)
        assert owner.reader_source_label.get_tooltip_text() is None
        assert not owner.reader_source_label.get_visible()
        if provider:
            owner._reader_source_url = "https://an-unusually-long-synthetic-external-source.example.org/opinion"
            owner._set_reader_source_provider(provider)
        for i, action in enumerate(actions):
            action.set_visible(i < count)
        window.set_default_size(width, 300)
        window.present()
        ui.GLib.timeout_add(70, check)
        return False

    def check():
        nonlocal total
        width, (title, metadata, provider), count = current
        center = owner.reader_header_center_box
        ok, bounds = center.compute_bounds(header)
        assert ok
        # compute_bounds is relative to the CSS content origin; include padding.
        ok, whole = header.compute_bounds(header)
        assert ok
        if whole.get_width() > width + 1:
            minimum_width_growth.add((width, round(whole.get_width())))
        assert abs(bounds.get_x() + bounds.get_width() / 2 - (whole.get_x() + whole.get_width() / 2)) <= 1, (current, bounds.get_x(), bounds.get_width(), whole.get_x(), whole.get_width())
        for label in (owner.reader_header_label, owner.reader_header_metadata_label):
            if label.get_visible():
                assert not label.get_layout().is_ellipsized()
                assert label.get_layout().get_pixel_size()[0] <= label.get_width() + 1
        source = owner.reader_source_label
        if provider and provider != "external_web":
            assert not source.get_layout().is_ellipsized()
            assert source.get_layout().get_pixel_size()[0] <= source.get_width() + 1
        if provider == "external_web":
            assert source.get_tooltip_text() == source.get_text()
        ok, leading = owner.reader_header_leading_spacer.compute_bounds(header)
        assert ok and leading.get_x() + leading.get_width() <= bounds.get_x()
        ok, trailing = owner.reader_header_action_box.compute_bounds(header)
        assert ok and bounds.get_x() + bounds.get_width() <= trailing.get_x()
        if count:
            assert abs(trailing.get_x() + trailing.get_width() - (whole.get_x() + whole.get_width() - 12)) <= 1
        if not provider:
            assert abs(leading.get_width() - trailing.get_width()) <= 1
        if width == 880 and provider == "courtlistener" and count == 1:
            after_height = header.measure(ui.Gtk.Orientation.VERTICAL, width).natural
            owner.reader_header_leading_spacer.remove(source)
            center.append(source)
            center.set_spacing(2)
            baseline_height = header.measure(ui.Gtk.Orientation.VERTICAL, width).natural
            center.remove(source)
            owner.reader_header_leading_spacer.append(source)
            center.set_spacing(3)
            assert after_height < baseline_height
            print(f"Short header: {after_height}px vs third-line {baseline_height}px (current fonts)", flush=True)
        total += 1
        ui.GLib.idle_add(advance)
        return False

    advance()


with patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked):
    app = ui.Adw.Application(application_id="com.mcglaw.OpenLawLens.MastheadPreview", flags=Gio.ApplicationFlags.NON_UNIQUE)
    failed = False

    def failure(kind, value, traceback):
        global failed
        failed = True
        sys.__excepthook__(kind, value, traceback)
        app.quit()

    sys.excepthook = failure
    app.connect("activate", activate)
    app.run([])
    sys.exit(1 if failed else 0)
