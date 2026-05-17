from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BATCHES: dict[str, list[str]] = {
    "experiment_guards": ["tests/unit/test_main_controller_experiment_guards.py"],
    "layout_experiment": ["tests/unit/test_main_controller_layout_experiment.py"],
    "layout_preview_gamesync": ["tests/unit/test_main_controller_preview_gamesync_layout.py"],
    "layout_preview_transport": ["tests/unit/test_main_controller_preview_transport_layout.py"],
    "layout_preview_recent": ["tests/unit/test_main_controller_preview_recent_layout.py"],
    "layout_build": ["tests/unit/test_main_controller_layout_build.py"],
    "full_flow_build": ["tests/unit/test_main_controller_full_flow.py", "-k", "build"],
}


@dataclass(slots=True)
class BatchResult:
    name: str
    passed: bool
    duration_seconds: float
    command: list[str]
    stdout_tail: list[str]
    stderr_tail: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_seconds": round(self.duration_seconds, 2),
            "command": list(self.command),
            "stdout_tail": list(self.stdout_tail),
            "stderr_tail": list(self.stderr_tail),
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run fixed main_controller stability pytest batches.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--batch", action="append", choices=sorted(DEFAULT_BATCHES.keys()))
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--report-markdown", type=Path)
    parser.add_argument("--fail-fast", action="store_true")
    return parser.parse_args(argv)


def _tail_lines(text: str, limit: int = 12) -> list[str]:
    lines = [line.rstrip() for line in text.splitlines() if line.rstrip()]
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def run_batch(workspace: Path, name: str, args: list[str]) -> BatchResult:
    command = [sys.executable, "-m", "pytest", *args, "-q"]
    env = dict(**subprocess.os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    duration_seconds = time.perf_counter() - started
    return BatchResult(
        name=name,
        passed=completed.returncode == 0,
        duration_seconds=duration_seconds,
        command=command,
        stdout_tail=_tail_lines(completed.stdout),
        stderr_tail=_tail_lines(completed.stderr),
    )


def run_batches(workspace: Path, batch_names: list[str], *, fail_fast: bool = False) -> list[BatchResult]:
    results: list[BatchResult] = []
    for name in batch_names:
        result = run_batch(workspace, name, DEFAULT_BATCHES[name])
        results.append(result)
        if fail_fast and not result.passed:
            break
    return results


def render_markdown_report(workspace: Path, results: list[BatchResult]) -> str:
    overall_passed = all(result.passed for result in results)
    lines = [
        "# MainController Stability Batches",
        "",
        f"- Workspace: {workspace}",
        f"- Overall: {'PASS' if overall_passed else 'FAIL'}",
        f"- Batch Count: {len(results)}",
        "",
        "## Results",
        "",
    ]
    for result in results:
        lines.append(f"### {result.name}")
        lines.append("")
        lines.append(f"- Status: {'PASS' if result.passed else 'FAIL'}")
        lines.append(f"- Duration Seconds: {result.duration_seconds:.2f}")
        lines.append(f"- Command: {' '.join(result.command)}")
        if result.stdout_tail:
            lines.append("- Stdout Tail:")
            for line in result.stdout_tail:
                lines.append(f"  - {line}")
        if result.stderr_tail:
            lines.append("- Stderr Tail:")
            for line in result.stderr_tail:
                lines.append(f"  - {line}")
        lines.append("")
    return "\n".join(lines)


def render_console_summary(results: list[BatchResult]) -> str:
    overall_passed = all(result.passed for result in results)
    lines = [f"MainController Stability Batches: {'PASS' if overall_passed else 'FAIL'}"]
    for result in results:
        lines.append(f"- [{'PASS' if result.passed else 'FAIL'}] {result.name} ({result.duration_seconds:.2f}s)")
    return "\n".join(lines)


def write_batch_reports(
    workspace: Path,
    results: list[BatchResult],
    report_json: Path,
    report_markdown: Path,
) -> dict[str, Any]:
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_markdown.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspace": str(workspace),
        "passed": all(result.passed for result in results),
        "results": [result.to_dict() for result in results],
    }
    report_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_markdown.write_text(render_markdown_report(workspace, results), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = args.workspace.resolve()
    selected_names = args.batch or list(DEFAULT_BATCHES.keys())
    results = run_batches(workspace, selected_names, fail_fast=args.fail_fast)

    report_json = (args.report_json or (workspace / "reports" / "main_controller_stability_batches.json")).resolve()
    report_markdown = (args.report_markdown or (workspace / "reports" / "main_controller_stability_batches.md")).resolve()
    payload = write_batch_reports(workspace, results, report_json, report_markdown)
    print(render_console_summary(results))
    print(f"JSON report: {report_json}")
    print(f"Markdown report: {report_markdown}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())