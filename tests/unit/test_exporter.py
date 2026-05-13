from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

import audioforge.app.services.audio_processor as audio_processor_module
from audioforge.app.models.audio_project import BusConfig, ClipModel, CurvePointModel, EventModel, GameParameterModel, MASTER_BUS_NAME, ProjectSettings, RtpcBindingModel, StateGroupModel, StateOverrideModel, SwitchGroupModel, SwitchVariantModel
from audioforge.app.services.audio_processor import AudioProcessor
from audioforge.app.services.exporter import ExportRequest, RuntimeExporter
from audioforge.app.services.validator import ProjectValidator

from tests.helpers import build_sample_project, write_wav_fixture


def test_runtime_exporter_writes_bundle_and_assets(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)

    result = RuntimeExporter().export(project, export_root, issues)

    assert result.data_file.exists()
    assert result.enum_file.exists()
    assert result.manifest_file.exists()
    assert result.report_file.exists()
    assert (result.assets_dir / "ui" / "click_primary.wav").exists()

    payload = json.loads(result.data_file.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
    report = json.loads(result.report_file.read_text(encoding="utf-8"))

    assert payload["SchemaVersion"] == 2
    assert payload["RuntimeAudioFormat"] == "wav"
    assert payload["Events"]["UiClick"]["Bus"] == "UI"
    assert manifest["Assets"][0]["ExportPath"] == "ui/click_primary.wav"
    assert report["EventCount"] == 1
    assert report["ClipCount"] == 1


def test_runtime_exporter_writes_schema_v2_gamesync_payload(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    alternate_wav = write_wav_fixture(tmp_path / "fixtures" / "ui_click_surface.wav", frequency_hz=523.25)
    event = project.events["UiClick"]
    variant_clip = ClipModel.from_path(alternate_wav, "ui/click_surface")
    variant_clip.active = False
    event.clips.append(variant_clip)
    event.rtpc_bindings = [
        RtpcBindingModel(
            parameter_name="PlayerSpeed",
            target="EventVolumeDb",
            scope="Emitter",
            curve_points=[
                CurvePointModel(input_value=0.0, output_value=-6.0, interpolation="Linear"),
                CurvePointModel(input_value=8.0, output_value=2.0, interpolation="Constant"),
            ],
        )
    ]
    event.state_overrides = [StateOverrideModel(group_name="CombatState", state_name="Combat", volume_db=3.0, pitch_cents=120, is_muted=False)]
    event.switch_variants = [SwitchVariantModel(group_name="FootstepSurface", switch_name="Stone", clip_ids=[variant_clip.id])]
    project.game_parameters = [GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)]
    project.state_groups = [
        StateGroupModel(
            name="CombatState",
            states=["Explore", "Combat"],
            default_state="Explore",
            state_effects={"Combat": {"volume_db": 2.0, "pitch_cents": 50, "is_muted": False, "notes": "战斗态增强。"}},
        )
    ]
    project.switch_groups = [
        SwitchGroupModel(
            name="FootstepSurface",
            switches=["Grass", "Stone"],
            default_switch="Grass",
            use_game_parameter=True,
            mapped_game_parameter="PlayerSpeed",
            switch_effects={"Stone": {"volume_db": 1.0, "pitch_cents": -30, "is_muted": False, "notes": "石地更硬。"}},
        )
    ]
    project.settings.bus_configs[1].rtpc_bindings = [
        RtpcBindingModel(
            parameter_name="PlayerSpeed",
            target="BusVolumeDb",
            scope="Global",
            curve_points=[CurvePointModel(input_value=0.0, output_value=-3.0), CurvePointModel(input_value=10.0, output_value=0.0)],
        )
    ]
    project.settings.bus_configs[1].state_overrides = [
        StateOverrideModel(group_name="CombatState", state_name="Combat", volume_db=1.5, pitch_cents=0, is_muted=False)
    ]

    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    result = RuntimeExporter().export(project, export_root, issues)

    payload = json.loads(result.data_file.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
    ui_click = payload["Events"]["UiClick"]
    ui_bus = next(config for config in payload["BusConfigs"] if config["Name"] == "BGM")

    assert payload["SchemaVersion"] == 2
    assert payload["GameParameters"][0]["Name"] == "PlayerSpeed"
    assert payload["StateGroups"][0]["DefaultState"] == "Explore"
    assert payload["StateGroups"][0]["StateEffects"][0]["StateName"] == "Combat"
    assert payload["SwitchGroups"][0]["UseGameParameter"] is True
    assert payload["SwitchGroups"][0]["Thresholds"][0]["SwitchName"] == "Grass"
    assert payload["SwitchGroups"][0]["SwitchEffects"][0]["SwitchName"] == "Stone"
    assert ui_click["RtpcBindings"][0]["Scope"] == "Emitter"
    assert ui_click["RtpcBindings"][0]["CurvePoints"][1]["Interpolation"] == "Constant"
    assert ui_click["StateOverrides"][0]["GroupName"] == "CombatState"
    assert ui_click["SwitchVariants"][0]["ClipIds"] == [variant_clip.id]
    assert variant_clip.id in ui_click["Clips"][1]["ClipId"]
    assert ui_bus["RtpcBindings"][0]["Target"] == "BusVolumeDb"
    assert ui_bus["StateOverrides"][0]["StateName"] == "Combat"
    assert {asset["AssetKey"] for asset in manifest["Assets"]} == {"ui/click_primary", "ui/click_surface"}


def test_runtime_exporter_is_stable_across_repeated_exports(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    issues = ProjectValidator().validate(project)
    first_root = tmp_path / "ExportA"
    second_root = tmp_path / "ExportB"

    first_result = RuntimeExporter().export(project, first_root, issues)
    second_result = RuntimeExporter().export(project, second_root, issues)

    first_data = json.loads(first_result.data_file.read_text(encoding="utf-8"))
    second_data = json.loads(second_result.data_file.read_text(encoding="utf-8"))
    first_data.pop("GeneratedAt", None)
    second_data.pop("GeneratedAt", None)

    assert first_data == second_data
    assert first_result.enum_file.read_text(encoding="utf-8") == second_result.enum_file.read_text(encoding="utf-8")
    assert first_result.manifest_file.read_text(encoding="utf-8") == second_result.manifest_file.read_text(encoding="utf-8")
    assert first_result.report_file.read_text(encoding="utf-8") == second_result.report_file.read_text(encoding="utf-8")
    assert _sha256(first_result.assets_dir / "ui" / "click_primary.wav") == _sha256(second_result.assets_dir / "ui" / "click_primary.wav")


def test_runtime_exporter_only_writes_active_binding_for_one_shot(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    alternate_wav = write_wav_fixture(tmp_path / "fixtures" / "ui_click_alt.wav", frequency_hz=660.0)
    event = project.events["UiClick"]
    event.play_mode = "OneShot"
    event.clips[0].active = False
    event.clips.append(ClipModel.from_path(alternate_wav, "ui/click_alternate"))
    event.clips[1].active = True
    project.touch()

    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    result = RuntimeExporter().export(project, export_root, issues)

    payload = json.loads(result.data_file.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))

    assert payload["Events"]["UiClick"]["PlayMode"] == "OneShot"
    assert [clip["AssetKey"] for clip in payload["Events"]["UiClick"]["Clips"]] == ["ui/click_alternate"]
    assert {asset["AssetKey"] for asset in manifest["Assets"]} == {"ui/click_alternate"}


def test_runtime_exporter_only_writes_active_bindings_for_random_mode(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    alternate_wav = write_wav_fixture(tmp_path / "fixtures" / "ui_click_random_alt.wav", frequency_hz=660.0)
    event = project.events["UiClick"]
    event.play_mode = "Random"
    event.clips[0].active = True
    event.clips.append(ClipModel.from_path(alternate_wav, "ui/click_random_alt"))
    event.clips[1].active = False
    project.touch()

    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    result = RuntimeExporter().export(project, export_root, issues)

    payload = json.loads(result.data_file.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))

    assert payload["Events"]["UiClick"]["PlayMode"] == "Random"
    assert [clip["AssetKey"] for clip in payload["Events"]["UiClick"]["Clips"]] == ["ui/click_primary"]
    assert {asset["AssetKey"] for asset in manifest["Assets"]} == {"ui/click_primary"}


def test_runtime_exporter_overwrites_existing_bundle_atomically(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)

    export_root.mkdir(parents=True)
    stale_file = export_root / "stale.txt"
    stale_file.write_text("stale", encoding="utf-8")
    (export_root / "AudioData.json").write_text('{"stale": true}', encoding="utf-8")

    result = RuntimeExporter().export(project, export_root, issues)

    assert result.data_file.exists()
    assert not stale_file.exists()
    assert not export_root.with_name("Export.bak").exists()

    payload = json.loads(result.data_file.read_text(encoding="utf-8"))
    assert payload["ProjectName"] == "InternalReleaseSample"
    assert payload["Events"]["UiClick"]["Bus"] == "UI"


def test_runtime_exporter_restores_previous_bundle_when_commit_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exporter = RuntimeExporter()
    original_project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    original_issues = ProjectValidator().validate(original_project)
    exporter.export(original_project, export_root, original_issues)

    original_data = (export_root / "AudioData.json").read_text(encoding="utf-8")
    original_manifest = (export_root / "AudioManifest.json").read_text(encoding="utf-8")
    backup_root = export_root.with_name(f"{export_root.name}.bak")

    updated_project, _ = build_sample_project(tmp_path / "updated", runtime_audio_format="wav", event_volume_db=-6.0)
    updated_issues = ProjectValidator().validate(updated_project)

    original_replace = Path.replace

    def fail_commit_replace(self: Path, target: Path | str) -> Path:
        target_path = Path(target)
        if target_path == export_root and self.name.startswith(f"{export_root.name}_"):
            raise RuntimeError("commit replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_commit_replace)

    with pytest.raises(RuntimeError, match="commit replace failed"):
        exporter.export(updated_project, export_root, updated_issues)

    assert export_root.exists()
    assert not backup_root.exists()
    assert (export_root / "AudioData.json").read_text(encoding="utf-8") == original_data
    assert (export_root / "AudioManifest.json").read_text(encoding="utf-8") == original_manifest
    assert not list(tmp_path.glob("Export_*"))


def test_runtime_exporter_incremental_rebuilds_only_changed_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    hover_wav = write_wav_fixture(tmp_path / "fixtures" / "ui_hover.wav", frequency_hz=660.0)
    project.add_event(
        project.root_folder_ids[0],
        EventModel(
            id="UiHover",
            display_name="UI Hover",
            bus="UI",
            clips=[ClipModel.from_path(hover_wav, "ui/hover_secondary")],
        ),
    )
    exporter = RuntimeExporter()
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    exporter.export(project, export_root, issues)

    reused_asset_path = export_root / "Assets" / "ui" / "hover_secondary.wav"
    reused_asset_hash = _sha256(reused_asset_path)
    project.events["UiClick"].clips[0].trim_end_ms = 15
    project.touch()

    request = ExportRequest(scope="incremental")
    plan = exporter.plan_export(project, export_root, request)

    assert plan.requested_scope == "incremental"
    assert plan.effective_scope == "incremental"
    assert plan.rebuilt_asset_keys == ("ui/click_primary",)
    assert plan.reused_asset_keys == ("ui/hover_secondary",)

    export_calls: list[str] = []
    original_export_clip = exporter.audio_processor.export_clip

    def track_export(clip, project_settings, destination_path):
        export_calls.append(clip.asset_key)
        return original_export_clip(clip, project_settings, destination_path)

    monkeypatch.setattr(exporter.audio_processor, "export_clip", track_export)

    exporter.export(project, export_root, issues, request=request, plan=plan)

    assert export_calls == ["ui/click_primary"]
    assert _sha256(export_root / "Assets" / "ui" / "hover_secondary.wav") == reused_asset_hash


def test_runtime_exporter_selection_scope_expands_when_out_of_scope_assets_are_dirty(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    hover_wav = write_wav_fixture(tmp_path / "fixtures" / "ui_hover.wav", frequency_hz=660.0)
    project.add_event(
        project.root_folder_ids[0],
        EventModel(
            id="UiHover",
            display_name="UI Hover",
            bus="UI",
            clips=[ClipModel.from_path(hover_wav, "ui/hover_secondary")],
        ),
    )
    exporter = RuntimeExporter()
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    exporter.export(project, export_root, issues)

    project.events["UiClick"].clips[0].trim_end_ms = 15
    project.events["UiHover"].clips[0].trim_start_ms = 8
    project.touch()

    plan = exporter.plan_export(
        project,
        export_root,
        ExportRequest(scope="selection", selected_event_ids=("UiClick",), selection_label="事件 UiClick"),
    )

    assert plan.requested_scope == "selection"
    assert plan.effective_scope == "incremental"
    assert plan.rebuilt_asset_keys == ("ui/click_primary", "ui/hover_secondary")
    assert plan.out_of_scope_dirty_asset_keys == ("ui/hover_secondary",)


def test_audio_processor_copies_same_format_without_reencoding(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source_path = tmp_path / "fixtures" / "game_bgm.ogg"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = b"OggS passthrough fixture"
    source_path.write_bytes(source_bytes)

    clip = ClipModel.from_path(source_path, "bgm/game_bgm")
    project_settings = ProjectSettings(
        default_bus="BGM",
        export_root=str(tmp_path / "Export"),
        buses=["BGM"],
        bus_configs=[BusConfig(name=MASTER_BUS_NAME), BusConfig(name="BGM")],
        source_audio_format="ogg",
        runtime_audio_format="ogg",
    )
    destination_path = tmp_path / "Export" / "Assets" / "bgm" / "game_bgm.ogg"

    monkeypatch.setattr(audio_processor_module, "sf", None)

    AudioProcessor().export_clip(clip, project_settings, destination_path)

    assert destination_path.read_bytes() == source_bytes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()