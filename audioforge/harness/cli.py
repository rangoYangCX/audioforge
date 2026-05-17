from __future__ import annotations

import argparse
import json
from pathlib import Path

from audioforge.harness.fixtures import create_workspace_from_base_project, save_sample_project
from audioforge.harness.scenarios import SCENARIO_DESCRIPTIONS, SCENARIO_REGISTRY, render_console_summary, render_markdown_report, run_scenarios


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AudioForge harness environment for repeatable iteration baselines.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-sandbox", help="生成可复用的样本工程和实验工作区。")
    init_parser.add_argument("--target", type=Path, default=Path("reports/harness/sandbox"))
    init_parser.add_argument("--project-name", default="HarnessSample")
    init_parser.add_argument("--workspace-name", default="HarnessWorkspace")
    init_parser.add_argument("--task-name", default="Harness Task")
    init_parser.add_argument("--variant-name", default="default")

    smoke_parser = subparsers.add_parser("run-smoke", help="执行 harness smoke 场景并输出报告。")
    smoke_parser.add_argument("--target", type=Path, default=Path("reports/harness/smoke"))
    smoke_parser.add_argument("--scenario", action="append", choices=sorted(SCENARIO_REGISTRY.keys()))
    smoke_parser.add_argument("--report-json", type=Path)
    smoke_parser.add_argument("--report-markdown", type=Path)

    list_parser = subparsers.add_parser("list-scenarios", help="列出内置 smoke 场景。")
    list_parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _cmd_init_sandbox(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    project_bundle = save_sample_project(target / "project", project_name=args.project_name)
    workspace_bundle = create_workspace_from_base_project(
        target / "workspace",
        project_bundle.project_path,
        workspace_name=args.workspace_name,
        task_name=args.task_name,
        variant_name=args.variant_name,
    )
    manifest = {
        "project": project_bundle.to_dict(),
        "workspace": workspace_bundle.to_dict(),
    }
    manifest_path = target / "harness_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Harness sandbox ready: {target}")
    print(f"Project: {project_bundle.project_path}")
    print(f"Workspace: {workspace_bundle.workspace_path}")
    print(f"Manifest: {manifest_path}")
    return 0


def _cmd_run_smoke(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    report = run_scenarios(target, scenario_names=args.scenario or None)
    json_path = (args.report_json or (target / "harness_report.json")).resolve()
    markdown_path = (args.report_markdown or (target / "harness_report.md")).resolve()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(render_console_summary(report))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if report.passed else 1


def _cmd_list_scenarios(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps(SCENARIO_DESCRIPTIONS, ensure_ascii=False, indent=2))
        return 0
    for name in sorted(SCENARIO_REGISTRY.keys()):
        print(f"{name}: {SCENARIO_DESCRIPTIONS.get(name, '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "init-sandbox":
        return _cmd_init_sandbox(args)
    if args.command == "run-smoke":
        return _cmd_run_smoke(args)
    if args.command == "list-scenarios":
        return _cmd_list_scenarios(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())