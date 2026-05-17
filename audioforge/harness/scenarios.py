from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from audioforge.app.controllers.experiment_controller import ExperimentController
from audioforge.app.services.experiment_exporter import ExperimentExporter
from audioforge.app.services.exporter import ExportRequest, RuntimeExporter
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.services.recovery_service import RecoveryService
from audioforge.app.services.validator import ProjectValidator
from audioforge.harness.fixtures import create_sample_workspace, save_sample_project


REQUIRED_EXPORT_FILES = (
    "AudioData.json",
    "AudioManifest.json",
    "AudioEventID.cs",
    "BuildReport.json",
)


@dataclass(slots=True)
class HarnessScenarioResult:
    name: str
    passed: bool
    details: list[str]
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": list(self.details),
            "artifacts": dict(self.artifacts),
        }


@dataclass(slots=True)
class HarnessRunReport:
    root_dir: Path
    started_at: str
    finished_at: str
    passed: bool
    results: list[HarnessScenarioResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "root_dir": str(self.root_dir),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "passed": self.passed,
            "results": [result.to_dict() for result in self.results],
        }


class _RecordingProjectOpener:
    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_project(self, path: str) -> None:
        self.opened_paths.append(path)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_export_contract_details(export_root: Path) -> tuple[bool, list[str], dict[str, str]]:
    missing_files = [name for name in REQUIRED_EXPORT_FILES if not (export_root / name).exists()]
    details = [f"export_root={export_root}"]
    if missing_files:
        details.extend(f"missing_file={name}" for name in missing_files)
        return False, details, {"export_root": str(export_root)}

    manifest_payload = _read_json(export_root / "AudioManifest.json")
    build_report = _read_json(export_root / "BuildReport.json")
    audio_data = _read_json(export_root / "AudioData.json")
    manifest_assets = manifest_payload.get("Assets", []) if isinstance(manifest_payload.get("Assets"), list) else []
    events_payload = audio_data.get("Events", {}) if isinstance(audio_data.get("Events"), dict) else {}
    build_report_files = build_report.get("ExportedFiles", []) if isinstance(build_report.get("ExportedFiles"), list) else []
    missing_assets: list[str] = []
    asset_key_map: dict[str, str] = {}
    for asset in manifest_assets:
        if not isinstance(asset, dict):
            continue
        asset_key = str(asset.get("AssetKey", "")).strip()
        export_path = str(asset.get("ExportPath", "")).strip()
        if asset_key and export_path:
            asset_key_map[asset_key] = export_path
        if export_path and not (export_root / "Assets" / export_path).exists():
            missing_assets.append(export_path)

    details.extend(
        [
            f"asset_entries={len(manifest_assets)}",
            f"event_count={len(events_payload)}",
            f"reported_event_count={build_report.get('EventCount', -1)}",
            f"reported_clip_count={build_report.get('ClipCount', -1)}",
            f"schema_version={audio_data.get('SchemaVersion', 0)}",
        ]
    )
    if missing_assets:
        details.extend(f"missing_asset={path}" for path in missing_assets)
    missing_report_entries = [name for name in REQUIRED_EXPORT_FILES if name not in build_report_files]
    if missing_report_entries:
        details.extend(f"build_report_missing_export_entry={name}" for name in missing_report_entries)

    passed = not missing_assets and not missing_report_entries and bool(events_payload) and bool(manifest_assets)
    return passed, details, {
        "export_root": str(export_root),
        "manifest_file": str(export_root / "AudioManifest.json"),
        "report_file": str(export_root / "BuildReport.json"),
        "data_file": str(export_root / "AudioData.json"),
        "event_enum_file": str(export_root / "AudioEventID.cs"),
        "asset_key_map": json.dumps(asset_key_map, ensure_ascii=False, sort_keys=True),
    }


def _scenario_project_roundtrip(root_dir: Path) -> HarnessScenarioResult:
    bundle = save_sample_project(root_dir, project_name="HarnessProjectRoundtrip")
    loaded = ProjectSerializer().load(bundle.project_path)
    asset_paths_exist = all(Path(path).exists() for path in loaded.asset_registry)
    passed = (
        bundle.project_path.exists()
        and "UiClick" in loaded.events
        and any(event.display_name == "BGM Menu Loop" for event in loaded.events.values())
        and asset_paths_exist
    )
    details = [
        f"project_path={bundle.project_path}",
        f"event_count={len(loaded.events)}",
        f"asset_count={len(loaded.asset_registry)}",
        f"asset_registry_paths_exist={asset_paths_exist}",
    ]
    return HarnessScenarioResult(
        name="project_roundtrip",
        passed=passed,
        details=details,
        artifacts={"project_path": str(bundle.project_path)},
    )


def _scenario_export_contract(root_dir: Path) -> HarnessScenarioResult:
    bundle = save_sample_project(root_dir, project_name="HarnessExportContract")
    validator = ProjectValidator()
    issues = validator.validate(bundle.project)
    error_count = sum(1 for issue in issues if issue.severity == "Error")
    if error_count:
        return HarnessScenarioResult(
            name="export_contract",
            passed=False,
            details=[f"error_count={error_count}"] + [f"validation_error={issue.code}:{issue.target}" for issue in issues if issue.severity == "Error"],
            artifacts={"project_path": str(bundle.project_path)},
        )

    export_result = RuntimeExporter().export(bundle.project, bundle.export_root, issues)
    contract_passed, contract_details, contract_artifacts = _collect_export_contract_details(export_result.export_root)
    details = [f"warning_count={sum(1 for issue in issues if issue.severity == 'Warning')}", *contract_details]
    return HarnessScenarioResult(
        name="export_contract",
        passed=contract_passed,
        details=details,
        artifacts={
            "project_path": str(bundle.project_path),
            **{key: value for key, value in contract_artifacts.items() if key != "asset_key_map"},
        },
    )


def _scenario_build_export_cycle(root_dir: Path) -> HarnessScenarioResult:
    bundle = save_sample_project(root_dir, project_name="HarnessBuildExportCycle")
    validator = ProjectValidator()
    exporter = RuntimeExporter()
    issues = validator.validate(bundle.project)
    error_count = sum(1 for issue in issues if issue.severity == "Error")
    if error_count:
        return HarnessScenarioResult(
            name="build_export_cycle",
            passed=False,
            details=[f"error_count={error_count}"],
            artifacts={"project_path": str(bundle.project_path)},
        )

    first_export = exporter.export(bundle.project, bundle.export_root, issues)
    _contract_passed, _contract_details, contract_artifacts = _collect_export_contract_details(first_export.export_root)
    asset_key_map = json.loads(contract_artifacts.get("asset_key_map", "{}"))
    reused_hashes_before = {
        asset_key: _sha256(first_export.export_root / "Assets" / export_path)
        for asset_key, export_path in asset_key_map.items()
        if asset_key in {"ui/hover", "bgm/menu_loop"}
    }

    bundle.project.events["UiClick"].clips[0].trim_end_ms = 15
    bundle.project.touch()
    updated_issues = validator.validate(bundle.project)
    request = ExportRequest(scope="incremental")
    plan = exporter.plan_export(bundle.project, bundle.export_root, request)
    second_export = exporter.export(bundle.project, bundle.export_root, updated_issues, request=request, plan=plan)
    contract_passed, contract_details, second_contract_artifacts = _collect_export_contract_details(second_export.export_root)
    second_asset_key_map = json.loads(second_contract_artifacts.get("asset_key_map", "{}"))
    reused_hashes_after = {
        asset_key: _sha256(second_export.export_root / "Assets" / export_path)
        for asset_key, export_path in second_asset_key_map.items()
        if asset_key in reused_hashes_before
    }
    reused_hashes_stable = reused_hashes_before == reused_hashes_after
    expected_reused = {"ui/hover", "bgm/menu_loop"}
    passed = (
        contract_passed
        and plan.requested_scope == "incremental"
        and plan.effective_scope == "incremental"
        and plan.rebuilt_asset_keys == ("ui/click_primary",)
        and expected_reused.issubset(set(plan.reused_asset_keys))
        and reused_hashes_stable
    )
    details = [
        f"requested_scope={plan.requested_scope}",
        f"effective_scope={plan.effective_scope}",
        f"rebuilt_asset_keys={','.join(plan.rebuilt_asset_keys)}",
        f"reused_asset_keys={','.join(plan.reused_asset_keys)}",
        f"reused_hashes_stable={reused_hashes_stable}",
        *contract_details,
    ]
    return HarnessScenarioResult(
        name="build_export_cycle",
        passed=passed,
        details=details,
        artifacts={
            "project_path": str(bundle.project_path),
            "export_root": str(second_export.export_root),
            "report_file": str(second_export.report_file),
        },
    )


def _scenario_recovery_cycle(root_dir: Path) -> HarnessScenarioResult:
    bundle = save_sample_project(root_dir, project_name="HarnessRecoveryCycle")
    recovery_service = RecoveryService(root_dir / "Recovery")
    snapshot_path = recovery_service.save_snapshot(bundle.project)
    history_path = recovery_service.save_history_snapshot(bundle.project)
    snapshot = recovery_service.load_snapshot(history_path)
    passed = snapshot_path.exists() and history_path.exists() and len(snapshot.project.events) == len(bundle.project.events)
    details = [
        f"snapshot_path={snapshot_path}",
        f"history_path={history_path}",
        f"loaded_event_count={len(snapshot.project.events)}",
    ]
    return HarnessScenarioResult(
        name="recovery_cycle",
        passed=passed,
        details=details,
        artifacts={"history_path": str(history_path)},
    )


def _scenario_recovery_reopen_cycle(root_dir: Path) -> HarnessScenarioResult:
    bundle = save_sample_project(root_dir, project_name="HarnessRecoveryReopen")
    serializer = ProjectSerializer()
    saved_project = serializer.load(bundle.project_path)
    saved_project.events["UiClick"].volume_db = -7.5
    serializer.save(saved_project, bundle.project_path)

    recovery_service = RecoveryService(root_dir / "Recovery")
    snapshot_path = recovery_service.save_snapshot(saved_project)
    history_path = recovery_service.save_history_snapshot(saved_project)
    recovered_snapshot = recovery_service.load_snapshot(history_path)
    reopened_path = root_dir / "RecoveredProject" / "RecoveredHarness.afproj"
    serializer.save(recovered_snapshot.project, reopened_path)
    reopened_project = serializer.load(reopened_path)
    clip_source_exists = Path(reopened_project.events["UiClick"].clips[0].source_path).exists()
    preserved_volume = reopened_project.events["UiClick"].volume_db == -7.5
    original_path_preserved = recovered_snapshot.original_project_path == str(bundle.project_path)
    passed = snapshot_path.exists() and history_path.exists() and reopened_path.exists() and clip_source_exists and preserved_volume and original_path_preserved
    details = [
        f"snapshot_path={snapshot_path}",
        f"history_path={history_path}",
        f"reopened_path={reopened_path}",
        f"clip_source_exists={clip_source_exists}",
        f"preserved_volume={preserved_volume}",
        f"original_path_preserved={original_path_preserved}",
    ]
    return HarnessScenarioResult(
        name="recovery_reopen_cycle",
        passed=passed,
        details=details,
        artifacts={
            "history_path": str(history_path),
            "reopened_path": str(reopened_path),
        },
    )


def _scenario_experiment_cycle(root_dir: Path) -> HarnessScenarioResult:
    _project_bundle, workspace_bundle = create_sample_workspace(
        root_dir,
        project_name="HarnessExperimentBase",
        workspace_name="HarnessExperimentWorkspace",
        task_name="Smoke Task",
        variant_name="default",
    )
    opener = _RecordingProjectOpener()
    controller = ExperimentController(project_opener=opener)
    controller.open_workspace(str(workspace_bundle.workspace_path))
    variant = controller.create_variant(0, "Variant B")
    activation = controller.activate_variant(0, 1) if variant is not None else None
    preview = (
        controller.preview_variant_delta(0, 1, ExperimentExporter.create_default(runtime_exporter=RuntimeExporter()))
        if activation is not None and activation.success
        else None
    )
    variant_path = Path(controller.get_variant_project_path(0, 1) or "")
    passed = (
        variant is not None
        and activation is not None
        and activation.success
        and variant_path.exists()
        and len(opener.opened_paths) == 1
        and preview is not None
        and isinstance(preview.preview, list)
    )
    details = [
        f"workspace_path={workspace_bundle.workspace_path}",
        f"variant_path={variant_path}",
        f"opened_paths={len(opener.opened_paths)}",
        f"preview_entries={len(preview.preview) if preview is not None else -1}",
    ]
    return HarnessScenarioResult(
        name="experiment_cycle",
        passed=passed,
        details=details,
        artifacts={
            "workspace_path": str(workspace_bundle.workspace_path),
            "variant_path": str(variant_path),
        },
    )


def _scenario_experiment_delta_export(root_dir: Path) -> HarnessScenarioResult:
    _project_bundle, workspace_bundle = create_sample_workspace(
        root_dir,
        project_name="HarnessExperimentDeltaBase",
        workspace_name="HarnessExperimentDeltaWorkspace",
        task_name="Delta Task",
        variant_name="default",
    )
    opener = _RecordingProjectOpener()
    controller = ExperimentController(project_opener=opener)
    controller.open_workspace(str(workspace_bundle.workspace_path))
    variant = controller.create_variant(0, "Variant Export")
    if variant is None:
        return HarnessScenarioResult(
            name="experiment_delta_export",
            passed=False,
            details=["create_variant_failed"],
            artifacts={"workspace_path": str(workspace_bundle.workspace_path)},
        )

    serializer = ProjectSerializer()
    variant_path = Path(controller.get_variant_project_path(0, 1) or "")
    variant_project = serializer.load(variant_path)
    variant_project.events["UiClick"].clips[0].trim_end_ms = 20
    serializer.save(variant_project, variant_path)

    exporter = ExperimentExporter.create_default(runtime_exporter=RuntimeExporter())
    activation = controller.activate_variant(0, 1)
    preview = controller.preview_variant_delta(0, 1, exporter) if activation.success else None
    export_result = controller.export_variant_delta(0, 1, exporter) if activation.success else None
    preview_has_modify = bool(preview and any(item.get("Op") == "modify" for item in preview.preview))
    passed = (
        activation.success
        and len(opener.opened_paths) == 1
        and preview_has_modify
        and export_result is not None
        and export_result.delta_result.delta_file.exists()
        and export_result.delta_result.modified_count >= 1
        and export_result.delta_result.asset_count >= 1
    )
    details = [
        f"workspace_path={workspace_bundle.workspace_path}",
        f"variant_path={variant_path}",
        f"opened_paths={len(opener.opened_paths)}",
        f"preview_has_modify={preview_has_modify}",
        f"modified_count={export_result.delta_result.modified_count if export_result is not None else -1}",
        f"asset_count={export_result.delta_result.asset_count if export_result is not None else -1}",
    ]
    return HarnessScenarioResult(
        name="experiment_delta_export",
        passed=passed,
        details=details,
        artifacts={
            "workspace_path": str(workspace_bundle.workspace_path),
            "variant_path": str(variant_path),
            "delta_file": str(export_result.delta_result.delta_file) if export_result is not None else "",
        },
    )


SCENARIO_REGISTRY: dict[str, Callable[[Path], HarnessScenarioResult]] = {
    "project_roundtrip": _scenario_project_roundtrip,
    "export_contract": _scenario_export_contract,
    "build_export_cycle": _scenario_build_export_cycle,
    "recovery_cycle": _scenario_recovery_cycle,
    "recovery_reopen_cycle": _scenario_recovery_reopen_cycle,
    "experiment_cycle": _scenario_experiment_cycle,
    "experiment_delta_export": _scenario_experiment_delta_export,
}

SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "project_roundtrip": "生成可迁移 afproj 样本并验证序列化回读。",
    "export_contract": "对样本工程执行完整导出并检查运行时契约与导出物。",
    "build_export_cycle": "执行完整导出后再跑一次增量导出，验证重建/复用资产计划。",
    "recovery_cycle": "验证 autosave / history snapshot 保存与恢复。",
    "recovery_reopen_cycle": "验证 autosave history 恢复后的工程可再次保存并重开。",
    "experiment_cycle": "验证实验工作区、任务/方案与方案激活主链路。",
    "experiment_delta_export": "验证实验方案修改、预览与增量导出主链路。",
}


def run_scenarios(root_dir: Path, scenario_names: list[str] | None = None) -> HarnessRunReport:
    root_dir = Path(root_dir).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    selected_names = list(scenario_names or SCENARIO_REGISTRY.keys())
    started_at = _now_iso()
    results: list[HarnessScenarioResult] = []
    for name in selected_names:
        runner = SCENARIO_REGISTRY.get(name)
        if runner is None:
            results.append(HarnessScenarioResult(name=name, passed=False, details=[f"unknown_scenario={name}"]))
            continue
        scenario_root = root_dir / name
        scenario_root.mkdir(parents=True, exist_ok=True)
        try:
            results.append(runner(scenario_root))
        except Exception as exc:
            results.append(
                HarnessScenarioResult(
                    name=name,
                    passed=False,
                    details=[
                        f"exception={type(exc).__name__}: {exc}",
                        *traceback.format_exc().strip().splitlines()[-8:],
                    ],
                )
            )
    finished_at = _now_iso()
    passed = all(result.passed for result in results)
    return HarnessRunReport(
        root_dir=root_dir,
        started_at=started_at,
        finished_at=finished_at,
        passed=passed,
        results=results,
    )


def render_console_summary(report: HarnessRunReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [f"AudioForge Harness Smoke: {status}", f"Root: {report.root_dir}", f"Started: {report.started_at}", f"Finished: {report.finished_at}"]
    for result in report.results:
        lines.append(f"- [{'PASS' if result.passed else 'FAIL'}] {result.name}")
        lines.extend(f"  {detail}" for detail in result.details[:4])
    return "\n".join(lines)


def render_markdown_report(report: HarnessRunReport) -> str:
    lines = [
        "# AudioForge Harness Report",
        "",
        f"- Status: {'PASS' if report.passed else 'FAIL'}",
        f"- Root: {report.root_dir}",
        f"- Started: {report.started_at}",
        f"- Finished: {report.finished_at}",
        "",
        "## Scenario Results",
        "",
    ]
    for result in report.results:
        lines.append(f"### {result.name}")
        lines.append("")
        lines.append(f"- Status: {'PASS' if result.passed else 'FAIL'}")
        for detail in result.details:
            lines.append(f"- {detail}")
        if result.artifacts:
            lines.append("- Artifacts:")
            for key, value in result.artifacts.items():
                lines.append(f"  - {key}: {value}")
        lines.append("")
    return "\n".join(lines)