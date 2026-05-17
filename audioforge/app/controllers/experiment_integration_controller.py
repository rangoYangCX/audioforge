from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from audioforge.app.application.contracts import ChoiceOption, ChoiceRequest, ConfirmationRequest, FileDialogRequest, UserNotification
from audioforge.app.services.experiment_exporter import ExperimentExporter

if TYPE_CHECKING:
    from audioforge.app.controllers.experiment_controller import ExperimentController
    from audioforge.app.controllers.main_controller import MainController


class ExperimentIntegrationHost(Protocol):
    window: Any
    project_repository: Any
    exporter: Any
    project: Any
    is_dirty: bool
    experiment_controller: ExperimentController
    _current_loaded_task_id: str | None
    _current_loaded_variant_id: str | None
    _current_loaded_variant_path: str | None

    def _clear_recovery_snapshot(self) -> None: ...


class ExperimentIntegrationController:
    """MainController 的 experiment 集成协调层。"""

    def __init__(self, host: ExperimentIntegrationHost) -> None:
        self._host = host
        self._export_history: list[dict[str, object]] = []

    def bind_signals(self) -> None:
        if not hasattr(self._host.window, "experiment_panel"):
            return
        panel = self._host.window.experiment_panel
        switcher = self._host.window.experiment_switcher
        controller = self._host.experiment_controller

        panel.createTaskRequested.connect(self.on_create_task_requested)
        panel.deleteTaskRequested.connect(controller.delete_task)
        panel.createVariantRequested.connect(self.on_create_variant_requested)
        panel.deleteVariantRequested.connect(self.on_delete_variant_requested)
        panel.activateVariantRequested.connect(self.on_variant_activate_requested)
        panel.duplicateVariantRequested.connect(self.on_duplicate_variant_requested)
        panel.syncFromBaseRequested.connect(self.on_sync_from_base_requested)
        panel.exportDeltaRequested.connect(self.export_delta)
        panel.compareRequested.connect(self.compare_delta)
        panel.lifecycleChangeRequested.connect(self.on_lifecycle_change_requested)

        switcher.workspaceOpenRequested.connect(self.on_workspace_open_requested)
        switcher.workspaceCloseRequested.connect(self.on_workspace_close_requested)
        switcher.taskVariantChanged.connect(self.on_variant_switch_requested)

        controller.workspaceChanged.connect(self.on_workspace_changed)
        controller.variantProjectLoaded.connect(self.on_variant_project_loaded)
        controller.workspaceClosed.connect(self.on_workspace_closed)

    def on_workspace_open_requested(self) -> None:
        controller = self._host.experiment_controller
        choice = self._host.window.execute_choice_request(
            ChoiceRequest(
                title="实验工作区",
                message="请选择操作：",
                informative_text="「新建」创建新的实验工作区\n「打开」打开已有的工作区",
                options=[
                    ChoiceOption(value="create", label="新建工作区"),
                    ChoiceOption(value="open", label="打开工作区"),
                    ChoiceOption(value="cancel", label="取消", is_cancel=True),
                ],
            )
        )

        if not choice or choice == "cancel":
            return

        if choice == "create":
            ws_path = self._host.window.execute_file_dialog_request(
                FileDialogRequest(
                    mode="save_file",
                    title="新建实验工作区",
                    file_filter="AudioForge 工作区 (*.afws)",
                )
            )
            if not ws_path:
                return
            if not ws_path.endswith(".afws"):
                ws_path += ".afws"
            base_path = self._host.window.execute_file_dialog_request(
                FileDialogRequest(
                    mode="open_file",
                    title="选择底板工程",
                    file_filter="AudioForge 工程 (*.afproj)",
                )
            )
            if not base_path:
                return
            try:
                self._host.window._activate_workspace_mode("experiment")
                controller.create_workspace(ws_path, base_path)
            except Exception as exc:
                self.notify_warning("打开工作区失败", str(exc))
            return

        path = self._host.window.execute_file_dialog_request(
            FileDialogRequest(
                mode="open_file",
                title="打开实验工作区",
                file_filter="AudioForge 工作区 (*.afws)",
            )
        )
        if not path:
            return
        try:
            self._host.window._activate_workspace_mode("experiment")
            controller.open_workspace(path)
        except Exception as exc:
            self.notify_warning("打开工作区失败", str(exc))

    def save_current_variant_project(self, *, action_name: str = "继续操作") -> bool:
        workspace = self._host.experiment_controller.workspace
        if workspace is None or not self._host.is_dirty or not self._host.project.file_path:
            return True

        try:
            save_path = self._host.project_repository.save(self._host.project, self._host.project.file_path)
            self._host.is_dirty = False
            self._host._clear_recovery_snapshot()
            self._host.window.append_log(f"已自动保存方案工程：{save_path}")
            return True
        except Exception as exc:
            confirmed = self._host.window.confirm_request(
                ConfirmationRequest(
                    title="保存方案工程失败",
                    message=f"自动保存当前方案失败，是否放弃未保存修改并继续{action_name}？\n\n{exc}",
                    default_accept=False,
                )
            )
            if not confirmed:
                return False
            self._host.is_dirty = False
            self._host._clear_recovery_snapshot()
            self._host.window.append_log(f"自动保存方案失败，已放弃未保存修改并继续{action_name}：{exc}")
            return True

    def run_action_with_saved_variant(self, action_name: str, action: Callable[[], object]) -> object | None:
        if not self.save_current_variant_project(action_name=action_name):
            return None
        return action()

    def activate_variant(self, task_index: int, variant_index: int) -> bool:
        result = self._host.experiment_controller.activate_variant(task_index, variant_index)
        if result.success:
            return True
        self.notify_warning("切换方案失败", result.error or "无法加载所选方案。")
        return False

    def reset_loaded_variant_context(self) -> None:
        self._host._current_loaded_task_id = None
        self._host._current_loaded_variant_id = None
        self._host._current_loaded_variant_path = None

    def current_dirty_indices(self) -> tuple[int, int] | None:
        workspace = self._host.experiment_controller.workspace
        if workspace is None or not self._host.is_dirty:
            return None
        if not self._host._current_loaded_task_id or not self._host._current_loaded_variant_id:
            return None
        if self._host.project.file_path and self._host._current_loaded_variant_path:
            project_path = self._host.project.file_path
            loaded_path = self._host._current_loaded_variant_path
            if project_path != loaded_path:
                return None
        for task_index, task in enumerate(workspace.tasks):
            if task.id != self._host._current_loaded_task_id:
                continue
            for variant_index, variant in enumerate(task.variants):
                if variant.id == self._host._current_loaded_variant_id:
                    return task_index, variant_index
        return None

    def current_loaded_indices(self) -> tuple[int, int] | None:
        workspace = self._host.experiment_controller.workspace
        if workspace is None or not self._host._current_loaded_task_id or not self._host._current_loaded_variant_id:
            return None
        for task_index, task in enumerate(workspace.tasks):
            if task.id != self._host._current_loaded_task_id:
                continue
            for variant_index, variant in enumerate(task.variants):
                if variant.id == self._host._current_loaded_variant_id:
                    return task_index, variant_index
        return None

    def is_read_only_variant(self, task_index: int, variant_index: int) -> bool:
        return self._host.experiment_controller.is_baseline_variant(task_index, variant_index)

    def variant_label(self, task_index: int, variant_index: int) -> str:
        workspace = self._host.experiment_controller.workspace
        if workspace is None:
            return "实验方案"
        if task_index < 0 or task_index >= len(workspace.tasks):
            return "实验方案"
        task = workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return task.name
        return f"{task.name} / {task.variants[variant_index].name}"

    def notify_warning(self, title: str, message: str) -> None:
        self._host.window.append_log(f"{title}：{message}")
        self._host.window.present_notification(UserNotification(level="warning", title=title, message=message))

    def notify_info(self, title: str, message: str, *, log_message: str | None = None) -> None:
        self._host.window.append_log(log_message or message)
        self._host.window.present_notification(UserNotification(level="info", title=title, message=message))

    def on_create_task_requested(self, name: str) -> None:
        try:
            self._host.experiment_controller.create_task(name)
        except Exception as exc:
            self.notify_warning("新建任务失败", str(exc))

    def on_create_variant_requested(self, task_index: int, variant_name: str) -> None:
        try:
            self._host.experiment_controller.create_variant(task_index, variant_name)
        except Exception as exc:
            self.notify_warning("新建方案失败", str(exc))

    def refresh_ui(self, workspace) -> None:
        if not hasattr(self._host.window, "experiment_panel") or not hasattr(self._host.window, "experiment_switcher"):
            return
        panel = self._host.window.experiment_panel
        switcher = self._host.window.experiment_switcher

        if workspace is None:
            self.reset_loaded_variant_context()
            switcher.set_workspace_active(False)
            switcher.set_variant_dirty(False)
            if hasattr(panel, "set_context_summary"):
                panel.set_context_summary(base_label="", active_label="")
            if hasattr(panel, "set_export_history"):
                panel.set_export_history([])
            panel.set_enabled(False)
            panel.refresh_tasks([])
            panel.set_preview([])
            return

        switcher.set_workspace_active(True)
        entries = []
        for task_i, task in enumerate(workspace.tasks):
            for variant_i, variant in enumerate(task.variants):
                entries.append((task_i, variant_i, f"{task.name} / {variant.name}"))
        switcher.set_entries(entries)

        active_task = workspace.active_task
        active_variant_index = active_task.active_variant_index if active_task else 0
        switcher.set_active(workspace.active_task_index, active_variant_index)

        tasks_data = []
        for task_i, task in enumerate(workspace.tasks):
            tasks_data.append({
                "name": task.name,
                "id": task.id,
                "variants": [
                    {
                        "name": v.name,
                        "id": v.id,
                        "lifecycle": v.lifecycle.value,
                        "readonly": self.is_read_only_variant(task_i, variant_i),
                    }
                    for variant_i, v in enumerate(task.variants)
                ],
            })

        dirty_indices = self.current_dirty_indices()
        panel.refresh_tasks(
            tasks_data,
            active_task_index=workspace.active_task_index,
            active_variant_index=workspace.active_task.active_variant_index if workspace.active_task else -1,
            dirty_task_index=dirty_indices[0] if dirty_indices else -1,
            dirty_variant_index=dirty_indices[1] if dirty_indices else -1,
        )
        if hasattr(panel, "set_context_summary"):
            active_label = self.variant_label(workspace.active_task_index, active_variant_index)
            if self.is_read_only_variant(workspace.active_task_index, active_variant_index):
                active_label = f"{active_label}（只读基线）"
            panel.set_context_summary(
                base_label=workspace.base_project_abs_path.name,
                active_label=active_label,
            )
        if hasattr(panel, "set_export_history"):
            panel.set_export_history(self._export_history)
        panel.set_enabled(True)
        switcher.set_variant_dirty(dirty_indices is not None)

    def on_variant_switch_requested(self, task_index: int, variant_index: int) -> None:
        self.run_action_with_saved_variant(
            "切换方案",
            lambda: self.activate_variant(task_index, variant_index),
        )

    def on_lifecycle_change_requested(self, task_index: int, variant_index: int, lifecycle_str: str) -> None:
        from audioforge.app.models.experiment_workspace import ExperimentLifecycle

        if self.is_read_only_variant(task_index, variant_index):
            self.notify_info("只读基线", "default 基线为只读版本，不支持修改生命周期。")
            return

        try:
            lifecycle_enum = ExperimentLifecycle(lifecycle_str)
        except ValueError:
            return
        self._host.experiment_controller.set_variant_lifecycle(task_index, variant_index, lifecycle_enum)

    def on_variant_activate_requested(self, task_index: int, variant_index: int) -> None:
        if variant_index < 0:
            return
        self.run_action_with_saved_variant(
            "切换方案",
            lambda: self.activate_variant(task_index, variant_index),
        )

    def on_delete_variant_requested(self, task_index: int, variant_index: int) -> None:
        if variant_index < 0:
            return
        if self.is_read_only_variant(task_index, variant_index):
            self.notify_info("只读基线", "default 基线为只读版本，不能删除。")
            return
        self.run_action_with_saved_variant(
            "删除方案",
            lambda: self._host.experiment_controller.delete_variant(task_index, variant_index),
        )

    def on_duplicate_variant_requested(self, task_index: int, variant_index: int, new_name: str) -> None:
        if variant_index < 0:
            return
        self.run_action_with_saved_variant(
            "复制方案",
            lambda: self._host.experiment_controller.duplicate_variant(task_index, variant_index, new_name),
        )

    def on_sync_from_base_requested(self, task_index: int, variant_index: int) -> None:
        if variant_index < 0:
            return
        if self.is_read_only_variant(task_index, variant_index):
            self.notify_info("只读基线", "default 基线为只读版本，不需要执行同步。")
            return

        def _sync_from_base() -> None:
            label = self.variant_label(task_index, variant_index)
            try:
                backup_path = self._host.experiment_controller.sync_variant_from_base(task_index, variant_index)
            except (FileNotFoundError, ValueError) as exc:
                self.notify_warning("同步底板失败", str(exc))
                return
            if self.current_loaded_indices() == (task_index, variant_index):
                if not self.activate_variant(task_index, variant_index):
                    return
            if backup_path is not None:
                self._host.window.append_log(f"已备份被覆盖的方案副本：{backup_path}")
            backup_hint = f"\n备份文件：{backup_path}" if backup_path is not None else ""
            self.notify_info(
                "同步完成",
                f"已将 {label} 同步到任务基线最新内容。{backup_hint}",
                log_message=f"已同步实验方案：{label}" + (f"；备份：{backup_path}" if backup_path is not None else ""),
            )

        self.run_action_with_saved_variant("同步底板", _sync_from_base)

    def on_workspace_close_requested(self) -> None:
        self.run_action_with_saved_variant(
            "关闭工作区",
            self._host.experiment_controller.close_workspace,
        )

    def on_variant_project_loaded(self, project_path: str) -> None:
        workspace = self._host.experiment_controller.workspace
        if workspace is None:
            self.reset_loaded_variant_context()
            return
        active_task = workspace.active_task
        active_variant = workspace.active_variant
        self._host._current_loaded_task_id = active_task.id if active_task else None
        self._host._current_loaded_variant_id = active_variant.id if active_variant else None
        self._host._current_loaded_variant_path = project_path
        if active_task is not None and active_variant is not None:
            self._host.window.append_log(f"已加载实验方案工程：{active_task.name} / {active_variant.name}")

    def on_workspace_changed(self, workspace) -> None:
        self.refresh_ui(workspace)

    def on_workspace_closed(self) -> None:
        self.refresh_ui(None)

    def compare_delta(self, task_index: int, variant_index: int) -> None:
        if self.is_read_only_variant(task_index, variant_index):
            self.notify_info("只读基线", "default 基线用于承载对比基准，不需要再生成差异预览。")
            return

        def _compare() -> None:
            exporter = ExperimentExporter.create_default(runtime_exporter=self._host.exporter)
            try:
                preview_data = self._host.experiment_controller.preview_variant_delta(
                    task_index,
                    variant_index,
                    exporter=exporter,
                    serializer=self._host.project_repository,
                )
            except Exception as exc:
                self.notify_warning("对比失败", str(exc))
                return

            if hasattr(self._host.window, "experiment_panel"):
                self._host.window.experiment_panel.set_preview(preview_data.preview)

            label = self.variant_label(task_index, variant_index)
            self.notify_info(
                "对比完成",
                f"已生成 {label} 相对任务基线的差异预览，共 {len(preview_data.preview)} 项。",
                log_message=f"已生成实验方案差异预览：{label}，差异项 {len(preview_data.preview)} 个。",
            )

        self.run_action_with_saved_variant("对比差异", _compare)

    def export_delta(self, task_index: int, variant_index: int) -> None:
        if self.is_read_only_variant(task_index, variant_index):
            self.notify_info("只读基线", "default 基线用于承载对比基准，不支持导出增量。")
            return

        def _export() -> None:
            exporter = ExperimentExporter.create_default(runtime_exporter=self._host.exporter)
            try:
                preview_data = self._host.experiment_controller.preview_variant_delta(
                    task_index,
                    variant_index,
                    exporter=exporter,
                    serializer=self._host.project_repository,
                )
            except Exception as exc:
                self.notify_warning("导出失败", f"增量预览失败:\n{exc}")
                return

            if hasattr(self._host.window, "experiment_panel"):
                self._host.window.experiment_panel.set_preview(preview_data.preview)

            added_count = sum(1 for entry in preview_data.preview if entry.get("Op") == "add")
            modified_count = sum(1 for entry in preview_data.preview if entry.get("Op") == "modify")
            deleted_count = sum(1 for entry in preview_data.preview if entry.get("Op") == "delete")
            preview_lines: list[str] = []
            op_labels = {"add": "新增", "modify": "修改", "delete": "删除"}
            for entry in preview_data.preview[:5]:
                diff_fields = entry.get("DiffFields") or []
                diff_suffix = f"（{'、'.join(diff_fields[:4])}）" if diff_fields else ""
                preview_lines.append(f"- {op_labels.get(entry.get('Op', ''), '变更')} {entry.get('EventName', '-')}{diff_suffix}")
            preview_summary = "\n".join(preview_lines) if preview_lines else "- 当前没有检测到差异，导出将生成空增量。"

            label = self.variant_label(task_index, variant_index)
            confirm_message = (
                f"即将导出 {label} 相对任务基线的增量。\n\n"
                f"差异汇总：新增 {added_count} / 修改 {modified_count} / 删除 {deleted_count}\n\n"
                f"主要变更：\n{preview_summary}\n\n是否继续导出？"
            )
            confirmed = self._host.window.confirm_request(
                ConfirmationRequest(
                    title="导出前确认",
                    message=confirm_message,
                    default_accept=False,
                )
            )
            if not confirmed:
                self._host.window.append_log(f"已取消实验增量导出：{label}")
                return

            try:
                export_data = self._host.experiment_controller.export_variant_delta(
                    task_index,
                    variant_index,
                    exporter=exporter,
                    serializer=self._host.project_repository,
                )
            except Exception as exc:
                self.notify_warning("导出失败", f"增量导出失败:\n{exc}")
                return

            if hasattr(self._host.window, "experiment_panel"):
                self._host.window.experiment_panel.set_preview(export_data.preview)

            report = export_data.delta_result.report
            summary = (
                f"新增 {report.get('AddedEvents', 0)} / 修改 {report.get('ModifiedEvents', 0)} / "
                f"删除 {report.get('DeletedEvents', 0)}"
            )
            self._export_history.insert(
                0,
                {
                    "label": f"{label} | {summary} | {export_data.export_root}",
                    "path": str(export_data.export_root),
                },
            )
            self._export_history = self._export_history[:10]
            if hasattr(self._host.window.experiment_panel, "set_export_history"):
                self._host.window.experiment_panel.set_export_history(self._export_history)
            if hasattr(self._host.window, "set_experiment_export_history"):
                self._host.window.set_experiment_export_history(self._export_history)
            self.notify_info(
                "导出完成",
                f"已导出 {label} 的增量结果。\n输出目录：{export_data.export_root}\n{summary}",
                log_message=f"已导出实验增量：{label} -> {export_data.export_root}（{summary}）",
            )

        self.run_action_with_saved_variant("导出增量", _export)