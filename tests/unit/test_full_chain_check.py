from __future__ import annotations

import json
from pathlib import Path

import pytest

from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.validator import ProjectValidator
from tools.run_full_chain_check import check_export_bundle, check_runtime_contract, run_harness_check, run_main_controller_batches_check
from tools.run_main_controller_stability_batches import BatchResult

from tests.helpers import build_sample_project


def test_full_chain_checks_pass_for_valid_export(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    RuntimeExporter().export(project, export_root, issues)

    export_result = check_export_bundle(export_root)
    contract_result = check_runtime_contract(export_root)

    assert export_result.passed is True
    assert contract_result.passed is True


def test_full_chain_runtime_contract_detects_missing_manifest_reference(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    RuntimeExporter().export(project, export_root, issues)

    audio_data_path = export_root / "AudioData.json"
    payload = json.loads(audio_data_path.read_text(encoding="utf-8"))
    audio_id = payload["Events"]["UiClick"]["AudioId"]
    payload["AudioObjects"][audio_id]["Clips"][0]["AssetKey"] = "ui/missing_asset"
    audio_data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_result = check_runtime_contract(export_root)

    assert contract_result.passed is False
    assert any(detail.startswith("manifest_missing_for_clip=") for detail in contract_result.details)


def test_full_chain_runtime_contract_requires_audio_object_for_schema_v3(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    RuntimeExporter().export(project, export_root, issues)

    audio_data_path = export_root / "AudioData.json"
    payload = json.loads(audio_data_path.read_text(encoding="utf-8"))
    audio_id = payload["Events"]["UiClick"]["AudioId"]
    del payload["AudioObjects"][audio_id]
    audio_data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_result = check_runtime_contract(export_root)

    assert contract_result.passed is False
    assert f"missing_schema_field=audio_object:UiClick:{audio_id}" in contract_result.details


def test_full_chain_runtime_contract_requires_event_audio_id(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path, runtime_audio_format="wav")
    export_root = tmp_path / "Export"
    issues = ProjectValidator().validate(project)
    RuntimeExporter().export(project, export_root, issues)

    audio_data_path = export_root / "AudioData.json"
    payload = json.loads(audio_data_path.read_text(encoding="utf-8"))
    del payload["Events"]["UiClick"]["AudioId"]
    audio_data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_result = check_runtime_contract(export_root)

    assert contract_result.passed is False
    assert "missing_schema_field=event:UiClick:AudioId" in contract_result.details


def test_full_chain_harness_check_writes_reports(tmp_path: Path) -> None:
    report_root = tmp_path / "harness"

    result = run_harness_check(report_root, ["project_roundtrip", "build_export_cycle", "experiment_delta_export"])

    assert result.passed is True
    assert (report_root / "harness_report.json").exists()
    assert (report_root / "harness_report.md").exists()
    assert any(detail == "scenario=project_roundtrip:PASS" for detail in result.details)
    assert any(detail == "scenario=build_export_cycle:PASS" for detail in result.details)
    assert any(detail == "scenario=experiment_delta_export:PASS" for detail in result.details)


def test_full_chain_main_controller_batches_check_writes_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report_root = tmp_path / "main_controller_batches"

    monkeypatch.setattr(
        "tools.run_full_chain_check.main_controller_stability_batches.run_batches",
        lambda workspace, batch_names, fail_fast=False: [
            BatchResult(
                name="layout_preview_gamesync",
                passed=True,
                duration_seconds=12.5,
                command=["python", "-m", "pytest"],
                stdout_tail=["4 passed in 12.5s"],
                stderr_tail=[],
            )
        ],
    )

    result = run_main_controller_batches_check(tmp_path, report_root, ["layout_preview_gamesync"])

    assert result.passed is True
    assert (report_root / "main_controller_stability_batches.json").exists()
    assert (report_root / "main_controller_stability_batches.md").exists()
    assert any(detail == "batch=layout_preview_gamesync:PASS:12.50s" for detail in result.details)