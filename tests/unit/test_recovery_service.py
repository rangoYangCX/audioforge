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


def test_recovery_service_history_snapshots_keep_recent_entries(tmp_path: Path) -> None:
    project, _ = build_sample_project(tmp_path)
    recovery = RecoveryService(tmp_path / "Recovery")

    first_path = recovery.save_history_snapshot(project, max_entries=2)
    second_path = recovery.save_history_snapshot(project, max_entries=2)
    third_path = recovery.save_history_snapshot(project, max_entries=2)

    history_paths = recovery.list_history_snapshots()

    assert len(history_paths) == 2
    assert third_path in history_paths
    assert second_path in history_paths
    assert first_path not in history_paths