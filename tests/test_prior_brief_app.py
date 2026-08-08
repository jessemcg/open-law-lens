from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from open_law_lens.app import (
    QUERY_MODE_BRIEF_SEARCH,
    OpenLawLensApp,
    OpenLawLensWindow,
    PriorBriefPhraseGroup,
    build_agent_launch_env,
    prior_brief_reader_masthead,
)
from open_law_lens.agent import QuoteTarget
from open_law_lens.config import AppConfig
from open_law_lens.prior_briefs import PriorBrief, PriorBriefHeading


class PriorBriefAppTests(unittest.TestCase):
    @staticmethod
    def _brief(
        brief_id: str,
        title: str,
        text: str,
        document_date: str,
    ) -> PriorBrief:
        return PriorBrief(
            brief_id=brief_id,
            relative_path=f"{title}.odt",
            source_path=f"/archive/{title}.odt",
            title=title,
            case_number=title.split("_", 1)[0],
            document_type="Appellant's opening brief",
            document_date=document_date,
            date_source="document_signature",
            text=text,
            sha256="b" * 64,
            file_size=len(text),
            file_mtime_ns=20,
            indexed_at="2026-07-29T00:00:00+00:00",
        )

    def test_speech_brief_dbus_action_submits_brief_mode(self) -> None:
        calls: list[str] = []
        window = type(
            "Window",
            (),
            {"submit_speech_question": lambda _self, mode: calls.append(mode)},
        )()
        app = type("App", (), {"_main_window": lambda _self: window})()

        OpenLawLensApp._on_submit_speech_brief_question(  # type: ignore[arg-type]
            app,
            object(),
            None,
        )

        self.assertEqual(calls, ["brief"])

    def test_following_brief_link_adds_brief_to_cache_before_display(self) -> None:
        brief = PriorBrief(
            brief_id="a" * 64,
            relative_path="B348009_RB_Breana_R.odt",
            source_path="/archive/B348009_RB_Breana_R.odt",
            title="B348009_RB_Breana_R",
            case_number="B348009",
            document_type="Respondent's brief",
            document_date="2026-06-08",
            date_source="document_signature",
            text="Reasonable, credible, and of solid value.",
            sha256="b" * 64,
            file_size=10,
            file_mtime_ns=20,
            indexed_at="2026-07-11T00:00:00+00:00",
            heading_spans=(
                PriorBriefHeading(1, 0, 10),
                PriorBriefHeading(2, 12, 20),
            ),
        )

        class Cache:
            def __init__(self) -> None:
                self.payload: dict[str, object] | None = None
                self.mark_dirty_values: list[bool] = []

            def read_prior_brief(self, _brief_id: str) -> dict[str, object] | None:
                return self.payload

            def upsert_prior_brief(
                self,
                payload: dict[str, object],
                *,
                mark_dirty: bool = True,
            ) -> str:
                self.payload = payload
                self.mark_dirty_values.append(mark_dirty)
                return str(payload["brief_id"])

        class CaseList:
            def unselect_all(self) -> None:
                pass

        class Window:
            def __init__(self) -> None:
                self.prior_briefs = type("Library", (), {"read": lambda _self, _id: brief})()
                self.client = type("Client", (), {"cache": Cache()})()
                self.case_list = CaseList()
                self._selected_cluster = None
                self._selected_statute = None
                self._selected_rule = None
                self._selected_agent_answer = None
                self._selected_prior_brief = None
                self._pending_quote_target = None
                self.status = ""
                self.rendered = ""
                self.headers: list[tuple[str, str]] = []
                self.rendered_style_spans = []
                self.cache_refreshes = 0
                self.pending_targets_at_render: list[QuoteTarget | None] = []

            def _load_cached_cases(self) -> None:
                self.cache_refreshes += 1

            def _capture_current_reader_position(self) -> None:
                pass

            def _set_reader_position_key(self, *_args: object) -> None:
                pass

            def _set_reader_header(
                self,
                text: str,
                _citation: object = None,
                _cluster: object = None,
                subtitle: str = "",
            ) -> None:
                self.headers.append((text, subtitle))

            def _set_reader_text(self, text: str, *, style_spans=None) -> None:
                self.rendered = text
                self.rendered_style_spans = list(style_spans or [])
                self.pending_targets_at_render.append(self._pending_quote_target)
                self._pending_quote_target = None

            def _set_status(self, text: str) -> None:
                self.status = text

        window = Window()
        target = QuoteTarget(
            phrase="reasonable, credible, and of solid value",
            cluster_id="",
            opinion_id="",
            title=brief.title,
            citation=brief.document_date,
            text_path=brief.source_path,
            offset=0,
            end_offset=39,
            authority_type="prior_brief",
            prior_brief_id=brief.brief_id,
        )

        OpenLawLensWindow._open_prior_brief(  # type: ignore[arg-type]
            window,
            brief.brief_id,
            target,
        )
        window.client.cache.payload["heading_spans"] = []
        OpenLawLensWindow._open_prior_brief(window, brief.brief_id)  # type: ignore[arg-type]

        self.assertEqual(window.client.cache.payload["title"], brief.title)
        self.assertEqual(window.cache_refreshes, 1)
        self.assertEqual(window.client.cache.mark_dirty_values, [True, False])
        self.assertEqual(window.rendered, brief.text)
        self.assertEqual(
            window.headers,
            [
                ("B348009_RB_Breana_R", "June 8, 2026"),
                ("B348009_RB_Breana_R", "June 8, 2026"),
            ],
        )
        self.assertEqual(
            [span.kind for span in window.rendered_style_spans],
            ["heading", "brief-subheading"],
        )
        self.assertIs(window.pending_targets_at_render[0], target)
        self.assertNotIn("Added to Research Cache", window.status)

    def test_prior_brief_masthead_uses_title_and_formatted_date(self) -> None:
        brief = self._brief(
            "a" * 64,
            "B348009_RB_Breana_R",
            "Brief text.",
            "2026-06-08",
        )

        masthead = prior_brief_reader_masthead(brief)

        self.assertEqual(masthead.title, "B348009_RB_Breana_R")
        self.assertEqual(masthead.metadata, "June 8, 2026")

    def test_inline_markdown_renders_internal_brief_link_as_title(self) -> None:
        brief_id = "a" * 64
        raw = f"[B353817_AOB](open-law-lens://prior-brief/{brief_id})"

        rendered, spans, offsets = OpenLawLensWindow._render_inline_markdown(  # type: ignore[arg-type]
            object(),
            raw,
            0,
        )

        self.assertEqual(rendered, "B353817_AOB")
        self.assertEqual(spans, [(0, len(rendered), f"prior_brief:{brief_id}")])
        self.assertEqual(offsets[-1], len(rendered))

    def test_brief_prompt_includes_snapshot_and_optional_socf_state(self) -> None:
        window = type(
            "Window",
            (),
            {"_format_agent_prompt": OpenLawLensWindow._format_agent_prompt},
        )()
        with patch("open_law_lens.app.load_config", return_value=AppConfig()):
            prompt = OpenLawLensWindow._compose_brief_agent_prompt(  # type: ignore[arg-type]
                window,
                "Find ICWA arguments",
                Path("/tmp/prior_briefs.sqlite3"),
                381,
                current_case_selected=False,
            )

        self.assertIn("Find ICWA arguments", prompt)
        self.assertIn("/tmp/prior_briefs.sqlite3", prompt)
        self.assertIn("Indexed brief count: 381", prompt)
        self.assertIn("Not selected", prompt)

    def test_launch_env_exposes_workspace_brief_snapshot_only_when_present(self) -> None:
        client = type("Client", (), {"library": None})()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            without = build_agent_launch_env(
                client,  # type: ignore[arg-type]
                workspace / "prompt.txt",
                workspace,
                "brief",
            )
            (workspace / "prior_briefs.sqlite3").write_bytes(b"db")
            with_snapshot = build_agent_launch_env(
                client,  # type: ignore[arg-type]
                workspace / "prompt.txt",
                workspace,
                "brief",
            )

        self.assertNotIn("OPEN_LAW_LENS_PRIOR_BRIEFS_DB", without)
        self.assertEqual(
            with_snapshot["OPEN_LAW_LENS_PRIOR_BRIEFS_DB"],
            str(workspace / "prior_briefs.sqlite3"),
        )

    def test_search_mode_launches_local_phrase_search_without_terminal(self) -> None:
        searches: list[str] = []
        window = type(
            "Window",
            (),
            {
                "_selected_agent_mode": QUERY_MODE_BRIEF_SEARCH,
                "agent_question_entry": type(
                    "Entry",
                    (),
                    {"get_text": lambda _self: " beneficial relationship "},
                )(),
                "_start_brief_phrase_search": lambda _self, query: searches.append(
                    query
                ),
            },
        )()

        with patch("open_law_lens.app.Vte", None):
            OpenLawLensWindow._on_agent_launch(window, object())  # type: ignore[arg-type]

        self.assertEqual(searches, ["beneficial relationship"])

    def test_cross_brief_navigation_cycles_occurrences_and_briefs(self) -> None:
        first = self._brief(
            "a" * 64,
            "B353817_AOB_Joseph_A",
            "alpha ... alpha",
            "2026-07-29",
        )
        second = self._brief(
            "b" * 64,
            "B352055_AOB_Kristen_G",
            "alpha",
            "2026-07-28",
        )

        class Window:
            def __init__(self) -> None:
                self._brief_search_groups = [
                    PriorBriefPhraseGroup(first, ((0, 5), (10, 15))),
                    PriorBriefPhraseGroup(second, ((0, 5),)),
                ]
                self._brief_search_brief_index = 0
                self._brief_search_match_index = 0
                self.visited: list[tuple[int, int]] = []

            def _show_current_brief_search_hit(self) -> None:
                self.visited.append(
                    (
                        self._brief_search_brief_index,
                        self._brief_search_match_index,
                    )
                )

        window = Window()
        for direction in (1, 1, 1, -1):
            OpenLawLensWindow._move_brief_search_match(  # type: ignore[arg-type]
                window,
                direction,
            )

        self.assertEqual(
            window.visited,
            [(0, 1), (1, 0), (0, 0), (1, 0)],
        )

    def test_search_hit_displays_without_cache_or_position_persistence(self) -> None:
        brief = self._brief(
            "a" * 64,
            "B353817_AOB_Joseph_A",
            "beneficial relationship",
            "2026-07-29",
        )
        displays: list[dict[str, object]] = []

        class Window:
            _brief_search_groups = [
                PriorBriefPhraseGroup(brief, ((0, len(brief.text)),))
            ]
            _brief_search_brief_index = 0
            _brief_search_match_index = 0
            _brief_search_total_matches = 1
            _brief_search_warning = ""
            _rendering_brief_search_hit = False

            def _display_prior_brief(
                self,
                displayed: PriorBrief,
                **options: object,
            ) -> None:
                displays.append({"brief": displayed, **options})

            def _apply_brief_search_tags(
                self,
                _group: PriorBriefPhraseGroup,
            ) -> None:
                pass

            def _set_status(self, _text: str) -> None:
                pass

        OpenLawLensWindow._show_current_brief_search_hit(  # type: ignore[arg-type]
            Window()
        )

        self.assertEqual(
            displays,
            [
                {
                    "brief": brief,
                    "set_status": False,
                    "persist_position": False,
                }
            ],
        )

    def test_search_hit_scrolls_after_brief_layout_and_confirms_visibility(self) -> None:
        brief = self._brief(
            "a" * 64,
            "B353817_AOB_Joseph_A",
            "introductory text beneficial relationship conclusion",
            "2026-07-29",
        )
        start = brief.text.index("beneficial relationship")
        end = start + len("beneficial relationship")

        class Buffer:
            def __init__(self) -> None:
                self.applied: list[tuple[object, int, int]] = []
                self.cursor_offset = -1

            def get_start_iter(self) -> int:
                return 0

            def get_end_iter(self) -> int:
                return len(brief.text)

            def remove_tag(
                self,
                _tag: object,
                _start: int,
                _end: int,
            ) -> None:
                pass

            def get_iter_at_offset(self, offset: int) -> int:
                return offset

            def apply_tag(self, tag: object, start_iter: int, end_iter: int) -> None:
                self.applied.append((tag, start_iter, end_iter))

            def place_cursor(self, iter_: int) -> None:
                self.cursor_offset = iter_

        class View:
            def __init__(self) -> None:
                self.visible_y = 0
                self.scrolls: list[tuple[int, float, bool, float, float]] = []

            def get_iter_location(self, iter_: int) -> object:
                return type("Rect", (), {"y": iter_, "height": 1})()

            def get_visible_rect(self) -> object:
                return type(
                    "Rect",
                    (),
                    {"y": self.visible_y, "height": 10},
                )()

            def scroll_to_iter(
                self,
                iter_: int,
                margin: float,
                use_align: bool,
                xalign: float,
                yalign: float,
            ) -> bool:
                self.scrolls.append(
                    (iter_, margin, use_align, xalign, yalign)
                )
                self.visible_y = iter_ - 2
                return True

        class Window:
            _brief_search_generation = 7
            _brief_search_groups = [
                PriorBriefPhraseGroup(brief, ((start, end),))
            ]
            _brief_search_brief_index = 0
            _brief_search_match_index = 0
            _selected_agent_mode = QUERY_MODE_BRIEF_SEARCH
            _selected_prior_brief = brief
            _reader_brief_search_tag = object()
            _reader_brief_search_current_tag = object()

            def __init__(self) -> None:
                self.reader_buffer = Buffer()
                self.reader_view = View()

            def _clear_brief_search_tags(self) -> None:
                OpenLawLensWindow._clear_brief_search_tags(self)  # type: ignore[arg-type]

            def _scroll_brief_search_hit_after_layout(
                self,
                *args: object,
            ) -> bool:
                return OpenLawLensWindow._scroll_brief_search_hit_after_layout(
                    self,  # type: ignore[arg-type]
                    *args,
                )

        window = Window()
        group = PriorBriefPhraseGroup(brief, ((start, end),))

        queued: list[tuple[Callable[..., object], tuple[object, ...]]] = []

        def queue_callback(
            callback: Callable[..., object],
            *args: object,
        ) -> None:
            queued.append((callback, args))

        with (
            patch(
                "open_law_lens.app.GLib.idle_add",
                side_effect=queue_callback,
            ),
            patch(
                "open_law_lens.app.GLib.timeout_add",
                side_effect=lambda _delay, callback, *args: queue_callback(
                    callback,
                    *args,
                ),
            ),
        ):
            OpenLawLensWindow._apply_brief_search_tags(  # type: ignore[arg-type]
                window,
                group,
            )
            callback, args = queued.pop(0)
            callback(*args)
            callback, args = queued.pop(0)
            callback(*args)

        self.assertEqual(window.reader_buffer.cursor_offset, start)
        self.assertEqual(
            window.reader_view.scrolls,
            [(start, 0.15, True, 0.0, 0.2)],
        )
        self.assertEqual(queued, [])

    def test_stale_search_scroll_does_not_override_new_match(self) -> None:
        brief = self._brief(
            "a" * 64,
            "B353817_AOB_Joseph_A",
            "alpha middle alpha",
            "2026-07-29",
        )

        class View:
            def __init__(self) -> None:
                self.scroll_count = 0

            def get_iter_location(self, _iter: int) -> object:
                return type("Rect", (), {"y": 100, "height": 1})()

            def get_visible_rect(self) -> object:
                return type("Rect", (), {"y": 0, "height": 10})()

            def scroll_to_iter(self, *_args: object) -> None:
                self.scroll_count += 1

        window = type(
            "Window",
            (),
            {
                "_brief_search_generation": 3,
                "_brief_search_groups": [
                    PriorBriefPhraseGroup(brief, ((0, 5), (13, 18)))
                ],
                "_brief_search_brief_index": 0,
                "_brief_search_match_index": 1,
                "_selected_agent_mode": QUERY_MODE_BRIEF_SEARCH,
                "_selected_prior_brief": brief,
                "reader_buffer": type(
                    "Buffer",
                    (),
                    {"get_iter_at_offset": lambda _self, offset: offset},
                )(),
                "reader_view": View(),
            },
        )()

        result = OpenLawLensWindow._scroll_brief_search_hit_after_layout(  # type: ignore[arg-type]
            window,
            3,
            brief.brief_id,
            0,
            0,
            0,
        )

        self.assertFalse(result)
        self.assertEqual(window.reader_view.scroll_count, 0)


if __name__ == "__main__":
    unittest.main()
