from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_law_lens.app import SettingsWindow
from open_law_lens.config import (
    AGENT_PROFILE_KEYS,
    AGENT_PROFILE_LAW,
    PiAgentProfile,
)
from open_law_lens.pi_runtime import PiModel, PiRuntimeCatalog


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
    original: dict[str, PiAgentProfile] | None = None,
) -> SimpleNamespace:
    window = SimpleNamespace(
        _pi_model_closed=False,
        _pi_model_generation=1,
        _pi_model_applying=False,
        _pi_profiles_ready=False,
        _pi_runtime_catalog=None,
        _pi_profile_model_rows={key: FakeComboRow() for key in AGENT_PROFILE_KEYS},
        _pi_profile_thinking_rows={key: FakeComboRow() for key in AGENT_PROFILE_KEYS},
        _pi_profile_model_options={},
        _pi_profile_thinking_options={},
        _pi_profile_adjustment_notes={},
        _original_pi_profiles=dict(original or {}),
        pi_model_refresh_button=FakeButton(),
    )
    window._selected_pi_model = lambda key: SettingsWindow._selected_pi_model(  # type: ignore[arg-type]
        window, key
    )
    window._selected_pi_thinking = (  # type: ignore[attr-defined]
        lambda key: SettingsWindow._selected_pi_thinking(window, key)  # type: ignore[arg-type]
    )
    window._selected_pi_profile = (  # type: ignore[attr-defined]
        lambda key: SettingsWindow._selected_pi_profile(window, key)  # type: ignore[arg-type]
    )
    window._selected_pi_profiles = (  # type: ignore[attr-defined]
        lambda: SettingsWindow._selected_pi_profiles(window)  # type: ignore[arg-type]
    )
    window._pi_model_is_available = (  # type: ignore[attr-defined]
        lambda model: SettingsWindow._pi_model_is_available(window, model)  # type: ignore[arg-type]
    )
    window._populate_pi_thinking_row = (  # type: ignore[attr-defined]
        lambda key, preferred: SettingsWindow._populate_pi_thinking_row(  # type: ignore[arg-type]
            window, key, preferred
        )
    )
    window._update_pi_profile_model_subtitle = (  # type: ignore[attr-defined]
        lambda key: SettingsWindow._update_pi_profile_model_subtitle(  # type: ignore[arg-type]
            window, key
        )
    )
    return window


class PiModelSettingsUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sol = PiModel(
            provider="openai-codex",
            model_id="gpt-5.6-sol",
            name="GPT-5.6 Sol",
            supported_thinking_levels=(
                "off",
                "minimal",
                "low",
                "medium",
                "high",
                "xhigh",
                "max",
            ),
        )
        self.fast = PiModel(
            provider="fireworks",
            model_id="accounts/fireworks/routers/glm-fast",
            name="GLM Fast",
            supported_thinking_levels=("off", "minimal", "low", "medium", "high"),
        )

    def _finish(
        self,
        window: SimpleNamespace,
        catalog: PiRuntimeCatalog | None,
        error: str = "",
        desired: dict[str, PiAgentProfile] | None = None,
    ) -> None:
        with patch(
            "open_law_lens.app.Gtk.StringList.new",
            side_effect=lambda labels: list(labels),
        ):
            result = SettingsWindow._finish_pi_model_load(  # type: ignore[arg-type]
                window,
                1,
                catalog,
                error,
                dict(desired or {}),
            )
        self.assertFalse(result)

    def test_missing_profiles_inherit_effective_pi_defaults(self) -> None:
        window = model_window()
        catalog = PiRuntimeCatalog(
            models=(self.fast, self.sol),
            default_model=self.sol,
            default_thinking_level="medium",
        )

        self._finish(window, catalog)

        for key in AGENT_PROFILE_KEYS:
            self.assertIsNone(window._selected_pi_model(key))
            self.assertEqual(window._selected_pi_thinking(key), "medium")
            self.assertFalse(window._pi_profile_thinking_rows[key].sensitive)
        self.assertEqual(window._selected_pi_profiles(), {})
        self.assertTrue(window._pi_profiles_ready)

    def test_explicit_profile_selects_model_and_supported_reasoning(self) -> None:
        profile = PiAgentProfile(
            provider=self.sol.provider,
            model=self.sol.model_id,
            thinking="max",
        )
        window = model_window({AGENT_PROFILE_LAW: profile})
        catalog = PiRuntimeCatalog(
            models=(self.fast, self.sol),
            default_model=self.sol,
            default_thinking_level="medium",
        )

        self._finish(window, catalog, desired={AGENT_PROFILE_LAW: profile})

        self.assertEqual(
            window._selected_pi_model(AGENT_PROFILE_LAW).settings_key,
            self.sol.settings_key,
        )
        self.assertEqual(window._selected_pi_thinking(AGENT_PROFILE_LAW), "max")
        self.assertTrue(
            window._pi_profile_thinking_rows[AGENT_PROFILE_LAW].sensitive
        )

    def test_unsupported_reasoning_moves_to_nearest_supported_level(self) -> None:
        profile = PiAgentProfile(
            provider=self.fast.provider,
            model=self.fast.model_id,
            thinking="max",
        )
        window = model_window({AGENT_PROFILE_LAW: profile})
        catalog = PiRuntimeCatalog(
            models=(self.fast, self.sol),
            default_model=self.sol,
            default_thinking_level="medium",
        )

        self._finish(window, catalog, desired={AGENT_PROFILE_LAW: profile})

        self.assertEqual(window._selected_pi_thinking(AGENT_PROFILE_LAW), "high")
        self.assertIn(
            "Max is unsupported",
            window._pi_profile_thinking_rows[AGENT_PROFILE_LAW].subtitle,
        )

    def test_unavailable_configured_model_is_preserved(self) -> None:
        profile = PiAgentProfile(
            provider="openai-codex",
            model="retired-model",
            thinking="xhigh",
        )
        window = model_window({AGENT_PROFILE_LAW: profile})
        catalog = PiRuntimeCatalog(
            models=(self.fast,),
            default_model=self.fast,
            default_thinking_level="low",
        )

        self._finish(window, catalog, desired={AGENT_PROFILE_LAW: profile})

        selected = window._selected_pi_model(AGENT_PROFILE_LAW)
        self.assertEqual(selected.settings_key, ("openai-codex", "retired-model"))
        self.assertEqual(window._selected_pi_thinking(AGENT_PROFILE_LAW), "xhigh")
        self.assertFalse(
            window._pi_profile_thinking_rows[AGENT_PROFILE_LAW].sensitive
        )
        self.assertIn(
            "configured; unavailable",
            window._pi_profile_model_rows[AGENT_PROFILE_LAW].model[1],
        )

    def test_model_query_failure_preserves_existing_profiles(self) -> None:
        profile = PiAgentProfile(
            provider=self.sol.provider,
            model=self.sol.model_id,
            thinking="high",
        )
        window = model_window({AGENT_PROFILE_LAW: profile})

        self._finish(
            window,
            None,
            "Pi model query failed.",
            desired={AGENT_PROFILE_LAW: profile},
        )

        self.assertFalse(window._pi_profiles_ready)
        self.assertFalse(window._pi_profile_model_rows[AGENT_PROFILE_LAW].sensitive)
        self.assertEqual(
            window._selected_pi_profile(AGENT_PROFILE_LAW),
            profile,
        )
        self.assertEqual(
            window._pi_profile_model_rows[AGENT_PROFILE_LAW].subtitle,
            "Pi model query failed.",
        )


if __name__ == "__main__":
    unittest.main()
