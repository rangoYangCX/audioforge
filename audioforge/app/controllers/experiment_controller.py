"""AB 实验工作区控制器。

管理实验工作区的状态、任务/方案切换，与 MainController 协作
加载方案的 .afproj 副本。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from PySide6.QtCore import QObject, Signal

from audioforge.app.adapters import SerializerExperimentWorkspaceRepository, SerializerProjectRepository
from audioforge.app.application.ports import ExperimentWorkspaceRepository, ProjectRepository
from audioforge.app.models.experiment_workspace import (
    ExperimentLifecycle,
    ExperimentTask,
    ExperimentVariant,
    ExperimentWorkspace,
)
from audioforge.app.services.experiment_exporter import ExperimentDeltaResult, ExperimentExporter
from audioforge.app.services.project_serializer import ProjectSerializer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExperimentVariantActivationResult:
    success: bool
    project_path: str | None = None
    error: str = ""
    task_id: str | None = None
    variant_id: str | None = None


@dataclass(slots=True)
class ExperimentVariantExportResult:
    delta_result: ExperimentDeltaResult
    preview: list[dict[str, Any]]
    export_root: Path
    task_id: str
    variant_id: str


@dataclass(slots=True)
class ExperimentVariantPreviewResult:
    preview: list[dict[str, Any]]
    task_id: str
    variant_id: str
    base_project_path: Path
    variant_project_path: Path


@runtime_checkable
class ProjectOpener(Protocol):
    """协议：打开工程文件。

    ExperimentController 只依赖此协议而非 MainController 本体，
    消除 C→C 的强耦合。
    """

    def open_project(self, path: str) -> None: ...


class ExperimentController(QObject):
    """管理 AB 实验工作区的业务逻辑。

    通过 MainController 间接操作 AudioProject 的加载/保存，
    本身只管理工作区级别的问题（任务、方案切换、导出协调）。
    """

    # ── 信号 ──────────────────────────────────────

    workspaceChanged = Signal(object)  # ExperimentWorkspace | None
    activeTaskChanged = Signal(object)  # ExperimentTask | None
    activeVariantChanged = Signal(object)  # ExperimentVariant | None
    variantProjectLoaded = Signal(str)  # 加载的 .afproj 路径
    workspaceClosed = Signal()
    exportCompleted = Signal(str)  # 导出报告摘要

    def __init__(
        self,
        project_opener: ProjectOpener,
        parent: QObject | None = None,
        *,
        workspace_repository: ExperimentWorkspaceRepository | None = None,
        project_repository: ProjectRepository | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_opener = project_opener
        self._workspace: ExperimentWorkspace | None = None
        self._workspace_repository = workspace_repository or SerializerExperimentWorkspaceRepository()
        self._project_repository = project_repository or SerializerProjectRepository()

    # ── 属性 ──────────────────────────────────────

    @property
    def workspace(self) -> ExperimentWorkspace | None:
        return self._workspace

    @property
    def is_open(self) -> bool:
        return self._workspace is not None

    # ── 工作区生命周期 ────────────────────────────

    def create_workspace(self, workspace_path: str, base_project_path: str, name: str = "") -> None:
        """创建新工作区并打开。"""
        ws_path = Path(workspace_path)
        base_path = Path(base_project_path)
        ws_name = name or ws_path.stem

        self._workspace = self._workspace_repository.create(
            workspace_path=str(ws_path),
            base_project_path=str(base_path),
            name=ws_name,
        )
        logger.info("Workspace created and opened: %s", ws_path)
        self._emit_workspace_signals()

    def open_workspace(self, path: str) -> None:
        """打开已有工作区。"""
        self._workspace = self._workspace_repository.load(path)
        logger.info("Workspace opened: %s", path)
        self._emit_workspace_signals()

    def close_workspace(self) -> None:
        """关闭当前工作区。"""
        self._workspace = None
        self.workspaceClosed.emit()
        self._emit_workspace_signals()
        logger.info("Workspace closed")

    def save_workspace(self) -> None:
        """保存当前工作区。"""
        if self._workspace is None:
            return
        self._workspace_repository.save(self._workspace)
        logger.info("Workspace saved: %s", self._workspace.file_path)

    # ── 任务管理 ──────────────────────────────────

    def create_task(self, name: str, variant_name: str = "default") -> ExperimentTask | None:
        """创建实验任务。"""
        if self._workspace is None:
            return None
        task = self._workspace_repository.create_task(self._workspace, name, variant_name)
        self.save_workspace()
        self._emit_workspace_signals()
        return task

    def delete_task(self, task_index: int) -> None:
        """删除实验任务。"""
        if self._workspace is None:
            return
        self._workspace_repository.delete_task(self._workspace, task_index)
        self.save_workspace()
        self._emit_workspace_signals()

    def set_active_task(self, task_index: int) -> None:
        """切换当前活跃任务。"""
        if self._workspace is None:
            return
        if 0 <= task_index < len(self._workspace.tasks):
            self._workspace.active_task_index = task_index
            self._workspace.touch()
            self.save_workspace()
            self._emit_workspace_signals()

    # ── 方案管理 ──────────────────────────────────

    def create_variant(self, task_index: int, variant_name: str) -> ExperimentVariant | None:
        """为指定任务创建新方案。"""
        if self._workspace is None:
            return None
        variant = self._workspace_repository.create_variant(self._workspace, task_index, variant_name)
        self.save_workspace()
        self._emit_workspace_signals()
        return variant

    def duplicate_variant(self, task_index: int, variant_index: int, new_name: str) -> ExperimentVariant | None:
        """复制方案。"""
        if self._workspace is None:
            return None
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return None
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return None
        variant = self._workspace_repository.duplicate_variant(self._workspace, task_index, variant_index, new_name)
        self.save_workspace()
        self._emit_workspace_signals()
        return variant

    def delete_variant(self, task_index: int, variant_index: int) -> None:
        """删除方案。"""
        if self._workspace is None:
            return
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return
        self._workspace_repository.delete_variant(self._workspace, task_index, variant_index)
        self.save_workspace()
        self._emit_workspace_signals()

    def is_baseline_variant(self, task_index: int, variant_index: int) -> bool:
        if self._workspace is None:
            return False
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return False
        task = self._workspace.tasks[task_index]
        baseline_variant = task.baseline_variant
        if baseline_variant is None or variant_index < 0 or variant_index >= len(task.variants):
            return False
        return task.variants[variant_index].id == baseline_variant.id

    def get_task_baseline_project_path(self, task_index: int) -> str | None:
        if self._workspace is None:
            return None
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return None
        task = self._workspace.tasks[task_index]
        baseline_variant = task.baseline_variant
        if baseline_variant is not None:
            baseline_path = self._workspace.resolve_variant_copy_path(baseline_variant)
            if baseline_path.exists():
                return str(baseline_path)
        return str(self._workspace.base_project_abs_path)

    def set_active_variant(self, task_index: int, variant_index: int) -> None:
        """切换当前活跃方案。"""
        if self._workspace is None:
            return
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return
        task = self._workspace.tasks[task_index]
        if 0 <= variant_index < len(task.variants):
            task.active_variant_index = variant_index
            task.touch()
            self._workspace.touch()
            self.save_workspace()
            self._emit_workspace_signals()

    def activate_variant(self, task_index: int, variant_index: int) -> ExperimentVariantActivationResult:
        """激活方案 → 加载该方案的 .afproj 副本到编辑器。"""
        if self._workspace is None:
            return ExperimentVariantActivationResult(success=False, error="当前未打开实验工作区。")
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return ExperimentVariantActivationResult(success=False, error=f"任务索引越界: {task_index}")
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return ExperimentVariantActivationResult(success=False, error=f"方案索引越界: {variant_index}")
        variant = task.variants[variant_index]

        copy_path = self._workspace.resolve_variant_copy_path(variant)

        if not copy_path.exists():
            logger.error("Variant project copy not found: %s", copy_path)
            return ExperimentVariantActivationResult(
                success=False,
                error=f"找不到方案工程副本：{copy_path}",
                task_id=task.id,
                variant_id=variant.id,
            )

        self.set_active_variant(task_index, variant_index)
        self._project_opener.open_project(str(copy_path))
        self.variantProjectLoaded.emit(str(copy_path))
        logger.info("Variant activated: %s (%s)", variant.id, variant.name)
        return ExperimentVariantActivationResult(
            success=True,
            project_path=str(copy_path),
            task_id=task.id,
            variant_id=variant.id,
        )

    # ── 生命周期 ──────────────────────────────────

    def set_task_lifecycle(self, task_index: int, lifecycle: ExperimentLifecycle) -> None:
        """修改任务状态。"""
        if self._workspace is None:
            return
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return
        task = self._workspace.tasks[task_index]
        for variant in task.variants:
            variant.lifecycle = lifecycle
            variant.touch()
        task.touch()
        self.save_workspace()
        self._emit_workspace_signals()

    def set_variant_lifecycle(
        self, task_index: int, variant_index: int, lifecycle: ExperimentLifecycle
    ) -> None:
        """修改方案状态。"""
        if self._workspace is None:
            return
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return
        variant = task.variants[variant_index]
        variant.lifecycle = lifecycle
        variant.touch()
        task.touch()
        self.save_workspace()
        self._emit_workspace_signals()

    # ── 底板同步 ──────────────────────────────────

    def sync_variant_from_base(self, task_index: int, variant_index: int) -> Path | None:
        """从底板同步到方案。"""
        if self._workspace is None:
            return None
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return None
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return None
        backup_path = self._workspace_repository.sync_variant_from_base(self._workspace, task_index, variant_index)
        self.save_workspace()
        self._emit_workspace_signals()
        return Path(backup_path) if backup_path is not None else None

    def export_variant_delta(
        self,
        task_index: int,
        variant_index: int,
        exporter: ExperimentExporter,
        serializer: ProjectSerializer | ProjectRepository | None = None,
    ) -> ExperimentVariantExportResult:
        """执行指定方案的增量导出并返回结果与预览。"""
        if self._workspace is None:
            raise RuntimeError("当前未打开实验工作区。")
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            raise IndexError(f"任务索引越界: {task_index}")

        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            raise IndexError(f"方案索引越界: {variant_index}")

        project_repository = self._resolve_project_repository(serializer)
        variant = task.variants[variant_index]
        baseline_path_text = self.get_task_baseline_project_path(task_index)
        base_path = Path(baseline_path_text) if baseline_path_text else self._workspace.base_project_abs_path
        variant_path = self._workspace.resolve_variant_copy_path(variant)

        if not base_path.exists():
            raise FileNotFoundError(f"底板工程不存在：{base_path}")
        if not variant_path.exists():
            raise FileNotFoundError(f"方案工程副本不存在：{variant_path}")

        base_project = project_repository.load(str(base_path))
        variant_project = project_repository.load(str(variant_path))
        export_root = self._workspace.workspace_dir / "Export" / f"{task.id}_{variant.id}"
        delta_result = exporter.export_delta(
            base_project=base_project,
            variant_project=variant_project,
            task=task,
            variant=variant,
            export_root=export_root,
        )
        preview = exporter.compute_deltas_preview(base_project, variant_project)
        self.exportCompleted.emit(
            f"task={task.id} variant={variant.id} added={delta_result.added_count} "
            f"modified={delta_result.modified_count} deleted={delta_result.deleted_count}"
        )
        return ExperimentVariantExportResult(
            delta_result=delta_result,
            preview=preview,
            export_root=export_root,
            task_id=task.id,
            variant_id=variant.id,
        )

    def preview_variant_delta(
        self,
        task_index: int,
        variant_index: int,
        exporter: ExperimentExporter,
        serializer: ProjectSerializer | ProjectRepository | None = None,
    ) -> ExperimentVariantPreviewResult:
        """计算指定方案相对底板的差异预览，不导出文件。"""
        if self._workspace is None:
            raise RuntimeError("当前未打开实验工作区。")
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            raise IndexError(f"任务索引越界: {task_index}")

        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            raise IndexError(f"方案索引越界: {variant_index}")

        project_repository = self._resolve_project_repository(serializer)
        variant = task.variants[variant_index]
        baseline_path_text = self.get_task_baseline_project_path(task_index)
        base_path = Path(baseline_path_text) if baseline_path_text else self._workspace.base_project_abs_path
        variant_path = self._workspace.resolve_variant_copy_path(variant)

        if not base_path.exists():
            raise FileNotFoundError(f"底板工程不存在：{base_path}")
        if not variant_path.exists():
            raise FileNotFoundError(f"方案工程副本不存在：{variant_path}")

        base_project = project_repository.load(str(base_path))
        variant_project = project_repository.load(str(variant_path))
        preview = exporter.compute_deltas_preview(base_project, variant_project)
        return ExperimentVariantPreviewResult(
            preview=preview,
            task_id=task.id,
            variant_id=variant.id,
            base_project_path=base_path,
            variant_project_path=variant_path,
        )

    def _resolve_project_repository(self, serializer: ProjectSerializer | ProjectRepository | None) -> ProjectRepository:
        if serializer is None:
            return self._project_repository
        if isinstance(serializer, ProjectSerializer):
            return SerializerProjectRepository(serializer)
        return serializer

    # ── 内部工具 ──────────────────────────────────

    def _emit_workspace_signals(self) -> None:
        self.workspaceChanged.emit(self._workspace)
        self.activeTaskChanged.emit(self._workspace.active_task if self._workspace else None)
        self.activeVariantChanged.emit(self._workspace.active_variant if self._workspace else None)

    def get_variant_project_path(self, task_index: int, variant_index: int) -> str | None:
        """获取指定方案的 .afproj 副本绝对路径。"""
        if self._workspace is None:
            return None
        if task_index < 0 or task_index >= len(self._workspace.tasks):
            return None
        task = self._workspace.tasks[task_index]
        if variant_index < 0 or variant_index >= len(task.variants):
            return None
        variant = task.variants[variant_index]
        return str(self._workspace.resolve_variant_copy_path(variant))

    def get_base_project_path(self) -> str | None:
        """获取底板工程的绝对路径。"""
        if self._workspace is None:
            return None
        return str(self._workspace.base_project_abs_path)
