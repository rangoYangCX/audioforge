from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from audioforge.app.utils.constants import WWISE_MASTER_MIXER_TITLE


class DetachedToolWindow(QWidget):
    closeRequested = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowTitleHint, True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closeRequested.emit()
        event.ignore()


class TaskSidebar(QFrame):
    modeRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TaskSidebar")
        self._buttons: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("工作模式")
        title.setProperty("role", "sidebarTitle")
        layout.addWidget(title)

        utility_specs = [("home", "欢迎页")]
        for mode, label in utility_specs:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "taskNavButton")
            button.clicked.connect(lambda checked=False, target_mode=mode: self.modeRequested.emit(target_mode))
            self._button_group.addButton(button)
            self._buttons[mode] = button
            layout.addWidget(button)

        workflow_title = QLabel("制作流程")
        workflow_title.setProperty("role", "sidebarTitle")
        layout.addWidget(workflow_title)

        button_specs = [
            ("resources", "资源整理"),
            ("events", "事件设计"),
            ("buses", WWISE_MASTER_MIXER_TITLE),
            ("validation", "校验修复"),
            ("build", "构建交付"),
        ]
        for mode, label in button_specs:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "taskNavButton")
            button.clicked.connect(lambda checked=False, target_mode=mode: self.modeRequested.emit(target_mode))
            self._button_group.addButton(button)
            self._buttons[mode] = button
            layout.addWidget(button)

        results_title = QLabel("结果回看")
        results_title.setProperty("role", "sidebarTitle")
        layout.addWidget(results_title)

        result_specs = [
            ("results", "结果中心"),
        ]
        for mode, label in result_specs:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("role", "taskNavButton")
            button.clicked.connect(lambda checked=False, target_mode=mode: self.modeRequested.emit(target_mode))
            self._button_group.addButton(button)
            self._buttons[mode] = button
            layout.addWidget(button)

        layout.addStretch(1)

    def set_active_mode(self, mode: str) -> None:
        for current_mode, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(current_mode == mode)
            button.blockSignals(False)

    def button(self, mode: str) -> QPushButton | None:
        return self._buttons.get(mode)


class AppShell(QFrame):
    def __init__(self, top_bar: QWidget, sidebar: QWidget, content: QWidget) -> None:
        super().__init__()
        self.setObjectName("AppShell")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(top_bar)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(content, 1)
        layout.addWidget(body, 1)


class CompatibilityTabWidget(QTabWidget):
    def __init__(self) -> None:
        super().__init__()
        self._current_widget_resolver: Callable[[], QWidget | None] | None = None

    def set_current_widget_resolver(self, resolver: Callable[[], QWidget | None]) -> None:
        self._current_widget_resolver = resolver

    def currentWidget(self) -> QWidget | None:  # type: ignore[override]
        if self._current_widget_resolver is not None:
            widget = self._current_widget_resolver()
            if widget is not None:
                return widget
        return super().currentWidget()
