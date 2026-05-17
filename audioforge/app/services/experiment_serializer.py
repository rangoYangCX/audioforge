"""AB 实验工作区序列化器。

负责 .afws 文件的读写、方案副本的创建与管理。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from audioforge.app.models.experiment_workspace import (
    WORKSPACE_SCHEMA_VERSION,
    ExperimentLifecycle,
    ExperimentTask,
    ExperimentVariant,
    ExperimentWorkspace,
    new_task_id,
    new_variant_id,
)
from audioforge.app.services.project_serializer import ProjectSerializer

logger = logging.getLogger(__name__)

VARIANTS_DIRNAME = "variants"


class ExperimentWorkspaceSerializer:
    """实验工作区 .afws 文件的读写与方案副本管理。"""

    # ── 保存 / 加载 ──────────────────────────────

    @staticmethod
    def save(workspace: ExperimentWorkspace, path: Path | None = None) -> None:
        """保存 .afws 文件。"""
        target = Path(path) if path else Path(workspace.file_path)
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        workspace.touch()
        payload = json.dumps(workspace.to_dict(), ensure_ascii=False, indent=2)
        temp_path = target.with_suffix(".tmp")
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(target)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        workspace.file_path = str(target)
        logger.info("Workspace saved: %s", target)

    @staticmethod
    def load(path: Path) -> ExperimentWorkspace:
        """加载 .afws 文件。"""
        path = path.resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        workspace = ExperimentWorkspace.from_dict(payload)
        workspace.file_path = str(path)
        logger.info("Workspace loaded: %s", path)
        return workspace

    # ── 创建工作区 ────────────────────────────────

    @staticmethod
    def create(
        workspace_path: Path,
        base_project_path: Path,
        name: str,
        source_audio_root: str = "",
    ) -> ExperimentWorkspace:
        """创建新的实验工作区。

        Args:
            workspace_path: .afws 输出路径。
            base_project_path: 底板 .afproj 文件路径。
            name: 工作区名称。
            source_audio_root: 共享源音频根目录（相对于 workspace 目录）。
        """
        workspace_path = workspace_path.resolve()
        base_project_path = base_project_path.resolve()

        # 底板文件必须存在
        if not base_project_path.exists():
            raise FileNotFoundError(f"底板工程不存在: {base_project_path}")
        if not base_project_path.is_file():
            raise IsADirectoryError(f"选择的底板路径不是工程文件: {base_project_path}")

        # 计算底板相对路径
        base_relative = _relative_path(base_project_path, workspace_path.parent)

        # 计算源音频根相对路径
        source_relative = source_audio_root

        workspace = ExperimentWorkspace(
            name=name,
            base_project_path=base_relative,
            source_audio_root=source_relative,
        )

        # 创建 variants 子目录
        variants_dir = workspace_path.parent / VARIANTS_DIRNAME
        variants_dir.mkdir(parents=True, exist_ok=True)

        ExperimentWorkspaceSerializer.save(workspace, workspace_path)
        logger.info("Workspace created: %s (base: %s)", workspace_path, base_relative)
        return workspace

    # ── 任务 & 方案管理 ───────────────────────────

    @staticmethod
    def create_task(
        workspace: ExperimentWorkspace,
        name: str,
        variant_name: str = "default",
    ) -> ExperimentTask:
        """在工作区中新增一个实验任务（自动附带一个默认方案）。"""
        workspace_dir = workspace.workspace_dir
        task_id = new_task_id()
        variant = ExperimentWorkspaceSerializer._create_variant(
            workspace_dir=workspace_dir,
            base_project_path=ExperimentWorkspaceSerializer._resolve_workspace_base_project_path(workspace),
            task_id=task_id,
            variant_name=variant_name,
        )
        task = ExperimentTask(
            id=task_id,
            name=name,
            variants=[variant],
            active_variant_index=0,
        )
        workspace.tasks.append(task)
        workspace.touch()
        logger.info("Task created: %s (%s)", task_id, name)
        return task

    @staticmethod
    def create_variant(
        workspace: ExperimentWorkspace,
        task_index: int,
        variant_name: str,
    ) -> ExperimentVariant:
        """为指定任务新增一个方案（基于底板副本）。"""
        workspace_dir = workspace.workspace_dir
        task = workspace.tasks[task_index]
        variant = ExperimentWorkspaceSerializer._create_variant(
            workspace_dir=workspace_dir,
            base_project_path=ExperimentWorkspaceSerializer._resolve_task_baseline_project_path(workspace, task),
            task_id=task.id,
            variant_name=variant_name,
        )
        task.variants.append(variant)
        task.touch()
        workspace.touch()
        logger.info("Variant created: %s (%s) in task %s", variant.id, variant_name, task.id)
        return variant

    @staticmethod
    def duplicate_variant(
        workspace: ExperimentWorkspace,
        task_index: int,
        variant_index: int,
        new_name: str,
    ) -> ExperimentVariant:
        """复制一个已有方案作为新方案。"""
        workspace_dir = workspace.workspace_dir
        task = workspace.tasks[task_index]
        source_variant = task.variants[variant_index]

        new_variant_id_str = new_variant_id()
        variant_dir = workspace_dir / VARIANTS_DIRNAME / task.id
        new_copy_path = variant_dir / f"{new_variant_id_str}.afproj"

        # 复制源方案的 .afproj
        source_copy_path = workspace.resolve_variant_copy_path(source_variant)
        if source_copy_path.exists():
            ProjectSerializer.copy_project_bundle(source_copy_path, new_copy_path)
        else:
            # 回退到从任务基线复制
            base_path = ExperimentWorkspaceSerializer._resolve_task_baseline_project_path(workspace, task)
            ProjectSerializer.copy_project_bundle(base_path, new_copy_path)

        new_copy_relative = _relative_path(new_copy_path, workspace_dir)
        new_variant = ExperimentVariant(
            id=new_variant_id_str,
            name=new_name,
            lifecycle=ExperimentLifecycle.DRAFT,
            base_project_copy_path=new_copy_relative,
        )
        task.variants.append(new_variant)
        task.touch()
        workspace.touch()
        logger.info("Variant duplicated: %s → %s", source_variant.id, new_variant_id_str)
        return new_variant

    @staticmethod
    def delete_task(workspace: ExperimentWorkspace, task_index: int) -> None:
        """删除一个实验任务及其所有方案副本文件。"""
        workspace_dir = workspace.workspace_dir
        task = workspace.tasks[task_index]
        task_dir = workspace_dir / VARIANTS_DIRNAME / task.id
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)
        workspace.tasks.pop(task_index)
        if workspace.active_task_index >= len(workspace.tasks):
            workspace.active_task_index = max(0, len(workspace.tasks) - 1)
        workspace.touch()
        logger.info("Task deleted: %s", task.id)

    @staticmethod
    def delete_variant(workspace: ExperimentWorkspace, task_index: int, variant_index: int) -> None:
        """删除指定方案及其副本文件。"""
        workspace_dir = workspace.workspace_dir
        task = workspace.tasks[task_index]
        variant = task.variants[variant_index]

        # 删除副本文件
        copy_path = workspace.resolve_variant_copy_path(variant)
        if copy_path.exists():
            copy_path.unlink(missing_ok=True)

        task.variants.pop(variant_index)
        if task.active_variant_index >= len(task.variants):
            task.active_variant_index = max(0, len(task.variants) - 1)
        task.touch()
        workspace.touch()
        logger.info("Variant deleted: %s", variant.id)

    # ── 底板同步 ──────────────────────────────────

    @staticmethod
    def sync_variant_from_base(
        workspace: ExperimentWorkspace,
        task_index: int,
        variant_index: int,
    ) -> Path | None:
        """将底板 .afproj 覆盖到指定方案的副本。

        警告：此操作会丢失方案中已有的所有修改！
        """
        task = workspace.tasks[task_index]
        variant = task.variants[variant_index]
        baseline_variant = task.baseline_variant
        if baseline_variant is not None and baseline_variant.id == variant.id:
            raise ValueError("default 基线为只读版本，不能执行同步。")

        base_path = ExperimentWorkspaceSerializer._resolve_task_baseline_project_path(workspace, task)
        copy_path = workspace.resolve_variant_copy_path(variant)

        backup_path: Path | None = None
        if copy_path.exists():
            backup_path = copy_path.with_name(f"{copy_path.stem}.bak{copy_path.suffix}")
            ProjectSerializer.copy_project_bundle(copy_path, backup_path)

        ProjectSerializer.copy_project_bundle(base_path, copy_path)
        variant.lifecycle = ExperimentLifecycle.DRAFT
        variant.touch()
        task.touch()
        workspace.touch()
        logger.info("Variant synced from base: %s", variant.id)
        return backup_path

    # ── 内部工具 ──────────────────────────────────

    @staticmethod
    def _create_variant(
        workspace_dir: Path,
        base_project_path: Path,
        task_id: str,
        variant_name: str,
    ) -> ExperimentVariant:
        """创建一个新方案（复制底板到 variants/<task_id>/<variant_id>.afproj）。"""
        variant_id = new_variant_id()
        variant_dir = workspace_dir / VARIANTS_DIRNAME / task_id
        variant_dir.mkdir(parents=True, exist_ok=True)
        copy_path = variant_dir / f"{variant_id}.afproj"

        if not base_project_path.exists():
            raise FileNotFoundError(f"底板工程不存在: {base_project_path}")
        if not base_project_path.is_file():
            raise IsADirectoryError(f"选择的底板路径不是工程文件: {base_project_path}")
        ProjectSerializer.copy_project_bundle(base_project_path, copy_path)

        copy_relative = _relative_path(copy_path, workspace_dir)
        return ExperimentVariant(
            id=variant_id,
            name=variant_name,
            lifecycle=ExperimentLifecycle.DRAFT,
            base_project_copy_path=copy_relative,
        )

    @staticmethod
    def _resolve_task_baseline_project_path(workspace: ExperimentWorkspace, task: ExperimentTask) -> Path:
        baseline_variant = task.baseline_variant
        if baseline_variant is not None:
            baseline_path = workspace.resolve_variant_copy_path(baseline_variant)
            if baseline_path.exists() and baseline_path.is_file():
                return baseline_path
        return ExperimentWorkspaceSerializer._resolve_workspace_base_project_path(workspace)

    @staticmethod
    def _resolve_workspace_base_project_path(workspace: ExperimentWorkspace) -> Path:
        base_path_text = workspace.base_project_path.strip()
        base_path = workspace.base_project_abs_path

        if base_path_text and base_path.exists() and base_path.is_file():
            return base_path

        inferred_path = ExperimentWorkspaceSerializer._infer_workspace_base_project_path(workspace)
        if inferred_path is not None:
            workspace.base_project_path = _relative_path(inferred_path, workspace.workspace_dir)
            workspace.touch()
            logger.warning("Workspace base project path repaired: %s -> %s", base_path_text or "<empty>", inferred_path)
            return inferred_path

        if base_path_text:
            if base_path.exists() and not base_path.is_file():
                raise IsADirectoryError(f"选择的底板路径不是工程文件: {base_path}")
            raise FileNotFoundError(f"底板工程不存在: {base_path}")

        raise FileNotFoundError(
            f"实验工作区缺少底板工程路径，且无法在 {workspace.workspace_dir} 自动推断唯一 .afproj 文件。"
        )

    @staticmethod
    def _infer_workspace_base_project_path(workspace: ExperimentWorkspace) -> Path | None:
        candidates = sorted(path for path in workspace.workspace_dir.glob("*.afproj") if path.is_file())
        if len(candidates) == 1:
            return candidates[0].resolve()
        return None


# ── 路径工具函数 ──────────────────────────────────


def _relative_path(target: Path, base: Path) -> str:
    """计算 target 相对于 base 的相对路径字符串。"""
    try:
        return str(target.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(target)


def _resolve_relative(base_dir: Path, relative_path: str) -> Path:
    """将相对路径解析为绝对路径。如果已是绝对路径则直接返回。"""
    p = Path(relative_path)
    if p.is_absolute():
        return p
    return (base_dir / p).resolve()
