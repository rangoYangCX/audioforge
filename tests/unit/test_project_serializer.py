from __future__ import annotations

from pathlib import Path

import pytest

from audioforge.app.models.audio_project import CurvePointModel, GameParameterModel, RtpcBindingModel, StateGroupModel, StateOverrideModel, SwitchGroupModel, SwitchVariantModel
from audioforge.app.services.project_serializer import ProjectSerializer

from tests.helpers import build_sample_project


def test_project_serializer_roundtrip_preserves_bus_routes_and_clips(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path, bus_volume_db=2.5, event_volume_db=-1.0)
    project.settings.auto_assign_bus_by_name = False
    project.game_parameters = [GameParameterModel(name="PlayerSpeed", default_value=3.0, min_value=0.0, max_value=10.0, notes="驱动移动类 RTPC。")]
    project.state_groups = [
        StateGroupModel(
            name="MusicState",
            states=["Explore", "Combat"],
            default_state="Explore",
            state_effects={"Combat": {"volume_db": 2.5, "pitch_cents": 80, "is_muted": False, "notes": "战斗态抬高音乐张力。"}},
            notes="全局音乐模式。",
        )
    ]
    project.switch_groups = [
        SwitchGroupModel(
            name="FootstepSurface",
            switches=["Concrete", "Grass"],
            default_switch="Concrete",
            use_game_parameter=True,
            mapped_game_parameter="PlayerSpeed",
            switch_effects={"Grass": {"volume_db": -1.5, "pitch_cents": -20, "is_muted": False, "notes": "草地更闷一些。"}},
            notes="按 emitter 分支切换脚步材质。",
        )
    ]
    project.events["UiClick"].rtpc_bindings = [
        RtpcBindingModel(
            parameter_name="PlayerSpeed",
            target="EventVolumeDb",
            scope="Emitter",
            curve_points=[
                CurvePointModel(input_value=0.0, output_value=-12.0),
                CurvePointModel(input_value=10.0, output_value=0.0),
            ],
            notes="速度越快，点击越响。",
        )
    ]
    project.events["UiClick"].state_overrides = [
        StateOverrideModel(group_name="MusicState", state_name="Combat", volume_db=1.5, pitch_cents=120, notes="战斗态增强 UI 反馈。")
    ]
    project.events["UiClick"].switch_variants = [
        SwitchVariantModel(group_name="FootstepSurface", switch_name="Grass", clip_ids=[project.events["UiClick"].clips[0].id], notes="草地变体。")
    ]
    project.settings.bus_configs[-1].rtpc_bindings = [
        RtpcBindingModel(
            parameter_name="PlayerSpeed",
            target="BusVolumeDb",
            scope="Global",
            curve_points=[
                CurvePointModel(input_value=0.0, output_value=-3.0),
                CurvePointModel(input_value=10.0, output_value=2.0, interpolation="Constant"),
            ],
            notes="UI Bus 混音提升。",
        )
    ]
    project.settings.bus_configs[-1].state_overrides = [
        StateOverrideModel(group_name="MusicState", state_name="Combat", volume_db=2.0, is_muted=False, notes="战斗态提高 UI 总线。")
    ]
    serializer = ProjectSerializer()
    project_path = tmp_path / "sample.afproj"

    serializer.save(project, project_path)
    loaded = serializer.load(project_path)

    assert loaded.file_path == str(project_path)
    assert loaded.events["UiClick"].clips[0].source_path == str(wav_path)
    assert loaded.events["UiClick"].clips[0].asset_key == "ui/click_primary"
    assert loaded.settings.default_bus == "UI"
    assert loaded.settings.auto_assign_bus_by_name is False
    assert loaded.settings.bus_configs[-1].name == "UI"
    assert loaded.settings.bus_configs[-1].parent_bus == "SFX"
    assert loaded.settings.bus_configs[-1].volume_db == 2.5
    assert str(wav_path) in loaded.asset_registry
    assert len(loaded.game_parameters) == 1
    assert loaded.game_parameters[0].name == "PlayerSpeed"
    assert loaded.state_groups[0].default_state == "Explore"
    assert loaded.state_groups[0].state_effects["Combat"].volume_db == 2.5
    assert loaded.switch_groups[0].mapped_game_parameter == "PlayerSpeed"
    assert loaded.switch_groups[0].switch_effects["Grass"].pitch_cents == -20
    assert loaded.events["UiClick"].rtpc_bindings[0].curve_points[1].output_value == 0.0
    assert loaded.events["UiClick"].state_overrides[0].state_name == "Combat"
    assert loaded.events["UiClick"].switch_variants[0].clip_ids == [loaded.events["UiClick"].clips[0].id]
    assert loaded.settings.bus_configs[-1].rtpc_bindings[0].target == "BusVolumeDb"
    assert loaded.settings.bus_configs[-1].rtpc_bindings[0].curve_points[1].interpolation == "Constant"
    assert loaded.settings.bus_configs[-1].state_overrides[0].volume_db == 2.0


def test_project_serializer_preserves_existing_file_when_atomic_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = build_sample_project(tmp_path)
    serializer = ProjectSerializer()
    project_path = tmp_path / "sample.afproj"
    temp_path = project_path.with_suffix(".tmp")

    serializer.save(project, project_path)
    original_payload = project_path.read_text(encoding="utf-8")
    project.name = "Changed Project"

    original_replace = Path.replace

    def failing_replace(self: Path, target: Path) -> Path:
        if self == temp_path and target == project_path:
            raise OSError("disk full")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        serializer.save(project, project_path)

    assert project_path.read_text(encoding="utf-8") == original_payload
    assert temp_path.exists() is False