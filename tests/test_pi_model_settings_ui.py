from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_law_lens.app import SettingsWindow
from open_law_lens.pi_runtime import PiModel


class FakeComboRow:
    def __init__(self) -> None:
        self.selected = 0
        self.model: object = None
        self.sensitive = False
        self.subtitle = ""

    def get_selected(self) -> int:
        return self.selected

    def set_selected(self, selected: int) -> None:
        self.selected = selected

    def set_model(self, model: object) -> None:
        self.model = model

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle = subtitle


class FakeButton:
    def __init__(self) -> None:
        self.sensitive = False

    def set_sensitive(self, sensitive: bool) -> None:
        self.sensitive = sensitive


def model_window(
    original: tuple[str, str] | None,
) -> SimpleNamespace:
    window = SimpleNamespace(
        _pi_model_closed=False,
        _pi_model_generation=1,
        _pi_model_options=[],
        _pi_model_applying=False,
        _pi_model_selection_changed=False,
        _original_pi_model_key=original,
        pi_model_row=FakeComboRow(),
        pi_model_refresh_button=FakeButton(),
    )
    window._selected_pi_model = lambda: SettingsWindow._selected_pi_model(  # type: ignore[arg-type]
        window
    )
    window._update_pi_model_subtitle = (  # type: ignore[attr-defined]
        lambda: SettingsWindow._update_pi_model_subtitle(window)  # type: ignore[arg-type]
    )
    return window


class PiModelSettingsUiTests(unittest.TestCase):
    def test_available_models_select_current_project_model(self) -> None:
        window = model_window(("openai-codex", "gpt-5.6-sol"))
        models = [
            PiModel(
                provider="fireworks",
                model_id="accounts/fireworks/models/glm-5p2",
                name="GLM 5.2",
            ),
            PiModel(
                provider="openai-codex",
                model_id="gpt-5.6-sol",
                name="GPT-5.6 Sol",
            ),
        ]

        with patch(
            "open_law_lens.app.Gtk.StringList.new",
            side_effect=lambda labels: list(labels),
        ):
            result = SettingsWindow._finish_pi_model_load(  # type: ignore[arg-type]
                window,
                1,
                models,
                "",
                ("openai-codex", "gpt-5.6-sol"),
            )

        self.assertFalse(result)
        self.assertEqual(window.pi_model_row.selected, 1)
        self.assertTrue(window.pi_model_row.sensitive)
        self.assertFalse(window._pi_model_selection_changed)
        self.assertEqual(
            window.pi_model_row.subtitle,
            "Project-wide setting: openai-codex / gpt-5.6-sol",
        )

    def test_unavailable_current_model_is_preserved(self) -> None:
        window = model_window(("openai-codex", "retired-model"))
        available = PiModel(
            provider="fireworks",
            model_id="accounts/fireworks/models/glm-5p2",
            name="GLM 5.2",
        )

        with patch(
            "open_law_lens.app.Gtk.StringList.new",
            side_effect=lambda labels: list(labels),
        ):
            SettingsWindow._finish_pi_model_load(  # type: ignore[arg-type]
                window,
                1,
                [available],
                "",
                ("openai-codex", "retired-model"),
            )

        self.assertEqual(window.pi_model_row.selected, 0)
        self.assertTrue(window.pi_model_row.sensitive)
        self.assertFalse(window._pi_model_selection_changed)
        self.assertIn(
            "currently configured; unavailable",
            window.pi_model_row.model[0],
        )

        window.pi_model_row.selected = 1
        SettingsWindow._on_pi_model_selected(  # type: ignore[arg-type]
            window,
            window.pi_model_row,
            object(),
        )
        self.assertTrue(window._pi_model_selection_changed)

    def test_model_query_failure_disables_row_without_changing_model(self) -> None:
        window = model_window(("openai-codex", "gpt-5.6-sol"))

        with patch(
            "open_law_lens.app.Gtk.StringList.new",
            side_effect=lambda labels: list(labels),
        ):
            SettingsWindow._finish_pi_model_load(  # type: ignore[arg-type]
                window,
                1,
                [],
                "Pi model query failed.",
                ("openai-codex", "gpt-5.6-sol"),
            )

        self.assertFalse(window.pi_model_row.sensitive)
        self.assertTrue(window.pi_model_refresh_button.sensitive)
        self.assertEqual(window.pi_model_row.subtitle, "Pi model query failed.")
        self.assertEqual(
            window._selected_pi_model().settings_key,
            ("openai-codex", "gpt-5.6-sol"),
        )
