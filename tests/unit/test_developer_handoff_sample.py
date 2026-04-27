from __future__ import annotations

from pathlib import Path

from audioforge.app.services.validator import ProjectValidator
from tests.helpers import write_wav_fixture
from tools.generate_developer_handoff_sample import build_developer_handoff_project


def test_developer_handoff_project_covers_expected_runtime_behaviors(tmp_path: Path) -> None:
    names = [
        "UIClick_CLICK-Classic_B00M_CUDS.wav",
        "UIClick_CLICK-Drip_B00M_CUDS.wav",
        "UIClick_CLICK-Playful_B00M_CUDS.wav",
        "UIClick_CLICK-Woody_B00M_CUDS.wav",
        "UIClick_CONFIRM-Check_B00M_CUDS.wav",
        "UIClick_CONFIRM-Ok_B00M_CUDS.wav",
        "UIClick_CONFIRM-Enter_B00M_CUDS.wav",
        "UIClick_CONFIRM-Yes Please_B00M_CUDS.wav",
        "UIMisc_ZAP-Fast Flip_B00M_CUDS.wav",
        "UIMisc_ZAP-Kickflip_B00M_CUDS.wav",
        "UIMisc_ZAP-Zippy_B00M_CUDS.wav",
        "UIMisc_DENY-No Entry_B00M_CUDS.wav",
        "UIMisc_DENY-Stop_B00M_CUDS.wav",
        "UIMvmt_WHOOSH NEUTRAL-Wind Blow_B00M_CUDS.wav",
        "UIMvmt_WHOOSH POSITIVE-Reward Reveal_B00M_CUDS.wav",
        "UIMvmt_WHOOSH POSITIVE-Winning Streak_B00M_CUDS.wav",
        "UIMvmt_POP UP-Tutorial_B00M_CUDS.wav",
        "UIMvmt_POP UP-Upfront_B00M_CUDS.wav",
        "UIMisc_MATCH-Align_B00M_CUDS.wav",
        "UIMisc_MATCH-Building Blocks_B00M_CUDS.wav",
        "UIMisc_MATCH-Waterworld_B00M_CUDS.wav",
        "MAGPoof_POOF-Bubble Stumble_B00M_CUDS.wav",
        "MAGPoof_POOF-Charm_B00M_CUDS.wav",
        "MAGPoof_POOF-Chaser_B00M_CUDS.wav",
        "MAGPoof_POOF-Fizzflip_B00M_CUDS.wav",
        "MAGPoof_POOF-Fizzleburst_B00M_CUDS.wav",
        "MAGPoof_POOF-Mystery Box_B00M_CUDS.wav",
        "MAGPoof_POOF-Nerfed_B00M_CUDS.wav",
        "MAGPoof_POOF-Neutral Zap_B00M_CUDS.wav",
    ]
    wav_files: list[Path] = []
    for index, name in enumerate(names, start=1):
        wav_files.append(write_wav_fixture(tmp_path / name, frequency_hz=220.0 + index * 10.0))

    project, coverage_entries = build_developer_handoff_project(sorted(wav_files), tmp_path / "Export")
    issues = ProjectValidator().validate(project)

    assert not [issue for issue in issues if issue.severity == "Error"]
    assert len(coverage_entries) == 11
    assert "UI_Click_RandomWeighted" in project.events
    assert "UI_Confirm_Sequence" in project.events
    assert "UI_Zap_Combo" in project.events
    assert "UI_Deny_Cooldown" in project.events
    assert "UI_Whoosh_RejectNew" in project.events
    assert "UI_Whoosh_StopOldest" in project.events
    assert "UI_Popup_TrimLoop_Metadata" in project.events
    assert "UI_Match_PitchRandom" in project.events
    assert "SFX_Poof_RandomWeighted" in project.events
    assert "SFX_Poof_Sequence" in project.events
    assert "BGM_Menu_ProxyLoop" in project.events
    assert project.events["UI_Click_RandomWeighted"].avoid_immediate_repeat is True
    assert project.events["UI_Zap_Combo"].play_mode == "Combo"
    assert project.events["UI_Deny_Cooldown"].cooldown_seconds == 0.35
    assert project.events["UI_Whoosh_StopOldest"].steal_policy == "StopOldest"
    assert project.events["UI_Popup_TrimLoop_Metadata"].clips[0].trim_start_ms == 5
    assert project.events["BGM_Menu_ProxyLoop"].bus == "BGM"