"""AB 实验面板 —— 左侧任务/方案管理面板。

显示在"实验模式"页面的左侧区域。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ExperimentPanel(QWidget):
    """实验任务/方案管理面板。"""

    createTaskRequested = Signal(str)  # task_name
    deleteTaskRequested = Signal(int)  # task_index
    createVariantRequested = Signal(int, str)  # task_index, variant_name
    deleteVariantRequested = Signal(int, int)  # task_index, variant_index
    activateVariantRequested = Signal(int, int)  # task_index, variant_index
    duplicateVariantRequested = Signal(int, int, str)  # task_index, variant_index, new_name
    syncFromBaseRequested = Signal(int, int)  # task_index, variant_index
    exportDeltaRequested = Signal(int, int)  # task_index, variant_index
    compareRequested = Signal(int, int)  # task_index, variant_index
    lifecycleChangeRequested = Signal(int, int, str)  # task_index, variant_index, lifecycle
    restoreSnapshotRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task_items: dict[tuple[int, int], QTreeWidgetItem] = {}
        self._dirty_variant_key: tuple[int, int] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── 标题行 ──
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        title_label = QLabel("AB 实验")
        title_label.setProperty("role", "panelTitle")
        header_layout.addWidget(title_label, 1)
        self._dirty_label = QLabel("当前方案未保存")
        self._dirty_label.setVisible(False)
        header_layout.addWidget(self._dirty_label)
        layout.addLayout(header_layout)

        self._context_label = QLabel("")
        self._context_label.setWordWrap(True)
        self._context_label.setVisible(False)
        layout.addWidget(self._context_label)

        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        filter_label = QLabel("筛选")
        filter_layout.addWidget(filter_label)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("按任务名或方案名筛选")
        self._filter_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self._filter_edit, 1)
        layout.addLayout(filter_layout)

        # ── 任务/方案树 ──
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["名称", "状态"])
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setAlternatingRowColors(True)
        self._tree.setMinimumHeight(200)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._tree, 1)

        # ── 操作按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._new_task_edit = QLineEdit()
        self._new_task_edit.setPlaceholderText("新任务名称")
        self._new_task_edit.returnPressed.connect(self._on_create_task)
        btn_row.addWidget(self._new_task_edit, 1)

        self._add_task_btn = QPushButton("+ 任务")
        self._add_task_btn.setFixedWidth(60)
        self._add_task_btn.clicked.connect(self._on_create_task)
        btn_row.addWidget(self._add_task_btn)

        layout.addLayout(btn_row)

        # ── 方案操作行 ──
        variant_row = QHBoxLayout()
        variant_row.setSpacing(6)

        self._new_variant_edit = QLineEdit()
        self._new_variant_edit.setPlaceholderText("新方案名称")
        self._new_variant_edit.returnPressed.connect(self._on_create_variant)
        variant_row.addWidget(self._new_variant_edit, 1)

        self._add_variant_btn = QPushButton("+ 方案")
        self._add_variant_btn.setFixedWidth(60)
        self._add_variant_btn.clicked.connect(self._on_create_variant)
        variant_row.addWidget(self._add_variant_btn)

        layout.addLayout(variant_row)

        # ── 选中方案的操作行 ──
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self._edit_btn = QPushButton("📝 编辑")
        self._edit_btn.setToolTip("双击也可激活编辑")
        self._edit_btn.clicked.connect(self._on_edit_variant)
        action_row.addWidget(self._edit_btn)

        self._duplicate_btn = QPushButton("📋 复制")
        self._duplicate_btn.clicked.connect(self._on_duplicate_variant)
        action_row.addWidget(self._duplicate_btn)

        self._sync_btn = QPushButton("🔄 同步底板")
        self._sync_btn.setToolTip("从底板同步到此方案（覆盖当前修改）")
        self._sync_btn.clicked.connect(self._on_sync_variant)
        action_row.addWidget(self._sync_btn)

        self._delete_btn = QPushButton("🗑 删除")
        self._delete_btn.clicked.connect(self._on_delete_variant)
        action_row.addWidget(self._delete_btn)

        layout.addLayout(action_row)

        # ── 导出按钮 ──
        export_row = QHBoxLayout()
        self._compare_btn = QPushButton("🔍 对比差异")
        self._compare_btn.setMinimumHeight(32)
        self._compare_btn.clicked.connect(self._on_compare_variant)
        export_row.addWidget(self._compare_btn)

        self._export_btn = QPushButton("📤 导出增量")
        self._export_btn.setMinimumHeight(32)
        self._export_btn.clicked.connect(self._on_export_delta)
        export_row.addWidget(self._export_btn)
        layout.addLayout(export_row)

        # ── 增量预览区 ──
        preview_label = QLabel("相对底板差异预览")
        preview_label.setProperty("role", "sectionTitle")
        layout.addWidget(preview_label)

        self._preview_tree = QTreeWidget()
        self._preview_tree.setHeaderLabels(["Event", "操作", "差异字段"])
        self._preview_tree.header().setStretchLastSection(True)
        self._preview_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._preview_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._preview_tree.setMinimumHeight(120)
        self._preview_tree.setMaximumHeight(300)
        layout.addWidget(self._preview_tree)

        export_history_label = QLabel("最近导出")
        export_history_label.setProperty("role", "sectionTitle")
        layout.addWidget(export_history_label)

        self._export_history_list = QListWidget()
        self._export_history_list.setMaximumHeight(140)
        layout.addWidget(self._export_history_list)

        autosave_history_label = QLabel("最近快照")
        autosave_history_label.setProperty("role", "sectionTitle")
        layout.addWidget(autosave_history_label)

        self._autosave_history_list = QListWidget()
        self._autosave_history_list.setMaximumHeight(140)
        self._autosave_history_list.itemDoubleClicked.connect(lambda item: self._emit_restore_snapshot(item))
        layout.addWidget(self._autosave_history_list)

        self._restore_snapshot_btn = QPushButton("恢复选中快照")
        self._restore_snapshot_btn.clicked.connect(self._restore_selected_snapshot)
        self._restore_snapshot_btn.setEnabled(False)
        layout.addWidget(self._restore_snapshot_btn)

    # ── 数据刷新 ──────────────────────────────────

    def refresh_tasks(
        self,
        tasks: list[dict],
        active_task_index: int = -1,
        active_variant_index: int = -1,
        dirty_task_index: int = -1,
        dirty_variant_index: int = -1,
    ) -> None:
        """刷新任务/方案树。

        Args:
            tasks: [{"id": ..., "name": ..., "variants": [{"id": ..., "name": ..., "lifecycle": ...}]}]
        """
        self._tree.blockSignals(True)
        self._tree.clear()
        self._task_items.clear()
        self._dirty_variant_key = None
        if dirty_task_index >= 0 and dirty_variant_index >= 0:
            self._dirty_variant_key = (dirty_task_index, dirty_variant_index)
            self._dirty_label.setVisible(True)
        else:
            self._dirty_label.setVisible(False)

        for task_i, task in enumerate(tasks):
            task_item = QTreeWidgetItem(self._tree, [task.get("name", ""), ""])
            task_item.setData(0, 1000, ("task", task_i))
            task_item.setExpanded(True)
            self._tree.addTopLevelItem(task_item)

            for variant_i, variant in enumerate(task.get("variants", [])):
                lifecycle_text = variant.get("lifecycle", "draft")
                lifecycle_icon, lifecycle_color = self._lifecycle_display(lifecycle_text)
                is_readonly = bool(variant.get("readonly", variant_i == 0 and str(variant.get("name", "")).strip().casefold() == "default"))
                status_text = lifecycle_icon
                if is_readonly:
                    status_text = f"{lifecycle_icon} • 只读基线"
                if self._dirty_variant_key == (task_i, variant_i):
                    status_text = f"{status_text} • 未保存"
                variant_item = QTreeWidgetItem(task_item, [
                    variant.get("name", ""),
                    status_text,
                ])
                variant_item.setData(0, 1000, ("variant", task_i, variant_i))
                variant_item.setData(0, 1001, is_readonly)
                if lifecycle_color:
                    variant_item.setForeground(0, lifecycle_color)
                    variant_item.setForeground(1, lifecycle_color)
                if is_readonly:
                    font = variant_item.font(0)
                    font.setBold(True)
                    variant_item.setFont(0, font)
                    variant_item.setToolTip(0, "default 基线为只读版本，用于承载当前任务的对比基准。")
                    variant_item.setToolTip(1, "只读基线")
                key = (task_i, variant_i)
                self._task_items[key] = variant_item

                # 选中当前激活的方案
                if task_i == active_task_index and variant_i == active_variant_index:
                    self._tree.setCurrentItem(variant_item)
                    self._tree.scrollToItem(variant_item)

        self._tree.blockSignals(False)
        self._apply_filter(self._filter_edit.text())

    def set_preview(self, deltas: list[dict]) -> None:
        """设置增量预览列表。"""
        self._preview_tree.clear()
        for delta in deltas:
            op = delta.get("Op", "")
            event_name = delta.get("EventName", "")
            diff_fields = delta.get("DiffFields", [])

            op_display = {
                "add": "➕ 新增",
                "modify": "✏️ 修改",
                "delete": "❌ 删除",
            }.get(op, op)

            item = QTreeWidgetItem(
                self._preview_tree,
                [event_name, op_display, ", ".join(str(f) for f in diff_fields)],
            )
            self._preview_tree.addTopLevelItem(item)

    def set_context_summary(self, *, base_label: str, active_label: str) -> None:
        if not base_label and not active_label:
            self._context_label.clear()
            self._context_label.setVisible(False)
            return
        self._context_label.setText(f"底板：{base_label or '-'}\n当前方案：{active_label or '-'}")
        self._context_label.setVisible(True)

    def set_export_history(self, entries: list[dict[str, object]]) -> None:
        self._export_history_list.clear()
        for entry in entries:
            self._export_history_list.addItem(str(entry.get("label", "导出记录")))

    def set_autosave_history(self, entries: list[dict[str, object]]) -> None:
        self._autosave_history_list.clear()
        for entry in entries:
            item = QListWidgetItem(str(entry.get("label", "自动保存记录")))
            item.setData(Qt.ItemDataRole.UserRole, str(entry.get("path", "")))
            item.setToolTip(str(entry.get("detail", "")))
            self._autosave_history_list.addItem(item)
        self._restore_snapshot_btn.setEnabled(self._autosave_history_list.count() > 0 and self.isEnabled())

    def set_enabled(self, enabled: bool) -> None:
        """设置面板可用状态。"""
        self._tree.setEnabled(enabled)
        self._preview_tree.setEnabled(enabled)
        self._autosave_history_list.setEnabled(enabled)
        if not enabled:
            self._new_task_edit.setEnabled(False)
            self._add_task_btn.setEnabled(False)
            self._new_variant_edit.setEnabled(False)
            self._add_variant_btn.setEnabled(False)
            self._filter_edit.setEnabled(False)
            self._edit_btn.setEnabled(False)
            self._compare_btn.setEnabled(False)
            self._duplicate_btn.setEnabled(False)
            self._sync_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            self._restore_snapshot_btn.setEnabled(False)
            self._dirty_label.setVisible(False)
        else:
            self._filter_edit.setEnabled(True)
            self._restore_snapshot_btn.setEnabled(self._autosave_history_list.count() > 0)
            # 重新根据当前选中状态设置按钮
            self._update_button_states()

    def _update_button_states(self) -> None:
        """根据选中节点类型细粒度设置按钮可用状态。"""
        # 任务级操作始终可用（只要有 workspace）
        self._new_task_edit.setEnabled(True)
        self._add_task_btn.setEnabled(True)

        selection = self._get_selection_type()
        if selection == "task":
            # 选中任务节点：创建方案可用，variant 级按钮不可用
            self._new_variant_edit.setEnabled(True)
            self._add_variant_btn.setEnabled(True)
            self._edit_btn.setEnabled(False)
            self._edit_btn.setText("📝 编辑")
            self._compare_btn.setEnabled(False)
            self._duplicate_btn.setEnabled(False)
            self._sync_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
        elif selection == "variant":
            is_readonly = self._selected_variant_is_read_only()
            self._new_variant_edit.setEnabled(True)
            self._add_variant_btn.setEnabled(True)
            self._edit_btn.setEnabled(True)
            self._compare_btn.setEnabled(not is_readonly)
            self._duplicate_btn.setEnabled(True)
            self._sync_btn.setEnabled(not is_readonly)
            self._delete_btn.setEnabled(not is_readonly)
            self._export_btn.setEnabled(not is_readonly)
            self._edit_btn.setText("👁 查看基线" if is_readonly else "📝 编辑")
        else:
            # 无选中或 workspace 未开
            self._new_variant_edit.setEnabled(False)
            self._add_variant_btn.setEnabled(False)
            self._edit_btn.setEnabled(False)
            self._compare_btn.setEnabled(False)
            self._duplicate_btn.setEnabled(False)
            self._sync_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            self._edit_btn.setText("📝 编辑")

    def _on_selection_changed(self) -> None:
        """选中节点变更时更新按钮状态。"""
        if self._tree.isEnabled():
            self._update_button_states()

    def _apply_filter(self, text: str) -> None:
        query = text.strip().casefold()
        for task_i in range(self._tree.topLevelItemCount()):
            task_item = self._tree.topLevelItem(task_i)
            task_matches = query in task_item.text(0).casefold()
            visible_children = 0
            for child_i in range(task_item.childCount()):
                child = task_item.child(child_i)
                child_matches = task_matches or query in child.text(0).casefold()
                child.setHidden(bool(query) and not child_matches)
                if not child.isHidden():
                    visible_children += 1
            task_visible = (not query) or task_matches or visible_children > 0
            task_item.setHidden(not task_visible)
            task_item.setExpanded(bool(query) and task_visible)

    def _get_selection_type(self) -> str:
        """返回当前选中类型: 'task', 'variant', 或 ''。"""
        item = self._tree.currentItem()
        if item is None:
            return ""
        data = item.data(0, 1000)
        if data is None:
            return ""
        return data[0]

    # ── 内部事件 ──────────────────────────────────

    @staticmethod
    def _lifecycle_display(lifecycle: str) -> tuple[str, QColor | None]:
        """返回 lifecycle 对应的显示文本和颜色。"""
        mapping = {
            "draft": ("📝 draft", QColor(128, 128, 128)),
            "active": ("🟢 active", QColor(34, 139, 34)),
            "archived": ("📦 archived", QColor(204, 119, 0)),
            "merged": ("✅ merged", QColor(30, 90, 180)),
        }
        return mapping.get(lifecycle, (lifecycle, None))

    def _selected_task_variant(self) -> tuple[int, int] | None:
        """获取当前选中的任务/方案索引。对 task 节点返回 (task_index, -1)。"""
        item = self._tree.currentItem()
        if item is None:
            return None
        data = item.data(0, 1000)
        if data is None:
            return None
        if data[0] == "variant":
            return data[1], data[2]
        if data[0] == "task":
            return data[1], -1
        return None

    def _on_create_task(self) -> None:
        name = self._new_task_edit.text().strip()
        if name:
            self.createTaskRequested.emit(name)
            self._new_task_edit.clear()

    def _on_create_variant(self) -> None:
        result = self._selected_task_variant()
        if result is None:
            return
        task_index, _ = result
        name = self._new_variant_edit.text().strip()
        if name:
            self.createVariantRequested.emit(task_index, name)
            self._new_variant_edit.clear()

    def _selected_variant_only(self) -> tuple[int, int] | None:
        """获取当前选中的方案索引（仅 variant 节点，task 节点返回 None）。"""
        result = self._selected_task_variant()
        if result is None or result[1] < 0:
            return None
        return result

    def _selected_variant_is_read_only(self) -> bool:
        item = self._tree.currentItem()
        if item is None:
            return False
        return bool(item.data(0, 1001))

    def _on_edit_variant(self) -> None:
        result = self._selected_variant_only()
        if result:
            self.activateVariantRequested.emit(result[0], result[1])

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, 1000)
        if data and data[0] == "variant":
            self.activateVariantRequested.emit(data[1], data[2])

    def _on_duplicate_variant(self) -> None:
        result = self._selected_variant_only()
        if result is None or result[1] < 0:
            return
        task_index, variant_index = result
        self.duplicateVariantRequested.emit(
            task_index, variant_index, f"副本_{variant_index + 1}"
        )

    def _on_sync_variant(self) -> None:
        result = self._selected_variant_only()
        if result is None or self._selected_variant_is_read_only():
            return
        ret = QMessageBox.question(
            self,
            "确认同步",
            "从底板同步到此方案将覆盖当前修改，此操作不可撤销。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.syncFromBaseRequested.emit(result[0], result[1])

    def _on_delete_variant(self) -> None:
        result = self._selected_variant_only()
        if result is None or self._selected_variant_is_read_only():
            return
        ret = QMessageBox.question(
            self,
            "确认删除",
            "删除方案不可撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.deleteVariantRequested.emit(result[0], result[1])

    def _on_export_delta(self) -> None:
        result = self._selected_variant_only()
        if result and not self._selected_variant_is_read_only():
            self.exportDeltaRequested.emit(result[0], result[1])

    def _on_compare_variant(self) -> None:
        result = self._selected_variant_only()
        if result and not self._selected_variant_is_read_only():
            self.compareRequested.emit(result[0], result[1])

    def _restore_selected_snapshot(self) -> None:
        self._emit_restore_snapshot(self._autosave_history_list.currentItem())

    def _emit_restore_snapshot(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        snapshot_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if snapshot_path:
            self.restoreSnapshotRequested.emit(snapshot_path)

    def _on_tree_context_menu(self, pos) -> None:
        """右键菜单：删除任务、修改方案状态。"""
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, 1000)
        if data is None:
            return

        menu = QMenu(self._tree)

        if data[0] == "task":
            # Phase 1.2: 删除任务
            task_index = data[1]
            delete_task_action = menu.addAction("删除任务")
            delete_task_action.triggered.connect(lambda _: self._confirm_delete_task(task_index))

        elif data[0] == "variant":
            # Phase 2.2: 修改方案生命周期
            task_index, variant_index = data[1], data[2]
            if bool(item.data(0, 1001)):
                readonly_action = menu.addAction("default 基线为只读版本")
                readonly_action.setEnabled(False)
            else:
                lifecycle_menu = menu.addMenu("修改状态")
                for lc_value, lc_label in [
                    ("draft", "📝 draft"),
                    ("active", "🟢 active"),
                    ("archived", "📦 archived"),
                    ("merged", "✅ merged"),
                ]:
                    action = lifecycle_menu.addAction(lc_label)
                    action.triggered.connect(
                        lambda _, t=task_index, v=variant_index, lc=lc_value:
                            self.lifecycleChangeRequested.emit(t, v, lc)
                    )

        if menu.actions():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _confirm_delete_task(self, task_index: int) -> None:
        """Phase 1.2: 删除任务确认对话框。"""
        ret = QMessageBox.question(
            self,
            "确认删除任务",
            "删除任务将同时删除其下所有方案，此操作不可撤销。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.deleteTaskRequested.emit(task_index)
