from __future__ import annotations

import json
from pathlib import Path

from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.validator import ProjectValidator
from tools.run_full_chain_check import check_export_bundle, check_runtime_contract

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
    payload["Events"]["UiClick"]["Clips"][0]["AssetKey"] = "ui/missing_asset"
    audio_data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    contract_result = check_runtime_contract(export_root)

    assert contract_result.passed is False
    assert any(detail.startswith("manifest_missing_for_clip=") for detail in contract_result.details)