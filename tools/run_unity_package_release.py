from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync, validate, package, and sign off the Unity integration package release."
    )
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-root", type=Path)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--skip-pytest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    report_root = (args.report_root or (workspace / "reports" / "unity_package_release")).resolve()
    export_dir = (args.export_dir or (workspace / "reports" / "internal_release_smoke" / "export")).resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    sync_command = [sys.executable, str(workspace / "tools" / "sync_unity_integration_package.py")]
    full_chain_command = [
        sys.executable,
        str(workspace / "tools" / "run_full_chain_check.py"),
        "--workspace",
        str(workspace),
        "--export-dir",
        str(export_dir),
        "--report-dir",
        str(report_root / "checks"),
    ]
    if args.skip_pytest:
        full_chain_command.append("--skip-pytest")
    package_command = [sys.executable, str(workspace / "tools" / "package_unity_integration_package.py")]

    sync_result = run_command(sync_command, workspace)
    full_chain_result = run_command(full_chain_command, workspace)
    package_result = run_command(package_command, workspace) if full_chain_result.returncode == 0 else None

    passed = sync_result.returncode == 0 and full_chain_result.returncode == 0 and package_result is not None and package_result.returncode == 0

    release_root = workspace / "dist" / f"AudioForgeUnityPackage-{APP_VERSION}"
    archive_path = workspace / "dist" / f"AudioForgeUnityPackage-{APP_VERSION}.zip"

    summary = {
        "overall": "PASS" if passed else "FAIL",
        "version": APP_VERSION,
        "sync": command_to_summary(sync_result),
        "full_chain": command_to_summary(full_chain_result),
        "package": command_to_summary(package_result),
        "release_root": str(release_root),
        "archive_path": str(archive_path),
        "release_root_exists": release_root.exists(),
        "archive_exists": archive_path.exists(),
        "residual_risks": [
            "当前环境未接入 Unity 编辑器命令行，因此这次签收仍以仓库静态检查和包完整性检查为主。",
            "最终项目仍需在目标 Unity 工程里跑一次场景级联调，确认 AudioMixer 路由和业务事件配置符合预期。",
        ],
    }
    write_signoff(report_root, summary)
    embed_signoff_in_release(report_root, release_root)

    print(f"Unity package release result: {summary['overall']}")
    print(f"Sign-off JSON: {report_root / 'unity_package_release_signoff.json'}")
    print(f"Sign-off Markdown: {report_root / 'unity_package_release_signoff.md'}")
    if summary["release_root_exists"]:
        print(f"Release directory: {release_root}")
    if summary["archive_exists"]:
        print(f"Release archive: {archive_path}")
    return 0 if passed else 1


def run_command(command: list[str], workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def command_to_summary(result: subprocess.CompletedProcess[str] | None) -> dict[str, object]:
    if result is None:
        return {
            "ran": False,
            "exit_code": None,
            "stdout_tail": [],
            "stderr_tail": [],
        }
    return {
        "ran": True,
        "exit_code": result.returncode,
        "stdout_tail": tail_lines(result.stdout, 20),
        "stderr_tail": tail_lines(result.stderr, 20),
    }


def tail_lines(text: str, limit: int) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def write_signoff(report_root: Path, summary: dict[str, object]) -> None:
    json_path = report_root / "unity_package_release_signoff.json"
    markdown_path = report_root / "unity_package_release_signoff.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AudioForge Unity Package Release Sign-off",
        "",
        f"- Result: {summary['overall']}",
        f"- Version: {summary['version']}",
        f"- Release Directory: {summary['release_root']}",
        f"- Release Archive: {summary['archive_path']}",
        "",
        "## Command Results",
        "",
    ]
    lines.extend(render_command_section("sync", summary["sync"]))
    lines.extend(render_command_section("full_chain", summary["full_chain"]))
    lines.extend(render_command_section("package", summary["package"]))
    lines.append("")
    lines.append("## Residual Risks")
    lines.append("")
    for risk in summary["residual_risks"]:
        lines.append(f"- {risk}")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def embed_signoff_in_release(report_root: Path, release_root: Path) -> None:
    if not release_root.exists():
        return

    verification_root = release_root / "Documentation~" / "Verification"
    verification_root.mkdir(parents=True, exist_ok=True)

    for file_name in ("unity_package_release_signoff.json", "unity_package_release_signoff.md"):
        source_path = report_root / file_name
        if source_path.exists():
            shutil.copy2(source_path, verification_root / file_name)


def render_command_section(name: str, payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return [f"- {name}: unavailable"]
    lines = [f"- {name}: {'ran' if payload.get('ran') else 'skipped'} exit_code={payload.get('exit_code')}"]
    stdout_tail = payload.get("stdout_tail", [])
    stderr_tail = payload.get("stderr_tail", [])
    if isinstance(stdout_tail, list):
        for line in stdout_tail:
            lines.append(f"  stdout: {line}")
    if isinstance(stderr_tail, list):
        for line in stderr_tail:
            lines.append(f"  stderr: {line}")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())