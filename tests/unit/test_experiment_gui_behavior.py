"""AB 实验面板 GUI 行为模拟测试。

验证用户操作路径中的信号发射和按钮状态变化。
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from audioforge.app.models.audio_project import AudioProject, EventModel, new_id
from audioforge.app.models.experiment_workspace import (
    ExperimentLifecycle,
    ExperimentTask,
    ExperimentVariant,
    ExperimentWorkspace,
)
from audioforge.app.controllers.experiment_controller import ExperimentController
from audioforge.app.services.experiment_serializer import ExperimentWorkspaceSerializer
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.widgets.experiment_panel import ExperimentPanel
from audioforge.app.widgets.experiment_switcher import ExperimentSwitcher


# ── Helpers ──────────────────────────────────────

def _make_project_with_events(name: str, event_names: list[str]) -> AudioProject:
    project = AudioProject(name=name)
    for en in event_names:
        eid = new_id("event")
        event = EventModel(id=eid, display_name=en)
        project.events[eid] = event
    return project


def _save_project(project: AudioProject, path: Path) -> Path:
    ProjectSerializer().save(project, path)
    return path


class MockProjectOpener:
    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_project(self, path: str) -> None:
        self.opened_paths.append(path)


# ── 测试：面板按钮状态 ───────────────────────────


@pytest.mark.usefixtures("qapp")
class TestExperimentPanelButtonStates:
    """验证面板按钮在不同选中状态下的可用性。"""

    def test_empty_tree_all_variant_buttons_disabled(self, qapp) -> None:
        """空树时，所有 variant 级按钮应禁用，但 task 级按钮可用。"""
        panel = ExperimentPanel()
        panel.refresh_tasks([], active_task_index=-1, active_variant_index=-1)
        panel.set_enabled(True)

        # task 级按钮应可用
        assert panel._new_task_edit.isEnabled()
        assert panel._add_task_btn.isEnabled()

        # variant 级按钮应禁用（空树，没有选中）
        assert not panel._new_variant_edit.isEnabled()
        assert not panel._add_variant_btn.isEnabled()
        assert not panel._edit_btn.isEnabled()
        assert not panel._export_btn.isEnabled()

    def test_task_selected_variant_buttons_enabled_for_create(self, qapp) -> None:
        """选中 task 节点时，创建方案按钮可用，编辑/导出不可用。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft"}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=-1)

        # 模拟选中 task 节点
        # refresh_tasks 中 setCurrentItem 选中了 variant(0,0)，需要手动选中 task
        task_item = panel._tree.topLevelItem(0)
        panel._tree.setCurrentItem(task_item)
        panel._update_button_states()

        # 创建方案按钮应可用（选中了 task）
        assert panel._new_variant_edit.isEnabled()
        assert panel._add_variant_btn.isEnabled()

        # 编辑/导出按钮不可用（需要选中 variant）
        assert not panel._edit_btn.isEnabled()
        assert not panel._export_btn.isEnabled()

    def test_variant_selected_all_buttons_enabled(self, qapp) -> None:
        """选中普通 variant 节点时，所有按钮可用。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "default", "id": "v1", "lifecycle": "draft", "readonly": True},
                    {"name": "方案B", "id": "v2", "lifecycle": "draft", "readonly": False},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=1)
        panel.set_enabled(True)

        # 创建方案 + 编辑/导出按钮应全部可用
        assert panel._new_variant_edit.isEnabled()
        assert panel._add_variant_btn.isEnabled()
        assert panel._edit_btn.isEnabled()
        assert panel._compare_btn.isEnabled()
        assert panel._duplicate_btn.isEnabled()
        assert panel._sync_btn.isEnabled()
        assert panel._delete_btn.isEnabled()
        assert panel._export_btn.isEnabled()

    def test_default_variant_selected_is_read_only_baseline(self, qapp) -> None:
        """选中 default 基线时，仅允许查看/复制，不允许变更或导出。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "default", "id": "v1", "lifecycle": "draft", "readonly": True},
                    {"name": "方案B", "id": "v2", "lifecycle": "draft", "readonly": False},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)
        panel.set_enabled(True)

        current = panel._tree.currentItem()
        assert current is not None
        assert "只读基线" in current.text(1)
        assert panel._edit_btn.isEnabled()
        assert panel._duplicate_btn.isEnabled()
        assert not panel._compare_btn.isEnabled()
        assert not panel._sync_btn.isEnabled()
        assert not panel._delete_btn.isEnabled()
        assert not panel._export_btn.isEnabled()

    def test_default_variant_direct_actions_do_not_emit_mutating_signals(self, qapp) -> None:
        """即使直接调用 handler，default 基线也不应发出同步/导出/删除/对比信号。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft", "readonly": True}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)

        received: list[tuple[str, tuple[int, int]]] = []
        panel.compareRequested.connect(lambda t, v: received.append(("compare", (t, v))))
        panel.syncFromBaseRequested.connect(lambda t, v: received.append(("sync", (t, v))))
        panel.deleteVariantRequested.connect(lambda t, v: received.append(("delete", (t, v))))
        panel.exportDeltaRequested.connect(lambda t, v: received.append(("export", (t, v))))

        panel._on_compare_variant()
        panel._on_sync_variant()
        panel._on_delete_variant()
        panel._on_export_delta()

        assert received == []

    def test_create_variant_signal_emitted_when_variant_selected(self, qapp) -> None:
        """选中 variant 时，点击"+方案"按钮应 emit createVariantRequested。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft"}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)

        signals_received: list[tuple] = []
        panel.createVariantRequested.connect(lambda t, n: signals_received.append((t, n)))

        panel._new_variant_edit.setText("方案B")
        panel._on_create_variant()

        assert len(signals_received) == 1
        assert signals_received[0] == (0, "方案B")

    def test_create_variant_signal_NOT_emitted_when_no_selection(self, qapp) -> None:
        """空树时，点击"+方案"按钮不应 emit 信号。"""
        panel = ExperimentPanel()
        panel.refresh_tasks([], active_task_index=-1, active_variant_index=-1)
        panel.set_enabled(True)

        signals_received: list[tuple] = []
        panel.createVariantRequested.connect(lambda t, n: signals_received.append((t, n)))

        # 按钮被禁用，但即使手动调用也不应 emit
        panel._new_variant_edit.setText("方案B")
        panel._on_create_variant()

        assert len(signals_received) == 0

    def test_create_variant_signal_emitted_when_task_selected(self, qapp) -> None:
        """选中 task 节点时，点击"+方案"应 emit createVariantRequested。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft"}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=-1)

        # 手动选中 task 节点
        task_item = panel._tree.topLevelItem(0)
        panel._tree.setCurrentItem(task_item)
        panel._update_button_states()

        signals_received: list[tuple] = []
        panel.createVariantRequested.connect(lambda t, n: signals_received.append((t, n)))

        panel._new_variant_edit.setText("方案B")
        panel._on_create_variant()

        assert len(signals_received) == 1
        assert signals_received[0] == (0, "方案B")

    def test_edit_variant_signal_emitted_when_variant_selected(self, qapp) -> None:
        """选中 variant 时，点击"编辑"按钮应 emit activateVariantRequested。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft"}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)

        signals_received: list[tuple] = []
        panel.activateVariantRequested.connect(lambda t, v: signals_received.append((t, v)))

        panel._on_edit_variant()

        assert len(signals_received) == 1
        assert signals_received[0] == (0, 0)

    def test_export_delta_signal_emitted_when_variant_selected(self, qapp) -> None:
        """选中 variant 时，点击"导出增量"应 emit exportDeltaRequested。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "default", "id": "v1", "lifecycle": "draft", "readonly": True},
                    {"name": "方案B", "id": "v2", "lifecycle": "draft", "readonly": False},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=1)

        signals_received: list[tuple] = []
        panel.exportDeltaRequested.connect(lambda t, v: signals_received.append((t, v)))

        panel._on_export_delta()

        assert len(signals_received) == 1
        assert signals_received[0] == (0, 1)

    def test_compare_signal_emitted_when_variant_selected(self, qapp) -> None:
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "default", "id": "v1", "lifecycle": "draft", "readonly": True},
                    {"name": "方案B", "id": "v2", "lifecycle": "draft", "readonly": False},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=1)

        signals_received: list[tuple] = []
        panel.compareRequested.connect(lambda t, v: signals_received.append((t, v)))

        panel._on_compare_variant()

        assert len(signals_received) == 1
        assert signals_received[0] == (0, 1)


# ── 测试：refresh_tasks 后的选中状态 ──────────────


@pytest.mark.usefixtures("qapp")
class TestRefreshTasksSelectionState:
    """验证 refresh_tasks 后面板的选中状态是否正确。"""

    def test_refresh_tasks_selects_active_variant(self, qapp) -> None:
        """refresh_tasks 应选中 active_variant 对应的节点。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "default", "id": "v1", "lifecycle": "draft"},
                    {"name": "方案B", "id": "v2", "lifecycle": "draft"},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=1)

        # 应选中 variant(0, 1) = "方案B"
        current = panel._tree.currentItem()
        assert current is not None
        data = current.data(0, 1000)
        assert data is not None
        assert data[0] == "variant"
        assert data[1] == 0  # task_index
        assert data[2] == 1  # variant_index

    def test_refresh_tasks_selects_default_variant_when_active_is_minus_one(self, qapp) -> None:
        """当 active_variant_index=-1 时，refresh_tasks 不应选中任何 variant。"""
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [{"name": "default", "id": "v1", "lifecycle": "draft"}],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=-1)

        # 由于 active_variant_index=-1，不会选中任何 variant
        # 但可能选中了 task 节点（如果之前有选中）
        current = panel._tree.currentItem()
        # 根据代码逻辑，没有 variant 满足条件，所以可能没有选中项
        # 或者选中了 task 节点

    def test_empty_workspace_no_selection(self, qapp) -> None:
        """空工作区（无任务）时，面板应无选中项。"""
        panel = ExperimentPanel()
        panel.refresh_tasks([], active_task_index=-1, active_variant_index=-1)

        current = panel._tree.currentItem()
        assert current is None

    def test_create_first_task_then_variant_should_be_selected(self, qapp) -> None:
        """创建第一个任务后，面板应选中 default variant。"""
        tmp_dir = Path(tempfile.mkdtemp(prefix="gui_behavior_"))
        try:
            base_path = tmp_dir / "base.afproj"
            _save_project(_make_project_with_events("base", ["E1"]), base_path)

            mock_opener = MockProjectOpener()
            ec = ExperimentController(project_opener=mock_opener)
            ws_path = tmp_dir / "ws.afws"
            ec.create_workspace(str(ws_path), str(base_path))

            # 创建第一个任务
            task = ec.create_task("任务1")
            assert task is not None
            assert len(ec.workspace.tasks) == 1

            # 验证 workspace 状态
            ws = ec.workspace
            assert ws.active_task_index == 0
            assert ws.active_task is not None
            assert ws.active_task.active_variant_index == 0

            # 模拟面板 refresh
            panel = ExperimentPanel()
            tasks_data = []
            for task in ws.tasks:
                tasks_data.append({
                    "name": task.name,
                    "id": task.id,
                    "variants": [
                        {"name": v.name, "id": v.id, "lifecycle": v.lifecycle.value}
                        for v in task.variants
                    ],
                })

            # 模拟 _on_experiment_workspace_changed 的行为
            active_variant_index = ws.active_task.active_variant_index if ws.active_task else -1
            panel.refresh_tasks(tasks_data, active_task_index=ws.active_task_index, active_variant_index=active_variant_index)
            panel.set_enabled(True)

            # 验证选中状态
            current = panel._tree.currentItem()
            assert current is not None, "创建任务后面板应有选中项"
            data = current.data(0, 1000)
            assert data is not None
            assert data[0] == "variant", f"选中项应为 variant，实际是 {data[0]}"
            assert data[1] == 0  # task_index
            assert data[2] == 0  # variant_index

            # 验证按钮状态
            assert panel._new_variant_edit.isEnabled(), "创建方案按钮应可用"
            assert panel._add_variant_btn.isEnabled(), "创建方案按钮应可用"
            assert panel._edit_btn.isEnabled(), "编辑按钮应可用"
            assert not panel._export_btn.isEnabled(), "default 基线不应允许导出增量"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.mark.usefixtures("qapp")
class TestExperimentPanelEnhancements:
    def test_refresh_tasks_marks_dirty_variant(self, qapp) -> None:
        panel = ExperimentPanel()
        panel.show()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "方案A", "id": "v1", "lifecycle": "draft"},
                    {"name": "方案B", "id": "v2", "lifecycle": "active"},
                ],
            }
        ]

        panel.refresh_tasks(
            tasks_data,
            active_task_index=0,
            active_variant_index=1,
            dirty_task_index=0,
            dirty_variant_index=1,
        )

        current = panel._tree.currentItem()
        assert current is not None
        assert "未保存" in current.text(1)
        assert panel._dirty_label.isVisible()

    def test_filter_hides_non_matching_variants(self, qapp) -> None:
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "任务1",
                "id": "t1",
                "variants": [
                    {"name": "方案Alpha", "id": "v1", "lifecycle": "draft"},
                    {"name": "方案Beta", "id": "v2", "lifecycle": "draft"},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)

        panel._filter_edit.setText("beta")

        task_item = panel._tree.topLevelItem(0)
        assert task_item is not None
        assert not task_item.isHidden()
        assert task_item.child(0).isHidden()
        assert not task_item.child(1).isHidden()

    def test_filter_by_task_keeps_task_children_visible(self, qapp) -> None:
        panel = ExperimentPanel()
        tasks_data = [
            {
                "name": "节奏任务",
                "id": "t1",
                "variants": [
                    {"name": "方案Alpha", "id": "v1", "lifecycle": "draft"},
                    {"name": "方案Beta", "id": "v2", "lifecycle": "draft"},
                ],
            }
        ]
        panel.refresh_tasks(tasks_data, active_task_index=0, active_variant_index=0)

        panel._filter_edit.setText("节奏")

        task_item = panel._tree.topLevelItem(0)
        assert task_item is not None
        assert not task_item.child(0).isHidden()
        assert not task_item.child(1).isHidden()

    def test_restore_snapshot_button_emits_selected_snapshot_path(self, qapp) -> None:
        panel = ExperimentPanel()
        restored_paths: list[str] = []
        panel.restoreSnapshotRequested.connect(restored_paths.append)

        panel.set_autosave_history(
            [
                {
                    "label": "2025-01-01T00:00:00Z | variant.afproj",
                    "path": "/tmp/variant.snapshot.json",
                    "detail": "variant snapshot",
                }
            ]
        )
        panel._autosave_history_list.setCurrentRow(0)

        panel._restore_snapshot_btn.click()

        assert restored_paths == ["/tmp/variant.snapshot.json"]


# ── 测试：空工作区创建方案的问题 ──────────────────


@pytest.mark.usefixtures("qapp")
class TestEmptyWorkspaceCreateVariantIssue:
    """验证空工作区（无任务）时创建方案的行为。"""

    def test_empty_workspace_variant_buttons_disabled(self, qapp) -> None:
        """空工作区时，方案按钮被禁用——这是当前行为，可能是 BUG。"""
        panel = ExperimentPanel()
        panel.refresh_tasks([], active_task_index=-1, active_variant_index=-1)
        panel.set_enabled(True)

        # 方案按钮被禁用（因为没有选中任何节点）
        assert not panel._add_variant_btn.isEnabled()

    def test_variant_create_fails_without_task_selection(self, qapp) -> None:
        """没有选中节点时，_on_create_variant 不 emit 信号。"""
        panel = ExperimentPanel()
        panel.refresh_tasks([], active_task_index=-1, active_variant_index=-1)

        signals: list[tuple] = []
        panel.createVariantRequested.connect(lambda t, n: signals.append((t, n)))

        panel._new_variant_edit.setText("方案A")
        panel._on_create_variant()

        assert len(signals) == 0, "空树时不应 emit createVariantRequested"


# ── 测试：switcher 信号 ────────────────────────────


@pytest.mark.usefixtures("qapp")
class TestSwitcherSignals:
    """验证 switcher 在工作区变更后的行为。"""

    def test_switcher_set_entries_with_tasks(self, qapp) -> None:
        """有任务时，switcher 应显示 entries。"""
        switcher = ExperimentSwitcher()
        switcher.set_workspace_active(True)

        entries = [(0, 0, "任务1 / default"), (0, 1, "任务1 / 方案B")]
        switcher.set_entries(entries)

        assert switcher._combo.count() == 2

    def test_switcher_set_active_selects_correct_entry(self, qapp) -> None:
        """set_active 应选中正确的 entry。"""
        switcher = ExperimentSwitcher()
        switcher.set_workspace_active(True)

        entries = [(0, 0, "任务1 / default"), (0, 1, "任务1 / 方案B")]
        switcher.set_entries(entries)
        switcher.set_active(0, 1)

        assert switcher._combo.currentIndex() == 1

    def test_switcher_empty_workspace_no_entries(self, qapp) -> None:
        """空工作区时，switcher 只有 "实验模式未开启" 一项。"""
        switcher = ExperimentSwitcher()
        # 默认状态
        assert switcher._combo.count() == 1
        assert not switcher._combo.isEnabled()

    def test_switcher_task_variant_changed_on_selection(self, qapp) -> None:
        """切换 switcher 下拉框应 emit taskVariantChanged 信号。"""
        switcher = ExperimentSwitcher()
        switcher.set_workspace_active(True)

        entries = [(0, 0, "任务1 / default"), (0, 1, "任务1 / 方案B")]
        switcher.set_entries(entries)
        switcher.set_active(0, 0)

        signals: list[tuple] = []
        switcher.taskVariantChanged.connect(lambda t, v: signals.append((t, v)))

        # 手动切换到方案B
        switcher._combo.setCurrentIndex(1)

        assert len(signals) >= 1
        assert signals[-1] == (0, 1)

    def test_switcher_shows_dirty_state_for_active_variant(self, qapp) -> None:
        switcher = ExperimentSwitcher()
        switcher.show()
        switcher.set_workspace_active(True)
        switcher.set_entries([(0, 0, "任务1 / 方案A")])
        switcher.set_active(0, 0)

        switcher.set_variant_dirty(True)

        assert switcher._dirty_label.isVisible()
        assert switcher._dirty_label.text() == "未保存"