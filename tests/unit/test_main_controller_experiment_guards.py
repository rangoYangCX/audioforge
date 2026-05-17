from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from audioforge.app.adapters.workbench_adapters import SerializerProjectRepository
from audioforge.app.application.contracts import ChoiceRequest, ConfirmationRequest, FileDialogRequest, UserNotification
from audioforge.app.controllers.experiment_controller import (
    ExperimentController,
    ExperimentVariantActivationResult,
    ExperimentVariantExportResult,
    ExperimentVariantPreviewResult,
)
from audioforge.app.controllers.main_controller import MainController
from audioforge.app.models.audio_project import AudioProject, EventModel, new_id
from audioforge.app.services.experiment_exporter import ExperimentDeltaResult
from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.project_serializer import ProjectSerializer


class _DummyPanel:
    def __init__(self) -> None:
        self.preview: list[dict[str, object]] = []
        self.export_history: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, object]] = []
        self.enabled = False

    def set_preview(self, preview: list[dict[str, object]]) -> None:
        self.preview = preview

    def refresh_tasks(
        self,
        tasks: list[dict[str, object]],
        active_task_index: int = -1,
        active_variant_index: int = -1,
        dirty_task_index: int = -1,
        dirty_variant_index: int = -1,
    ) -> None:
        self.refresh_calls.append({
            "tasks": tasks,
            "active": (active_task_index, active_variant_index),
            "dirty": (dirty_task_index, dirty_variant_index),
        })

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def set_export_history(self, entries: list[dict[str, object]]) -> None:
        self.export_history = list(entries)


class _DummySwitcher:
    def __init__(self) -> None:
        self.workspace_active = False
        self.entries: list[tuple[int, int, str]] = []
        self.active: tuple[int, int] | None = None
        self.dirty = False

    def set_workspace_active(self, active: bool) -> None:
        self.workspace_active = active

    def set_entries(self, entries: list[tuple[int, int, str]]) -> None:
        self.entries = entries

    def set_active(self, task_index: int, variant_index: int) -> None:
        self.active = (task_index, variant_index)

    def set_variant_dirty(self, is_dirty: bool) -> None:
        self.dirty = is_dirty


class _DummyWindow:
    def __init__(self) -> None:
        self.experiment_panel = _DummyPanel()
        self.experiment_switcher = _DummySwitcher()
        self.logs: list[str] = []

    def append_log(self, message: str) -> None:
        self.logs.append(message)

    def present_notification(self, notification: UserNotification) -> None:
        if notification.level == "warning":
            QMessageBox.warning(self, notification.title, notification.message)
            return
        if notification.level == "error":
            QMessageBox.critical(self, notification.title, notification.message)
            return
        QMessageBox.information(self, notification.title, notification.message)

    def confirm_request(self, request: ConfirmationRequest) -> bool:
        result = QMessageBox.question(
            self,
            request.title,
            request.message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes if request.default_accept else QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def execute_choice_request(self, request: ChoiceRequest) -> str | None:
        buttons = {option.value: option for option in request.options}
        result = QMessageBox.question(
            self,
            request.title,
            request.message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            for option in request.options:
                if not option.is_cancel:
                    return option.value
        cancel_option = next((option for option in request.options if option.is_cancel), None)
        return cancel_option.value if cancel_option is not None else None

    def execute_file_dialog_request(self, request: FileDialogRequest) -> str:
        return ""


class _MockProjectOpener:
    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_project(self, path: str) -> None:
        self.opened_paths.append(path)


def _make_base_project() -> AudioProject:
    project = AudioProject(name="base")
    event_id = new_id("event")
    project.events[event_id] = EventModel(id=event_id, display_name="E1")
    return project


def _build_controller(tmp_path: Path) -> MainController:
    controller = MainController.__new__(MainController)
    controller.serializer = ProjectSerializer()
    controller.project_repository = SerializerProjectRepository(controller.serializer)
    controller.exporter = RuntimeExporter()
    controller.window = _DummyWindow()
    controller._clear_recovery_snapshot = lambda: None
    controller._refresh_experiment_ux_context = lambda: None
    controller._current_loaded_task_id = None
    controller._current_loaded_variant_id = None
    controller._current_loaded_variant_path = None
    controller.is_dirty = False

    base_path = tmp_path / "base.afproj"
    ProjectSerializer().save(_make_base_project(), base_path)

    opener = _MockProjectOpener()
    controller.experiment_controller = ExperimentController(project_opener=opener)
    ws_path = tmp_path / "experiment.afws"
    controller.experiment_controller.create_workspace(str(ws_path), str(base_path), name="实验")
    controller.experiment_controller.create_task("任务1")
    controller._mock_project_opener = opener
    return controller


def _prepare_dirty_variant(controller: MainController, volume_db: float = -6.0) -> Path:
    variant_path = Path(controller.experiment_controller.get_variant_project_path(0, 0) or "")
    controller.project = ProjectSerializer().load(variant_path)
    event = next(iter(controller.project.events.values()))
    event.volume_db = volume_db
    controller.is_dirty = True
    return variant_path


def test_duplicate_variant_saves_current_variant_before_copy(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    _prepare_dirty_variant(controller, -6.0)

    controller._on_experiment_duplicate_variant_requested(0, 0, "副本方案")

    duplicate_path = Path(controller.experiment_controller.get_variant_project_path(0, 1) or "")
    duplicate_project = ProjectSerializer().load(duplicate_path)
    duplicate_event = next(iter(duplicate_project.events.values()))

    assert duplicate_event.volume_db == -6.0
    assert controller.is_dirty is False


def test_close_workspace_saves_current_variant_before_close(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    variant_path = _prepare_dirty_variant(controller, -9.0)

    controller._on_experiment_workspace_close_requested()

    saved_project = ProjectSerializer().load(variant_path)
    saved_event = next(iter(saved_project.events.values()))

    assert saved_event.volume_db == -9.0
    assert controller.experiment_controller.workspace is None
    assert any("已自动保存方案工程" in message for message in controller.window.logs)


def test_export_delta_saves_current_variant_before_loading_variant_copy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    controller = _build_controller(tmp_path)
    controller.experiment_controller.create_variant(0, "方案B")
    variant_path = Path(controller.experiment_controller.get_variant_project_path(0, 1) or "")
    controller.project = ProjectSerializer().load(variant_path)
    next(iter(controller.project.events.values())).volume_db = -12.0
    controller.project.file_path = str(variant_path)
    controller.is_dirty = True
    controller._on_experiment_variant_project_loaded(str(variant_path))
    captured: dict[str, float] = {}

    monkeypatch.setattr(
        controller.experiment_controller,
        "preview_variant_delta",
        lambda task_index, variant_index, *, exporter, serializer: ExperimentVariantPreviewResult(
            preview=[{"EventName": "E1", "Op": "modify", "DiffFields": ["VolumeDb"]}],
            task_id="task",
            variant_id="variant",
            base_project_path=tmp_path / "base.afproj",
            variant_project_path=tmp_path / "variant.afproj",
        ),
    )

    def _fake_export_variant_delta(task_index, variant_index, *, exporter, serializer):
        variant_path = Path(controller.experiment_controller.get_variant_project_path(task_index, variant_index) or "")
        variant_project = ProjectSerializer().load(variant_path)
        captured["volume_db"] = next(iter(variant_project.events.values())).volume_db
        return ExperimentVariantExportResult(
            delta_result=ExperimentDeltaResult(
                delta_file=variant_path,
                assets_dir=variant_path.parent,
                report={},
            ),
            preview=[{"EventName": "E1", "Op": "modify"}],
            export_root=variant_path.parent,
            task_id="task",
            variant_id="variant",
        )

    monkeypatch.setattr(controller.experiment_controller, "export_variant_delta", _fake_export_variant_delta)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    controller._export_experiment_delta(0, 1)

    assert captured["volume_db"] == -12.0
    assert controller.window.experiment_panel.preview == [{"EventName": "E1", "Op": "modify"}]
    assert len(controller.window.experiment_panel.export_history) == 1
    assert "任务1 / 方案B" in controller.window.experiment_panel.export_history[0]["label"]


def test_export_delta_cancelled_by_confirmation_skips_export(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    controller.experiment_controller.create_variant(0, "方案B")

    monkeypatch.setattr(
        controller.experiment_controller,
        "preview_variant_delta",
        lambda task_index, variant_index, *, exporter, serializer: ExperimentVariantPreviewResult(
            preview=[{"EventName": "E1", "Op": "modify", "DiffFields": ["VolumeDb"]}],
            task_id="task",
            variant_id="variant",
            base_project_path=tmp_path / "base.afproj",
            variant_project_path=tmp_path / "variant.afproj",
        ),
    )
    export_called = {"value": False}

    def _should_not_export(*args, **kwargs):
        export_called["value"] = True
        raise AssertionError("export_variant_delta 不应在取消确认后执行")

    monkeypatch.setattr(controller.experiment_controller, "export_variant_delta", _should_not_export)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)

    controller._export_experiment_delta(0, 1)

    assert export_called["value"] is False
    assert controller.window.experiment_panel.preview == [{"EventName": "E1", "Op": "modify", "DiffFields": ["VolumeDb"]}]
    assert any("已取消实验增量导出" in message for message in controller.window.logs)


def test_workspace_refresh_marks_dirty_variant(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    variant_path = _prepare_dirty_variant(controller, -5.0)
    controller._on_experiment_variant_project_loaded(str(variant_path))

    controller._on_experiment_workspace_changed(controller.experiment_controller.workspace)

    assert controller.window.experiment_switcher.dirty is True
    assert controller.window.experiment_panel.refresh_calls[-1]["dirty"] == (0, 0)


def test_save_failure_can_discard_changes_and_continue(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    _prepare_dirty_variant(controller, -3.0)

    monkeypatch.setattr(controller.serializer, "save", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    controller._on_experiment_workspace_close_requested()

    assert controller.is_dirty is False
    assert controller.experiment_controller.workspace is None
    assert any("已放弃未保存修改并继续关闭工作区" in message for message in controller.window.logs)


def test_activate_variant_failure_shows_warning(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    warning_messages: list[str] = []

    monkeypatch.setattr(
        controller.experiment_controller,
        "activate_variant",
        lambda task_index, variant_index: ExperimentVariantActivationResult(
            success=False,
            error="找不到方案工程副本：missing.afproj",
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warning_messages.append(message),
    )

    controller._on_experiment_variant_activate_requested(0, 0)

    assert warning_messages == ["找不到方案工程副本：missing.afproj"]


def test_variant_project_loaded_updates_context(tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    variant_path = Path(controller.experiment_controller.get_variant_project_path(0, 0) or "")

    controller._on_experiment_variant_project_loaded(str(variant_path))

    assert controller._current_loaded_task_id == controller.experiment_controller.workspace.tasks[0].id
    assert controller._current_loaded_variant_id == controller.experiment_controller.workspace.tasks[0].variants[0].id
    assert controller._current_loaded_variant_path == str(variant_path)


def test_sync_from_base_creates_backup_and_logs(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    controller.experiment_controller.create_variant(0, "方案B")
    backup_path = tmp_path / "variant.afproj.bak"
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        controller.experiment_controller,
        "sync_variant_from_base",
        lambda task_index, variant_index: backup_path,
    )

    controller._on_experiment_sync_from_base_requested(0, 1)

    assert any(str(backup_path) in message for message in controller.window.logs)


def test_sync_from_base_reloads_current_loaded_variant(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    controller.experiment_controller.create_variant(0, "方案B")
    controller.experiment_controller.set_active_variant(0, 1)
    variant_path = Path(controller.experiment_controller.get_variant_project_path(0, 1) or "")
    original_activate_variant = controller.experiment_controller.activate_variant

    def _activate_and_reload(task_index: int, variant_index: int):
        result = original_activate_variant(task_index, variant_index)
        if result.success:
            controller.project = ProjectSerializer().load(variant_path)
            controller.project.file_path = str(variant_path)
        return result

    monkeypatch.setattr(controller.experiment_controller, "activate_variant", _activate_and_reload)
    controller.project = ProjectSerializer().load(variant_path)
    event = next(iter(controller.project.events.values()))
    event.volume_db = -8.0
    controller.project.file_path = str(variant_path)
    controller.is_dirty = True
    controller._on_experiment_variant_project_loaded(str(variant_path))

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    controller._on_experiment_sync_from_base_requested(0, 1)

    reloaded_event = next(iter(controller.project.events.values()))
    assert controller.project.file_path == str(variant_path)
    assert reloaded_event.volume_db == 0.0
    assert controller.is_dirty is False


def test_compare_delta_updates_preview_and_logs(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    controller.experiment_controller.create_variant(0, "方案B")
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        controller.experiment_controller,
        "preview_variant_delta",
        lambda task_index, variant_index, *, exporter, serializer: ExperimentVariantPreviewResult(
            preview=[{"EventName": "E1", "Op": "modify"}],
            task_id="task",
            variant_id="variant",
            base_project_path=tmp_path / "base.afproj",
            variant_project_path=tmp_path / "variant.afproj",
        ),
    )

    controller._compare_experiment_delta(0, 1)

    assert controller.window.experiment_panel.preview == [{"EventName": "E1", "Op": "modify"}]
    assert any("差异预览" in message for message in controller.window.logs)


def test_create_task_failure_is_reported_to_user(monkeypatch, tmp_path: Path) -> None:
    controller = _build_controller(tmp_path)
    warning_messages: list[str] = []

    monkeypatch.setattr(
        controller.experiment_controller,
        "create_task",
        lambda name: (_ for _ in ()).throw(IsADirectoryError("选择的底板路径不是工程文件: /tmp/demo")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warning_messages.append(message),
    )

    controller._experiment_integration().on_create_task_requested("任务1")

    assert warning_messages == ["选择的底板路径不是工程文件: /tmp/demo"]
    assert any("新建任务失败" in message for message in controller.window.logs)