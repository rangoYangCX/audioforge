from __future__ import annotations

import json
from pathlib import Path

from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.harness.cli import main as harness_main
from audioforge.harness.fixtures import create_workspace_from_base_project, save_sample_project
from audioforge.harness.scenarios import run_scenarios


def test_harness_save_sample_project_creates_portable_bundle(tmp_path: Path) -> None:
    bundle = save_sample_project(tmp_path, project_name="HarnessFixture")
    loaded = ProjectSerializer().load(bundle.project_path)

    assert bundle.project_path.exists()
    assert Path(loaded.events["UiClick"].clips[0].source_path).exists()
    assert Path(loaded.settings.export_root) == bundle.export_root
    assert any(event.display_name == "BGM Menu Loop" for event in loaded.events.values())


def test_harness_create_workspace_from_base_project_creates_variant_bundle(tmp_path: Path) -> None:
    project_bundle = save_sample_project(tmp_path / "project")
    workspace_bundle = create_workspace_from_base_project(
        tmp_path / "workspace",
        project_bundle.project_path,
        workspace_name="HarnessWorkspace",
        task_name="Harness Task",
    )
    loaded_variant = ProjectSerializer().load(workspace_bundle.default_variant_path)

    assert workspace_bundle.workspace_path.exists()
    assert workspace_bundle.default_variant_path.exists()
    assert Path(loaded_variant.events["UiClick"].clips[0].source_path).exists()


def test_harness_run_scenarios_produces_passing_report(tmp_path: Path) -> None:
    report = run_scenarios(
        tmp_path,
        scenario_names=[
            "project_roundtrip",
            "export_contract",
            "build_export_cycle",
            "recovery_cycle",
            "recovery_reopen_cycle",
            "experiment_cycle",
            "experiment_delta_export",
        ],
    )

    assert report.passed is True
    assert [result.name for result in report.results] == [
        "project_roundtrip",
        "export_contract",
        "build_export_cycle",
        "recovery_cycle",
        "recovery_reopen_cycle",
        "experiment_cycle",
        "experiment_delta_export",
    ]


def test_harness_cli_init_sandbox_and_run_smoke_write_reports(tmp_path: Path) -> None:
    sandbox_root = tmp_path / "sandbox"
    smoke_root = tmp_path / "smoke"

    assert harness_main(["init-sandbox", "--target", str(sandbox_root)]) == 0
    assert harness_main(["run-smoke", "--target", str(smoke_root), "--scenario", "build_export_cycle"]) == 0

    manifest = json.loads((sandbox_root / "harness_manifest.json").read_text(encoding="utf-8"))
    smoke_report = json.loads((smoke_root / "harness_report.json").read_text(encoding="utf-8"))

    assert Path(manifest["project"]["project_path"]).exists()
    assert Path(manifest["workspace"]["workspace_path"]).exists()
    assert smoke_report["passed"] is True
    assert smoke_report["results"][0]["name"] == "build_export_cycle"