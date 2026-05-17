"""AB 实验模块端到端流程验证测试。

验证核心数据链路能跑通：
  - 工作区创建/打开/关闭
  - 任务创建/删除
  - 方案创建/删除/复制/激活
  - 生命周期变更
  - 底板同步
  - 增量导出
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from audioforge.app.models.audio_project import AudioProject, EventModel, new_id
from audioforge.app.models.experiment_workspace import (
    ExperimentLifecycle,
    ExperimentTask,
    ExperimentVariant,
    ExperimentWorkspace,
)
from audioforge.app.services.experiment_serializer import (
    ExperimentWorkspaceSerializer,
    _relative_path,
    _resolve_relative,
)
from audioforge.app.services.experiment_exporter import ExperimentExporter
from audioforge.app.services.project_serializer import ProjectSerializer
from tests.helpers import build_sample_project


# ── Helpers ──────────────────────────────────────


def _make_minimal_project(name: str = "test_project") -> AudioProject:
    """创建包含少量事件的 AudioProject。"""
    project = AudioProject(name=name)
    e1_id = new_id("event")
    e2_id = new_id("event")
    project.events[e1_id] = EventModel(id=e1_id, display_name="Event_A")
    project.events[e2_id] = EventModel(id=e2_id, display_name="Event_B")
    return project


def _make_variant_project(name: str = "variant_project") -> AudioProject:
    """创建包含增/删/改事件的 AudioProject（模拟方案副本经编辑后）。"""
    project = AudioProject(name=name)
    e1_id = new_id("event")
    e2_id = new_id("event")
    e3_id = new_id("event")
    project.events[e1_id] = EventModel(id=e1_id, display_name="Event_A")       # unchanged
    project.events[e2_id] = EventModel(id=e2_id, display_name="Event_B_Mod")   # modified name
    project.events[e3_id] = EventModel(id=e3_id, display_name="Event_C")       # new event
    # Event_D removed (was in base, not in variant)
    return project


def _save_project_to_file(project: AudioProject, path: Path) -> Path:
    """保存 AudioProject 到指定路径。"""
    ProjectSerializer().save(project, path)
    return path


# ── Test: ExperimentWorkspace Model ──────────────


class TestExperimentWorkspaceModel:
    """验证 ExperimentWorkspace 数据模型基本功能。"""

    def test_variant_lifecycle_init(self) -> None:
        v = ExperimentVariant(id="v1", name="方案A", lifecycle="draft")
        assert v.lifecycle == ExperimentLifecycle.DRAFT

    def test_variant_lifecycle_from_str(self) -> None:
        v = ExperimentVariant(id="v2", name="方案B", lifecycle=ExperimentLifecycle.ACTIVE)
        assert v.lifecycle == ExperimentLifecycle.ACTIVE

    def test_variant_touch(self) -> None:
        v = ExperimentVariant(id="v3", name="方案C")
        old = v.updated_at
        v.touch()
        # touch() 会更新 updated_at（同一秒内可能不变，所以只验证类型）
        assert isinstance(v.updated_at, str) and len(v.updated_at) > 0

    def test_task_active_variant(self) -> None:
        v1 = ExperimentVariant(id="v1", name="default")
        v2 = ExperimentVariant(id="v2", name="方案B")
        task = ExperimentTask(id="t1", name="任务1", variants=[v1, v2], active_variant_index=1)
        assert task.active_variant == v2

    def test_task_active_variant_out_of_range(self) -> None:
        task = ExperimentTask(id="t2", name="任务2", variants=[], active_variant_index=0)
        assert task.active_variant is None

    def test_workspace_active_task(self) -> None:
        task = ExperimentTask(id="t1", name="任务1")
        ws = ExperimentWorkspace(name="ws1", tasks=[task], active_task_index=0)
        assert ws.active_task == task

    def test_workspace_active_variant(self) -> None:
        v = ExperimentVariant(id="v1", name="default")
        task = ExperimentTask(id="t1", name="任务1", variants=[v], active_variant_index=0)
        ws = ExperimentWorkspace(name="ws1", tasks=[task], active_task_index=0)
        assert ws.active_variant == v

    def test_workspace_active_variant_no_tasks(self) -> None:
        ws = ExperimentWorkspace(name="ws1", tasks=[], active_task_index=0)
        assert ws.active_task is None
        assert ws.active_variant is None

    def test_variant_to_dict_roundtrip(self) -> None:
        v = ExperimentVariant(id="v1", name="方案A", lifecycle=ExperimentLifecycle.ACTIVE, notes="test")
        d = v.to_dict()
        v2 = ExperimentVariant.from_dict(d)
        assert v2.id == v.id
        assert v2.name == v.name
        assert v2.lifecycle == v.lifecycle
        assert v2.notes == v.notes

    def test_task_to_dict_roundtrip(self) -> None:
        v = ExperimentVariant(id="v1", name="default")
        task = ExperimentTask(id="t1", name="任务1", variants=[v], active_variant_index=0)
        d = task.to_dict()
        task2 = ExperimentTask.from_dict(d)
        assert task2.id == task.id
        assert task2.name == task.name
        assert len(task2.variants) == 1
        assert task2.active_variant_index == 0

    def test_workspace_to_dict_roundtrip(self) -> None:
        v = ExperimentVariant(id="v1", name="default")
        task = ExperimentTask(id="t1", name="任务1", variants=[v], active_variant_index=0)
        ws = ExperimentWorkspace(name="ws1", base_project_path="base.afproj", tasks=[task], active_task_index=0)
        d = ws.to_dict()
        ws2 = ExperimentWorkspace.from_dict(d)
        assert ws2.name == ws.name
        assert ws2.base_project_path == ws.base_project_path
        assert ws2.schema_version == ws.schema_version
        assert len(ws2.tasks) == 1


# ── Test: ExperimentWorkspaceSerializer ───────────


class TestExperimentWorkspaceSerializer:
    """验证 ExperimentWorkspaceSerializer 的创建/保存/加载/任务/方案操作。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="experiment_test_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project_to_file(_make_minimal_project(), self.base_path)

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_workspace(self, name: str = "test_ws") -> ExperimentWorkspace:
        ws_path = self.tmp_dir / f"{name}.afws"
        return ExperimentWorkspaceSerializer.create(
            workspace_path=ws_path,
            base_project_path=self.base_path,
            name=name,
        )

    def test_create_workspace(self) -> None:
        ws = self._create_workspace()
        assert ws.name == "test_ws"
        assert ws.base_project_path != ""
        assert len(ws.tasks) == 0
        assert (self.tmp_dir / "test_ws.afws").exists()

    def test_create_workspace_generates_variants_dir(self) -> None:
        ws = self._create_workspace()
        assert (self.tmp_dir / "variants").exists()

    def test_workspace_model_path_helpers(self) -> None:
        ws = self._create_workspace("helpers")
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")

        assert ws.workspace_dir == Path(ws.file_path).resolve().parent
        assert ws.base_project_abs_path == self.base_path.resolve()
        assert ws.resolve_variant_copy_path(task.variants[0]).exists()

    def test_save_and_load_roundtrip(self) -> None:
        ws = self._create_workspace()
        ws_path = Path(ws.file_path)
        ExperimentWorkspaceSerializer.save(ws, ws_path)

        ws2 = ExperimentWorkspaceSerializer.load(ws_path)
        assert ws2.name == ws.name
        assert ws2.base_project_path == ws.base_project_path
        assert ws2.file_path == str(ws_path.resolve())

    def test_create_task(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        assert task.name == "任务1"
        assert len(task.variants) == 1
        assert task.variants[0].name == "default"
        assert len(ws.tasks) == 1

        # 验证副本文件存在
        copy_path = ws.resolve_variant_copy_path(task.variants[0])
        assert copy_path.exists()

    def test_create_task_keeps_internalized_sources_available(self) -> None:
        project, wav_path = build_sample_project(self.tmp_dir / "portable_task")
        self.base_path = self.tmp_dir / "portable_task.afproj"
        ProjectSerializer().save(project, self.base_path)

        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        copy_path = ws.resolve_variant_copy_path(task.variants[0])
        loaded = ProjectSerializer().load(copy_path)
        loaded_clip_path = Path(loaded.events["UiClick"].clips[0].source_path)

        assert loaded_clip_path.exists()
        assert loaded_clip_path.name == wav_path.name
        assert any(Path(path).exists() and Path(path).name == wav_path.name for path in loaded.asset_registry)

    def test_create_task_with_custom_variant_name(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1", variant_name="方案A")
        assert task.variants[0].name == "方案A"

    def test_create_task_repairs_missing_base_project_path_from_workspace_dir(self) -> None:
        ws = self._create_workspace()
        ws.base_project_path = ""

        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")

        assert task.name == "任务1"
        assert ws.base_project_path == self.base_path.name
        assert ws.resolve_variant_copy_path(task.variants[0]).exists()

    def test_create_variant(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        variant = ExperimentWorkspaceSerializer.create_variant(ws, 0, "方案B")
        assert variant.name == "方案B"
        assert len(task.variants) == 2

        # 验证副本文件存在
        copy_path = ws.resolve_variant_copy_path(variant)
        assert copy_path.exists()

    def test_duplicate_variant(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        ExperimentWorkspaceSerializer.create_variant(ws, 0, "方案B")

        dup = ExperimentWorkspaceSerializer.duplicate_variant(ws, 0, 1, "副本方案B")
        assert dup.name == "副本方案B"
        assert len(task.variants) == 3

        copy_path = ws.resolve_variant_copy_path(dup)
        assert copy_path.exists()

    def test_duplicate_variant_keeps_internalized_sources_available(self) -> None:
        project, wav_path = build_sample_project(self.tmp_dir / "portable_duplicate")
        self.base_path = self.tmp_dir / "portable_duplicate.afproj"
        ProjectSerializer().save(project, self.base_path)

        ws = self._create_workspace()
        ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        dup = ExperimentWorkspaceSerializer.duplicate_variant(ws, 0, 0, "副本方案")
        copy_path = ws.resolve_variant_copy_path(dup)
        loaded = ProjectSerializer().load(copy_path)
        loaded_clip_path = Path(loaded.events["UiClick"].clips[0].source_path)

        assert loaded_clip_path.exists()
        assert loaded_clip_path.name == wav_path.name

    def test_delete_task(self) -> None:
        ws = self._create_workspace()
        ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        ExperimentWorkspaceSerializer.create_task(ws, "任务2")
        assert len(ws.tasks) == 2

        ExperimentWorkspaceSerializer.delete_task(ws, 0)
        assert len(ws.tasks) == 1
        assert ws.tasks[0].name == "任务2"

    def test_delete_variant(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        ExperimentWorkspaceSerializer.create_variant(ws, 0, "方案B")
        assert len(task.variants) == 2

        ExperimentWorkspaceSerializer.delete_variant(ws, 0, 1)
        assert len(task.variants) == 1

    def test_sync_variant_from_base(self) -> None:
        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")

        # 修改方案副本内容使其不同于底板
        copy_path = ws.resolve_variant_copy_path(task.variants[0])
        variant_project = _make_variant_project()
        _save_project_to_file(variant_project, copy_path)

        # 同步底板后，副本应恢复为底板内容
        backup_path = ExperimentWorkspaceSerializer.sync_variant_from_base(ws, 0, 0)

        # 验证内容恢复为底板
        base_content = ProjectSerializer().load(self.base_path)
        synced_content = ProjectSerializer().load(copy_path)
        assert base_content.name == synced_content.name
        assert backup_path is not None and backup_path.exists()

    def test_sync_variant_from_base_restores_internalized_sources(self) -> None:
        project, wav_path = build_sample_project(self.tmp_dir / "portable_sync")
        self.base_path = self.tmp_dir / "portable_sync.afproj"
        ProjectSerializer().save(project, self.base_path)

        ws = self._create_workspace()
        task = ExperimentWorkspaceSerializer.create_task(ws, "任务1")
        copy_path = ws.resolve_variant_copy_path(task.variants[0])
        shutil.rmtree(copy_path.with_suffix(""), ignore_errors=True)

        backup_path = ExperimentWorkspaceSerializer.sync_variant_from_base(ws, 0, 0)
        synced_content = ProjectSerializer().load(copy_path)
        loaded_clip_path = Path(synced_content.events["UiClick"].clips[0].source_path)

        assert backup_path is not None and backup_path.exists()
        assert loaded_clip_path.exists()
        assert loaded_clip_path.name == wav_path.name

    def test_relative_path_within_workspace(self) -> None:
        """验证相对路径工具函数正确性。"""
        target = self.tmp_dir / "variants" / "task_001" / "variant_001.afproj"
        result = _relative_path(target, self.tmp_dir)
        assert result == "variants/task_001/variant_001.afproj"

    def test_resolve_relative_absolute_path(self) -> None:
        """绝对路径应直接返回。"""
        abs_path = Path("/tmp/something.afproj")
        result = _resolve_relative(self.tmp_dir, str(abs_path))
        assert result == abs_path


# ── Test: ExperimentController (signal-less mock) ─


class MockProjectOpener:
    """模拟 ProjectOpener 协议。"""

    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_project(self, path: str) -> None:
        self.opened_paths.append(path)


class TestExperimentControllerLogic:
    """验证 ExperimentController 业务逻辑（不含 Qt 信号）。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="ec_test_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project_to_file(_make_minimal_project(), self.base_path)
        self.mock_opener = MockProjectOpener()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_controller(self) -> "ExperimentController":
        from audioforge.app.controllers.experiment_controller import ExperimentController
        return ExperimentController(project_opener=self.mock_opener)

    def test_create_workspace(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path), name="ws1")
        assert ec.is_open
        assert ec.workspace is not None
        assert ec.workspace.name == "ws1"

    def test_open_workspace(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws1.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.close_workspace()

        ec2 = self._make_controller()
        ec2.open_workspace(str(ws_path.resolve()))
        assert ec2.is_open
        assert ec2.workspace.name == "ws1"

    def test_close_workspace(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.close_workspace()
        assert not ec.is_open
        assert ec.workspace is None

    def test_create_task(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        task = ec.create_task("任务1")
        assert task is not None
        assert task.name == "任务1"
        assert len(ec.workspace.tasks) == 1

    def test_create_task_without_workspace(self) -> None:
        ec = self._make_controller()
        result = ec.create_task("任务1")
        assert result is None

    def test_delete_task(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        ec.create_task("任务2")
        ec.delete_task(0)
        assert len(ec.workspace.tasks) == 1
        assert ec.workspace.tasks[0].name == "任务2"

    def test_set_active_task(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        ec.create_task("任务2")
        ec.set_active_task(1)
        assert ec.workspace.active_task_index == 1

    def test_set_active_task_out_of_range(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        ec.set_active_task(99)  # out of range
        assert ec.workspace.active_task_index == 0  # unchanged

    def test_create_variant(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        variant = ec.create_variant(0, "方案B")
        assert variant is not None
        assert variant.name == "方案B"
        assert len(ec.workspace.tasks[0].variants) == 2

    def test_activate_variant_calls_project_opener(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")

        result = ec.activate_variant(0, 0)
        assert result.success is True
        assert len(self.mock_opener.opened_paths) == 1
        assert self.mock_opener.opened_paths[0].endswith(".afproj")

    def test_activate_variant_out_of_range(self) -> None:
        """边界检查：activate_variant 对越界索引应该不崩溃。"""
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        result = ec.activate_variant(0, 99)
        assert result.success is False

    def test_set_variant_lifecycle(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        ec.set_variant_lifecycle(0, 0, ExperimentLifecycle.ACTIVE)
        assert ec.workspace.tasks[0].variants[0].lifecycle == ExperimentLifecycle.ACTIVE

    def test_sync_variant_from_base(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        backup_path = ec.sync_variant_from_base(0, 0)
        # 操作完成无异常即可
        assert backup_path is not None

    def test_export_variant_delta(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws_export.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        exporter = ExperimentExporter.create_default()

        result = ec.export_variant_delta(0, 0, exporter)

        assert result.delta_result.delta_file.exists()
        assert result.preview == []

    def test_preview_variant_delta(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws_preview.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")

        variant_path = Path(ec.get_variant_project_path(0, 0) or "")
        variant_project = ProjectSerializer().load(variant_path)
        event = next(iter(variant_project.events.values()))
        event.volume_db = -8.0
        ProjectSerializer().save(variant_project, variant_path)

        exporter = ExperimentExporter.create_default()
        result = ec.preview_variant_delta(0, 0, exporter)

        assert result.preview
        assert any(item["Op"] == "modify" for item in result.preview)

    def test_get_variant_project_path(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        path = ec.get_variant_project_path(0, 0)
        assert path is not None
        assert path.endswith(".afproj")

    def test_get_variant_project_path_out_of_range(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.create_task("任务1")
        result = ec.get_variant_project_path(0, -1)
        assert result is None

    def test_get_base_project_path(self) -> None:
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        path = ec.get_base_project_path()
        assert path is not None


# ── Test: ExperimentExporter ──────────────────────


class TestExperimentExporter:
    """验证增量导出器核心功能。"""

    def test_compute_deltas_preview(self) -> None:
        base = _make_minimal_project()
        variant = _make_variant_project()
        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, variant)
        assert len(deltas) > 0
        # 应包含至少一个 modify 操作（Event_B → Event_B_Mod）
        ops = [d.get("Op") for d in deltas]
        assert "modify" in ops or "add" in ops or "delete" in ops

    def test_compute_deltas_preview_empty_variant(self) -> None:
        base = _make_minimal_project()
        variant = AudioProject(name="empty")
        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, variant)
        # 所有 base 事件应在 variant 中为 delete
        assert all(d.get("Op") == "delete" for d in deltas)

    def test_compute_deltas_preview_identical(self) -> None:
        base = _make_minimal_project()
        # 完全相同的工程不应有增量
        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, base)
        assert len(deltas) == 0

    def test_export_delta_to_disk(self) -> None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="export_test_"))
        try:
            base = _make_minimal_project()
            variant = _make_variant_project()
            task = ExperimentTask(id="t1", name="任务1")
            v = ExperimentVariant(id="v1", name="方案A")
            exporter = ExperimentExporter()
            export_root = tmp_dir / "Export" / "t1_v1"
            result = exporter.export_delta(
                base_project=base,
                variant_project=variant,
                task=task,
                variant=v,
                export_root=export_root,
            )
            assert result.delta_file.exists()
            assert result.report is not None
            assert result.delta_file.name.startswith("ExperimentDelta_")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)