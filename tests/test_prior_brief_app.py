from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_law_lens.app import OpenLawLensApp, OpenLawLensWindow, build_agent_launch_env
from open_law_lens.agent import QuoteTarget
from open_law_lens.config import AppConfig
from open_law_lens.prior_briefs import PriorBrief


class PriorBriefAppTests(unittest.TestCase):
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
        )

        class Cache:
            def __init__(self) -> None:
                self.payload: dict[str, object] | None = None

            def read_prior_brief(self, _brief_id: str) -> dict[str, object] | None:
                return self.payload

            def upsert_prior_brief(self, payload: dict[str, object]) -> str:
                self.payload = payload
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
                self.cache_refreshes = 0
                self.pending_targets_at_render: list[QuoteTarget | None] = []

            def _load_cached_cases(self) -> None:
                self.cache_refreshes += 1

            def _capture_current_reader_position(self) -> None:
                pass

            def _set_reader_position_key(self, *_args: object) -> None:
                pass

            def _set_reader_header(self, *_args: object) -> None:
                pass

            def _set_reader_text(self, text: str) -> None:
                self.rendered = text
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
        OpenLawLensWindow._open_prior_brief(window, brief.brief_id)  # type: ignore[arg-type]

        self.assertEqual(window.client.cache.payload["title"], brief.title)
        self.assertEqual(window.cache_refreshes, 1)
        self.assertEqual(window.rendered, brief.text)
        self.assertIs(window.pending_targets_at_render[0], target)
        self.assertNotIn("Added to Research Cache", window.status)

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
                AppConfig(),
            )
            (workspace / "prior_briefs.sqlite3").write_bytes(b"db")
            with_snapshot = build_agent_launch_env(
                client,  # type: ignore[arg-type]
                workspace / "prompt.txt",
                workspace,
                "brief",
                AppConfig(),
            )

        self.assertNotIn("OPEN_LAW_LENS_PRIOR_BRIEFS_DB", without)
        self.assertEqual(
            with_snapshot["OPEN_LAW_LENS_PRIOR_BRIEFS_DB"],
            str(workspace / "prior_briefs.sqlite3"),
        )


if __name__ == "__main__":
    unittest.main()
