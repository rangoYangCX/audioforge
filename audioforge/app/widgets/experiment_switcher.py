"""AB 实验切换器组件 —— 集成到 TopBar 中。

显示当前实验任务/方案，支持快速切换。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class ExperimentSwitcher(QWidget):
    """TopBar 中的实验切换下拉框。

    未打开实验工作区时显示 "[ 实验模式未开启 ]" 并置灰。
    """

    workspaceCreateRequested = Signal()
    workspaceOpenRequested = Signal()
    workspaceCloseRequested = Signal()
    taskVariantChanged = Signal(int, int)  # task_index, variant_index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._task_index = -1
        self._variant_index = -1
        self._is_open = False
        self._is_dirty = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        icon_label = QLabel("🧪")
        icon_label.setFixedWidth(20)
        layout.addWidget(icon_label)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(180)
        self._combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._combo.setEnabled(False)
        self._combo.addItem("实验模式未开启")
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo, 1)

        self._dirty_label = QLabel("未保存")
        self._dirty_label.setVisible(False)
        self._dirty_label.setToolTip("当前实验方案存在未保存修改")
        layout.addWidget(self._dirty_label)

        self._open_button = QPushButton("打开")
        self._open_button.setFixedWidth(48)
        self._open_button.setToolTip("打开或创建实验工作区")
        self._open_button.clicked.connect(self._on_open_clicked)
        layout.addWidget(self._open_button)

        self._close_button = QPushButton("关闭")
        self._close_button.setFixedWidth(48)
        self._close_button.setToolTip("关闭实验工作区")
        self._close_button.setEnabled(False)
        self._close_button.clicked.connect(self.workspaceCloseRequested.emit)
        layout.addWidget(self._close_button)

    def set_workspace_active(self, active: bool) -> None:
        """设置实验工作区是否激活。"""
        self._is_open = active
        self._combo.setEnabled(active)
        self._close_button.setEnabled(active)
        if not active:
            self._combo.clear()
            self._combo.addItem("实验模式未开启")
            self._task_index = -1
            self._variant_index = -1
            self.set_variant_dirty(False)

    def set_entries(self, entries: list[tuple[int, int, str]]) -> None:
        """设置任务/方案列表。

        Args:
            entries: [(task_index, variant_index, "任务名 / 方案名"), ...]
        """
        self._combo.blockSignals(True)
        self._combo.clear()
        for task_idx, variant_idx, label in entries:
            self._combo.addItem(label, (task_idx, variant_idx))
        self._combo.blockSignals(False)
        if self._combo.count() > 0 and self._task_index >= 0:
            self._select_entry(self._task_index, self._variant_index)

    def set_active(self, task_index: int, variant_index: int) -> None:
        """设置当前激活的任务/方案。"""
        self._task_index = task_index
        self._variant_index = variant_index
        self._select_entry(task_index, variant_index)

    def set_variant_dirty(self, is_dirty: bool) -> None:
        """显示当前激活方案是否存在未保存修改。"""
        self._is_dirty = is_dirty
        self._dirty_label.setVisible(self._is_open and is_dirty)
        self._dirty_label.setText("未保存" if is_dirty else "")

    def _select_entry(self, task_index: int, variant_index: int) -> None:
        for i in range(self._combo.count()):
            data = self._combo.itemData(i)
            if data == (task_index, variant_index):
                self._combo.blockSignals(True)
                self._combo.setCurrentIndex(i)
                self._combo.blockSignals(False)
                return

    def _on_combo_changed(self, index: int) -> None:
        if index < 0:
            return
        data = self._combo.itemData(index)
        if isinstance(data, tuple) and len(data) == 2:
            task_index, variant_index = data
            if task_index != self._task_index or variant_index != self._variant_index:
                self._task_index = task_index
                self._variant_index = variant_index
                self.taskVariantChanged.emit(task_index, variant_index)

    def _on_open_clicked(self) -> None:
        if self._is_open:
            self.workspaceCloseRequested.emit()
        else:
            self.workspaceOpenRequested.emit()
