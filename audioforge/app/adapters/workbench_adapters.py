from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from audioforge.app.application.ports import ExperimentWorkspaceRepository, PlaybackGateway, ProjectRepository, SettingsStore, SnapshotRepository
from audioforge.app.models.audio_project import AudioProject
from audioforge.app.models.experiment_workspace import ExperimentTask, ExperimentVariant, ExperimentWorkspace
from audioforge.app.services.experiment_serializer import ExperimentWorkspaceSerializer
from audioforge.app.services.playback_service import PlaybackService
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.services.recovery_service import RecoveryService, RecoverySnapshot
from audioforge.app.utils.constants import PROJECT_EXTENSION


class SerializerProjectRepository(ProjectRepository):
    def __init__(self, serializer: ProjectSerializer | None = None) -> None:
        self._serializer = serializer or ProjectSerializer()

    def exists(self, file_path: str) -> bool:
        return Path(file_path).exists()

    def is_file(self, file_path: str) -> bool:
        return Path(file_path).is_file()

    def load(self, file_path: str) -> AudioProject:
        return self._serializer.load(Path(file_path))

    def save(self, project: AudioProject, file_path: str) -> str:
        target_path = Path(file_path)
        self._serializer.save(project, target_path)
        return str(target_path)

    def resolve_save_path(self, file_path: str | None, suggested_name: str) -> str | None:
        if not file_path:
            return None
        save_path = Path(file_path).expanduser()
        if save_path.exists() and save_path.is_dir():
            save_path = save_path / suggested_name
        elif not save_path.suffix and save_path.name in {".", "..", ""}:
            save_path = save_path / suggested_name
        if save_path.suffix != PROJECT_EXTENSION:
            save_path = save_path.with_suffix(PROJECT_EXTENSION)
        return str(save_path)


class SerializerExperimentWorkspaceRepository(ExperimentWorkspaceRepository):
    def __init__(self, serializer: ExperimentWorkspaceSerializer | None = None) -> None:
        self._serializer = serializer or ExperimentWorkspaceSerializer()

    def create(self, workspace_path: str, base_project_path: str, name: str) -> ExperimentWorkspace:
        return self._serializer.create(Path(workspace_path), Path(base_project_path), name)

    def load(self, path: str) -> ExperimentWorkspace:
        return self._serializer.load(Path(path))

    def save(self, workspace: ExperimentWorkspace) -> None:
        self._serializer.save(workspace)

    def create_task(self, workspace: ExperimentWorkspace, name: str, variant_name: str) -> ExperimentTask:
        return self._serializer.create_task(workspace, name, variant_name)

    def delete_task(self, workspace: ExperimentWorkspace, task_index: int) -> None:
        self._serializer.delete_task(workspace, task_index)

    def create_variant(self, workspace: ExperimentWorkspace, task_index: int, variant_name: str) -> ExperimentVariant:
        return self._serializer.create_variant(workspace, task_index, variant_name)

    def duplicate_variant(
        self,
        workspace: ExperimentWorkspace,
        task_index: int,
        variant_index: int,
        new_name: str,
    ) -> ExperimentVariant:
        return self._serializer.duplicate_variant(workspace, task_index, variant_index, new_name)

    def delete_variant(self, workspace: ExperimentWorkspace, task_index: int, variant_index: int) -> None:
        self._serializer.delete_variant(workspace, task_index, variant_index)

    def sync_variant_from_base(self, workspace: ExperimentWorkspace, task_index: int, variant_index: int) -> str | None:
        backup_path = self._serializer.sync_variant_from_base(workspace, task_index, variant_index)
        return str(backup_path) if backup_path is not None else None


class RecoveryServiceSnapshotRepository(SnapshotRepository):
    def __init__(self, recovery_service: RecoveryService | None = None) -> None:
        self._recovery_service = recovery_service or RecoveryService()

    def has_snapshot(self) -> bool:
        return self._recovery_service.has_snapshot()

    def exists(self, snapshot_path: str) -> bool:
        return Path(snapshot_path).exists()

    def save_snapshot(self, project: AudioProject) -> str:
        return str(self._recovery_service.save_snapshot(project))

    def save_history_snapshot(self, project: AudioProject, *, max_entries: int = 10) -> str:
        return str(self._recovery_service.save_history_snapshot(project, max_entries=max_entries))

    def load_snapshot(self, snapshot_path: str | None = None) -> RecoverySnapshot:
        return self._recovery_service.load_snapshot(Path(snapshot_path) if snapshot_path else None)

    def list_history_snapshots(self) -> list[str]:
        return [str(path) for path in self._recovery_service.list_history_snapshots()]

    def clear_snapshot(self) -> None:
        self._recovery_service.clear_snapshot()


class QtSettingsStore(SettingsStore):
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("AudioForge", "Workbench")

    def get_value(self, key: str, default: Any = None) -> Any:
        return self._settings.value(key, default)

    def set_value(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)


class PlaybackServiceGateway(PlaybackGateway):
    def __init__(self, playback_service: PlaybackService | None = None) -> None:
        self._playback_service = playback_service or PlaybackService()

    def play_file(
        self,
        file_path: str,
        *,
        event_id: str,
        volume_db: float,
        pitch_cents: int,
        trim_start_ms: int,
        trim_end_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
    ) -> str:
        return self._playback_service.play_file(
            file_path,
            event_id=event_id,
            volume_db=volume_db,
            pitch_cents=pitch_cents,
            trim_start_ms=trim_start_ms,
            trim_end_ms=trim_end_ms,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

    def stop_event(self, event_id: str) -> None:
        self._playback_service.stop_event(event_id)

    def stop_oldest(self, event_id: str) -> None:
        self._playback_service.stop_oldest(event_id)

    def has_active_event(self, event_id: str) -> bool:
        return self._playback_service.has_active_event(event_id)

    def is_event_paused(self, event_id: str) -> bool:
        return self._playback_service.is_event_paused(event_id)

    def pause_event(self, event_id: str) -> bool:
        return self._playback_service.pause_event(event_id)

    def resume_event(self, event_id: str) -> bool:
        return self._playback_service.resume_event(event_id)

    def stop_buses(self, bus_names: list[str]) -> None:
        self._playback_service.stop_buses(bus_names)

    def refresh_bus_volumes(self, resolver: Callable[[str], float]) -> None:
        self._playback_service.refresh_bus_volumes(resolver)