"""Presentation tests: real GTK rows, private temporary storage, no network."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from open_law_lens.app import (
    Adw, Gtk, OpenLawLensWindow, RESEARCH_CACHE_CSS, RESEARCH_CACHE_GROUPS,
)
from open_law_lens.cache import JsonCache
from open_law_lens.library import CaseLibrary


def seed(cache):
    cache.ensure()
    cache.upsert_cluster({"id": 42, "case_name": "Example v. State", "citations": [{"volume": 1, "reporter": "Cal.", "page": "2"}]})
    cache.upsert_statute({"statute_id": "WIC:300", "title": "Synthetic statute", "text": "Statute text"})
    cache.upsert_rule({"rule_id": "CRC:8.11", "title": "California Rules of Court, rule 8.11", "text": "Rule text"})
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
        self.window.render(select_first=True)
        self.assertIn(self.window.case_list.get_selected_row()._open_law_lens_authority_type, ("statute", "rule"))

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

    def test_css_and_appearance_notifications_preserve_rows(self):
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
        finally:
            manager.set_color_scheme(original)
            window.destroy()


if __name__ == "__main__":
    unittest.main()
