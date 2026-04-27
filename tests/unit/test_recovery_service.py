from __future__ import annotations

from pathlib import Path

from audioforge.app.services.recovery_service import RecoveryService

from tests.helpers import build_sample_project


def test_recovery_service_roundtrip_and_clear(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)
    recovery = RecoveryService(tmp_path / "Recovery")

    recovery.save_snapshot(project)
    snapshot = recovery.load_snapshot()

    assert recovery.has_snapshot() is True
    assert snapshot.project.name == project.name
    assert snapshot.project.events["UiClick"].clips[0].asset_key == "ui/click_primary"
    assert snapshot.original_project_path == project.file_path

    recovery.clear_snapshot()

    assert recovery.has_snapshot() is False