from __future__ import annotations

import json
from dataclasses import dataclass

from audioforge.app.application.contracts import ProjectSessionState, UserNotification, WorkflowResult
from audioforge.app.application.ports import ProjectRepository, SettingsStore
from audioforge.app.models.audio_project import AudioProject


@dataclass(slots=True)
class ProjectOpenPayload:
    session_state: ProjectSessionState | None
    project_path: str | None
    recent_projects: list[str]


@dataclass(slots=True)
class ProjectSavePayload:
    save_path: str | None
    recent_projects: list[str]


class ProjectLifecycleController:
    def __init__(self, project_repository: ProjectRepository, settings_store: SettingsStore) -> None:
        self._project_repository = project_repository
        self._settings_store = settings_store

    def create_new_project(self) -> ProjectSessionState:
        project = AudioProject.create_empty()
        selected_folder_id = project.root_folder_ids[0] if project.root_folder_ids else None
        return ProjectSessionState(
            project=project,
            selected_event_id=None,
            selected_event_ids=[],
            selected_folder_id=selected_folder_id,
            selected_audio_id=None,
        )

    def open_project(self, file_path: str) -> WorkflowResult[ProjectOpenPayload]:
        normalized_path = str(file_path).strip()
        recent_projects = self.recent_projects()
        if not self._project_repository.exists(normalized_path):
            recent_projects = self.remove_recent_project(normalized_path)
            return WorkflowResult(
                success=False,
                value=ProjectOpenPayload(session_state=None, project_path=None, recent_projects=recent_projects),
                notifications=[
                    UserNotification(
                        level="warning",
                        title="打开工程失败",
                        message=f"找不到工程文件：{normalized_path}",
                    )
                ],
            )
        if not self._project_repository.is_file(normalized_path):
            return WorkflowResult(
                success=False,
                value=ProjectOpenPayload(session_state=None, project_path=None, recent_projects=recent_projects),
                notifications=[
                    UserNotification(
                        level="warning",
                        title="打开工程失败",
                        message=f"选择的路径不是工程文件：{normalized_path}",
                    )
                ],
            )

        try:
            project = self._project_repository.load(normalized_path)
        except Exception as exc:
            return WorkflowResult(
                success=False,
                value=ProjectOpenPayload(session_state=None, project_path=None, recent_projects=recent_projects),
                notifications=[UserNotification(level="error", title="打开工程失败", message=str(exc))],
            )

        session_state = self._session_state_for_loaded_project(project)
        recent_projects = self.remember_recent_project(normalized_path)
        return WorkflowResult(
            success=True,
            value=ProjectOpenPayload(session_state=session_state, project_path=normalized_path, recent_projects=recent_projects),
        )

    def save_project(
        self,
        project: AudioProject,
        file_path: str | None,
        suggested_name: str,
    ) -> WorkflowResult[ProjectSavePayload]:
        save_path = self._project_repository.resolve_save_path(file_path, suggested_name)
        recent_projects = self.recent_projects()
        if save_path is None:
            return WorkflowResult(
                success=False,
                value=ProjectSavePayload(save_path=None, recent_projects=recent_projects),
                cancelled=True,
            )
        try:
            persisted_path = self._project_repository.save(project, save_path)
        except Exception as exc:
            return WorkflowResult(
                success=False,
                value=ProjectSavePayload(save_path=save_path, recent_projects=recent_projects),
                notifications=[
                    UserNotification(level="error", title="保存工程失败", message=str(exc))
                ],
            )
        recent_projects = self.remember_recent_project(persisted_path)
        return WorkflowResult(
            success=True,
            value=ProjectSavePayload(save_path=persisted_path, recent_projects=recent_projects),
        )

    def recent_projects(self) -> list[str]:
        value = self._settings_store.get_value("recentProjects", [])
        if isinstance(value, str):
            return [value] if value else []
        return [str(item) for item in value or []]

    def remember_recent_project(self, file_path: str) -> list[str]:
        recent = [item for item in self.recent_projects() if item != file_path]
        recent.insert(0, file_path)
        self._settings_store.set_value("recentProjects", recent[:10])
        return recent[:10]

    def remove_recent_project(self, file_path: str) -> list[str]:
        recent = [item for item in self.recent_projects() if item != file_path]
        self._settings_store.set_value("recentProjects", recent)
        return recent

    def restore_ui_preferences(self, default_preferences: dict[str, object]) -> dict[str, object]:
        preferences = dict(default_preferences)
        stored_preferences = self._settings_store.get_value("uiPreferencesJson", "")
        if isinstance(stored_preferences, str) and stored_preferences.strip():
            try:
                parsed_preferences = json.loads(stored_preferences)
            except json.JSONDecodeError:
                parsed_preferences = None
            if isinstance(parsed_preferences, dict):
                preferences.update(parsed_preferences)
                return preferences

        preferences.update(
            {
                "ui_scale": self._settings_store.get_value("uiScale", default_preferences["ui_scale"]),
                "workspace_splitter_sizes": self._settings_store.get_value(
                    "workspaceSplitterSizes",
                    default_preferences["workspace_splitter_sizes"],
                ),
                "main_splitter_sizes": self._settings_store.get_value(
                    "mainSplitterSizes",
                    default_preferences["main_splitter_sizes"],
                ),
                "active_editor_tab": self._settings_store.get_value(
                    "activeEditorTab",
                    default_preferences["active_editor_tab"],
                ),
                "inspector_splitter_sizes": self._settings_store.get_value(
                    "inspectorSplitterSizes",
                    default_preferences["inspector_splitter_sizes"],
                ),
                "content_top_splitter_sizes": self._settings_store.get_value(
                    "contentTopSplitterSizes",
                    default_preferences["content_top_splitter_sizes"],
                ),
                "active_contents_tab": self._settings_store.get_value(
                    "activeContentsTab",
                    default_preferences["active_contents_tab"],
                ),
                "event_import_template": self._settings_store.get_value(
                    "eventImportTemplate",
                    default_preferences["event_import_template"],
                ),
            }
        )
        return preferences

    def save_ui_preferences(self, preferences: dict[str, object]) -> None:
        self._settings_store.set_value("uiPreferencesJson", json.dumps(preferences, ensure_ascii=False))
        self._settings_store.set_value("uiScale", preferences["ui_scale"])
        self._settings_store.set_value("workspaceSplitterSizes", preferences["workspace_splitter_sizes"])
        self._settings_store.set_value("mainSplitterSizes", preferences["main_splitter_sizes"])
        self._settings_store.set_value("activeEditorTab", preferences["active_editor_tab"])
        self._settings_store.set_value("inspectorSplitterSizes", preferences["inspector_splitter_sizes"])
        self._settings_store.set_value("contentTopSplitterSizes", preferences["content_top_splitter_sizes"])
        self._settings_store.set_value("activeContentsTab", preferences["active_contents_tab"])
        self._settings_store.set_value("eventImportTemplate", preferences["event_import_template"])

    def _session_state_for_loaded_project(self, project: AudioProject) -> ProjectSessionState:
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