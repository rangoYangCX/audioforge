from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REQUIRED_EXPORT_FILES = (
    "AudioData.json",
    "AudioManifest.json",
    "AudioEventID.cs",
    "BuildReport.json",
)

REQUIRED_UNITY_RUNTIME_FILES = (
    "Assets/AudioForgeRuntime/Scripts/AudioForgeRuntime.cs",
    "Assets/AudioForgeRuntime/Scripts/AudioForgeModels.cs",
    "Assets/AudioForgeRuntime/Scripts/AudioForgeJsonAdapter.cs",
    "Assets/AudioForgeRuntime/Scripts/AudioForgeEventPlayer.cs",
    "Assets/AudioForgeRuntime/Scripts/AudioForgeBootstrap.cs",
    "Assets/AudioForgeRuntime/Scripts/MiniJson.cs",
    "Assets/AudioForgeRuntime/Scripts/AudioEventID.cs",
    "Assets/AudioForgeRuntime/Editor/AudioForgeMissingScriptCleaner.cs",
)


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    details: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "details": list(self.details),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AudioForge full-chain checks and generate a report.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--unity-validation-dir", type=Path)
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--skip-pytest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    export_dir = (args.export_dir or (workspace / "Export")).resolve()
    unity_validation_dir = (args.unity_validation_dir or (workspace / "unity_validation")).resolve()
    report_dir = (args.report_dir or (workspace / "reports")).resolve()

    results: list[CheckResult] = []
    if not args.skip_pytest:
        results.append(run_pytest_check(workspace))
    else:
        results.append(CheckResult("pytest", True, ["Skipped by --skip-pytest."]))

    results.append(check_export_bundle(export_dir))
    results.append(check_runtime_contract(export_dir))
    results.append(check_unity_validation_package(unity_validation_dir))

    report = build_report(workspace, export_dir, unity_validation_dir, results)
    write_reports(report_dir, report)

    print(render_console_summary(report, report_dir))
    return 0 if report["passed"] else 1


def run_pytest_check(workspace: Path) -> CheckResult:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    details = [f"exit_code={completed.returncode}"]
    stdout_tail = tail_lines(completed.stdout, 20)
    stderr_tail = tail_lines(completed.stderr, 20)
    if stdout_tail:
        details.append("stdout_tail:")
        details.extend(stdout_tail)
    if stderr_tail:
        details.append("stderr_tail:")
        details.extend(stderr_tail)
    return CheckResult("pytest", completed.returncode == 0, details)


def check_export_bundle(export_dir: Path) -> CheckResult:
    details: list[str] = [f"export_dir={export_dir}"]
    missing = [name for name in REQUIRED_EXPORT_FILES if not (export_dir / name).exists()]
    if missing:
        details.extend(f"missing_file={name}" for name in missing)
        return CheckResult("export_bundle", False, details)

    details.append("all_required_export_files_present")

    manifest = read_json(export_dir / "AudioManifest.json")
    build_report = read_json(export_dir / "BuildReport.json")
    assets = manifest.get("Assets", []) if isinstance(manifest, dict) else []
    missing_assets: list[str] = []
    duplicate_asset_keys: set[str] = set()
    duplicate_export_paths: set[str] = set()
    seen_asset_keys: set[str] = set()
    seen_export_paths: set[str] = set()
    for asset in assets:
        export_path = asset.get("ExportPath", "") if isinstance(asset, dict) else ""
        asset_key = asset.get("AssetKey", "") if isinstance(asset, dict) else ""
        if export_path and not (export_dir / "Assets" / export_path).exists():
            missing_assets.append(export_path)
        if asset_key in seen_asset_keys:
            duplicate_asset_keys.add(asset_key)
        elif asset_key:
            seen_asset_keys.add(asset_key)
        if export_path in seen_export_paths:
            duplicate_export_paths.add(export_path)
        elif export_path:
            seen_export_paths.add(export_path)

    if missing_assets:
        details.extend(f"missing_asset={path}" for path in missing_assets)
        return CheckResult("export_bundle", False, details)
    if duplicate_asset_keys:
        details.extend(f"duplicate_asset_key={item}" for item in sorted(duplicate_asset_keys))
        return CheckResult("export_bundle", False, details)
    if duplicate_export_paths:
        details.extend(f"duplicate_export_path={item}" for item in sorted(duplicate_export_paths))
        return CheckResult("export_bundle", False, details)

    exported_files = build_report.get("ExportedFiles", []) if isinstance(build_report, dict) else []
    missing_report_entries = [name for name in REQUIRED_EXPORT_FILES if name not in exported_files]
    if missing_report_entries:
        details.extend(f"build_report_missing_export_entry={name}" for name in missing_report_entries)
        return CheckResult("export_bundle", False, details)

    details.append(f"asset_entries={len(assets)}")
    return CheckResult("export_bundle", True, details)


def check_runtime_contract(export_dir: Path) -> CheckResult:
    details: list[str] = []
    audio_data = read_json(export_dir / "AudioData.json")
    build_report = read_json(export_dir / "BuildReport.json")
    manifest = read_json(export_dir / "AudioManifest.json")
    event_enum_text = (export_dir / "AudioEventID.cs").read_text(encoding="utf-8")

    events = audio_data.get("Events", {}) if isinstance(audio_data, dict) else {}
    buses = audio_data.get("Buses", []) if isinstance(audio_data, dict) else []
    bus_configs = audio_data.get("BusConfigs", []) if isinstance(audio_data, dict) else []
    manifest_assets = manifest.get("Assets", []) if isinstance(manifest, dict) else []
    enum_members = parse_enum_members(event_enum_text)
    manifest_by_key = {
        asset.get("AssetKey", ""): asset
        for asset in manifest_assets
        if isinstance(asset, dict) and asset.get("AssetKey", "")
    }

    event_ids = sorted(events.keys())
    declared_event_count = int(build_report.get("EventCount", -1)) if isinstance(build_report, dict) else -1
    declared_clip_count = int(build_report.get("ClipCount", -1)) if isinstance(build_report, dict) else -1
    actual_clip_count = 0
    invalid_bus_events: list[str] = []
    manifest_missing_for_clip: list[str] = []
    manifest_runtime_mismatch: list[str] = []

    for event_id, payload in events.items():
        if not isinstance(payload, dict):
            details.append(f"event_payload_invalid={event_id}")
            continue
        clips = payload.get("Clips", [])
        actual_clip_count += len(clips)
        bus_name = payload.get("Bus", "")
        if bus_name and bus_name not in buses:
            invalid_bus_events.append(f"{event_id}:{bus_name}")
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            asset_key = clip.get("AssetKey", "")
            if asset_key not in manifest_by_key:
                manifest_missing_for_clip.append(f"{event_id}:{asset_key}")

    passed = True
    if declared_event_count != len(event_ids):
        passed = False
        details.append(f"event_count_mismatch=build:{declared_event_count},actual:{len(event_ids)}")
    if declared_clip_count != actual_clip_count:
        passed = False
        details.append(f"clip_count_mismatch=build:{declared_clip_count},actual:{actual_clip_count}")
    if enum_members != event_ids:
        passed = False
        details.append("event_enum_mismatch")
        details.append(f"enum_members={','.join(enum_members)}")
        details.append(f"event_ids={','.join(event_ids)}")
    if invalid_bus_events:
        passed = False
        details.extend(f"invalid_bus_binding={entry}" for entry in invalid_bus_events)

    bus_config_names = [config.get("Name", "") for config in bus_configs if isinstance(config, dict)]
    expected_bus_names = sorted({"Master", *buses})
    if sorted(bus_config_names) != expected_bus_names:
        passed = False
        details.append(f"bus_config_names={','.join(sorted(bus_config_names))}")
        details.append(f"expected_bus_names={','.join(expected_bus_names)}")

    runtime_format = audio_data.get("RuntimeAudioFormat", "") if isinstance(audio_data, dict) else ""
    for asset_key, asset in manifest_by_key.items():
        manifest_format = asset.get("RuntimeFormat", "") if isinstance(asset, dict) else ""
        if manifest_format != runtime_format:
            manifest_runtime_mismatch.append(f"{asset_key}:{manifest_format}")
    if manifest_missing_for_clip:
        passed = False
        details.extend(f"manifest_missing_for_clip={entry}" for entry in manifest_missing_for_clip)
    if manifest_runtime_mismatch:
        passed = False
        details.extend(f"manifest_runtime_format_mismatch={entry}" for entry in manifest_runtime_mismatch)

    details.append(f"schema_version={audio_data.get('SchemaVersion', 'unknown')}")
    details.append(f"runtime_audio_format={runtime_format}")
    details.append(f"events={len(event_ids)}")
    details.append(f"clips={actual_clip_count}")
    details.append(f"buses={len(buses)}")
    details.append(f"manifest_assets={len(manifest_by_key)}")
    return CheckResult("runtime_contract", passed, details)


def check_unity_validation_package(unity_validation_dir: Path) -> CheckResult:
    details: list[str] = [f"unity_validation_dir={unity_validation_dir}"]
    missing_files: list[str] = []
    missing_meta: list[str] = []

    for relative_path in REQUIRED_UNITY_RUNTIME_FILES:
        file_path = unity_validation_dir / relative_path
        if not file_path.exists():
            missing_files.append(relative_path)
            continue
        meta_path = file_path.with_name(file_path.name + ".meta")
        if not meta_path.exists():
            missing_meta.append(str(Path(relative_path).with_name(Path(relative_path).name + ".meta")).replace("\\", "/"))

    folder_meta_targets = (
        unity_validation_dir / "Assets/AudioForgeRuntime.meta",
        unity_validation_dir / "Assets/AudioForgeRuntime/Scripts.meta",
        unity_validation_dir / "Assets/AudioForgeRuntime/Editor.meta",
    )
    for meta_path in folder_meta_targets:
        if not meta_path.exists():
            missing_meta.append(str(meta_path.relative_to(unity_validation_dir)).replace("\\", "/"))

    passed = not missing_files and not missing_meta
    details.extend(f"missing_file={item}" for item in missing_files)
    details.extend(f"missing_meta={item}" for item in missing_meta)
    details.append(f"runtime_files_checked={len(REQUIRED_UNITY_RUNTIME_FILES)}")
    return CheckResult("unity_validation_package", passed, details)


def build_report(
    workspace: Path,
    export_dir: Path,
    unity_validation_dir: Path,
    results: list[CheckResult],
) -> dict[str, Any]:
    passed = all(result.passed for result in results)
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "generated_at": timestamp,
        "workspace": str(workspace),
        "export_dir": str(export_dir),
        "unity_validation_dir": str(unity_validation_dir),
        "passed": passed,
        "summary": {
            "total": len(results),
            "passed": sum(1 for result in results if result.passed),
            "failed": sum(1 for result in results if not result.passed),
        },
        "checks": [result.to_dict() for result in results],
    }


def write_reports(report_dir: Path, report: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "full_chain_report.json"
    md_path = report_dir / "full_chain_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")


def render_console_summary(report: dict[str, Any], report_dir: Path) -> str:
    lines = [
        f"AudioForge full-chain check: {'PASS' if report['passed'] else 'FAIL'}",
        f"checks={report['summary']['total']} passed={report['summary']['passed']} failed={report['summary']['failed']}",
        f"json_report={report_dir / 'full_chain_report.json'}",
        f"markdown_report={report_dir / 'full_chain_report.md'}",
    ]
    for check in report["checks"]:
        lines.append(f"- {check['name']}: {'PASS' if check['passed'] else 'FAIL'}")
    return "\n".join(lines)


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AudioForge Full-Chain Report",
        "",
        f"- Generated At: {report['generated_at']}",
        f"- Overall: {'PASS' if report['passed'] else 'FAIL'}",
        f"- Workspace: {report['workspace']}",
        f"- Export Dir: {report['export_dir']}",
        f"- Unity Validation Dir: {report['unity_validation_dir']}",
        "",
        "## Summary",
        "",
        f"- Total Checks: {report['summary']['total']}",
        f"- Passed: {report['summary']['passed']}",
        f"- Failed: {report['summary']['failed']}",
        "",
        "## Checks",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"### {check['name']} - {'PASS' if check['passed'] else 'FAIL'}")
        lines.append("")
        for detail in check["details"]:
            lines.append(f"- {detail}")
        lines.append("")
    return "\n".join(lines)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_enum_members(text: str) -> list[str]:
    match = re.search(r"enum\s+\w+\s*\{(?P<body>.*?)\}", text, re.DOTALL)
    if not match:
        return []
    body = match.group("body")
    members: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        members.append(line)
    return sorted(members)


def tail_lines(text: str, limit: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


if __name__ == "__main__":
    raise SystemExit(main())