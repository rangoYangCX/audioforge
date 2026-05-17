from __future__ import annotations

from pathlib import Path

from audioforge.app.application.contracts import AutosavePreferences, ConfirmationRequest, ProjectSessionState, UserNotification, WorkflowResult
from audioforge.app.application.ports import SettingsStore, SnapshotRepository
from audioforge.app.models.audio_project import AudioProject


class RecoveryAutosaveController:
    def __init__(self, snapshot_repository: SnapshotRepository, settings_store: SettingsStore) -> None:
        self._snapshot_repository = snapshot_repository
        self._settings_store = settings_store

    def restore_preferences(self) -> AutosavePreferences:
        enabled = str(self._settings_store.get_value("autosaveEnabled", "true")).lower() != "false"
        interval_value = self._settings_store.get_value("autosaveIntervalMinutes", 5)
        try:
            interval_minutes = max(1, int(interval_value))
        except (TypeError, ValueError):
            interval_minutes = 5
        return AutosavePreferences(enabled=enabled, interval_minutes=interval_minutes)

    def update_preferences(self, preferences: dict[str, object]) -> AutosavePreferences:
        normalized = AutosavePreferences(
            enabled=bool(preferences.get("enabled", True)),
            interval_minutes=max(1, int(preferences.get("interval_minutes", 5))),
        )
        self._settings_store.set_value("autosaveEnabled", normalized.enabled)
        self._settings_store.set_value("autosaveIntervalMinutes", normalized.interval_minutes)
        return normalized

    def build_history_entries(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for snapshot_path in self._snapshot_repository.list_history_snapshots()[:10]:
            try:
                snapshot = self._snapshot_repository.load_snapshot(snapshot_path)
            except Exception:
                continue
            original_name = Path(snapshot.original_project_path).name if snapshot.original_project_path else "未保存工程"
            entries.append(
                {
                    "label": f"{snapshot.saved_at} | {original_name}",
                    "path": snapshot_path,
                    "detail": f"原工程：{snapshot.original_project_path or '-'}\n快照：{snapshot_path}",
                    "original_project_path": snapshot.original_project_path or "",
                }
            )
        return entries

    def current_project_history_entries(
        self,
        project_file_path: str | None,
        current_variant_path: str | None,
    ) -> list[dict[str, object]]:
        current_paths: set[str] = set()
        if project_file_path:
            current_paths.add(str(Path(project_file_path).resolve(strict=False)))
        if current_variant_path:
            current_paths.add(str(Path(current_variant_path).resolve(strict=False)))
        if not current_paths:
            return []

        entries = []
        for entry in self.build_history_entries():
            original_project_path = str(entry.get("original_project_path", "")).strip()
            if not original_project_path:
                continue
            resolved_original = str(Path(original_project_path).resolve(strict=False))
            if resolved_original in current_paths:
                entries.append(entry)
        return entries[:5]

    def save_recovery_snapshot(self, project: AudioProject) -> WorkflowResult[None]:
        try:
            self._snapshot_repository.save_snapshot(project)
        except Exception as exc:
            notifications = [
                UserNotification(
                    level="warning",
                    title="自动恢复快照保存失败",
                    message=str(exc),
                    log_message=f"自动恢复快照保存失败：{type(exc).__name__}: {exc}",
                )
            ]
            try:
                self._snapshot_repository.clear_snapshot()
            except Exception as cleanup_exc:
                notifications.append(
                    UserNotification(
                        level="warning",
                        title="自动恢复快照清理失败",
                        message=str(cleanup_exc),
                        log_message=f"自动恢复快照清理失败：{type(cleanup_exc).__name__}: {cleanup_exc}",
                    )
                )
            return WorkflowResult(success=False, notifications=notifications)
        return WorkflowResult(success=True)

    def perform_autosave(self, project: AudioProject, *, enabled: bool, is_dirty: bool) -> WorkflowResult[str]:
        if not enabled or not is_dirty:
            return WorkflowResult(success=False, cancelled=True)
        try:
            self._snapshot_repository.save_snapshot(project)
            history_path = self._snapshot_repository.save_history_snapshot(project)
        except Exception as exc:
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(
                        level="warning",
                        title="自动保存失败",
                        message=str(exc),
                        log_message=f"自动保存失败：{type(exc).__name__}: {exc}",
                    )
                ],
            )
        return WorkflowResult(success=True, value=history_path)

    def prepare_autosave_restore(self, snapshot_path: str) -> WorkflowResult[ConfirmationRequest]:
        target_path = str(snapshot_path).strip()
        if not self._snapshot_repository.exists(target_path):
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(
                        level="warning",
                        title="恢复自动保存失败",
                        message=f"找不到快照文件：{target_path}",
                    )
                ],
            )
        return WorkflowResult(
            success=True,
            value=ConfirmationRequest(
                title="恢复自动保存",
                message=(
                    "恢复后会用自动保存快照覆盖当前内存中的工程状态。\n\n"
                    f"快照：{Path(target_path).name}\n是否继续？"
                ),
                default_accept=False,
            ),
        )

    def restore_autosave_snapshot(self, snapshot_path: str) -> WorkflowResult[ProjectSessionState]:
        try:
            snapshot = self._snapshot_repository.load_snapshot(snapshot_path)
        except Exception as exc:
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(level="warning", title="恢复自动保存失败", message=str(exc))
                ],
            )
        return WorkflowResult(success=True, value=self._session_state_from_project(snapshot.project))

    def prepare_recovery_restore(self) -> WorkflowResult[ConfirmationRequest]:
        if not self._snapshot_repository.has_snapshot():
            return WorkflowResult(success=False, cancelled=True)
        try:
            snapshot = self._snapshot_repository.load_snapshot()
        except Exception as exc:
            self._safe_clear_snapshot()
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(
                        level="warning",
                        title="自动恢复快照损坏",
                        message=str(exc),
                        log_message=f"自动恢复快照损坏，已忽略：{exc}",
                    )
                ],
            )
        prompt = (
            "检测到未保存的自动恢复快照。\n\n"
            f"工程路径：{snapshot.original_project_path or '未保存工程'}\n"
            f"快照时间：{snapshot.saved_at}\n\n"
            "是否恢复这份快照？"
        )
        return WorkflowResult(
            success=True,
            value=ConfirmationRequest(
                title="恢复自动保存快照",
                message=prompt,
                default_accept=False,
            ),
        )

    def restore_recovery_snapshot(self) -> WorkflowResult[ProjectSessionState]:
        try:
            snapshot = self._snapshot_repository.load_snapshot()
        except Exception as exc:
            self._safe_clear_snapshot()
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(
                        level="warning",
                        title="自动恢复快照损坏",
                        message=str(exc),
                        log_message=f"自动恢复快照损坏，已忽略：{exc}",
                    )
                ],
            )
        return WorkflowResult(success=True, value=self._session_state_from_project(snapshot.project))

    def clear_snapshot(self) -> WorkflowResult[None]:
        try:
            self._snapshot_repository.clear_snapshot()
        except Exception as exc:
            return WorkflowResult(
                success=False,
                notifications=[
                    UserNotification(
                        level="warning",
                        title="自动恢复快照清理失败",
                        message=str(exc),
                        log_message=f"自动恢复快照清理失败：{exc}",
                    )
                ],
            )
        return WorkflowResult(success=True)

    def _safe_clear_snapshot(self) -> None:
        try:
            self._snapshot_repository.clear_snapshot()
        except Exception:
            pass

    def _session_state_from_project(self, project: AudioProject) -> ProjectSessionState:
        selected_event_id = next(iter(project.events), None)
        selected_event_ids = [selected_event_id] if selected_event_id else []
        selected_audio_id = project.events[selected_event_id].audio_id if selected_event_id in project.events else None
        if selected_event_id is not None:
            selected_folder_id = project.find_event_folder_id(selected_event_id)
        else:
            selected_folder_id = next(iter(project.root_folder_ids), None)
        return ProjectSessionState(
            project=project,
            selected_event_id=selected_event_id,
            selected_event_ids=selected_event_ids,
            selected_folder_id=selected_folder_id,
            selected_audio_id=selected_audio_id,
        )