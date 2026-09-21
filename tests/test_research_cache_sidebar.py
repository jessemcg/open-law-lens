"""Presentation tests: real GTK rows, private temporary storage, no network."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import re
from unittest.mock import Mock, patch

import cairo

from open_law_lens.app import (
    Adw, Gdk, Gtk, OpenLawLensWindow, RESEARCH_CACHE_CSS, RESEARCH_CACHE_GROUPS,
)
from open_law_lens.config import AppConfig
from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary


def seed(cache):
    cache.ensure()
    cache.upsert_cluster({"id": 42, "case_name": "Example v. State", "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}]})
    cache.upsert_statute({"statute_id": "WIC:300", "title": "Synthetic statute", "citation": "Welf. & Inst. Code, § 300", "text": "Statute text"})
    cache.upsert_rule({"rule_id": "CRC:8.11", "title": "California Rules of Court, rule 8.11", "citation": "Cal. Rules of Court, rule 8.11", "text": "Rule text"})
    cache.upsert_prior_brief({"brief_id": "brief-1", "title": "Synthetic prior advocacy", "text": "Brief text"})
    cache.save_agent_answer("Synthetic answer about statutes", mode="appeal", title="Saved statute assessment")


def rows(window):
    result = []
    index = 0
    while row := window.case_list.get_row_at_index(index):
        result.append(row)
        index += 1
    return result


class SidebarHarness:
    def __init__(self, cache):
        self.client = SimpleNamespace(cache=cache)
        self.case_list = Gtk.ListBox()
        self.case_list.add_css_class("case-list")
        self.case_list.add_css_class("research-cache")
        self.case_list.set_sort_func(self._sort_research_cache_rows)
        self._suppress_sidebar_selection_lookup = False
        self._capture_current_reader_position = Mock()
        self._refresh_active_research_set_from_cache = Mock()
        for kind in ("case", "statute", "rule", "agent_answer", "prior_brief"):
            remove = "_on_remove_" + ("cached_" if kind in ("case", "statute", "rule") else "") + kind + "_clicked"
            setattr(self, remove, Mock())

    def __getattr__(self, name):
        value = getattr(OpenLawLensWindow, name)
        if isinstance(OpenLawLensWindow.__dict__.get(name), staticmethod):
            return value
        return value.__get__(self, type(self))

    def render(self, **selection):
        cache = self.client.cache
        self._set_sidebar_authorities(
            [cache.read_resource("clusters", e["cluster_id"]) for e in cache.list_case_entries()],
            [cache.read_cached_statute(e["statute_id"]) for e in cache.list_statute_entries()],
            [cache.read_cached_rule(e["rule_id"]) for e in cache.list_rule_entries()],
            **selection,
        )


class SidebarTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = JsonCache(self.root / "cache")
        seed(self.cache)
        self.window = SidebarHarness(self.cache)

    def test_all_types_counts_and_explicit_selection(self):
        for key, expected in (("select_cluster_id", "42"), ("select_statute_id", "WIC:300"),
                              ("select_rule_id", "CRC:8.11"),
                              ("select_agent_answer_id", self.cache.list_agent_answer_entries()[0]["answer_id"])):
            self.window.render(**{key: expected})
            self.assertEqual(self.window.case_list.get_selected_row()._open_law_lens_authority_id, expected)
        headers = [r for r in rows(self.window) if not r.get_selectable()]
        self.assertEqual([r._open_law_lens_cache_section for r in headers], [g.key + "_header" for g in RESEARCH_CACHE_GROUPS])
        self.assertEqual([r._open_law_lens_cache_count for r in headers], [2, 1, 1, 1])
        for header in headers:
            self.assertFalse(header.get_focusable())
            self.assertFalse(header.get_activatable())
            band = header.get_child()
            heading = band.get_first_child()
            self.assertIsNone(heading.get_next_sibling())
            self.assertEqual(heading.get_last_child().get_label(), str(header._open_law_lens_cache_count))
        self.window.render(select_first=True)
        self.assertIn(self.window.case_list.get_selected_row()._open_law_lens_authority_type, ("statute", "rule"))

    def test_statute_rows_use_code_name_and_section_without_repeating_citation(self):
        examples = [
            ({"title": "Welfare and Institutions Code section 300",
              "citation": "Welf. & Inst. Code, § 300"},
             ["Welfare and Institutions Code", "§ 300"]),
            ({"code_label": "Civil Code", "section": "43.5",
              "title": "Civil Code section 43.5", "citation": "Civ. Code, § 43.5"},
             ["Civil Code", "§ 43.5"]),
            ({"citation": "Pen. Code, § 1016.5"}, ["Penal Code", "§ 1016.5"]),
            ({"title": "Legacy statute"}, ["Legacy statute"]),
            ({}, ["Untitled statute"]),
        ]
        for payload, expected in examples:
            with self.subTest(payload=payload):
                statute = {"statute_id": "SYN:1", **payload}
                original = dict(statute)
                self.window._set_sidebar_authorities([], [statute], [])
                row = next(r for r in rows(self.window)
                           if getattr(r, "_open_law_lens_authority_type", "") == "statute")
                labels = []
                child = row.get_child().get_first_child().get_first_child()
                while child is not None:
                    labels.append(child.get_label())
                    child = child.get_next_sibling()
                self.assertEqual(labels, expected)
                self.assertEqual(statute, original)
                self.assertEqual(row._open_law_lens_authority_id, "SYN:1")

    def test_empty_and_single_groups(self):
        for keep in ((), ("case",), ("statute",), ("rule",), ("prior_brief",), ("agent_answer",), ("statute", "rule")):
            with self.subTest(keep=keep):
                self.cache.clear()
                seed(self.cache)
                for kind, identifier in (("case", "42"), ("statute", "WIC:300"), ("rule", "CRC:8.11"),
                                         ("prior_brief", "brief-1"), ("agent_answer", self.cache.list_agent_answer_entries()[0]["answer_id"])):
                    if kind not in keep:
                        getattr(self.cache, "remove_" + kind)(identifier)
                self.window.render(select_first=True)
                headers = [r for r in rows(self.window) if not r.get_selectable()]
                self.assertEqual(len(headers), int(bool(keep)))
                if keep:
                    self.assertEqual(headers[0]._open_law_lens_cache_count, len(keep))
                else:
                    self.assertIsNone(self.window._first_selectable_research_cache_row())

    def test_counts_follow_rendered_rows_not_cache_indices(self):
        # Upstream may supply a deduplicated/subset authority list. Do not count
        # a raw cache entry that was not rendered.
        self.window._set_sidebar_authorities(
            [], [self.cache.read_cached_statute("WIC:300")], [],
        )
        headers = [r for r in rows(self.window) if not r.get_selectable()]
        self.assertEqual(
            [(r._open_law_lens_cache_section, r._open_law_lens_cache_count) for r in headers],
            [("statutes_header", 1), ("prior_brief_header", 1), ("agent_answer_header", 1)],
        )
        self.cache.remove_statute("WIC:300")
        self.cache.remove_rule("CRC:8.11")
        self.window.render(select_cluster_id="42")
        self.assertNotIn("statutes_header", [r._open_law_lens_cache_section for r in rows(self.window)])
        self.assertEqual(self.window.case_list.get_selected_row()._open_law_lens_authority_type, "case")

    def test_action_rail_keeps_typed_callbacks(self):
        self.window.render()
        for row in rows(self.window):
            if not row.get_selectable():
                continue
            kind, identifier = row._open_law_lens_authority_type, row._open_law_lens_authority_id
            rail = row.get_child().get_last_child()
            self.assertTrue(rail.has_css_class("cache-row-actions"))
            check = rail.get_last_child()
            check.set_active(True)
            getter = {"case": "is_agent_selected", "agent_answer": "is_agent_answer_selected"}.get(kind, "is_" + kind + "_agent_selected")
            self.assertTrue(getattr(self.cache, getter)(identifier))
            rail.get_first_child().emit("clicked")
            remove = "_on_remove_" + ("cached_" if kind in ("case", "statute", "rule") else "") + kind + "_clicked"
            self.assertEqual(getattr(self.window, remove).call_args.args[1], identifier)

    def test_timestamp_boundaries_and_ties(self):
        self.window.render()
        items = [r for r in rows(self.window) if r.get_selectable()]
        rule = next(r for r in items if r._open_law_lens_authority_type == "rule")
        statute = next(r for r in items if r._open_law_lens_authority_type == "statute")
        case = next(r for r in items if r._open_law_lens_authority_type == "case")
        rule._open_law_lens_cache_sort_key = ("", "a", "", "rule", "1")
        statute._open_law_lens_cache_sort_key = ("2000", "z", "", "statute", "2")
        case._open_law_lens_cache_sort_key = ("9999", "", "", "case", "3")
        self.assertLess(self.window._sort_research_cache_rows(statute, rule), 0)
        self.assertLess(self.window._sort_research_cache_rows(rule, case), 0)
        statute._open_law_lens_cache_sort_key = ("", "z", "", "statute", "2")
        self.assertLess(self.window._sort_research_cache_rows(rule, statute), 0)
        self.assertEqual(self.window._research_cache_row_sort_key({"added_at": "2001"}, "A", "B", "rule", "r"), ("2001", "a", "b", "rule", "r"))

    def test_research_set_round_trip_does_not_dirty(self):
        self.cache.set_rule_agent_selected("CRC:8.11", True)
        library = CaseLibrary(self.root / "library.sqlite3")
        library.ensure()
        saved = library.save_research_set("Synthetic", self.cache)
        self.assertEqual(saved.item_count, 5)
        before = self.cache.read_cached_rule("CRC:8.11")
        self.cache.clear()
        library.load_research_set_into_cache("Synthetic", self.cache)
        metadata = self.cache.active_research_set_metadata()
        self.window.render(select_rule_id="CRC:8.11")
        self.assertEqual(self.cache.active_research_set_metadata(), metadata)
        self.assertFalse(metadata["dirty"])
        self.assertEqual(self.cache.read_cached_rule("CRC:8.11"), before)
        self.assertTrue(self.cache.is_rule_agent_selected("CRC:8.11"))
        self.assertEqual(len(rows(self.window)), 9)

    def test_composited_category_states_contrast_and_pinned_exclusion(self):
        # Exercise GTK's actual cascade, including the generic case-list rules.
        # Cairo renders final backgrounds/frames/outlines without taking a
        # screenshot of the user's desktop. No private config is read.
        host = SimpleNamespace(_css_provider=None)
        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            OpenLawLensWindow._install_css(host)
        self.addCleanup(Gtk.StyleContext.remove_provider_for_display,
                        Gdk.Display.get_default(), host._css_provider)
        settings = Gtk.Settings.get_default()
        animations = settings.get_property("gtk-enable-animations")
        settings.set_property("gtk-enable-animations", False)
        self.addCleanup(settings.set_property, "gtk-enable-animations", animations)
        manager = Adw.StyleManager.get_default()
        original = manager.get_color_scheme()
        self.addCleanup(manager.set_color_scheme, original)
        self.window.render()
        cache_list = self.window.case_list
        pinned = Gtk.ListBox()
        pinned.add_css_class("case-list")
        pinned_row = Gtk.ListBoxRow()
        pinned_row.add_css_class("case-cache-row")
        # Even a stray category class must not bring cache styling to this list.
        pinned_row.add_css_class("cache-statutes")
        pinned.append(pinned_row)

        def rgb(color):
            return (color.red, color.green, color.blue)

        def blend(fg, bg, opacity):
            return tuple(a * opacity + b * (1 - opacity) for a, b in zip(fg, bg))

        def contrast(a, b):
            def lum(c):
                linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c]
                return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))
            values = sorted((lum(a), lum(b)))
            return (values[1] + .05) / (values[0] + .05)

        def paint(widget, bg, operation=Gtk.render_background, point=(50, 30)):
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 60)
            ctx = cairo.Context(surface)
            ctx.set_source_rgb(*bg)
            ctx.paint()
            if operation == Gtk.render_focus:
                # GTK 4.14's deprecated cairo render_focus erroneously renders
                # the frame; Snapshot.render_focus renders the actual outline.
                snapshot = Gtk.Snapshot()
                snapshot.render_focus(widget.get_style_context(), 0, 0, 100, 60)
                node = snapshot.to_node()
                if node is not None:
                    node.draw(ctx)
            else:
                operation(widget.get_style_context(), ctx, 0, 0, 100, 60)
            surface.flush()
            x, y = point
            offset = y * surface.get_stride() + x * 4
            b, g, r, _ = surface.get_data()[offset:offset + 4]
            return (r / 255, g / 255, b / 255)

        minima = {"text": 100, "subtitle": 100, "indicator": 100}
        for dark in (False, True):
            manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
            if dark:
                cache_list.add_css_class("cache-dark")
            else:
                cache_list.remove_css_class("cache-dark")
            hc = manager.get_high_contrast()
            if hc:
                cache_list.add_css_class("cache-high-contrast")
            context = cache_list.get_style_context()
            bg = rgb(context.lookup_color("window_bg_color")[1])
            fg = rgb(context.lookup_color("window_fg_color")[1])
            self.assertEqual(pinned_row.get_style_context().get_border().left, 0)
            self.assertEqual(paint(pinned_row, bg), tuple(round(v * 255) / 255 for v in bg))
            for row in rows(self.window):
                group = next(g for g in RESEARCH_CACHE_GROUPS if row.has_css_class(g.css_class))
                accent = Gdk.RGBA()
                accent.parse(group.dark if dark else group.light)
                header = not row.get_selectable()
                for hover, selected, focused, backdrop in (
                    (False, False, False, False), (True, False, False, False),
                    (False, True, False, False), (True, True, False, False),
                    (False, True, False, True), (True, True, True, False),
                    (True, False, True, False),
                ):
                    if header and (hover or selected or focused or backdrop):
                        continue
                    with self.subTest(dark=dark, hc=hc, group=group.key, header=header,
                                      hover=hover, selected=selected, focused=focused, backdrop=backdrop):
                        flags = Gtk.StateFlags.NORMAL
                        for active, flag in ((hover, Gtk.StateFlags.PRELIGHT), (selected, Gtk.StateFlags.SELECTED),
                                             (focused, Gtk.StateFlags.FOCUSED | Gtk.StateFlags.FOCUS_VISIBLE),
                                             (backdrop, Gtk.StateFlags.BACKDROP)):
                            if active:
                                flags |= flag
                        row.set_state_flags(flags, True)
                        opacity = ((.30 if dark else .21) if header else
                                   (.31 if dark else .23) if selected else
                                   (.23 if dark else .16) if hover else (.16 if dark else .10))
                        expected = blend(rgb(accent), bg, opacity)
                        foreground = fg
                        if hc:
                            expected = blend((0, 0, 0), rgb(context.lookup_color("theme_selected_bg_color")[1]), .10) if selected else bg
                            if selected:
                                foreground = rgb(context.lookup_color("theme_selected_fg_color")[1])
                        actual = paint(row, bg)
                        for a, b in zip(actual, expected):
                            self.assertAlmostEqual(a, b, delta=2 / 255)
                        self.assertEqual(row.get_style_context().get_border().left, 4)
                        edge = paint(row, actual, Gtk.render_frame, (1, 30))
                        edge_color = context.lookup_color("theme_selected_fg_color" if selected else "window_fg_color")[1] if hc else accent
                        expected_edge = blend(rgb(edge_color), actual, edge_color.alpha)
                        for a, b in zip(edge, expected_edge):
                            self.assertAlmostEqual(a, b, delta=2 / 255)
                        fg_alpha = context.lookup_color("theme_selected_fg_color" if hc and selected else "window_fg_color")[1].alpha
                        text_ratio = contrast(blend(foreground, actual, fg_alpha), actual)
                        subtitle_ratio = contrast(blend(foreground, actual, 1 if hc else .85), actual)
                        self.assertGreaterEqual(text_ratio, 4.5)
                        self.assertGreaterEqual(subtitle_ratio, 4.5)
                        minima["text"] = min(minima["text"], text_ratio)
                        minima["subtitle"] = min(minima["subtitle"], subtitle_ratio)
                        if selected or focused:
                            snapshot = Gtk.Snapshot()
                            snapshot.render_focus(row.get_style_context(), 0, 0, 100, 60)
                            outline_node = snapshot.to_node()
                            self.assertEqual(list(outline_node.get_widths()), [2 if focused else 1] * 4)
                            outline = paint(row, actual, Gtk.render_focus, (50, 0))
                            ratio = contrast(outline, actual)
                            self.assertGreaterEqual(ratio, 3)
                            minima["indicator"] = min(minima["indicator"], ratio)
                        if not header:
                            box = row.get_child()
                            subtitle = box.get_first_child().get_last_child()
                            if subtitle.has_css_class("dim-label"):
                                self.assertEqual(subtitle.get_opacity(), 1)
                                color = subtitle.get_style_context().get_color()
                                self.assertAlmostEqual(color.alpha, fg_alpha if hc else .85, places=2)
                            rail = box.get_last_child()
                            check = rail.get_last_child()
                            check_node = check.get_first_child()
                            for checked in (False, True):
                                check.set_active(checked)
                                border = paint(check_node, actual, Gtk.render_background, (50, 0))
                                self.assertGreaterEqual(contrast(border, actual), 3)
                                interior = paint(check_node, actual)
                                self.assertGreaterEqual(contrast(border, interior), 3)
                                minima["indicator"] = min(minima["indicator"], contrast(border, actual), contrast(border, interior))
                            if hover or selected:
                                color = rail.get_first_child().get_style_context().get_color()
                                ratio = contrast(blend(rgb(color), actual, color.alpha), actual)
                                self.assertGreaterEqual(ratio, 3)
                                minima["indicator"] = min(minima["indicator"], ratio)
        print("Research Cache composited contrast minima", minima)

    def test_css_and_appearance_notifications_preserve_rows(self):
        for selector_block in re.findall(r"([^{}]+)\{[^{}]*\}", RESEARCH_CACHE_CSS):
            for selector in selector_block.split(","):
                self.assertTrue(selector.strip().startswith("list.research-cache"), selector)
        provider = Gtk.CssProvider()
        errors = []
        provider.connect("parsing-error", lambda *args: errors.append(args))
        provider.load_from_data(RESEARCH_CACHE_CSS.encode())
        self.assertEqual(errors, [])
        window = Adw.Window()
        window.case_list = self.window.case_list
        window.set_content(window.case_list)
        self.window.render(select_rule_id="CRC:8.11")
        before = rows(self.window)
        selected = self.window.case_list.get_selected_row()
        checks = [r.get_child().get_last_child().get_last_child() for r in before if r.get_selectable()]
        checks[0].set_active(True)
        values = [check.get_active() for check in checks]
        metadata = self.cache.active_research_set_metadata()
        OpenLawLensWindow._watch_research_cache_appearance(window)
        manager = Adw.StyleManager.get_default()
        original = manager.get_color_scheme()
        try:
            for scheme in (Adw.ColorScheme.FORCE_DARK, Adw.ColorScheme.FORCE_LIGHT):
                manager.set_color_scheme(scheme)
                manager.notify("high-contrast")
                self.assertEqual(window.case_list.has_css_class("cache-dark"), manager.get_dark())
                self.assertEqual(window.case_list.has_css_class("cache-high-contrast"), manager.get_high_contrast())
                self.assertEqual(rows(self.window), before)
                self.assertIs(self.window.case_list.get_selected_row(), selected)
                self.assertEqual([check.get_active() for check in checks], values)
                self.assertEqual(self.cache.active_research_set_metadata(), metadata)
        finally:
            manager.set_color_scheme(original)
            window.destroy()


if __name__ == "__main__":
    unittest.main()
