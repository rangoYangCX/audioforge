from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from audioforge.app.application.recovery_autosave_controller import RecoveryAutosaveController
from audioforge.app.services.recovery_service import RecoverySnapshot
from audioforge.app.models.audio_project import AudioProject, ClipModel, EventModel


@dataclass
class _FakeSettingsStore:
    values: dict[str, object]

    def get_value(self, key: str, default=None):
        return self.values.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        self.values[key] = value


class _FakeSnapshotRepository:
    def __init__(self, snapshot: RecoverySnapshot | None = None) -> None:
        self.snapshot = snapshot
        self.history: list[tuple[str, RecoverySnapshot]] = []
        self.cleared = False
        self.fail_save = False

    def has_snapshot(self) -> bool:
        return self.snapshot is not None

    def exists(self, snapshot_path: str) -> bool:
        return any(path == snapshot_path for path, _snapshot in self.history)

    def save_snapshot(self, project: AudioProject) -> str:
        if self.fail_save:
            raise OSError("disk full")
        self.snapshot = RecoverySnapshot(project=project, saved_at="2026-05-17T10:00:00Z", original_project_path=project.file_path)
        return "/tmp/recovery.json"

    def save_history_snapshot(self, project: AudioProject, *, max_entries: int = 10) -> str:
        path = f"/tmp/history_{len(self.history)}.json"
        self.history.append(
            (
                path,
                RecoverySnapshot(project=project, saved_at=f"2026-05-17T10:00:0{len(self.history)}Z", original_project_path=project.file_path),
            )
        )
        return path

    def load_snapshot(self, snapshot_path: str | None = None) -> RecoverySnapshot:
        if snapshot_path is None:
            if self.snapshot is None:
                raise FileNotFoundError("missing snapshot")
            return self.snapshot
        for path, snapshot in self.history:
            if path == snapshot_path:
                return snapshot
        raise FileNotFoundError(snapshot_path)

    def list_history_snapshots(self) -> list[str]:
        return [path for path, _snapshot in reversed(self.history)]

    def clear_snapshot(self) -> None:
        self.cleared = True
        self.snapshot = None


def _make_project(file_path: str | None = None) -> AudioProject:
    project = AudioProject.create_empty(name="RecoverySample")
    root_folder_id = project.root_folder_ids[0]
    clip = ClipModel.from_path(Path("/tmp/ui_click.wav"), "ui/click")
    event = EventModel(id="UiClick", display_name="UI Click", clips=[clip])
    project.add_event(root_folder_id, event)
    project.file_path = file_path
    return project


def test_save_recovery_snapshot_clears_on_failure() -> None:
    snapshot_repository = _FakeSnapshotRepository()
    snapshot_repository.fail_save = True
    controller = RecoveryAutosaveController(snapshot_repository, _FakeSettingsStore({}))

    result = controller.save_recovery_snapshot(_make_project("/tmp/sample.afproj"))

    assert result.success is False
    assert snapshot_repository.cleared is True
    assert result.notifications[0].log_message == "自动恢复快照保存失败：OSError: disk full"


def test_prepare_recovery_restore_returns_confirmation_request() -> None:
    snapshot = RecoverySnapshot(
        project=_make_project("/tmp/sample.afproj"),
        saved_at="2026-05-17T10:00:00Z",
        original_project_path="/tmp/sample.afproj",
    )
    controller = RecoveryAutosaveController(_FakeSnapshotRepository(snapshot), _FakeSettingsStore({}))

    result = controller.prepare_recovery_restore()

    assert result.success is True
    assert result.value is not None
    assert "是否恢复这份快照" in result.value.message


def test_restore_autosave_snapshot_returns_project_session_state() -> None:
    project = _make_project("/tmp/sample.afproj")
    snapshot_repository = _FakeSnapshotRepository()
    snapshot_repository.history.append(
        (
            "/tmp/history_0.json",
            RecoverySnapshot(project=project, saved_at="2026-05-17T10:00:00Z", original_project_path=project.file_path),
        )
    )
    controller = RecoveryAutosaveController(snapshot_repository, _FakeSettingsStore({}))

    result = controller.restore_autosave_snapshot("/tmp/history_0.json")

    assert result.success is True
    assert result.value is not None
    assert result.value.selected_event_id == "UiClick"


def test_current_project_history_entries_filters_paths() -> None:
    project = _make_project("/tmp/sample.afproj")
    snapshot_repository = _FakeSnapshotRepository()
    snapshot_repository.history.extend(
        [
            (
                "/tmp/history_0.json",
                RecoverySnapshot(project=project, saved_at="2026-05-17T10:00:00Z", original_project_path="/tmp/sample.afproj"),
            ),
            (
                "/tmp/history_1.json",
                RecoverySnapshot(project=project, saved_at="2026-05-17T10:01:00Z", original_project_path="/tmp/other.afproj"),
            ),
        ]
    )
    controller = RecoveryAutosaveController(snapshot_repository, _FakeSettingsStore({}))

    entries = controller.current_project_history_entries("/tmp/sample.afproj", None)

    assert len(entries) == 1
    assert entries[0]["path"] == "/tmp/history_0.json"