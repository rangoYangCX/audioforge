from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.validator import ProjectValidator

from tests.helpers import build_sample_project


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()