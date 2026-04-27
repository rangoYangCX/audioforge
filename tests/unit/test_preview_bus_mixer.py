from __future__ import annotations

from audioforge.app.services.preview_bus_mixer import PreviewBusMixer


def test_preview_bus_mixer_computes_nested_bus_gain() -> None:
    mixer = PreviewBusMixer()
    mixer.sync_buses(["SFX", "UI"], {"UI": "SFX"})
    mixer.set_state("Master", volume_linear=0.5, is_muted=False)
    mixer.set_state("SFX", volume_linear=0.8, is_muted=False)
    mixer.set_state("UI", volume_linear=0.5, is_muted=False)

    assert mixer.effective_gain_linear("UI") == 0.2
    assert mixer.describe_bus("UI") == "UI -> SFX -> Master | 20%"


def test_preview_bus_mixer_returns_zero_for_muted_parent_bus() -> None:
    mixer = PreviewBusMixer()
    mixer.sync_buses(["SFX", "UI"], {"UI": "SFX"})
    mixer.set_state("SFX", volume_linear=1.0, is_muted=True)

    assert mixer.effective_gain_linear("UI") == 0.0