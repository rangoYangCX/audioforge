from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from audioforge.app.models.audio_project import ClipModel, EventModel
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

    assert payload["RuntimeAudioFormat"] == "wav"
    assert payload["Events"]["UiClick"]["Bus"] == "UI"
    assert manifest["Assets"][0]["ExportPath"] == "ui/click_primary.wav"
    assert report["EventCount"] == 1
    assert report["ClipCount"] == 1


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()