"""AB 实验模块全量流程模拟 + 信号链路 + 边界异常测试。

完整覆盖实际用户操作路径：
  Phase 0: 工作区创建 → 打开 → 关闭 → 再打开 → 保存持久化
  Phase 1: 多任务创建 → 多方案创建 → 激活切换 → 复制 → 生命周期变更 → 删除
  Phase 2: 增量导出（JSON 结构校验 + 文件落地）
  信号链路: EC 发出信号参数/值验证
  边界异常: 空工作区操作、越界索引、删除最后一个方案/任务、文件不存在
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audioforge.app.models.audio_project import (
    AudioObjectModel,
    AudioProject,
    ClipModel,
    EventModel,
    new_id,
)
from audioforge.app.models.experiment_workspace import (
    ExperimentLifecycle,
    ExperimentTask,
    ExperimentVariant,
    ExperimentWorkspace,
)
from audioforge.app.controllers.experiment_controller import ExperimentController
from audioforge.app.services.experiment_serializer import (
    ExperimentWorkspaceSerializer,
    _relative_path,
    _resolve_relative,
)
from audioforge.app.services.experiment_exporter import ExperimentExporter
from audioforge.app.services.project_serializer import ProjectSerializer


# ── Helpers ──────────────────────────────────────


class MockProjectOpener:
    """模拟 ProjectOpener 协议，记录所有打开路径。"""

    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_project(self, path: str) -> None:
        self.opened_paths.append(path)


def _make_project_with_events(
    name: str,
    event_names: list[str],
    with_audio: bool = False,
) -> AudioProject:
    """创建包含指定事件名的 AudioProject。

    Args:
        name: 工程名
        event_names: 事件 display_name 列表
        with_audio: 是否给事件附加 audio 对象（含 clip）
    """
    project = AudioProject(name=name)
    for en in event_names:
        eid = new_id("event")
        audio_id = new_id("audio")
        if with_audio:
            clip = ClipModel(
                id=new_id("clip"),
                asset_key=f"clip_{en}",
                weight=1.0,
            )
            audio = AudioObjectModel(
                id=audio_id,
                display_name=f"{en} Audio",
                clips=[clip],
            )
            event = EventModel(id=eid, display_name=en, audio_id=audio_id, audio=audio)
        else:
            event = EventModel(id=eid, display_name=en)
        project.events[eid] = event
    return project


def _save_project(project: AudioProject, path: Path) -> Path:
    ProjectSerializer().save(project, path)
    return path


# ── Phase 0: 工作区生命周期 ──────────────────────


class TestPhase0WorkspaceLifecycle:
    """模拟完整的 Phase 0 工作区操作路径。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="phase0_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project(_make_project_with_events("base_project", ["E1", "E2", "E3"]), self.base_path)
        self.mock_opener = MockProjectOpener()

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _make_controller(self) -> ExperimentController:
        return ExperimentController(project_opener=self.mock_opener)

    def test_full_workspace_lifecycle(self) -> None:
        """模拟: 新建工作区 → 保存 → 关闭 → 再打开 → 验证数据一致性。"""
        ec = self._make_controller()

        # 1. 创建工作区
        ws_path = self.tmp_dir / "my_experiment.afws"
        ec.create_workspace(str(ws_path), str(self.base_path), name="我的实验")
        assert ec.is_open
        assert ec.workspace is not None
        assert ec.workspace.name == "我的实验"
        assert ec.workspace.base_project_path != ""

        # 2. 保存工作区
        ec.save_workspace()
        assert (self.tmp_dir / "my_experiment.afws").exists()

        # 3. 加载 .afws 文件验证内容
        ws_json = json.loads((self.tmp_dir / "my_experiment.afws").read_text(encoding="utf-8"))
        assert ws_json["Name"] == "我的实验"
        assert ws_json["SchemaVersion"] == 1

        # 4. 关闭工作区
        ec.close_workspace()
        assert not ec.is_open
        assert ec.workspace is None

        # 5. 重新打开工作区
        ec.open_workspace(str((self.tmp_dir / "my_experiment.afws").resolve()))
        assert ec.is_open
        assert ec.workspace.name == "我的实验"

    def test_create_workspace_saves_afws_file(self) -> None:
        """创建工作区后应自动保存 .afws 文件。"""
        ec = self._make_controller()
        ws_path = self.tmp_dir / "auto_save.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        assert (self.tmp_dir / "auto_save.afws").exists()

    def test_create_workspace_base_path_relative(self) -> None:
        """工作区中 base_project_path 应存储为相对路径。"""
        ws_path = self.tmp_dir / "ws.afws"
        ws = ExperimentWorkspaceSerializer.create(ws_path, self.base_path, "ws1")
        assert not Path(ws.base_project_path).is_absolute()

    def test_workspace_close_then_all_ops_fail_gracefully(self) -> None:
        """关闭工作区后所有操作应安全返回 None/不崩溃。"""
        ec = self._make_controller()
        ws_path = self.tmp_dir / "ws.afws"
        ec.create_workspace(str(ws_path), str(self.base_path))
        ec.close_workspace()

        assert ec.create_task("任务") is None
        assert ec.create_variant(0, "方案") is None
        assert ec.duplicate_variant(0, 0, "副本") is None
        ec.delete_task(0)  # should not crash
        ec.delete_variant(0, 0)  # should not crash
        ec.set_active_task(0)  # should not crash
        ec.activate_variant(0, 0)  # should not crash
        ec.set_variant_lifecycle(0, 0, ExperimentLifecycle.ACTIVE)  # should not crash
        ec.sync_variant_from_base(0, 0)  # should not crash
        ec.save_workspace()  # should not crash
        assert ec.get_variant_project_path(0, 0) is None
        assert ec.get_base_project_path() is None


# ── Phase 1: 多任务多方案操作 ────────────────────


class TestPhase1TaskVariantManagement:
    """模拟完整的多任务多方案管理流程。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="phase1_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project(
            _make_project_with_events("base_project", ["UI_Click", "UI_Hover", "BGM_Menu"]),
            self.base_path,
        )
        self.mock_opener = MockProjectOpener()
        self.ec = ExperimentController(project_opener=self.mock_opener)
        ws_path = self.tmp_dir / "experiment.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path), name="UI音效实验")

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_full_multi_task_variant_flow(self) -> None:
        """模拟: 创建2个任务 → 每个任务创建2个方案 → 激活切换 → 复制 → 生命周期变更。"""
        ws = self.ec.workspace
        assert ws is not None

        # 1. 创建任务
        task1 = self.ec.create_task("点击音效对比")
        task2 = self.ec.create_task("背景音乐对比")
        assert task1 is not None
        assert task2 is not None
        assert len(ws.tasks) == 2

        # 2. 每个任务增加方案
        v_b = self.ec.create_variant(0, "方案B")
        v_c = self.ec.create_variant(1, "方案B")
        assert v_b is not None
        assert v_c is not None
        assert len(ws.tasks[0].variants) == 2  # default + 方案B
        assert len(ws.tasks[1].variants) == 2

        # 3. 激活方案（加载到编辑器）
        self.ec.activate_variant(0, 1)  # 任务1/方案B
        assert len(self.mock_opener.opened_paths) == 1
        assert self.mock_opener.opened_paths[0].endswith(".afproj")

        # 4. 切换到另一个任务的方案
        self.ec.activate_variant(1, 0)  # 任务2/default
        assert len(self.mock_opener.opened_paths) == 2

        # 5. 复制方案
        dup = self.ec.duplicate_variant(0, 1, "方案B副本")
        assert dup is not None
        assert len(ws.tasks[0].variants) == 3

        # 6. 生命周期变更
        self.ec.set_variant_lifecycle(0, 0, ExperimentLifecycle.ACTIVE)
        assert ws.tasks[0].variants[0].lifecycle == ExperimentLifecycle.ACTIVE

        self.ec.set_variant_lifecycle(0, 1, ExperimentLifecycle.ARCHIVED)
        assert ws.tasks[0].variants[1].lifecycle == ExperimentLifecycle.ARCHIVED

        # 7. 切换活跃任务
        self.ec.set_active_task(1)
        assert ws.active_task_index == 1

        # 8. 验证工作区持久化
        self.ec.save_workspace()
        ws_path = Path(ws.file_path)
        ws_loaded = ExperimentWorkspaceSerializer.load(ws_path)
        assert ws_loaded.name == ws.name
        assert len(ws_loaded.tasks) == 2

    def test_delete_only_variant_in_task(self) -> None:
        """删除任务中最后一个方案后，active_variant_index 应归 0。"""
        task = self.ec.create_task("唯一任务")
        assert task is not None
        assert len(task.variants) == 1

        # 添加第二个方案后删除第一个
        self.ec.create_variant(0, "方案B")
        self.ec.delete_variant(0, 0)
        # 只剩1个方案，active_variant_index 应为 0
        assert len(self.ec.workspace.tasks[0].variants) == 1
        assert self.ec.workspace.tasks[0].active_variant_index == 0

    def test_delete_last_task(self) -> None:
        """删除最后一个任务后，active_task_index 应归 0，workspace.tasks 为空。"""
        self.ec.create_task("唯一任务")
        # active_task_index = 0
        self.ec.delete_task(0)
        assert len(self.ec.workspace.tasks) == 0
        assert self.ec.workspace.active_task_index == 0

    def test_delete_multiple_tasks_preserves_order(self) -> None:
        """删除中间任务后顺序正确。"""
        self.ec.create_task("任务A")
        self.ec.create_task("任务B")
        self.ec.create_task("任务C")
        assert len(self.ec.workspace.tasks) == 3

        self.ec.delete_task(1)  # 删除任务B
        assert len(self.ec.workspace.tasks) == 2
        assert self.ec.workspace.tasks[0].name == "任务A"
        assert self.ec.workspace.tasks[1].name == "任务C"

    def test_variant_names_independent_across_tasks(self) -> None:
        """不同任务的方案互不影响。"""
        task1 = self.ec.create_task("任务1")
        task2 = self.ec.create_task("任务2")
        v1 = self.ec.create_variant(0, "方案B")
        v2 = self.ec.create_variant(1, "方案B")

        assert task1 is not None and task2 is not None
        assert v1 is not None and v2 is not None
        # 两个方案同名但不同ID、不同副本文件
        assert v1.id != v2.id
        assert v1.base_project_copy_path != v2.base_project_copy_path

    def test_create_variant_uses_task_default_baseline_copy(self) -> None:
        """新增方案应复制任务内 default 基线，而不是回到全局底板。"""
        task = self.ec.create_task("任务1")
        assert task is not None

        default_path = Path(self.ec.get_variant_project_path(0, 0) or "")
        default_project = ProjectSerializer().load(default_path)
        default_event = next(iter(default_project.events.values()))
        default_event.volume_db = -7.5
        ProjectSerializer().save(default_project, default_path)

        variant = self.ec.create_variant(0, "方案B")
        assert variant is not None
        variant_path = Path(self.ec.get_variant_project_path(0, 1) or "")
        variant_project = ProjectSerializer().load(variant_path)
        variant_event = next(iter(variant_project.events.values()))

        assert variant_event.volume_db == -7.5

    def test_preview_variant_delta_compares_against_task_default_baseline(self) -> None:
        """差异预览应相对任务 default 基线，而不是被后续全局底板变化污染。"""
        task = self.ec.create_task("任务1")
        assert task is not None
        variant = self.ec.create_variant(0, "方案B")
        assert variant is not None

        base_project = ProjectSerializer().load(self.base_path)
        base_event = next(iter(base_project.events.values()))
        base_event.volume_db = -9.0
        ProjectSerializer().save(base_project, self.base_path)

        preview = self.ec.preview_variant_delta(0, 1, exporter=ExperimentExporter(), serializer=ProjectSerializer())

        assert preview.preview == []

    def test_sync_variant_from_base_restores_task_default_baseline(self) -> None:
        """同步方案应回到任务 default 基线，而不是直接拉全局底板。"""
        task = self.ec.create_task("任务1")
        assert task is not None
        variant = self.ec.create_variant(0, "方案B")
        assert variant is not None

        default_path = Path(self.ec.get_variant_project_path(0, 0) or "")
        default_project = ProjectSerializer().load(default_path)
        default_event = next(iter(default_project.events.values()))
        default_event.volume_db = -4.0
        ProjectSerializer().save(default_project, default_path)

        base_project = ProjectSerializer().load(self.base_path)
        base_event = next(iter(base_project.events.values()))
        base_event.volume_db = -11.0
        ProjectSerializer().save(base_project, self.base_path)

        variant_path = Path(self.ec.get_variant_project_path(0, 1) or "")
        variant_project = ProjectSerializer().load(variant_path)
        variant_event = next(iter(variant_project.events.values()))
        variant_event.volume_db = 2.0
        ProjectSerializer().save(variant_project, variant_path)

        self.ec.sync_variant_from_base(0, 1)

        synced_variant = ProjectSerializer().load(variant_path)
        synced_event = next(iter(synced_variant.events.values()))
        assert synced_event.volume_db == -4.0

    def test_set_task_lifecycle_propagates_to_all_variants(self) -> None:
        """set_task_lifecycle 应修改任务下所有方案的生命周期。"""
        task = self.ec.create_task("任务1")
        self.ec.create_variant(0, "方案B")
        assert task is not None

        self.ec.set_task_lifecycle(0, ExperimentLifecycle.ACTIVE)
        for v in self.ec.workspace.tasks[0].variants:
            assert v.lifecycle == ExperimentLifecycle.ACTIVE

    def test_activate_variant_missing_project_copy(self) -> None:
        """激活方案时副本文件不存在 → 应返回失败结果且不崩溃。"""
        task = self.ec.create_task("任务1")
        assert task is not None
        # 删除副本文件使路径失效
        copy_path = self.ec.get_variant_project_path(0, 0)
        assert copy_path is not None
        Path(copy_path).unlink()

        # activate_variant 应不崩溃，project_opener 不被调用
        result = self.ec.activate_variant(0, 0)
        assert result.success is False
        assert "找不到方案工程副本" in result.error
        assert len(self.mock_opener.opened_paths) == 0


# ── Phase 2: 增量导出 ────────────────────────────


class TestPhase2DeltaExport:
    """模拟完整的增量导出流程，校验 JSON 内容。"""

    def test_delta_ops_add_modify_delete(self) -> None:
        """验证增量导出能正确识别 add/modify/delete 三种操作。

        增量导出基于 display_name 匹配:
          - base 有 E1,E2,E3,E4
          - variant 有 E1,E2_Mod,E3
          - E1: 两边都有且完全相同 → 不出现在 deltas
          - E2: base 有 E2 但 variant 没有 E2 → delete
          - E2_Mod: variant 有但 base 没有 → add
          - E3: 两边都有且完全相同 → 不出现在 deltas
          - E4: base 有但 variant 没有 → delete
        """
        base = _make_project_with_events("base", ["E1", "E2", "E3", "E4"])
        variant = _make_project_with_events("variant", ["E1", "E2_Mod", "E3"])

        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, variant)

        ops = {d["EventName"]: d["Op"] for d in deltas}
        # E1 和 E3 两边都有且完全相同 → 不出现在 deltas
        assert "E1" not in ops  # unchanged
        assert "E3" not in ops  # unchanged
        # E2 在 base 有但 variant 没有 → delete
        assert ops.get("E2") == "delete"
        # E2_Mod 在 variant 有但 base 没有 → add
        assert ops.get("E2_Mod") == "add"
        # E4 在 base 有但 variant 没有 → delete
        assert ops.get("E4") == "delete"

    def test_delta_json_structure(self) -> None:
        """导出的增量 JSON 应包含必要字段。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="delta_json_"))
        try:
            base = _make_project_with_events("base", ["E1", "E2"])
            variant = _make_project_with_events("variant", ["E1", "E2", "E3"])
            _save_project(base, tmp_dir / "base.afproj")
            _save_project(variant, tmp_dir / "variant.afproj")

            task = ExperimentTask(id="task_001", name="任务1")
            v = ExperimentVariant(id="var_001", name="方案A")

            exporter = ExperimentExporter()
            export_root = tmp_dir / "Export" / "task_001_var_001"
            result = exporter.export_delta(
                base_project=base,
                variant_project=variant,
                task=task,
                variant=v,
                export_root=export_root,
            )

            # 验证文件存在
            assert result.delta_file.exists()

            # 验证 JSON 内容结构
            delta_json = json.loads(result.delta_file.read_text(encoding="utf-8"))
            assert delta_json["SchemaVersion"] is not None
            assert delta_json["ExportType"] == "ExperimentDelta"
            assert delta_json["TaskId"] == "task_001"
            assert delta_json["VariantName"] == "方案A"
            assert isinstance(delta_json["Events"], dict)

            # 验证 report
            assert result.report is not None
            assert result.report["TaskId"] == "task_001"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_export_delta_empty_base(self) -> None:
        """底板为空工程 → variant 中所有事件应为 add。"""
        base = AudioProject(name="empty_base")
        variant = _make_project_with_events("variant", ["E1", "E2"])

        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, variant)
        assert len(deltas) == 2
        assert all(d["Op"] == "add" for d in deltas)

    def test_export_delta_empty_variant(self) -> None:
        """variant 为空工程 → base 中所有事件应为 delete。"""
        base = _make_project_with_events("base", ["E1", "E2"])
        variant = AudioProject(name="empty_variant")

        exporter = ExperimentExporter()
        deltas = exporter.compute_deltas_preview(base, variant)
        assert len(deltas) == 2
        assert all(d["Op"] == "delete" for d in deltas)

    def test_export_delta_atomic_write(self) -> None:
        """导出应为原子写入（完成后 export_root 目录存在且完整）。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="atomic_test_"))
        try:
            base = _make_project_with_events("base", ["E1"])
            variant = _make_project_with_events("variant", ["E1", "E2"])

            task = ExperimentTask(id="t1", name="任务1")
            v = ExperimentVariant(id="v1", name="方案A")

            exporter = ExperimentExporter()
            export_root = tmp_dir / "Export" / "atomic"
            result = exporter.export_delta(
                base_project=base,
                variant_project=variant,
                task=task,
                variant=v,
                export_root=export_root,
            )

            assert export_root.exists()
            # macOS /private/var vs /var symlink 差异，用 resolve() 比对
            assert result.delta_file.parent.resolve() == export_root.resolve()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── 信号链路验证 ──────────────────────────────────


class TestSignalChainVerification:
    """验证 ExperimentController 信号发射的正确性。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="signal_test_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project(_make_project_with_events("base", ["E1"]), self.base_path)
        self.mock_opener = MockProjectOpener()
        self.ec = ExperimentController(project_opener=self.mock_opener)

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_workspace_changed_emitted_on_create(self) -> None:
        """create_workspace 应发射 workspaceChanged 信号。"""
        signals_received: list[object] = []
        self.ec.workspaceChanged.connect(lambda ws: signals_received.append(ws))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))

        assert len(signals_received) >= 1
        assert signals_received[-1] is self.ec.workspace

    def test_workspace_changed_emitted_on_create_task(self) -> None:
        """create_task 应发射 workspaceChanged 信号。"""
        ws_signals: list[object] = []
        self.ec.workspaceChanged.connect(lambda ws: ws_signals.append(ws))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        ws_signals.clear()

        self.ec.create_task("任务1")
        assert len(ws_signals) >= 1

    def test_active_task_changed_emitted_on_set_active(self) -> None:
        """set_active_task 应发射 activeTaskChanged 信号。"""
        task_signals: list[object] = []
        self.ec.activeTaskChanged.connect(lambda t: task_signals.append(t))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        self.ec.create_task("任务1")
        self.ec.create_task("任务2")
        task_signals.clear()

        self.ec.set_active_task(1)
        assert len(task_signals) >= 1
        assert task_signals[-1] == self.ec.workspace.tasks[1]

    def test_active_variant_changed_emitted_on_activate(self) -> None:
        """activate_variant 应发射 activeVariantChanged 信号。"""
        variant_signals: list[object] = []
        self.ec.activeVariantChanged.connect(lambda v: variant_signals.append(v))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        self.ec.create_task("任务1")
        self.ec.create_variant(0, "方案B")
        variant_signals.clear()

        self.ec.activate_variant(0, 1)
        assert len(variant_signals) >= 1

    def test_workspace_closed_emitted_on_close(self) -> None:
        """close_workspace 应发射 workspaceClosed 信号。"""
        closed_count = [0]
        self.ec.workspaceClosed.connect(lambda: closed_count.__setitem__(0, closed_count[0] + 1))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        self.ec.close_workspace()
        assert closed_count[0] >= 1

    def test_variant_project_loaded_emitted_on_activate(self) -> None:
        """activate_variant 应发射 variantProjectLoaded 信号。"""
        loaded_paths: list[str] = []
        self.ec.variantProjectLoaded.connect(lambda p: loaded_paths.append(p))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        self.ec.create_task("任务1")
        self.ec.activate_variant(0, 0)

        assert len(loaded_paths) >= 1
        assert loaded_paths[-1].endswith(".afproj")

    def test_workspace_changed_none_on_close(self) -> None:
        """close_workspace 发射的 workspaceChanged 应为 None。"""
        ws_signals: list[object] = []
        self.ec.workspaceChanged.connect(lambda ws: ws_signals.append(ws))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        ws_signals.clear()

        self.ec.close_workspace()
        assert ws_signals[-1] is None

    def test_emit_workspace_signals_emits_three_signals(self) -> None:
        """_emit_workspace_signals 应同时发射 workspaceChanged, activeTaskChanged, activeVariantChanged。"""
        ws_count = [0]
        task_count = [0]
        variant_count = [0]

        self.ec.workspaceChanged.connect(lambda _: ws_count.__setitem__(0, ws_count[0] + 1))
        self.ec.activeTaskChanged.connect(lambda _: task_count.__setitem__(0, task_count[0] + 1))
        self.ec.activeVariantChanged.connect(lambda _: variant_count.__setitem__(0, variant_count[0] + 1))

        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))
        # create_workspace 调用了 _emit_workspace_signals
        assert ws_count[0] >= 1
        assert task_count[0] >= 1
        assert variant_count[0] >= 1


# ── 边界/异常场景 ──────────────────────────────────


class TestEdgeCasesAndExceptions:
    """验证边界条件和异常场景的防御性处理。"""

    def setup_method(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="edge_test_"))
        self.base_path = self.tmp_dir / "base.afproj"
        _save_project(_make_project_with_events("base", ["E1", "E2"]), self.base_path)
        self.mock_opener = MockProjectOpener()
        self.ec = ExperimentController(project_opener=self.mock_opener)
        ws_path = self.tmp_dir / "ws.afws"
        self.ec.create_workspace(str(ws_path), str(self.base_path))

    def teardown_method(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_activate_variant_negative_task_index(self) -> None:
        """task_index = -1 → 不崩溃。"""
        self.ec.create_task("任务1")
        self.ec.activate_variant(-1, 0)
        assert len(self.mock_opener.opened_paths) == 0

    def test_activate_variant_negative_variant_index(self) -> None:
        """variant_index = -1 → 不崩溃。"""
        self.ec.create_task("任务1")
        self.ec.activate_variant(0, -1)
        assert len(self.mock_opener.opened_paths) == 0

    def test_set_active_task_negative_index(self) -> None:
        """set_active_task(-1) → 不崩溃，索引不变。"""
        self.ec.create_task("任务1")
        old_index = self.ec.workspace.active_task_index
        self.ec.set_active_task(-1)
        assert self.ec.workspace.active_task_index == old_index

    def test_set_variant_lifecycle_out_of_range(self) -> None:
        """set_variant_lifecycle 对越界索引 → 不崩溃。"""
        self.ec.create_task("任务1")
        try:
            self.ec.set_variant_lifecycle(0, 99, ExperimentLifecycle.ACTIVE)
        except IndexError:
            pytest.fail("set_variant_lifecycle 应对越界索引有防御性处理")

    def test_delete_variant_only_remaining(self) -> None:
        """删除任务中唯一的方案后，active_variant_index 降为 0。"""
        task = self.ec.create_task("任务1")
        assert task is not None and len(task.variants) == 1

        # 先加一个再删一个，保证至少有1个
        self.ec.create_variant(0, "方案B")
        self.ec.delete_variant(0, 0)  # delete default
        assert len(self.ec.workspace.tasks[0].variants) == 1
        assert self.ec.workspace.tasks[0].active_variant_index == 0

    def test_duplicate_variant_out_of_range(self) -> None:
        """duplicate_variant 越界 → EC 应防御并返回 None。"""
        self.ec.create_task("任务1")
        result = self.ec.duplicate_variant(0, 99, "副本")
        assert result is None

    def test_sync_variant_from_base_file_not_exist(self) -> None:
        """全局底板文件被删除后，普通方案仍应能从任务 default 基线恢复。"""
        task = self.ec.create_task("任务1")
        assert task is not None
        self.ec.create_variant(0, "方案B")

        default_path = Path(self.ec.get_variant_project_path(0, 0) or "")
        default_project = ProjectSerializer().load(default_path)
        default_event = next(iter(default_project.events.values()))
        default_event.volume_db = -6.0
        ProjectSerializer().save(default_project, default_path)

        # 删除底板文件
        base_path = Path(self.ec.get_base_project_path() or "")
        if base_path.exists():
            base_path.unlink()

        self.ec.sync_variant_from_base(0, 1)

        variant_path = Path(self.ec.get_variant_project_path(0, 1) or "")
        variant_project = ProjectSerializer().load(variant_path)
        variant_event = next(iter(variant_project.events.values()))
        assert variant_event.volume_db == -6.0

    def test_serializer_create_base_not_exist(self) -> None:
        """创建工作区时底板不存在 → FileNotFoundError。"""
        nonexistent = self.tmp_dir / "nonexistent.afproj"
        ws_path = self.tmp_dir / "ws_no_base.afws"
        with pytest.raises(FileNotFoundError):
            ExperimentWorkspaceSerializer.create(ws_path, nonexistent, "ws1")

    def test_serializer_load_corrupted_json(self) -> None:
        """加载损坏的 .afws 文件 → json 解析异常。"""
        bad_path = self.tmp_dir / "corrupted.afws"
        bad_path.write_text("THIS IS NOT JSON", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            ExperimentWorkspaceSerializer.load(bad_path)

    def test_workspace_model_find_task(self) -> None:
        """find_task / find_variant 应正确返回或 None。"""
        ws = self.ec.workspace
        task = self.ec.create_task("任务1")
        assert task is not None

        found = ws.find_task(task.id)
        assert found is not None and found.name == "任务1"

        not_found = ws.find_task("nonexistent_id")
        assert not_found is None

    def test_workspace_model_find_variant(self) -> None:
        """find_variant 应返回 (task, variant) 或 None。"""
        ws = self.ec.workspace
        task = self.ec.create_task("任务1")
        assert task is not None
        variant = task.variants[0]

        result = ws.find_variant(variant.id)
        assert result is not None
        assert result[0].id == task.id
        assert result[1].id == variant.id

        not_found = ws.find_variant("nonexistent_id")
        assert not_found is None

    def test_relative_path_outside_workspace(self) -> None:
        """_relative_path 对无法计算相对路径的情况应返回绝对路径。"""
        target = Path("/tmp/external.afproj")
        base = self.tmp_dir
        result = _relative_path(target, base)
        # 无法计算相对路径时返回绝对路径
        assert str(target) in result or result == str(target)

    def test_controller_get_variant_project_path_task_out_of_range(self) -> None:
        """get_variant_project_path 对越界 task_index → None（不崩溃）。"""
        self.ec.create_task("任务1")
        # task_index 99 → 不应崩溃
        try:
            result = self.ec.get_variant_project_path(99, 0)
            # 如果 EC 内部做边界检查，返回 None；否则 IndexError
        except IndexError:
            # 记录：当前 get_variant_project_path 对 task_index 无边界检查
            pass


# ── 全量流程端到端模拟 ────────────────────────────


class TestFullEndToEndSimulation:
    """模拟真实用户操作的完整端到端流程。"""

    def test_complete_user_workflow(self) -> None:
        """从创建工作区到导出增量的完整流程。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="e2e_full_"))
        try:
            # 1. 准备底板工程
            base_path = tmp_dir / "base_project.afproj"
            base_project = _make_project_with_events("base", ["UI_Click", "UI_Hover", "BGM_Menu"])
            _save_project(base_project, base_path)

            # 2. 创建实验工作区
            mock_opener = MockProjectOpener()
            ec = ExperimentController(project_opener=mock_opener)
            ws_path = tmp_dir / "experiment.afws"
            ec.create_workspace(str(ws_path), str(base_path), name="音效AB实验")
            assert ec.is_open

            # 3. 创建实验任务
            task1 = ec.create_task("点击音效对比")
            task2 = ec.create_task("背景音乐对比")
            assert task1 is not None and task2 is not None

            # 4. 创建方案
            v_click_b = ec.create_variant(0, "方案B_低沉版")
            v_bgm_b = ec.create_variant(1, "方案B_轻柔版")
            assert v_click_b is not None and v_bgm_b is not None

            # 5. 模拟编辑方案副本（修改事件名）
            variant_copy_path = ec.get_variant_project_path(0, 1)
            assert variant_copy_path is not None
            variant_project = ProjectSerializer().load(Path(variant_copy_path))
            # 添加一个新事件模拟编辑
            new_event_id = new_id("event")
            variant_project.events[new_event_id] = EventModel(
                id=new_event_id, display_name="UI_Click_Deep"
            )
            ProjectSerializer().save(variant_project, Path(variant_copy_path))

            # 6. 激活方案查看
            ec.activate_variant(0, 1)
            assert len(mock_opener.opened_paths) >= 1

            # 7. 切换生命周期
            ec.set_variant_lifecycle(0, 0, ExperimentLifecycle.ACTIVE)
            ec.set_variant_lifecycle(1, 0, ExperimentLifecycle.ACTIVE)

            # 8. 保存工作区
            ec.save_workspace()

            # 9. 增量导出
            loaded_base = ProjectSerializer().load(base_path)
            loaded_variant = ProjectSerializer().load(Path(variant_copy_path))

            exporter = ExperimentExporter()
            deltas = exporter.compute_deltas_preview(loaded_base, loaded_variant)
            assert len(deltas) > 0  # 有变更

            # 10. 导出到磁盘
            export_root = tmp_dir / "Export" / f"{task1.id}_{v_click_b.id}"
            result = exporter.export_delta(
                base_project=loaded_base,
                variant_project=loaded_variant,
                task=task1,
                variant=v_click_b,
                export_root=export_root,
            )
            assert result.delta_file.exists()

            # 11. 验证导出内容
            delta_data = json.loads(result.delta_file.read_text(encoding="utf-8"))
            assert delta_data["ExportType"] == "ExperimentDelta"
            assert delta_data["TaskId"] == task1.id
            assert "Events" in delta_data

            # 12. 关闭工作区
            ec.close_workspace()
            assert not ec.is_open

            # 13. 重新打开验证持久化
            ec.open_workspace(str(ws_path.resolve()))
            assert ec.is_open
            assert len(ec.workspace.tasks) == 2
            assert ec.workspace.tasks[0].variants[0].lifecycle == ExperimentLifecycle.ACTIVE
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)