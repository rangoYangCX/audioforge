from __future__ import annotations

from pathlib import Path

from tools import run_test_suite


def test_parse_args_collects_passthrough_after_separator() -> None:
    args = run_test_suite.parse_args(["fast", "--", "-k", "validator"])

    assert args.suite == "fast"
    assert args.passthrough == ["-k", "validator"]


def test_run_pytest_suite_builds_expected_command(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Completed:
        returncode = 0

    def fake_run(command, cwd):
        captured["command"] = command
        captured["cwd"] = cwd
        return Completed()

    monkeypatch.setattr(run_test_suite.subprocess, "run", fake_run)

    exit_code = run_test_suite.run_pytest_suite(Path("/tmp/audioforge"), "smoke", ["-k", "full_chain"])

    assert exit_code == 0
    assert captured["cwd"] == Path("/tmp/audioforge")
    assert captured["command"] == [
        run_test_suite.sys.executable,
        "-m",
        "pytest",
        *run_test_suite.SMOKE_TARGETS,
        "-k",
        "full_chain",
    ]


def test_main_routes_main_controller_suite_and_strips_separator(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(run_test_suite, "run_main_controller_suite", lambda workspace, passthrough=None: captured.update({"workspace": workspace, "passthrough": passthrough}) or 0)

    exit_code = run_test_suite.main(["main-controller", "--workspace", str(tmp_path), "--", "--fail-fast"])

    assert exit_code == 0
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["passthrough"] == ["--fail-fast"]