from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SMOKE_TARGETS = [
    "tests/unit/test_documentation_baseline.py",
    "tests/unit/test_full_chain_check.py",
    "tests/unit/test_harness_environment.py",
    "tests/unit/test_validator.py",
    "tests/unit/test_exporter.py",
]

SUITE_ARGS: dict[str, list[str]] = {
    "fast": ["-m", "fast"],
    "gui": ["-m", "gui"],
    "integration": ["-m", "integration"],
    "release": ["-m", "release"],
    "smoke": SMOKE_TARGETS,
    "all": [],
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a curated AudioForge pytest suite.")
    parser.add_argument("suite", choices=[*SUITE_ARGS.keys(), "main-controller"])
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    args, passthrough = parser.parse_known_args(argv)
    args.passthrough = passthrough
    return args


def run_pytest_suite(workspace: Path, suite: str, passthrough: list[str] | None = None) -> int:
    command = [sys.executable, "-m", "pytest", *SUITE_ARGS[suite], *(passthrough or [])]
    return subprocess.run(command, cwd=workspace).returncode


def run_main_controller_suite(workspace: Path, passthrough: list[str] | None = None) -> int:
    command = [sys.executable, str(workspace / "tools" / "run_main_controller_stability_batches.py"), *(passthrough or [])]
    return subprocess.run(command, cwd=workspace).returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    workspace = args.workspace.resolve()
    passthrough = list(args.passthrough or [])
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    if args.suite == "main-controller":
        return run_main_controller_suite(workspace, passthrough)
    return run_pytest_suite(workspace, args.suite, passthrough)


if __name__ == "__main__":
    raise SystemExit(main())