from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from audioforge.app.application.project_lifecycle_controller import ProjectLifecycleController
from audioforge.app.models.audio_project import AudioProject, ClipModel, EventModel


@dataclass
class _FakeSettingsStore:
    values: dict[str, object]

    def get_value(self, key: str, default=None):
        return self.values.get(key, default)

    def set_value(self, key: str, value: object) -> None:
        self.values[key] = value


class _FakeProjectRepository:
    def __init__(self, project: AudioProject | None = None) -> None:
        self.project = project
        self.saved_path: str | None = None
        self.existing_paths: set[str] = set()
        self.file_paths: set[str] = set()

    def exists(self, file_path: str) -> bool:
        return file_path in self.existing_paths

    def is_file(self, file_path: str) -> bool:
        return file_path in self.file_paths

    def load(self, file_path: str) -> AudioProject:
        if self.project is None:
            raise FileNotFoundError(file_path)
        loaded = copy.deepcopy(self.project)
        loaded.file_path = file_path
        return loaded

    def save(self, project: AudioProject, file_path: str) -> str:
        self.saved_path = file_path
        project.file_path = file_path
        return file_path

    def resolve_save_path(self, file_path: str | None, suggested_name: str) -> str | None:
        if not file_path:
            return None
        return file_path if file_path.endswith(".afproj") else f"{file_path}.afproj"


def _make_project() -> AudioProject:
    project = AudioProject.create_empty(name="LifecycleSample")
    root_folder_id = project.root_folder_ids[0]
    clip = ClipModel.from_path(Path("/tmp/ui_click.wav"), "ui/click")
    event = EventModel(id="UiClick", display_name="UI Click", clips=[clip])
    project.add_event(root_folder_id, event)
    return project


def test_open_project_returns_session_state_and_updates_recent_projects() -> None:
    repository = _FakeProjectRepository(_make_project())
    repository.existing_paths.add("/tmp/sample.afproj")
    repository.file_paths.add("/tmp/sample.afproj")
    settings = _FakeSettingsStore({})
    controller = ProjectLifecycleController(repository, settings)

    result = controller.open_project("/tmp/sample.afproj")

    assert result.success is True
    assert result.value is not None
    assert result.value.session_state is not None
    assert result.value.session_state.selected_event_id == "UiClick"
    assert result.value.recent_projects == ["/tmp/sample.afproj"]


def test_save_project_returns_cancelled_when_no_path_available() -> None:
    repository = _FakeProjectRepository(_make_project())
    settings = _FakeSettingsStore({})
    controller = ProjectLifecycleController(repository, settings)

    result = controller.save_project(_make_project(), None, "LifecycleSample.afproj")

    assert result.success is False
    assert result.cancelled is True


def test_restore_ui_preferences_prefers_json_blob() -> None:
    settings = _FakeSettingsStore(
        {
            "uiPreferencesJson": '{"ui_scale": 1.2, "active_editor_tab": 1}',
            "uiScale": 0.9,
        }
    )
    controller = ProjectLifecycleController(_FakeProjectRepository(_make_project()), settings)

    preferences = controller.restore_ui_preferences(
        {
            "ui_scale": 1.0,
            "workspace_splitter_sizes": [1, 2],
            "main_splitter_sizes": [3, 4],
            "active_editor_tab": 0,
            "inspector_splitter_sizes": [5, 6],
            "content_top_splitter_sizes": [7, 8],
            "active_contents_tab": 0,
            "event_import_template": {},
        }
    )

    assert preferences["ui_scale"] == 1.2
    assert preferences["active_editor_tab"] == 1