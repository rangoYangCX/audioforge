from __future__ import annotations

from audioforge.app.models.audio_project import (
    ClipModel,
    CurvePointModel,
    EventModel,
    GameParameterModel,
    RtpcBindingModel,
    StateGroupModel,
    StateOverrideModel,
    SwitchGroupModel,
    SwitchVariantModel,
)
from audioforge.app.services.preview_service import PreviewGameSyncContext, PreviewService

from tests.helpers import build_sample_project, write_wav_fixture


def test_preview_service_rejects_missing_clip_source_file(tmp_path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    event = project.events["UiClick"]
    wav_path.unlink()

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is False
    assert "not found" in result.reason
    assert str(wav_path) in result.reason


def test_preview_service_uses_active_binding_for_one_shot(tmp_path) -> None:
    primary_path = write_wav_fixture(tmp_path / "fixtures" / "primary.wav", frequency_hz=440.0)
    alternate_path = write_wav_fixture(tmp_path / "fixtures" / "alternate.wav", frequency_hz=660.0)
    event = EventModel(
        id="UiClick",
        display_name="UI Click",
        bus="UI",
        play_mode="OneShot",
        clips=[
            ClipModel.from_path(primary_path, "ui/click_primary"),
            ClipModel.from_path(alternate_path, "ui/click_alternate"),
        ],
    )
    event.clips[0].active = False
    event.clips[1].active = True

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is True
    assert result.clip_id == event.clips[1].id
    assert result.asset_key == "ui/click_alternate"


def test_preview_service_ignores_inactive_bindings_for_random_mode(tmp_path) -> None:
    primary_path = write_wav_fixture(tmp_path / "fixtures" / "random_primary.wav", frequency_hz=440.0)
    alternate_path = write_wav_fixture(tmp_path / "fixtures" / "random_alternate.wav", frequency_hz=660.0)
    event = EventModel(
        id="UiRandom",
        display_name="UI Random",
        bus="UI",
        play_mode="Random",
        clips=[
            ClipModel.from_path(primary_path, "ui/random_primary"),
            ClipModel.from_path(alternate_path, "ui/random_alternate"),
        ],
    )
    event.clips[0].active = True
    event.clips[1].active = False

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is True
    assert result.clip_id == event.clips[0].id
    assert result.asset_key == "ui/random_primary"


def test_preview_service_applies_gamesync_rtpc_state_and_mapped_switch(tmp_path) -> None:
    default_path = write_wav_fixture(tmp_path / "fixtures" / "surface_default.wav", frequency_hz=440.0)
    stone_path = write_wav_fixture(tmp_path / "fixtures" / "surface_stone.wav", frequency_hz=660.0)
    default_clip = ClipModel.from_path(default_path, "footstep/default")
    stone_clip = ClipModel.from_path(stone_path, "footstep/stone")
    stone_clip.active = False
    event = EventModel(
        id="Footstep",
        display_name="Footstep",
        bus="SFX",
        play_mode="OneShot",
        clips=[default_clip, stone_clip],
        rtpc_bindings=[
            RtpcBindingModel(
                parameter_name="PlayerSpeed",
                target="EventVolumeDb",
                scope="Emitter",
                curve_points=[
                    CurvePointModel(input_value=0.0, output_value=-6.0),
                    CurvePointModel(input_value=10.0, output_value=2.0),
                ],
            )
        ],
        state_overrides=[
            StateOverrideModel(group_name="CombatState", state_name="Combat", volume_db=3.0, pitch_cents=120, is_muted=False)
        ],
        switch_variants=[
            SwitchVariantModel(group_name="FootstepSurface", switch_name="Stone", clip_ids=[stone_clip.id])
        ],
    )

    result = PreviewService(seed=7).preview_event(
        event,
        preview_gamesync=PreviewGameSyncContext(
            emitter_game_parameters={"PlayerSpeed": 10.0},
            states={"CombatState": "Combat"},
        ),
        game_parameters=[GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)],
        state_groups=[
            StateGroupModel(
                name="CombatState",
                states=["Explore", "Combat"],
                default_state="Explore",
                state_effects={"Combat": {"volume_db": 1.5, "pitch_cents": 30, "is_muted": False}},
            )
        ],
        switch_groups=[
            SwitchGroupModel(
                name="FootstepSurface",
                switches=["Grass", "Stone"],
                default_switch="Grass",
                use_game_parameter=True,
                mapped_game_parameter="PlayerSpeed",
                switch_effects={"Stone": {"volume_db": 0.5, "pitch_cents": -10, "is_muted": False}},
            )
        ],
    )

    assert result.accepted is True
    assert result.clip_id == stone_clip.id
    assert result.asset_key == "footstep/stone"
    assert result.volume_db == 7.0
    assert result.pitch_cents == 140


def test_preview_service_mapped_switch_falls_back_to_global_parameter(tmp_path) -> None:
    default_path = write_wav_fixture(tmp_path / "fixtures" / "surface_default_global.wav", frequency_hz=440.0)
    stone_path = write_wav_fixture(tmp_path / "fixtures" / "surface_stone_global.wav", frequency_hz=660.0)
    default_clip = ClipModel.from_path(default_path, "footstep/default_global")
    stone_clip = ClipModel.from_path(stone_path, "footstep/stone_global")
    stone_clip.active = False
    event = EventModel(
        id="FootstepGlobal",
        display_name="Footstep Global",
        bus="SFX",
        play_mode="OneShot",
        clips=[default_clip, stone_clip],
        switch_variants=[
            SwitchVariantModel(group_name="FootstepSurface", switch_name="Stone", clip_ids=[stone_clip.id])
        ],
    )

    result = PreviewService(seed=7).preview_event(
        event,
        preview_gamesync=PreviewGameSyncContext(
            global_game_parameters={"PlayerSpeed": 10.0},
        ),
        game_parameters=[GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)],
        switch_groups=[
            SwitchGroupModel(
                name="FootstepSurface",
                switches=["Grass", "Stone"],
                default_switch="Grass",
                use_game_parameter=True,
                mapped_game_parameter="PlayerSpeed",
            )
        ],
    )

    assert result.accepted is True
    assert result.clip_id == stone_clip.id
    assert result.asset_key == "footstep/stone_global"