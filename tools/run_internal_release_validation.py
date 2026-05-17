from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, BusConfig, ClipModel, EventModel, MASTER_BUS_NAME, ProjectSettings
from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.services.validator import ProjectValidator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a smoke-test AudioForge project from a real WAV directory and run release validation.")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source-dir", type=Path)
    source_group.add_argument("--existing-export-dir", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-harness", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    source_dir = args.source_dir.resolve() if args.source_dir is not None else None
    existing_export_dir = args.existing_export_dir.resolve() if args.existing_export_dir is not None else None
    default_report_dirname = "internal_release_existing_export" if existing_export_dir is not None else "internal_release_smoke"
    report_root = (args.report_root or (workspace / "reports" / default_report_dirname)).resolve()
    export_root = existing_export_dir if existing_export_dir is not None else (report_root / "export")
    checks_root = report_root / "checks"
    project_path = report_root / "internal_release_smoke.afproj"

    selected_files: list[Path] = []
    warning_count = 0
    smoke_project_path: Path | None = None
    validation_mode = "existing_export" if existing_export_dir is not None else "wav_smoke"

    if source_dir is not None:
        wav_files = sorted(source_dir.rglob("*.wav"))
        if not wav_files:
            print(f"No WAV files found under {source_dir}")
            return 1

        selected_files = wav_files[: max(1, args.limit)]
        project = build_smoke_project(selected_files, export_root)

        validator = ProjectValidator()
        issues = validator.validate(project)
        error_count = sum(1 for issue in issues if issue.severity == "Error")
        warning_count = sum(1 for issue in issues if issue.severity == "Warning")
        if error_count:
            print(f"Validation failed before export: errors={error_count} warnings={warning_count}")
            for issue in issues:
                print(f"- {issue.severity} {issue.code} {issue.target}: {issue.message}")
            return 1

        report_root.mkdir(parents=True, exist_ok=True)
        ProjectSerializer().save(project, project_path)
        RuntimeExporter().export(project, export_root, issues)
        smoke_project_path = project_path
    else:
        report_root.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        str(workspace / "tools" / "run_full_chain_check.py"),
        "--workspace",
        str(workspace),
        "--export-dir",
        str(export_root),
        "--report-dir",
        str(checks_root),
    ]
    if args.skip_pytest:
        command.append("--skip-pytest")
    if args.skip_harness:
        command.append("--skip-harness")
    completed = subprocess.run(command, cwd=workspace)
    write_release_signoff(
        report_root=report_root,
        project_path=smoke_project_path,
        export_root=export_root,
        checks_root=checks_root,
        selected_files=selected_files,
        warning_count=warning_count,
        passed=completed.returncode == 0,
        validation_mode=validation_mode,
    )
    if smoke_project_path is not None:
        print(f"Smoke project saved to {smoke_project_path}")
    else:
        print(f"Validated existing export directory: {export_root}")
    print(f"Export directory: {export_root}")
    print(f"Selected WAV files: {len(selected_files)}")
    print(f"Warnings: {warning_count}")
    return completed.returncode


def build_smoke_project(wav_files: list[Path], export_root: Path) -> AudioProject:
    project = AudioProject.create_empty(name="InternalReleaseSmoke")
    project.settings = ProjectSettings(
        default_bus="SFX",
        export_root=str(export_root),
        buses=["BGM", "SFX", "UI"],
        bus_configs=[
            BusConfig(name=MASTER_BUS_NAME),
            BusConfig(name="BGM", volume_db=-2.0),
            BusConfig(name="SFX", volume_db=-1.0),
            BusConfig(name="UI", parent_bus="SFX", volume_db=-1.5),
        ],
        source_audio_format="wav",
        runtime_audio_format="wav",
    )
    root_folder_id = project.root_folder_ids[0]
    used_event_ids: set[str] = set()

    for index, wav_path in enumerate(wav_files, start=1):
        bus_name = classify_bus(wav_path)
        event_id = make_event_id(wav_path.stem, index, used_event_ids)
        asset_key = f"{bus_name.lower()}/{index:02d}_{slugify(wav_path.stem)}"
        clip = ClipModel.from_path(wav_path, asset_key)
        event = EventModel(
            id=event_id,
            display_name=wav_path.stem,
            bus=bus_name,
            volume_db=-2.0 if bus_name == "UI" else -3.0,
            clips=[clip],
        )
        project.add_event(root_folder_id, event)
        used_event_ids.add(event_id)

    return project


def classify_bus(wav_path: Path) -> str:
    stem = wav_path.stem.upper()
    if stem.startswith("UI"):
        return "UI"
    if "BGM" in stem or "MUSIC" in stem:
        return "BGM"
    return "SFX"


def make_event_id(stem: str, index: int, used_ids: set[str]) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"Event_{index}_{normalized}".strip("_")
    candidate = normalized
    suffix = 1
    while candidate in used_ids:
        suffix += 1
        candidate = f"{normalized}_{suffix}"
    return candidate


def slugify(stem: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    return slug or "clip"


def write_release_signoff(
    *,
    report_root: Path,
    project_path: Path | None,
    export_root: Path,
    checks_root: Path,
    selected_files: list[Path],
    warning_count: int,
    passed: bool,
    validation_mode: str,
) -> None:
    full_chain_report_path = checks_root / "full_chain_report.json"
    full_chain_report = json.loads(full_chain_report_path.read_text(encoding="utf-8")) if full_chain_report_path.exists() else {}
    risks = [
        "Unity 侧仍是参考运行时，生产项目接入前仍需做一次目标工程联调。",
        "自动恢复当前覆盖单份最近快照，适合内部上线前保护，不等于完整版本化备份。",
        "本轮签收仍不代表已穷尽全部素材边界。",
    ]
    harness_report_path = checks_root / "harness_smoke" / "harness_report.json"
    project_label = str(project_path) if project_path is not None else "(existing export mode; no smoke project generated)"
    summary = {
        "overall": "PASS" if passed else "FAIL",
        "validation_mode": validation_mode,
        "project_path": project_label,
        "export_root": str(export_root),
        "checks_root": str(checks_root),
        "harness_report_path": str(harness_report_path),
        "harness_report_exists": harness_report_path.exists(),
        "selected_wav_files": [str(path) for path in selected_files],
        "warning_count": warning_count,
        "full_chain_report": full_chain_report,
        "residual_risks": risks,
    }
    (report_root / "release_signoff.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# AudioForge Internal Release Sign-off",
        "",
        f"- Result: {'PASS' if passed else 'FAIL'}",
        f"- Validation Mode: {validation_mode}",
        f"- Smoke Project: {project_label}",
        f"- Export Root: {export_root}",
        f"- Check Reports: {checks_root}",
        f"- Harness Report: {harness_report_path}",
        f"- Selected WAV Files: {len(selected_files)}",
        f"- Validation Warnings: {warning_count}",
        "",
        "## Residual Risks",
        "",
    ]
    for risk in risks:
        lines.append(f"- {risk}")
    (report_root / "release_signoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())