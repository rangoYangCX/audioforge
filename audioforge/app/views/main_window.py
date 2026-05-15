from __future__ import annotations

import os

try:
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    sf = None

from PySide6.QtCore import QByteArray, QItemSelectionModel, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QGridLayout,
    QSpinBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from audioforge.app.models.audio_project import (
    BusConfig,
    ClipModel,
    EventModel,
    GameParameterModel,
    ProjectSettings,
    RtpcBindingModel,
    StateGroupModel,
    StateOverrideModel,
    SwitchGroupModel,
    SwitchVariantModel,
    ValidationIssue,
)
from audioforge.app.services.audio_meter_service import AudioMeterSnapshot, LoudnessReading
from audioforge.app.utils.icons import load_app_icon
from audioforge.app.utils.constants import (
    APP_NAME,
    CLIP_WEIGHT_PRESETS,
    DEFAULT_BUSES,
    DEFAULT_WINDOW_SIZE,
    MAX_CLIP_TIME_MS,
    MAX_CLIP_WEIGHT,
    MAX_COOLDOWN_SECONDS,
    MAX_COMBO_MAX_STEP,
    MAX_MAX_INSTANCES,
    MAX_PITCH_CENTS,
    MAX_VOLUME_DB,
    MIN_CLIP_TIME_MS,
    MIN_CLIP_WEIGHT,
    MIN_COOLDOWN_SECONDS,
    MIN_COMBO_MAX_STEP,
    MIN_MAX_INSTANCES,
    MIN_PITCH_CENTS,
    MIN_VOLUME_DB,
    PROJECT_EXTENSION,
    WWISE_BUS_NAME_LABEL,
    WWISE_BUS_SEARCH_KEYWORDS,
    WWISE_BUS_VIEW_LABEL,
    WWISE_BUS_WORKSPACE_KEYWORDS,
    WWISE_CHILD_BUSES_LABEL,
    WWISE_DEFAULT_BUS_LABEL,
    WWISE_EFFECTIVE_OUTPUT_LABEL,
    WWISE_MASTER_AUDIO_BUS_TITLE,
    WWISE_MASTER_MIXER_HIERARCHY_TITLE,
    WWISE_MASTER_MIXER_TITLE,
    WWISE_OUTPUT_BUS_LABEL,
    WWISE_PARENT_BUS_LABEL,
    WWISE_PROPERTY_EDITOR_TITLE,
    WWISE_RESOURCES_BATCH_FEEDBACK_KEYWORDS,
    WWISE_ROUTING_LABEL,
    WWISE_TARGET_BUS_LABEL,
    WWISE_TRANSPORT_TITLE,
)
from audioforge.app.widgets.clip_table import ClipTableWidget
from audioforge.app.widgets.clip_waveform_editor import ClipWaveformEditor
from audioforge.app.widgets.audio_tree import AudioTreeWidget
from audioforge.app.widgets.event_tree import EventTreeWidget, decode_source_binding_token
from audioforge.app.widgets.loudness_history_plot import LoudnessHistoryPlot
from audioforge.app.widgets.rtpc_curve_editor import RtpcCurveEditor
from audioforge.app.widgets.source_tree import SOURCE_ASSET_MIME_TYPE, SourceTreeWidget
from audioforge.app.views.shell_components import AppShell, DetachedToolWindow, TaskSidebar


class ProjectBusTreeWidget(QTreeWidget):
    hierarchyChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setIndentation(18)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self.hierarchyChanged.emit()


class CurrentPageStack(QStackedWidget):
    def sizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is not None:
            hint = current.sizeHint()
            if hint.isValid():
                return QSize(hint.width(), 0)
        hint = super().sizeHint()
        return QSize(hint.width(), 0)

    def minimumSizeHint(self) -> QSize:
        current = self.currentWidget()
        if current is not None:
            hint = current.minimumSizeHint()
            if hint.isValid():
                return QSize(hint.width(), 0)
        hint = super().minimumSizeHint()
        return QSize(hint.width(), 0)


class EventSourceBindingDropZone(QFrame):
    sourceAssetsDropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("EventSourceBindingDropZone")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setMinimumHeight(92)
        self.setProperty("dragActive", False)
        self.setStyleSheet(
            "QFrame#EventSourceBindingDropZone {"
            "border: 1px dashed rgba(159, 184, 205, 0.55);"
            "border-radius: 10px;"
            "background-color: rgba(159, 184, 205, 0.05);"
            "}"
            "QFrame#EventSourceBindingDropZone[dragActive=\"true\"] {"
            "border: 2px solid rgba(214, 145, 59, 0.95);"
            "background-color: rgba(214, 145, 59, 0.12);"
            "}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.isEnabled() and self._extract_source_paths(event.mimeData()):
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self.isEnabled() and self._extract_source_paths(event.mimeData()):
            self._set_drag_active(True)
            event.acceptProposedAction()
            return
        self._set_drag_active(False)
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        source_paths = self._extract_source_paths(event.mimeData())
        self._set_drag_active(False)
        if not self.isEnabled() or not source_paths:
            event.ignore()
            return
        self.sourceAssetsDropped.emit(source_paths)
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _extract_source_paths(self, mime_data) -> list[str]:
        if mime_data is None or not mime_data.hasFormat(SOURCE_ASSET_MIME_TYPE):
            return []
        raw_payload = bytes(mime_data.data(SOURCE_ASSET_MIME_TYPE)).decode("utf-8", errors="ignore")
        source_paths: list[str] = []
        seen_paths: set[str] = set()
        for line in raw_payload.splitlines():
            source_path = line.strip()
            if not source_path or source_path in seen_paths:
                continue
            source_paths.append(source_path)
            seen_paths.add(source_path)
        return source_paths


def _is_single_active_mode(play_mode: str) -> bool:
    return str(play_mode) == "OneShot"


def _binding_state_key(play_mode: str, clip: ClipModel) -> str:
    if not bool(clip.enabled):
        return "disabled"
    if bool(clip.active):
        return "active"
    return "inactive"


def _binding_state_label(play_mode: str, clip: ClipModel) -> str:
    state_key = _binding_state_key(play_mode, clip)
    if state_key == "disabled":
        return "已停用"
    if state_key == "active":
        return "已激活"
    if _is_single_active_mode(play_mode):
        return "候选未激活"
    return "未激活"


def _binding_rollup_text(play_mode: str, clips: list[ClipModel]) -> str:
    total_count = len(clips)
    effective_count = sum(1 for clip in clips if bool(clip.enabled) and bool(clip.active))
    inactive_count = sum(1 for clip in clips if bool(clip.enabled) and not bool(clip.active))
    disabled_count = sum(1 for clip in clips if not bool(clip.enabled))
    fragments = [f"当前挂载 {total_count} 条 Source Binding", f"生效 {effective_count} 条"]
    if inactive_count:
        inactive_label = "候选未激活" if _is_single_active_mode(play_mode) else "未激活"
        fragments.append(f"{inactive_label} {inactive_count} 条")
    if disabled_count:
        fragments.append(f"已停用 {disabled_count} 条")
    return " | ".join(fragments)


def _binding_state_palette(state_key: str) -> dict[str, str]:
    palette = {
        "active": {
            "background": "rgba(54, 118, 98, 0.16)",
            "border": "rgba(81, 191, 154, 0.88)",
            "accent": "rgba(112, 227, 187, 0.98)",
            "title": "#f1fff9",
            "meta": "#d7efe5",
            "path": "#add6c6",
            "chip_text": "#ecfff7",
            "chip_background": "rgba(93, 211, 170, 0.22)",
        },
        "inactive": {
            "background": "rgba(118, 132, 145, 0.09)",
            "border": "rgba(152, 167, 181, 0.64)",
            "accent": "rgba(190, 202, 214, 0.84)",
            "title": "#f1f5f8",
            "meta": "#d7dfe6",
            "path": "#aebbc7",
            "chip_text": "#edf2f6",
            "chip_background": "rgba(179, 191, 203, 0.18)",
        },
        "disabled": {
            "background": "rgba(131, 79, 79, 0.08)",
            "border": "rgba(198, 118, 118, 0.66)",
            "accent": "rgba(223, 136, 136, 0.9)",
            "title": "#fff1f1",
            "meta": "#ebcece",
            "path": "#d6b2b2",
            "chip_text": "#fff5f5",
            "chip_background": "rgba(214, 133, 133, 0.2)",
        },
    }
    return palette.get(state_key, palette["inactive"])


def _apply_binding_card_style(
    card: QFrame,
    chip: QLabel,
    title_label: QLabel,
    meta_labels: list[QLabel],
    path_label: QLabel,
    state_key: str,
) -> None:
    palette = _binding_state_palette(state_key)
    card.setStyleSheet(
        "QFrame {"
        f"border: 1px solid {palette['border']};"
        f"border-left: 4px solid {palette['accent']};"
        "border-radius: 12px;"
        f"background-color: {palette['background']};"
        "}"
    )
    chip.setStyleSheet(
        "QLabel {"
        f"color: {palette['chip_text']};"
        f"background-color: {palette['chip_background']};"
        "border-radius: 10px;"
        "padding: 3px 8px;"
        "font-weight: 600;"
        "}"
    )
    title_label.setStyleSheet(f"color: {palette['title']}; font-weight: 700;")
    for label in meta_labels:
        label.setStyleSheet(f"color: {palette['meta']};")
    path_label.setStyleSheet(f"color: {palette['path']};")


class AudioBindingsPopup(QDialog):
    sourceAssetsDropped = Signal(str, list)
    bindingEnabledChanged = Signal(str, str, bool)
    bindingActiveChanged = Signal(str, str, bool)
    locateSourceRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._event_id = ""
        self._play_mode = "Random"
        self._binding_group: QButtonGroup | None = QButtonGroup(self)
        self._binding_group.setExclusive(True)

        self.setWindowTitle("Audio 源音频绑定")
        self.setWindowFlag(Qt.WindowType.Popup, True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(460)
        self.setMaximumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.title_label = QLabel("Audio 源音频绑定")
        self.title_label.setProperty("role", "workspaceSectionTitle")
        self.detail_label = QLabel("拖拽左侧源音频到这里，或直接调整当前 Audio 的 Active / Enabled。")
        self.detail_label.setProperty("role", "workspaceSectionSummary")
        self.detail_label.setWordWrap(True)

        self.status_label = QLabel("")
        self.status_label.setProperty("role", "workspaceSectionSummary")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "QLabel {"
            "border: 1px solid rgba(214, 145, 59, 0.35);"
            "border-radius: 8px;"
            "padding: 6px 10px;"
            "background-color: rgba(214, 145, 59, 0.1);"
            "color: #f4ddc0;"
            "}"
        )
        self.status_label.hide()

        self.drop_zone = EventSourceBindingDropZone(self)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(12, 10, 12, 10)
        drop_layout.setSpacing(4)
        self.drop_title_label = QLabel("拖拽源音频到这里")
        self.drop_title_label.setProperty("role", "workspaceSectionTitle")
        self.drop_detail_label = QLabel("支持从左侧源音频树单选或多选后直接拖入；重复绑定会自动跳过。")
        self.drop_detail_label.setWordWrap(True)
        drop_layout.addWidget(self.drop_title_label)
        drop_layout.addWidget(self.drop_detail_label)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setMinimumHeight(180)
        self.scroll_area.setMaximumHeight(360)
        self.bindings_container = QWidget(self.scroll_area)
        self.bindings_layout = QVBoxLayout(self.bindings_container)
        self.bindings_layout.setContentsMargins(0, 0, 0, 0)
        self.bindings_layout.setSpacing(8)
        self.scroll_area.setWidget(self.bindings_container)

        self.empty_state_label = QLabel("当前 Audio 还没有绑定源音频。直接从左侧源音频树拖进来即可。")
        self.empty_state_label.setProperty("role", "workspaceSectionSummary")
        self.empty_state_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.drop_zone)
        layout.addWidget(self.empty_state_label)
        layout.addWidget(self.scroll_area)

        self.drop_zone.sourceAssetsDropped.connect(self._emit_source_asset_drop)

    def event_id(self) -> str:
        return self._event_id

    def set_event(self, event: EventModel, status_message: str = "") -> None:
        self._event_id = event.id
        self._play_mode = str(event.play_mode)
        label = event.display_name or event.id
        play_mode_label = {"OneShot": "单次播放"}.get(str(event.play_mode), str(event.play_mode))
        if _is_single_active_mode(self._play_mode):
            mode_hint = "OneShot 下只能保留一个 Active；切换时会自动取消其他绑定的 Active。"
        else:
            mode_hint = "当前模式允许多个 Active；新追加的已启用绑定默认都会进入 Active。"
        self.title_label.setText(f"事件 {label} 的 Audio 源音频绑定")
        self.detail_label.setText(
            f"Audio 模式 {play_mode_label} | {_binding_rollup_text(self._play_mode, list(event.clips))}。{mode_hint}"
        )
        self.drop_title_label.setText(f"拖入即可追加到事件 {event.id} 的 Audio")
        self.drop_detail_label.setText("支持从左侧源音频树单选或多选后直接拖入；重复绑定会自动跳过。")
        self.set_status_message(status_message)
        self._clear_binding_cards()
        if _is_single_active_mode(self._play_mode):
            self._binding_group = QButtonGroup(self)
            self._binding_group.setExclusive(True)
        else:
            self._binding_group = None

        has_bindings = bool(event.clips)
        self.empty_state_label.setVisible(not has_bindings)
        self.scroll_area.setVisible(has_bindings)
        if not has_bindings:
            return

        for clip in event.clips:
            self.bindings_layout.addWidget(self._build_binding_card(clip))
        self.bindings_layout.addStretch(1)

    def set_status_message(self, message: str) -> None:
        normalized = str(message).strip()
        self.status_label.setVisible(bool(normalized))
        self.status_label.setText(normalized)
        self.status_label.setToolTip(normalized)

    def show_at(self, global_pos: QPoint) -> None:
        self.adjustSize()
        target = QPoint(global_pos)
        popup_size = self.sizeHint()
        screen = QApplication.screenAt(global_pos)
        if screen is not None:
            available = screen.availableGeometry()
            target.setX(max(available.left(), min(target.x(), available.right() - popup_size.width())))
            target.setY(max(available.top(), min(target.y(), available.bottom() - popup_size.height())))
        self.move(target)
        self.show()
        self.raise_()
        self.activateWindow()

    def _emit_source_asset_drop(self, source_paths: list[str]) -> None:
        if self._event_id and source_paths:
            self.sourceAssetsDropped.emit(self._event_id, list(source_paths))

    def _clear_binding_cards(self) -> None:
        while self.bindings_layout.count():
            item = self.bindings_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_binding_card(self, clip: ClipModel) -> QFrame:
        source_name = os.path.basename(clip.source_path) or clip.asset_key or clip.id
        state_key = _binding_state_key(self._play_mode, clip)
        state_label = _binding_state_label(self._play_mode, clip)

        card = QFrame(self.bindings_container)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setFrameShadow(QFrame.Shadow.Raised)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        name_label = QLabel(source_name)
        name_label.setProperty("role", "workspaceSectionTitle")
        state_chip = QLabel(state_label)
        locate_button = QToolButton(card)
        locate_button.setText("定位")
        locate_icon = load_app_icon("open_project")
        if not locate_icon.isNull():
            locate_button.setIcon(locate_icon)
        locate_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        locate_button.setAutoRaise(True)
        locate_button.setToolTip("在源音频树中定位该源文件")
        locate_button.clicked.connect(lambda _checked=False, path=clip.source_path: self.locateSourceRequested.emit(path))
        header_row.addWidget(name_label, 1)
        header_row.addWidget(state_chip)
        header_row.addWidget(locate_button)

        state_detail_label = QLabel(f"Enabled {'开' if bool(clip.enabled) else '关'} | Active {'是' if bool(clip.active) else '否'}")
        state_detail_label.setWordWrap(True)
        meta_label = QLabel(f"Clip ID {clip.id} | 资源键 {clip.asset_key or '-'}")
        meta_label.setWordWrap(True)
        path_label = QLabel(clip.source_path or "未记录源路径")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        _apply_binding_card_style(card, state_chip, name_label, [state_detail_label, meta_label], path_label, state_key)

        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(12)
        enabled_check = QCheckBox("Enabled", card)
        enabled_check.setChecked(bool(clip.enabled))
        if _is_single_active_mode(self._play_mode):
            active_control: QAbstractButton = QRadioButton("Active", card)
            if self._binding_group is not None:
                self._binding_group.addButton(active_control)
        else:
            active_control = QCheckBox("Active", card)
        active_control.setChecked(bool(clip.active))
        enabled_check.toggled.connect(
            lambda checked, clip_id=clip.id: self.bindingEnabledChanged.emit(self._event_id, clip_id, bool(checked))
        )
        active_control.toggled.connect(
            lambda checked, clip_id=clip.id, checkbox=enabled_check: self._handle_active_toggled(clip_id, bool(checked), checkbox)
        )
        control_row.addWidget(enabled_check)
        control_row.addWidget(active_control)
        control_row.addStretch(1)

        card_layout.addLayout(header_row)
        card_layout.addWidget(state_detail_label)
        card_layout.addWidget(meta_label)
        card_layout.addWidget(path_label)
        card_layout.addLayout(control_row)
        return card

    def _handle_active_toggled(self, clip_id: str, checked: bool, enabled_check: QCheckBox) -> None:
        if not self._event_id:
            return

        if checked and not enabled_check.isChecked():
            enabled_check.setChecked(True)

        if _is_single_active_mode(self._play_mode) and not checked:
            return

        self.bindingActiveChanged.emit(self._event_id, clip_id, bool(checked))


class MainWindow(QMainWindow):
    eventPropertiesChanged = Signal()
    audioPropertiesChanged = Signal()
    projectSettingsChanged = Signal()
    gameSyncChanged = Signal()
    previewGameSyncChanged = Signal()
    previewBusSelectionChanged = Signal()
    previewBusStateChanged = Signal()
    logAppended = Signal(str)
    diagnosticContextChanged = Signal()
    validationReportUpdated = Signal(object)
    buildStatusUpdated = Signal(str, str)
    loudnessReportUpdated = Signal(str)
    createFolderRequested = Signal()
    createEventRequested = Signal()
    renameSelectedRequested = Signal()
    deleteSelectedRequested = Signal()
    saveProjectAsRequested = Signal()
    undoRequested = Signal()
    redoRequested = Signal()
    previewRequested = Signal()
    previewTransportPlayRequested = Signal()
    pausePreviewRequested = Signal()
    resumePreviewRequested = Signal()
    restartPreviewRequested = Signal()
    stopPreviewEventRequested = Signal()
    stopPreviewBusRequested = Signal()
    importClipsRequested = Signal(list)
    removeClipsRequested = Signal(list)
    assignSourceAssetsToCurrentAudioRequested = Signal(list, bool)
    assignSourceAssetsToAudioRequested = Signal(str, list, bool)
    removeSourceAssetsFromCurrentAudioRequested = Signal(list)
    removeSourceAssetsFromRegistryRequested = Signal(list)
    deleteSourceFilesRequested = Signal(list)
    audioSourceBindingEnabledChangedRequested = Signal(str, str, bool)
    audioSourceBindingActiveChangedRequested = Signal(str, str, bool)
    bulkWeightRequested = Signal(int)
    batchRenameRequested = Signal(str, int)
    bulkClipPropertiesRequested = Signal(dict)
    sortClipsRequested = Signal(str, bool)
    reorderClipsRequested = Signal(list)
    previewExportDiffRequested = Signal()
    loudnessScanRequested = Signal()
    openRecentProjectRequested = Signal(str)
    navigateParentRequested = Signal()
    applyDefaultBusToAllRequested = Signal()
    bulkEventBusRequested = Signal(str)
    clipEdited = Signal(str, str, str)
    buildRequested = Signal()
    previewClipRequested = Signal(str)
    previewClipSegmentRequested = Signal(str, int, int)
    importAudioAsEventsRequested = Signal(list, object, dict)
    reportTargetRequested = Signal(str, str)
    openAudioBindingsForAudioRequested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(load_app_icon("app"))
        self._audio_bindings_popup: AudioBindingsPopup | None = None
        self._audio_source_binding_feedback_event_id = ""
        self._audio_source_binding_feedback_message = ""
        self._loading_event = False
        self._close_handler = None
        self._ui_scale = 1.0
        self._compact_report_panel_height = 56
        self._default_workspace_splitter_sizes = [1144, self._compact_report_panel_height]
        self._default_main_splitter_sizes = [286, 1414]
        self._default_content_top_splitter_sizes = [700, 360]
        self._default_focus_content_splitter_sizes = [760, 320]
        self._minimum_report_panel_height = self._compact_report_panel_height
        self._last_docked_main_splitter_sizes = list(self._default_main_splitter_sizes)
        self._last_expanded_report_panel_height = 220
        self._pending_workspace_splitter_sizes: list[int] | None = None
        self._pending_main_splitter_sizes: list[int] | None = None
        self._pending_content_top_splitter_sizes: list[int] | None = None
        self._pending_named_splitter_sizes: dict[str, list[int]] = {}
        self._pending_layout_flush = False
        self._responsive_two_column_splitters: list[QSplitter] = []
        self._two_column_compact_breakpoint = 780
        self._content_top_medium_breakpoint = 880
        self._content_top_wide_breakpoint = 1100
        self._clip_detail_medium_breakpoint = 480
        self._clip_detail_wide_breakpoint = 620
        self._clip_editor_layout_mode = ""
        self._build_status_summary_override: str | None = None
        self._build_status_detail_override: str | None = None
        self._project_settings_change_source = ""
        self._closing_main_window = False
        self._loading_clip_details = False
        self._preview_transport_state = "idle"
        self._preview_transport_has_target = False
        self._preview_transport_can_replay = False
        self._preview_transport_expansion_pinned: bool | None = None
        self._preview_transport_details_expanded = False
        self._preview_transport_compact_min_width = 248
        self._preview_transport_compact_max_width = 320
        self._preview_transport_expanded_min_width = 312
        self._preview_transport_expanded_max_width = 420
        self._clip_lookup: dict[str, object] = {}
        self._project_bus_configs: list[dict[str, object]] = []
        self._active_project_bus_name = ""
        self._active_event_id: str | None = None
        self._active_audio_id: str | None = None
        self._loading_project_bus_details = False
        self._project_bus_selection_overridden = False
        self._syncing_project_bus_selection = False
        self._explorer_detached = False
        self._active_workspace_mode = "home"
        self._event_import_template_defaults = {
            "bus_name": "",
            "asset_prefix": "",
            "tags": [],
        }
        self._source_browser_entries: list[dict[str, object]] = []
        self._audio_browser_entries: list[dict[str, object]] = []
        self._gamesync_entries: dict[str, list[dict[str, object]]] = {
            "game_parameters": [],
            "state_groups": [],
            "switch_groups": [],
        }
        self._loading_gamesync = False
        self._gamesync_models: dict[str, list[dict[str, object]]] = {
            "game_parameters": [],
            "state_groups": [],
            "switch_groups": [],
        }
        self._event_rtpc_bindings: list[dict[str, object]] = []
        self._event_state_overrides: list[dict[str, object]] = []
        self._event_switch_variants: list[dict[str, object]] = []
        self._current_event_source_paths: list[str] = []

        self._apply_adaptive_top_level_defaults(self, DEFAULT_WINDOW_SIZE, (1180, 760))

        self._init_widgets()
        self._build_ui()
        self._bind_internal_signals()
        self._bind_shortcuts()
        self._apply_wwise_style()

    def _init_widgets(self) -> None:
        """Create all workspace widgets."""

        self.tree = EventTreeWidget()
        self.tree_filter_edit = QLineEdit()
        self.tree_filter_edit.setPlaceholderText("搜索当前浏览页")
        self.explorer_tabs = QTabWidget()
        self.gamesync_browser_tabs = QTabWidget()
        self.object_type_label = QLabel("Event")
        self.object_name_label = QLabel("未选择对象")
        self.object_scope_label = QLabel("Project / Root")
        self.object_stats_label = QLabel("片段 0 | 标签 0")
        self.object_summary_primary_label = QLabel(f"模式 - | {WWISE_OUTPUT_BUS_LABEL} -")
        self.object_summary_secondary_label = QLabel("生成 - | 来源 -")
        self.object_event_bus_chip = QLabel(f"{WWISE_OUTPUT_BUS_LABEL} -")
        self.object_bus_browser_chip = QLabel(f"{WWISE_BUS_VIEW_LABEL} -")
        self.object_context_hint_label = QLabel("当前浏览与编辑状态会在这里显示。")
        self.object_parent_button = QToolButton()
        self.object_preview_button = QPushButton("试听对象")
        self.object_contents_button = QPushButton("片段列表")
        self.object_follow_bus_button = QPushButton(f"跟随 {WWISE_OUTPUT_BUS_LABEL}")
        self.object_report_button = QPushButton("问题中心")
        self.reference_parent_value_button = QToolButton()
        self.reference_bus_value_button = QToolButton()
        self.reference_assets_value_button = QToolButton()
        self.reference_generation_value_button = QToolButton()
        self.reference_work_unit_label = QLabel("Work Unit：-")
        self.reference_output_label = QLabel("输出：-")
        self.event_id_edit = QLineEdit()
        self.display_name_edit = QLineEdit()
        self.bus_combo = QComboBox()
        self.bus_combo.addItems(DEFAULT_BUSES)
        self.play_mode_combo = QComboBox()
        for label, value in [("单次播放", "OneShot"), ("Random", "Random"), ("Sequence", "Sequence"), ("Combo", "Combo")]:
            self.play_mode_combo.addItem(label, value)
        self.steal_policy_combo = QComboBox()
        self.steal_policy_combo.addItems(["RejectNew", "StopOldest"])
        self.steal_policy_combo.setToolTip("当前只实现 RejectNew 和 StopOldest；StopQuietest 已从一期界面移除。")
        self.load_policy_combo = QComboBox()
        self.load_policy_combo.addItems(["OnDemand"])
        self.load_policy_combo.setEnabled(False)
        self.load_policy_combo.setToolTip("一期运行时固定按 OnDemand 工作，Preload/Stream 暂未开放。")
        self.source_audio_format_combo = QComboBox()
        self.source_audio_format_combo.addItems(["wav", "ogg"])
        self.runtime_audio_format_combo = QComboBox()
        self.runtime_audio_format_combo.addItems(["ogg", "wav"])
        self.default_bus_combo = QComboBox()
        self.default_bus_combo.addItems(DEFAULT_BUSES)
        self.auto_assign_bus_by_name_check = QCheckBox("根据事件命名智能分配总线")
        self.auto_assign_bus_by_name_check.setToolTip("开启后，新建事件和拖拽导入事件会按事件名中的 UI / BGM 等关键词优先匹配总线。")
        self.inline_bus_new_button = QPushButton("新建并分配")
        self.inline_bus_set_default_button = QPushButton(f"设为 {WWISE_DEFAULT_BUS_LABEL}")
        self.inline_bus_to_master_button = QPushButton(f"挂回 {WWISE_MASTER_AUDIO_BUS_TITLE}")
        self.inline_bus_open_parent_button = QPushButton(f"切到 {WWISE_PARENT_BUS_LABEL}")
        self.inline_bus_header = QFrame()
        self.inline_bus_name_chip = QLabel("Bus -")
        self.inline_bus_parent_chip = QLabel(f"{WWISE_PARENT_BUS_LABEL} -")
        self.inline_bus_default_chip = QLabel(f"{WWISE_DEFAULT_BUS_LABEL} -")
        self.inline_bus_export_chip = QLabel("导出 -")
        self.project_bus_list = ProjectBusTreeWidget()
        self.source_tree = SourceTreeWidget(selection_mode=QAbstractItemView.SelectionMode.MultiSelection)
        self.audio_tree = AudioTreeWidget()
        self.source_browser_filter_combo = QComboBox()
        self.source_browser_filter_combo.addItem("全部状态", "all")
        self.source_browser_filter_combo.addItem("文件缺失", "missing")
        self.source_browser_filter_combo.addItem("未被引用", "unreferenced")
        self.source_browser_filter_combo.addItem("多 Audio 复用", "reused")
        self.source_browser_filter_combo.addItem("当前 Audio 已绑定", "current_event")
        self.source_browser_filter_combo.addItem("当前 Audio 未绑定", "not_current_event")
        self.source_browser_filter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source_browser_filter_combo.setMinimumContentsLength(8)
        self.project_bus_add_button = QPushButton("新建 Bus")
        self.project_bus_remove_button = QPushButton("删除 Bus")
        self.source_browser_locate_button = QPushButton("定位源文件")
        self.source_browser_copy_button = QPushButton("复制源路径")
        self.source_browser_locate_event_button = QPushButton("定位引用 Audio")
        self.source_browser_add_to_event_button = QPushButton("追加到 Audio")
        self.audio_browser_locate_event_button = QPushButton("定位引用 Event")
        self.audio_browser_open_bindings_button = QPushButton("打开 Audio 绑定")
        self.project_bus_browser_button = QPushButton("切到总线树")
        self.project_bus_name_edit = QLineEdit()
        self.project_bus_name_edit.setPlaceholderText("Music")
        self.project_bus_parent_combo = QComboBox()
        self.project_bus_volume_spin = QDoubleSpinBox()
        self.project_bus_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.project_bus_volume_spin.setDecimals(1)
        self.project_bus_volume_spin.setSingleStep(0.5)
        self.project_bus_volume_spin.setSuffix(" dB")
        self.project_bus_mute_check = QCheckBox("导出时静音")
        self.project_bus_count_label = QLabel("Bus 0 条")
        self.project_bus_default_label = QLabel(f"{WWISE_DEFAULT_BUS_LABEL}: -")
        self.project_bus_export_label = QLabel("未选择 Bus")
        self.project_bus_route_label = QLabel("未选择 Bus")
        self.project_bus_route_bar = QWidget()
        self.project_bus_children_label = QLabel(f"{WWISE_CHILD_BUSES_LABEL}: -")
        self.project_bus_effective_value = QLabel("0%")
        self.project_bus_effective_bar = QProgressBar()
        self.project_bus_effective_bar.setRange(0, 100)
        self.project_bus_summary_label = QLabel("在左侧选择 Bus 后，可在属性编辑器中直接编辑当前 Bus。")
        self.project_bus_summary_label.setWordWrap(True)
        self.source_browser_summary_label = QLabel("源音频树会按路径展示工程中的源文件，并标记 Audio 引用、缺失和未引用状态。")
        self.source_browser_summary_label.setWordWrap(True)
        self.source_browser_status_label = QLabel("当前没有源音频。")
        self.source_browser_status_label.setWordWrap(True)
        self.audio_browser_summary_label = QLabel("Audio 树展示项目级 Audio Object，并聚合它们引用的 Event、Bus 和片段数量。")
        self.audio_browser_summary_label.setWordWrap(True)
        self.audio_browser_status_label = QLabel("当前没有 Audio Object。")
        self.audio_browser_status_label.setWordWrap(True)
        self.gamesync_browser_summary_label = QLabel("GameSync 浏览页会汇总项目级 RTPC、State Group 和 Switch Group。")
        self.gamesync_browser_summary_label.setWordWrap(True)
        self.gamesync_browser_status_label = QLabel("当前还没有任何 GameSync 定义。")
        self.gamesync_browser_status_label.setWordWrap(True)
        self.gamesync_parameter_browser_list = QListWidget()
        self.gamesync_state_browser_list = QListWidget()
        self.gamesync_switch_browser_list = QListWidget()
        self.gamesync_parameter_browser_detail_label = QLabel("当前还没有 Game Parameter。")
        self.gamesync_state_browser_detail_label = QLabel("当前还没有 State Group。")
        self.gamesync_switch_browser_detail_label = QLabel("当前还没有 Switch Group。")
        self.gamesync_parameter_add_button = QPushButton("新建参数")
        self.gamesync_parameter_remove_button = QPushButton("删除参数")
        self.gamesync_parameter_name_edit = QLineEdit()
        self.gamesync_parameter_default_spin = QDoubleSpinBox()
        self.gamesync_parameter_default_spin.setRange(-99999.0, 99999.0)
        self.gamesync_parameter_default_spin.setDecimals(2)
        self.gamesync_parameter_min_spin = QDoubleSpinBox()
        self.gamesync_parameter_min_spin.setRange(-99999.0, 99999.0)
        self.gamesync_parameter_min_spin.setDecimals(2)
        self.gamesync_parameter_max_spin = QDoubleSpinBox()
        self.gamesync_parameter_max_spin.setRange(-99999.0, 99999.0)
        self.gamesync_parameter_max_spin.setDecimals(2)
        self.gamesync_parameter_notes_edit = QPlainTextEdit()
        self.gamesync_parameter_notes_edit.setPlaceholderText("用法说明、范围约束、运行时映射")
        self.gamesync_state_add_button = QPushButton("新建 State Group")
        self.gamesync_state_remove_button = QPushButton("删除 State Group")
        self.gamesync_state_name_edit = QLineEdit()
        self.gamesync_state_value_list = QListWidget()
        self.gamesync_state_value_add_button = QPushButton("新增 State")
        self.gamesync_state_value_remove_button = QPushButton("删除 State")
        self.gamesync_state_values_edit = QLineEdit()
        self.gamesync_state_values_edit.setPlaceholderText("State 名称，例如 Completed")
        self.gamesync_state_value_volume_spin = QDoubleSpinBox()
        self.gamesync_state_value_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.gamesync_state_value_volume_spin.setDecimals(1)
        self.gamesync_state_value_volume_spin.setSuffix(" dB")
        self.gamesync_state_value_pitch_spin = QSpinBox()
        self.gamesync_state_value_pitch_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.gamesync_state_value_mute_check = QCheckBox("该 State 静音")
        self.gamesync_state_value_notes_edit = QPlainTextEdit()
        self.gamesync_state_value_notes_edit.setPlaceholderText("记录该 State 的音量、音高或场景语义")
        self.gamesync_state_default_edit = QLineEdit()
        self.gamesync_state_notes_edit = QPlainTextEdit()
        self.gamesync_state_notes_edit.setPlaceholderText("描述该组 State 的用途")
        self.gamesync_switch_add_button = QPushButton("新建 Switch Group")
        self.gamesync_switch_remove_button = QPushButton("删除 Switch Group")
        self.gamesync_switch_name_edit = QLineEdit()
        self.gamesync_switch_value_list = QListWidget()
        self.gamesync_switch_value_add_button = QPushButton("新增 Switch")
        self.gamesync_switch_value_remove_button = QPushButton("删除 Switch")
        self.gamesync_switch_values_edit = QLineEdit()
        self.gamesync_switch_values_edit.setPlaceholderText("Switch 名称，例如 Stone")
        self.gamesync_switch_value_volume_spin = QDoubleSpinBox()
        self.gamesync_switch_value_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.gamesync_switch_value_volume_spin.setDecimals(1)
        self.gamesync_switch_value_volume_spin.setSuffix(" dB")
        self.gamesync_switch_value_pitch_spin = QSpinBox()
        self.gamesync_switch_value_pitch_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.gamesync_switch_value_mute_check = QCheckBox("该 Switch 静音")
        self.gamesync_switch_value_notes_edit = QPlainTextEdit()
        self.gamesync_switch_value_notes_edit.setPlaceholderText("记录该 Switch 的音量、音高或场景语义")
        self.gamesync_switch_default_edit = QLineEdit()
        self.gamesync_switch_use_rtpc_check = QCheckBox("使用 Game Parameter 映射")
        self.gamesync_switch_mapped_parameter_edit = QLineEdit()
        self.gamesync_switch_mapped_parameter_edit.setPlaceholderText("SurfaceBlend")
        self.gamesync_switch_notes_edit = QPlainTextEdit()
        self.gamesync_switch_notes_edit.setPlaceholderText("记录 emitter 作用域或映射规则")
        self.event_source_binding_summary_label = QLabel("当前 Audio 还没有绑定源音频。")
        self.event_source_binding_summary_label.setWordWrap(True)
        self.event_source_binding_detail_label = QLabel("这里现在只展示当前 Audio 的绑定摘要。需要追加源音频或切换 Active / Enabled，请在 Audio 树中定位当前对象后打开 Audio 绑定。")
        self.event_source_binding_detail_label.setProperty("role", "workspaceSectionSummary")
        self.event_source_binding_detail_label.setWordWrap(True)
        self.event_source_binding_overview_scroll = QScrollArea()
        self.event_source_binding_overview_scroll.setWidgetResizable(True)
        self.event_source_binding_overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.event_source_binding_overview_scroll.setMinimumHeight(180)
        self.event_source_binding_overview_scroll.setMaximumHeight(320)
        self.event_source_binding_overview_container = QWidget(self.event_source_binding_overview_scroll)
        self.event_source_binding_overview_layout = QVBoxLayout(self.event_source_binding_overview_container)
        self.event_source_binding_overview_layout.setContentsMargins(0, 0, 0, 0)
        self.event_source_binding_overview_layout.setSpacing(8)
        self.event_source_binding_overview_scroll.setWidget(self.event_source_binding_overview_container)
        self.event_source_binding_empty_label = QLabel("当前 Audio 还没有绑定源音频。")
        self.event_source_binding_empty_label.setProperty("role", "workspaceSectionSummary")
        self.event_source_binding_empty_label.setWordWrap(True)
        self.project_bus_focus_audio_button = QPushButton("在属性编辑器中编辑当前 Bus")
        self.project_master_summary_label = QLabel("Master")
        self.project_master_volume_spin = QDoubleSpinBox()
        self.project_master_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.project_master_volume_spin.setDecimals(1)
        self.project_master_volume_spin.setSingleStep(0.5)
        self.project_master_volume_spin.setSuffix(" dB")
        self.project_master_mute_check = QCheckBox("导出时静音")
        self.project_master_effective_value = QLabel("100%")
        self.project_master_effective_bar = QProgressBar()
        self.project_master_effective_bar.setRange(0, 100)
        self.project_master_hint_label = QLabel("主 Bus 会作为正式工程 Bus 一起保存和导出；试听总控仍可在下方传输控制面板中单独调整。")
        self.event_rtpc_list = QListWidget()
        self.event_rtpc_add_button = QPushButton("新增 RTPC")
        self.event_rtpc_remove_button = QPushButton("删除 RTPC")
        self.event_rtpc_parameter_edit = QComboBox()
        self.event_rtpc_target_combo = QComboBox()
        self.event_rtpc_target_combo.addItems(["EventVolumeDb", "EventPitchCents"])
        self.event_rtpc_scope_combo = QComboBox()
        self.event_rtpc_scope_combo.addItems(["Global", "Emitter"])
        self.event_rtpc_curve_table = self._create_curve_table()
        self.event_rtpc_interpolation_combo = QComboBox()
        self.event_rtpc_interpolation_combo.addItems(["Linear", "Constant"])
        self.event_rtpc_add_point_button = QPushButton("新增曲线点")
        self.event_rtpc_remove_point_button = QPushButton("删除曲线点")
        self.event_rtpc_selected_input_spin = QDoubleSpinBox()
        self.event_rtpc_selected_input_spin.setRange(-99999.0, 99999.0)
        self.event_rtpc_selected_input_spin.setDecimals(2)
        self.event_rtpc_selected_output_spin = QDoubleSpinBox()
        self.event_rtpc_selected_output_spin.setRange(-99999.0, 99999.0)
        self.event_rtpc_selected_output_spin.setDecimals(2)
        self.event_rtpc_snap_check = QCheckBox("拖拽吸附")
        self.event_rtpc_snap_x_spin = QDoubleSpinBox()
        self.event_rtpc_snap_x_spin.setRange(0.01, 99999.0)
        self.event_rtpc_snap_x_spin.setDecimals(2)
        self.event_rtpc_snap_x_spin.setValue(1.0)
        self.event_rtpc_snap_y_spin = QDoubleSpinBox()
        self.event_rtpc_snap_y_spin.setRange(0.01, 99999.0)
        self.event_rtpc_snap_y_spin.setDecimals(2)
        self.event_rtpc_snap_y_spin.setValue(1.0)
        self.event_rtpc_notes_edit = QPlainTextEdit()
        self.event_rtpc_notes_edit.setPlaceholderText("记录驱动对象、取值说明或设计约束")
        self.event_state_list = QListWidget()
        self.event_state_add_button = QPushButton("新增 State Override")
        self.event_state_remove_button = QPushButton("删除 State Override")
        self.event_state_group_edit = QComboBox()
        self.event_state_name_edit = QComboBox()
        self.event_state_volume_spin = QDoubleSpinBox()
        self.event_state_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.event_state_volume_spin.setDecimals(1)
        self.event_state_volume_spin.setSuffix(" dB")
        self.event_state_pitch_spin = QSpinBox()
        self.event_state_pitch_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.event_state_mute_check = QCheckBox("切到该 State 时静音")
        self.event_state_notes_edit = QPlainTextEdit()
        self.event_state_notes_edit.setPlaceholderText("记录覆盖原因或目标场景")
        self.event_switch_list = QListWidget()
        self.event_switch_add_button = QPushButton("新增 Switch Variant")
        self.event_switch_remove_button = QPushButton("删除 Switch Variant")
        self.event_switch_group_edit = QComboBox()
        self.event_switch_name_edit = QComboBox()
        self.event_switch_clip_ids_edit = QLineEdit()
        self.event_switch_clip_ids_edit.setPlaceholderText("clip_a, clip_b")
        self.event_switch_notes_edit = QPlainTextEdit()
        self.event_switch_notes_edit.setPlaceholderText("记录该变体关联的源音频或层级规则")
        self.bus_rtpc_list = QListWidget()
        self.bus_rtpc_add_button = QPushButton("新增 RTPC")
        self.bus_rtpc_remove_button = QPushButton("删除 RTPC")
        self.bus_rtpc_parameter_edit = QLineEdit()
        self.bus_rtpc_parameter_edit.setPlaceholderText("CombatIntensity")
        self.bus_rtpc_target_combo = QComboBox()
        self.bus_rtpc_target_combo.addItems(["BusVolumeDb"])
        self.bus_rtpc_scope_combo = QComboBox()
        self.bus_rtpc_scope_combo.addItems(["Global", "Emitter"])
        self.bus_rtpc_curve_table = self._create_curve_table()
        self.bus_rtpc_interpolation_combo = QComboBox()
        self.bus_rtpc_interpolation_combo.addItems(["Linear", "Constant"])
        self.bus_rtpc_add_point_button = QPushButton("新增曲线点")
        self.bus_rtpc_remove_point_button = QPushButton("删除曲线点")
        self.bus_rtpc_selected_input_spin = QDoubleSpinBox()
        self.bus_rtpc_selected_input_spin.setRange(-99999.0, 99999.0)
        self.bus_rtpc_selected_input_spin.setDecimals(2)
        self.bus_rtpc_selected_output_spin = QDoubleSpinBox()
        self.bus_rtpc_selected_output_spin.setRange(-99999.0, 99999.0)
        self.bus_rtpc_selected_output_spin.setDecimals(2)
        self.bus_rtpc_snap_check = QCheckBox("拖拽吸附")
        self.bus_rtpc_snap_x_spin = QDoubleSpinBox()
        self.bus_rtpc_snap_x_spin.setRange(0.01, 99999.0)
        self.bus_rtpc_snap_x_spin.setDecimals(2)
        self.bus_rtpc_snap_x_spin.setValue(1.0)
        self.bus_rtpc_snap_y_spin = QDoubleSpinBox()
        self.bus_rtpc_snap_y_spin.setRange(0.01, 99999.0)
        self.bus_rtpc_snap_y_spin.setDecimals(2)
        self.bus_rtpc_snap_y_spin.setValue(1.0)
        self.bus_rtpc_notes_edit = QPlainTextEdit()
        self.bus_rtpc_notes_edit.setPlaceholderText("记录混音目标或调制范围")
        self.bus_state_list = QListWidget()
        self.bus_state_add_button = QPushButton("新增 State Override")
        self.bus_state_remove_button = QPushButton("删除 State Override")
        self.bus_state_group_edit = QLineEdit()
        self.bus_state_group_edit.setPlaceholderText("MusicState")
        self.bus_state_name_edit = QLineEdit()
        self.bus_state_name_edit.setPlaceholderText("Stealth")
        self.bus_state_volume_spin = QDoubleSpinBox()
        self.bus_state_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.bus_state_volume_spin.setDecimals(1)
        self.bus_state_volume_spin.setSuffix(" dB")
        self.bus_state_pitch_spin = QSpinBox()
        self.bus_state_pitch_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.bus_state_mute_check = QCheckBox("切到该 State 时静音")
        self.bus_state_notes_edit = QPlainTextEdit()
        self.bus_state_notes_edit.setPlaceholderText("记录总线状态覆盖的使用场景")
        self.preview_bus_combo = QComboBox()
        self.preview_bus_volume_spin = QDoubleSpinBox()
        self.preview_bus_volume_spin.setRange(0.0, 100.0)
        self.preview_bus_volume_spin.setDecimals(0)
        self.preview_bus_volume_spin.setSuffix(" %")
        self.preview_bus_mute_check = QCheckBox("静音")
        self.preview_bus_effective_label = QLabel(f"{WWISE_EFFECTIVE_OUTPUT_LABEL}: 100%")
        self._preview_gamesync_loading = False
        self._preview_gamesync_definitions: dict[str, list[dict[str, object]]] = {
            "game_parameters": [],
            "state_groups": [],
            "switch_groups": [],
        }
        self._preview_gamesync_state: dict[str, object] = {
            "selected_parameter_name": "",
            "selected_parameter_scope": "Emitter",
            "global_parameters": {},
            "emitter_parameters": {},
            "selected_state_group": "",
            "states": {},
            "selected_switch_group": "",
            "switches": {},
        }
        self.preview_gamesync_group = QGroupBox()
        self.preview_gamesync_group.setTitle("")
        self.preview_gamesync_group.setProperty("role", "inlineRecentPreview")
        self.preview_gamesync_label = QLabel("试听 GameSync")
        self.preview_rtpc_transport_frame = QFrame()
        self.preview_rtpc_transport_frame.setObjectName("PreviewRtpcTransportFrame")
        self.preview_gamesync_modes_frame = QFrame()
        self.preview_gamesync_modes_frame.setObjectName("PreviewGameSyncModesFrame")
        self.preview_parameter_section_label = QLabel("RTPC")
        self.preview_parameter_name_combo = QComboBox()
        self.preview_parameter_scope_combo = QComboBox()
        self.preview_parameter_scope_combo.addItems(["Global", "Emitter"])
        self.preview_parameter_current_label = QLabel("0")
        self.preview_parameter_source_chip = QLabel("Default")
        self.preview_parameter_min_label = QLabel("0")
        self.preview_parameter_max_label = QLabel("0")
        self.preview_parameter_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_parameter_slider.setRange(0, 1000)
        self.preview_parameter_slider.setSingleStep(1)
        self.preview_parameter_slider.setPageStep(50)
        self.preview_parameter_slider.setTracking(False)
        self.preview_parameter_value_spin = QDoubleSpinBox()
        self.preview_parameter_value_spin.setRange(-99999.0, 99999.0)
        self.preview_parameter_value_spin.setDecimals(2)
        self.preview_parameter_value_spin.setKeyboardTracking(False)
        self.preview_state_section_label = QLabel("State")
        self.preview_state_group_combo = QComboBox()
        self.preview_state_name_combo = QComboBox()
        self.preview_state_scope_chip = QLabel("Global")
        self.preview_switch_section_label = QLabel("Switch")
        self.preview_switch_group_combo = QComboBox()
        self.preview_switch_name_combo = QComboBox()
        self.preview_switch_source_chip = QLabel("Default")
        self.preview_switch_parameter_source_chip = QLabel("参数 -")
        self.preview_gamesync_summary_label = QLabel("当前没有额外的 GameSync 覆盖。")
        self.export_root_edit = QLineEdit()
        self.export_root_edit.setPlaceholderText("./Export")
        self.export_root_browse_button = QPushButton("选择目录")
        self.buses_edit = QLineEdit()
        self.buses_edit.setPlaceholderText("BGM, SFX, UI")
        self.volume_spin = QDoubleSpinBox()
        self.volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.volume_rand_min_spin = QDoubleSpinBox()
        self.volume_rand_min_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.volume_rand_max_spin = QDoubleSpinBox()
        self.volume_rand_max_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.pitch_spin.setToolTip("本地试听中，基础音高会按保时长变调处理；升降音高时默认不改变片段长度。")
        self.pitch_rand_min_spin = QSpinBox()
        self.pitch_rand_min_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.pitch_rand_min_spin.setToolTip("本地试听中的随机音高同样按保时长变调处理。")
        self.pitch_rand_max_spin = QSpinBox()
        self.pitch_rand_max_spin.setRange(MIN_PITCH_CENTS, MAX_PITCH_CENTS)
        self.pitch_rand_max_spin.setToolTip("本地试听中的随机音高同样按保时长变调处理。")
        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(MIN_COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS)
        self.max_instances_spin = QSpinBox()
        self.max_instances_spin.setRange(MIN_MAX_INSTANCES, MAX_MAX_INSTANCES)
        self.combo_pitch_step_spin = QSpinBox()
        self.combo_pitch_step_spin.setRange(MIN_PITCH_CENTS // 100, MAX_PITCH_CENTS // 100)
        self.combo_pitch_step_spin.setSuffix(" 半音")
        self.combo_pitch_step_spin.setToolTip("连击每步按半音档位加音高；本地试听会尽量保持原始时长不变。")
        self.combo_reset_spin = QDoubleSpinBox()
        self.combo_reset_spin.setRange(MIN_COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS)
        self.combo_max_step_spin = QSpinBox()
        self.combo_max_step_spin.setRange(MIN_COMBO_MAX_STEP, MAX_COMBO_MAX_STEP)
        self.avoid_repeat_check = QCheckBox("避免连续重复")
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(100)
        self.notes_edit.setPlaceholderText("记录触发语义、使用场景或联调备注")
        self.event_audio_reference_label = QLabel("当前引用 Audio：-")
        self.event_audio_reference_label.setWordWrap(True)
        self.event_open_audio_workspace_button = QPushButton("切到 Audio 属性")
        self.event_locate_audio_browser_button = QPushButton("在 Audio 树中定位")
        self.tags_summary_edit = QLineEdit()
        self.tags_summary_edit.setPlaceholderText("ui, click, soft")

        self.clip_table = ClipTableWidget(0, 9)
        self.clip_table.setHorizontalHeaderLabels([
            "片段 ID",
            "源路径",
            "资源键",
            "权重",
            "起始裁剪",
            "结束裁剪",
            "循环起点",
            "循环终点",
            "标签",
        ])
        self.clip_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.clip_selected_label = QLabel("未选择片段")
        self.clip_asset_detail_edit = QLineEdit()
        self.clip_asset_detail_edit.setPlaceholderText("ui/click_01")
        self.clip_source_detail_edit = QLineEdit()
        self.clip_source_detail_edit.setPlaceholderText("C:/Audio/ui/click_01.wav")
        self.clip_weight_detail_spin = QSpinBox()
        self.clip_weight_detail_spin.setRange(MIN_CLIP_WEIGHT, MAX_CLIP_WEIGHT)
        self.clip_weight_detail_spin.setToolTip("相对权重，推荐 1-100；不需要所有片段加起来等于 100，0 不允许。")
        self.clip_weight_preset_combo = QComboBox()
        self._populate_weight_preset_combo(self.clip_weight_preset_combo)
        self.clip_weight_row = self._build_weight_editor(self.clip_weight_detail_spin, self.clip_weight_preset_combo)
        self.clip_trim_start_spin = QSpinBox()
        self.clip_trim_start_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_trim_start_spin.setToolTip("单位 ms。若源文件可读取，将自动按音频实际时长限制。")
        self.clip_trim_end_spin = QSpinBox()
        self.clip_trim_end_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_trim_end_spin.setToolTip("单位 ms。0 表示使用文件尾；若源文件可读取，将自动按音频实际时长限制。")
        self.clip_fade_in_spin = QSpinBox()
        self.clip_fade_in_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_fade_in_spin.setToolTip("单位 ms。控制当前裁剪区域的淡入长度。")
        self.clip_fade_out_spin = QSpinBox()
        self.clip_fade_out_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_fade_out_spin.setToolTip("单位 ms。控制当前裁剪区域的淡出长度。")
        self.clip_loop_start_spin = QSpinBox()
        self.clip_loop_start_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_loop_start_spin.setToolTip("单位 ms。若源文件可读取，将自动按音频实际时长限制。")
        self.clip_loop_end_spin = QSpinBox()
        self.clip_loop_end_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_loop_end_spin.setToolTip("单位 ms。0 表示不设循环终点；若源文件可读取，将自动按音频实际时长限制。")
        self.clip_tags_detail_edit = QLineEdit()
        self.clip_tags_detail_edit.setPlaceholderText("ui, click")
        self.clip_preview_hint_label = QLabel("选择片段后可在此精修裁剪、淡入淡出、循环和局部试听。")
        self.clip_preview_hint_label.setWordWrap(True)
        self.clip_preview_hint_label.setMaximumHeight(40)
        self.clip_preview_hint_label.setProperty("role", "clipPreviewHint")
        self.clip_waveform_editor = ClipWaveformEditor()
        self.clip_playhead_label = QLabel("游标 0 ms")
        self.clip_waveform_zoom_out_button = QPushButton("缩小")
        self.clip_waveform_zoom_reset_button = QPushButton("全段")
        self.clip_waveform_frame_selection_button = QPushButton("聚焦选区")
        self.clip_waveform_zoom_in_button = QPushButton("放大")
        self.clip_set_start_from_playhead_button = QPushButton("起点=游标")
        self.clip_set_end_from_playhead_button = QPushButton("终点=游标")
        self.clip_set_loop_from_selection_button = QPushButton("循环=选区")
        self.clip_clear_loop_button = QPushButton("清循环")
        self.clip_preview_button = QPushButton("试听片段")
        self.clip_preview_segment_button = QPushButton("试听局部")
        self.clip_copy_asset_key_button = QPushButton("复制资源键")
        self.clip_locate_source_button = QPushButton("定位源文件")
        for compact_button in [
            self.clip_waveform_zoom_out_button,
            self.clip_waveform_zoom_reset_button,
            self.clip_waveform_frame_selection_button,
            self.clip_waveform_zoom_in_button,
            self.clip_set_start_from_playhead_button,
            self.clip_set_end_from_playhead_button,
            self.clip_set_loop_from_selection_button,
            self.clip_clear_loop_button,
            self.clip_preview_button,
            self.clip_preview_segment_button,
            self.clip_copy_asset_key_button,
            self.clip_locate_source_button,
        ]:
            compact_button.setProperty("role", "clipCompactButton")
        self._clip_waveform_action_buttons = [
            self.clip_set_start_from_playhead_button,
            self.clip_set_end_from_playhead_button,
            self.clip_set_loop_from_selection_button,
            self.clip_clear_loop_button,
            self.clip_waveform_zoom_out_button,
            self.clip_waveform_zoom_reset_button,
            self.clip_waveform_frame_selection_button,
            self.clip_waveform_zoom_in_button,
        ]
        self._clip_detail_action_buttons = [
            self.clip_preview_button,
            self.clip_preview_segment_button,
            self.clip_copy_asset_key_button,
            self.clip_locate_source_button,
        ]
        for compact_spin in [
            self.clip_trim_start_spin,
            self.clip_trim_end_spin,
            self.clip_fade_in_spin,
            self.clip_fade_out_spin,
            self.clip_loop_start_spin,
            self.clip_loop_end_spin,
            self.clip_weight_detail_spin,
        ]:
            compact_spin.setProperty("role", "clipCompactSpin")
        self.clip_asset_detail_edit.setProperty("role", "clipCompactField")
        self.clip_source_detail_edit.setProperty("role", "clipCompactField")
        self.clip_tags_detail_edit.setProperty("role", "clipCompactField")
        self.build_preview_output = QPlainTextEdit()
        self.build_preview_output.setReadOnly(True)
        self.build_preview_output.setPlaceholderText("导出差异、构建摘要和交付文本会显示在这里。")
        self.resources_preview_output = QPlainTextEdit()
        self.resources_preview_output.setReadOnly(True)
        self.resources_preview_output.setPlaceholderText("当前没有可回看的导出预览。先执行差异预览或构建，再回到这里查看镜像内容。")
        self.resources_preview_output.setDocument(self.build_preview_output.document())
        self.audio_meter_context_label = QLabel("未执行试听")
        self.audio_meter_short_term_value = QLabel("-Inf")
        self.audio_meter_short_term_max_value = QLabel("-Inf")
        self.audio_meter_integrated_value = QLabel("-Inf")
        self.audio_meter_momentary_value = QLabel("-Inf")
        self.audio_meter_momentary_max_value = QLabel("-Inf")
        self.audio_meter_lra_value = QLabel("0.0")
        self.audio_meter_true_peak_value = QLabel("-Inf")
        self.audio_meter_left_peak_value = QLabel("-Inf")
        self.audio_meter_left_rms_value = QLabel("-Inf")
        self.audio_meter_right_peak_value = QLabel("-Inf")
        self.audio_meter_right_rms_value = QLabel("-Inf")
        self.audio_meter_left_bar = QProgressBar()
        self.audio_meter_right_bar = QProgressBar()
        self.audio_meter_summary_context_label = QLabel("未执行试听")
        self.audio_meter_summary_source_context_label = QLabel("未执行试听")
        self.audio_meter_summary_integrated_value = QLabel("-Inf")
        self.audio_meter_summary_true_peak_value = QLabel("-Inf")
        self.audio_meter_summary_source_integrated_value = QLabel("-Inf")
        self.audio_meter_summary_source_true_peak_value = QLabel("-Inf")
        self.preview_waveform_strip = ClipWaveformEditor()
        self.preview_inline_momentary_max_value = QLabel("-Inf")
        self.preview_transport_header = QFrame()
        self.preview_transport_title_label = QLabel("最近试听")
        self.preview_transport_status_chip = QLabel("待命")
        self.preview_transport_toggle_button = QToolButton()
        self.preview_transport_detail_label = QLabel("切换事件、资源或流程时，会保留最近一次试听会话。")
        self.preview_transport_frame = QFrame()
        self.preview_transport_metrics_frame = QFrame()
        self.preview_metric_source_context_label = QLabel("未执行试听")
        self.preview_metric_source_integrated_value = QLabel("-Inf")
        self.preview_metric_source_true_peak_value = QLabel("-Inf")
        self.preview_metric_context_label = QLabel("未执行试听")
        self.preview_metric_integrated_value = QLabel("-Inf")
        self.preview_metric_true_peak_value = QLabel("-Inf")
        self.preview_transport_play_button = QToolButton()
        self.preview_transport_pause_button = QToolButton()
        self.preview_transport_restart_button = QToolButton()
        self.preview_transport_stop_button = QToolButton()
        self.open_loudness_view_button = QToolButton()
        self.hold_peaks_check = QCheckBox("保持峰值")
        self.clear_meter_button = QPushButton("清零")
        self._held_true_peak_db: float | None = None
        self._held_left_peak_db: float | None = None
        self._held_right_peak_db: float | None = None
        self.momentary_plot = LoudnessHistoryPlot("Momentary Trace")
        self.short_term_plot = LoudnessHistoryPlot("Short-term Trace")

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("运行日志、导入反馈和交付链路输出会显示在这里。")
        self.validation_summary_label = QLabel("等待校验。")
        self.validation_filter_status_label = QLabel("显示全部校验问题。")
        self.validation_filter_severity_combo = QComboBox()
        self.validation_filter_severity_combo.addItems(["全部级别", "错误", "警告", "信息"])
        self.validation_filter_keyword_edit = QLineEdit()
        self.validation_filter_keyword_edit.setPlaceholderText("按代码、目标或消息过滤")
        self.validation_filter_reset_button = QPushButton("清空筛选")
        self.validation_revalidate_button = QPushButton("重新校验")
        self.validation_locate_button = QPushButton("定位当前问题")
        self.validation_issue_list = QListWidget()
        self.validation_report_output = QPlainTextEdit()
        self.validation_report_output.setReadOnly(True)
        self.validation_report_output.setPlaceholderText("选择左侧问题条目后，这里会显示详细说明与定位上下文。")
        self.build_summary_label = QLabel("等待构建或差异预览。")
        self.build_issue_list = QListWidget()
        self.build_report_output = QPlainTextEdit()
        self.build_report_output.setReadOnly(True)
        self.build_report_output.setPlaceholderText("构建摘要、产物说明和异常输出会显示在这里。")
        self.loudness_summary_label = QLabel("等待响度扫描。")
        self.loudness_issue_list = QListWidget()
        self.loudness_report_output = QPlainTextEdit()
        self.loudness_report_output.setReadOnly(True)
        self.loudness_report_output.setPlaceholderText("响度扫描完成后，这里会显示条目细节、阈值与超标说明。")
        self._latest_log_message = ""
        self.diagnostic_summary_label = QLabel("诊断概览已接入结果中心；等待新的日志、校验、构建或响度结果。")
        self.diagnostic_log_summary_label = QLabel("最近日志：等待运行输出。")
        self.diagnostic_validation_summary_label = QLabel(self.validation_summary_label.text())
        self.diagnostic_build_summary_label = QLabel(self.build_summary_label.text())
        self.diagnostic_loudness_summary_label = QLabel(self.loudness_summary_label.text())
        self.diagnostic_bus_summary_label = QLabel("等待 Bus 上下文。")
        self.diagnostic_section_list = QListWidget()
        self.diagnostic_section_detail_output = QPlainTextEdit()
        self.diagnostic_section_detail_output.setReadOnly(True)
        self.diagnostic_section_detail_output.setPlaceholderText("选择左侧诊断 section 后，这里会显示控制器收口后的 detail、定位目标和上下文。")
        self._diagnostic_snapshot_data = {
            "summary": self.diagnostic_summary_label.text(),
            "log_summary": self.diagnostic_log_summary_label.text(),
            "validation_summary": self.diagnostic_validation_summary_label.text(),
            "build_summary": self.diagnostic_build_summary_label.text(),
            "loudness_summary": self.diagnostic_loudness_summary_label.text(),
            "bus_summary": self.diagnostic_bus_summary_label.text(),
            "sections": [],
            "build_profile": [],
        }
        self.clip_filter_edit = QLineEdit()
        self.clip_filter_edit.setPlaceholderText("按片段 ID、源路径、资源键或标签过滤")
        self.bulk_clip_weight_spin = QSpinBox()
        self.bulk_clip_weight_spin.setRange(MIN_CLIP_WEIGHT, MAX_CLIP_WEIGHT)
        self.bulk_clip_weight_spin.setToolTip("批量设置相对权重，推荐 1-100；不需要总和等于 100。")
        self.bulk_weight_preset_combo = QComboBox()
        self._populate_weight_preset_combo(self.bulk_weight_preset_combo)
        self.bulk_clip_weight_row = self._build_weight_editor(self.bulk_clip_weight_spin, self.bulk_weight_preset_combo)
        self.bulk_clip_asset_prefix_edit = QLineEdit()
        self.bulk_clip_asset_prefix_edit.setPlaceholderText("ui/click")
        self.bulk_clip_tags_edit = QLineEdit()
        self.bulk_clip_tags_edit.setPlaceholderText("ui, click")
        self.apply_bulk_clip_button = QPushButton("应用到所选片段")
        self.sort_field_combo = QComboBox()
        self.sort_field_combo.addItems(["片段 ID", "资源键", "权重", "源路径"])
        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems(["升序", "降序"])
        self.sort_clips_button = QPushButton("排序")
        self.preview_export_diff_button = QPushButton("预览导出差异")
        self.build_scope_combo = QComboBox()
        self.build_scope_combo.addItem("增量构建（默认）", "incremental")
        self.build_scope_combo.addItem("全量构建", "full")
        self.build_scope_combo.addItem("选中构建", "selection")
        self.build_scope_target_label = QLabel("当前范围：整个工程")
        self.build_scope_target_label.setWordWrap(True)
        self.build_scope_hint_label = QLabel("默认只重建受影响音频资源，元数据文件会全量刷新。")
        self.build_scope_hint_label.setWordWrap(True)
        self.build_plan_summary_label = QLabel("尚未生成构建计划。")
        self.build_plan_summary_label.setWordWrap(True)
        self.build_plan_detail_label = QLabel("点击“预览导出差异”或执行构建后，这里会显示重建、复用和移除计划。")
        self.build_plan_detail_label.setWordWrap(True)
        self.build_profile_list = QListWidget()
        self.build_profile_list.setMaximumHeight(132)
        self.build_profile_detail_output = QPlainTextEdit()
        self.build_profile_detail_output.setReadOnly(True)
        self.build_profile_detail_output.setMaximumHeight(96)
        self.build_profile_detail_output.setPlaceholderText("最近一次构建画像会在这里展开范围、资源差异与交付目标。")
        self.loudness_scan_button = QPushButton("响度扫描")
        self.recent_projects_combo = QComboBox()
        self.recent_projects_combo.setMinimumWidth(280)
        self.open_recent_project_button = QPushButton("打开最近工程")
        self.recent_projects_list = QListWidget()
        self.recent_projects_list.setMaximumHeight(120)
        self.import_template_bus_combo = QComboBox()
        self.import_template_asset_prefix_edit = QLineEdit()
        self.import_template_asset_prefix_edit.setPlaceholderText("ui/click")
        self.import_template_tags_edit = QLineEdit()
        self.import_template_tags_edit.setPlaceholderText("ui, click")
        self.import_template_hint_label = QLabel("树上“批量导入音频为事件”会默认读取这里的模板。")
        self.import_template_hint_label.setWordWrap(True)

        self.project_badge = QLabel("AudioForge 工程台")
        self.project_title_label = QLabel("未命名工程")
        self.project_path_label = QLabel("尚未保存")
        self.welcome_project_title_label = QLabel("未命名工程")
        self.welcome_project_path_label = QLabel("尚未保存")
        self.welcome_dirty_label = QLabel("已保存")
        self.shell_product_label = QLabel(APP_NAME)
        self.shell_project_title_label = QLabel("未命名工程")
        self.shell_project_path_label = QLabel("尚未保存")
        self.shell_mode_title_label = QLabel("欢迎页")
        self.status_label = QLabel("未选择事件")
        self.dirty_status_label = QLabel("已保存")
        self.toolbar_dirty_label = QLabel("已保存")
        self.workspace_dirty_label = QLabel("已保存")
        self.workspace_report_focus_label = QLabel("当前：日志")
        self.activity_report_focus_label = QLabel("当前：日志")
        self.activity_dirty_label = QLabel("已保存")
        self.report_focus_label = QLabel("当前：日志")
        self.report_detail_label = QLabel("等待校验、构建或响度扫描结果")
        self.inspector_caption = QLabel("检查器")
        self.explorer_caption = QLabel("工程浏览器")
        self.contents_caption = QLabel("内容编辑器")
        self.log_caption = QLabel("捕获日志")

        self.new_project_button = QPushButton("新建工程")
        self.open_project_button = QPushButton("打开工程")
        self.save_project_button = QPushButton("保存工程")
        self.save_as_project_button = QPushButton("另存为")
        self.zoom_out_button = QToolButton()
        self.zoom_reset_button = QToolButton()
        self.zoom_in_button = QToolButton()
        self.reset_layout_button = QToolButton()
        self.settings_button = QPushButton("设置")
        self.command_button = QPushButton("命令面板")
        self.scale_status_label = QLabel("100%")
        self.new_folder_button = QPushButton("新建文件夹")
        self.new_event_button = QPushButton("新建事件")
        self.rename_button = QPushButton("重命名")
        self.delete_button = QPushButton("删除")
        self.bulk_event_bus_button = QPushButton(f"批量改 {WWISE_OUTPUT_BUS_LABEL}")
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.validate_button = QPushButton("校验")
        self.preview_button = QPushButton("试听")
        self.stop_preview_event_button = QPushButton("停事件")
        self.stop_preview_bus_button = QPushButton("停止 Bus")
        self.build_button = QPushButton("构建交付")
        self.build_execute_button = QPushButton("开始构建导出")
        self.import_clips_button = QPushButton("导入音频")
        self.remove_clips_button = QPushButton("移除片段")
        self.bulk_weight_button = QPushButton("批量权重")
        self.batch_rename_button = QPushButton("批量重命名")
        self.apply_default_bus_button = QPushButton(f"应用 {WWISE_DEFAULT_BUS_LABEL} 到全部事件")
        self.tree_search_button = QToolButton()
        self.global_search_edit = QLineEdit()
        self.global_search_edit.setPlaceholderText("搜索对象、总线、问题或结果")
        self.global_search_button = QToolButton()
        self.task_sidebar = TaskSidebar()
        self.workspace_mode_stack = CurrentPageStack()
        self.activity_summary_label = QLabel("底部试听中心保持常驻，结果回看统一进入结果中心。")
        self.events_workspace_status_label = QLabel("等待选择事件。")
        self.event_overview_hint_label = QLabel("从左侧概览快速切到参数、资源或结果页。")
        self.resources_workspace_status_label = QLabel("等待导入或选择片段。")
        self.resources_overview_hint_label = QLabel("先完成片段编排，再进入批处理或生成预览。")
        self._resources_batch_feedback_event_id = ""
        self._has_resources_batch_feedback = False
        self.resources_batch_feedback_title_label = QLabel("等待批量操作")
        self.resources_batch_feedback_scope_label = QLabel("事件 -")
        self.resources_batch_feedback_count_label = QLabel("片段 0")
        self.resources_batch_feedback_field_label = QLabel("字段 -")
        self.resources_batch_feedback_summary_label = QLabel("进入“批处理”或使用资源页工具后，这里会显示最近一次成组修改。")
        self.resources_batch_feedback_detail_label = QLabel("支持批量权重、批量属性、批量重命名和排序反馈。")
        self.buses_workspace_status_label = QLabel(f"等待选择 {WWISE_OUTPUT_BUS_LABEL}。")
        self.buses_overview_hint_label = QLabel(f"从左侧概览选择当前要处理的 {WWISE_MASTER_MIXER_TITLE} 工作流。")
        self.gamesync_workspace_status_label = QLabel("等待建立项目级 GameSync 定义。")
        self.gamesync_overview_hint_label = QLabel("先补齐项目级 RTPC、State Group、Switch Group 壳层，再继续向事件和运行时绑定扩展。")
        self.gamesync_overview_total_label = QLabel("GameSync 对象 0")
        self.gamesync_overview_detail_label = QLabel("当前工程还没有任何 GameSync 定义。")
        self.gamesync_workspace_tabs = QTabWidget()
        self.gamesync_parameter_workspace_list = QListWidget()
        self.gamesync_state_workspace_list = QListWidget()
        self.gamesync_switch_workspace_list = QListWidget()
        self.gamesync_parameter_workspace_detail_label = QLabel("当前还没有 Game Parameter。")
        self.gamesync_state_workspace_detail_label = QLabel("当前还没有 State Group。")
        self.gamesync_switch_workspace_detail_label = QLabel("当前还没有 Switch Group。")
        self.build_workspace_status_label = QLabel("等待准备导出配置。")
        self.build_overview_hint_label = QLabel("先确认导出设置，再查看差异和构建结果。")
        self.validation_overview_hint_label = QLabel("按级别与关键字聚焦问题，再回到对象或资源页修复。")
        self.results_overview_hint_label = QLabel("从结果导航进入日志、校验、构建或响度结果。")
        self._validation_issue_items: list[dict[str, object]] = []


    def _build_ui(self) -> None:
        self.top_app_bar = self._build_top_app_bar()

        self.hero_panel = QFrame()
        self.hero_panel.setObjectName("HeroPanel")
        hero_layout = QVBoxLayout(self.hero_panel)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(2)
        hero_layout.addWidget(self.project_badge)
        hero_layout.addWidget(self.project_title_label)
        hero_layout.addWidget(self.project_path_label)
        hero_layout.addWidget(self.dirty_status_label)

        self.object_header_frame = QFrame()
        self.object_header_frame.setObjectName("ObjectHeader")
        object_header_layout = QVBoxLayout(self.object_header_frame)
        object_header_layout.setContentsMargins(12, 10, 12, 10)
        object_header_layout.setSpacing(4)
        object_top_row = QHBoxLayout()
        object_top_row.setContentsMargins(0, 0, 0, 0)
        object_top_row.setSpacing(8)
        object_top_row.addWidget(self.object_type_label)
        object_top_row.addWidget(self.object_name_label, 1)
        object_top_row.addWidget(self.object_parent_button)
        object_header_layout.addLayout(object_top_row)
        object_header_layout.addWidget(self.object_scope_label)
        object_meta_row = QHBoxLayout()
        object_meta_row.setContentsMargins(0, 0, 0, 0)
        object_meta_row.setSpacing(12)
        object_meta_row.addWidget(self.object_stats_label)
        object_meta_row.addWidget(self.object_summary_primary_label, 1)
        object_meta_row.addWidget(self.object_summary_secondary_label, 1)
        object_header_layout.addLayout(object_meta_row)
        object_bus_row = QHBoxLayout()
        object_bus_row.setContentsMargins(0, 0, 0, 0)
        object_bus_row.setSpacing(8)
        object_bus_row.addWidget(self.object_event_bus_chip)
        object_bus_row.addWidget(self.object_bus_browser_chip)
        object_bus_row.addWidget(self.object_context_hint_label, 1)
        object_header_layout.addLayout(object_bus_row)
        object_action_row = QHBoxLayout()
        object_action_row.setContentsMargins(0, 0, 0, 0)
        object_action_row.setSpacing(8)
        object_action_row.addWidget(self.object_preview_button)
        object_action_row.addWidget(self.object_contents_button)
        object_action_row.addWidget(self.object_follow_bus_button)
        object_action_row.addWidget(self.object_report_button)
        object_action_row.addStretch(1)
        object_header_layout.addLayout(object_action_row)

        self.reference_group = QGroupBox("对象引用")
        reference_layout = QGridLayout(self.reference_group)
        reference_layout.setContentsMargins(10, 8, 10, 8)
        reference_layout.setHorizontalSpacing(10)
        reference_layout.setVerticalSpacing(6)
        reference_layout.addWidget(QLabel("父级"), 0, 0)
        reference_layout.addWidget(self.reference_parent_value_button, 0, 1)
        reference_layout.addWidget(QLabel(WWISE_OUTPUT_BUS_LABEL), 0, 2)
        reference_layout.addWidget(self.reference_bus_value_button, 0, 3)
        reference_layout.addWidget(QLabel("资源"), 1, 0)
        reference_layout.addWidget(self.reference_assets_value_button, 1, 1)
        reference_layout.addWidget(QLabel("生成"), 1, 2)
        reference_layout.addWidget(self.reference_generation_value_button, 1, 3)
        reference_layout.addWidget(self.reference_work_unit_label, 2, 0, 1, 2)
        reference_layout.addWidget(self.reference_output_label, 2, 2, 1, 2)

        self.event_general_group = QGroupBox("事件元数据")
        general_layout = QFormLayout(self.event_general_group)
        general_layout.addRow("名称", self.display_name_edit)
        general_layout.addRow("对象 ID", self.event_id_edit)

        self.event_behavior_group = QGroupBox("播放控制")
        voice_layout = QFormLayout(self.event_behavior_group)
        voice_layout.addRow("抢占策略", self.steal_policy_combo)
        voice_layout.addRow("实例上限", self.max_instances_spin)
        voice_layout.addRow("冷却时间（秒）", self.cooldown_spin)

        self.event_audio_reference_group = QGroupBox("引用 Audio")
        event_audio_reference_layout = QVBoxLayout(self.event_audio_reference_group)
        event_audio_reference_layout.setSpacing(8)
        event_audio_reference_layout.addWidget(self.event_audio_reference_label)
        event_audio_reference_actions = QHBoxLayout()
        event_audio_reference_actions.setContentsMargins(0, 0, 0, 0)
        event_audio_reference_actions.setSpacing(8)
        event_audio_reference_actions.addWidget(self.event_open_audio_workspace_button)
        event_audio_reference_actions.addWidget(self.event_locate_audio_browser_button)
        event_audio_reference_actions.addStretch(1)
        event_audio_reference_layout.addLayout(event_audio_reference_actions)

        self.audio_general_group = QGroupBox("Audio 属性")
        audio_general_layout = QFormLayout(self.audio_general_group)
        audio_general_layout.addRow(WWISE_OUTPUT_BUS_LABEL, self.bus_combo)
        audio_general_layout.addRow("Audio 模式", self.play_mode_combo)
        audio_general_layout.addRow("加载方式", self.load_policy_combo)
        audio_general_layout.addRow("避免紧邻重复", self.avoid_repeat_check)
        audio_general_layout.addRow("标签", self.tags_summary_edit)

        self.modulation_group = QGroupBox("Audio 调制")
        modulation_layout = QFormLayout(self.modulation_group)
        modulation_layout.addRow("基础音量（dB）", self.volume_spin)
        modulation_layout.addRow("音量随机最小（dB）", self.volume_rand_min_spin)
        modulation_layout.addRow("音量随机最大（dB）", self.volume_rand_max_spin)
        modulation_layout.addRow("基础音高（cents）", self.pitch_spin)
        modulation_layout.addRow("音高随机最小（cents）", self.pitch_rand_min_spin)
        modulation_layout.addRow("音高随机最大（cents）", self.pitch_rand_max_spin)

        self.combo_group = QGroupBox("Audio Combo 规则")
        combo_layout = QFormLayout(self.combo_group)
        combo_layout.addRow("连击步进（半音）", self.combo_pitch_step_spin)
        combo_layout.addRow("重置时间（秒）", self.combo_reset_spin)
        combo_layout.addRow("最大步数", self.combo_max_step_spin)

        self.loudness_group = QGroupBox()
        self.loudness_group.setTitle("")
        self.loudness_group.setProperty("role", "inlineRecentPreview")
        self.loudness_group.setMinimumWidth(0)
        self.loudness_group.setMinimumHeight(36)
        self.loudness_group.setMaximumHeight(44)
        self.loudness_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        loudness_group_layout = QHBoxLayout(self.loudness_group)
        loudness_group_layout.setContentsMargins(0, 0, 0, 0)
        loudness_group_layout.setSpacing(8)
        self.preview_transport_title_label.setProperty("role", "previewTransportTitle")
        self.preview_transport_status_chip.setProperty("role", "previewTransportStatusChip")
        self.preview_transport_status_chip.setProperty("transportState", "idle")
        self.preview_transport_toggle_button.setCheckable(True)
        self.preview_transport_toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.preview_transport_toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.preview_transport_toggle_button.setProperty("role", "previewTransportToggle")
        self.preview_transport_toggle_button.setProperty("expanded", False)
        self.preview_transport_detail_label.setProperty("role", "previewTransportDetail")
        self.preview_transport_title_label.setWordWrap(False)
        self.preview_transport_title_label.setMinimumWidth(0)
        self.preview_transport_title_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.preview_transport_detail_label.setMinimumWidth(0)
        self.preview_transport_detail_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.preview_transport_detail_label.setWordWrap(False)
        self.preview_transport_frame.setObjectName("PreviewTransportFrame")
        for button, kind in [
            (self.preview_transport_play_button, "primary"),
            (self.preview_transport_pause_button, "secondary"),
            (self.preview_transport_restart_button, "secondary"),
            (self.preview_transport_stop_button, "danger"),
            (self.open_loudness_view_button, "monitor"),
        ]:
            button.setProperty("role", "previewTransportButton")
            button.setProperty("transportKind", kind)
            button.setProperty("transportState", "idle")
        self.preview_transport_metrics_frame.setObjectName("PreviewMetricsFrame")
        preview_summary_widget = QWidget()
        preview_summary_widget.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        preview_summary_layout = QVBoxLayout(preview_summary_widget)
        preview_summary_layout.setContentsMargins(0, 0, 0, 0)
        preview_summary_layout.setSpacing(0)
        preview_summary_title_row = QHBoxLayout()
        preview_summary_title_row.setContentsMargins(0, 0, 0, 0)
        preview_summary_title_row.setSpacing(6)
        preview_summary_title_row.addWidget(self.preview_transport_title_label)
        preview_summary_title_row.addWidget(self.preview_transport_status_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        preview_summary_title_row.addStretch(1)
        preview_summary_layout.addLayout(preview_summary_title_row)
        preview_summary_layout.addWidget(self.preview_transport_detail_label)

        self.preview_waveform_strip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.preview_waveform_strip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_waveform_strip.setMinimumHeight(32)
        self.preview_waveform_strip.setMaximumHeight(32)
        self.preview_waveform_strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_waveform_strip.setToolTip("最近一次试听的波形概览。")
        self.preview_waveform_strip.clear()

        preview_momentary_inline = self._build_meter_inline_stat("Momentary Max", self.preview_inline_momentary_max_value, "LUFS")
        preview_momentary_inline.setObjectName("PreviewMomentaryInline")
        preview_momentary_inline.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

        self.preview_gamesync_group.setMinimumWidth(0)
        self.preview_gamesync_group.setMinimumHeight(56)
        self.preview_gamesync_group.setMaximumHeight(84)
        self.preview_gamesync_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        preview_gamesync_layout = QHBoxLayout(self.preview_gamesync_group)
        preview_gamesync_layout.setContentsMargins(0, 0, 0, 0)
        preview_gamesync_layout.setSpacing(8)
        self.preview_gamesync_label.setProperty("role", "previewTransportTitle")
        self.preview_gamesync_label.setMinimumWidth(0)
        self.preview_gamesync_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.preview_parameter_section_label.setProperty("role", "previewTransportCaption")
        self.preview_state_section_label.setProperty("role", "previewTransportCaption")
        self.preview_switch_section_label.setProperty("role", "previewTransportCaption")
        self.preview_parameter_current_label.setProperty("role", "previewTransportReadout")
        self.preview_parameter_min_label.setProperty("role", "previewTransportCaption")
        self.preview_parameter_max_label.setProperty("role", "previewTransportCaption")
        for chip in [
            self.preview_parameter_source_chip,
            self.preview_state_scope_chip,
            self.preview_switch_source_chip,
            self.preview_switch_parameter_source_chip,
        ]:
            chip.setProperty("role", "busHeaderChip")
        self.preview_gamesync_summary_label.setProperty("role", "previewTransportCaption")
        self.preview_gamesync_summary_label.setWordWrap(True)
        for combo in [
            self.preview_parameter_name_combo,
            self.preview_parameter_scope_combo,
            self.preview_state_group_combo,
            self.preview_state_name_combo,
            self.preview_switch_group_combo,
            self.preview_switch_name_combo,
        ]:
            combo.setMinimumWidth(96)
            combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.preview_parameter_name_combo.setMinimumWidth(124)
        self.preview_parameter_slider.setMinimumWidth(176)
        self.preview_parameter_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_parameter_value_spin.setMinimumWidth(82)
        self.preview_parameter_value_spin.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        rtpc_layout = QVBoxLayout(self.preview_rtpc_transport_frame)
        rtpc_layout.setContentsMargins(10, 6, 10, 6)
        rtpc_layout.setSpacing(4)
        rtpc_header_layout = QHBoxLayout()
        rtpc_header_layout.setContentsMargins(0, 0, 0, 0)
        rtpc_header_layout.setSpacing(6)
        rtpc_header_layout.addWidget(self.preview_gamesync_label)
        rtpc_header_layout.addWidget(self.preview_parameter_section_label)
        rtpc_header_layout.addWidget(self.preview_parameter_name_combo)
        rtpc_header_layout.addWidget(self.preview_parameter_scope_combo)
        rtpc_header_layout.addWidget(self.preview_parameter_source_chip)
        rtpc_header_layout.addStretch(1)
        rtpc_header_layout.addWidget(self.preview_parameter_current_label)
        rtpc_layout.addLayout(rtpc_header_layout)

        rtpc_value_layout = QHBoxLayout()
        rtpc_value_layout.setContentsMargins(0, 0, 0, 0)
        rtpc_value_layout.setSpacing(8)
        rtpc_value_layout.addWidget(self.preview_parameter_min_label)
        rtpc_value_layout.addWidget(self.preview_parameter_slider, 1)
        rtpc_value_layout.addWidget(self.preview_parameter_max_label)
        rtpc_value_layout.addWidget(self.preview_parameter_value_spin)
        rtpc_layout.addLayout(rtpc_value_layout)
        rtpc_layout.addWidget(self.preview_gamesync_summary_label)

        preview_modes_layout = QGridLayout(self.preview_gamesync_modes_frame)
        preview_modes_layout.setContentsMargins(10, 6, 10, 6)
        preview_modes_layout.setHorizontalSpacing(6)
        preview_modes_layout.setVerticalSpacing(4)
        preview_modes_layout.addWidget(self.preview_state_section_label, 0, 0)
        preview_modes_layout.addWidget(self.preview_state_group_combo, 0, 1)
        preview_modes_layout.addWidget(self.preview_state_name_combo, 0, 2)
        preview_modes_layout.addWidget(self.preview_state_scope_chip, 0, 3)
        preview_modes_layout.addWidget(self.preview_switch_section_label, 1, 0)
        preview_modes_layout.addWidget(self.preview_switch_group_combo, 1, 1)
        preview_modes_layout.addWidget(self.preview_switch_name_combo, 1, 2)
        preview_modes_layout.addWidget(self.preview_switch_source_chip, 1, 3)
        preview_modes_layout.addWidget(self.preview_switch_parameter_source_chip, 1, 4)

        preview_gamesync_layout.addWidget(self.preview_rtpc_transport_frame, 1)
        preview_gamesync_layout.addWidget(self.preview_gamesync_modes_frame, 0)

        loudness_group_layout.addWidget(preview_summary_widget, 0)
        loudness_group_layout.addWidget(self.preview_waveform_strip, 1)
        loudness_group_layout.addWidget(preview_momentary_inline, 0)
        self.set_preview_transport_state("idle", has_target=False, can_replay=False)
        self.clear_recent_preview_insight()
        self._load_preview_gamesync_editor()

        self.notes_group = QGroupBox("备注")
        notes_layout = QVBoxLayout(self.notes_group)
        notes_layout.addWidget(self.notes_edit)

        self.event_source_binding_group = QGroupBox("Audio 源音频绑定")
        event_source_binding_layout = QVBoxLayout(self.event_source_binding_group)
        event_source_binding_layout.setSpacing(8)
        event_source_binding_layout.addWidget(self.event_source_binding_summary_label)
        event_source_binding_layout.addWidget(self.event_source_binding_detail_label)
        event_source_binding_layout.addWidget(self.event_source_binding_empty_label)
        event_source_binding_layout.addWidget(self.event_source_binding_overview_scroll)
        self.event_gamesync_group = self._build_event_gamesync_group()

        self.inline_bus_group = QGroupBox(WWISE_PROPERTY_EDITOR_TITLE)
        inline_bus_layout = QVBoxLayout(self.inline_bus_group)
        self.inline_bus_header.setObjectName("InlineBusHeader")
        inline_bus_header_layout = QHBoxLayout(self.inline_bus_header)
        inline_bus_header_layout.setContentsMargins(12, 10, 12, 10)
        inline_bus_header_layout.setSpacing(8)
        for chip in [self.inline_bus_name_chip, self.inline_bus_parent_chip, self.inline_bus_default_chip, self.inline_bus_export_chip]:
            chip.setProperty("role", "busHeaderChip")
            inline_bus_header_layout.addWidget(chip)
        inline_bus_header_layout.addStretch(1)
        inline_bus_layout.addWidget(self.inline_bus_header)
        inline_bus_actions = QHBoxLayout()
        inline_bus_actions.setContentsMargins(0, 0, 0, 0)
        inline_bus_actions.setSpacing(8)
        inline_bus_actions.addWidget(self.inline_bus_new_button)
        inline_bus_actions.addWidget(self.inline_bus_set_default_button)
        inline_bus_actions.addWidget(self.inline_bus_to_master_button)
        inline_bus_actions.addWidget(self.inline_bus_open_parent_button)
        inline_bus_layout.addLayout(inline_bus_actions)
        route_bar_layout = QVBoxLayout(self.project_bus_route_bar)
        route_bar_layout.setContentsMargins(0, 0, 0, 0)
        route_bar_layout.setSpacing(6)
        self.bus_routing_group = QGroupBox(WWISE_ROUTING_LABEL)
        bus_routing_layout = QVBoxLayout(self.bus_routing_group)
        bus_identity_form = QFormLayout()
        bus_identity_form.addRow(WWISE_BUS_NAME_LABEL, self.project_bus_name_edit)
        bus_identity_form.addRow(WWISE_PARENT_BUS_LABEL, self.project_bus_parent_combo)
        bus_routing_layout.addLayout(bus_identity_form)
        route_caption = QLabel(WWISE_ROUTING_LABEL)
        route_caption.setProperty("role", "meterTitle")
        bus_routing_layout.addWidget(route_caption)
        bus_routing_layout.addWidget(self.project_bus_route_bar)
        child_caption = QLabel(WWISE_CHILD_BUSES_LABEL)
        child_caption.setProperty("role", "meterTitle")
        bus_routing_layout.addWidget(child_caption)
        bus_routing_layout.addWidget(self.project_bus_children_label)
        self.bus_level_group = QGroupBox("Bus Volume")
        bus_level_layout = QFormLayout(self.bus_level_group)
        bus_level_layout.addRow("基础音量（dB）", self.project_bus_volume_spin)
        bus_level_layout.addRow("静音", self.project_bus_mute_check)
        bus_level_layout.addRow(WWISE_EFFECTIVE_OUTPUT_LABEL, self.project_bus_effective_value)
        bus_level_layout.addRow("输出表", self.project_bus_effective_bar)
        self.bus_validation_group = QGroupBox("导出结果")
        bus_validation_layout = QVBoxLayout(self.bus_validation_group)
        bus_validation_layout.setContentsMargins(12, 10, 12, 10)
        bus_validation_layout.addWidget(self.project_bus_export_label)
        self.bus_gamesync_group = self._build_bus_gamesync_group()
        self.current_bus_detail_tabs = QTabWidget()
        inline_bus_layout.addWidget(self.current_bus_detail_tabs)

        self.audio_top_splitter = QSplitter()
        self.audio_top_splitter.setObjectName("AudioTopSplitter")
        self.audio_top_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.audio_top_splitter.setChildrenCollapsible(False)
        self.audio_top_splitter.addWidget(self.modulation_group)
        self.audio_top_splitter.addWidget(self.loudness_group)
        self.audio_top_splitter.setStretchFactor(0, 2)
        self.audio_top_splitter.setStretchFactor(1, 3)
        self._responsive_two_column_splitters.append(self.audio_top_splitter)

        self.generation_settings_group = QGroupBox("生成设置")
        generation_settings_layout = QFormLayout(self.generation_settings_group)
        export_root_row = QHBoxLayout()
        export_root_row.setContentsMargins(0, 0, 0, 0)
        export_root_row.setSpacing(8)
        export_root_row.addWidget(self.export_root_edit, 1)
        export_root_row.addWidget(self.export_root_browse_button)
        generation_settings_layout.addRow("导出目录", export_root_row)
        generation_settings_layout.addRow("源格式", self.source_audio_format_combo)
        generation_settings_layout.addRow("运行时格式", self.runtime_audio_format_combo)

        self.build_overview_group = QGroupBox("生成概览")
        build_layout = QVBoxLayout(self.build_overview_group)
        build_layout.addWidget(QLabel("休闲游戏推荐流程：WAV 源资源 -> OGG 运行时导出"))
        build_layout.addWidget(QLabel("建议交付：AudioData.json、AudioManifest.json、AudioEventID.cs 与轻量音频资源目录"))
        build_scope_form = QFormLayout()
        build_scope_form.addRow("构建范围", self.build_scope_combo)
        build_scope_form.addRow("当前选区", self.build_scope_target_label)
        build_layout.addLayout(build_scope_form)
        build_layout.addWidget(self.build_scope_hint_label)
        build_layout.addWidget(self.build_plan_summary_label)
        build_layout.addWidget(self.build_plan_detail_label)
        build_layout.addWidget(self.preview_export_diff_button)
        build_profile_group = QGroupBox("构建画像")
        build_profile_layout = QVBoxLayout(build_profile_group)
        build_profile_layout.setContentsMargins(10, 8, 10, 8)
        build_profile_layout.setSpacing(6)
        build_profile_hint = QLabel("这里直接消费控制器的 build metadata，不再从页面标签反推。")
        build_profile_hint.setWordWrap(True)
        build_profile_hint.setProperty("role", "workspaceSectionSummary")
        build_profile_layout.addWidget(build_profile_hint)
        build_profile_layout.addWidget(self.build_profile_list)
        build_profile_layout.addWidget(self.build_profile_detail_output)
        build_layout.addWidget(build_profile_group)
        build_layout.addStretch(1)

        self.project_settings_group = QGroupBox("工程总览")
        project_settings_layout = QFormLayout(self.project_settings_group)
        project_settings_layout.addRow(WWISE_DEFAULT_BUS_LABEL, self.default_bus_combo)
        project_settings_layout.addRow("导入命名策略", self.auto_assign_bus_by_name_check)
        project_settings_layout.addRow("总线概况", self.project_bus_count_label)
        project_settings_layout.addRow("批量操作", self.apply_default_bus_button)

        self.bus_browser_group = QGroupBox(WWISE_MASTER_MIXER_HIERARCHY_TITLE)
        bus_browser_layout = QVBoxLayout(self.bus_browser_group)
        bus_browser_actions = QHBoxLayout()
        bus_browser_actions.addWidget(self.project_bus_add_button)
        bus_browser_actions.addWidget(self.project_bus_remove_button)
        bus_browser_layout.addLayout(bus_browser_actions)
        bus_browser_layout.addWidget(self.project_bus_list)
        bus_browser_layout.addWidget(self.project_bus_default_label)

        self.source_browser_group = QGroupBox("源音频树")
        source_browser_layout = QVBoxLayout(self.source_browser_group)
        source_browser_actions = QVBoxLayout()
        source_browser_actions.setContentsMargins(0, 0, 0, 0)
        source_browser_actions.setSpacing(6)
        source_browser_action_row_top = QHBoxLayout()
        source_browser_action_row_top.addWidget(self.source_browser_filter_combo)
        source_browser_action_row_top.addWidget(self.source_browser_locate_button)
        source_browser_action_row_top.addWidget(self.source_browser_copy_button)
        source_browser_action_row_top.addStretch(1)
        source_browser_action_row_bottom = QHBoxLayout()
        source_browser_action_row_bottom.addWidget(self.source_browser_locate_event_button)
        source_browser_action_row_bottom.addWidget(self.source_browser_add_to_event_button)
        source_browser_action_row_bottom.addStretch(1)
        source_browser_actions.addLayout(source_browser_action_row_top)
        source_browser_actions.addLayout(source_browser_action_row_bottom)
        source_browser_layout.addLayout(source_browser_actions)
        source_browser_layout.addWidget(self.source_tree)
        source_browser_layout.addWidget(self.source_browser_summary_label)
        source_browser_layout.addWidget(self.source_browser_status_label)

        self.audio_browser_group = QGroupBox("Audio 树")
        audio_browser_layout = QVBoxLayout(self.audio_browser_group)
        audio_browser_actions = QHBoxLayout()
        audio_browser_actions.setContentsMargins(0, 0, 0, 0)
        audio_browser_actions.setSpacing(8)
        audio_browser_actions.addWidget(self.audio_browser_locate_event_button)
        audio_browser_actions.addWidget(self.audio_browser_open_bindings_button)
        audio_browser_actions.addStretch(1)
        audio_browser_layout.addLayout(audio_browser_actions)
        audio_browser_layout.addWidget(self.audio_tree)
        audio_browser_layout.addWidget(self.audio_browser_summary_label)
        audio_browser_layout.addWidget(self.audio_browser_status_label)

        self.gamesync_browser_group = QGroupBox("GameSync")
        gamesync_browser_layout = QVBoxLayout(self.gamesync_browser_group)
        self.gamesync_browser_tabs.addTab(
            self._build_gamesync_entry_panel(
                "Game Parameters",
                "项目级连续参数，后续会映射到 RTPC。",
                self.gamesync_parameter_browser_list,
                self.gamesync_parameter_browser_detail_label,
            ),
            load_app_icon("rtpc"),
            "参数",
        )
        self.gamesync_browser_tabs.addTab(
            self._build_gamesync_entry_panel(
                "State Groups",
                "项目级全局离散模式，后续用于 Event / Bus 属性覆盖。",
                self.gamesync_state_browser_list,
                self.gamesync_state_browser_detail_label,
            ),
            load_app_icon("state"),
            "State",
        )
        self.gamesync_browser_tabs.addTab(
            self._build_gamesync_entry_panel(
                "Switch Groups",
                "按 emitter 生效的离散分支，后续用于事件内变体切换。",
                self.gamesync_switch_browser_list,
                self.gamesync_switch_browser_detail_label,
            ),
            load_app_icon("switch"),
            "Switch",
        )
        gamesync_browser_layout.addWidget(self.gamesync_browser_tabs)
        gamesync_browser_layout.addWidget(self.gamesync_browser_summary_label)
        gamesync_browser_layout.addWidget(self.gamesync_browser_status_label)

        self.master_bus_group = QGroupBox(WWISE_MASTER_AUDIO_BUS_TITLE)
        master_bus_layout = QFormLayout(self.master_bus_group)
        master_bus_layout.addRow(WWISE_BUS_NAME_LABEL, self.project_master_summary_label)
        master_bus_layout.addRow("基础音量（dB）", self.project_master_volume_spin)
        master_bus_layout.addRow("静音", self.project_master_mute_check)
        master_bus_layout.addRow(WWISE_EFFECTIVE_OUTPUT_LABEL, self.project_master_effective_value)
        master_bus_layout.addRow("输出表", self.project_master_effective_bar)
        master_bus_layout.addRow("说明", self.project_master_hint_label)

        self.project_bus_overview_group = QGroupBox(WWISE_MASTER_MIXER_TITLE)
        project_bus_overview_layout = QVBoxLayout(self.project_bus_overview_group)
        project_bus_overview_layout.addWidget(self.project_bus_summary_label)
        project_bus_overview_layout.addWidget(self.project_bus_focus_audio_button)

        self.current_bus_route_scroll = self._wrap_scrollable_page(
            self._build_two_column_page(
                [self.bus_routing_group],
                [self.project_bus_overview_group],
                splitter_name="CurrentBusRoutePageSplitter",
            )
        )
        self.current_bus_level_scroll = self._wrap_scrollable_page(
            self._build_two_column_page(
                [self.bus_level_group],
                [self.bus_validation_group],
                splitter_name="CurrentBusLevelPageSplitter",
            )
        )
        self.current_bus_detail_tabs.addTab(self.current_bus_route_scroll, load_app_icon("route"), WWISE_ROUTING_LABEL)
        self.current_bus_detail_tabs.addTab(self.current_bus_level_scroll, load_app_icon("generate"), "电平/导出")

        self.project_bus_browser_hint_group = QGroupBox("对象浏览器")
        project_bus_browser_hint_layout = QVBoxLayout(self.project_bus_browser_hint_group)
        project_bus_browser_hint_label = QLabel("总线树已并入左侧对象浏览器；在浏览器中选中 Bus 后，这里只保留属性与总览。")
        project_bus_browser_hint_label.setWordWrap(True)
        project_bus_browser_hint_layout.addWidget(project_bus_browser_hint_label)
        project_bus_browser_hint_layout.addWidget(self.project_bus_browser_button)
        project_bus_browser_hint_layout.addStretch(1)

        project_right_panel = QWidget()
        project_right_layout = QVBoxLayout(project_right_panel)
        project_right_layout.setContentsMargins(0, 0, 0, 0)
        project_right_layout.addWidget(self.master_bus_group)
        project_right_layout.addWidget(self.project_settings_group)
        project_right_layout.addStretch(1)

        self.project_splitter = QSplitter()
        self.project_splitter.setObjectName("ProjectSplitter")
        self.project_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.project_splitter.setChildrenCollapsible(False)
        self.project_splitter.addWidget(self.project_bus_browser_hint_group)
        self.project_splitter.addWidget(project_right_panel)
        self.project_splitter.setStretchFactor(1, 1)
        self._responsive_two_column_splitters.append(self.project_splitter)

        clip_list_group = QGroupBox("片段列表")
        clip_list_layout = QVBoxLayout(clip_list_group)
        clip_actions = QHBoxLayout()
        clip_actions.addWidget(self.import_clips_button)
        clip_actions.addWidget(self.remove_clips_button)
        clip_actions.addWidget(self.bulk_weight_button)
        clip_actions.addWidget(self.batch_rename_button)
        clip_list_layout.addLayout(clip_actions)
        clip_list_layout.addWidget(self.clip_filter_edit)
        clip_list_layout.addWidget(self.clip_table)

        clip_detail_group = QGroupBox("片段编辑台")
        self.clip_detail_group = clip_detail_group
        clip_detail_layout = QVBoxLayout(clip_detail_group)
        clip_detail_layout.setSpacing(8)
        self.clip_context_bar = QFrame()
        self.clip_context_bar.setObjectName("ModeIntroCard")
        clip_context_layout = QVBoxLayout(self.clip_context_bar)
        clip_context_layout.setContentsMargins(12, 10, 12, 10)
        clip_context_layout.setSpacing(4)
        self.clip_selected_label.setProperty("role", "workspaceSectionTitle")
        self.clip_preview_hint_label.setProperty("role", "workspaceSectionSummary")
        clip_context_layout.addWidget(self.clip_selected_label)
        clip_context_layout.addWidget(self.clip_preview_hint_label)

        clip_timing_card = QFrame()
        clip_timing_card.setObjectName("ModeIntroCard")
        clip_timing_layout = QVBoxLayout(clip_timing_card)
        clip_timing_layout.setContentsMargins(10, 10, 10, 10)
        clip_timing_layout.setSpacing(6)
        clip_timing_layout.addWidget(self.clip_waveform_editor)
        self.clip_waveform_action_panel = QWidget()
        self.clip_waveform_action_layout = QGridLayout(self.clip_waveform_action_panel)
        self.clip_waveform_action_layout.setContentsMargins(0, 0, 0, 0)
        self.clip_waveform_action_layout.setHorizontalSpacing(6)
        self.clip_waveform_action_layout.setVerticalSpacing(6)
        clip_timing_layout.addWidget(self.clip_waveform_action_panel)
        clip_time_grid = QGridLayout()
        clip_time_grid.setContentsMargins(0, 0, 0, 0)
        clip_time_grid.setHorizontalSpacing(8)
        clip_time_grid.setVerticalSpacing(6)
        clip_time_grid.addWidget(QLabel("起始"), 0, 0)
        clip_time_grid.addWidget(self.clip_trim_start_spin, 0, 1)
        clip_time_grid.addWidget(QLabel("结束"), 0, 2)
        clip_time_grid.addWidget(self.clip_trim_end_spin, 0, 3)
        clip_time_grid.addWidget(QLabel("淡入"), 1, 0)
        clip_time_grid.addWidget(self.clip_fade_in_spin, 1, 1)
        clip_time_grid.addWidget(QLabel("淡出"), 1, 2)
        clip_time_grid.addWidget(self.clip_fade_out_spin, 1, 3)
        clip_time_grid.addWidget(QLabel("循环起点"), 2, 0)
        clip_time_grid.addWidget(self.clip_loop_start_spin, 2, 1)
        clip_time_grid.addWidget(QLabel("循环终点"), 2, 2)
        clip_time_grid.addWidget(self.clip_loop_end_spin, 2, 3)
        clip_timing_layout.addLayout(clip_time_grid)
        clip_timing_layout.setStretch(0, 1)

        clip_meta_card = QFrame()
        clip_meta_card.setObjectName("ModeIntroCard")
        self.clip_meta_layout = QFormLayout(clip_meta_card)
        self.clip_meta_layout.setContentsMargins(12, 10, 12, 10)
        self.clip_meta_layout.setSpacing(6)
        self.clip_meta_layout.addRow("源路径", self.clip_source_detail_edit)
        self.clip_meta_layout.addRow("资源键", self.clip_asset_detail_edit)
        self.clip_meta_inline_panel = QWidget()
        clip_meta_inline_layout = QGridLayout(self.clip_meta_inline_panel)
        clip_meta_inline_layout.setContentsMargins(0, 0, 0, 0)
        clip_meta_inline_layout.setHorizontalSpacing(8)
        clip_meta_inline_layout.setVerticalSpacing(6)
        clip_meta_inline_layout.addWidget(QLabel("权重"), 0, 0)
        clip_meta_inline_layout.addWidget(self.clip_weight_row, 0, 1)
        clip_meta_inline_layout.addWidget(QLabel("标签"), 1, 0)
        clip_meta_inline_layout.addWidget(self.clip_tags_detail_edit, 1, 1)
        clip_meta_inline_layout.setColumnStretch(1, 1)
        self.clip_meta_layout.addRow(self.clip_meta_inline_panel)

        self.clip_action_row = QWidget()
        self.clip_action_layout = QGridLayout(self.clip_action_row)
        self.clip_action_layout.setContentsMargins(0, 0, 0, 0)
        self.clip_action_layout.setHorizontalSpacing(8)
        self.clip_action_layout.setVerticalSpacing(8)
        clip_detail_layout.addWidget(self.clip_context_bar)
        clip_detail_layout.addWidget(clip_timing_card, 1)
        clip_detail_layout.addWidget(clip_meta_card)
        clip_detail_layout.addWidget(self.clip_action_row)

        clip_tools_group = QGroupBox("批量编辑与排序")
        clip_tools_layout = QFormLayout(clip_tools_group)
        clip_tools_layout.addRow("批量权重", self.bulk_clip_weight_row)
        clip_tools_layout.addRow("资源前缀", self.bulk_clip_asset_prefix_edit)
        clip_tools_layout.addRow("标签", self.bulk_clip_tags_edit)

        sort_row = QWidget()
        sort_row_layout = QHBoxLayout(sort_row)
        sort_row_layout.setContentsMargins(0, 0, 0, 0)
        sort_row_layout.addWidget(self.sort_field_combo)
        sort_row_layout.addWidget(self.sort_order_combo)
        sort_row_layout.addWidget(self.sort_clips_button)
        clip_tools_layout.addRow("排序", sort_row)
        clip_tools_layout.addRow("应用", self.apply_bulk_clip_button)

        batch_guide_group = QGroupBox("批处理建议")
        batch_guide_layout = QVBoxLayout(batch_guide_group)
        batch_guide_layout.addWidget(QLabel("先按资源前缀和标签清洗片段，再批量改权重，最后再排序。"))
        batch_guide_layout.addWidget(QLabel("批处理页只做成组修改，不承载单片段精修；单片段精修仍在“片段编排”页完成。"))
        batch_guide_layout.addWidget(QLabel("如果只是想确认导出差异，请切到“生成预览”，避免在批处理页塞入过多只读信息。"))
        batch_guide_layout.addStretch(1)

        self.build_preview_group = QGroupBox("生成预览")
        build_preview_layout = QVBoxLayout(self.build_preview_group)
        build_preview_layout.addWidget(self.build_preview_output)

        self.content_top_splitter = QSplitter()
        self.content_top_splitter.setObjectName("ContentTopSplitter")
        self.content_top_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.content_top_splitter.setChildrenCollapsible(False)
        self.content_top_splitter.addWidget(clip_list_group)
        self.content_top_splitter.addWidget(clip_detail_group)
        self.content_top_splitter.splitterMoved.connect(lambda *_args: self._schedule_layout_flush())
        self._set_content_top_splitter_sizes(self._default_content_top_splitter_sizes)
        self._rebuild_clip_waveform_action_panel("wide")
        self._rebuild_clip_detail_action_panel("wide")

        batch_page = self._build_two_column_page(
            [clip_tools_group],
            [batch_guide_group],
            splitter_name="ResourceBatchPageSplitter",
        )

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(10)
        preview_layout.addWidget(self._build_mode_surface_card("生成预览入口", "这里显示当前导出差异与构建预览的镜像视图；正式交付仍在构建交付工作区完成。"))
        preview_shortcut_button = QPushButton("进入构建交付")
        preview_shortcut_button.clicked.connect(lambda: self._activate_workspace_mode("build"))
        preview_layout.addWidget(preview_shortcut_button)
        preview_mirror_group = QGroupBox("当前导出预览")
        preview_mirror_layout = QVBoxLayout(preview_mirror_group)
        preview_mirror_layout.addWidget(self.resources_preview_output)
        preview_layout.addWidget(preview_mirror_group, 1)

        self.contents_tabs = QTabWidget()
        self.contents_tabs.addTab(self.content_top_splitter, load_app_icon("content"), "片段编排")
        self.contents_tabs.addTab(self._wrap_scrollable_page(batch_page), load_app_icon("audio"), "批处理")
        self.contents_tabs.addTab(self._wrap_scrollable_page(preview_page), load_app_icon("generate"), "生成预览")

        self.loudness_view = QWidget()
        loudness_view_layout = QVBoxLayout(self.loudness_view)
        loudness_view_layout.addWidget(self._build_panel_header("响度监视器", "meter"))
        loudness_view_layout.addWidget(self._build_loudness_monitor_view())

        self._property_compat_scroll_pages = {
            1: self._build_property_compat_scroll("音频属性兼容页", f"旧兼容接口仍会把这一页视作可滚动属性页；真实编辑已迁到“{WWISE_MASTER_MIXER_TITLE}”工作区。"),
            2: self._build_property_compat_scroll("生成兼容页", "旧兼容接口仍会把这一页视作可滚动属性页；真实编辑已迁到“构建交付”工作区。"),
            3: self._build_property_compat_scroll("工程兼容页", "旧兼容接口仍会把这一页视作可滚动属性页；真实工程配置已收口到独立工作区。"),
        }
        self._property_tab_index: int = 0
        self._property_tab_labels: list[str] = ["事件", "音频属性", "生成", "工程"]

        self._editor_tab_index: int = 0
        self._editor_tab_labels: list[str] = ["属性编辑器", "内容编辑器", "响度监视器"]

        self.events_workspace = self._build_events_workspace()
        self.resources_workspace = self._build_resources_workspace()
        self.gamesync_workspace = self._build_gamesync_workspace()
        self.buses_workspace = self._build_buses_workspace()
        self.build_workspace = self._build_build_workspace()
        self.validation_workspace = self._build_validation_workspace()
        self.property_group = self.events_workspace

        self.report_pages = QStackedWidget()
        self._report_page_titles = ["当前：日志", "当前：校验报告", "当前：构建报告", "当前：响度扫描", "当前：诊断概览"]
        self._report_pages: dict[int, QWidget] = {
            0: self._build_log_results_page(),
            1: self._build_validation_results_page(),
            2: self._build_build_results_page(),
            3: self._build_loudness_results_page(),
            4: self._build_diagnostic_results_page(),
        }
        for index in range(len(self._report_pages)):
            self.report_pages.addWidget(self._report_pages[index])
        self._active_report_index = 0

        self._report_tab_index: int = 0
        self._report_tab_labels: list[str] = ["日志", "校验报告", "构建报告", "响度扫描", "诊断概览"]

        self.report_header = QFrame()
        self.report_header.setObjectName("ReportHeader")
        self.report_focus_label = QLabel(self.report_focus_label.text(), self.report_header)
        self.report_detail_label = QLabel(self.report_detail_label.text(), self.report_header)
        report_header_layout = QHBoxLayout(self.report_header)
        report_header_layout.setContentsMargins(10, 8, 10, 8)
        report_header_layout.setSpacing(8)
        report_header_layout.addWidget(self.report_focus_label)
        report_header_layout.addWidget(self.report_detail_label, 1)
        report_header_layout.addWidget(self._build_report_jump_button("日志", 0))
        report_header_layout.addWidget(self._build_report_jump_button("校验", 1))
        report_header_layout.addWidget(self._build_report_jump_button("构建", 2))
        report_header_layout.addWidget(self._build_report_jump_button("扫描", 3))
        report_header_layout.addWidget(self._build_report_jump_button("诊断", 4))

        self.results_center_panel = self._build_results_center_panel()
        self.activity_panel = self._build_activity_panel()

        self._workspace_mode_pages: dict[str, QWidget] = {}
        self._workspace_mode_hosts: dict[str, QVBoxLayout] = {}
        self._workspace_shared_surfaces: dict[str, QWidget] = {
            "results": self.results_center_panel,
            "validation": self.validation_workspace,
        }
        self.workspace_mode_stack.addWidget(self._build_welcome_page())
        self._workspace_mode_pages["home"] = self.workspace_mode_stack.widget(self.workspace_mode_stack.count() - 1)
        for mode, title, description in [
            ("events", "事件设计", "以事件参数、触发控制和响度监视作为专属工作区，不再依赖旧属性编辑器。"),
            ("resources", "资源整理", "集中处理片段编排、批处理和生成预览，不再从属性页反复跳转。"),
            ("gamesync", "GameSync", "集中查看项目级 Game Parameter、State Group 和 Switch Group，为 phase3 的 runtime 绑定做准备。"),
            ("buses", WWISE_MASTER_MIXER_TITLE, "将当前输出 Bus、Bus 层级和主 Bus 整合为独立工作区。"),
            ("validation", "校验修复", "直接进入问题中心，按校验结果修复对象与资源。"),
            ("build", "构建交付", "将导出设置、交付预览和构建入口收口到专门页面。"),
            ("results", "结果中心", "统一回看日志、构建输出和响度扫描；校验修复仍在专门工作区完成。"),
        ]:
            page, host_layout = self._build_workspace_mode_page(mode, title, description)
            self._workspace_mode_pages[mode] = page
            self._workspace_mode_hosts[mode] = host_layout
            self.workspace_mode_stack.addWidget(page)
        self._workspace_mode_hosts["events"].addWidget(self.events_workspace)
        self._workspace_mode_hosts["resources"].addWidget(self.resources_workspace)
        self._workspace_mode_hosts["gamesync"].addWidget(self.gamesync_workspace)
        self._workspace_mode_hosts["buses"].addWidget(self.buses_workspace)
        self._workspace_mode_hosts["build"].addWidget(self.build_workspace)

        self.workspace_status_bar = QFrame()
        self.workspace_status_bar.setObjectName("WorkspaceStatusBar")
        self.status_label = QLabel(self.status_label.text(), self.workspace_status_bar)
        workspace_status_layout = QHBoxLayout(self.workspace_status_bar)
        workspace_status_layout.setContentsMargins(12, 8, 12, 8)
        workspace_status_layout.setSpacing(10)
        workspace_status_layout.addWidget(self.status_label)
        workspace_status_layout.addStretch(1)

        self.main_splitter = QSplitter()
        self.main_splitter.setObjectName("MainSplitter")
        self.main_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)
        self.explorer_panel = QWidget()
        left_layout = QVBoxLayout(self.explorer_panel)
        left_layout.addWidget(self._build_panel_header("工程浏览器", "explorer"))
        tree_filter_row = QHBoxLayout()
        tree_filter_row.setContentsMargins(0, 0, 0, 0)
        tree_filter_row.setSpacing(6)
        tree_filter_row.addWidget(self.tree_filter_edit, 1)
        tree_filter_row.addWidget(self.tree_search_button)
        left_layout.addLayout(tree_filter_row)
        event_browser_page = QWidget()
        event_browser_layout = QVBoxLayout(event_browser_page)
        event_browser_layout.setContentsMargins(0, 0, 0, 0)
        event_browser_layout.addWidget(self.tree)
        self.explorer_tabs.addTab(self.bus_browser_group, load_app_icon("bus"), "总线树")
        self.explorer_tabs.addTab(self.source_browser_group, load_app_icon("audio"), "源音频树")
        self.explorer_tabs.addTab(self.audio_browser_group, load_app_icon("audio"), "Audio 树")
        self.explorer_tabs.addTab(event_browser_page, load_app_icon("event"), "事件树")
        self.explorer_tabs.addTab(self.gamesync_browser_group, load_app_icon("curve"), "GameSync")
        left_layout.addWidget(self.explorer_tabs)
        self._sync_explorer_browser_state()
        self.explorer_placeholder = self._build_detached_explorer_placeholder()
        self.explorer_window = DetachedToolWindow()
        self.explorer_window.setWindowTitle(f"{APP_NAME} - 工程浏览器")
        self.explorer_window.setWindowIcon(load_app_icon("app"))
        self._apply_adaptive_top_level_defaults(self.explorer_window, (460, 820), (360, 480))
        explorer_window_layout = QVBoxLayout(self.explorer_window)
        explorer_window_layout.setContentsMargins(8, 8, 8, 8)
        explorer_window_layout.setSpacing(8)
        self.explorer_window_layout = explorer_window_layout
        self.explorer_window.closeRequested.connect(self.attach_explorer_panel)
        self.explorer_panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.workspace_mode_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.main_splitter.addWidget(self.explorer_panel)
        self.main_splitter.addWidget(self.workspace_mode_stack)
        self.main_splitter.setStretchFactor(0, 2)
        self.main_splitter.setStretchFactor(1, 8)
        self._set_main_splitter_sizes(self._default_main_splitter_sizes)

        self.workspace_splitter = QSplitter()
        self.workspace_splitter.setObjectName("WorkspaceSplitter")
        self.workspace_splitter.setOrientation(Qt.Orientation.Vertical)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(10)
        self.workspace_splitter.addWidget(self.main_splitter)
        self.workspace_splitter.addWidget(self.activity_panel)
        self.workspace_splitter.setStretchFactor(0, 8)
        self.workspace_splitter.setStretchFactor(1, 1)
        self._set_workspace_splitter_sizes(self._default_workspace_splitter_sizes)

        workspace_container = QWidget()
        workspace_container_layout = QVBoxLayout(workspace_container)
        workspace_container_layout.setContentsMargins(0, 0, 0, 0)
        workspace_container_layout.setSpacing(8)
        workspace_container_layout.addWidget(self.workspace_status_bar)
        workspace_container_layout.addWidget(self.workspace_splitter)

        shell = AppShell(self.top_app_bar, self.task_sidebar, workspace_container)
        self.setCentralWidget(shell)
        self._apply_splitter_resize_defaults()
        self._activate_workspace_mode(self._active_workspace_mode)
        self.task_sidebar.set_active_mode(self._active_workspace_mode)
        self._build_settings_dialog()

    def _apply_splitter_resize_defaults(self) -> None:
        for splitter in self.findChildren(QSplitter):
            splitter.setChildrenCollapsible(False)
            splitter.setOpaqueResize(True)
            if splitter.handleWidth() < 10:
                splitter.setHandleWidth(10)

    def _named_splitter_sizes(self) -> dict[str, list[int]]:
        splitter_sizes: dict[str, list[int]] = {}
        for splitter in self.findChildren(QSplitter):
            name = splitter.objectName().strip()
            if not name:
                continue
            if name == "MainSplitter":
                splitter_sizes[name] = self._effective_main_splitter_sizes()
            else:
                splitter_sizes[name] = [int(value) for value in splitter.sizes()]
        return splitter_sizes

    def _set_named_splitter_sizes(self, splitter_sizes: object) -> None:
        pending: dict[str, list[int]] = {}
        if isinstance(splitter_sizes, dict):
            for name, values in splitter_sizes.items():
                if not isinstance(name, str) or not isinstance(values, list) or len(values) < 2:
                    continue
                pending[name] = [int(value) for value in values]
        self._pending_named_splitter_sizes = pending
        if pending and self.isVisible():
            self._schedule_layout_flush()

    def _encode_window_geometry(self, widget: QWidget) -> str:
        return bytes(widget.saveGeometry().toBase64()).decode("ascii")

    def _restore_window_geometry(self, widget: QWidget, encoded_geometry: object) -> None:
        if not isinstance(encoded_geometry, str) or not encoded_geometry:
            return
        widget.restoreGeometry(QByteArray.fromBase64(encoded_geometry.encode("ascii")))
        self._constrain_window_to_available_geometry(widget)

    def _screen_available_geometry(self, widget: QWidget | None = None) -> QRect:
        screen = None
        if widget is not None:
            screen = widget.screen()
        if screen is None:
            screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, DEFAULT_WINDOW_SIZE[0], DEFAULT_WINDOW_SIZE[1])
        available = screen.availableGeometry()
        if available.isValid() and available.width() > 0 and available.height() > 0:
            return available
        return QRect(0, 0, DEFAULT_WINDOW_SIZE[0], DEFAULT_WINDOW_SIZE[1])

    def _adaptive_top_level_sizes(
        self,
        default_size: tuple[int, int] | QSize,
        base_minimum_size: tuple[int, int] | QSize,
        *,
        available_geometry: QRect | None = None,
    ) -> tuple[QSize, QSize]:
        available = available_geometry if available_geometry is not None else self._screen_available_geometry()
        default_qsize = default_size if isinstance(default_size, QSize) else QSize(int(default_size[0]), int(default_size[1]))
        minimum_qsize = base_minimum_size if isinstance(base_minimum_size, QSize) else QSize(int(base_minimum_size[0]), int(base_minimum_size[1]))

        min_width = min(minimum_qsize.width(), max(640, int(available.width() * 0.64)))
        min_height = min(minimum_qsize.height(), max(520, int(available.height() * 0.64)))
        adaptive_minimum = QSize(min_width, min_height)

        target_width = min(default_qsize.width(), max(min_width, int(available.width() * 0.94)))
        target_height = min(default_qsize.height(), max(min_height, int(available.height() * 0.94)))
        adaptive_size = QSize(target_width, target_height)
        return adaptive_minimum, adaptive_size

    def _fit_top_level_geometry(self, geometry: QRect, available_geometry: QRect, minimum_size: QSize) -> QRect:
        if not geometry.isValid() or geometry.width() <= 0 or geometry.height() <= 0:
            return QRect(available_geometry.topLeft(), minimum_size)

        width = min(max(minimum_size.width(), geometry.width()), available_geometry.width())
        height = min(max(minimum_size.height(), geometry.height()), available_geometry.height())
        max_x = available_geometry.left() + max(0, available_geometry.width() - width)
        max_y = available_geometry.top() + max(0, available_geometry.height() - height)
        x = min(max(geometry.x(), available_geometry.left()), max_x)
        y = min(max(geometry.y(), available_geometry.top()), max_y)
        return QRect(x, y, width, height)

    def _apply_adaptive_top_level_defaults(
        self,
        widget: QWidget,
        default_size: tuple[int, int] | QSize,
        base_minimum_size: tuple[int, int] | QSize,
    ) -> None:
        adaptive_minimum, adaptive_size = self._adaptive_top_level_sizes(
            default_size,
            base_minimum_size,
            available_geometry=self._screen_available_geometry(widget),
        )
        widget.setMinimumSize(adaptive_minimum)
        widget.resize(adaptive_size)
        self._constrain_window_to_available_geometry(widget)

    def _constrain_window_to_available_geometry(self, widget: QWidget) -> None:
        available = self._screen_available_geometry(widget)
        current_minimum = widget.minimumSizeHint()
        minimum_width = max(widget.minimumWidth(), current_minimum.width(), 1)
        minimum_height = max(widget.minimumHeight(), current_minimum.height(), 1)
        constrained_minimum = QSize(min(minimum_width, available.width()), min(minimum_height, available.height()))
        widget.setMinimumSize(constrained_minimum)
        target_geometry = self._fit_top_level_geometry(widget.geometry(), available, constrained_minimum)
        widget.setGeometry(target_geometry)

    def _build_top_app_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopAppBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        branding = QWidget()
        branding_layout = QVBoxLayout(branding)
        branding_layout.setContentsMargins(0, 0, 0, 0)
        branding_layout.setSpacing(2)
        self.shell_product_label.setProperty("role", "appTitle")
        self.shell_project_title_label.setProperty("role", "appProjectTitle")
        self.shell_project_path_label.setProperty("role", "appProjectPath")
        branding_layout.addWidget(self.shell_product_label)
        branding_layout.addWidget(self.shell_project_title_label)
        branding_layout.addWidget(self.shell_project_path_label)

        mode_summary = QWidget()
        mode_summary_layout = QVBoxLayout(mode_summary)
        mode_summary_layout.setContentsMargins(0, 0, 0, 0)
        mode_summary_layout.setSpacing(2)
        mode_title_caption = QLabel("当前工作模式")
        mode_title_caption.setProperty("role", "appMetaCaption")
        self.shell_mode_title_label.setProperty("role", "appModeTitle")
        mode_summary_layout.addWidget(mode_title_caption)
        mode_summary_layout.addWidget(self.shell_mode_title_label)

        search_row = QWidget()
        search_row_layout = QHBoxLayout(search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_row_layout.setSpacing(6)
        self.global_search_edit.setProperty("role", "topSearchField")
        self.global_search_button.setProperty("role", "topSearchButton")
        search_row_layout.addWidget(self.global_search_edit, 1)
        search_row_layout.addWidget(self.global_search_button)

        primary_actions = QWidget()
        primary_actions_layout = QHBoxLayout(primary_actions)
        primary_actions_layout.setContentsMargins(0, 0, 0, 0)
        primary_actions_layout.setSpacing(8)
        self.new_project_button.setProperty("role", "topSubtleButton")
        self.open_project_button.setProperty("role", "topSubtleButton")
        self.save_project_button.setProperty("role", "topSubtleButton")
        self.validate_button.setProperty("role", "topAccentButton")
        self.build_button.setProperty("role", "topPrimaryButton")
        self.command_button.setProperty("role", "topSubtleButton")
        self.settings_button.setProperty("role", "topSubtleButton")
        for button in [
            self.new_project_button,
            self.open_project_button,
            self.save_project_button,
            self.validate_button,
            self.build_button,
            self.command_button,
            self.settings_button,
        ]:
            primary_actions_layout.addWidget(button)
        self.toolbar_dirty_label.setProperty("role", "topStatusChip")
        primary_actions_layout.addWidget(self.toolbar_dirty_label)

        layout.addWidget(branding)
        layout.addSpacing(8)
        layout.addWidget(mode_summary)
        layout.addSpacing(12)
        layout.addWidget(search_row, 1)
        layout.addWidget(primary_actions)
        return bar

    def _build_workspace_mode_page(self, mode: str, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        layout.addWidget(host, 1)
        return page, host_layout

    def _build_mode_surface_card(self, title: str, description: str, *, role: str = "modeCardDescription") -> QFrame:
        card = QFrame()
        card.setObjectName("ModeIntroCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setProperty("role", "modeCardTitle")
        normalized_description = " ".join(description.split())
        description_label = QLabel(normalized_description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", role)
        description_label.setToolTip(normalized_description)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return card

    def _card_icon_name_for_title(self, title: str) -> str:
        if any(token in title for token in ["事件", "对象"]):
            return "event"
        if any(token in title for token in ["资源", "片段", "批处理"]):
            return "content"
        if any(token in title for token in ["总线", "混音", "Routing", "Bus", WWISE_MASTER_MIXER_TITLE, WWISE_PROPERTY_EDITOR_TITLE, WWISE_TRANSPORT_TITLE, "Master-Mixer"]):
            return "bus"
        if any(token in title for token in ["校验", "问题"]):
            return "validate"
        if any(token in title for token in ["构建", "导出", "生成", "交付"]):
            return "generate"
        if any(token in title for token in ["响度", "电平", "测量"]):
            return "audio"
        if any(token in title for token in ["日志", "结果", "报告"]):
            return "report"
        if any(token in title for token in ["工程", "欢迎"]):
            return "app"
        return "focus_panel"

    def _card_tone_for_icon(self, icon_name: str) -> str:
        return {
            "event": "event",
            "content": "content",
            "bus": "bus",
            "validate": "validate",
            "generate": "generate",
            "audio": "audio",
            "report": "report",
            "app": "app",
        }.get(icon_name, "neutral")

    def _card_eyebrow_for_icon(self, icon_name: str) -> str:
        return {
            "event": "事件控制",
            "content": "资源编排",
            "bus": "混音路由",
            "validate": "问题修复",
            "generate": "交付流程",
            "audio": "响度监视",
            "report": "结果回看",
            "app": "工程上下文",
            "focus_panel": "当前焦点",
        }.get(icon_name, "当前焦点")

    def _build_card_title_row(self, title: str, icon_name: str | None = None) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        icon_key = icon_name or self._card_icon_name_for_title(title)
        icon = load_app_icon(icon_key)
        if not icon.isNull():
            icon_label = QLabel()
            icon_label.setProperty("role", "cardIconBubble")
            icon_label.setProperty("cardTone", self._card_tone_for_icon(icon_key))
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setFixedSize(36, 36)
            pixmap = icon.pixmap(QSize(18, 18))
            if not pixmap.isNull():
                icon_label.setPixmap(pixmap)
            layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)
        text_column = QWidget()
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        eyebrow_label = QLabel(self._card_eyebrow_for_icon(icon_key))
        eyebrow_label.setObjectName("CardEyebrowLabel")
        eyebrow_label.setProperty("role", "cardEyebrow")
        title_label = QLabel(title)
        title_label.setObjectName("CardTitleLabel")
        title_label.setProperty("role", "workspaceSectionTitle")
        title_label.setWordWrap(True)
        text_layout.addWidget(eyebrow_label)
        text_layout.addWidget(title_label)
        layout.addWidget(text_column, 1)
        return row

    def _wrap_emphasis_card(
        self,
        title: str,
        content: QWidget,
        *,
        description: str | None = None,
        icon_name: str | None = None,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("EmphasisCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self._build_card_title_row(title, icon_name))
        if description:
            description_label = QLabel(description)
            description_label.setWordWrap(True)
            description_label.setProperty("role", "workspaceSectionSummary")
            layout.addWidget(description_label)
        if isinstance(content, QGroupBox):
            content.setTitle("")
            content.setProperty("role", "contentCardInner")
        elif isinstance(content, QFrame):
            content.setProperty("role", "contentCardInnerFrame")
        layout.addWidget(content)
        return card

    def _wrap_workspace_widget(self, widget: QWidget) -> QWidget:
        if isinstance(widget, QGroupBox):
            return self._wrap_emphasis_card(widget.title(), widget)
        return widget

    def _build_workspace_action_bar(
        self,
        title: str,
        summary_label: QLabel,
        actions: list[tuple[str, object, str]],
    ) -> QFrame:
        bar = QFrame()
        bar.setObjectName("WorkspaceActionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        title_label = QLabel(title)
        title_label.setProperty("role", "workspaceSectionTitle")
        summary_label.setProperty("role", "workspaceSectionSummary")
        summary_label.setWordWrap(True)
        text_column.addWidget(title_label)
        text_column.addWidget(summary_label)
        layout.addLayout(text_column, 1)

        for label, handler, icon_name in actions:
            button = QPushButton(label)
            button.setProperty("role", "workspaceActionButton")
            icon = load_app_icon(icon_name)
            if not icon.isNull():
                button.setIcon(icon)
            button.clicked.connect(handler)
            layout.addWidget(button)
        return bar

    def _build_workspace_shortcut_grid(self, shortcut_specs: list[tuple[str, object, str, int, int]]) -> QGridLayout:
        shortcut_grid = QGridLayout()
        shortcut_grid.setContentsMargins(0, 0, 0, 0)
        shortcut_grid.setHorizontalSpacing(8)
        shortcut_grid.setVerticalSpacing(8)
        for label, handler, icon_name, row, column in shortcut_specs:
            button = QPushButton(label)
            button.setProperty("role", "workspaceShortcutButton")
            icon = load_app_icon(icon_name)
            if not icon.isNull():
                button.setIcon(icon)
            button.clicked.connect(handler)
            shortcut_grid.addWidget(button, row, column)
        return shortcut_grid

    def _build_workspace_overview_card(
        self,
        title: str,
        summary_label: QLabel,
        shortcut_specs: list[tuple[str, object, str, int, int]] | None = None,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("WorkspaceOverviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        summary_label.setProperty("role", "workspaceSectionSummary")
        summary_label.setWordWrap(True)
        layout.addWidget(self._build_card_title_row(title))
        layout.addWidget(summary_label)
        if shortcut_specs:
            layout.addLayout(self._build_workspace_shortcut_grid(shortcut_specs))
        return card

    def _build_workspace_note_card(self, title: str, lines: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("WorkspaceOverviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(self._build_card_title_row(title))
        normalized_lines: list[str] = []
        seen_lines: set[str] = set()
        for line in lines:
            normalized = " ".join(str(line).split())
            if not normalized or normalized in seen_lines:
                continue
            normalized_lines.append(normalized)
            seen_lines.add(normalized)
        card.setToolTip("\n".join(normalized_lines))
        for line in normalized_lines:
            label = QLabel(line)
            label.setWordWrap(True)
            label.setProperty("role", "workspaceChecklistLine")
            label.setToolTip(line)
            layout.addWidget(label)
        return card

    def _build_resources_batch_feedback_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("WorkspaceOverviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.resources_batch_feedback_title_label.setProperty("role", "modeCardTitle")
        self.resources_batch_feedback_title_label.setWordWrap(True)
        self.resources_batch_feedback_summary_label.setProperty("role", "workspaceSectionSummary")
        self.resources_batch_feedback_detail_label.setProperty("role", "workspaceChecklistLine")
        self.resources_batch_feedback_summary_label.setWordWrap(True)
        self.resources_batch_feedback_detail_label.setWordWrap(True)
        layout.addWidget(self._build_card_title_row("批量编辑反馈"))
        layout.addWidget(self.resources_batch_feedback_title_label)
        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(6)
        for chip in [
            self.resources_batch_feedback_scope_label,
            self.resources_batch_feedback_count_label,
            self.resources_batch_feedback_field_label,
        ]:
            chip.setProperty("role", "busHeaderChip")
            chip_row.addWidget(chip)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)
        layout.addWidget(self.resources_batch_feedback_summary_label)
        layout.addWidget(self.resources_batch_feedback_detail_label)
        return card

    def clear_resources_batch_feedback(self, event_id: str = "", clip_count: int = 0) -> None:
        self._resources_batch_feedback_event_id = event_id
        self._has_resources_batch_feedback = False
        self.resources_batch_feedback_title_label.setText("等待批量操作" if not event_id else "等待当前事件的批量修改")
        self.resources_batch_feedback_scope_label.setText(f"事件 {event_id or '-'}")
        self.resources_batch_feedback_count_label.setText(f"片段 {clip_count}")
        self.resources_batch_feedback_field_label.setText("字段 等待操作")
        if event_id:
            summary = f"当前事件 {event_id} 共有 {clip_count} 个片段，可继续批量设置权重、前缀、标签或顺序。"
        else:
            summary = "进入“批处理”或使用资源页工具后，这里会显示最近一次成组修改。"
        detail = "支持批量权重、批量属性、批量重命名和排序反馈。"
        self.resources_batch_feedback_summary_label.setText(summary)
        self.resources_batch_feedback_detail_label.setText(detail)
        self.resources_batch_feedback_summary_label.setToolTip(summary)
        self.resources_batch_feedback_detail_label.setToolTip(detail)

    def set_resources_batch_feedback(
        self,
        *,
        event_id: str,
        title: str,
        summary: str,
        detail: str,
        field_summary: str,
        affected_count: int,
    ) -> None:
        self._resources_batch_feedback_event_id = event_id
        self._has_resources_batch_feedback = True
        self.resources_batch_feedback_title_label.setText(title)
        self.resources_batch_feedback_scope_label.setText(f"事件 {event_id or '-'}")
        self.resources_batch_feedback_count_label.setText(f"片段 {affected_count}")
        self.resources_batch_feedback_field_label.setText(f"字段 {field_summary}")
        self.resources_batch_feedback_summary_label.setText(summary)
        self.resources_batch_feedback_detail_label.setText(detail)
        self.resources_batch_feedback_title_label.setToolTip(summary)
        self.resources_batch_feedback_summary_label.setToolTip(summary)
        self.resources_batch_feedback_detail_label.setToolTip(detail)

    def _build_empty_state_card(self, title: str, description: str) -> QFrame:
        card = QFrame()
        card.setObjectName("EmptyStateCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", "emptyStateBody")
        title_row = self._build_card_title_row(title)
        title_label = title_row.findChild(QLabel, "CardTitleLabel")
        if title_label is not None:
            title_label.setProperty("role", "emptyStateTitle")
        layout.addWidget(title_row)
        layout.addWidget(description_label)
        return card

    def _build_events_workspace(self) -> QWidget:
        self.events_workspace_tabs = QTabWidget()
        event_top_section = self._build_two_column_page(
            [self.event_general_group, self.event_behavior_group],
            [self.event_audio_reference_group, self.notes_group],
            splitter_name="EventDesignPageSplitter",
        )
        event_design_page = QWidget()
        event_design_layout = QVBoxLayout(event_design_page)
        event_design_layout.setContentsMargins(0, 0, 0, 0)
        event_design_layout.setSpacing(10)
        event_design_layout.addWidget(event_top_section)
        event_design_layout.addStretch(1)
        self.event_design_scroll = self._wrap_scrollable_page(event_design_page)

        audio_top_section = self._build_two_column_page(
            [self.audio_general_group, self.modulation_group],
            [self.combo_group, self.event_source_binding_group],
            splitter_name="AudioDesignPageSplitter",
        )
        audio_design_page = QWidget()
        audio_design_layout = QVBoxLayout(audio_design_page)
        audio_design_layout.setContentsMargins(0, 0, 0, 0)
        audio_design_layout.setSpacing(10)
        audio_design_layout.addWidget(audio_top_section)
        audio_design_layout.addWidget(self._wrap_workspace_widget(self.event_gamesync_group))
        audio_design_layout.addStretch(1)
        self.audio_design_scroll = self._wrap_scrollable_page(audio_design_page)

        self.events_workspace_tabs.addTab(self.event_design_scroll, load_app_icon("event"), "事件")
        self.events_workspace_tabs.addTab(self.audio_design_scroll, load_app_icon("audio"), "Audio")
        self.events_workspace_tabs.addTab(self.loudness_view, load_app_icon("audio"), "响度监视器")

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                "事件设计",
                self.events_workspace_status_label,
                [
                    ("新建事件", self.createEventRequested.emit, "event"),
                    ("试听对象", self.previewRequested.emit, "play"),
                    ("跟随总线", self._follow_current_event_bus, "bus"),
                ],
            )
        )
        layout.addWidget(self.events_workspace_tabs, 1)
        return workspace

    def _build_event_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(
            self._build_workspace_overview_card(
                "事件概览",
                self.event_overview_hint_label,
                [
                    ("参数画布", lambda: self.events_workspace_tabs.setCurrentIndex(0), "event", 0, 0),
                    ("响度监视", self.show_loudness_view, "audio", 0, 1),
                    ("资源片段", lambda: self.set_active_contents_category("片段"), "content", 1, 0),
                    ("进入校验修复", lambda: self._activate_workspace_mode("validation"), "validate", 1, 1),
                ],
            )
        )
        layout.addWidget(self._wrap_emphasis_card("当前对象", self.object_header_frame, icon_name="event"))
        layout.addStretch(1)
        return panel

    def _build_resources_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "资源工作流",
                self.resources_overview_hint_label,
                [
                    ("片段编排", lambda: self.set_active_contents_category("片段"), "content", 0, 0),
                    ("批处理", lambda: self.set_active_contents_category("批处理"), "audio", 0, 1),
                    ("生成预览", lambda: self.set_active_contents_category("生成"), "generate", 1, 0),
                    ("事件设计", lambda: self._activate_workspace_mode("events"), "event", 1, 1),
                ],
            )
        )
        layout.addWidget(self._build_resources_batch_feedback_card())
        layout.addStretch(1)
        return panel

    def _build_resources_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                "资源整理",
                self.resources_workspace_status_label,
                [
                    ("导入音频", self._request_clip_import, "content"),
                    ("批量权重", self._request_bulk_weight, "audio"),
                    ("生成预览", lambda: self.set_active_contents_category("生成"), "generate"),
                ],
            )
        )
        layout.addWidget(self.contents_tabs, 1)
        return workspace

    def _create_curve_table(self) -> RtpcCurveEditor:
        editor = RtpcCurveEditor()
        editor.setMinimumHeight(164)
        return editor

    def _build_curve_editor_panel(
        self,
        table: RtpcCurveEditor,
        interpolation_combo: QComboBox,
        add_button: QPushButton,
        remove_button: QPushButton,
    ) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        curve_hint = QLabel("曲线点")
        curve_hint.setProperty("role", "workspaceSectionTitle")
        action_row.addWidget(curve_hint)
        action_row.addWidget(interpolation_combo)
        action_row.addStretch(1)
        action_row.addWidget(add_button)
        action_row.addWidget(remove_button)
        layout.addLayout(action_row)
        layout.addWidget(table)
        return panel

    def _build_gamesync_parameter_editor(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.gamesync_parameter_add_button)
        action_row.addWidget(self.gamesync_parameter_remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("参数名", self.gamesync_parameter_name_edit)
        form.addRow("默认值", self.gamesync_parameter_default_spin)
        form.addRow("最小值", self.gamesync_parameter_min_spin)
        form.addRow("最大值", self.gamesync_parameter_max_spin)
        layout.addLayout(action_row)
        layout.addLayout(form)
        layout.addWidget(self.gamesync_parameter_notes_edit, 1)
        return panel

    def _build_gamesync_state_editor(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.gamesync_state_add_button)
        action_row.addWidget(self.gamesync_state_remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("组名", self.gamesync_state_name_edit)
        form.addRow("默认 State", self.gamesync_state_default_edit)
        child_actions = QHBoxLayout()
        child_actions.setContentsMargins(0, 0, 0, 0)
        child_actions.setSpacing(8)
        child_actions.addWidget(self.gamesync_state_value_add_button)
        child_actions.addWidget(self.gamesync_state_value_remove_button)
        child_actions.addStretch(1)
        self.gamesync_state_value_list.setAlternatingRowColors(True)
        layout.addLayout(action_row)
        layout.addLayout(form)
        layout.addWidget(QLabel("State 子项"))
        layout.addLayout(child_actions)
        layout.addWidget(self.gamesync_state_value_list)
        layout.addWidget(self.gamesync_state_values_edit)
        state_effect_form = QFormLayout()
        state_effect_form.addRow("音量效果", self.gamesync_state_value_volume_spin)
        state_effect_form.addRow("音高效果", self.gamesync_state_value_pitch_spin)
        state_effect_form.addRow("静音效果", self.gamesync_state_value_mute_check)
        layout.addLayout(state_effect_form)
        layout.addWidget(self.gamesync_state_value_notes_edit)
        layout.addWidget(self.gamesync_state_notes_edit, 1)
        return panel

    def _build_gamesync_switch_editor(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.gamesync_switch_add_button)
        action_row.addWidget(self.gamesync_switch_remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("组名", self.gamesync_switch_name_edit)
        form.addRow("默认 Switch", self.gamesync_switch_default_edit)
        form.addRow("映射模式", self.gamesync_switch_use_rtpc_check)
        form.addRow("Game Parameter", self.gamesync_switch_mapped_parameter_edit)
        child_actions = QHBoxLayout()
        child_actions.setContentsMargins(0, 0, 0, 0)
        child_actions.setSpacing(8)
        child_actions.addWidget(self.gamesync_switch_value_add_button)
        child_actions.addWidget(self.gamesync_switch_value_remove_button)
        child_actions.addStretch(1)
        self.gamesync_switch_value_list.setAlternatingRowColors(True)
        layout.addLayout(action_row)
        layout.addLayout(form)
        layout.addWidget(QLabel("Switch 子项"))
        layout.addLayout(child_actions)
        layout.addWidget(self.gamesync_switch_value_list)
        layout.addWidget(self.gamesync_switch_values_edit)
        switch_effect_form = QFormLayout()
        switch_effect_form.addRow("音量效果", self.gamesync_switch_value_volume_spin)
        switch_effect_form.addRow("音高效果", self.gamesync_switch_value_pitch_spin)
        switch_effect_form.addRow("静音效果", self.gamesync_switch_value_mute_check)
        layout.addLayout(switch_effect_form)
        layout.addWidget(self.gamesync_switch_value_notes_edit)
        layout.addWidget(self.gamesync_switch_notes_edit, 1)
        return panel

    def _build_rtpc_binding_editor(
        self,
        list_widget: QListWidget,
        add_button: QPushButton,
        remove_button: QPushButton,
        parameter_edit: QLineEdit,
        target_combo: QComboBox,
        scope_combo: QComboBox,
        curve_table: RtpcCurveEditor,
        interpolation_combo: QComboBox,
        add_point_button: QPushButton,
        remove_point_button: QPushButton,
        selected_input_spin: QDoubleSpinBox,
        selected_output_spin: QDoubleSpinBox,
        snap_check: QCheckBox,
        snap_x_spin: QDoubleSpinBox,
        snap_y_spin: QDoubleSpinBox,
        notes_edit: QPlainTextEdit,
    ) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(add_button)
        action_row.addWidget(remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("Game Parameter", parameter_edit)
        form.addRow("目标", target_combo)
        form.addRow("作用域", scope_combo)
        list_widget.setAlternatingRowColors(True)
        layout.addLayout(action_row)
        layout.addWidget(list_widget)
        layout.addLayout(form)
        layout.addWidget(self._build_curve_editor_panel(curve_table, interpolation_combo, add_point_button, remove_point_button))
        layout.addWidget(self._build_curve_detail_panel(selected_input_spin, selected_output_spin, snap_check, snap_x_spin, snap_y_spin))
        layout.addWidget(notes_edit, 1)
        return panel

    def _build_curve_detail_panel(
        self,
        selected_input_spin: QDoubleSpinBox,
        selected_output_spin: QDoubleSpinBox,
        snap_check: QCheckBox,
        snap_x_spin: QDoubleSpinBox,
        snap_y_spin: QDoubleSpinBox,
    ) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewCard")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addWidget(QLabel("选中点输入"))
        layout.addWidget(selected_input_spin)
        layout.addWidget(QLabel("输出"))
        layout.addWidget(selected_output_spin)
        layout.addSpacing(10)
        layout.addWidget(snap_check)
        layout.addWidget(QLabel("X 步长"))
        layout.addWidget(snap_x_spin)
        layout.addWidget(QLabel("Y 步长"))
        layout.addWidget(snap_y_spin)
        layout.addStretch(1)
        return panel

    def _build_state_override_editor(
        self,
        list_widget: QListWidget,
        add_button: QPushButton,
        remove_button: QPushButton,
        group_edit: QLineEdit,
        state_edit: QLineEdit,
        volume_spin: QDoubleSpinBox,
        pitch_spin: QSpinBox,
        mute_check: QCheckBox,
        notes_edit: QPlainTextEdit,
    ) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(add_button)
        action_row.addWidget(remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("State Group", group_edit)
        form.addRow("State", state_edit)
        form.addRow("音量覆盖", volume_spin)
        form.addRow("音高覆盖", pitch_spin)
        form.addRow("静音", mute_check)
        list_widget.setAlternatingRowColors(True)
        layout.addLayout(action_row)
        layout.addWidget(list_widget)
        layout.addLayout(form)
        layout.addWidget(notes_edit, 1)
        return panel

    def _build_switch_variant_editor(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.event_switch_add_button)
        action_row.addWidget(self.event_switch_remove_button)
        action_row.addStretch(1)
        form = QFormLayout()
        form.addRow("Switch Group", self.event_switch_group_edit)
        form.addRow("Switch", self.event_switch_name_edit)
        form.addRow("Clip IDs", self.event_switch_clip_ids_edit)
        self.event_switch_list.setAlternatingRowColors(True)
        layout.addLayout(action_row)
        layout.addWidget(self.event_switch_list)
        layout.addLayout(form)
        layout.addWidget(self.event_switch_notes_edit, 1)
        return panel

    def _build_event_gamesync_group(self) -> QGroupBox:
        group = QGroupBox("Audio GameSync 绑定")
        layout = QVBoxLayout(group)
        self.event_gamesync_context_label = QLabel("当前 Audio：-")
        self.event_gamesync_context_label.setProperty("role", "workspaceSectionSummary")
        self.event_gamesync_context_label.setWordWrap(True)
        tabs = QTabWidget()
        tabs.addTab(
            self._build_rtpc_binding_editor(
                self.event_rtpc_list,
                self.event_rtpc_add_button,
                self.event_rtpc_remove_button,
                self.event_rtpc_parameter_edit,
                self.event_rtpc_target_combo,
                self.event_rtpc_scope_combo,
                self.event_rtpc_curve_table,
                self.event_rtpc_interpolation_combo,
                self.event_rtpc_add_point_button,
                self.event_rtpc_remove_point_button,
                self.event_rtpc_selected_input_spin,
                self.event_rtpc_selected_output_spin,
                self.event_rtpc_snap_check,
                self.event_rtpc_snap_x_spin,
                self.event_rtpc_snap_y_spin,
                self.event_rtpc_notes_edit,
            ),
            load_app_icon("rtpc"),
            "RTPC",
        )
        tabs.addTab(
            self._build_state_override_editor(
                self.event_state_list,
                self.event_state_add_button,
                self.event_state_remove_button,
                self.event_state_group_edit,
                self.event_state_name_edit,
                self.event_state_volume_spin,
                self.event_state_pitch_spin,
                self.event_state_mute_check,
                self.event_state_notes_edit,
            ),
            load_app_icon("state"),
            "State",
        )
        tabs.addTab(self._build_switch_variant_editor(), load_app_icon("switch"), "Switch")
        layout.addWidget(self.event_gamesync_context_label)
        layout.addWidget(tabs)
        self.event_gamesync_tabs = tabs
        return group

    def _build_bus_gamesync_group(self) -> QGroupBox:
        group = QGroupBox("Bus GameSync 绑定")
        layout = QVBoxLayout(group)
        tabs = QTabWidget()
        tabs.addTab(
            self._build_rtpc_binding_editor(
                self.bus_rtpc_list,
                self.bus_rtpc_add_button,
                self.bus_rtpc_remove_button,
                self.bus_rtpc_parameter_edit,
                self.bus_rtpc_target_combo,
                self.bus_rtpc_scope_combo,
                self.bus_rtpc_curve_table,
                self.bus_rtpc_interpolation_combo,
                self.bus_rtpc_add_point_button,
                self.bus_rtpc_remove_point_button,
                self.bus_rtpc_selected_input_spin,
                self.bus_rtpc_selected_output_spin,
                self.bus_rtpc_snap_check,
                self.bus_rtpc_snap_x_spin,
                self.bus_rtpc_snap_y_spin,
                self.bus_rtpc_notes_edit,
            ),
            load_app_icon("rtpc"),
            "RTPC",
        )
        tabs.addTab(
            self._build_state_override_editor(
                self.bus_state_list,
                self.bus_state_add_button,
                self.bus_state_remove_button,
                self.bus_state_group_edit,
                self.bus_state_name_edit,
                self.bus_state_volume_spin,
                self.bus_state_pitch_spin,
                self.bus_state_mute_check,
                self.bus_state_notes_edit,
            ),
            load_app_icon("state"),
            "State",
        )
        layout.addWidget(tabs)
        self.bus_gamesync_tabs = tabs
        return group

    def _build_gamesync_entry_panel(
        self,
        title: str,
        summary: str,
        list_widget: QListWidget,
        detail_label: QLabel,
        editor_widget: QWidget | None = None,
    ) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setProperty("role", "workspaceSectionTitle")
        summary_label = QLabel(summary)
        summary_label.setProperty("role", "workspaceSectionSummary")
        summary_label.setWordWrap(True)
        list_widget.setAlternatingRowColors(True)
        detail_card = QFrame()
        detail_card.setObjectName("WorkspaceOverviewCard")
        detail_layout = QVBoxLayout(detail_card)
        detail_layout.setContentsMargins(12, 10, 12, 10)
        detail_layout.setSpacing(6)
        detail_label.setWordWrap(True)
        detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(detail_label)
        layout.addWidget(title_label)
        layout.addWidget(summary_label)
        layout.addWidget(list_widget, 1)
        layout.addWidget(detail_card)
        if editor_widget is not None:
            layout.addWidget(editor_widget, 1)
        return panel

    def _build_gamesync_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "GameSync 概览",
                self.gamesync_overview_hint_label,
                [
                    ("概览", lambda: self.gamesync_workspace_tabs.setCurrentIndex(0), "curve", 0, 0),
                    ("参数", lambda: self.gamesync_workspace_tabs.setCurrentIndex(1), "rtpc", 0, 1),
                    ("State", lambda: self.gamesync_workspace_tabs.setCurrentIndex(2), "state", 1, 0),
                    ("Switch", lambda: self.gamesync_workspace_tabs.setCurrentIndex(3), "switch", 1, 1),
                ],
            )
        )
        stats_card = QFrame()
        stats_card.setObjectName("WorkspaceOverviewCard")
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(12, 10, 12, 10)
        stats_layout.setSpacing(6)
        self.gamesync_overview_total_label.setProperty("role", "workspaceSectionTitle")
        self.gamesync_overview_detail_label.setProperty("role", "workspaceSectionSummary")
        self.gamesync_overview_detail_label.setWordWrap(True)
        stats_layout.addWidget(self.gamesync_overview_total_label)
        stats_layout.addWidget(self.gamesync_overview_detail_label)
        layout.addWidget(stats_card)
        layout.addWidget(
            self._build_workspace_note_card(
                "阶段边界",
                [
                    "项目级对象、事件绑定、总线绑定统一走工程模型，避免 authoring 数据散落在 UI 状态里。",
                    "曲线模型先对齐 Wwise 心智，运行时 Schema v2 与 Unity API 仍留在后续 phase3 runtime 接入。",
                ],
            )
        )
        layout.addStretch(1)
        return panel

    def _build_gamesync_workspace(self) -> QWidget:
        self.gamesync_workspace_tabs.addTab(self._build_gamesync_overview_panel(), load_app_icon("curve"), "概览")
        self.gamesync_workspace_tabs.addTab(
            self._build_gamesync_entry_panel(
                "Game Parameters",
                "项目级连续参数，驱动 RTPC 曲线与运行时全局参数。",
                self.gamesync_parameter_workspace_list,
                self.gamesync_parameter_workspace_detail_label,
                self._build_gamesync_parameter_editor(),
            ),
            load_app_icon("rtpc"),
            "参数",
        )
        self.gamesync_workspace_tabs.addTab(
            self._build_gamesync_entry_panel(
                "State Groups",
                "项目级全局离散模式，用于事件与总线属性覆盖。",
                self.gamesync_state_workspace_list,
                self.gamesync_state_workspace_detail_label,
                self._build_gamesync_state_editor(),
            ),
            load_app_icon("state"),
            "State",
        )
        self.gamesync_workspace_tabs.addTab(
            self._build_gamesync_entry_panel(
                "Switch Groups",
                "项目级 emitter 分支列表，用于事件内部变体切换。",
                self.gamesync_switch_workspace_list,
                self.gamesync_switch_workspace_detail_label,
                self._build_gamesync_switch_editor(),
            ),
            load_app_icon("switch"),
            "Switch",
        )

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                "GameSync",
                self.gamesync_workspace_status_label,
                [
                    ("概览", lambda: self.gamesync_workspace_tabs.setCurrentIndex(0), "curve"),
                    ("参数", lambda: self.gamesync_workspace_tabs.setCurrentIndex(1), "rtpc"),
                    ("State", lambda: self.gamesync_workspace_tabs.setCurrentIndex(2), "state"),
                    ("Switch", lambda: self.gamesync_workspace_tabs.setCurrentIndex(3), "switch"),
                ],
            )
        )
        layout.addWidget(self.gamesync_workspace_tabs, 1)
        return workspace

    def _build_buses_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "Bus 导航",
                self.buses_overview_hint_label,
                [
                    (f"跟随 {WWISE_OUTPUT_BUS_LABEL}", self._follow_current_event_bus, "bus", 0, 0),
                    (f"切到 {WWISE_PARENT_BUS_LABEL}", self._select_parent_bus_for_current, "route", 0, 1),
                    (WWISE_MASTER_AUDIO_BUS_TITLE, lambda: self._select_project_bus_by_name("Master"), "generate", 1, 0),
                    ("回到事件", lambda: self._activate_workspace_mode("events"), "event", 1, 1),
                ],
            )
        )
        layout.addWidget(self._wrap_emphasis_card("工程设置", self.project_settings_group, icon_name="app"))
        layout.addStretch(1)
        return panel

    def _build_buses_workspace(self) -> QWidget:
        self.buses_workspace_tabs = QTabWidget()

        current_bus_page = QWidget()
        current_bus_layout = QVBoxLayout(current_bus_page)
        current_bus_layout.setContentsMargins(0, 0, 0, 0)
        current_bus_layout.setSpacing(10)
        current_bus_layout.addWidget(self._wrap_workspace_widget(self.inline_bus_group))
        current_bus_layout.addStretch(1)
        self.current_bus_workspace_scroll = self._wrap_scrollable_page(current_bus_page)

        bus_overview_page = QWidget()
        bus_overview_layout = QVBoxLayout(bus_overview_page)
        bus_overview_layout.setContentsMargins(0, 0, 0, 0)
        bus_overview_layout.setSpacing(10)
        bus_overview_layout.addWidget(self.project_splitter)
        bus_overview_layout.addStretch(1)
        self.bus_overview_workspace_scroll = self._wrap_scrollable_page(bus_overview_page)

        bus_gamesync_page = QWidget()
        bus_gamesync_layout = QVBoxLayout(bus_gamesync_page)
        bus_gamesync_layout.setContentsMargins(0, 0, 0, 0)
        bus_gamesync_layout.setSpacing(10)
        bus_gamesync_layout.addWidget(self._wrap_workspace_widget(self.bus_gamesync_group))
        bus_gamesync_layout.addStretch(1)
        self.bus_gamesync_workspace_scroll = self._wrap_scrollable_page(bus_gamesync_page)

        self.buses_workspace_tabs.addTab(self.current_bus_workspace_scroll, load_app_icon("bus"), "当前 Bus")
        self.buses_workspace_tabs.addTab(self.bus_overview_workspace_scroll, load_app_icon("route"), "工程总览")
        self.buses_workspace_tabs.addTab(self.bus_gamesync_workspace_scroll, load_app_icon("rtpc"), "Bus GameSync")

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                WWISE_MASTER_MIXER_TITLE,
                self.buses_workspace_status_label,
                [
                    ("新建 Bus", self._request_add_project_bus, "bus"),
                    (f"设为 {WWISE_DEFAULT_BUS_LABEL}", self._set_current_bus_as_default, "generate"),
                    (f"挂到 {WWISE_MASTER_AUDIO_BUS_TITLE}", self._route_current_bus_to_master, "route"),
                ],
            )
        )
        layout.addWidget(self.buses_workspace_tabs, 1)
        return workspace

    def _build_build_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "交付流程",
                self.build_overview_hint_label,
                [
                    ("校验修复", lambda: self._activate_workspace_mode("validation"), "validate", 0, 0),
                    ("结果中心", lambda: self._activate_workspace_mode("results"), "report", 0, 1),
                    ("日志结果", lambda: self.show_report_tab(0), "report", 1, 0),
                    ("响度结果", lambda: self.show_report_tab(3), "audio", 1, 1),
                ],
            )
        )
        layout.addWidget(self._wrap_emphasis_card("导出设置", self.generation_settings_group, icon_name="generate"))
        layout.addWidget(self._wrap_emphasis_card("生成概览", self.build_overview_group, icon_name="report"))
        layout.addStretch(1)
        return panel

    def _build_build_workspace(self) -> QWidget:
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(self.build_preview_group, 1)
        build_execute_row = QHBoxLayout()
        build_execute_row.setContentsMargins(0, 0, 0, 0)
        build_execute_row.setSpacing(8)
        self.build_execute_button.setProperty("role", "workspaceActionButton")
        build_execute_row.addWidget(self.build_execute_button)
        build_execute_row.addStretch(1)
        right_layout.addLayout(build_execute_row)

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                "构建交付",
                self.build_workspace_status_label,
                [
                    ("校验", self.validate_button.click, "validate"),
                    ("导出差异", self.previewExportDiffRequested.emit, "report"),
                    ("开始构建", self.buildRequested.emit, "generate"),
                ],
            )
        )
        layout.addWidget(
            self._build_two_column_page(
                [self.generation_settings_group],
                [self.build_overview_group],
                splitter_name="BuildControlsSplitter",
            )
        )
        layout.addWidget(right_panel, 1)
        return workspace

    def _build_validation_overview_panel(self, filter_card: QWidget) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "校验工作流",
                self.validation_overview_hint_label,
                [
                    ("校验结果页", lambda: self.show_report_tab(1), "validate", 0, 0),
                    ("构建交付", lambda: self._activate_workspace_mode("build"), "generate", 0, 1),
                    ("事件设计", lambda: self._activate_workspace_mode("events"), "event", 1, 0),
                    ("资源整理", lambda: self._activate_workspace_mode("resources"), "content", 1, 1),
                ],
            )
        )
        layout.addWidget(filter_card)
        layout.addWidget(self.validation_filter_status_label)
        layout.addStretch(1)
        return panel

    def _build_validation_workspace(self) -> QWidget:
        filter_card = QFrame()
        filter_card.setObjectName("ModeIntroCard")
        filter_layout = QHBoxLayout(filter_card)
        filter_layout.setContentsMargins(14, 12, 14, 12)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(QLabel("问题级别"))
        filter_layout.addWidget(self.validation_filter_severity_combo)
        filter_layout.addWidget(QLabel("关键字"))
        filter_layout.addWidget(self.validation_filter_keyword_edit, 1)
        filter_layout.addWidget(self.validation_filter_reset_button)
        filter_layout.addWidget(self.validation_revalidate_button)
        filter_layout.addWidget(self.validation_locate_button)

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(filter_card)
        layout.addWidget(self.validation_filter_status_label)
        layout.addWidget(
            self._build_report_center_page(
                self.validation_summary_label,
                self.validation_issue_list,
                self.validation_report_output,
                splitter_name="ValidationReportCenterSplitter",
            ),
            1,
        )
        return workspace

    def _current_property_scroll_widget(self) -> QWidget | None:
        return self._current_property_compat_widget()

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("WelcomeHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 18, 20, 18)
        hero_layout.setSpacing(6)
        title = QLabel("欢迎进入新的 AudioForge AppShell")
        title.setProperty("role", "welcomeTitle")
        subtitle = QLabel("先新建或打开工程，再直接进入事件、资源、Bus 或结果工作流。")
        subtitle.setWordWrap(True)
        subtitle.setProperty("role", "welcomeDescription")
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 6, 0, 0)
        action_row.setSpacing(8)
        new_button = QPushButton("新建工程")
        open_button = QPushButton("打开工程")
        events_button = QPushButton("进入事件设计")
        results_button = QPushButton("查看结果中心")
        new_button.clicked.connect(self.new_project_button.click)
        open_button.clicked.connect(self.open_project_button.click)
        events_button.clicked.connect(lambda: self._activate_workspace_mode("events"))
        results_button.clicked.connect(lambda: self._activate_workspace_mode("results"))
        action_row.addWidget(new_button)
        action_row.addWidget(open_button)
        action_row.addWidget(events_button)
        action_row.addWidget(results_button)
        action_row.addStretch(1)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addLayout(action_row)

        project_snapshot = QFrame()
        project_snapshot.setObjectName("WorkspaceOverviewCard")
        project_snapshot_layout = QVBoxLayout(project_snapshot)
        project_snapshot_layout.setContentsMargins(12, 10, 12, 10)
        project_snapshot_layout.setSpacing(6)
        project_snapshot_layout.addWidget(self._build_card_title_row("当前工程", "app"))
        snapshot_header = QHBoxLayout()
        snapshot_header.setContentsMargins(0, 0, 0, 0)
        snapshot_header.setSpacing(8)
        self.welcome_dirty_label.setProperty("role", "busHeaderChip")
        snapshot_header.addWidget(self.welcome_project_title_label, 1)
        snapshot_header.addWidget(self.welcome_dirty_label)
        project_snapshot_layout.addLayout(snapshot_header)
        project_snapshot_layout.addWidget(self.welcome_project_path_label)
        quick_entry_summary = QLabel("直接进入核心工作区，不再从首页层层钻取。")
        quick_entry = self._build_workspace_overview_card(
            "首屏快捷跳转",
            quick_entry_summary,
            [
                ("事件设计", lambda: self._activate_workspace_mode("events"), "event", 0, 0),
                ("资源整理", lambda: self._activate_workspace_mode("resources"), "content", 0, 1),
                (WWISE_MASTER_MIXER_TITLE, lambda: self._activate_workspace_mode("buses"), "bus", 1, 0),
                ("GameSync", lambda: self._activate_workspace_mode("gamesync"), "generate", 1, 1),
                ("结果中心", lambda: self._activate_workspace_mode("results"), "report", 2, 0),
            ],
        )
        first_run_note = self._build_workspace_note_card(
            "首次闭环",
            [
                "资源整理 -> 事件设计 -> 构建交付。",
                "结果中心负责回看；编辑动作仍在各工作区完成。",
            ],
        )

        layout.addWidget(hero)
        layout.addWidget(project_snapshot)
        layout.addWidget(quick_entry)
        layout.addWidget(first_run_note)
        layout.addStretch(1)
        return self._wrap_scrollable_page(page)

    def _build_log_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("日志中心", "集中查看运行日志、导入反馈和交付链路输出；当没有问题时，这里主要承担追踪和回溯职责。"))
        results_splitter = QSplitter()
        results_splitter.setObjectName("LogResultsSplitter")
        results_splitter.setOrientation(Qt.Orientation.Horizontal)
        results_splitter.setChildrenCollapsible(False)
        results_splitter.addWidget(
            self._build_workspace_note_card(
                "日志用途",
                [
                    "导入反馈、构建输出和异常日志都统一在这里回看。",
                    "如果日志已经定位到对象，可从左侧导航切回对应工作区继续修订。",
                ],
            )
        )
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.addWidget(self.log_output)
        results_splitter.addWidget(log_group)
        results_splitter.setStretchFactor(0, 2)
        results_splitter.setStretchFactor(1, 5)
        layout.addWidget(results_splitter, 1)
        layout.addWidget(self._build_empty_state_card("日志区当前为空", "这通常意味着你刚打开工程，或者当前操作还没有触发导入、校验或构建链路。"))
        return page

    def _build_diagnostic_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_mode_surface_card(
                "诊断概览",
                "把最近日志、校验、构建、响度和 Bus 上下文统一收口到同一页；这里只做汇总和导航，不复制原有模块。",
            )
        )
        layout.addWidget(
            self._build_workspace_note_card(
                "当前约束",
                [
                    "不改 Unity 对接 SDK，也不改既有导出契约语义。",
                    "诊断页只复用现有结果中心、结果坞和 Bus 状态，不新起平行模块。",
                ],
            )
        )

        summary_group = QGroupBox("当前诊断快照")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(8)
        self.diagnostic_summary_label.setWordWrap(True)
        self.diagnostic_summary_label.setProperty("role", "modeCardDescription")
        summary_layout.addWidget(self.diagnostic_summary_label)

        sections_group = QGroupBox("统一 Section 视图")
        sections_layout = QVBoxLayout(sections_group)
        sections_layout.setContentsMargins(12, 10, 12, 10)
        sections_layout.setSpacing(8)
        section_hint = QLabel("双击条目可跳转到对应对象；颜色与排序直接继承控制器的 section 状态。")
        section_hint.setProperty("role", "workspaceSectionSummary")
        section_hint.setWordWrap(True)
        sections_layout.addWidget(section_hint)
        section_splitter = QSplitter()
        section_splitter.setObjectName("DiagnosticSectionsSplitter")
        section_splitter.setOrientation(Qt.Orientation.Horizontal)
        section_splitter.setChildrenCollapsible(False)
        section_splitter.addWidget(self.diagnostic_section_list)
        section_splitter.addWidget(self.diagnostic_section_detail_output)
        section_splitter.setStretchFactor(0, 2)
        section_splitter.setStretchFactor(1, 3)
        sections_layout.addWidget(section_splitter, 1)

        layout.addWidget(summary_group)
        layout.addWidget(sections_group, 1)
        layout.addWidget(self._build_empty_state_card("诊断页已就绪", "这里默认显示最近一次日志、校验、构建、响度和 Bus 上下文；后续只在现有链路上继续加深，不扩成第二套系统。"))
        return page

    def _build_validation_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("校验结果入口", "校验问题已经收口到“校验修复”工作流页。你仍然可以从结果导航直接进入那里继续修复。"))
        layout.addWidget(
            self._build_workspace_overview_card(
                "继续修复",
                QLabel("结果专页只保留回看入口，真正的筛选与定位动作集中在校验修复页。"),
                [
                    ("进入校验修复", lambda: self._activate_workspace_mode("validation"), "validate", 0, 0),
                    ("回到事件设计", lambda: self._activate_workspace_mode("events"), "event", 0, 1),
                ],
            )
        )
        layout.addWidget(self._build_empty_state_card("还没有新的校验批次", "当你还没有运行校验，或者当前问题已全部清空时，这里只保留回看和跳转入口。"))
        layout.addStretch(1)
        return page

    def _build_build_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("构建结果", "将构建摘要、问题定位和完整输出固定为交付专页，不再和其他结果共享同一组 tab。"))
        top_splitter = QSplitter()
        top_splitter.setObjectName("BuildResultsSplitter")
        top_splitter.setOrientation(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(
            self._build_report_center_page(
                self.build_summary_label,
                self.build_issue_list,
                self.build_report_output,
                splitter_name="BuildReportCenterSplitter",
            )
        )
        preview_group = QGroupBox("交付预览")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.addWidget(self.build_preview_output)
        top_splitter.addWidget(preview_group)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)
        layout.addWidget(top_splitter, 1)
        layout.addWidget(self._build_empty_state_card("还没有构建批次", "先运行差异预览或构建导出，这里才会出现交付摘要、问题定位和完整输出。"))
        return page

    def _build_loudness_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("响度结果", "把超标项、条目细节和扫描输出固定成独立结果页，便于与事件修订来回切换。"))
        loudness_splitter = QSplitter()
        loudness_splitter.setObjectName("LoudnessResultsSplitter")
        loudness_splitter.setOrientation(Qt.Orientation.Horizontal)
        loudness_splitter.setChildrenCollapsible(False)
        loudness_splitter.addWidget(
            self._build_workspace_note_card(
                "扫描回路",
                [
                    "先看超标项，再回到事件设计做音量或随机范围修订。",
                    "响度专页负责结论回看，参数调整仍在事件工作区完成。",
                ],
            )
        )
        loudness_splitter.addWidget(
            self._build_report_center_page(
                self.loudness_summary_label,
                self.loudness_issue_list,
                self.loudness_report_output,
                splitter_name="LoudnessReportCenterSplitter",
            )
        )
        loudness_splitter.setStretchFactor(0, 2)
        loudness_splitter.setStretchFactor(1, 5)
        layout.addWidget(loudness_splitter, 1)
        layout.addWidget(self._build_empty_state_card("还没有扫描结果", "先执行响度扫描，再回到这里查看超标项、通过项和逐条说明。"))
        return page

    def _build_results_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_overview_card(
                "结果导航",
                self.results_overview_hint_label,
                [
                    ("日志", lambda: self.show_report_tab(0), "report", 0, 0),
                    ("校验", lambda: self.show_report_tab(1), "validate", 0, 1),
                    ("构建", lambda: self.show_report_tab(2), "generate", 1, 0),
                    ("响度", lambda: self.show_report_tab(3), "audio", 1, 1),
                    ("诊断", lambda: self.show_report_tab(4), "report", 2, 0),
                ],
            )
        )
        layout.addStretch(1)
        return panel

    def _build_results_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_panel_header("结果中心", "log"))
        layout.addWidget(self.report_header)
        layout.addWidget(self.report_pages, 1)
        return panel

    def _update_activity_panel_status(self) -> None:
        """Update the single-line status indicator in the audition center header."""
        if not hasattr(self, "activity_status_indicator"):
            return
        snapshot = getattr(self, "_diagnostic_snapshot_data", {})
        validation = str(snapshot.get("validation_summary", "") or "")
        build = str(snapshot.get("build_summary", "") or "")
        log_text = str(snapshot.get("log_summary", "") or "")

        parts: list[str] = []
        if validation:
            parts.append(validation)
        if build:
            parts.append(build)
        if not parts and log_text:
            parts.append(log_text)
        if not parts:
            parts.append("等待校验、构建或日志结果。")

        summary = " · ".join(parts)
        display = summary if len(summary) <= 96 else f"{summary[:93]}..."
        self.activity_status_indicator.setText(display)
        self.activity_status_indicator.setToolTip(summary)

    def _set_activity_summary_text(self, label: QLabel, text: str, *, fallback: str) -> None:
        normalized = " ".join(text.split()) if text else ""
        normalized = normalized or fallback
        display = normalized if len(normalized) <= 72 else f"{normalized[:69]}..."
        label.setText(display)
        label.setToolTip(normalized)

    def _apply_activity_panel_presentation(self) -> None:
        if not hasattr(self, "activity_panel"):
            return
        self.activity_panel.setMinimumHeight(self._minimum_report_panel_height)
        self.activity_panel.setMaximumHeight(16777215)

    def _first_report_item_detail(self, list_widget: QListWidget) -> str:
        item = list_widget.item(0)
        if item is None:
            return ""
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        return str(payload.get("detail", item.toolTip() or item.text())).strip()

    def _update_diagnostic_snapshot_labels(self) -> None:
        snapshot = self._diagnostic_snapshot_data
        self._set_activity_summary_text(
            self.diagnostic_log_summary_label,
            str(snapshot.get("log_summary", "")),
            fallback="最近日志：等待运行输出。",
        )
        self._set_activity_summary_text(
            self.diagnostic_validation_summary_label,
            str(snapshot.get("validation_summary", "")),
            fallback="等待校验。",
        )
        self._set_activity_summary_text(
            self.diagnostic_build_summary_label,
            str(snapshot.get("build_summary", "")),
            fallback="等待构建或差异预览。",
        )
        self._set_activity_summary_text(
            self.diagnostic_loudness_summary_label,
            str(snapshot.get("loudness_summary", "")),
            fallback="等待响度扫描。",
        )
        self._set_activity_summary_text(
            self.diagnostic_bus_summary_label,
            str(snapshot.get("bus_summary", "")),
            fallback="等待 Bus 上下文。",
        )
        self._set_activity_summary_text(
            self.diagnostic_summary_label,
            str(snapshot.get("summary", "")),
            fallback="诊断概览已接入结果中心；这里统一汇总日志、校验、构建、响度和 Bus 状态。",
        )
        self._update_activity_panel_status()

    def _update_snapshot_report_panel(
        self,
        list_widget: QListWidget,
        output: QPlainTextEdit,
        items: list[dict[str, object]],
        empty_text: str,
    ) -> None:
        panel_state = self._capture_report_panel_state(list_widget, output)
        self._set_report_items(list_widget, items)
        if list_widget.count():
            self._update_report_detail_from_item(list_widget, output)
        else:
            output.setPlainText(empty_text)
        self._restore_report_panel_state(list_widget, output, panel_state)
        if list_widget.count():
            self._update_report_detail_from_item(list_widget, output)
        else:
            output.setPlainText(empty_text)

    def set_diagnostic_snapshot(self, snapshot: dict[str, object]) -> None:
        section_items = snapshot.get("sections", self._diagnostic_snapshot_data.get("sections", []))
        build_profile_items = snapshot.get("build_profile", self._diagnostic_snapshot_data.get("build_profile", []))
        self._diagnostic_snapshot_data = {
            "summary": str(snapshot.get("summary", self._diagnostic_snapshot_data.get("summary", ""))),
            "log_summary": str(snapshot.get("log_summary", self._diagnostic_snapshot_data.get("log_summary", ""))),
            "validation_summary": str(snapshot.get("validation_summary", self._diagnostic_snapshot_data.get("validation_summary", ""))),
            "build_summary": str(snapshot.get("build_summary", self._diagnostic_snapshot_data.get("build_summary", ""))),
            "loudness_summary": str(snapshot.get("loudness_summary", self._diagnostic_snapshot_data.get("loudness_summary", ""))),
            "bus_summary": str(snapshot.get("bus_summary", self._diagnostic_snapshot_data.get("bus_summary", ""))),
            "sections": [dict(item) for item in section_items] if isinstance(section_items, list) else [],
            "build_profile": [dict(item) for item in build_profile_items] if isinstance(build_profile_items, list) else [],
        }
        self._update_diagnostic_snapshot_labels()
        self._update_snapshot_report_panel(
            self.diagnostic_section_list,
            self.diagnostic_section_detail_output,
            self._diagnostic_snapshot_data["sections"],
            "当前没有可显示的诊断 section。",
        )
        self._update_snapshot_report_panel(
            self.build_profile_list,
            self.build_profile_detail_output,
            self._diagnostic_snapshot_data["build_profile"],
            "当前还没有构建画像。",
        )

    def _build_activity_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumHeight(self._minimum_report_panel_height)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QFrame()
        body.setObjectName("ActivityPanel")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 8, 12, 8)
        body_layout.setSpacing(6)

        # Header row: title + status indicator + results jump button
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title_label = QLabel("试听中心")
        title_label.setProperty("role", "busHeaderChip")
        header_row.addWidget(title_label)

        self.activity_status_indicator = QLabel("")
        self.activity_status_indicator.setProperty("role", "workspaceSectionSummary")
        self.activity_status_indicator.setWordWrap(False)
        header_row.addWidget(self.activity_status_indicator, 1)

        results_button = QPushButton("结果中心")
        results_button.setProperty("role", "activityCompactButton")
        results_button.clicked.connect(lambda: self._activate_workspace_mode("results"))
        header_row.addWidget(results_button)

        body_layout.addLayout(header_row)

        # Audition center host – contains gamesync and bus controls
        self.activity_preview_host = QWidget()
        self.activity_preview_host.setObjectName("ActivityPreviewHost")
        self.activity_preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        activity_preview_layout = QHBoxLayout(self.activity_preview_host)
        activity_preview_layout.setContentsMargins(0, 0, 0, 0)
        activity_preview_layout.setSpacing(8)
        activity_preview_layout.addWidget(self.preview_gamesync_group, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        activity_preview_layout.addWidget(QLabel(WWISE_TARGET_BUS_LABEL))
        activity_preview_layout.addWidget(self.preview_bus_combo)
        activity_preview_layout.addWidget(self.preview_bus_volume_spin)
        activity_preview_layout.addWidget(self.preview_bus_mute_check)
        activity_preview_layout.addWidget(self.preview_bus_effective_label)
        body_layout.addWidget(self.activity_preview_host)

        layout.addWidget(body)
        self.log_panel = panel
        self._update_activity_panel_status()
        return panel

    def _mount_workspace_surface(self, mode: str) -> None:
        surface_key = {
            "validation": "validation",
            "results": "results",
        }.get(mode)
        if surface_key is None:
            return
        surface = self._workspace_shared_surfaces[surface_key]
        host_layout = self._workspace_mode_hosts.get(mode)
        if host_layout is None:
            return
        if host_layout.indexOf(surface) >= 0:
            return
        surface.setParent(None)
        host_layout.addWidget(surface)

    def _reset_validation_filters(self) -> None:
        self.validation_filter_severity_combo.setCurrentIndex(0)
        self.validation_filter_keyword_edit.clear()

    def _sync_validation_issue_actions(self) -> None:
        self.validation_locate_button.setEnabled(self.validation_issue_list.currentItem() is not None)

    def _locate_selected_validation_issue(self) -> None:
        self._activate_report_item(self.validation_issue_list)

    def _apply_validation_filters(self) -> None:
        severity_map = {
            "错误": "Error",
            "警告": "Warning",
            "信息": "Info",
        }
        severity_text = self.validation_filter_severity_combo.currentText().strip()
        keyword = self.validation_filter_keyword_edit.text().strip().casefold()
        filtered_items: list[dict[str, object]] = []
        for item in self._validation_issue_items:
            severity_value = str(item.get("severity", "")).strip()
            if severity_text != "全部级别" and severity_value != severity_map.get(severity_text, severity_value):
                continue
            haystack = " ".join(
                [
                    str(item.get("title", "")),
                    str(item.get("detail", "")),
                    str(item.get("target_id", "")),
                    str(item.get("code", "")),
                ]
            ).casefold()
            if keyword and keyword not in haystack:
                continue
            filtered_items.append(item)
        self._set_report_items(self.validation_issue_list, filtered_items)
        self.validation_filter_status_label.setText(
            f"当前筛选后显示 {len(filtered_items)} / {len(self._validation_issue_items)} 个校验问题。"
        )
        if not filtered_items:
            self.validation_report_output.setPlainText("当前筛选条件下没有匹配的问题。")
        self._sync_validation_issue_actions()
        self._update_workspace_summary_labels()

    def _build_settings_dialog(self) -> None:
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("设置")
        self._apply_adaptive_top_level_defaults(self.settings_dialog, (760, 620), (520, 360))

        intro_label = QLabel("把低频的应用级控制集中收纳到这里，避免工程首页堆叠。")
        intro_label.setWordWrap(True)

        preview_bus_group = QGroupBox(WWISE_TRANSPORT_TITLE)
        preview_bus_layout = QVBoxLayout(preview_bus_group)
        preview_bus_hint = QLabel("试听 Bus 调节已移至底部试听中心。")
        preview_bus_hint.setWordWrap(True)
        preview_bus_hint.setProperty("role", "workspaceSectionSummary")
        preview_bus_layout.addWidget(preview_bus_hint)

        import_template_group = QGroupBox("导入模板默认值")
        import_template_layout = QFormLayout(import_template_group)
        import_template_layout.addRow(WWISE_DEFAULT_BUS_LABEL, self.import_template_bus_combo)
        import_template_layout.addRow("资源前缀", self.import_template_asset_prefix_edit)
        import_template_layout.addRow("默认标签", self.import_template_tags_edit)
        import_template_layout.addRow("说明", self.import_template_hint_label)

        recent_group = QGroupBox("最近工程")
        recent_layout = QVBoxLayout(recent_group)
        recent_top_layout = QHBoxLayout()
        recent_top_layout.addWidget(self.recent_projects_combo)
        recent_top_layout.addWidget(self.open_recent_project_button)
        recent_layout.addLayout(recent_top_layout)
        recent_layout.addWidget(self.recent_projects_list)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.settings_dialog.close)
        footer_layout = QHBoxLayout()
        footer_layout.addStretch(1)
        footer_layout.addWidget(close_button)

        dialog_layout = QVBoxLayout(self.settings_dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.setSpacing(12)
        dialog_layout.addWidget(intro_label)
        dialog_layout.addWidget(preview_bus_group)
        dialog_layout.addWidget(import_template_group)
        dialog_layout.addWidget(recent_group)
        dialog_layout.addLayout(footer_layout)

    def open_settings_dialog(self) -> None:
        self._constrain_window_to_available_geometry(self.settings_dialog)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _focus_global_search(self) -> None:
        self.global_search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.global_search_edit.selectAll()

    def _command_palette_items(self) -> list[dict[str, object]]:
        return [
            {
                "title": "另存工程",
                "description": "把当前工程保存到新路径；顶栏只保留常用保存入口。",
                "keywords": "save as project 工程 另存为 隐藏动作",
                "action": self.save_as_project_button.click,
            },
            {
                "title": "恢复默认布局",
                "description": "恢复主分栏、工作区和结果坞的默认尺寸。",
                "keywords": "layout splitter dock 布局 分栏 结果坞 隐藏动作",
                "action": self.restore_default_layout,
            },
            {
                "title": "聚焦全局搜索",
                "description": "把焦点移动到顶部搜索框，方便立即输入关键字。",
                "keywords": "search focus 搜索 聚焦 顶部",
                "action": self._focus_global_search,
            },
            {
                "title": "切到欢迎页",
                "description": "返回工作台首页和快速入口。",
                "keywords": "home welcome 欢迎页 首页",
                "action": lambda: self._activate_workspace_mode("home"),
            },
            {
                "title": "切到资源整理",
                "description": "进入片段导入、批量编辑和内容整理工作区。",
                "keywords": f"resources clips content 资源 片段 {WWISE_RESOURCES_BATCH_FEEDBACK_KEYWORDS}",
                "action": lambda: self._activate_workspace_mode("resources"),
            },
            {
                "title": "切到事件设计",
                "description": "进入事件属性、播放模式和引用关系工作区。",
                "keywords": "events design 事件 设计 属性",
                "action": lambda: self._activate_workspace_mode("events"),
            },
            {
                "title": "切到 GameSync",
                "description": "进入项目级 RTPC、State Group 和 Switch Group 工作区。",
                "keywords": "gamesync rtpc state switch 参数 状态 分支",
                "action": lambda: self._activate_workspace_mode("gamesync"),
            },
            {
                "title": f"切到 {WWISE_MASTER_MIXER_TITLE}",
                "description": f"集中查看 {WWISE_OUTPUT_BUS_LABEL}、{WWISE_ROUTING_LABEL}、{WWISE_MASTER_MIXER_HIERARCHY_TITLE} 和 {WWISE_MASTER_AUDIO_BUS_TITLE}。",
                "keywords": WWISE_BUS_WORKSPACE_KEYWORDS,
                "action": lambda: self._activate_workspace_mode("buses"),
            },
            {
                "title": "切到校验修复",
                "description": "进入问题筛选、定位和重新校验工作区。",
                "keywords": "validation validate 校验 修复 问题",
                "action": lambda: self._activate_workspace_mode("validation"),
            },
            {
                "title": "切到构建交付",
                "description": "进入构建范围、导出和交付工作区。",
                "keywords": "build export delivery 构建 导出 交付",
                "action": lambda: self._activate_workspace_mode("build"),
            },
            {
                "title": "切到结果中心",
                "description": "打开统一的日志、校验、构建和响度结果面板。",
                "keywords": "results logs report 结果 日志 报告",
                "action": lambda: self._activate_workspace_mode("results"),
            },
        ]

    def _filter_command_palette_items(
        self,
        query: str,
        commands: list[dict[str, object]] | None = None,
    ) -> list[tuple[int, dict[str, object]]]:
        available_commands = commands or self._command_palette_items()
        normalized_query = query.strip().casefold()
        filtered: list[tuple[int, dict[str, object]]] = []
        for index, command in enumerate(available_commands):
            haystack = f"{command['title']} {command['description']} {command['keywords']}".casefold()
            if normalized_query and normalized_query not in haystack:
                continue
            filtered.append((index, command))
        return filtered

    def _show_command_palette(self) -> None:
        commands = self._command_palette_items()
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{APP_NAME} 命令面板")
        dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dialog.setModal(True)
        dialog.resize(640, 460)
        dialog.setMinimumSize(520, 360)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro_label = QLabel("输入关键字筛选工作区、对象入口或隐藏动作，按 Enter 执行当前高亮项，Esc 关闭。")
        intro_label.setWordWrap(True)
        filter_edit = QLineEdit()
        filter_edit.setClearButtonEnabled(True)
        filter_edit.setPlaceholderText("搜索工作区或隐藏动作，例如：bus、批量反馈、结果中心、另存")
        filter_edit.setProperty("role", "topSearchField")

        command_list = QListWidget()
        command_list.setProperty("role", "resultList")
        command_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        command_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        command_list.setAlternatingRowColors(True)

        detail_label = QLabel()
        detail_label.setWordWrap(True)
        status_label = QLabel("Ctrl+Shift+P 可随时再次打开命令面板。")

        def update_selected_command_detail() -> None:
            current_item = command_list.currentItem()
            if current_item is None:
                detail_label.setText("没有匹配项。可以尝试输入“bus”“批量反馈”“结果中心”“另存”等关键字。")
                return
            command_index = current_item.data(Qt.ItemDataRole.UserRole)
            command = commands[int(command_index)]
            detail_label.setText(f"{command['title']}\n{command['description']}")

        def refresh_command_list() -> None:
            command_list.clear()
            visible_count = 0
            for index, command in self._filter_command_palette_items(filter_edit.text(), commands):
                item = QListWidgetItem(f"{command['title']}\n{command['description']}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(str(command["description"]))
                item.setSizeHint(QSize(0, 48))
                command_list.addItem(item)
                visible_count += 1
            if visible_count > 0:
                command_list.setCurrentRow(0)
                status_label.setText(f"{visible_count} 个命令可执行，Enter 运行，Esc 关闭。")
            else:
                status_label.setText("没有匹配命令")
            update_selected_command_detail()

        def run_selected_command() -> None:
            current_item = command_list.currentItem()
            if current_item is None:
                return
            command_index = current_item.data(Qt.ItemDataRole.UserRole)
            action = commands[int(command_index)].get("action")
            if not callable(action):
                return
            dialog.accept()
            QTimer.singleShot(0, action)

        filter_edit.textChanged.connect(refresh_command_list)
        filter_edit.returnPressed.connect(run_selected_command)
        command_list.itemDoubleClicked.connect(lambda _item: run_selected_command())
        command_list.itemSelectionChanged.connect(update_selected_command_detail)

        layout.addWidget(intro_label)
        layout.addWidget(filter_edit)
        layout.addWidget(command_list, 1)
        layout.addWidget(detail_label)
        layout.addWidget(status_label)

        refresh_command_list()
        dialog.exec()

    def _set_workspace_mode(self, mode: str) -> None:
        mode_titles = {
            "home": "欢迎页",
            "resources": "资源整理",
            "events": "事件设计",
            "gamesync": "GameSync",
            "buses": WWISE_MASTER_MIXER_TITLE,
            "validation": "校验修复",
            "build": "构建交付",
            "results": "结果中心",
        }
        self._active_workspace_mode = mode
        self.task_sidebar.set_active_mode(mode)
        self.status_label.setText(f"当前工作区：{mode_titles.get(mode, mode)}")

    def _activate_workspace_mode(self, mode: str) -> None:
        previous_main_sizes = self._effective_main_splitter_sizes()
        if mode == "logs-results":
            self._active_report_index = 0
            self.report_pages.setCurrentIndex(0)
            self._report_tab_index = 0
            mode = "results"
        elif mode == "validation-results":
            self._active_report_index = 1
            self.report_pages.setCurrentIndex(1)
            self._report_tab_index = 1
            mode = "results"
        elif mode == "build-results":
            self._active_report_index = 2
            self.report_pages.setCurrentIndex(2)
            self._report_tab_index = 2
            mode = "results"
        elif mode == "loudness-results":
            self._active_report_index = 3
            self.report_pages.setCurrentIndex(3)
            self._report_tab_index = 3
            mode = "results"
        if mode == "home":
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["home"])
        elif mode == "resources":
            self._mount_workspace_surface("resources")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["resources"])
            self._editor_tab_index = 1
            self.contents_tabs.setCurrentIndex(0)
            self._set_content_top_splitter_sizes(self._default_focus_content_splitter_sizes)
        elif mode == "events":
            self._mount_workspace_surface("events")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["events"])
            self._editor_tab_index = 0
            self._property_tab_index = 0
            self.events_workspace_tabs.setCurrentIndex(0)
        elif mode == "gamesync":
            self._mount_workspace_surface("gamesync")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["gamesync"])
            self.gamesync_workspace_tabs.setCurrentIndex(0)
        elif mode == "buses":
            self._mount_workspace_surface("buses")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["buses"])
            self._editor_tab_index = 0
            self._property_tab_index = 1
            self._project_bus_selection_overridden = False
            self._sync_current_event_bus_selection(force=True)
        elif mode == "validation":
            self._mount_workspace_surface("validation")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["validation"])
            self._active_report_index = 1
            self.report_pages.setCurrentIndex(1)
            self._report_tab_index = 1
        elif mode == "build":
            self._mount_workspace_surface("build")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["build"])
            self._editor_tab_index = 0
            self._property_tab_index = 2
        elif mode == "results":
            self._mount_workspace_surface("results")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["results"])
        current_page = self.workspace_mode_stack.currentWidget()
        if current_page is not None:
            current_page.updateGeometry()
        self.workspace_mode_stack.updateGeometry()
        self.main_splitter.updateGeometry()
        self.workspace_splitter.updateGeometry()
        if previous_main_sizes and not self._explorer_detached:
            restored_main_sizes = [int(value) for value in previous_main_sizes]
            self._set_main_splitter_sizes(restored_main_sizes)
            QTimer.singleShot(0, lambda sizes=list(restored_main_sizes): self._restore_main_splitter_sizes_after_mode_switch(sizes))
        self._set_workspace_mode(mode)
        self._update_object_bus_status()
        self._schedule_layout_flush()

    def _restore_main_splitter_sizes_after_mode_switch(self, sizes: list[int]) -> None:
        if self._explorer_detached or not self.isVisible():
            return
        normalized_sizes = [int(value) for value in sizes]
        self._last_docked_main_splitter_sizes = list(normalized_sizes)
        self.main_splitter.setSizes(normalized_sizes)

    def _sync_global_search_fields(self, text: str) -> None:
        self.tree_filter_edit.setText(text)

    def _request_global_search(self) -> None:
        query = self.global_search_edit.text().strip()
        self.tree_filter_edit.setText(query)
        if not query:
            self.report_detail_label.setText("先输入关键字，再执行全局搜索。")
            return
        candidates = self._global_search_candidates()
        matches = self._filter_global_search_candidates(query, candidates)
        if not matches:
            self.report_detail_label.setText(f"没有找到匹配“{query}”的工作区、对象、Bus 或结果。")
            self.report_detail_label.setToolTip(query)
            return
        if len(matches) == 1:
            self._run_global_search_match(matches[0])
            return
        self._show_global_search_results(query, candidates)

    def _global_search_candidates(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        candidates.extend(self._collect_workspace_search_candidates())
        candidates.extend(self._collect_tree_search_candidates())
        candidates.extend(self._collect_project_bus_search_candidates())
        candidates.extend(self._collect_report_list_search_candidates(self.validation_issue_list, 1, "校验问题", 10))
        candidates.extend(self._collect_report_list_search_candidates(self.build_issue_list, 2, "构建结果", 20))
        candidates.extend(self._collect_report_list_search_candidates(self.loudness_issue_list, 3, "响度结果", 20))
        return candidates

    def _collect_workspace_search_candidates(self) -> list[dict[str, object]]:
        candidates = [
            {
                "title": "工作区 | 欢迎页",
                "description": "欢迎页 / 首页快捷入口。",
                "keywords": "欢迎页 首页 home welcome",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("home"),
            },
            {
                "title": "工作区 | 资源整理",
                "description": "资源整理 / 片段编排、批处理、最近批量反馈。",
                "keywords": f"资源整理 片段 编排 批处理 {WWISE_RESOURCES_BATCH_FEEDBACK_KEYWORDS}",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("resources"),
            },
            {
                "title": "工作区 | 事件设计",
                "description": "事件设计 / 事件属性、播放模式和引用关系。",
                "keywords": "事件设计 事件 属性 播放模式 引用关系 events design",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("events"),
            },
            {
                "title": "工作区 | GameSync",
                "description": "GameSync / 项目级 Game Parameter、State Group 和 Switch Group。",
                "keywords": "gamesync rtpc state switch 参数 状态 分支",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("gamesync"),
            },
            {
                "title": f"工作区 | {WWISE_MASTER_MIXER_TITLE}",
                "description": f"{WWISE_MASTER_MIXER_TITLE} / {WWISE_OUTPUT_BUS_LABEL}、{WWISE_ROUTING_LABEL}、{WWISE_MASTER_AUDIO_BUS_TITLE}。",
                "keywords": WWISE_BUS_WORKSPACE_KEYWORDS,
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("buses"),
            },
            {
                "title": "工作区 | 校验修复",
                "description": "校验修复 / 问题筛选、定位和修复。",
                "keywords": "校验 修复 validation issue problem",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("validation"),
            },
            {
                "title": "工作区 | 构建交付",
                "description": "构建交付 / 导出范围、交付预览和构建入口。",
                "keywords": "构建 交付 导出 build export delivery",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("build"),
            },
            {
                "title": "工作区 | 结果中心",
                "description": "结果中心 / 日志、校验、构建和响度结果。",
                "keywords": "结果中心 结果 日志 校验 构建 响度 results logs validation build loudness",
                "priority": 25,
                "action": lambda: self._activate_workspace_mode("results"),
            },
        ]
        if self._has_resources_batch_feedback:
            candidates.append(
                {
                    "title": "资源页 | 最近批量反馈",
                    "description": self.resources_batch_feedback_summary_label.text().strip() or "查看最近一次批量编辑反馈。",
                    "keywords": f"{WWISE_RESOURCES_BATCH_FEEDBACK_KEYWORDS} {self.resources_batch_feedback_title_label.text().strip()} {self.resources_batch_feedback_field_label.text().strip()}",
                    "priority": 12,
                    "action": lambda: self._activate_workspace_mode("resources"),
                }
            )
        return candidates

    def _collect_tree_search_candidates(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        pending = [self.tree.topLevelItem(index) for index in range(self.tree.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(payload, (tuple, list)) and len(payload) >= 2:
                target_type = str(payload[0])
                target_id = str(payload[1])
                label = item.text(0).strip() or target_id
                kind_label = "事件" if target_type == "event" else "文件夹" if target_type == "folder" else "对象"
                breadcrumb = self._tree_item_search_breadcrumb(item)
                description = f"工程对象 / {kind_label} / 标识 {target_id}"
                if breadcrumb:
                    description = f"{description} / 路径 {breadcrumb}"
                candidates.append(
                    {
                        "title": f"{kind_label} | {label}",
                        "description": description,
                        "keywords": f"工程对象 {kind_label} {label} {target_id} {breadcrumb}",
                        "priority": 0,
                        "action": lambda node_type=target_type, node_id=target_id: self.reportTargetRequested.emit(node_type, node_id),
                    }
                )
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        return candidates

    def _tree_item_search_breadcrumb(self, item: QTreeWidgetItem) -> str:
        segments: list[str] = []
        current: QTreeWidgetItem | None = item.parent()
        while current is not None:
            label = current.text(0).strip()
            if label:
                segments.append(label)
            current = current.parent()
        segments.reverse()
        return " / ".join(segments)

    def _collect_project_bus_search_candidates(self) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for config in self._project_bus_configs:
            bus_name = str(config.get("name", "")).strip()
            if not bus_name:
                continue
            parent_bus = str(config.get("parent_bus", "Master") or "Master")
            volume_db = float(config.get("volume_db", 0.0))
            muted_text = "静音" if bool(config.get("is_muted", False)) else "可用"
            candidates.append(
                {
                    "title": f"Bus | {bus_name}",
                    "description": f"{WWISE_MASTER_MIXER_TITLE} / {WWISE_PARENT_BUS_LABEL} {parent_bus} / {volume_db:.1f} dB / {muted_text}",
                    "keywords": f"{WWISE_BUS_SEARCH_KEYWORDS} {bus_name} {parent_bus} {muted_text}",
                    "priority": 5,
                    "action": lambda name=bus_name: self._focus_project_bus_search_result(name),
                }
            )
        return candidates

    def _collect_report_list_search_candidates(
        self,
        list_widget: QListWidget,
        report_index: int,
        category_label: str,
        priority: int,
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item is None:
                continue
            payload = item.data(Qt.ItemDataRole.UserRole) or {}
            detail = str(payload.get("detail", item.text())).strip()
            summary_line = detail.splitlines()[0] if detail else item.text().strip()
            target_type = str(payload.get("target_type", "")).strip()
            target_id = str(payload.get("target_id", "")).strip()
            title = item.text().strip()
            candidates.append(
                {
                    "title": f"{category_label} | {title}",
                    "description": summary_line,
                    "keywords": f"{category_label} {title} {summary_line} {target_type} {target_id}",
                    "priority": priority,
                    "action": lambda page_index=report_index, widget=list_widget, target_row=row: self._focus_report_search_result(page_index, widget, target_row),
                }
            )
        return candidates

    def _filter_global_search_candidates(
        self,
        query: str,
        candidates: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        normalized_query = query.strip().casefold()
        if not normalized_query:
            return []
        matches = [
            candidate
            for candidate in candidates
            if normalized_query in str(candidate.get("keywords", "")).casefold()
            or normalized_query in str(candidate.get("title", "")).casefold()
            or normalized_query in str(candidate.get("description", "")).casefold()
        ]
        return sorted(matches, key=lambda candidate: self._global_search_sort_key(normalized_query, candidate))

    def _global_search_sort_key(self, normalized_query: str, candidate: dict[str, object]) -> tuple[int, int, str]:
        title = str(candidate.get("title", "")).casefold()
        description = str(candidate.get("description", "")).casefold()
        keywords = str(candidate.get("keywords", "")).casefold()
        if title == normalized_query:
            score = 0
        elif title.startswith(normalized_query):
            score = 1
        elif any(token.startswith(normalized_query) for token in keywords.split()):
            score = 2
        elif normalized_query in title:
            score = 3
        elif normalized_query in description:
            score = 4
        else:
            score = 5
        return int(candidate.get("priority", 99)) + score, len(title), title

    def _run_global_search_match(self, candidate: dict[str, object]) -> None:
        action = candidate.get("action")
        if callable(action):
            action()
        title = str(candidate.get("title", "")).strip()
        description = str(candidate.get("description", "")).strip()
        if title:
            self.report_detail_label.setText(f"已跳转：{title}")
            self.report_detail_label.setToolTip(description or title)

    def _focus_project_bus_search_result(self, bus_name: str) -> None:
        self.set_active_property_category("音频属性")
        if self._select_project_bus_by_name(bus_name):
            self.project_bus_list.scrollToItem(self.project_bus_list.currentItem(), QAbstractItemView.ScrollHint.PositionAtCenter)

    def _focus_report_search_result(self, report_index: int, list_widget: QListWidget, row: int) -> None:
        self.show_report_tab(report_index)
        if not 0 <= row < list_widget.count():
            return
        list_widget.setCurrentRow(row)
        item = list_widget.item(row)
        if item is not None:
            list_widget.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _show_global_search_results(self, initial_query: str, candidates: list[dict[str, object]]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{APP_NAME} 全局搜索")
        dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dialog.setModal(True)
        dialog.resize(720, 480)
        dialog.setMinimumSize(560, 360)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro_label = QLabel("搜索对象、总线、问题和结果。按 Enter 跳转当前高亮项，Esc 关闭。")
        intro_label.setWordWrap(True)

        query_edit = QLineEdit()
        query_edit.setClearButtonEnabled(True)
        query_edit.setPlaceholderText("例如：UI_Click、Master、校验、构建、响度")
        query_edit.setProperty("role", "topSearchField")
        query_edit.setText(initial_query)

        result_list = QListWidget()
        result_list.setProperty("role", "resultList")
        result_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        result_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        result_list.setAlternatingRowColors(True)

        detail_label = QLabel()
        detail_label.setWordWrap(True)
        status_label = QLabel()

        filtered_matches: list[dict[str, object]] = []

        def update_selected_detail() -> None:
            current_item = result_list.currentItem()
            if current_item is None:
                detail_label.setText("没有匹配结果。可以尝试对象名、总线名、问题代码或结果关键字。")
                return
            match_index = int(current_item.data(Qt.ItemDataRole.UserRole))
            candidate = filtered_matches[match_index]
            detail_label.setText(f"{candidate['title']}\n{candidate['description']}")

        def refresh_results() -> None:
            nonlocal filtered_matches
            filtered_matches = self._filter_global_search_candidates(query_edit.text(), candidates)
            result_list.clear()
            for index, candidate in enumerate(filtered_matches):
                item = QListWidgetItem(f"{candidate['title']}\n{candidate['description']}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(str(candidate.get("description", candidate.get("title", ""))))
                item.setSizeHint(QSize(0, 48))
                result_list.addItem(item)
            if filtered_matches:
                result_list.setCurrentRow(0)
                status_label.setText(f"找到 {len(filtered_matches)} 个结果，Enter 跳转。")
            else:
                status_label.setText("没有匹配结果。")
            update_selected_detail()

        def activate_selected_result() -> None:
            current_item = result_list.currentItem()
            if current_item is None:
                return
            match_index = int(current_item.data(Qt.ItemDataRole.UserRole))
            candidate = filtered_matches[match_index]
            dialog.accept()
            QTimer.singleShot(0, lambda selected=candidate: self._run_global_search_match(selected))

        query_edit.textChanged.connect(refresh_results)
        query_edit.returnPressed.connect(activate_selected_result)
        result_list.itemDoubleClicked.connect(lambda _item: activate_selected_result())
        result_list.itemSelectionChanged.connect(update_selected_detail)

        layout.addWidget(intro_label)
        layout.addWidget(query_edit)
        layout.addWidget(result_list, 1)
        layout.addWidget(detail_label)
        layout.addWidget(status_label)

        refresh_results()
        query_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        query_edit.selectAll()
        dialog.exec()

    def current_event_import_template_defaults(self) -> dict[str, object]:
        selected_bus = self.import_template_bus_combo.currentData()
        bus_name = str(selected_bus) if selected_bus is not None else str(self._event_import_template_defaults.get("bus_name", ""))
        return {
            "bus_name": bus_name,
            "asset_prefix": self.import_template_asset_prefix_edit.text().strip().strip("/"),
            "tags": [tag.strip() for tag in self.import_template_tags_edit.text().split(",") if tag.strip()],
        }

    def _sync_event_import_template_controls(self, buses: list[str] | None = None) -> None:
        available_buses = list(buses) if buses is not None else [self.default_bus_combo.itemText(i) for i in range(self.default_bus_combo.count())]
        remembered_bus_name = str(self._event_import_template_defaults.get("bus_name", ""))
        self.import_template_bus_combo.blockSignals(True)
        self.import_template_asset_prefix_edit.blockSignals(True)
        self.import_template_tags_edit.blockSignals(True)
        self.import_template_bus_combo.clear()
        self.import_template_bus_combo.addItem("自动选择", "")
        for bus_name in available_buses:
            self.import_template_bus_combo.addItem(bus_name, bus_name)
        target_bus_name = remembered_bus_name if remembered_bus_name in available_buses else ""
        target_index = self.import_template_bus_combo.findData(target_bus_name)
        self.import_template_bus_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.import_template_asset_prefix_edit.setText(str(self._event_import_template_defaults.get("asset_prefix", "")))
        self.import_template_tags_edit.setText(", ".join(str(tag) for tag in self._event_import_template_defaults.get("tags", [])))
        self.import_template_bus_combo.blockSignals(False)
        self.import_template_asset_prefix_edit.blockSignals(False)
        self.import_template_tags_edit.blockSignals(False)

    def _update_event_import_template_defaults_from_controls(self) -> None:
        self._event_import_template_defaults = self.current_event_import_template_defaults()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._constrain_window_to_available_geometry(self)
        self._apply_splitter_resize_defaults()
        self._schedule_layout_flush()
        if self._explorer_detached and not self.explorer_window.isVisible():
            QTimer.singleShot(0, self.show_detached_explorer)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._schedule_layout_flush()

    def _schedule_layout_flush(self) -> None:
        if self._pending_layout_flush:
            return
        self._pending_layout_flush = True
        QTimer.singleShot(0, self._flush_pending_layout_sizes)

    def _flush_pending_layout_sizes(self) -> None:
        self._pending_layout_flush = False
        if self._pending_workspace_splitter_sizes is not None:
            sizes = self._normalize_workspace_splitter_sizes(self._pending_workspace_splitter_sizes)
            self._apply_activity_panel_presentation()
            self.workspace_splitter.setSizes(sizes)
            self._pending_workspace_splitter_sizes = None
        if self._pending_main_splitter_sizes is not None and not self._explorer_detached:
            sizes = [int(value) for value in self._pending_main_splitter_sizes]
            self.main_splitter.setSizes(sizes)
            self._pending_main_splitter_sizes = None
        if self._pending_content_top_splitter_sizes is not None:
            sizes = [int(value) for value in self._pending_content_top_splitter_sizes]
            self.content_top_splitter.setSizes(sizes)
            self._pending_content_top_splitter_sizes = None
        if self._pending_named_splitter_sizes:
            pending = dict(self._pending_named_splitter_sizes)
            self._pending_named_splitter_sizes = {}
            for name, sizes in pending.items():
                if name == "WorkspaceSplitter":
                    self.workspace_splitter.setSizes(self._normalize_workspace_splitter_sizes(sizes))
                    continue
                if name == "MainSplitter":
                    if self._explorer_detached:
                        self._last_docked_main_splitter_sizes = [int(value) for value in sizes]
                    else:
                        self.main_splitter.setSizes([int(value) for value in sizes])
                    continue
                if name == "ContentTopSplitter":
                    self.content_top_splitter.setSizes([int(value) for value in sizes])
                    continue
                splitter = self.findChild(QSplitter, name)
                if splitter is not None:
                    splitter.setSizes([int(value) for value in sizes])
        self._apply_responsive_workspace_layouts()
        actual_workspace_sizes = self.workspace_splitter.sizes() if hasattr(self, "workspace_splitter") else []
        if len(actual_workspace_sizes) == 2 and actual_workspace_sizes[1] > self._minimum_report_panel_height + 24:
            self._last_expanded_report_panel_height = actual_workspace_sizes[1]
        self._apply_activity_panel_presentation()

    def _apply_responsive_workspace_layouts(self) -> None:
        self._apply_two_column_splitter_responsiveness()
        self._apply_clip_editor_responsive_layout()

    def _apply_two_column_splitter_responsiveness(self) -> None:
        for splitter in self._responsive_two_column_splitters:
            self._apply_responsive_two_column_splitter(splitter)

    def _apply_responsive_two_column_splitter(self, splitter: QSplitter, *, available_width: int | None = None) -> None:
        width = int(available_width or 0)
        if width <= 0:
            width = splitter.width()
        if width <= 0 and splitter.parentWidget() is not None:
            width = splitter.parentWidget().width()
        if width <= 0:
            sizes = splitter.sizes()
            width = sum(sizes) if sizes else 0
        if width <= 0:
            return
        breakpoint = int(splitter.property("responsiveBreakPoint") or self._two_column_compact_breakpoint)
        desired_orientation = Qt.Orientation.Vertical if width < breakpoint else Qt.Orientation.Horizontal
        splitter.setProperty("responsiveMode", "compact" if desired_orientation == Qt.Orientation.Vertical else "wide")
        if splitter.orientation() == desired_orientation:
            return
        splitter.setOrientation(desired_orientation)
        extent = splitter.height() if desired_orientation == Qt.Orientation.Vertical else width
        if extent <= 0:
            sizes = splitter.sizes()
            extent = sum(sizes) if sizes else 0
        if extent <= 0:
            return
        lead = int(extent * (0.56 if desired_orientation == Qt.Orientation.Vertical else 0.6))
        lead = max(220, lead)
        lead = min(lead, max(0, extent - 180))
        splitter.setSizes([lead, max(0, extent - lead)])

    def _apply_clip_editor_responsive_layout(self) -> None:
        if not hasattr(self, "content_top_splitter") or not hasattr(self, "contents_tabs"):
            return
        resources_page = self._workspace_mode_pages.get("resources") if hasattr(self, "_workspace_mode_pages") else None
        if resources_page is None or self.workspace_mode_stack.currentWidget() is not resources_page or self.contents_tabs.currentIndex() != 0:
            return
        sizes = self.content_top_splitter.sizes()
        if len(sizes) != 2:
            return
        total_width = sum(sizes)
        if total_width <= 0:
            total_width = self.content_top_splitter.width()
        if total_width <= 0:
            return
        target_sizes = self._responsive_content_top_splitter_sizes(total_width)
        if target_sizes is not None and sizes[1] + 12 < target_sizes[1]:
            self.content_top_splitter.setSizes(target_sizes)
            sizes = self.content_top_splitter.sizes()
        detail_width = sizes[1] if len(sizes) == 2 and sizes[1] > 0 else self.clip_detail_group.width()
        self._apply_clip_editor_layout_mode(self._clip_detail_layout_mode_for_width(detail_width))

    def _responsive_content_top_splitter_sizes(self, total_width: int) -> list[int] | None:
        mode = self._content_top_layout_mode_for_width(total_width)
        if mode == "wide":
            return None
        left_minimum = 320
        desired_right = max(int(total_width * (0.44 if mode == "medium" else 0.5)), 430 if mode == "medium" else 460)
        desired_right = min(desired_right, max(0, total_width - left_minimum))
        if desired_right <= 0 or desired_right >= total_width:
            return None
        return [max(left_minimum, total_width - desired_right), desired_right]

    def _content_top_layout_mode_for_width(self, total_width: int) -> str:
        if total_width >= self._content_top_wide_breakpoint:
            return "wide"
        if total_width >= self._content_top_medium_breakpoint:
            return "medium"
        return "compact"

    def _clip_detail_layout_mode_for_width(self, detail_width: int) -> str:
        if detail_width >= self._clip_detail_wide_breakpoint:
            return "wide"
        if detail_width >= self._clip_detail_medium_breakpoint:
            return "medium"
        return "compact"

    def _apply_clip_editor_layout_mode(self, mode: str) -> None:
        if self._clip_editor_layout_mode == mode:
            return
        self._clip_editor_layout_mode = mode
        self._rebuild_clip_waveform_action_panel(mode)
        self._rebuild_clip_detail_action_panel(mode)
        if mode == "wide":
            self.clip_meta_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
            self.clip_preview_hint_label.setMaximumHeight(40)
        elif mode == "medium":
            self.clip_meta_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            self.clip_preview_hint_label.setMaximumHeight(52)
        else:
            self.clip_meta_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
            self.clip_preview_hint_label.setMaximumHeight(72)
        self.clip_waveform_action_panel.setProperty("layoutMode", mode)
        self.clip_action_row.setProperty("layoutMode", mode)
        self.clip_waveform_action_panel.updateGeometry()
        self.clip_action_row.updateGeometry()

    def _detach_widgets_from_layout(self, layout, widgets: list[QWidget]) -> None:
        for widget in widgets:
            layout.removeWidget(widget)

    def _rebuild_clip_waveform_action_panel(self, mode: str) -> None:
        self._detach_widgets_from_layout(
            self.clip_waveform_action_layout,
            [self.clip_playhead_label, *self._clip_waveform_action_buttons],
        )
        if mode == "wide":
            self.clip_waveform_action_layout.addWidget(self.clip_playhead_label, 0, 0)
            for index, button in enumerate(self._clip_waveform_action_buttons, start=1):
                self.clip_waveform_action_layout.addWidget(button, 0, index)
            return
        if mode == "medium":
            self.clip_waveform_action_layout.addWidget(self.clip_playhead_label, 0, 0, 1, 4)
            for index, button in enumerate(self._clip_waveform_action_buttons[:4]):
                self.clip_waveform_action_layout.addWidget(button, 1, index)
            for index, button in enumerate(self._clip_waveform_action_buttons[4:]):
                self.clip_waveform_action_layout.addWidget(button, 2, index)
            return
        self.clip_waveform_action_layout.addWidget(self.clip_playhead_label, 0, 0, 1, 2)
        compact_rows = [
            self._clip_waveform_action_buttons[0:2],
            self._clip_waveform_action_buttons[2:4],
            self._clip_waveform_action_buttons[4:6],
            self._clip_waveform_action_buttons[6:8],
        ]
        for row_index, row_buttons in enumerate(compact_rows, start=1):
            for column_index, button in enumerate(row_buttons):
                self.clip_waveform_action_layout.addWidget(button, row_index, column_index)

    def _rebuild_clip_detail_action_panel(self, mode: str) -> None:
        self._detach_widgets_from_layout(self.clip_action_layout, self._clip_detail_action_buttons)
        if mode == "wide":
            for index, button in enumerate(self._clip_detail_action_buttons):
                self.clip_action_layout.addWidget(button, 0, index)
            return
        top_row = self._clip_detail_action_buttons[:2]
        bottom_row = self._clip_detail_action_buttons[2:]
        for index, button in enumerate(top_row):
            self.clip_action_layout.addWidget(button, 0, index)
        for index, button in enumerate(bottom_row):
            self.clip_action_layout.addWidget(button, 1, index)

    def _normalize_workspace_splitter_sizes(self, sizes: list[int]) -> list[int]:
        normalized = [int(value) for value in sizes]
        total = max(sum(normalized), sum(self._default_workspace_splitter_sizes)) if normalized else sum(self._default_workspace_splitter_sizes)
        if len(normalized) < 2:
            normalized = [max(0, total - self._minimum_report_panel_height), self._minimum_report_panel_height]
        bottom = max(self._minimum_report_panel_height, normalized[1])
        bottom = min(bottom, total)
        top = max(0, total - bottom)
        if bottom > self._minimum_report_panel_height + 24:
            self._last_expanded_report_panel_height = bottom
        return [top, bottom]

    def _set_workspace_splitter_sizes(self, sizes: list[int]) -> None:
        normalized = self._normalize_workspace_splitter_sizes(sizes)
        self._pending_workspace_splitter_sizes = normalized
        self._apply_activity_panel_presentation()
        if self.isVisible():
            self._schedule_layout_flush()

    def _set_main_splitter_sizes(self, sizes: list[int]) -> None:
        normalized_sizes = [int(value) for value in sizes]
        self._last_docked_main_splitter_sizes = normalized_sizes
        self._pending_main_splitter_sizes = normalized_sizes
        if self.isVisible() and not self._explorer_detached:
            self._schedule_layout_flush()

    def _effective_main_splitter_sizes(self) -> list[int]:
        if self._explorer_detached:
            return list(self._last_docked_main_splitter_sizes)
        return self.main_splitter.sizes()

    def _build_detached_explorer_placeholder(self) -> QWidget:
        placeholder = QWidget()
        placeholder.setMinimumWidth(56)
        placeholder.setMaximumWidth(72)
        placeholder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(6, 10, 6, 10)
        layout.setSpacing(8)
        title = QLabel("浏览器\n已分离")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setWordWrap(True)
        focus_button = QPushButton("定位")
        focus_button.clicked.connect(self.show_detached_explorer)
        focus_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        attach_button = QPushButton("停靠")
        attach_button.clicked.connect(self.attach_explorer_panel)
        attach_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(title)
        layout.addWidget(focus_button)
        layout.addWidget(attach_button)
        layout.addStretch(1)
        return placeholder

    def toggle_explorer_detached(self) -> None:
        if self._explorer_detached:
            self.attach_explorer_panel()
        else:
            self.detach_explorer_panel()

    def detach_explorer_panel(self) -> None:
        if self._explorer_detached:
            self.show_detached_explorer()
            return
        self._last_docked_main_splitter_sizes = self.main_splitter.sizes()
        self.explorer_panel.setParent(None)
        self.main_splitter.insertWidget(0, self.explorer_placeholder)
        self.explorer_window_layout.addWidget(self.explorer_panel)
        self._explorer_detached = True
        if self.isVisible():
            total = max(sum(self._last_docked_main_splitter_sizes), sum(self._default_main_splitter_sizes))
            self.main_splitter.setSizes([64, max(320, total - 64)])
        self.show_detached_explorer()

    def show_detached_explorer(self) -> None:
        if not self._explorer_detached:
            return
        self._constrain_window_to_available_geometry(self.explorer_window)
        self.explorer_window.show()
        self.explorer_window.raise_()
        self.explorer_window.activateWindow()

    def attach_explorer_panel(self) -> None:
        if not self._explorer_detached:
            return
        self.explorer_panel.setParent(None)
        self.explorer_placeholder.setParent(None)
        self.main_splitter.insertWidget(0, self.explorer_panel)
        self._explorer_detached = False
        self.explorer_window.hide()
        self._set_main_splitter_sizes(self._last_docked_main_splitter_sizes)

    def _set_content_top_splitter_sizes(self, sizes: list[int]) -> None:
        self._pending_content_top_splitter_sizes = [int(value) for value in sizes]
        if self.isVisible():
            self._schedule_layout_flush()

    def set_event_details(self, event: EventModel | None) -> None:
        previous_event_id = self._active_event_id
        current_event_id = event.id if event is not None else None
        event_changed = current_event_id != previous_event_id
        self._active_event_id = current_event_id
        self._active_audio_id = event.audio_id if event is not None else None
        self._loading_event = True
        if event is None:
            self.event_gamesync_group.setTitle("Audio GameSync 绑定")
            self.event_gamesync_context_label.setText("当前 Audio：-")
            self.clear_resources_batch_feedback()
            self.status_label.setText("未选择事件")
            self.event_id_edit.clear()
            self.display_name_edit.clear()
            self.tags_summary_edit.clear()
            self.bus_combo.setCurrentIndex(0)
            self.play_mode_combo.setCurrentIndex(0)
            self.steal_policy_combo.setCurrentIndex(0)
            self.load_policy_combo.setCurrentIndex(0)
            self.source_audio_format_combo.setCurrentText("wav")
            self.runtime_audio_format_combo.setCurrentText("ogg")
            self.volume_spin.setValue(0.0)
            self.volume_rand_min_spin.setValue(0.0)
            self.volume_rand_max_spin.setValue(0.0)
            self.pitch_spin.setValue(0.0)
            self.pitch_rand_min_spin.setValue(0)
            self.pitch_rand_max_spin.setValue(0)
            self.cooldown_spin.setValue(0.0)
            self.max_instances_spin.setValue(0)
            self.combo_pitch_step_spin.setValue(0)
            self.combo_reset_spin.setValue(0.0)
            self.combo_max_step_spin.setValue(0)
            self.avoid_repeat_check.setChecked(False)
            self.notes_edit.clear()
            self.event_audio_reference_label.setText("当前引用 Audio：-")
            self.event_open_audio_workspace_button.setEnabled(False)
            self.event_locate_audio_browser_button.setEnabled(False)
            self.clip_table.setRowCount(0)
            self._event_rtpc_bindings = []
            self._event_state_overrides = []
            self._event_switch_variants = []
            self._refresh_event_binding_views()
            self._load_event_binding_editor("rtpc")
            self._load_event_binding_editor("state")
            self._load_event_binding_editor("switch")
            self._current_event_source_paths = []
            self.set_object_context(
                object_type="Folder",
                object_name="未选择对象",
                breadcrumb="Project / Root",
                stats_text="片段 0 | 标签 0",
                summary_primary=f"模式 - | {WWISE_OUTPUT_BUS_LABEL} -",
                summary_secondary="生成 - | 来源 -",
                can_navigate_parent=False,
            )
            self.set_reference_context(
                parent_name="-",
                bus_name="-",
                assets_name="0 个片段",
                generation_name="未配置",
                work_unit_text="Work Unit：-",
                output_text="输出：-",
                has_parent=False,
            )
            self._set_selected_clip_details(None)
            self._refresh_event_source_binding_state()
            self._refresh_source_browser_tree()
            self.property_group.setEnabled(False)
            self.import_clips_button.setEnabled(False)
            self.remove_clips_button.setEnabled(False)
            self.bulk_weight_button.setEnabled(False)
            self.batch_rename_button.setEnabled(False)
            self.apply_bulk_clip_button.setEnabled(False)
            self.sort_clips_button.setEnabled(False)
            self.object_preview_button.setEnabled(False)
            self.object_contents_button.setEnabled(False)
            self.object_follow_bus_button.setEnabled(False)
            self._sync_event_mode_ui()
            if event_changed:
                self._project_bus_selection_overridden = False
            self._update_object_bus_status()
            self.set_preview_gamesync_enabled(False)
            self._loading_event = False
            return

        audio_context_label = event.display_name or event.id
        self.event_gamesync_group.setTitle(f"Audio GameSync 绑定 | {audio_context_label}")
        self.event_gamesync_context_label.setText(f"当前 Audio：{event.audio_id}")
        self.status_label.setText(f"当前事件：{event.id}")
        if self._resources_batch_feedback_event_id != event.id:
            self.clear_resources_batch_feedback(event.id, len(event.clips))
        event_tags = sorted({tag for clip in event.clips for tag in getattr(clip, "tags", [])})
        self.set_object_context(
            object_type="Event",
            object_name=event.display_name or event.id,
            breadcrumb=f"Project / Event / {event.id}",
            stats_text=f"片段 {len(event.clips)} | 标签 {len(event_tags)}",
            summary_primary=f"Audio {self._play_mode_label(event.play_mode)} | {WWISE_OUTPUT_BUS_LABEL} {event.bus}",
            summary_secondary=f"实例 {'不限' if event.max_instances == 0 else event.max_instances} | 导出 {self.runtime_audio_format_combo.currentText()}",
            can_navigate_parent=True,
        )
        self.event_id_edit.setText(event.id)
        self.display_name_edit.setText(event.display_name)
        self.tags_summary_edit.setText(", ".join(event_tags))
        event_bus_index = self.bus_combo.findData(event.bus)
        if event_bus_index >= 0:
            self.bus_combo.setCurrentIndex(event_bus_index)
        self._set_play_mode(event.play_mode)
        self.steal_policy_combo.setCurrentText(event.steal_policy)
        self.load_policy_combo.setCurrentText(event.load_policy)
        self.volume_spin.setValue(event.volume_db)
        self.volume_rand_min_spin.setValue(event.volume_rand_min_db)
        self.volume_rand_max_spin.setValue(event.volume_rand_max_db)
        self.pitch_spin.setValue(float(event.pitch_cents))
        self.pitch_rand_min_spin.setValue(event.pitch_rand_min_cents)
        self.pitch_rand_max_spin.setValue(event.pitch_rand_max_cents)
        self.cooldown_spin.setValue(event.cooldown_seconds)
        self.max_instances_spin.setValue(event.max_instances)
        self.combo_pitch_step_spin.setValue(int(round(event.combo_pitch_step_cents / 100)))
        self.combo_reset_spin.setValue(event.combo_reset_seconds)
        self.combo_max_step_spin.setValue(event.combo_max_step)
        self.avoid_repeat_check.setChecked(event.avoid_immediate_repeat)
        self.notes_edit.setPlainText(event.notes)
        self.event_audio_reference_label.setText(f"当前引用 Audio：{event.audio_id}")
        self.event_open_audio_workspace_button.setEnabled(True)
        self.event_locate_audio_browser_button.setEnabled(True)
        self._event_rtpc_bindings = [self._rtpc_binding_payload(binding) for binding in getattr(event, "rtpc_bindings", [])]
        self._event_state_overrides = [self._state_override_payload(override) for override in getattr(event, "state_overrides", [])]
        self._event_switch_variants = [self._switch_variant_payload(variant) for variant in getattr(event, "switch_variants", [])]
        self._refresh_event_binding_views()
        self._load_event_binding_editor("rtpc")
        self._load_event_binding_editor("state")
        self._load_event_binding_editor("switch")
        self._set_clip_rows(event)
        self._clip_lookup = {clip.id: clip for clip in event.clips}
        self._current_event_source_paths = self._normalized_event_source_paths(event)
        self.property_group.setEnabled(True)
        self.import_clips_button.setEnabled(True)
        self.remove_clips_button.setEnabled(bool(event.clips))
        self.bulk_weight_button.setEnabled(bool(event.clips))
        self.batch_rename_button.setEnabled(bool(event.clips))
        self.apply_bulk_clip_button.setEnabled(bool(event.clips))
        self.sort_clips_button.setEnabled(bool(event.clips))
        self.object_preview_button.setEnabled(True)
        self.object_contents_button.setEnabled(True)
        self.object_follow_bus_button.setEnabled(True)
        self._sync_event_mode_ui()
        if event_changed:
            self._project_bus_selection_overridden = False
            self._sync_current_event_bus_selection(force=True)
        else:
            self._sync_current_event_bus_selection()
        self._update_object_bus_status()
        self.set_preview_gamesync_enabled(True)
        if event.clips and not self.clip_table.selected_clip_ids():
            self.clip_table.selectRow(0)
        self._sync_clip_detail_from_table()
        self._refresh_event_source_binding_state()
        self._refresh_source_browser_tree()
        self._loading_event = False

    def _normalized_event_source_paths(self, event: EventModel | None) -> list[str]:
        if event is None:
            return []
        return sorted({str(clip.source_path).strip() for clip in event.clips if str(clip.source_path).strip()})

    def _source_filter_key(self, combo: QComboBox) -> str:
        current_data = combo.currentData()
        return str(current_data if current_data is not None else "all")

    def _source_entry_matches_query(self, entry: dict[str, object], normalized_query: str) -> bool:
        if not normalized_query:
            return True
        haystacks = [
            str(entry.get("source_path", "")).lower(),
            *[str(value).lower() for value in entry.get("event_ids", [])],
            *[str(value).lower() for value in entry.get("asset_keys", [])],
        ]
        source_name = os.path.basename(str(entry.get("source_path", ""))).lower()
        haystacks.append(source_name)
        return any(normalized_query in haystack for haystack in haystacks)

    def _source_entry_matches_filter(self, entry: dict[str, object], filter_key: str) -> bool:
        source_path = str(entry.get("source_path", "")).strip()
        reference_count = int(entry.get("reference_count", 0))
        current_event_paths = set(self._current_event_source_paths)
        if filter_key == "missing":
            return bool(entry.get("missing", False))
        if filter_key == "unreferenced":
            return bool(entry.get("unreferenced", False)) or reference_count == 0
        if filter_key == "reused":
            return reference_count > 1
        if filter_key == "current_event":
            return bool(source_path) and source_path in current_event_paths
        if filter_key == "not_current_event":
            return not source_path or source_path not in current_event_paths
        return True

    def _filtered_source_entries(self, query: str, filter_key: str) -> list[dict[str, object]]:
        normalized_query = query.strip().lower()
        return [
            entry
            for entry in self._source_browser_entries
            if self._source_entry_matches_query(entry, normalized_query) and self._source_entry_matches_filter(entry, filter_key)
        ]

    def _refresh_source_browser_tree(self) -> None:
        selected_source_paths = self.source_tree.selected_source_paths()
        current_source_path = self.source_tree.current_source_path()
        entries = self._filtered_source_entries(self.tree_filter_edit.text(), self._source_filter_key(self.source_browser_filter_combo))
        self.source_tree.rebuild(entries)
        if selected_source_paths:
            self.source_tree.set_selected_source_paths(selected_source_paths)
        elif current_source_path:
            self.source_tree.select_source_path(current_source_path)
        self._update_source_browser_summary(entries)
        self._update_source_browser_status()

    def set_audio_browser_entries(self, entries: list[dict[str, object]]) -> None:
        self._audio_browser_entries = [dict(entry) for entry in entries]
        self._refresh_audio_browser_tree()

    def _filtered_audio_entries(self, query: str) -> list[dict[str, object]]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return list(self._audio_browser_entries)
        visible_entries: list[dict[str, object]] = []
        for entry in self._audio_browser_entries:
            haystacks = [
                str(entry.get("audio_id", "")).lower(),
                str(entry.get("display_name", "")).lower(),
                str(entry.get("play_mode", "")).lower(),
                str(entry.get("bus", "")).lower(),
                *[str(value).lower() for value in entry.get("event_ids", [])],
            ]
            if any(normalized_query in value for value in haystacks):
                visible_entries.append(entry)
        return visible_entries

    def _refresh_audio_browser_tree(self) -> None:
        current_audio_id = self.audio_tree.current_audio_id()
        entries = self._filtered_audio_entries(self.tree_filter_edit.text())
        self.audio_tree.rebuild(entries)
        if current_audio_id:
            self.audio_tree.select_audio_id(current_audio_id)
        self.audio_tree.apply_filter(self.tree_filter_edit.text())
        self._update_audio_browser_summary(entries)
        self._update_audio_browser_status()

    def _update_audio_browser_summary(self, visible_entries: list[dict[str, object]]) -> None:
        total_count = len(self._audio_browser_entries)
        visible_count = len(visible_entries)
        referenced_events = sum(int(entry.get("event_count", 0)) for entry in self._audio_browser_entries)
        total_clips = sum(int(entry.get("clip_count", 0)) for entry in self._audio_browser_entries)
        self.audio_browser_summary_label.setText(
            f"Audio Object {total_count} 个 | 当前显示 {visible_count} | 引用 Event {referenced_events} 个 | 片段 {total_clips} 个"
        )

    def _update_audio_browser_status(self) -> None:
        entry = self.current_audio_browser_entry()
        if not entry:
            self.audio_browser_status_label.setText("选择一个 Audio Object，可查看模式、Bus、片段数量和引用 Event。")
            self.audio_browser_locate_event_button.setEnabled(False)
            self.audio_browser_open_bindings_button.setEnabled(False)
            return

        audio_id = str(entry.get("audio_id", "")).strip() or "-"
        play_mode = str(entry.get("play_mode", "")).strip() or "-"
        bus_name = str(entry.get("bus", "")).strip() or "-"
        clip_count = int(entry.get("clip_count", 0))
        event_ids = [str(value) for value in entry.get("event_ids", []) if str(value).strip()]
        preview_events = "、".join(event_ids[:4]) if event_ids else "-"
        self.audio_browser_status_label.setText(
            f"{audio_id}\n模式 {play_mode} | {WWISE_OUTPUT_BUS_LABEL} {bus_name} | 片段 {clip_count}\n引用 Event：{preview_events}"
        )
        self.audio_browser_locate_event_button.setEnabled(bool(event_ids))
        self.audio_browser_open_bindings_button.setEnabled(bool(event_ids))

    def current_audio_browser_entry(self) -> dict[str, object] | None:
        current_audio_id = self.audio_tree.current_audio_id()
        if not current_audio_id:
            return None
        for entry in self._audio_browser_entries:
            if str(entry.get("audio_id", "")).strip() == current_audio_id:
                return entry
        return None

    def select_audio_browser_audio(self, audio_id: str | None) -> None:
        self.audio_tree.select_audio_id(audio_id)
        self._update_audio_browser_status()

    def _update_source_browser_summary(self, visible_entries: list[dict[str, object]]) -> None:
        total_count = len(self._source_browser_entries)
        visible_count = len(visible_entries)
        missing_count = sum(1 for entry in self._source_browser_entries if bool(entry.get("missing", False)))
        unreferenced_count = sum(1 for entry in self._source_browser_entries if bool(entry.get("unreferenced", False)))
        referenced_count = total_count - unreferenced_count
        self.source_browser_summary_label.setText(
            f"源音频 {total_count} 条 | 当前显示 {visible_count} | 已引用 {referenced_count} | 缺失 {missing_count} | 未引用 {unreferenced_count}"
        )

    def _clear_event_source_binding_overview(self) -> None:
        while self.event_source_binding_overview_layout.count():
            item = self.event_source_binding_overview_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _current_event_play_mode_value(self) -> str:
        current_data = self.play_mode_combo.currentData()
        if current_data is not None:
            return str(current_data)
        current_text = self.play_mode_combo.currentText().strip()
        return current_text or "Random"

    def _refresh_event_source_binding_overview(self, clips: list[ClipModel], play_mode: str) -> None:
        self._clear_event_source_binding_overview()
        has_clips = bool(clips)
        self.event_source_binding_empty_label.setVisible(not has_clips)
        self.event_source_binding_overview_scroll.setVisible(has_clips)
        if not has_clips:
            return

        for clip in clips:
            source_name = os.path.basename(clip.source_path) or clip.asset_key or clip.id
            state_key = _binding_state_key(play_mode, clip)
            state_label = _binding_state_label(play_mode, clip)

            card = QFrame(self.event_source_binding_overview_container)
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setFrameShadow(QFrame.Shadow.Raised)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)

            header_row = QHBoxLayout()
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(8)
            name_label = QLabel(source_name)
            name_label.setProperty("role", "workspaceSectionTitle")
            state_chip = QLabel(state_label)
            header_row.addWidget(name_label, 1)
            header_row.addWidget(state_chip)

            state_detail_label = QLabel(f"Enabled {'开' if bool(clip.enabled) else '关'} | Active {'是' if bool(clip.active) else '否'}")
            state_detail_label.setWordWrap(True)
            meta_label = QLabel(f"Clip ID {clip.id} | 资源键 {clip.asset_key or '-'}")
            meta_label.setWordWrap(True)
            path_label = QLabel(clip.source_path or "未记录源路径")
            path_label.setWordWrap(True)
            path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            _apply_binding_card_style(card, state_chip, name_label, [state_detail_label, meta_label], path_label, state_key)

            card_layout.addLayout(header_row)
            card_layout.addWidget(state_detail_label)
            card_layout.addWidget(meta_label)
            card_layout.addWidget(path_label)
            self.event_source_binding_overview_layout.addWidget(card)

        self.event_source_binding_overview_layout.addStretch(1)

    def _refresh_event_source_binding_state(self) -> None:
        if not self._active_event_id:
            self.event_source_binding_summary_label.setText("当前 Audio 还没有绑定源音频。")
            self.event_source_binding_detail_label.setText("这里现在只展示当前 Audio 的绑定摘要。需要追加源音频或切换 Active / Enabled，请在 Audio 树中定位当前对象后打开 Audio 绑定。")
            self._refresh_event_source_binding_overview([], "Random")
            return

        current_event_clips = list(self._clip_lookup.values())
        play_mode = self._current_event_play_mode_value()
        bound_paths = list(self._current_event_source_paths)
        preview_names = [os.path.basename(path) or path for path in bound_paths[:4]]
        preview_text = "、".join(preview_names) if preview_names else "未绑定"
        self.event_source_binding_summary_label.setText(
            f"当前 Audio 已绑定 {len(bound_paths)} 个源音频 | {_binding_rollup_text(play_mode, current_event_clips)}\n{preview_text}"
        )
        feedback_message = self._audio_source_binding_feedback_for(self._active_event_id)
        self.event_source_binding_detail_label.setText(
            feedback_message
            or "这里只保留当前 Audio 绑定摘要。需要追加绑定、切换 Active / Enabled 或定位源音频时，请在 Audio 树中定位当前对象后打开 Audio 绑定。"
        )
        self._refresh_event_source_binding_overview(current_event_clips, play_mode)

    def _ensure_audio_bindings_popup(self) -> AudioBindingsPopup:
        if self._audio_bindings_popup is None:
            popup = AudioBindingsPopup(self)
            popup.sourceAssetsDropped.connect(
                lambda event_id, source_paths: self.assignSourceAssetsToAudioRequested.emit(event_id, source_paths, False)
            )
            popup.bindingEnabledChanged.connect(self.audioSourceBindingEnabledChangedRequested.emit)
            popup.bindingActiveChanged.connect(self.audioSourceBindingActiveChangedRequested.emit)
            popup.locateSourceRequested.connect(self._show_source_in_browser)
            self._audio_bindings_popup = popup
        return self._audio_bindings_popup

    def show_audio_bindings_popup(self, event: EventModel, global_pos: QPoint) -> None:
        popup = self._ensure_audio_bindings_popup()
        popup.set_event(event, self._audio_source_binding_feedback_for(event.id))
        popup.show_at(global_pos)

    def refresh_audio_bindings_popup(self, event: EventModel | None) -> None:
        popup = self._audio_bindings_popup
        if popup is None or not popup.isVisible():
            return
        if event is None or popup.event_id() != event.id:
            popup.close()
            return
        popup.set_event(event, self._audio_source_binding_feedback_for(event.id))

    def current_audio_bindings_popup_event_id(self) -> str | None:
        popup = self._audio_bindings_popup
        if popup is None or not popup.isVisible():
            return None
        event_id = popup.event_id().strip()
        return event_id or None

    def _audio_source_binding_feedback_for(self, event_id: str | None) -> str:
        normalized_event_id = str(event_id or "").strip()
        if not normalized_event_id or normalized_event_id != self._audio_source_binding_feedback_event_id:
            return ""
        return self._audio_source_binding_feedback_message

    def set_audio_source_binding_feedback(self, event_id: str, message: str) -> None:
        self._audio_source_binding_feedback_event_id = str(event_id).strip()
        self._audio_source_binding_feedback_message = str(message).strip()
        if self._active_event_id == self._audio_source_binding_feedback_event_id:
            self._refresh_event_source_binding_state()
        popup = self._audio_bindings_popup
        if popup is not None and popup.event_id() == self._audio_source_binding_feedback_event_id:
            popup.set_status_message(self._audio_source_binding_feedback_message)

    def clear_audio_source_binding_feedback(self, event_id: str | None = None) -> None:
        normalized_event_id = str(event_id or "").strip()
        if normalized_event_id and normalized_event_id != self._audio_source_binding_feedback_event_id:
            return
        self._audio_source_binding_feedback_event_id = ""
        self._audio_source_binding_feedback_message = ""
        if self._active_event_id:
            self._refresh_event_source_binding_state()
        popup = self._audio_bindings_popup
        if popup is not None:
            popup.set_status_message("")

    def _show_source_in_browser(self, source_path: str) -> None:
        normalized_source_path = str(source_path).strip()
        if not normalized_source_path:
            return
        self.explorer_tabs.setCurrentIndex(1)
        self.source_browser_filter_combo.setCurrentIndex(0)
        if self.tree_filter_edit.text().strip():
            self.tree_filter_edit.clear()
        self.source_tree.select_source_path(normalized_source_path)
        self.report_detail_label.setText(f"已在源音频树中定位：{normalized_source_path}")
        self.report_detail_label.setToolTip(normalized_source_path)

    def _append_selected_source_to_current_audio(self) -> None:
        source_entries = self.source_tree.selected_source_entries()
        if not source_entries:
            self.show_context_feedback("当前没有选中的源音频。")
            return
        source_paths = [
            str(entry.get("source_path", "")).strip()
            for entry in source_entries
            if str(entry.get("source_path", "")).strip()
        ]
        if not source_paths:
            return
        self.assignSourceAssetsToCurrentAudioRequested.emit(source_paths, False)
        self.show_context_feedback(f"已请求向当前 Audio 追加 {len(source_paths)} 条源音频。")

    def _request_remove_selected_sources_from_current_audio(self) -> None:
        source_paths = self.source_tree.selected_source_paths()
        if not source_paths:
            self.show_context_feedback("当前没有选中的源音频。")
            return
        self.removeSourceAssetsFromCurrentAudioRequested.emit(source_paths)

    def _request_remove_selected_sources_from_registry(self) -> None:
        source_paths = self.source_tree.selected_source_paths()
        if not source_paths:
            self.show_context_feedback("当前没有选中的源音频。")
            return
        self.removeSourceAssetsFromRegistryRequested.emit(source_paths)

    def _request_delete_selected_source_files(self) -> None:
        source_paths = self.source_tree.selected_source_paths()
        if not source_paths:
            self.show_context_feedback("当前没有选中的源音频。")
            return
        self.deleteSourceFilesRequested.emit(source_paths)

    def _append_selected_source_to_current_event(self) -> None:
        self._append_selected_source_to_current_audio()

    def _locate_selected_source_reference_audio(self) -> None:
        entry = self.source_tree.current_source_entry()
        if not entry:
            self.show_context_feedback("当前没有选中的源音频。")
            return
        target_audio_id = ""
        audio_ids = [str(value) for value in entry.get("audio_ids", []) if str(value).strip()]
        current_audio_id = self.audio_tree.current_audio_id() or self._active_audio_id or ""
        if current_audio_id and current_audio_id in audio_ids:
            target_audio_id = current_audio_id
        elif audio_ids:
            target_audio_id = audio_ids[0]
        if not target_audio_id:
            self.show_context_feedback("当前源音频没有可跳转的引用 Audio。")
            return
        self.reportTargetRequested.emit("audio", target_audio_id)
        self.show_context_feedback(f"已定位引用 Audio：{target_audio_id}", target_audio_id)

    def _locate_selected_audio_reference_event(self) -> None:
        entry = self.current_audio_browser_entry()
        if not entry:
            self.report_detail_label.setText("当前没有选中的 Audio。")
            return
        event_ids = [str(value) for value in entry.get("event_ids", []) if str(value).strip()]
        if not event_ids:
            self.report_detail_label.setText("当前 Audio 没有可跳转的引用 Event。")
            return
        self.reportTargetRequested.emit("event", event_ids[0])
        self.report_detail_label.setText(f"已定位引用 Event：{event_ids[0]}")
        self.report_detail_label.setToolTip(event_ids[0])

    def _open_selected_audio_bindings(self) -> None:
        entry = self.current_audio_browser_entry()
        if not entry:
            self.report_detail_label.setText("当前没有选中的 Audio。")
            return
        audio_id = str(entry.get("audio_id", "")).strip()
        if not audio_id:
            self.report_detail_label.setText("当前 Audio 没有可用的 Audio ID。")
            return
        self.openAudioBindingsForAudioRequested.emit(audio_id)
        self.report_detail_label.setText(f"已打开 Audio 绑定：{audio_id}")
        self.report_detail_label.setToolTip(audio_id)

    def focus_current_audio_browser(self) -> None:
        self.set_active_property_category("音频属性")
        self.explorer_tabs.setCurrentIndex(2)
        current_audio_id = self._active_audio_id
        if current_audio_id:
            self.select_audio_browser_audio(current_audio_id)
            self.report_detail_label.setText(f"已定位当前 Audio：{current_audio_id}")
            self.report_detail_label.setToolTip(current_audio_id)

    def _select_source_context_menu_target(self, position) -> None:
        item = self.source_tree.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.source_tree.blockSignals(True)
            self.source_tree.clearSelection()
            self.source_tree.setCurrentItem(item)
            item.setSelected(True)
            self.source_tree.blockSignals(False)
            self._update_source_browser_status()
            return
        self.source_tree.setCurrentItem(item)

    def _select_audio_context_menu_target(self, position) -> None:
        item = self.audio_tree.itemAt(position)
        if item is None:
            return
        self.audio_tree.setCurrentItem(item)
        item.setSelected(True)

    def _show_source_tree_context_menu(self, position) -> None:
        self._select_source_context_menu_target(position)
        menu = QMenu(self)
        locate_action = menu.addAction("定位源文件")
        copy_action = menu.addAction("复制源路径")
        locate_event_action = menu.addAction("定位引用 Audio")
        add_to_audio_action = menu.addAction("追加到 Audio")
        menu.addSeparator()
        remove_from_audio_action = menu.addAction("从当前 Audio 移除绑定")
        remove_from_registry_action = menu.addAction("从项目注册表移除")
        delete_file_action = menu.addAction("从磁盘删除源文件")

        selected_entries = self.source_tree.selected_source_entries()
        selected_paths = [str(entry.get("source_path", "")).strip() for entry in selected_entries if str(entry.get("source_path", "")).strip()]
        has_selection = bool(selected_entries)
        has_paths = bool(selected_paths)
        has_current_audio = bool(self.audio_tree.current_audio_id())
        locate_action.setEnabled(has_paths)
        copy_action.setEnabled(has_paths)
        locate_event_action.setEnabled(has_selection)
        add_to_audio_action.setEnabled(has_paths and has_current_audio)
        remove_from_audio_action.setEnabled(has_paths and has_current_audio)
        remove_from_registry_action.setEnabled(has_paths)
        delete_file_action.setEnabled(has_paths)

        action = menu.exec(self.source_tree.viewport().mapToGlobal(position))
        if action == locate_action:
            self._locate_selected_source_asset()
        elif action == copy_action:
            self._copy_selected_source_asset_path()
        elif action == locate_event_action:
            self._locate_selected_source_reference_audio()
        elif action == add_to_audio_action:
            self._append_selected_source_to_current_audio()
        elif action == remove_from_audio_action:
            self._request_remove_selected_sources_from_current_audio()
        elif action == remove_from_registry_action:
            self._request_remove_selected_sources_from_registry()
        elif action == delete_file_action:
            self._request_delete_selected_source_files()

    def _show_audio_tree_context_menu(self, position) -> None:
        self._select_audio_context_menu_target(position)
        entry = self.current_audio_browser_entry()
        menu = QMenu(self)
        rename_action = menu.addAction("重命名 Audio")
        delete_action = menu.addAction("删除 Audio")
        copy_action = menu.addAction("复制 Audio 标识")
        property_action = menu.addAction("打开属性编辑器")
        locate_event_action = menu.addAction("定位引用 Event")
        open_bindings_action = menu.addAction("打开 Audio 绑定")
        has_entry = entry is not None
        has_events = bool(entry and entry.get("event_ids"))
        rename_action.setEnabled(has_entry)
        delete_action.setEnabled(has_entry)
        copy_action.setEnabled(has_entry)
        property_action.setEnabled(has_entry)
        locate_event_action.setEnabled(has_events)
        open_bindings_action.setEnabled(has_entry)

        action = menu.exec(self.audio_tree.viewport().mapToGlobal(position))
        if action == rename_action:
            self.renameSelectedRequested.emit()
        elif action == delete_action:
            self.deleteSelectedRequested.emit()
        elif action == copy_action:
            self._handle_copy_shortcut()
        elif action == property_action:
            self.set_active_property_category("音频属性")
            self.bus_combo.setFocus()
        elif action == locate_event_action:
            self._locate_selected_audio_reference_event()
        elif action == open_bindings_action:
            self._open_selected_audio_bindings()

    def _sync_event_mode_ui(self) -> None:
        is_combo_mode = self._current_play_mode() == "Combo"
        has_instance_limit = self.max_instances_spin.value() > 0
        self.combo_group.setVisible(is_combo_mode)
        self.steal_policy_combo.setEnabled(has_instance_limit)
        if has_instance_limit:
            self.steal_policy_combo.setToolTip("达到实例上限后的处理方式。")
        else:
            self.steal_policy_combo.setToolTip("实例上限为 0 时表示不限数量，抢占策略不会生效。")

    def set_reference_context(
        self,
        parent_name: str,
        bus_name: str,
        assets_name: str,
        generation_name: str,
        work_unit_text: str,
        output_text: str,
        has_parent: bool,
    ) -> None:
        self.reference_parent_value_button.setText(parent_name)
        self.reference_parent_value_button.setEnabled(has_parent)
        self.reference_bus_value_button.setText(bus_name)
        self.reference_assets_value_button.setText(assets_name)
        self.reference_generation_value_button.setText(generation_name)
        self.reference_work_unit_label.setText(work_unit_text)
        self.reference_output_label.setText(output_text)

    def set_preview_bus_editor(
        self,
        bus_names: list[str],
        selected_bus: str,
        volume_percent: float,
        is_muted: bool,
        effective_output_text: str,
    ) -> None:
        self._loading_event = True
        current_bus = self.preview_bus_combo.currentText()
        self.preview_bus_combo.blockSignals(True)
        self.preview_bus_volume_spin.blockSignals(True)
        self.preview_bus_mute_check.blockSignals(True)
        self.preview_bus_combo.clear()
        self.preview_bus_combo.addItems(bus_names)
        target_bus = selected_bus if selected_bus in bus_names else current_bus if current_bus in bus_names else bus_names[0]
        self.preview_bus_combo.setCurrentText(target_bus)
        self.preview_bus_volume_spin.setValue(volume_percent)
        self.preview_bus_mute_check.setChecked(is_muted)
        self.preview_bus_effective_label.setText(effective_output_text)
        self.preview_bus_combo.blockSignals(False)
        self.preview_bus_volume_spin.blockSignals(False)
        self.preview_bus_mute_check.blockSignals(False)
        self._refresh_master_bus_summary()
        self._loading_event = False

    def current_preview_bus_name(self) -> str:
        return self.preview_bus_combo.currentText()

    def current_preview_bus_form_data(self) -> dict[str, object]:
        return {
            "bus_name": self.preview_bus_combo.currentText(),
            "volume_percent": self.preview_bus_volume_spin.value(),
            "is_muted": self.preview_bus_mute_check.isChecked(),
        }

    def set_object_context(
        self,
        object_type: str,
        object_name: str,
        breadcrumb: str,
        stats_text: str,
        summary_primary: str,
        summary_secondary: str,
        can_navigate_parent: bool,
    ) -> None:
        self.object_type_label.setText(object_type)
        self.object_name_label.setText(object_name)
        self.object_scope_label.setText(breadcrumb)
        self.object_stats_label.setText(stats_text)
        self.object_summary_primary_label.setText(summary_primary)
        self.object_summary_secondary_label.setText(summary_secondary)
        self.object_parent_button.setEnabled(can_navigate_parent)
        self.object_name_label.setToolTip(object_name)
        self.object_scope_label.setToolTip(breadcrumb)
        self.object_summary_primary_label.setToolTip(summary_primary)
        self.object_summary_secondary_label.setToolTip(summary_secondary)
        self.status_label.setText(f"当前对象：{object_type} / {object_name}")

    def _focus_is_within(self, widget: QWidget | None) -> bool:
        current = self.focusWidget()
        while current is not None:
            if current is widget:
                return True
            current = current.parentWidget()
        return False

    def _selected_tree_payload(self) -> tuple[str, str] | None:
        payloads = self.selected_tree_payloads()
        if payloads:
            current_item = self.tree.currentItem()
            if current_item is not None:
                current_payload = current_item.data(0, Qt.ItemDataRole.UserRole)
                if current_payload is not None:
                    typed_payload = (str(current_payload[0]), str(current_payload[1]))
                    if typed_payload in payloads:
                        return typed_payload
            return payloads[0]
        item = self.tree.currentItem()
        if item is None:
            return None
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload is None:
            return None
        return str(payload[0]), str(payload[1])

    def _active_explorer_page_key(self) -> str:
        page_keys = {0: "buses", 1: "sources", 2: "audios", 3: "events", 4: "gamesync"}
        return page_keys.get(self.explorer_tabs.currentIndex(), "events")

    def current_explorer_page_key(self) -> str:
        return self._active_explorer_page_key()

    def _sync_explorer_browser_state(self) -> None:
        placeholder_map = {
            "buses": "搜索总线",
            "sources": "搜索源音频",
            "audios": "搜索 Audio Object",
            "events": "搜索事件与文件夹",
            "gamesync": "搜索 GameSync 定义",
        }
        self.tree_filter_edit.setPlaceholderText(placeholder_map.get(self._active_explorer_page_key(), "搜索当前浏览页"))
        self._apply_explorer_filter(self.tree_filter_edit.text())

    def _apply_explorer_filter(self, query: str) -> None:
        self._apply_project_bus_browser_filter(query)
        self._refresh_source_browser_tree()
        self._refresh_audio_browser_tree()
        self._refresh_gamesync_views()
        self.tree.apply_filter(query)

    def _apply_project_bus_browser_filter(self, query: str) -> None:
        normalized = query.strip().lower()
        for root_index in range(self.project_bus_list.topLevelItemCount()):
            item = self.project_bus_list.topLevelItem(root_index)
            self._apply_project_bus_item_filter(item, normalized)
        if normalized:
            self.project_bus_list.expandAll()

    def _apply_project_bus_item_filter(self, item: QTreeWidgetItem, query: str) -> bool:
        child_visible = False
        for child_index in range(item.childCount()):
            if self._apply_project_bus_item_filter(item.child(child_index), query):
                child_visible = True
        bus_name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
        self_match = not query or query in item.text(0).lower() or query in bus_name.lower()
        visible = self_match or child_visible
        item.setHidden(not visible)
        return visible

    def selected_tree_payloads(self) -> list[tuple[str, str]]:
        return self.tree.selected_payloads()

    def selected_tree_event_ids(self) -> list[str]:
        return self.tree.selected_event_ids()

    def selected_tree_source_binding_tokens(self) -> list[str]:
        return [node_id for node_type, node_id in self.selected_tree_payloads() if node_type == "source_binding"]

    def selected_tree_source_binding_clip_ids(self) -> list[str]:
        clip_ids: list[str] = []
        seen: set[str] = set()
        for token in self.selected_tree_source_binding_tokens():
            _event_id, clip_id = decode_source_binding_token(token)
            if not clip_id or clip_id in seen:
                continue
            clip_ids.append(clip_id)
            seen.add(clip_id)
        return clip_ids

    def select_clip_ids(self, clip_ids: list[str]) -> None:
        normalized_ids = {str(value).strip() for value in clip_ids if str(value).strip()}
        selection_model = self.clip_table.selectionModel()
        self.clip_table.clearSelection()
        if selection_model is None or not normalized_ids:
            self._sync_clip_detail_from_table()
            return

        first_index = None
        for row in range(self.clip_table.rowCount()):
            item = self.clip_table.item(row, 0)
            if item is None or item.text().strip() not in normalized_ids:
                continue
            model_index = self.clip_table.model().index(row, 0)
            selection_model.select(
                model_index,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            if first_index is None:
                first_index = model_index
        if first_index is not None:
            selection_model.setCurrentIndex(first_index, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.clip_table.scrollTo(first_index)
        self._sync_clip_detail_from_table()

    def _current_workspace_context_text(self) -> str:
        mode_title = self.shell_mode_title_label.text()
        editor_index = self._editor_tab_index
        if self._active_workspace_mode == "home":
            editor_title = "欢迎页"
        elif self._active_workspace_mode in {"validation", "results"}:
            editor_title = f"结果/{self._report_page_titles[self._active_report_index].replace('当前：', '')}"
        elif self._active_workspace_mode == "events":
            editor_title = f"事件设计/{self.events_workspace_tabs.tabText(self.events_workspace_tabs.currentIndex())}"
        elif self._active_workspace_mode == "gamesync":
            editor_title = f"GameSync/{self.gamesync_workspace_tabs.tabText(self.gamesync_workspace_tabs.currentIndex())}"
        elif self._active_workspace_mode == "buses":
            editor_title = f"{WWISE_MASTER_MIXER_TITLE}/{WWISE_PROPERTY_EDITOR_TITLE}"
        elif self._active_workspace_mode == "build":
            editor_title = "构建交付/交付准备"
        elif self._active_workspace_mode == "resources":
            editor_title = f"资源整理/{self.contents_tabs.tabText(self.contents_tabs.currentIndex())}"
        elif editor_index == 0:
            editor_title = f"属性/{self._property_tab_labels[self._property_tab_index]}"
        elif editor_index == 1:
            editor_title = f"内容/{self.contents_tabs.tabText(self.contents_tabs.currentIndex())}"
        else:
            editor_title = "响度监视器"
        report_title = self._report_page_titles[self._active_report_index].replace("当前：", "")
        dirty_text = self.dirty_status_label.text()
        selected_event_count = len(self.selected_tree_event_ids())
        selected_clip_count = len(self.selected_clip_ids())
        event_text = f" | 已选事件 {selected_event_count}" if selected_event_count else ""
        clip_text = f" | 已选片段 {selected_clip_count}" if selected_clip_count else ""
        return f"模式：{mode_title} | 当前页：{editor_title} | 报告：{report_title} | 状态：{dirty_text}{event_text}{clip_text}"

    def _scrollable_widget_state(self, widget: QWidget | None) -> dict[str, int]:
        if widget is None or not hasattr(widget, "verticalScrollBar") or not hasattr(widget, "horizontalScrollBar"):
            return {}
        vertical_bar = widget.verticalScrollBar()
        horizontal_bar = widget.horizontalScrollBar()
        return {
            "vertical": int(vertical_bar.value()),
            "horizontal": int(horizontal_bar.value()),
        }

    def _apply_scrollable_widget_state(self, widget: QWidget | None, state: dict[str, object] | None) -> None:
        if widget is None or not isinstance(state, dict):
            return
        if hasattr(widget, "verticalScrollBar"):
            vertical_value = state.get("vertical")
            if isinstance(vertical_value, int):
                widget.verticalScrollBar().setValue(vertical_value)
        if hasattr(widget, "horizontalScrollBar"):
            horizontal_value = state.get("horizontal")
            if isinstance(horizontal_value, int):
                widget.horizontalScrollBar().setValue(horizontal_value)

    def _report_item_identity(self, item: QListWidgetItem | None) -> dict[str, str] | None:
        if item is None:
            return None
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        return {
            "target_type": str(payload.get("target_type", "")),
            "target_id": str(payload.get("target_id", "")),
            "title": item.text(),
        }

    def _capture_report_list_state(self, list_widget: QListWidget) -> dict[str, object]:
        return {
            "selected_item": self._report_item_identity(list_widget.currentItem()),
            "current_row": list_widget.currentRow(),
            "scroll": self._scrollable_widget_state(list_widget),
        }

    def _restore_report_list_state(self, list_widget: QListWidget, state: dict[str, object] | None) -> None:
        if not isinstance(state, dict) or list_widget.count() == 0:
            return
        selected_item = state.get("selected_item")
        target_row = -1
        if isinstance(selected_item, dict):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if self._report_item_identity(item) == selected_item:
                    target_row = row
                    break
        if target_row < 0:
            current_row = state.get("current_row")
            if isinstance(current_row, int) and 0 <= current_row < list_widget.count():
                target_row = current_row
        if target_row >= 0:
            list_widget.setCurrentRow(target_row)
        self._apply_scrollable_widget_state(list_widget, state.get("scroll"))

    def _capture_report_panel_state(self, list_widget: QListWidget, output: QPlainTextEdit) -> dict[str, object]:
        return {
            "list": self._capture_report_list_state(list_widget),
            "output": self._scrollable_widget_state(output),
        }

    def _restore_report_panel_state(
        self,
        list_widget: QListWidget,
        output: QPlainTextEdit,
        state: dict[str, object] | None,
    ) -> None:
        if not isinstance(state, dict):
            return
        self._restore_report_list_state(list_widget, state.get("list"))
        output_state = state.get("output")
        self._apply_scrollable_widget_state(output, output_state)
        QTimer.singleShot(0, lambda: self._apply_scrollable_widget_state(output, output_state))

    def navigation_state(self) -> dict[str, object]:
        return {
            "workspace_mode": self._active_workspace_mode,
            "project_bus_name": self.current_project_bus_name(),
            "project_bus_selection_overridden": self._project_bus_selection_overridden,
            "buses_workspace_tab": self.buses_workspace_tabs.currentIndex(),
            "current_bus_detail_tab": self.current_bus_detail_tabs.currentIndex(),
            "explorer_tab": self.explorer_tabs.currentIndex(),
            "editor_tab": self._editor_tab_index,
            "property_tab": self._property_tab_index,
            "events_workspace_tab": self.events_workspace_tabs.currentIndex(),
            "gamesync_workspace_tab": self.gamesync_workspace_tabs.currentIndex(),
            "contents_tab": self.contents_tabs.currentIndex(),
            "report_tab": self._active_report_index,
            "workspace_splitter_sizes": self.workspace_splitter.sizes(),
            "main_splitter_sizes": self._effective_main_splitter_sizes(),
            "content_top_splitter_sizes": self.content_top_splitter.sizes(),
            "property_scroll": self._scrollable_widget_state(self._current_property_scroll_widget()),
            "contents_scroll": self._scrollable_widget_state(self.contents_tabs.currentWidget()),
            "log_scroll": self._scrollable_widget_state(self.log_output),
            "validation_report_panel": self._capture_report_panel_state(self.validation_issue_list, self.validation_report_output),
            "build_report_panel": self._capture_report_panel_state(self.build_issue_list, self.build_report_output),
            "loudness_report_panel": self._capture_report_panel_state(self.loudness_issue_list, self.loudness_report_output),
            "diagnostic_report_panel": self._capture_report_panel_state(self.diagnostic_section_list, self.diagnostic_section_detail_output),
            "build_profile_panel": self._capture_report_panel_state(self.build_profile_list, self.build_profile_detail_output),
        }

    def apply_navigation_state(self, state: dict[str, object] | None) -> None:
        if not state:
            return
        workspace_mode = state.get("workspace_mode")
        project_bus_name = state.get("project_bus_name")
        project_bus_selection_overridden = state.get("project_bus_selection_overridden")
        buses_workspace_tab = state.get("buses_workspace_tab")
        current_bus_detail_tab = state.get("current_bus_detail_tab")
        explorer_tab = state.get("explorer_tab")
        workspace_sizes = state.get("workspace_splitter_sizes")
        main_sizes = state.get("main_splitter_sizes")
        content_sizes = state.get("content_top_splitter_sizes")
        editor_tab = state.get("editor_tab")
        property_tab = state.get("property_tab")
        events_workspace_tab = state.get("events_workspace_tab")
        gamesync_workspace_tab = state.get("gamesync_workspace_tab")
        contents_tab = state.get("contents_tab")
        report_tab = state.get("report_tab")
        if isinstance(workspace_mode, str) and workspace_mode in self._workspace_mode_pages:
            self._activate_workspace_mode(workspace_mode)
        if isinstance(workspace_sizes, list) and len(workspace_sizes) == 2:
            self._set_workspace_splitter_sizes([int(value) for value in workspace_sizes])
        if isinstance(main_sizes, list) and len(main_sizes) == 2:
            self._set_main_splitter_sizes([int(value) for value in main_sizes])
        if isinstance(content_sizes, list) and len(content_sizes) == 2:
            self._set_content_top_splitter_sizes([int(value) for value in content_sizes])
        if isinstance(explorer_tab, int) and 0 <= explorer_tab < self.explorer_tabs.count():
            self.explorer_tabs.setCurrentIndex(explorer_tab)
        if isinstance(buses_workspace_tab, int) and 0 <= buses_workspace_tab < self.buses_workspace_tabs.count():
            self.buses_workspace_tabs.setCurrentIndex(buses_workspace_tab)
        if isinstance(current_bus_detail_tab, int) and 0 <= current_bus_detail_tab < self.current_bus_detail_tabs.count():
            self.current_bus_detail_tabs.setCurrentIndex(current_bus_detail_tab)
        if isinstance(editor_tab, int) and 0 <= editor_tab < len(self._editor_tab_labels):
            self._editor_tab_index = editor_tab
        if isinstance(property_tab, int) and 0 <= property_tab < len(self._property_tab_labels):
            self._property_tab_index = property_tab
        if isinstance(events_workspace_tab, int) and 0 <= events_workspace_tab < self.events_workspace_tabs.count():
            self.events_workspace_tabs.setCurrentIndex(events_workspace_tab)
        if isinstance(gamesync_workspace_tab, int) and 0 <= gamesync_workspace_tab < self.gamesync_workspace_tabs.count():
            self.gamesync_workspace_tabs.setCurrentIndex(gamesync_workspace_tab)
        if isinstance(contents_tab, int) and 0 <= contents_tab < self.contents_tabs.count():
            self.contents_tabs.setCurrentIndex(contents_tab)
        if isinstance(report_tab, int) and 0 <= report_tab < len(self._report_tab_labels):
            self._active_report_index = report_tab
            self.report_pages.setCurrentIndex(report_tab)
            self._report_tab_index = report_tab
        if (
            project_bus_selection_overridden
            and isinstance(project_bus_name, str)
            and project_bus_name
            and project_bus_name != self._current_event_bus_name()
        ):
            self._select_project_bus_by_name(project_bus_name)
        self._apply_scrollable_widget_state(self._current_property_scroll_widget(), state.get("property_scroll"))
        self._apply_scrollable_widget_state(self.contents_tabs.currentWidget(), state.get("contents_scroll"))
        self._apply_scrollable_widget_state(self.log_output, state.get("log_scroll"))
        self._restore_report_panel_state(self.validation_issue_list, self.validation_report_output, state.get("validation_report_panel"))
        self._restore_report_panel_state(self.build_issue_list, self.build_report_output, state.get("build_report_panel"))
        self._restore_report_panel_state(self.loudness_issue_list, self.loudness_report_output, state.get("loudness_report_panel"))
        self._restore_report_panel_state(self.diagnostic_section_list, self.diagnostic_section_detail_output, state.get("diagnostic_report_panel"))
        self._restore_report_panel_state(self.build_profile_list, self.build_profile_detail_output, state.get("build_profile_panel"))

    def _update_object_bus_status(self) -> None:
        current_event_bus = self._current_event_bus_name() or "-"
        current_project_bus = self.current_project_bus_name() or "-"
        self.object_event_bus_chip.setText(f"{WWISE_OUTPUT_BUS_LABEL} {current_event_bus}")
        if self._project_bus_selection_overridden and current_project_bus != current_event_bus:
            self.object_bus_browser_chip.setText(f"{WWISE_BUS_VIEW_LABEL} {current_project_bus}")
            bus_hint = f"当前正在浏览其他 Bus {current_project_bus}；点击“跟随 {WWISE_OUTPUT_BUS_LABEL}”可回到当前对象。"
        else:
            self.object_bus_browser_chip.setText(f"{WWISE_BUS_VIEW_LABEL} {current_project_bus}")
            bus_hint = f"当前 {WWISE_BUS_VIEW_LABEL} 跟随 {WWISE_OUTPUT_BUS_LABEL} {current_project_bus}。"
        self.object_context_hint_label.setText(f"{self._current_workspace_context_text()} | {bus_hint}")
        self._update_workspace_summary_labels()
        self.diagnosticContextChanged.emit()

    def _update_workspace_summary_labels(self) -> None:
        selected_event_count = len(self.selected_tree_event_ids())
        selected_clip_count = len(self.selected_clip_ids())
        current_event_bus = self._current_event_bus_name() or "-"
        current_project_bus = self.current_project_bus_name() or "-"
        export_root = self.export_root_edit.text().strip() or "未设置"
        runtime_format = self.runtime_audio_format_combo.currentText() or "-"
        current_results_title = self._report_page_titles[self._active_report_index].replace("当前：", "")
        event_workspace_title = self.events_workspace_tabs.tabText(self.events_workspace_tabs.currentIndex())
        resources_workspace_title = self.contents_tabs.tabText(self.contents_tabs.currentIndex())
        buses_workspace_title = self.buses_workspace_tabs.tabText(self.buses_workspace_tabs.currentIndex())
        current_bus_detail_title = self.current_bus_detail_tabs.tabText(self.current_bus_detail_tabs.currentIndex())

        self.events_workspace_status_label.setText(
            f"已选事件 {selected_event_count} | 当前子页 {event_workspace_title} | {WWISE_OUTPUT_BUS_LABEL} {current_event_bus}。"
        )
        self.event_overview_hint_label.setText(
            f"当前浏览 {event_workspace_title}。左侧保留单一对象摘要，主画布聚焦事件参数与响度。"
        )
        self.resources_workspace_status_label.setText(
            f"已选片段 {selected_clip_count} | 当前页 {resources_workspace_title} | 资源整理后可直接切到生成预览。"
        )
        if self._has_resources_batch_feedback:
            self.resources_overview_hint_label.setText(
                f"当前浏览 {resources_workspace_title}，已选片段 {selected_clip_count}。最近操作：{self.resources_batch_feedback_title_label.text()}。"
            )
        else:
            self.resources_overview_hint_label.setText(
                f"当前浏览 {resources_workspace_title}，已选片段 {selected_clip_count}。先做片段编排，再进批处理或预览镜像。"
            )
        self.buses_workspace_status_label.setText(
            f"当前页 {buses_workspace_title}{' / ' + current_bus_detail_title if buses_workspace_title == '当前 Bus' else ''} | {WWISE_BUS_VIEW_LABEL} {current_project_bus} | {WWISE_OUTPUT_BUS_LABEL} {current_event_bus} | {WWISE_DEFAULT_BUS_LABEL} {self.default_bus_combo.currentText() or '-'}。"
        )
        self.buses_overview_hint_label.setText(
            f"当前浏览 {buses_workspace_title}{' / ' + current_bus_detail_title if buses_workspace_title == '当前 Bus' else ''} / Bus {current_project_bus}。左侧只保留导航与工程设置，主画布按页签拆分路由、工程总览和 GameSync。"
        )
        gamesync_tab_title = self.gamesync_workspace_tabs.tabText(self.gamesync_workspace_tabs.currentIndex())
        total_gamesync_count = sum(len(self._gamesync_entries.get(key, [])) for key in ("game_parameters", "state_groups", "switch_groups"))
        self.gamesync_workspace_status_label.setText(
            f"当前页 {gamesync_tab_title} | GameSync 对象 {total_gamesync_count} 个 | phase3 工程对象已接入。"
        )
        self.gamesync_overview_hint_label.setText(
            f"当前浏览 {gamesync_tab_title}。先稳定项目级对象，再推进 Event / Bus 绑定与 Schema v2。"
        )
        if self._build_status_detail_override is not None:
            self.build_workspace_status_label.setText(self._build_status_detail_override)
        else:
            self.build_workspace_status_label.setText(
                f"导出目录 {export_root} | 运行时格式 {runtime_format} | {self.build_scope_target_label.text().strip()}。"
            )
        if self._build_status_summary_override is not None:
            self.build_overview_hint_label.setText(self._build_status_summary_override)
        else:
            self.build_overview_hint_label.setText(
                f"先确认导出目录、构建范围和差异画像，再执行正式构建。"
            )
        self.validation_overview_hint_label.setText(
            f"{self.validation_filter_status_label.text()} 优先修错误，再处理警告。"
        )
        self.results_overview_hint_label.setText(
            f"当前结果页 {current_results_title}。这里统一回看日志、校验、构建、响度和诊断。"
        )
        self._update_diagnostic_snapshot_labels()

    def _build_report_center_page(
        self,
        summary_label: QLabel,
        issue_list: QListWidget,
        detail_output: QPlainTextEdit,
        *,
        splitter_name: str,
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        summary_label.setWordWrap(True)
        issue_list.setAlternatingRowColors(True)
        splitter = QSplitter()
        splitter.setObjectName(splitter_name)
        splitter.setOrientation(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(issue_list)
        splitter.addWidget(detail_output)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(summary_label)
        layout.addWidget(splitter)
        return page

    def _report_item_state(self, payload: dict[str, object]) -> str:
        explicit_state = str(payload.get("state", "")).strip().casefold()
        if explicit_state in {"error", "warning", "success", "info"}:
            return explicit_state
        severity = str(payload.get("severity", "")).strip().casefold()
        if severity == "error":
            return "error"
        if severity == "warning":
            return "warning"
        if severity == "success":
            return "success"
        if severity == "info":
            return "info"
        title = str(payload.get("title", "")).casefold()
        detail = str(payload.get("detail", "")).casefold()
        haystack = f"{title} {detail}"
        if any(token in haystack for token in ["超标", "失败", "error", "缺失"]):
            return "error"
        if any(token in haystack for token in ["警告", "warning", "差异", "risk"]):
            return "warning"
        if any(token in haystack for token in ["通过", "完成", "success", "已刷新"]):
            return "success"
        return "info"

    def _apply_report_item_state(self, list_item: QListWidgetItem, payload: dict[str, object]) -> None:
        state = self._report_item_state(payload)
        palette = {
            "error": (QColor("#ffd8d8"), QColor("#4a2327")),
            "warning": (QColor("#ffe8bf"), QColor("#4b3a1c")),
            "success": (QColor("#d9f6e6"), QColor("#1f3a31")),
            "info": (QColor("#d8ecff"), QColor("#203948")),
        }
        foreground, background = palette.get(state, palette["info"])
        list_item.setForeground(QBrush(foreground))
        list_item.setBackground(QBrush(background))

    def _set_report_items(self, list_widget: QListWidget, items: list[dict[str, object]]) -> None:
        list_widget.clear()
        for item in items:
            label = str(item.get("title", ""))
            list_item = QListWidgetItem(label)
            list_item.setToolTip(str(item.get("detail", label)))
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._apply_report_item_state(list_item, item)
            list_widget.addItem(list_item)
        if items:
            list_widget.setCurrentRow(0)

    def _update_report_detail_from_item(self, list_widget: QListWidget, output: QPlainTextEdit) -> None:
        item = list_widget.currentItem()
        if item is None:
            output.setPlainText("当前没有选中问题条目。")
            return
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        output.setPlainText(str(payload.get("detail", "")))

    def _activate_report_item(self, list_widget: QListWidget) -> None:
        item = list_widget.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        target_type = str(payload.get("target_type", "")).strip()
        target_id = str(payload.get("target_id", "")).strip()
        if target_type and target_id:
            self.reportTargetRequested.emit(target_type, target_id)

    def set_active_property_category(self, category: str) -> None:
        tab_map = {"事件": 0, "音频属性": 1, "生成": 2, "工程": 3}
        index = tab_map.get(category)
        if index is not None:
            if category == "音频属性":
                self._activate_workspace_mode("events")
                self.events_workspace_tabs.setCurrentIndex(1)
            elif category == "生成":
                self._activate_workspace_mode("build")
            elif category == "工程":
                self._activate_workspace_mode("buses")
            else:
                self._activate_workspace_mode("events")
                self.events_workspace_tabs.setCurrentIndex(0)
            self._editor_tab_index = 0
            self._property_tab_index = index
            self._update_object_bus_status()

    def show_loudness_view(self) -> None:
        self._activate_workspace_mode("events")
        self._editor_tab_index = 2
        self.events_workspace_tabs.setCurrentIndex(2)
        self._update_object_bus_status()

    def _toggle_preview_transport_pause(self) -> None:
        if self._preview_transport_state == "paused":
            self.resumePreviewRequested.emit()
            return
        self.pausePreviewRequested.emit()

    def set_recent_preview_session_summary(self, title: str, detail: str) -> None:
        normalized_title = title.strip() or "最近试听"
        normalized_detail = detail.strip() or "切换事件、资源或流程时，会保留最近一次试听会话。"
        self.preview_transport_title_label.setText(normalized_title)
        self.preview_transport_title_label.setToolTip(normalized_title)
        self.preview_transport_detail_label.setText(normalized_detail)
        self.preview_transport_detail_label.setToolTip(normalized_detail)

    def clear_recent_preview_insight(self) -> None:
        self.preview_waveform_strip.clear()
        self.preview_waveform_strip.setToolTip("最近一次试听的波形概览。")
        self.preview_inline_momentary_max_value.setText("-Inf")

    def set_recent_preview_source(self, source_path: str, clip_id: str, asset_key: str) -> None:
        if not source_path:
            self.clear_recent_preview_insight()
            return
        self.preview_waveform_strip.set_clip(source_path)
        self.preview_waveform_strip.setToolTip(f"片段 {clip_id} | 资源 {asset_key}")

    def _preview_transport_auto_expanded(self) -> bool:
        return self._preview_transport_state in {"playing", "paused"}

    def _apply_preview_transport_expanded(self, expanded: bool) -> None:
        self._preview_transport_details_expanded = expanded
        self.preview_transport_detail_label.setVisible(True)
        self.preview_transport_metrics_frame.setVisible(False)
        self.preview_transport_toggle_button.blockSignals(True)
        self.preview_transport_toggle_button.setChecked(False)
        self.preview_transport_toggle_button.blockSignals(False)
        self.preview_transport_toggle_button.setArrowType(Qt.ArrowType.RightArrow)
        self.preview_transport_toggle_button.setToolTip("最近试听详情已改为底栏只读概览。")
        self.preview_transport_toggle_button.setProperty("expanded", False)

        self.loudness_group.setMinimumWidth(0)
        self.loudness_group.setMaximumWidth(16777215)
        if hasattr(self, "activity_preview_host"):
            self.activity_preview_host.updateGeometry()

        self.loudness_group.updateGeometry()
        self._refresh_preview_transport_style()

    def _tree_preview_context_actions(self, *, has_event_target: bool) -> list[tuple[str, str]]:
        if not has_event_target:
            return []
        actions: list[tuple[str, str]] = [("preview", "试听事件")]
        if self._preview_transport_state == "playing":
            actions.append(("pause", "暂停当前试听"))
            actions.append(("stop", "停止当前试听"))
        elif self._preview_transport_state == "paused":
            actions.append(("resume", "继续当前试听"))
            actions.append(("stop", "停止当前试听"))
        if self._preview_transport_can_replay:
            actions.append(("restart", "从头播放最近试听"))
        return actions

    def _dispatch_tree_preview_context_action(self, action_key: str) -> None:
        if action_key == "preview":
            self.previewRequested.emit()
        elif action_key == "pause":
            self.pausePreviewRequested.emit()
        elif action_key == "resume":
            self.resumePreviewRequested.emit()
        elif action_key == "restart":
            self.restartPreviewRequested.emit()
        elif action_key == "stop":
            self.stopPreviewEventRequested.emit()

    def _sync_preview_transport_presentation(self) -> None:
        expanded = (
            self._preview_transport_expansion_pinned
            if self._preview_transport_expansion_pinned is not None
            else self._preview_transport_auto_expanded()
        )
        self._apply_preview_transport_expanded(expanded)

    def _toggle_preview_transport_details(self, expanded: bool) -> None:
        adaptive_expanded = self._preview_transport_auto_expanded()
        self._preview_transport_expansion_pinned = None if expanded == adaptive_expanded else expanded
        self._apply_preview_transport_expanded(expanded)

    def _set_preview_metric_context(self, label: QLabel, text: str) -> None:
        label.setText(text)
        label.setToolTip(text)

    def _refresh_preview_transport_style(self) -> None:
        for widget in [
            self.preview_transport_header,
            self.preview_transport_frame,
            self.preview_transport_metrics_frame,
            self.preview_rtpc_transport_frame,
            self.preview_gamesync_modes_frame,
            self.preview_transport_title_label,
            self.preview_transport_status_chip,
            self.preview_transport_toggle_button,
            self.preview_transport_detail_label,
            self.preview_transport_play_button,
            self.preview_transport_pause_button,
            self.preview_transport_restart_button,
            self.preview_transport_stop_button,
            self.open_loudness_view_button,
            self.preview_parameter_current_label,
            self.preview_parameter_min_label,
            self.preview_parameter_max_label,
            self.preview_parameter_slider,
        ]:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def set_preview_transport_state(self, state: str, *, has_target: bool, can_replay: bool) -> None:
        normalized_state = state if state in {"idle", "playing", "paused"} else "idle"
        self._preview_transport_state = normalized_state
        self._preview_transport_has_target = has_target
        self._preview_transport_can_replay = can_replay
        has_playback = normalized_state in {"playing", "paused"}
        status_text = {
            "playing": "播放中",
            "paused": "已暂停",
            "idle": "可重播" if can_replay else ("可试听" if has_target else "待命"),
        }[normalized_state]
        self.preview_transport_play_button.setEnabled(has_target or can_replay)
        self.preview_transport_pause_button.setEnabled(has_playback)
        self.preview_transport_restart_button.setEnabled(can_replay)
        self.preview_transport_stop_button.setEnabled(has_playback)
        self.preview_transport_pause_button.setIcon(load_app_icon("play" if normalized_state == "paused" else "pause"))
        self.preview_transport_status_chip.setText(status_text)
        self.preview_transport_status_chip.setToolTip(status_text)
        self.preview_transport_status_chip.setProperty("transportState", normalized_state)
        if can_replay:
            self.preview_transport_play_button.setToolTip("播放最近试听")
        elif has_target:
            self.preview_transport_play_button.setToolTip("试听当前对象")
        else:
            self.preview_transport_play_button.setToolTip("当前没有可播放的试听")
        self.preview_transport_pause_button.setToolTip("继续试听" if normalized_state == "paused" else "暂停试听")
        self.preview_transport_restart_button.setToolTip("从头播放最近一次试听")
        self.preview_transport_stop_button.setToolTip("停止当前试听")
        self.open_loudness_view_button.setToolTip("打开响度监视器")
        self.preview_transport_frame.setProperty("transportState", normalized_state)
        self.preview_transport_play_button.setProperty("transportState", "active" if normalized_state == "playing" else "idle")
        self.preview_transport_pause_button.setProperty("transportState", "active" if normalized_state == "paused" else "idle")
        self.preview_transport_restart_button.setProperty(
            "transportState",
            "available" if can_replay else "idle",
        )
        self.preview_transport_stop_button.setProperty("transportState", "available" if has_playback else "idle")
        self.open_loudness_view_button.setProperty("transportState", "idle")
        self._sync_preview_transport_presentation()

    def set_active_contents_category(self, category: str) -> None:
        if category == "生成":
            self._activate_workspace_mode("build")
        else:
            self._activate_workspace_mode("resources")
        self._editor_tab_index = 1
        if category == "片段":
            self.contents_tabs.setCurrentIndex(0)
            self._set_content_top_splitter_sizes(self._default_focus_content_splitter_sizes)
        elif category == "批处理":
            self.contents_tabs.setCurrentIndex(1)
        elif category == "生成":
            self.contents_tabs.setCurrentIndex(2)
        self._update_object_bus_status()

    def _set_selected_clip_details(self, clip) -> None:
        self._loading_clip_details = True
        if clip is None:
            self._apply_clip_time_limits(None)
            self.clip_selected_label.setText("未选择片段")
            self.clip_source_detail_edit.clear()
            self.clip_asset_detail_edit.clear()
            self.clip_weight_detail_spin.setValue(1)
            self._sync_weight_preset_combo(self.clip_weight_preset_combo, 1)
            self.clip_trim_start_spin.setValue(0)
            self.clip_trim_end_spin.setValue(0)
            self.clip_fade_in_spin.setValue(0)
            self.clip_fade_out_spin.setValue(0)
            self.clip_loop_start_spin.setValue(0)
            self.clip_loop_end_spin.setValue(0)
            self.clip_tags_detail_edit.clear()
            self.clip_waveform_editor.clear()
            self.clip_playhead_label.setText("游标 0 ms")
            self.clip_preview_hint_label.setText("选择片段后可直接在波形上拖拽裁剪、淡入淡出和循环区；滚轮缩放，双击聚焦选区，并可局部试听。")
            self.clip_preview_button.setEnabled(False)
            self.clip_preview_segment_button.setEnabled(False)
            self.clip_copy_asset_key_button.setEnabled(False)
            self.clip_locate_source_button.setEnabled(False)
            for button in [
                self.clip_waveform_zoom_out_button,
                self.clip_waveform_zoom_reset_button,
                self.clip_waveform_frame_selection_button,
                self.clip_waveform_zoom_in_button,
                self.clip_set_start_from_playhead_button,
                self.clip_set_end_from_playhead_button,
                self.clip_set_loop_from_selection_button,
                self.clip_clear_loop_button,
            ]:
                button.setEnabled(False)
            self._loading_clip_details = False
            return

        clip_duration_ms = self._apply_clip_time_limits(clip)
        self.clip_selected_label.setText(clip.id)
        self.clip_source_detail_edit.setText(clip.source_path)
        self.clip_asset_detail_edit.setText(clip.asset_key)
        self.clip_weight_detail_spin.setValue(clip.weight)
        self._sync_weight_preset_combo(self.clip_weight_preset_combo, clip.weight)
        self.clip_trim_start_spin.setValue(clip.trim_start_ms)
        self.clip_trim_end_spin.setValue(clip.trim_end_ms)
        self.clip_fade_in_spin.setValue(getattr(clip, "fade_in_ms", 0))
        self.clip_fade_out_spin.setValue(getattr(clip, "fade_out_ms", 0))
        self.clip_loop_start_spin.setValue(clip.loop_start_ms)
        self.clip_loop_end_spin.setValue(clip.loop_end_ms)
        self.clip_tags_detail_edit.setText(", ".join(getattr(clip, "tags", [])))
        self.clip_waveform_editor.set_clip(
            clip.source_path,
            trim_start_ms=clip.trim_start_ms,
            trim_end_ms=clip.trim_end_ms,
            fade_in_ms=getattr(clip, "fade_in_ms", 0),
            fade_out_ms=getattr(clip, "fade_out_ms", 0),
            loop_start_ms=clip.loop_start_ms,
            loop_end_ms=clip.loop_end_ms,
        )
        self.clip_playhead_label.setText(f"游标 {self.clip_waveform_editor.playhead_ms()} ms")
        hint_segments = [
            f"源：{os.path.basename(clip.source_path) if clip.source_path else '未指定'}",
            "拖拽裁剪/淡入淡出/循环",
            "滚轮缩放，双击聚焦，支持局部试听",
        ]
        if clip_duration_ms is not None:
            hint_segments.append(f"范围 0-{clip_duration_ms} ms")
            if any(value > clip_duration_ms for value in [clip.trim_start_ms, clip.loop_start_ms]) or any(value > clip_duration_ms for value in [clip.trim_end_ms, clip.loop_end_ms] if value > 0):
                hint_segments.append("裁剪或循环已超出源文件长度")
        else:
            hint_segments.append("无法读取音频时长")
        selected_count = len(self.selected_clip_ids())
        if selected_count > 1:
            hint_segments.insert(0, f"已选 {selected_count} 个片段，当前编辑首条")
        else:
            hint_segments.insert(0, f"片段 {clip.id}")
        self.clip_preview_hint_label.setText(" | ".join(hint_segments))
        self.clip_preview_button.setEnabled(True)
        self.clip_preview_segment_button.setEnabled(True)
        self.clip_copy_asset_key_button.setEnabled(True)
        self.clip_locate_source_button.setEnabled(True)
        for button in [
            self.clip_waveform_zoom_out_button,
            self.clip_waveform_zoom_reset_button,
            self.clip_waveform_frame_selection_button,
            self.clip_waveform_zoom_in_button,
            self.clip_set_start_from_playhead_button,
            self.clip_set_end_from_playhead_button,
            self.clip_set_loop_from_selection_button,
            self.clip_clear_loop_button,
        ]:
            button.setEnabled(True)
        self._loading_clip_details = False

    def _apply_clip_time_limits(self, clip) -> int | None:
        maximum_ms = MAX_CLIP_TIME_MS
        duration_ms: int | None = None
        if clip is not None and getattr(clip, "source_path", "") and sf is not None:
            try:
                info = sf.info(clip.source_path)
                if info.samplerate > 0:
                    duration_ms = max(MIN_CLIP_TIME_MS, int(round(info.frames * 1000.0 / info.samplerate)))
                    maximum_ms = duration_ms
            except Exception:
                duration_ms = None
        for spin_box in [
            self.clip_trim_start_spin,
            self.clip_trim_end_spin,
            self.clip_fade_in_spin,
            self.clip_fade_out_spin,
            self.clip_loop_start_spin,
            self.clip_loop_end_spin,
        ]:
            spin_box.setRange(MIN_CLIP_TIME_MS, maximum_ms)
        return duration_ms

    def _sync_clip_waveform_from_controls(self) -> None:
        self.clip_waveform_editor.set_selection(
            self.clip_trim_start_spin.value(),
            self.clip_trim_end_spin.value(),
            self.clip_fade_in_spin.value(),
            self.clip_fade_out_spin.value(),
            emit_signal=False,
        )
        self.clip_waveform_editor.set_loop(
            self.clip_loop_start_spin.value(),
            self.clip_loop_end_spin.value(),
            emit_signal=False,
        )

    def _handle_clip_timing_spin_change(self, field_name: str, value: int) -> None:
        self._emit_selected_clip_detail_change(field_name, str(value))
        if not self._loading_clip_details:
            self._sync_clip_waveform_from_controls()

    def _handle_clip_waveform_change(self, trim_start_ms: int, trim_end_ms: int, fade_in_ms: int, fade_out_ms: int) -> None:
        if self._loading_clip_details:
            return
        updates: list[tuple[QSpinBox, int, str]] = [
            (self.clip_trim_start_spin, trim_start_ms, "trim_start_ms"),
            (self.clip_trim_end_spin, trim_end_ms, "trim_end_ms"),
            (self.clip_fade_in_spin, fade_in_ms, "fade_in_ms"),
            (self.clip_fade_out_spin, fade_out_ms, "fade_out_ms"),
        ]
        changed_fields: list[tuple[str, int]] = []
        self._loading_clip_details = True
        for spin_box, new_value, field_name in updates:
            if spin_box.value() != new_value:
                spin_box.setValue(new_value)
                changed_fields.append((field_name, new_value))
        self._loading_clip_details = False
        for field_name, new_value in changed_fields:
            self._emit_selected_clip_detail_change(field_name, str(new_value))

    def _handle_clip_waveform_loop_change(self, loop_start_ms: int, loop_end_ms: int) -> None:
        if self._loading_clip_details:
            return
        updates: list[tuple[QSpinBox, int, str]] = [
            (self.clip_loop_start_spin, loop_start_ms, "loop_start_ms"),
            (self.clip_loop_end_spin, loop_end_ms, "loop_end_ms"),
        ]
        changed_fields: list[tuple[str, int]] = []
        self._loading_clip_details = True
        for spin_box, new_value, field_name in updates:
            if spin_box.value() != new_value:
                spin_box.setValue(new_value)
                changed_fields.append((field_name, new_value))
        self._loading_clip_details = False
        for field_name, new_value in changed_fields:
            self._emit_selected_clip_detail_change(field_name, str(new_value))

    def _handle_clip_waveform_playhead_change(self, playhead_ms: int) -> None:
        self.clip_playhead_label.setText(f"游标 {playhead_ms} ms")

    def _set_clip_trim_start_from_playhead(self) -> None:
        if self._loading_clip_details:
            return
        maximum_start = self.clip_trim_end_spin.value() - 1 if self.clip_trim_end_spin.value() > 0 else max(MIN_CLIP_TIME_MS, self.clip_waveform_editor.duration_ms() - 1)
        target_value = min(self.clip_waveform_editor.playhead_ms(), maximum_start)
        self.clip_trim_start_spin.setValue(max(MIN_CLIP_TIME_MS, target_value))

    def _set_clip_trim_end_from_playhead(self) -> None:
        if self._loading_clip_details:
            return
        playhead_ms = self.clip_waveform_editor.playhead_ms()
        minimum_end = self.clip_trim_start_spin.value() + 1
        target_value = max(minimum_end, playhead_ms)
        if self.clip_waveform_editor.duration_ms() > 0 and target_value >= self.clip_waveform_editor.duration_ms():
            target_value = 0
        self.clip_trim_end_spin.setValue(target_value)

    def _set_clip_loop_from_selection(self) -> None:
        if self._loading_clip_details:
            return
        self.clip_loop_start_spin.setValue(self.clip_trim_start_spin.value())
        selection_end = self.clip_trim_end_spin.value()
        if selection_end == 0 and self.clip_waveform_editor.duration_ms() > 0:
            selection_end = self.clip_waveform_editor.duration_ms()
        self.clip_loop_end_spin.setValue(max(self.clip_loop_start_spin.value() + 1, selection_end))

    def _clear_clip_loop(self) -> None:
        if self._loading_clip_details:
            return
        self.clip_loop_start_spin.setValue(0)
        self.clip_loop_end_spin.setValue(0)

    def _request_selected_clip_segment_preview(self) -> None:
        clip_ids = self.selected_clip_ids()
        if not clip_ids:
            return
        playhead_ms = self.clip_waveform_editor.playhead_ms()
        duration_ms = self.clip_waveform_editor.duration_ms()
        if duration_ms > 0:
            segment_start_ms = max(MIN_CLIP_TIME_MS, playhead_ms - 120)
            segment_end_ms = min(duration_ms, segment_start_ms + 1500)
            if segment_end_ms <= segment_start_ms:
                segment_end_ms = min(duration_ms, max(segment_start_ms + 1, playhead_ms + 600))
        else:
            segment_start_ms = self.clip_trim_start_spin.value()
            segment_end_ms = self.clip_trim_end_spin.value()
        if segment_end_ms > segment_start_ms:
            self.previewClipSegmentRequested.emit(clip_ids[0], segment_start_ms, segment_end_ms)

    def _populate_weight_preset_combo(self, combo: QComboBox) -> None:
        combo.addItem("自定义", None)
        for value in CLIP_WEIGHT_PRESETS:
            combo.addItem(f"预设 {value}", value)

    def _build_weight_editor(self, spin_box: QSpinBox, preset_combo: QComboBox) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(spin_box, 1)
        layout.addWidget(preset_combo)
        return row

    def _build_property_compat_scroll(self, title: str, description: str) -> QScrollArea:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._build_empty_state_card(title, description))
        layout.addStretch(1)
        return self._wrap_scrollable_page(content)

    def _current_property_compat_widget(self) -> QWidget | None:
        index = self._property_tab_index
        if index == 0:
            return self.event_design_scroll
        return self._property_compat_scroll_pages.get(index)

    def _sync_weight_preset_combo(self, combo: QComboBox, value: int) -> None:
        index = combo.findData(value)
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _apply_weight_preset(self, spin_box: QSpinBox, combo: QComboBox) -> None:
        preset_value = combo.currentData()
        if preset_value is None:
            return
        spin_box.setValue(int(preset_value))

    def _sync_clip_detail_from_table(self) -> None:
        clip_ids = self.clip_table.selected_clip_ids()
        if not clip_ids:
            self._set_selected_clip_details(None)
            self._update_object_bus_status()
            return
        self._set_selected_clip_details(self._clip_lookup.get(clip_ids[0]))
        self._update_object_bus_status()

    def _emit_selected_clip_detail_change(self, field_name: str, raw_value: str) -> None:
        if self._loading_clip_details:
            return
        clip_ids = self.clip_table.selected_clip_ids()
        if not clip_ids:
            return
        clip_id = clip_ids[0]
        if clip_id not in self._clip_lookup:
            return
        self.clipEdited.emit(clip_id, field_name, raw_value)

    def _build_two_column_page(
        self,
        left_widgets: list[QWidget],
        right_widgets: list[QWidget],
        *,
        splitter_name: str | None = None,
        compact_breakpoint: int | None = None,
    ) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        for widget in left_widgets:
            left_column.addWidget(self._wrap_workspace_widget(widget))
        left_column.addStretch(1)
        for widget in right_widgets:
            right_column.addWidget(self._wrap_workspace_widget(widget))
        right_column.addStretch(1)
        left_container = QWidget()
        left_container.setLayout(left_column)
        right_container = QWidget()
        right_container.setLayout(right_column)
        splitter = QSplitter()
        if splitter_name:
            splitter.setObjectName(splitter_name)
        splitter.setOrientation(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_container)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setProperty("responsiveBreakPoint", compact_breakpoint or self._two_column_compact_breakpoint)
        splitter.splitterMoved.connect(lambda *_args: self._schedule_layout_flush())
        self._responsive_two_column_splitters.append(splitter)
        layout.addWidget(splitter)
        return page

    def _wrap_scrollable_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(page)
        return scroll

    def _wrap_overview_scroll(self, panel: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(220)
        scroll.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        return scroll

    def _build_meter_stat_card(self, title: str, value_label: QLabel, unit_text: str) -> QWidget:
        card = QFrame()
        card.setObjectName("MeterStatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        title_label = QLabel(title)
        title_label.setProperty("role", "meterTitle")
        value_label.setProperty("role", "meterValue")
        unit_label = QLabel(unit_text)
        unit_label.setProperty("role", "meterUnit")
        layout.addWidget(title_label)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.addWidget(value_label)
        value_row.addWidget(unit_label)
        value_row.addStretch(1)
        layout.addLayout(value_row)
        return card

    def _build_meter_inline_stat(self, title: str, value_label: QLabel, unit_text: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(title)
        title_label.setProperty("role", "meterTitle")
        value_label.setProperty("role", "meterInlineValue")
        unit_label = QLabel(unit_text)
        unit_label.setProperty("role", "meterUnit")
        layout.addWidget(title_label)
        layout.addSpacing(10)
        layout.addWidget(value_label)
        layout.addWidget(unit_label)
        layout.addStretch(1)
        return row

    def _build_preview_metric_column(
        self,
        heading: str,
        context_label: QLabel,
        integrated_label: QLabel,
        true_peak_label: QLabel,
    ) -> QWidget:
        column = QFrame()
        column.setObjectName("PreviewMetricColumn")
        column.setMinimumWidth(0)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(column)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        heading_label = QLabel(heading)
        heading_label.setProperty("role", "previewMetricHeading")
        context_label.setProperty("role", "previewMetricContext")
        context_label.setWordWrap(False)
        context_label.setMinimumWidth(0)
        context_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(heading_label)
        text_layout.addWidget(context_label)

        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(6)
        stats_layout.addWidget(self._build_preview_metric_stat("Integrated", integrated_label))
        stats_layout.addWidget(self._build_preview_metric_stat("True Peak", true_peak_label))

        layout.addLayout(text_layout, 1)
        layout.addLayout(stats_layout)
        return column

    def _build_preview_metric_stat(self, title: str, value_label: QLabel) -> QWidget:
        card = QFrame()
        card.setObjectName("PreviewMetricStat")
        card.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        caption_label = QLabel(title)
        caption_label.setProperty("role", "previewMetricCaption")
        value_label.setProperty("role", "previewMetricValue")
        value_label.setMinimumWidth(56)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(caption_label, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(value_label, 0, Qt.AlignmentFlag.AlignRight)
        return card

    def _build_channel_meter(self, channel_name: str, meter_bar: QProgressBar, peak_label: QLabel, rms_label: QLabel) -> QWidget:
        container = QFrame()
        container.setObjectName("ChannelMeter")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 10)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(channel_name)
        title_label.setProperty("role", "meterTitle")
        peak_label.setProperty("role", "meterInlineValue")
        rms_label.setProperty("role", "meterUnit")
        top_row.addWidget(title_label)
        top_row.addStretch(1)
        top_row.addWidget(QLabel("Peak"))
        top_row.addWidget(peak_label)
        layout.addLayout(top_row)
        meter_bar.setOrientation(Qt.Orientation.Vertical)
        meter_bar.setRange(0, 100)
        meter_bar.setTextVisible(False)
        meter_bar.setFixedHeight(180)
        layout.addWidget(meter_bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.addWidget(QLabel("RMS"))
        bottom_row.addWidget(rms_label)
        bottom_row.addStretch(1)
        layout.addLayout(bottom_row)
        return container

    def _build_loudness_monitor_view(self) -> QWidget:
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.setContentsMargins(0, 0, 0, 0)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.addWidget(self.hold_peaks_check)
        controls_row.addWidget(self.clear_meter_button)
        controls_row.addStretch(1)
        layout.addLayout(controls_row)

        summary_panel = QGroupBox("测量口径")
        summary_layout = QGridLayout(summary_panel)
        summary_layout.addWidget(QLabel("源文件"), 0, 0)
        summary_layout.addWidget(self.audio_meter_summary_source_context_label, 0, 1)
        summary_layout.addWidget(QLabel("Integrated"), 1, 0)
        summary_layout.addWidget(self.audio_meter_summary_source_integrated_value, 1, 1)
        summary_layout.addWidget(QLabel("True Peak"), 2, 0)
        summary_layout.addWidget(self.audio_meter_summary_source_true_peak_value, 2, 1)
        summary_layout.addWidget(QLabel("事件后"), 0, 2)
        summary_layout.addWidget(self.audio_meter_summary_context_label, 0, 3)
        summary_layout.addWidget(QLabel("Integrated"), 1, 2)
        summary_layout.addWidget(self.audio_meter_summary_integrated_value, 1, 3)
        summary_layout.addWidget(QLabel("True Peak"), 2, 2)
        summary_layout.addWidget(self.audio_meter_summary_true_peak_value, 2, 3)
        layout.addWidget(summary_panel)

        loudness_content = QWidget()
        loudness_content_layout = QGridLayout(loudness_content)
        loudness_content_layout.addWidget(self._build_meter_stat_card("Momentary", self.audio_meter_momentary_value, "LUFS"), 0, 0)
        loudness_content_layout.addWidget(self._build_meter_stat_card("Momentary Max", self.audio_meter_momentary_max_value, "LUFS"), 0, 1)
        loudness_content_layout.addWidget(self._build_meter_stat_card("Short-term", self.audio_meter_short_term_value, "LUFS"), 0, 2)
        loudness_content_layout.addWidget(self._build_meter_stat_card("Short-term Max", self.audio_meter_short_term_max_value, "LUFS"), 0, 3)
        loudness_content_layout.addWidget(self._build_meter_inline_stat("Integrated", self.audio_meter_integrated_value, "LUFS"), 1, 0)
        loudness_content_layout.addWidget(self._build_meter_inline_stat("LRA", self.audio_meter_lra_value, "LU"), 1, 1)
        loudness_content_layout.addWidget(self._build_meter_inline_stat("True Peak", self.audio_meter_true_peak_value, "dBTP"), 1, 2)
        loudness_content_layout.addWidget(self.audio_meter_context_label, 1, 3)

        levels_content = QWidget()
        levels_content_layout = QHBoxLayout(levels_content)
        levels_content_layout.setContentsMargins(0, 0, 0, 0)
        levels_content_layout.addWidget(self._build_channel_meter("L", self.audio_meter_left_bar, self.audio_meter_left_peak_value, self.audio_meter_left_rms_value))
        levels_content_layout.addWidget(self._build_channel_meter("R", self.audio_meter_right_bar, self.audio_meter_right_peak_value, self.audio_meter_right_rms_value))

        self.loudness_section = self._build_collapsible_section("响度", loudness_content, default_expanded=True)
        self.levels_section = self._build_collapsible_section("电平", levels_content, default_expanded=True)
        traces_content = QWidget()
        traces_layout = QVBoxLayout(traces_content)
        traces_layout.setContentsMargins(0, 0, 0, 0)
        traces_layout.addWidget(self.momentary_plot)
        traces_layout.addWidget(self.short_term_plot)
        self.traces_section = self._build_collapsible_section("时间轨迹", traces_content, default_expanded=True)
        layout.addWidget(self.loudness_section)
        layout.addWidget(self.levels_section)
        layout.addWidget(self.traces_section)
        layout.addStretch(1)
        return view

    def _build_collapsible_section(self, title: str, content: QWidget, default_expanded: bool = True) -> QFrame:
        section = QFrame()
        section.setObjectName("CollapsibleSection")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        header_button = QToolButton()
        header_button.setCheckable(True)
        header_button.setChecked(default_expanded)
        header_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header_button.setArrowType(Qt.ArrowType.DownArrow if default_expanded else Qt.ArrowType.RightArrow)
        header_button.setText(title)
        header_button.setProperty("role", "collapsibleHeader")
        content.setVisible(default_expanded)

        def _toggle(expanded: bool) -> None:
            header_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            content.setVisible(expanded)

        header_button.toggled.connect(_toggle)
        layout.addWidget(header_button)
        layout.addWidget(content)
        return section

    def _set_clip_rows(self, event: EventModel) -> None:
        self.clip_table.begin_loading()
        self.clip_table.setRowCount(len(event.clips))
        for row, clip in enumerate(event.clips):
            self.clip_table.setItem(row, 0, QTableWidgetItem(clip.id))
            self.clip_table.setItem(row, 1, QTableWidgetItem(clip.source_path))
            self.clip_table.setItem(row, 2, QTableWidgetItem(clip.asset_key))
            self.clip_table.setItem(row, 3, QTableWidgetItem(str(clip.weight)))
            self.clip_table.setItem(row, 4, QTableWidgetItem(str(clip.trim_start_ms)))
            self.clip_table.setItem(row, 5, QTableWidgetItem(str(clip.trim_end_ms)))
            self.clip_table.setItem(row, 6, QTableWidgetItem(str(clip.loop_start_ms)))
            self.clip_table.setItem(row, 7, QTableWidgetItem(str(clip.loop_end_ms)))
            self.clip_table.setItem(row, 8, QTableWidgetItem(", ".join(getattr(clip, "tags", []))))
            row_state = "success"
            if not clip.source_path.strip() or not clip.asset_key.strip():
                row_state = "error"
            elif not getattr(clip, "tags", []):
                row_state = "warning"
            row_palette = {
                "error": (QColor("#ffd8d8"), QColor("#3d2326")),
                "warning": (QColor("#ffe7bc"), QColor("#40341e")),
                "success": (QColor("#d7f4e3"), QColor("#20342b")),
            }
            row_foreground, row_background = row_palette[row_state]
            for column in range(9):
                item = self.clip_table.item(row, column)
                if item is None:
                    continue
                flags = item.flags()
                item.setForeground(QBrush(row_foreground))
                if column == 0:
                    item.setBackground(QBrush(row_background))
                if column == 0:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
        self.clip_table.end_loading()
        self.remove_clips_button.setEnabled(bool(event.clips))
        self.bulk_weight_button.setEnabled(bool(event.clips))
        self.batch_rename_button.setEnabled(bool(event.clips))

    def append_log(self, message: str) -> None:
        self.log_output.appendPlainText(message)
        self._latest_log_message = message.strip()
        self.report_detail_label.setText(f"最近日志：{message[:80]}")
        self.report_detail_label.setToolTip(message)
        self._update_workspace_summary_labels()
        self.logAppended.emit(message)

    def show_validation_summary(self, issues: list[ValidationIssue]) -> None:
        if not issues:
            self.report_detail_label.setText("校验通过，没有发现问题。")
            return

        error_count = sum(1 for issue in issues if issue.severity == "Error")
        warning_count = sum(1 for issue in issues if issue.severity == "Warning")
        self.report_detail_label.setText(f"校验完成：错误 {error_count}，警告 {warning_count}。")

    def ask_open_project_path(self) -> str:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 AudioForge 工程",
            "",
            f"AudioForge 工程 (*{PROJECT_EXTENSION})",
        )
        return file_path

    def ask_save_project_path(self, suggested_name: str) -> str:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 AudioForge 工程",
            suggested_name,
            f"AudioForge 工程 (*{PROJECT_EXTENSION})",
        )
        return file_path

    def ask_export_root_path(self, initial_path: str) -> str:
        return QFileDialog.getExistingDirectory(self, "选择导出目录", initial_path or "")

    def set_project_title(self, project_name: str, file_path: str | None) -> None:
        suffix = file_path if file_path else "未保存"
        self.project_title_label.setText(project_name)
        self.project_path_label.setText(suffix)
        self.welcome_project_title_label.setText(project_name)
        self.welcome_project_path_label.setText(suffix)
        self.shell_project_title_label.setText(project_name)
        self.shell_project_path_label.setText(suffix)
        self.setWindowTitle(f"{APP_NAME} - {project_name} [{suffix}]")
        self._update_workspace_summary_labels()

    def ui_preferences(self) -> dict[str, object]:
        return {
            "ui_scale": self._ui_scale,
            "workspace_splitter_sizes": self.workspace_splitter.sizes(),
            "main_splitter_sizes": self._effective_main_splitter_sizes(),
            "explorer_tab": self.explorer_tabs.currentIndex(),
            "active_editor_tab": self._editor_tab_index,
            "inspector_splitter_sizes": None,
            "content_top_splitter_sizes": self.content_top_splitter.sizes(),
            "active_contents_tab": self.contents_tabs.currentIndex(),
            "workspace_mode": self._active_workspace_mode,
            "property_tab": self._property_tab_index,
            "events_workspace_tab": self.events_workspace_tabs.currentIndex(),
            "gamesync_workspace_tab": self.gamesync_workspace_tabs.currentIndex(),
            "contents_tab": self.contents_tabs.currentIndex(),
            "report_tab": self._active_report_index,
            "explorer_detached": self._explorer_detached,
            "window_geometry": self._encode_window_geometry(self),
            "explorer_window_geometry": self._encode_window_geometry(self.explorer_window),
            "settings_dialog_geometry": self._encode_window_geometry(self.settings_dialog),
            "named_splitter_sizes": self._named_splitter_sizes(),
            "event_import_template": self.current_event_import_template_defaults(),
        }

    def apply_ui_preferences(self, preferences: dict[str, object]) -> None:
        ui_scale = float(preferences.get("ui_scale", 1.0) or 1.0)
        self.set_ui_scale(ui_scale)

        explorer_detached = bool(preferences.get("explorer_detached", False))
        if explorer_detached and not self._explorer_detached:
            self.detach_explorer_panel()
        elif not explorer_detached and self._explorer_detached:
            self.attach_explorer_panel()

        self._restore_window_geometry(self, preferences.get("window_geometry"))
        self._restore_window_geometry(self.explorer_window, preferences.get("explorer_window_geometry"))
        self._restore_window_geometry(self.settings_dialog, preferences.get("settings_dialog_geometry"))

        event_import_template = preferences.get("event_import_template")
        if isinstance(event_import_template, dict):
            self._event_import_template_defaults = {
                "bus_name": str(event_import_template.get("bus_name", "")),
                "asset_prefix": str(event_import_template.get("asset_prefix", "")),
                "tags": [str(tag) for tag in event_import_template.get("tags", [])],
            }

        navigation_state = {
            "workspace_mode": preferences.get("workspace_mode", self._active_workspace_mode),
            "explorer_tab": preferences.get("explorer_tab", self.explorer_tabs.currentIndex()),
            "editor_tab": preferences.get("active_editor_tab", self._editor_tab_index),
            "property_tab": preferences.get("property_tab", self._property_tab_index),
            "events_workspace_tab": preferences.get("events_workspace_tab", self.events_workspace_tabs.currentIndex()),
            "gamesync_workspace_tab": preferences.get("gamesync_workspace_tab", self.gamesync_workspace_tabs.currentIndex()),
            "contents_tab": preferences.get("contents_tab", preferences.get("active_contents_tab", self.contents_tabs.currentIndex())),
            "report_tab": preferences.get("report_tab", self._active_report_index),
            "workspace_splitter_sizes": preferences.get("workspace_splitter_sizes"),
            "main_splitter_sizes": preferences.get("main_splitter_sizes"),
            "content_top_splitter_sizes": preferences.get("content_top_splitter_sizes"),
        }
        self.apply_navigation_state(navigation_state)

        named_splitter_sizes = preferences.get("named_splitter_sizes")
        if not isinstance(named_splitter_sizes, dict):
            named_splitter_sizes = {}
        if "WorkspaceSplitter" not in named_splitter_sizes and isinstance(preferences.get("workspace_splitter_sizes"), list):
            named_splitter_sizes["WorkspaceSplitter"] = [int(value) for value in preferences["workspace_splitter_sizes"]]
        if "MainSplitter" not in named_splitter_sizes and isinstance(preferences.get("main_splitter_sizes"), list):
            named_splitter_sizes["MainSplitter"] = [int(value) for value in preferences["main_splitter_sizes"]]
        if "ContentTopSplitter" not in named_splitter_sizes and isinstance(preferences.get("content_top_splitter_sizes"), list):
            named_splitter_sizes["ContentTopSplitter"] = [int(value) for value in preferences["content_top_splitter_sizes"]]
        self._set_named_splitter_sizes(named_splitter_sizes)
        self._sync_event_import_template_controls()

    def set_dirty_state(self, is_dirty: bool) -> None:
        text = "未保存更改" if is_dirty else "已保存"
        self.dirty_status_label.setText(text)
        self.welcome_dirty_label.setText(text)
        self.toolbar_dirty_label.setText(text)
        self.workspace_dirty_label.setText(text)
        self.activity_dirty_label.setText(text)
        self._update_object_bus_status()

    def set_recent_projects(self, project_paths: list[str]) -> None:
        self.recent_projects_combo.blockSignals(True)
        self.recent_projects_combo.clear()
        self.recent_projects_combo.addItems(project_paths)
        self.recent_projects_combo.blockSignals(False)
        self.recent_projects_list.clear()
        self.recent_projects_list.addItems(project_paths)

    def set_project_settings(self, settings: ProjectSettings) -> None:
        self._loading_event = True
        current_project_bus = self.current_project_bus_name() or settings.default_bus
        self._set_project_bus_configs(settings.bus_configs, selected_bus_name=current_project_bus)
        self.set_bus_options(settings.buses)
        self.default_bus_combo.setCurrentText(settings.default_bus)
        self.auto_assign_bus_by_name_check.setChecked(bool(settings.auto_assign_bus_by_name))
        self.export_root_edit.setText(settings.export_root)
        self.source_audio_format_combo.setCurrentText(settings.source_audio_format)
        self.runtime_audio_format_combo.setCurrentText(settings.runtime_audio_format)
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {settings.default_bus}")
        self._sync_event_import_template_controls(settings.buses)
        self._load_selected_project_bus_details()
        self._loading_event = False

    def _current_event_bus_name(self) -> str:
        current_data = self.bus_combo.currentData()
        if current_data is None:
            return self.bus_combo.currentText().strip()
        return str(current_data).strip()

    def _current_play_mode(self) -> str:
        current_data = self.play_mode_combo.currentData()
        if current_data is None:
            return self.play_mode_combo.currentText().strip()
        return str(current_data).strip()

    def _set_play_mode(self, play_mode: str) -> None:
        target_value = str(play_mode).strip()
        target_index = self.play_mode_combo.findData(target_value)
        if target_index < 0:
            target_index = self.play_mode_combo.findText(target_value)
        if target_index >= 0:
            self.play_mode_combo.setCurrentIndex(target_index)

    def _play_mode_label(self, play_mode: str) -> str:
        return {"OneShot": "单次播放"}.get(str(play_mode).strip(), str(play_mode).strip())

    def _bus_visual_label(self, bus_name: str, *, include_depth: bool) -> str:
        depth = self._project_bus_depth(bus_name)
        prefix = ""
        if include_depth:
            prefix = "    " * max(depth - 1, 0)
            if depth > 1:
                prefix += "+ "
        badges: list[str] = []
        if self.default_bus_combo.currentText() == bus_name:
            badges.append("Default")
        if str(self._project_master_bus_config().get("name", "Master")) == bus_name:
            badges.append("Master")
        badge_text = f" [{' / '.join(badges)}]" if badges else ""
        return f"{prefix}{bus_name}{badge_text}"

    def set_bus_options(self, buses: list[str]) -> None:
        current_event_bus = self._current_event_bus_name()
        current_default_bus = self.default_bus_combo.currentText()
        self.bus_combo.blockSignals(True)
        self.default_bus_combo.blockSignals(True)
        self.bus_combo.clear()
        self.default_bus_combo.clear()
        ordered_buses = [str(config["name"]) for config in self._project_bus_child_configs()] or list(buses)
        for bus_name in ordered_buses:
            self.bus_combo.addItem(self._bus_visual_label(bus_name, include_depth=True), bus_name)
        self.default_bus_combo.addItems(buses)
        current_index = self.bus_combo.findData(current_event_bus)
        if current_index >= 0:
            self.bus_combo.setCurrentIndex(current_index)
        elif ordered_buses:
            self.bus_combo.setCurrentIndex(0)
        if current_default_bus in buses:
            self.default_bus_combo.setCurrentText(current_default_bus)
        elif buses:
            self.default_bus_combo.setCurrentText(buses[0])
        self.bus_combo.blockSignals(False)
        self.default_bus_combo.blockSignals(False)

    def current_project_settings_form_data(self) -> dict[str, object]:
        self._sync_project_master_editor_to_state()
        self._sync_project_bus_editor_to_state()
        bus_configs = [
            {
                "name": str(config["name"]),
                "original_name": str(config.get("original_name", config["name"])),
                "parent_bus": str(config.get("parent_bus", "Master")),
                "volume_db": float(config["volume_db"]),
                "is_muted": bool(config["is_muted"]),
                "rtpc_bindings": [dict(binding) for binding in config.get("rtpc_bindings", [])],
                "state_overrides": [dict(override) for override in config.get("state_overrides", [])],
            }
            for config in self._project_bus_configs
        ]
        buses = [config["name"] for config in bus_configs if config["name"] != "Master"]
        return {
            "default_bus": self.default_bus_combo.currentText(),
            "auto_assign_bus_by_name": self.auto_assign_bus_by_name_check.isChecked(),
            "export_root": self.export_root_edit.text().strip() or "./Export",
            "buses": buses or list(DEFAULT_BUSES),
            "bus_configs": bus_configs,
            "source_audio_format": self.source_audio_format_combo.currentText(),
            "runtime_audio_format": self.runtime_audio_format_combo.currentText(),
        }

    def current_project_bus_name(self) -> str:
        item = self.project_bus_list.currentItem()
        if item is None:
            return "Master" if self._active_project_bus_name == "Master" else ""
        return str(item.data(0, Qt.ItemDataRole.UserRole) or "")

    def _project_master_bus_config(self) -> dict[str, object]:
        for config in self._project_bus_configs:
            if str(config["name"]) == "Master":
                return config
        master_config = {
            "name": "Master",
            "original_name": "Master",
            "parent_bus": "Master",
            "volume_db": 0.0,
            "is_muted": False,
            "rtpc_bindings": [],
            "state_overrides": [],
        }
        self._project_bus_configs.insert(0, master_config)
        return master_config

    def _project_bus_child_configs(self) -> list[dict[str, object]]:
        return [config for config in self._project_bus_configs if str(config["name"]) != "Master"]

    def _project_bus_depth(self, bus_name: str, visited: set[str] | None = None) -> int:
        config_map = {str(config["name"]): config for config in self._project_bus_child_configs()}
        depth = 0
        current_name = bus_name
        seen = set(visited or set())
        while current_name in config_map:
            parent_name = str(config_map[current_name].get("parent_bus", "Master"))
            if parent_name == "Master":
                return depth + 1
            if parent_name in seen:
                return depth
            seen.add(parent_name)
            current_name = parent_name
            depth += 1
        return depth

    def _display_project_bus_label(self, bus_name: str) -> str:
        return self._bus_visual_label(bus_name, include_depth=False)

    def _rebuild_project_bus_route_bar(
        self,
        route_names: list[str],
        *,
        child_names: list[str] | None = None,
        effective_linear: float | None = None,
    ) -> None:
        layout = self.project_bus_route_bar.layout()
        if layout is None:
            return
        self._clear_layout_items(layout)
        if not route_names:
            placeholder = QLabel("未选择 Bus")
            placeholder.setProperty("role", "meterContext")
            layout.addWidget(placeholder)
            return
        route_row = QHBoxLayout()
        route_row.setContentsMargins(0, 0, 0, 0)
        route_row.setSpacing(6)
        current_bus = route_names[0]
        for index, route_name in enumerate(route_names):
            if route_name == current_bus:
                tone = "current"
                subtitle = "当前"
            elif route_name == "Master":
                tone = "master"
                subtitle = "主 Bus"
            else:
                tone = "parent"
                subtitle = WWISE_PARENT_BUS_LABEL
            route_row.addWidget(self._build_project_bus_route_node(route_name, tone=tone, subtitle=subtitle))
            if index < len(route_names) - 1:
                separator = QLabel("->")
                separator.setProperty("role", "routeConnector")
                route_row.addWidget(separator)
        if effective_linear is not None:
            output_chip = QLabel(f"{WWISE_EFFECTIVE_OUTPUT_LABEL} {effective_linear * 100:.0f}%")
            output_chip.setProperty("role", "busHeaderChip")
            route_row.addWidget(output_chip)
        route_row.addStretch(1)
        layout.addLayout(route_row)

        branch_row = QHBoxLayout()
        branch_row.setContentsMargins(0, 0, 0, 0)
        branch_row.setSpacing(6)
        branch_label = QLabel(WWISE_CHILD_BUSES_LABEL)
        branch_label.setProperty("role", "meterTitle")
        branch_row.addWidget(branch_label)
        if child_names:
            for child_name in child_names:
                button = QToolButton()
                button.setText(child_name)
                button.setProperty("role", "routeChip")
                button.clicked.connect(lambda _checked=False, name=child_name: self._select_project_bus_by_name(name))
                branch_row.addWidget(button)
        else:
            placeholder = QLabel("无子 Bus")
            placeholder.setProperty("role", "meterContext")
            branch_row.addWidget(placeholder)
        branch_row.addStretch(1)
        layout.addLayout(branch_row)

    def _clear_layout_items(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout_items(child_layout)
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_project_bus_route_node(self, bus_name: str, *, tone: str, subtitle: str) -> QToolButton:
        button = QToolButton()
        button.setText(f"{bus_name}\n{subtitle}")
        button.setProperty("role", "routeNode")
        button.setProperty("routeTone", tone)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAutoRaise(False)
        button.setToolTip(f"切到 Bus：{bus_name}")
        button.clicked.connect(lambda _checked=False, name=bus_name: self._select_project_bus_by_name(name))
        return button

    def _refresh_project_bus_parent_options(self, selected_bus_name: str, current_parent_name: str) -> None:
        self.project_bus_parent_combo.blockSignals(True)
        self.project_bus_parent_combo.clear()
        self.project_bus_parent_combo.addItem("Master")
        for config in self._project_bus_child_configs():
            bus_name = str(config["name"])
            if bus_name.casefold() == selected_bus_name.casefold():
                continue
            self.project_bus_parent_combo.addItem(bus_name)
        target_parent = current_parent_name if self.project_bus_parent_combo.findText(current_parent_name) >= 0 else "Master"
        self.project_bus_parent_combo.setCurrentText(target_parent)
        self.project_bus_parent_combo.blockSignals(False)

    def _project_bus_route_names(self, bus_name: str) -> list[str]:
        route = [bus_name]
        config_map = {str(config["name"]): config for config in self._project_bus_configs}
        current_name = bus_name
        visited: set[str] = set()
        while current_name in config_map:
            parent_name = str(config_map[current_name].get("parent_bus", "Master")) or "Master"
            route.append(parent_name)
            if parent_name == "Master" or parent_name in visited:
                break
            visited.add(parent_name)
            current_name = parent_name
        return route

    def _would_create_project_bus_cycle(self, bus_name: str, parent_bus_name: str) -> bool:
        if parent_bus_name == "Master":
            return False
        return bus_name in self._project_bus_route_names(parent_bus_name)

    def _project_bus_effective_linear(self, bus_name: str) -> float:
        config_map = {str(config["name"]): config for config in self._project_bus_configs}
        current_name = bus_name
        gain = 1.0
        visited: set[str] = set()
        while current_name in config_map:
            config = config_map[current_name]
            if bool(config.get("is_muted", False)):
                return 0.0
            gain *= 10.0 ** (float(config.get("volume_db", 0.0)) / 20.0)
            if current_name == "Master":
                return max(0.0, min(1.0, gain))
            parent_name = str(config.get("parent_bus", "Master")) or "Master"
            if parent_name in visited:
                return 0.0
            visited.add(parent_name)
            current_name = parent_name
        return max(0.0, min(1.0, gain))

    def _refresh_master_bus_summary(self) -> None:
        master_config = self._project_master_bus_config()
        effective_linear = self._project_bus_effective_linear("Master")
        self.project_master_summary_label.setText("Master")
        self.project_master_volume_spin.blockSignals(True)
        self.project_master_mute_check.blockSignals(True)
        self.project_master_volume_spin.setValue(float(master_config.get("volume_db", 0.0)))
        self.project_master_mute_check.setChecked(bool(master_config.get("is_muted", False)))
        self.project_master_volume_spin.blockSignals(False)
        self.project_master_mute_check.blockSignals(False)
        self.project_master_effective_value.setText(f"{effective_linear * 100:.0f}%")
        self.project_master_effective_bar.setValue(int(effective_linear * 100.0))

    def _sync_project_master_editor_to_state(self) -> None:
        master_config = self._project_master_bus_config()
        master_config["volume_db"] = float(self.project_master_volume_spin.value())
        master_config["is_muted"] = bool(self.project_master_mute_check.isChecked())
        self._refresh_master_bus_summary()

    def _make_project_bus_tree_item(self, bus_name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._display_project_bus_label(bus_name)])
        item.setData(0, Qt.ItemDataRole.UserRole, bus_name)
        item.setIcon(0, load_app_icon("bus"))
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        return item

    def _rebuild_project_bus_tree(self, selected_bus_name: str | None = None) -> None:
        child_configs = self._project_bus_child_configs()
        child_names = {str(config["name"]) for config in child_configs}
        children_by_parent: dict[str, list[dict[str, object]]] = {"Master": []}
        for config in child_configs:
            parent_name = str(config.get("parent_bus", "Master") or "Master")
            if parent_name not in child_names:
                parent_name = "Master"
                config["parent_bus"] = "Master"
            children_by_parent.setdefault(parent_name, []).append(config)

        self.project_bus_list.blockSignals(True)
        self.project_bus_list.clear()

        def add_children(parent_name: str, parent_item: QTreeWidgetItem | None) -> None:
            for config in children_by_parent.get(parent_name, []):
                item = self._make_project_bus_tree_item(str(config["name"]))
                if parent_item is None:
                    self.project_bus_list.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                add_children(str(config["name"]), item)

        add_children("Master", None)
        self.project_bus_list.expandAll()
        target_name = selected_bus_name or self.default_bus_combo.currentText()
        if target_name:
            pending = [self.project_bus_list.topLevelItem(index) for index in range(self.project_bus_list.topLevelItemCount())]
            while pending:
                item = pending.pop(0)
                if str(item.data(0, Qt.ItemDataRole.UserRole) or "") == target_name:
                    self.project_bus_list.setCurrentItem(item)
                    break
                for index in range(item.childCount()):
                    pending.append(item.child(index))
        self.project_bus_list.blockSignals(False)

    def _sync_project_bus_tree_to_state(self) -> None:
        config_map = {str(config["name"]): config for config in self._project_bus_child_configs()}
        ordered_names: list[str] = []

        def walk(parent_item: QTreeWidgetItem | None, parent_name: str) -> None:
            if parent_item is None:
                items = [self.project_bus_list.topLevelItem(index) for index in range(self.project_bus_list.topLevelItemCount())]
            else:
                items = [parent_item.child(index) for index in range(parent_item.childCount())]
            for item in items:
                bus_name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                if bus_name not in config_map:
                    continue
                config_map[bus_name]["parent_bus"] = parent_name
                ordered_names.append(bus_name)
                walk(item, bus_name)

        walk(None, "Master")
        master_config = self._project_master_bus_config()
        self._project_bus_configs = [master_config] + [config_map[name] for name in ordered_names if name in config_map]

    def _set_project_bus_configs(self, bus_configs: list[BusConfig], selected_bus_name: str | None = None) -> None:
        normalized_master = {
            "name": "Master",
            "original_name": "Master",
            "parent_bus": "Master",
            "volume_db": 0.0,
            "is_muted": False,
            "rtpc_bindings": [],
            "state_overrides": [],
        }
        normalized_children: list[dict[str, object]] = []
        seen: set[str] = set()
        existing_original_names = {
            str(config["name"]): str(config.get("original_name", config["name"]))
            for config in self._project_bus_configs
        }
        for config in bus_configs:
            bus_name = str(config.name).strip()
            if not bus_name:
                continue
            key = bus_name.casefold()
            if key in seen:
                continue
            if key == "master":
                normalized_master = {
                    "name": "Master",
                    "original_name": "Master",
                    "parent_bus": "Master",
                    "volume_db": float(config.volume_db),
                    "is_muted": bool(config.is_muted),
                    "rtpc_bindings": [self._rtpc_binding_payload(binding) for binding in getattr(config, "rtpc_bindings", [])],
                    "state_overrides": [self._state_override_payload(override) for override in getattr(config, "state_overrides", [])],
                }
                seen.add(key)
                continue
            normalized_children.append(
                {
                    "name": bus_name,
                    "original_name": existing_original_names.get(bus_name, bus_name),
                    "parent_bus": str(getattr(config, "parent_bus", "Master") or "Master"),
                    "volume_db": float(config.volume_db),
                    "is_muted": bool(config.is_muted),
                    "rtpc_bindings": [self._rtpc_binding_payload(binding) for binding in getattr(config, "rtpc_bindings", [])],
                    "state_overrides": [self._state_override_payload(override) for override in getattr(config, "state_overrides", [])],
                }
            )
            seen.add(key)
        if not normalized_children:
            normalized_children = [
                {
                    "name": bus_name,
                    "original_name": bus_name,
                    "parent_bus": "Master",
                    "volume_db": 0.0,
                    "is_muted": False,
                    "rtpc_bindings": [],
                    "state_overrides": [],
                }
                for bus_name in DEFAULT_BUSES
            ]
        self._project_bus_configs = [normalized_master, *normalized_children]
        self._rebuild_project_bus_tree(selected_bus_name=selected_bus_name)
        self.project_bus_count_label.setText(f"Bus {len(self._project_bus_configs) - 1} 条")
        self._refresh_master_bus_summary()

    def _selected_project_bus_index(self) -> int:
        selected_name = self.current_project_bus_name()
        return self._project_bus_index_by_name(selected_name)

    def _project_bus_index_by_name(self, bus_name: str) -> int:
        if not bus_name:
            return -1
        for index, config in enumerate(self._project_bus_configs):
            if str(config["name"]) == bus_name:
                return index
        return -1

    def _load_selected_project_bus_details(self) -> None:
        self._loading_project_bus_details = True
        try:
            row = self._selected_project_bus_index()
            has_selection = row >= 0
            self.project_bus_name_edit.setEnabled(has_selection)
            self.project_bus_parent_combo.setEnabled(has_selection)
            self.project_bus_volume_spin.setEnabled(has_selection)
            self.project_bus_mute_check.setEnabled(has_selection)
            self.project_bus_remove_button.setEnabled(len(self._project_bus_configs) > 2 and has_selection)
            self.inline_bus_set_default_button.setEnabled(has_selection)
            self.inline_bus_to_master_button.setEnabled(has_selection)
            self.inline_bus_open_parent_button.setEnabled(has_selection)
            if not has_selection:
                if self._active_project_bus_name == "Master":
                    child_names = [str(item["name"]) for item in self._project_bus_child_configs() if str(item.get("parent_bus", "Master")) == "Master"]
                    effective_linear = self._project_bus_effective_linear("Master")
                    self.project_bus_name_edit.clear()
                    self.project_bus_parent_combo.clear()
                    self.project_bus_volume_spin.setValue(0.0)
                    self.project_bus_mute_check.setChecked(False)
                    self.project_bus_export_label.setText("主 Bus，已写入 BusConfigs；Unity 初始化会恢复主 Bus 的音量与静音。")
                    self.project_bus_route_label.setText("Master")
                    self._rebuild_project_bus_route_bar(["Master"], child_names=child_names, effective_linear=effective_linear)
                    self.project_bus_children_label.setText(f"{WWISE_CHILD_BUSES_LABEL}: " + (", ".join(child_names) if child_names else "-"))
                    self.project_bus_effective_value.setText(f"{effective_linear * 100:.0f}%")
                    self.project_bus_effective_bar.setValue(int(effective_linear * 100.0))
                    self.inline_bus_group.setTitle(f"{WWISE_PROPERTY_EDITOR_TITLE}: {WWISE_MASTER_AUDIO_BUS_TITLE}")
                    self.inline_bus_set_default_button.setEnabled(False)
                    self.inline_bus_to_master_button.setEnabled(False)
                    self.inline_bus_open_parent_button.setEnabled(False)
                    self.project_bus_summary_label.setText("当前查看主 Bus；详细音量与静音可直接在右侧主 Bus 编辑区调整。")
                    self.inline_bus_name_chip.setText("Bus Master")
                    self.inline_bus_parent_chip.setText(f"{WWISE_PARENT_BUS_LABEL} -")
                    self.inline_bus_default_chip.setText(f"{WWISE_DEFAULT_BUS_LABEL} -")
                    self.inline_bus_export_chip.setText("导出 BusConfigs")
                    self._load_bus_binding_editors(self._project_master_bus_config())
                    return
                self._active_project_bus_name = ""
                self.project_bus_name_edit.clear()
                self.project_bus_parent_combo.clear()
                self.project_bus_volume_spin.setValue(0.0)
                self.project_bus_mute_check.setChecked(False)
                self.project_bus_export_label.setText("未选择 Bus")
                self.project_bus_route_label.setText("未选择 Bus")
                self._rebuild_project_bus_route_bar([])
                self.project_bus_children_label.setText(f"{WWISE_CHILD_BUSES_LABEL}: -")
                self.project_bus_effective_value.setText("0%")
                self.project_bus_effective_bar.setValue(0)
                self.inline_bus_group.setTitle(WWISE_PROPERTY_EDITOR_TITLE)
                self.inline_bus_set_default_button.setEnabled(False)
                self.inline_bus_to_master_button.setEnabled(False)
                self.inline_bus_open_parent_button.setEnabled(False)
                self.project_bus_summary_label.setText("在左侧选择 Bus 后，可在属性编辑器中直接编辑当前 Bus。")
                self.inline_bus_name_chip.setText("Bus -")
                self.inline_bus_parent_chip.setText(f"{WWISE_PARENT_BUS_LABEL} -")
                self.inline_bus_default_chip.setText(f"{WWISE_DEFAULT_BUS_LABEL} -")
                self.inline_bus_export_chip.setText("导出 -")
                self._load_bus_binding_editors(None)
                return
            config = self._project_bus_configs[row]
            bus_name = str(config["name"])
            self._active_project_bus_name = bus_name
            self.project_bus_name_edit.setText(bus_name)
            self._refresh_project_bus_parent_options(bus_name, str(config.get("parent_bus", "Master")))
            self.project_bus_volume_spin.setValue(float(config["volume_db"]))
            self.project_bus_mute_check.setChecked(bool(config["is_muted"]))
            role_text = WWISE_DEFAULT_BUS_LABEL if self.default_bus_combo.currentText() == bus_name else "普通 Bus"
            route_text = " -> ".join(self._project_bus_route_names(bus_name))
            child_names = [str(item["name"]) for item in self._project_bus_child_configs() if str(item.get("parent_bus", "Master")) == bus_name]
            effective_linear = self._project_bus_effective_linear(bus_name)
            self.project_bus_route_label.setText(route_text)
            self._rebuild_project_bus_route_bar(
                self._project_bus_route_names(bus_name),
                child_names=child_names,
                effective_linear=effective_linear,
            )
            self.project_bus_children_label.setText(f"{WWISE_CHILD_BUSES_LABEL}: " + (", ".join(child_names) if child_names else "-"))
            self.project_bus_effective_value.setText(f"{effective_linear * 100:.0f}%")
            self.project_bus_effective_bar.setValue(int(effective_linear * 100.0))
            self.project_bus_export_label.setText(f"{role_text}，已写入 BusConfigs；Unity 初始化会按该路由恢复音量与静音。")
            self.inline_bus_group.setTitle(f"{WWISE_PROPERTY_EDITOR_TITLE}: {bus_name}")
            self.inline_bus_set_default_button.setEnabled(self.default_bus_combo.currentText() != bus_name)
            parent_bus_name = str(config.get("parent_bus", "Master") or "Master")
            self.inline_bus_open_parent_button.setEnabled(parent_bus_name != "Master")
            self.inline_bus_name_chip.setText(f"Bus {bus_name}")
            self.inline_bus_parent_chip.setText(f"{WWISE_PARENT_BUS_LABEL} {parent_bus_name}")
            self.inline_bus_default_chip.setText(f"{WWISE_DEFAULT_BUS_LABEL} 是" if self.default_bus_combo.currentText() == bus_name else f"{WWISE_DEFAULT_BUS_LABEL} 否")
            self.inline_bus_export_chip.setText("导出 BusConfigs")
            self._load_bus_binding_editors(config)
            self.project_bus_summary_label.setText(
                f"当前选中：{bus_name}\n{WWISE_ROUTING_LABEL}: {route_text}\n{WWISE_CHILD_BUSES_LABEL}: {', '.join(child_names) if child_names else '无'}\n常用编辑已整合到属性编辑器。"
            )
        finally:
            self._loading_project_bus_details = False

    def _sync_project_bus_editor_to_state(
        self,
        show_errors: bool = True,
        bus_name: str | None = None,
        selected_bus_name: str | None = None,
    ) -> bool:
        target_bus_name = bus_name or self.current_project_bus_name()
        if target_bus_name == "Master":
            return True
        row = self._project_bus_index_by_name(target_bus_name)
        if row < 0:
            return True
        current_config = self._project_bus_configs[row]
        current_name = str(current_config["name"])
        new_name = self.project_bus_name_edit.text().strip() or current_name
        new_parent_bus = self.project_bus_parent_combo.currentText().strip() or "Master"
        duplicate_names = {
            str(config["name"]).casefold()
            for index, config in enumerate(self._project_bus_configs)
            if index != row
        }
        if new_name.casefold() in duplicate_names:
            self.project_bus_name_edit.blockSignals(True)
            self.project_bus_name_edit.setText(current_name)
            self.project_bus_name_edit.blockSignals(False)
            if show_errors:
                QMessageBox.warning(self, "Bus 名称重复", f"Bus“{new_name}”已存在，请换一个名称。")
            return False
        if new_parent_bus.casefold() == new_name.casefold():
            self.project_bus_parent_combo.blockSignals(True)
            self.project_bus_parent_combo.setCurrentText("Master")
            self.project_bus_parent_combo.blockSignals(False)
            if show_errors:
                QMessageBox.warning(self, "父 Bus 非法", "Bus 不能把自己作为父 Bus。")
            return False
        if self._would_create_project_bus_cycle(new_name, new_parent_bus):
            self.project_bus_parent_combo.blockSignals(True)
            self.project_bus_parent_combo.setCurrentText("Master")
            self.project_bus_parent_combo.blockSignals(False)
            if show_errors:
                QMessageBox.warning(self, "父 Bus 非法", "当前选择会形成路由环，请改为 Master 或其他父 Bus。")
            return False
        current_config["name"] = new_name
        current_config["parent_bus"] = new_parent_bus
        current_config["volume_db"] = float(self.project_bus_volume_spin.value())
        current_config["is_muted"] = bool(self.project_bus_mute_check.isChecked())
        self._sync_bus_binding_editor_to_state(current_config)
        current_default_bus = self.default_bus_combo.currentText()
        if current_default_bus.casefold() == current_name.casefold() and current_default_bus != new_name:
            current_default_bus = new_name
        for config in self._project_bus_configs:
            if str(config.get("parent_bus", "Master")).casefold() == current_name.casefold() and config is not current_config:
                config["parent_bus"] = new_name
        self.set_bus_options([str(config["name"]) for config in self._project_bus_child_configs()])
        self.default_bus_combo.setCurrentText(current_default_bus)
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {self.default_bus_combo.currentText() or '-'}")
        self.project_bus_count_label.setText(f"Bus {len(self._project_bus_configs) - 1} 条")
        self._set_project_bus_configs(
            [
                BusConfig(
                    name=str(config["name"]),
                    parent_bus=str(config.get("parent_bus", "Master")),
                    volume_db=float(config["volume_db"]),
                    is_muted=bool(config["is_muted"]),
                    rtpc_bindings=[RtpcBindingModel(**binding) for binding in config.get("rtpc_bindings", [])],
                    state_overrides=[StateOverrideModel(**override) for override in config.get("state_overrides", [])],
                )
                for config in self._project_bus_configs
            ],
            selected_bus_name=selected_bus_name or new_name,
        )
        self.default_bus_combo.setCurrentText(current_default_bus)
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {self.default_bus_combo.currentText() or '-'}")
        self._load_selected_project_bus_details()
        return True

    def _handle_project_bus_selection_changed(self) -> None:
        previous_bus_name = self._active_project_bus_name
        current_bus_name = self.current_project_bus_name()
        if previous_bus_name and previous_bus_name != current_bus_name:
            if not self._sync_project_bus_editor_to_state(
                show_errors=True,
                bus_name=previous_bus_name,
                selected_bus_name=current_bus_name or previous_bus_name,
            ):
                self._select_project_bus_by_name(previous_bus_name)
                return
            if not self._loading_event:
                self._queue_project_settings_changed("project-bus-selection")
        if not self._loading_event and not self._syncing_project_bus_selection:
            self._project_bus_selection_overridden = True
        self._load_selected_project_bus_details()
        self._update_object_bus_status()

    def _focus_master_bus_view(self) -> bool:
        previous_bus_name = self._active_project_bus_name
        if previous_bus_name and previous_bus_name != "Master":
            if not self._sync_project_bus_editor_to_state(
                show_errors=True,
                bus_name=previous_bus_name,
                selected_bus_name=previous_bus_name,
            ):
                return False
            if not self._loading_event:
                self._queue_project_settings_changed("project-bus-selection")

        self._syncing_project_bus_selection = True
        self.project_bus_list.blockSignals(True)
        try:
            self.project_bus_list.clearSelection()
            self.project_bus_list.setCurrentItem(None)
        finally:
            self.project_bus_list.blockSignals(False)
            self._syncing_project_bus_selection = False

        if not self._loading_event:
            self._project_bus_selection_overridden = True
        self._active_project_bus_name = "Master"
        self._load_selected_project_bus_details()
        self._update_object_bus_status()
        self.project_master_volume_spin.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _select_project_bus_by_name(self, bus_name: str) -> bool:
        if not bus_name:
            return False
        if bus_name == "Master":
            return self._focus_master_bus_view()
        pending = [self.project_bus_list.topLevelItem(index) for index in range(self.project_bus_list.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            if str(item.data(0, Qt.ItemDataRole.UserRole)) == bus_name:
                self.project_bus_list.setCurrentItem(item)
                return True
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        return False

    def _sync_current_event_bus_selection(self, force: bool = False) -> None:
        bus_name = self._current_event_bus_name()
        if not bus_name:
            self.inline_bus_group.setTitle(WWISE_PROPERTY_EDITOR_TITLE)
            return
        if self._project_bus_selection_overridden and not force:
            return
        self._syncing_project_bus_selection = True
        try:
            self._select_project_bus_by_name(bus_name)
        finally:
            self._syncing_project_bus_selection = False

    def _request_add_and_assign_project_bus(self) -> None:
        bus_name = self.ask_new_bus_name().strip()
        if not bus_name:
            return
        existing_names = {str(config["name"]).casefold() for config in self._project_bus_configs}
        if bus_name.casefold() in existing_names:
            QMessageBox.warning(self, "新建 Bus 失败", f"Bus“{bus_name}”已存在。")
            return
        self._project_bus_configs.append(
            {
                "name": bus_name,
                "original_name": bus_name,
                "parent_bus": "Master",
                "volume_db": 0.0,
                "is_muted": False,
            }
        )
        self._set_project_bus_configs(
            [
                BusConfig(
                    name=str(config["name"]),
                    parent_bus=str(config.get("parent_bus", "Master")),
                    volume_db=float(config["volume_db"]),
                    is_muted=bool(config["is_muted"]),
                )
                for config in self._project_bus_configs
            ],
            selected_bus_name=bus_name,
        )
        self.set_bus_options([str(config["name"]) for config in self._project_bus_child_configs()])
        self.bus_combo.setCurrentText(bus_name)
        self._sync_current_event_bus_selection()
        self._emit_project_settings_changed()
        self._emit_event_properties_changed()

    def _set_current_bus_as_default(self) -> None:
        bus_name = self.current_project_bus_name() or self._current_event_bus_name()
        if not bus_name:
            return
        self.default_bus_combo.setCurrentText(bus_name)
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {bus_name}")
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def _route_current_bus_to_master(self) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        self.project_bus_parent_combo.setCurrentText("Master")
        if self._sync_project_bus_editor_to_state(show_errors=True):
            self._emit_project_settings_changed()

    def _select_parent_bus_for_current(self) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        parent_bus_name = str(self._project_bus_configs[row].get("parent_bus", "Master") or "Master")
        if parent_bus_name == "Master":
            QMessageBox.information(self, f"切到 {WWISE_PARENT_BUS_LABEL}", f"当前 Bus 已经直接挂在 {WWISE_MASTER_AUDIO_BUS_TITLE} 下。")
            return
        self._select_project_bus_by_name(parent_bus_name)
        self.set_active_property_category("音频属性")

    def _handle_project_bus_hierarchy_changed(self) -> None:
        self._sync_project_bus_tree_to_state()
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def _request_add_project_bus(self) -> None:
        bus_name = self.ask_new_bus_name().strip()
        if not bus_name:
            return
        existing_names = {str(config["name"]).casefold() for config in self._project_bus_configs}
        if bus_name.casefold() in existing_names:
            QMessageBox.warning(self, "新建 Bus 失败", f"Bus“{bus_name}”已存在。")
            return
        current_parent = self.current_project_bus_name() or "Master"
        self._project_bus_configs.append(
            {
                "name": bus_name,
                "original_name": bus_name,
                "parent_bus": current_parent if current_parent and current_parent != bus_name else "Master",
                "volume_db": 0.0,
                "is_muted": False,
            }
        )
        self._set_project_bus_configs(
            [
                BusConfig(
                    name=str(config["name"]),
                    parent_bus=str(config.get("parent_bus", "Master")),
                    volume_db=float(config["volume_db"]),
                    is_muted=bool(config["is_muted"]),
                )
                for config in self._project_bus_configs
            ],
            selected_bus_name=bus_name,
        )
        self.set_bus_options([str(config["name"]) for config in self._project_bus_child_configs()])
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {self.default_bus_combo.currentText() or '-'}")
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def _request_remove_project_bus(self) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        if str(self._project_bus_configs[row]["name"]) == "Master":
            QMessageBox.information(self, "删除 Bus", f"{WWISE_MASTER_AUDIO_BUS_TITLE} 是固定 Bus，不能删除。")
            return
        if len(self._project_bus_configs) <= 2:
            QMessageBox.information(self, "删除 Bus", "工程至少需要保留一条 Bus。")
            return
        removed_name = str(self._project_bus_configs[row]["name"])
        removed_parent = str(self._project_bus_configs[row].get("parent_bus", "Master"))
        del self._project_bus_configs[row]
        for config in self._project_bus_configs:
            if str(config.get("parent_bus", "Master")).casefold() == removed_name.casefold():
                config["parent_bus"] = removed_parent if removed_parent.casefold() != removed_name.casefold() else "Master"
        selected_bus_name = str(self._project_bus_configs[min(row, len(self._project_bus_configs) - 1)]["name"])
        self._set_project_bus_configs(
            [
                BusConfig(
                    name=str(config["name"]),
                    parent_bus=str(config.get("parent_bus", "Master")),
                    volume_db=float(config["volume_db"]),
                    is_muted=bool(config["is_muted"]),
                )
                for config in self._project_bus_configs
            ],
            selected_bus_name=selected_bus_name,
        )
        self.set_bus_options([str(config["name"]) for config in self._project_bus_child_configs()])
        if self.default_bus_combo.currentText().casefold() == removed_name.casefold():
            self.default_bus_combo.setCurrentText(selected_bus_name)
        self.project_bus_default_label.setText(f"{WWISE_DEFAULT_BUS_LABEL}: {self.default_bus_combo.currentText() or '-'}")
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def current_event_form_data(self) -> dict[str, object]:
        return {
            **self.current_event_identity_form_data(),
            **self.current_audio_form_data(),
        }

    def current_event_identity_form_data(self) -> dict[str, object]:
        return {
            "id": self.event_id_edit.text().strip(),
            "display_name": self.display_name_edit.text().strip(),
            "steal_policy": self.steal_policy_combo.currentText(),
            "cooldown_seconds": self.cooldown_spin.value(),
            "max_instances": self.max_instances_spin.value(),
            "notes": self.notes_edit.toPlainText().strip(),
        }

    def current_audio_form_data(self) -> dict[str, object]:
        self._sync_event_binding_editor_to_state("rtpc")
        self._sync_event_binding_editor_to_state("state")
        self._sync_event_binding_editor_to_state("switch")
        return {
            "bus": self._current_event_bus_name(),
            "play_mode": self._current_play_mode(),
            "load_policy": self.load_policy_combo.currentText(),
            "volume_db": self.volume_spin.value(),
            "volume_rand_min_db": self.volume_rand_min_spin.value(),
            "volume_rand_max_db": self.volume_rand_max_spin.value(),
            "pitch_cents": int(self.pitch_spin.value()),
            "pitch_rand_min_cents": self.pitch_rand_min_spin.value(),
            "pitch_rand_max_cents": self.pitch_rand_max_spin.value(),
            "combo_pitch_step_cents": self.combo_pitch_step_spin.value() * 100,
            "combo_reset_seconds": self.combo_reset_spin.value(),
            "combo_max_step": self.combo_max_step_spin.value(),
            "avoid_immediate_repeat": self.avoid_repeat_check.isChecked(),
            "tags": [tag.strip() for tag in self.tags_summary_edit.text().split(",") if tag.strip()],
            "rtpc_bindings": [dict(binding) for binding in self._event_rtpc_bindings],
            "state_overrides": [dict(override) for override in self._event_state_overrides],
            "switch_variants": [
                {
                    **dict(variant),
                    "clip_ids": list(variant.get("clip_ids", [])),
                }
                for variant in self._event_switch_variants
            ],
        }

    def current_bulk_clip_form_data(self) -> dict[str, object]:
        return {
            "weight": self.bulk_clip_weight_spin.value(),
            "asset_prefix": self.bulk_clip_asset_prefix_edit.text().strip(),
            "tags": [tag.strip() for tag in self.bulk_clip_tags_edit.text().split(",") if tag.strip()],
        }

    def current_clip_sort_request(self) -> tuple[str, bool]:
        field_map = {
            "片段 ID": "id",
            "资源键": "asset_key",
            "权重": "weight",
            "源路径": "source_path",
        }
        return field_map.get(self.sort_field_combo.currentText(), "id"), self.sort_order_combo.currentText() == "升序"

    def selected_clip_ids(self) -> list[str]:
        return self.clip_table.selected_clip_ids()

    def set_validation_report(self, report_text: str, issues: list[ValidationIssue] | None = None) -> None:
        panel_state = self._capture_report_panel_state(self.validation_issue_list, self.validation_report_output)
        self.validation_report_output.setPlainText(report_text)
        issue_items: list[dict[str, object]] = []
        severity_priority = {"Error": 0, "Warning": 1, "Info": 2}
        issues = sorted(issues or [], key=lambda issue: (severity_priority.get(issue.severity, 9), issue.target, issue.code))
        error_count = sum(1 for issue in issues if issue.severity == "Error")
        warning_count = sum(1 for issue in issues if issue.severity == "Warning")
        info_count = sum(1 for issue in issues if issue.severity == "Info")
        if issues:
            severity_label = {"Error": "错误", "Warning": "警告", "Info": "信息"}
            for issue in issues:
                issue_items.append(
                    {
                        "title": f"{severity_label.get(issue.severity, issue.severity)} | {issue.target} | {issue.code}",
                        "detail": f"目标：{issue.target}\n级别：{issue.severity}\n代码：{issue.code}\n\n{issue.message}",
                        "target_type": "auto",
                        "target_id": issue.target,
                        "severity": issue.severity,
                        "code": issue.code,
                    }
                )
            self.validation_summary_label.setText(
                f"校验问题中心：错误 {error_count} | 警告 {warning_count} | 信息 {info_count}。双击列表可跳转到对应对象。"
            )
        else:
            self.validation_summary_label.setText("校验通过，没有发现问题。")
        self._validation_issue_items = issue_items
        self._apply_validation_filters()
        self._restore_report_panel_state(self.validation_issue_list, self.validation_report_output, panel_state)
        self.report_detail_label.setText("校验报告已刷新，可在问题中心快速定位对象。")
        self._update_workspace_summary_labels()
        self.validationReportUpdated.emit(issues)

    def set_build_report(self, report_text: str, highlights: list[dict[str, object]] | None = None) -> None:
        panel_state = self._capture_report_panel_state(self.build_issue_list, self.build_report_output)
        self.build_report_output.setPlainText(report_text)
        self.build_preview_output.setPlainText(report_text)
        highlight_items = highlights or []
        if not highlight_items:
            for line in [line.strip() for line in report_text.splitlines() if line.strip()][:12]:
                highlight_items.append({"title": f"构建摘要 | {line}", "detail": line})
        self._set_report_items(self.build_issue_list, highlight_items)
        self._restore_report_panel_state(self.build_issue_list, self.build_report_output, panel_state)
        if self._build_status_summary_override is None:
            self.build_summary_label.setText("构建问题中心：优先看 Schema、BusConfigs、资源差异与导出数量。")
        if self._build_status_detail_override is None:
            self.report_detail_label.setText("构建报告已刷新，生成预览已同步。")
        self._update_workspace_summary_labels()

    def current_build_scope(self) -> str:
        return str(self.build_scope_combo.currentData() or "incremental")

    def set_build_selection_context(self, summary: str, detail: str) -> None:
        self.build_scope_target_label.setText(summary)
        self.build_scope_hint_label.setText(detail)

    def set_build_plan_summary(self, summary: str, detail: str) -> None:
        self.build_plan_summary_label.setText(summary)
        self.build_plan_detail_label.setText(detail)

    def set_build_status(self, summary: str, detail: str, *, activate_results: bool = False) -> None:
        self._build_status_summary_override = summary
        self._build_status_detail_override = detail
        self.build_summary_label.setText(summary)
        self.build_workspace_status_label.setText(detail)
        self.report_detail_label.setText(detail)
        self.report_detail_label.setToolTip(detail)
        if activate_results:
            self.report_pages.setCurrentIndex(2)
            self._report_tab_index = 2
        self._update_workspace_summary_labels()
        self.buildStatusUpdated.emit(summary, detail)

    def clear_build_status(self) -> None:
        self._build_status_summary_override = None
        self._build_status_detail_override = None
        self._update_workspace_summary_labels()

    def set_loudness_report(self, report_text: str, rows: list[dict[str, object]] | None = None, summary_text: str | None = None) -> None:
        panel_state = self._capture_report_panel_state(self.loudness_issue_list, self.loudness_report_output)
        self.loudness_report_output.setPlainText(report_text)
        row_items: list[dict[str, object]] = []
        for row in rows or []:
            findings = row.get("findings", [])
            row_items.append(
                {
                    "title": f"{'超标' if findings else '通过'} | {row['event_id']} | {row['clip_id']} | TP {row['true_peak_db']:.1f} dBTP",
                    "detail": (
                        f"事件：{row['event_id']}\n片段：{row['clip_id']}\n资源：{row['asset_key']}\n"
                        f"Integrated：{row['integrated_lufs']:.1f} LUFS\nMomentary Max：{row['momentary_max_lufs']:.1f} LUFS\n"
                        f"True Peak：{row['true_peak_db']:.1f} dBTP\n\n说明：{'; '.join(findings) if findings else '未发现超标项'}"
                    ),
                    "target_type": "event",
                    "target_id": row["event_id"],
                }
            )
        self._set_report_items(self.loudness_issue_list, row_items)
        self._restore_report_panel_state(self.loudness_issue_list, self.loudness_report_output, panel_state)
        self.loudness_summary_label.setText(summary_text or "响度扫描报告已刷新。双击条目可跳转到事件。")
        self.report_detail_label.setText("响度扫描报告已刷新。")
        self._update_workspace_summary_labels()
        self.loudnessReportUpdated.emit(summary_text or "响度扫描报告已刷新。双击条目可跳转到事件。")

    def show_report_tab(self, index: int) -> None:
        if not 0 <= index < len(self._report_page_titles):
            return
        self._active_report_index = index
        self.report_pages.setCurrentIndex(index)
        self._report_tab_index = index
        report_title = self._report_page_titles[index]
        self.report_focus_label.setText(report_title)
        self.workspace_report_focus_label.setText(report_title)
        self.activity_report_focus_label.setText(report_title)
        if index == 1:
            self._activate_workspace_mode("validation")
        else:
            self._activate_workspace_mode("results")
        self._update_object_bus_status()

    def ask_import_clip_paths(self) -> list[str]:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "导入音频片段",
            "",
            "音频文件 (*.wav *.ogg)",
        )
        return file_paths

    def ask_import_audio_event_paths(self) -> list[str]:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "批量导入音频为事件",
            "",
            "音频文件 (*.wav *.ogg)",
        )
        return file_paths

    def ask_event_import_template(self, buses: list[str], default_bus: str) -> dict[str, object] | None:
        auto_option = "自动推荐"
        bus_options = [auto_option, *buses]
        remembered_bus_name = str(self._event_import_template_defaults.get("bus_name", ""))
        current_bus_label = remembered_bus_name if remembered_bus_name in buses else auto_option
        bus_name, accepted = QInputDialog.getItem(
            self,
            "导入模板",
            f"导入后挂到哪个 {WWISE_OUTPUT_BUS_LABEL}",
            bus_options,
            current=bus_options.index(current_bus_label) if current_bus_label in bus_options else (bus_options.index(default_bus) if default_bus in bus_options else 0),
            editable=False,
        )
        if not accepted:
            return None
        asset_prefix, accepted = QInputDialog.getText(
            self,
            "导入模板",
            "资源键前缀（可选）",
            text=str(self._event_import_template_defaults.get("asset_prefix", "")),
        )
        if not accepted:
            return None
        tags_text, accepted = QInputDialog.getText(
            self,
            "导入模板",
            "默认标签（逗号分隔，可选）",
            text=", ".join(str(tag) for tag in self._event_import_template_defaults.get("tags", [])),
        )
        if not accepted:
            return None
        template = {
            "bus_name": "" if bus_name == auto_option else bus_name,
            "asset_prefix": asset_prefix.strip().strip("/"),
            "tags": [tag.strip() for tag in tags_text.split(",") if tag.strip()],
        }
        self._event_import_template_defaults = {
            "bus_name": str(template["bus_name"]),
            "asset_prefix": str(template["asset_prefix"]),
            "tags": list(template["tags"]),
        }
        self._sync_event_import_template_controls()
        return template

    def ask_new_folder_name(self) -> str:
        name, accepted = QInputDialog.getText(self, "新建文件夹", "文件夹名称")
        return name.strip() if accepted else ""

    def ask_new_event_id(self) -> str:
        event_id, accepted = QInputDialog.getText(self, "新建事件", "事件 ID")
        return event_id.strip() if accepted else ""

    def ask_new_bus_name(self) -> str:
        bus_name, accepted = QInputDialog.getText(self, "新建 Bus", WWISE_BUS_NAME_LABEL)
        return bus_name.strip() if accepted else ""

    def ask_rename_value(self, title: str, label: str, initial_value: str) -> str:
        value, accepted = QInputDialog.getText(self, title, label, text=initial_value)
        return value.strip() if accepted else ""

    def ask_bulk_weight(self, current_value: int = 1) -> int | None:
        value, accepted = QInputDialog.getInt(
            self,
            "批量设置权重",
            "权重",
            value=current_value,
            minValue=MIN_CLIP_WEIGHT,
            maxValue=MAX_CLIP_WEIGHT,
        )
        return value if accepted else None

    def ask_batch_rename(self) -> tuple[str, int] | None:
        prefix, accepted = QInputDialog.getText(self, "批量重命名片段", "基础名称")
        if not accepted or not prefix.strip():
            return None
        start_index, accepted = QInputDialog.getInt(self, "批量重命名片段", "起始序号", value=1, minValue=1, maxValue=9999)
        if not accepted:
            return None
        return prefix.strip(), start_index

    def ask_batch_event_rename(self) -> tuple[str, int] | None:
        prefix, accepted = QInputDialog.getText(self, "批量重命名事件", "基础名称")
        if not accepted or not prefix.strip():
            return None
        start_index, accepted = QInputDialog.getInt(self, "批量重命名事件", "起始序号", value=1, minValue=1, maxValue=9999)
        if not accepted:
            return None
        return prefix.strip(), start_index

    def ask_batch_event_bus(self, bus_names: list[str], current_bus: str) -> str | None:
        if not bus_names:
            return None
        bus_name, accepted = QInputDialog.getItem(
            self,
            f"批量修改事件{WWISE_OUTPUT_BUS_LABEL}",
            WWISE_TARGET_BUS_LABEL,
            bus_names,
            current=bus_names.index(current_bus) if current_bus in bus_names else 0,
            editable=False,
        )
        return bus_name if accepted and bus_name else None

    def confirm_delete(self, label: str) -> bool:
        result = QMessageBox.question(self, APP_NAME, label)
        return result == QMessageBox.StandardButton.Yes

    def confirm_delete_audio(self, audio_id: str, referenced_event_ids: list[str]) -> bool:
        if not referenced_event_ids:
            return self.confirm_delete(f"确认删除 Audio“{audio_id}”？")

        message_box = QMessageBox(self)
        message_box.setWindowTitle(APP_NAME)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(
            f"Audio“{audio_id}”当前仍被 {len(referenced_event_ids)} 个 Event 引用。\n删除 Audio 需要同时删除这些引用 Event。"
        )
        message_box.setInformativeText("确认后会级联删除引用它的 Event，并从 Audio 树移除该 AudioObject。")
        delete_button = message_box.addButton(
            f"删除 Audio 与 {len(referenced_event_ids)} 个引用 Event",
            QMessageBox.ButtonRole.DestructiveRole,
        )
        message_box.addButton(QMessageBox.StandardButton.Cancel)
        message_box.exec()
        return message_box.clickedButton() is delete_button

    def ask_source_delete_action(
        self,
        source_count: int,
        *,
        allow_remove_from_audio: bool,
        allow_remove_from_registry: bool,
        allow_delete_files: bool,
    ) -> str | None:
        message_box = QMessageBox(self)
        message_box.setWindowTitle(APP_NAME)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(f"已选择 {source_count} 条源音频。请选择删除方式。")
        message_box.setInformativeText(
            "从当前 Audio 移除绑定只影响当前 AudioObject；从项目注册表移除只清理未引用注册项；从磁盘删除源文件会让引用它们的条目标记为缺失。"
        )
        remove_binding_button = message_box.addButton("从当前 Audio 移除绑定", QMessageBox.ButtonRole.ActionRole)
        remove_registry_button = message_box.addButton("从项目注册表移除", QMessageBox.ButtonRole.ActionRole)
        delete_files_button = message_box.addButton("从磁盘删除源文件", QMessageBox.ButtonRole.DestructiveRole)
        remove_binding_button.setEnabled(allow_remove_from_audio)
        remove_registry_button.setEnabled(allow_remove_from_registry)
        delete_files_button.setEnabled(allow_delete_files)
        message_box.addButton(QMessageBox.StandardButton.Cancel)
        message_box.exec()
        clicked_button = message_box.clickedButton()
        if clicked_button is remove_binding_button and allow_remove_from_audio:
            return "remove_from_audio"
        if clicked_button is remove_registry_button and allow_remove_from_registry:
            return "remove_from_registry"
        if clicked_button is delete_files_button and allow_delete_files:
            return "delete_files"
        return None

    def show_context_feedback(self, text: str, tooltip: str | None = None) -> None:
        detail_text = str(text).strip()
        if not detail_text:
            return
        self.report_detail_label.setText(detail_text)
        self.report_detail_label.setToolTip(tooltip if tooltip is not None else detail_text)

    def set_explorer_action_state(
        self,
        *,
        rename_enabled: bool,
        delete_enabled: bool,
        bulk_bus_enabled: bool,
        rename_text: str = "重命名",
        delete_text: str = "删除",
        rename_tooltip: str = "",
        delete_tooltip: str = "",
    ) -> None:
        self.rename_button.setEnabled(rename_enabled)
        self.delete_button.setEnabled(delete_enabled)
        self.bulk_event_bus_button.setEnabled(bulk_bus_enabled)
        self.rename_button.setText(rename_text)
        self.delete_button.setText(delete_text)
        self.rename_button.setToolTip(rename_tooltip)
        self.delete_button.setToolTip(delete_tooltip)

    def ask_audio_import_create_events(self, import_count: int) -> bool | None:
        result = QMessageBox.question(
            self,
            APP_NAME,
            f"本次将创建 {import_count} 个 Audio Object。是否同时创建同名 Event？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return None
        return result == QMessageBox.StandardButton.Yes

    def ask_audio_import_binding_mode(self, audio_name: str) -> str | None:
        result = QMessageBox.question(
            self,
            APP_NAME,
            f"Audio“{audio_name}”已存在源音频。是否替换为本次拖入内容？\n选择“否”将把新资源追加到当前 Audio。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return None
        return "replace" if result == QMessageBox.StandardButton.Yes else "append"

    def confirm_save_before_close(self) -> str:
        result = QMessageBox.question(
            self,
            APP_NAME,
            "当前工程有未保存更改。是否先保存？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return "save"
        if result == QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

    def set_close_handler(self, handler) -> None:
        self._close_handler = handler

    def set_ui_scale(self, scale: float) -> None:
        clamped = max(0.85, min(1.6, round(scale, 2)))
        self._ui_scale = clamped
        self.scale_status_label.setText(f"{int(clamped * 100)}%")
        self._apply_wwise_style()

    def increase_ui_scale(self) -> None:
        self.set_ui_scale(self._ui_scale + 0.1)

    def decrease_ui_scale(self) -> None:
        self.set_ui_scale(self._ui_scale - 0.1)

    def reset_ui_scale(self) -> None:
        self.set_ui_scale(1.0)

    def restore_default_layout(self) -> None:
        self.attach_explorer_panel()
        self._set_workspace_splitter_sizes(self._default_workspace_splitter_sizes)
        self._set_main_splitter_sizes(self._default_main_splitter_sizes)
        self._editor_tab_index = 0
        self._property_tab_index = 0
        self._set_content_top_splitter_sizes(self._default_content_top_splitter_sizes)
        self.contents_tabs.setCurrentIndex(0)
        self._active_report_index = 0
        self.report_pages.setCurrentIndex(0)
        self._report_tab_index = 0
        self.report_detail_label.setText("已恢复默认布局。")
        self._activate_workspace_mode("events")
        self._update_object_bus_status()

    def focus_panel(self, panel_key: str) -> None:
        workspace_total = max(sum(self.workspace_splitter.sizes()), sum(self._default_workspace_splitter_sizes))
        main_total = max(sum(self._effective_main_splitter_sizes()), sum(self._default_main_splitter_sizes))
        self._set_workspace_splitter_sizes([int(workspace_total * 0.82), int(workspace_total * 0.18)])
        if panel_key == "explorer":
            if self._explorer_detached:
                self.show_detached_explorer()
                return
            self._set_main_splitter_sizes([int(main_total * 0.42), int(main_total * 0.58)])
            return
        if panel_key == "property":
            self._activate_workspace_mode("events")
            self._editor_tab_index = 0
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
        elif panel_key == "contents":
            self._activate_workspace_mode("resources")
            self._editor_tab_index = 1
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
            self.contents_tabs.setCurrentIndex(0)
            self._set_content_top_splitter_sizes(self._default_focus_content_splitter_sizes)
        elif panel_key == "meter":
            self._activate_workspace_mode("events")
            self._editor_tab_index = 2
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
        elif panel_key == "log":
            self._activate_workspace_mode("results")
        self._update_object_bus_status()

    def _bind_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence("Delete"), self),
            QShortcut(QKeySequence("F2"), self),
            QShortcut(QKeySequence("Return"), self),
            QShortcut(QKeySequence("Enter"), self),
            QShortcut(QKeySequence.StandardKey.Copy, self),
            QShortcut(QKeySequence("Ctrl+Shift+P"), self),
        ]
        self._shortcuts[0].activated.connect(self._handle_delete_shortcut)
        self._shortcuts[1].activated.connect(self._handle_rename_shortcut)
        self._shortcuts[2].activated.connect(self._handle_open_shortcut)
        self._shortcuts[3].activated.connect(self._handle_open_shortcut)
        self._shortcuts[4].activated.connect(self._handle_copy_shortcut)
        self._shortcuts[5].activated.connect(self._show_command_palette)

    def _handle_delete_shortcut(self) -> None:
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self._request_remove_clips()
            return
        if self._focus_is_within(self.source_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "sources"):
            self.deleteSelectedRequested.emit()
            return
        if self._focus_is_within(self.audio_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "audios"):
            self.deleteSelectedRequested.emit()
            return
        if self._focus_is_within(self.tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "events"):
            self.deleteSelectedRequested.emit()

    def _handle_rename_shortcut(self) -> None:
        if self._focus_is_within(self.tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "events"):
            payload = self._selected_tree_payload()
            if payload is not None and payload[0] == "source_binding":
                self.report_detail_label.setText("Source Binding 请在片段列表中批量重命名。")
                return
        if self._focus_is_within(self.source_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "sources"):
            self.show_context_feedback("源音频路径重命名请在外部文件系统中处理；浏览器内暂不提供路径重命名。")
            return
        if self._focus_is_within(self.audio_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "audios"):
            self.renameSelectedRequested.emit()
            return
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self._request_batch_rename()

    def _handle_open_shortcut(self) -> None:
        if self._focus_is_within(self.project_bus_list) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "buses"):
            self._activate_workspace_mode("buses")
            if self.current_project_bus_name() == "Master":
                self.project_master_volume_spin.setFocus()
            else:
                self.project_bus_name_edit.setFocus()
                self.project_bus_name_edit.selectAll()
            return
        if self._focus_is_within(self.source_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "sources"):
            self._locate_selected_source_asset()
            return
        if self._focus_is_within(self.audio_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "audios"):
            self.set_active_property_category("音频属性")
            self.bus_combo.setFocus()
            return
        if self._focus_is_within(self.tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "events"):
            payload = self._selected_tree_payload()
            if payload is None:
                return
            if payload[0] == "source_binding":
                _event_id, clip_id = decode_source_binding_token(payload[1])
                self.set_active_contents_category("片段")
                self.select_clip_ids([clip_id])
                self.clip_asset_detail_edit.setFocus()
                self.clip_asset_detail_edit.selectAll()
                return
            if payload[0] == "event":
                self.reportTargetRequested.emit("audio", payload[1])
                return
            self.set_active_property_category("工程")
            self.export_root_edit.setFocus()
            self.export_root_edit.selectAll()
            return
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self.set_active_contents_category("片段")
            self.clip_asset_detail_edit.setFocus()
            self.clip_asset_detail_edit.selectAll()

    def _handle_copy_shortcut(self) -> None:
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self._copy_selected_clip_asset_keys()
            return
        if self._focus_is_within(self.project_bus_list) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "buses"):
            bus_name = self.current_project_bus_name()
            if not bus_name:
                return
            QApplication.clipboard().setText(bus_name)
            self.report_detail_label.setText(f"已复制总线标识：{bus_name}")
            self.report_detail_label.setToolTip(bus_name)
            return
        if self._focus_is_within(self.source_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "sources"):
            self._copy_selected_source_asset_path()
            return
        if self._focus_is_within(self.audio_tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "audios"):
            audio_id = self.audio_tree.current_audio_id()
            if not audio_id:
                return
            QApplication.clipboard().setText(audio_id)
            self.show_context_feedback(f"已复制 Audio 标识：{audio_id}", audio_id)
            return
        if self._focus_is_within(self.tree) or (self._focus_is_within(self.tree_filter_edit) and self._active_explorer_page_key() == "events"):
            payload = self._selected_tree_payload()
            if payload is None:
                return
            if payload[0] == "source_binding":
                clip_ids = self.selected_tree_source_binding_clip_ids()
                if not clip_ids:
                    return
                QApplication.clipboard().setText("\n".join(clip_ids))
                self.report_detail_label.setText(f"已复制 {len(clip_ids)} 个 Source Binding 标识。")
                self.report_detail_label.setToolTip("\n".join(clip_ids[:12]))
                return
            QApplication.clipboard().setText(payload[1])
            self.report_detail_label.setText(f"已复制对象标识：{payload[1]}")
            self.report_detail_label.setToolTip(payload[1])

    def set_preview_audio_metrics(self, snapshot: AudioMeterSnapshot, clip_id: str, asset_key: str) -> None:
        if not snapshot.available or snapshot.processed is None:
            self.clear_preview_audio_metrics(snapshot.reason or "当前片段无法分析响度。")
            return
        processed = snapshot.processed
        source = snapshot.source or processed
        true_peak_db = self._resolve_peak_display_value(processed.true_peak_db, "true")
        left_peak_db = self._resolve_peak_display_value(processed.left_peak_db, "left")
        right_peak_db = self._resolve_peak_display_value(processed.right_peak_db, "right")
        self.audio_meter_context_label.setText(f"片段 {clip_id} | 资源 {asset_key}")
        self.audio_meter_summary_source_context_label.setText(f"片段 {clip_id}")
        self.audio_meter_summary_context_label.setText(f"片段 {clip_id}")
        self._set_preview_metric_context(self.preview_metric_source_context_label, f"片段 {clip_id}")
        self._set_preview_metric_context(self.preview_metric_context_label, f"片段 {clip_id}")
        self.audio_meter_short_term_value.setText(self._format_meter_value(processed.short_term_lufs))
        self.audio_meter_short_term_max_value.setText(self._format_meter_value(processed.short_term_max_lufs))
        self.audio_meter_integrated_value.setText(self._format_meter_value(processed.integrated_lufs))
        self.audio_meter_momentary_value.setText(self._format_meter_value(processed.momentary_lufs))
        self.audio_meter_momentary_max_value.setText(self._format_meter_value(processed.momentary_max_lufs))
        self.preview_inline_momentary_max_value.setText(self._format_meter_value(processed.momentary_max_lufs))
        self.audio_meter_lra_value.setText(f"{processed.loudness_range_lu:.1f}")
        self.audio_meter_true_peak_value.setText(self._format_meter_value(true_peak_db))
        self.audio_meter_summary_source_integrated_value.setText(self._format_meter_value(source.integrated_lufs))
        self.audio_meter_summary_source_true_peak_value.setText(self._format_meter_value(source.true_peak_db))
        self.audio_meter_summary_integrated_value.setText(self._format_meter_value(processed.integrated_lufs))
        self.audio_meter_summary_true_peak_value.setText(self._format_meter_value(true_peak_db))
        self.preview_metric_source_integrated_value.setText(self._format_meter_value(source.integrated_lufs))
        self.preview_metric_source_true_peak_value.setText(self._format_meter_value(source.true_peak_db))
        self.preview_metric_integrated_value.setText(self._format_meter_value(processed.integrated_lufs))
        self.preview_metric_true_peak_value.setText(self._format_meter_value(true_peak_db))
        self.audio_meter_left_peak_value.setText(self._format_meter_value(left_peak_db))
        self.audio_meter_left_rms_value.setText(self._format_meter_value(processed.left_rms_db))
        self.audio_meter_right_peak_value.setText(self._format_meter_value(right_peak_db))
        self.audio_meter_right_rms_value.setText(self._format_meter_value(processed.right_rms_db))
        self.audio_meter_left_bar.setValue(self._meter_progress(left_peak_db))
        self.audio_meter_right_bar.setValue(self._meter_progress(right_peak_db))
        self.momentary_plot.set_series(source.momentary_history or [], processed.momentary_history or [])
        self.short_term_plot.set_series(source.short_term_history or [], processed.short_term_history or [])

    def clear_preview_audio_metrics(self, reason: str) -> None:
        self._held_true_peak_db = None
        self._held_left_peak_db = None
        self._held_right_peak_db = None
        self.audio_meter_context_label.setText(reason)
        self.audio_meter_summary_source_context_label.setText(reason)
        self.audio_meter_summary_context_label.setText(reason)
        self._set_preview_metric_context(self.preview_metric_source_context_label, reason)
        self._set_preview_metric_context(self.preview_metric_context_label, reason)
        for label in [
            self.audio_meter_short_term_value,
            self.audio_meter_short_term_max_value,
            self.audio_meter_integrated_value,
            self.audio_meter_momentary_value,
            self.audio_meter_momentary_max_value,
            self.audio_meter_true_peak_value,
            self.audio_meter_left_peak_value,
            self.audio_meter_left_rms_value,
            self.audio_meter_right_peak_value,
            self.audio_meter_right_rms_value,
        ]:
            label.setText("-Inf")
        self.audio_meter_summary_source_integrated_value.setText("-Inf")
        self.audio_meter_summary_source_true_peak_value.setText("-Inf")
        self.audio_meter_summary_integrated_value.setText("-Inf")
        self.audio_meter_summary_true_peak_value.setText("-Inf")
        self.preview_metric_source_integrated_value.setText("-Inf")
        self.preview_metric_source_true_peak_value.setText("-Inf")
        self.preview_metric_integrated_value.setText("-Inf")
        self.preview_metric_true_peak_value.setText("-Inf")
        self.preview_inline_momentary_max_value.setText("-Inf")
        self.audio_meter_lra_value.setText("0.0")
        self.audio_meter_left_bar.setValue(0)
        self.audio_meter_right_bar.setValue(0)
        self.momentary_plot.clear()
        self.short_term_plot.clear()

    def clear_peak_hold(self) -> None:
        self._held_true_peak_db = None
        self._held_left_peak_db = None
        self._held_right_peak_db = None
        self.audio_meter_true_peak_value.setText("-Inf")
        self.audio_meter_summary_true_peak_value.setText("-Inf")
        self.preview_metric_true_peak_value.setText("-Inf")
        self.audio_meter_left_peak_value.setText("-Inf")
        self.audio_meter_right_peak_value.setText("-Inf")
        self.audio_meter_left_bar.setValue(0)
        self.audio_meter_right_bar.setValue(0)

    def _resolve_peak_display_value(self, value: float, channel: str) -> float:
        if not self.hold_peaks_check.isChecked():
            if channel == "true":
                self._held_true_peak_db = value
            elif channel == "left":
                self._held_left_peak_db = value
            else:
                self._held_right_peak_db = value
            return value
        current_held = {
            "true": self._held_true_peak_db,
            "left": self._held_left_peak_db,
            "right": self._held_right_peak_db,
        }[channel]
        if current_held is None or value > current_held:
            current_held = value
        if channel == "true":
            self._held_true_peak_db = current_held
        elif channel == "left":
            self._held_left_peak_db = current_held
        else:
            self._held_right_peak_db = current_held
        return current_held

    def _format_meter_value(self, value: float) -> str:
        if value == float("-inf"):
            return "-Inf"
        return f"{value:.1f}"

    def _meter_progress(self, value: float) -> int:
        if value == float("-inf"):
            return 0
        normalized = max(-60.0, min(6.0, value))
        return int(((normalized + 60.0) / 66.0) * 100)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._close_handler is not None and not self._close_handler():
            event.ignore()
            return
        self._closing_main_window = True
        try:
            if self._explorer_detached:
                self.explorer_window.hide()
            super().closeEvent(event)
        finally:
            self._closing_main_window = False

    def _bind_internal_signals(self) -> None:
        self.task_sidebar.modeRequested.connect(self._activate_workspace_mode)
        self.zoom_in_button.clicked.connect(self.increase_ui_scale)
        self.zoom_out_button.clicked.connect(self.decrease_ui_scale)
        self.zoom_reset_button.clicked.connect(self.reset_ui_scale)
        self.reset_layout_button.clicked.connect(self.restore_default_layout)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.command_button.clicked.connect(self._show_command_palette)
        self.global_search_edit.returnPressed.connect(self._request_global_search)
        self.global_search_edit.textChanged.connect(self._sync_global_search_fields)
        self.global_search_button.clicked.connect(self._request_global_search)
        self.build_button.clicked.connect(lambda: self._activate_workspace_mode("build"))
        self.build_execute_button.clicked.connect(self.buildRequested.emit)
        self.object_parent_button.clicked.connect(self.navigateParentRequested.emit)
        self.reference_parent_value_button.clicked.connect(self.navigateParentRequested.emit)
        self.reference_bus_value_button.clicked.connect(lambda: self.set_active_property_category("事件"))
        self.reference_assets_value_button.clicked.connect(lambda: self.set_active_contents_category("片段"))
        self.reference_generation_value_button.clicked.connect(lambda: self.set_active_property_category("生成"))
        self.object_preview_button.clicked.connect(self.previewRequested.emit)
        self.object_contents_button.clicked.connect(lambda: self._activate_workspace_mode("resources"))
        self.object_follow_bus_button.clicked.connect(self._follow_current_event_bus)
        self.object_report_button.clicked.connect(lambda: self._activate_workspace_mode("validation"))
        self.validation_filter_severity_combo.currentIndexChanged.connect(self._apply_validation_filters)
        self.validation_filter_keyword_edit.textChanged.connect(lambda _text: self._apply_validation_filters())
        self.validation_filter_reset_button.clicked.connect(self._reset_validation_filters)
        self.validation_revalidate_button.clicked.connect(self.validate_button.click)
        self.validation_locate_button.clicked.connect(self._locate_selected_validation_issue)
        self.open_loudness_view_button.clicked.connect(self.show_loudness_view)
        self.preview_transport_toggle_button.toggled.connect(self._toggle_preview_transport_details)
        self.preview_transport_play_button.clicked.connect(self.previewTransportPlayRequested.emit)
        self.preview_transport_pause_button.clicked.connect(self._toggle_preview_transport_pause)
        self.preview_transport_restart_button.clicked.connect(self.restartPreviewRequested.emit)
        self.preview_transport_stop_button.clicked.connect(self.stopPreviewEventRequested.emit)
        self.events_workspace_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.buses_workspace_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.current_bus_detail_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.gamesync_workspace_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.contents_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.events_workspace_tabs.currentChanged.connect(lambda _index: self._schedule_layout_flush())
        self.buses_workspace_tabs.currentChanged.connect(lambda _index: self._schedule_layout_flush())
        self.current_bus_detail_tabs.currentChanged.connect(lambda _index: self._schedule_layout_flush())
        self.gamesync_workspace_tabs.currentChanged.connect(lambda _index: self._schedule_layout_flush())
        self.contents_tabs.currentChanged.connect(lambda _index: self._schedule_layout_flush())
        self.clear_meter_button.clicked.connect(self.clear_peak_hold)
        self.loudness_scan_button.clicked.connect(self.loudnessScanRequested.emit)
        self.clip_preview_button.clicked.connect(self._request_selected_clip_preview)
        self.clip_preview_segment_button.clicked.connect(self._request_selected_clip_segment_preview)
        self.clip_copy_asset_key_button.clicked.connect(self._copy_selected_clip_asset_keys)
        self.clip_locate_source_button.clicked.connect(self._locate_selected_clip_source)
        self.clip_table.itemSelectionChanged.connect(self._sync_clip_detail_from_table)
        self.event_id_edit.editingFinished.connect(self._emit_event_properties_changed)
        self.display_name_edit.editingFinished.connect(self._emit_event_properties_changed)
        self.bus_combo.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.bus_combo.currentIndexChanged.connect(self._sync_current_event_bus_selection)
        self.play_mode_combo.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.play_mode_combo.currentIndexChanged.connect(self._sync_event_mode_ui)
        self.steal_policy_combo.currentIndexChanged.connect(self._emit_event_properties_changed)
        self.load_policy_combo.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.source_audio_format_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.runtime_audio_format_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.default_bus_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.auto_assign_bus_by_name_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.project_bus_list.itemSelectionChanged.connect(self._handle_project_bus_selection_changed)
        self.project_bus_list.hierarchyChanged.connect(self._handle_project_bus_hierarchy_changed)
        self.project_bus_name_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.project_bus_parent_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.project_bus_volume_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.project_bus_mute_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.project_master_volume_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.project_master_mute_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.bus_rtpc_list.itemSelectionChanged.connect(
            lambda: self._load_bus_binding_editors(self._project_bus_configs[self._selected_project_bus_index()] if self._selected_project_bus_index() >= 0 else None)
        )
        self.bus_rtpc_add_button.clicked.connect(lambda: self._add_current_bus_binding("rtpc"))
        self.bus_rtpc_remove_button.clicked.connect(lambda: self._remove_current_bus_binding("rtpc"))
        self.bus_rtpc_parameter_edit.editingFinished.connect(self._handle_bus_rtpc_curve_context_changed)
        self.bus_rtpc_target_combo.currentIndexChanged.connect(self._handle_bus_rtpc_curve_context_changed)
        self.bus_rtpc_scope_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.bus_rtpc_curve_table.pointsChanged.connect(self._emit_project_settings_changed)
        self.bus_rtpc_curve_table.selectionChanged.connect(lambda _index: self._sync_curve_interpolation_combo(self.bus_rtpc_curve_table, self.bus_rtpc_interpolation_combo))
        self.bus_rtpc_curve_table.selectionChanged.connect(lambda _index: self._sync_curve_point_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin))
        self.bus_rtpc_curve_table.pointPreviewChanged.connect(lambda: self._sync_curve_point_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin))
        self.bus_rtpc_interpolation_combo.currentIndexChanged.connect(lambda: self._update_curve_interpolation(self.bus_rtpc_curve_table, self.bus_rtpc_interpolation_combo, self._emit_project_settings_changed))
        self.bus_rtpc_add_point_button.clicked.connect(lambda: self._append_curve_point(self.bus_rtpc_curve_table, self._emit_project_settings_changed))
        self.bus_rtpc_remove_point_button.clicked.connect(lambda: self._remove_curve_point(self.bus_rtpc_curve_table, self._emit_project_settings_changed))
        self.bus_rtpc_selected_input_spin.valueChanged.connect(lambda _value: self._update_curve_point_from_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin))
        self.bus_rtpc_selected_output_spin.valueChanged.connect(lambda _value: self._update_curve_point_from_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin))
        self.bus_rtpc_snap_check.checkStateChanged.connect(lambda _state: self._apply_curve_snap_settings(self.bus_rtpc_curve_table, self.bus_rtpc_snap_check, self.bus_rtpc_snap_x_spin, self.bus_rtpc_snap_y_spin))
        self.bus_rtpc_snap_x_spin.valueChanged.connect(lambda _value: self._apply_curve_snap_settings(self.bus_rtpc_curve_table, self.bus_rtpc_snap_check, self.bus_rtpc_snap_x_spin, self.bus_rtpc_snap_y_spin))
        self.bus_rtpc_snap_y_spin.valueChanged.connect(lambda _value: self._apply_curve_snap_settings(self.bus_rtpc_curve_table, self.bus_rtpc_snap_check, self.bus_rtpc_snap_x_spin, self.bus_rtpc_snap_y_spin))
        self.bus_rtpc_notes_edit.textChanged.connect(self._emit_project_settings_changed)
        self.bus_state_list.itemSelectionChanged.connect(
            lambda: self._load_bus_binding_editors(self._project_bus_configs[self._selected_project_bus_index()] if self._selected_project_bus_index() >= 0 else None)
        )
        self.bus_state_add_button.clicked.connect(lambda: self._add_current_bus_binding("state"))
        self.bus_state_remove_button.clicked.connect(lambda: self._remove_current_bus_binding("state"))
        self.bus_state_group_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.bus_state_name_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.bus_state_volume_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.bus_state_pitch_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.bus_state_mute_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.bus_state_notes_edit.textChanged.connect(self._emit_project_settings_changed)
        self.inline_bus_new_button.clicked.connect(self._request_add_and_assign_project_bus)
        self.inline_bus_set_default_button.clicked.connect(self._set_current_bus_as_default)
        self.inline_bus_to_master_button.clicked.connect(self._route_current_bus_to_master)
        self.inline_bus_open_parent_button.clicked.connect(self._select_parent_bus_for_current)
        self.project_bus_focus_audio_button.clicked.connect(lambda: self.set_active_property_category("音频属性"))
        self.project_bus_add_button.clicked.connect(self._request_add_project_bus)
        self.project_bus_remove_button.clicked.connect(self._request_remove_project_bus)
        self.project_bus_browser_button.clicked.connect(lambda: self.explorer_tabs.setCurrentIndex(0))
        self.source_browser_filter_combo.currentIndexChanged.connect(lambda _index: self._refresh_source_browser_tree())
        self.source_browser_locate_button.clicked.connect(self._locate_selected_source_asset)
        self.source_browser_copy_button.clicked.connect(self._copy_selected_source_asset_path)
        self.source_browser_locate_event_button.clicked.connect(self._locate_selected_source_reference_audio)
        self.source_browser_add_to_event_button.clicked.connect(self._append_selected_source_to_current_audio)
        self.audio_browser_locate_event_button.clicked.connect(self._locate_selected_audio_reference_event)
        self.audio_browser_open_bindings_button.clicked.connect(self._open_selected_audio_bindings)
        self.event_open_audio_workspace_button.clicked.connect(lambda: self.set_active_property_category("音频属性"))
        self.event_locate_audio_browser_button.clicked.connect(self.focus_current_audio_browser)
        self.gamesync_browser_tabs.currentChanged.connect(lambda _index: self._update_gamesync_browser_status())
        self.gamesync_parameter_browser_list.itemSelectionChanged.connect(self._update_gamesync_browser_status)
        self.gamesync_state_browser_list.itemSelectionChanged.connect(self._update_gamesync_browser_status)
        self.gamesync_switch_browser_list.itemSelectionChanged.connect(self._update_gamesync_browser_status)
        self.gamesync_parameter_workspace_list.itemSelectionChanged.connect(lambda: self._load_gamesync_editor("game_parameters"))
        self.gamesync_parameter_workspace_list.itemSelectionChanged.connect(
            lambda: self._update_gamesync_detail_label(
                self.gamesync_parameter_workspace_list,
                self.gamesync_parameter_workspace_detail_label,
                "当前还没有 Game Parameter。",
            )
        )
        self.gamesync_state_workspace_list.itemSelectionChanged.connect(lambda: self._load_gamesync_editor("state_groups"))
        self.gamesync_state_workspace_list.itemSelectionChanged.connect(
            lambda: self._update_gamesync_detail_label(
                self.gamesync_state_workspace_list,
                self.gamesync_state_workspace_detail_label,
                "当前还没有 State Group。",
            )
        )
        self.gamesync_switch_workspace_list.itemSelectionChanged.connect(lambda: self._load_gamesync_editor("switch_groups"))
        self.gamesync_switch_workspace_list.itemSelectionChanged.connect(
            lambda: self._update_gamesync_detail_label(
                self.gamesync_switch_workspace_list,
                self.gamesync_switch_workspace_detail_label,
                "当前还没有 Switch Group。",
            )
        )
        self.gamesync_parameter_add_button.clicked.connect(lambda: self._create_gamesync_item("game_parameters"))
        self.gamesync_parameter_remove_button.clicked.connect(lambda: self._remove_gamesync_item("game_parameters"))
        self.gamesync_parameter_name_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_parameter_default_spin.valueChanged.connect(self._emit_gamesync_changed)
        self.gamesync_parameter_min_spin.valueChanged.connect(self._emit_gamesync_changed)
        self.gamesync_parameter_max_spin.valueChanged.connect(self._emit_gamesync_changed)
        self.gamesync_parameter_notes_edit.textChanged.connect(self._emit_gamesync_changed)
        self.gamesync_state_add_button.clicked.connect(lambda: self._create_gamesync_item("state_groups"))
        self.gamesync_state_remove_button.clicked.connect(lambda: self._remove_gamesync_item("state_groups"))
        self.gamesync_state_name_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_state_value_list.itemSelectionChanged.connect(lambda: self._load_gamesync_child_value_editor("state_groups"))
        self.gamesync_state_value_add_button.clicked.connect(lambda: self._create_gamesync_child_value("state_groups"))
        self.gamesync_state_value_remove_button.clicked.connect(lambda: self._remove_gamesync_child_value("state_groups"))
        self.gamesync_state_values_edit.editingFinished.connect(lambda: self._commit_gamesync_child_value("state_groups"))
        self.gamesync_state_value_volume_spin.valueChanged.connect(lambda _value: self._commit_gamesync_child_value("state_groups"))
        self.gamesync_state_value_pitch_spin.valueChanged.connect(lambda _value: self._commit_gamesync_child_value("state_groups"))
        self.gamesync_state_value_mute_check.checkStateChanged.connect(lambda _state: self._commit_gamesync_child_value("state_groups"))
        self.gamesync_state_value_notes_edit.textChanged.connect(lambda: self._commit_gamesync_child_value("state_groups"))
        self.gamesync_state_default_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_state_notes_edit.textChanged.connect(self._emit_gamesync_changed)
        self.gamesync_switch_add_button.clicked.connect(lambda: self._create_gamesync_item("switch_groups"))
        self.gamesync_switch_remove_button.clicked.connect(lambda: self._remove_gamesync_item("switch_groups"))
        self.gamesync_switch_name_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_switch_value_list.itemSelectionChanged.connect(lambda: self._load_gamesync_child_value_editor("switch_groups"))
        self.gamesync_switch_value_add_button.clicked.connect(lambda: self._create_gamesync_child_value("switch_groups"))
        self.gamesync_switch_value_remove_button.clicked.connect(lambda: self._remove_gamesync_child_value("switch_groups"))
        self.gamesync_switch_values_edit.editingFinished.connect(lambda: self._commit_gamesync_child_value("switch_groups"))
        self.gamesync_switch_value_volume_spin.valueChanged.connect(lambda _value: self._commit_gamesync_child_value("switch_groups"))
        self.gamesync_switch_value_pitch_spin.valueChanged.connect(lambda _value: self._commit_gamesync_child_value("switch_groups"))
        self.gamesync_switch_value_mute_check.checkStateChanged.connect(lambda _state: self._commit_gamesync_child_value("switch_groups"))
        self.gamesync_switch_value_notes_edit.textChanged.connect(lambda: self._commit_gamesync_child_value("switch_groups"))
        self.gamesync_switch_default_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_switch_use_rtpc_check.checkStateChanged.connect(self._emit_gamesync_changed)
        self.gamesync_switch_mapped_parameter_edit.editingFinished.connect(self._emit_gamesync_changed)
        self.gamesync_switch_notes_edit.textChanged.connect(self._emit_gamesync_changed)
        self.preview_bus_combo.currentIndexChanged.connect(self.previewBusSelectionChanged.emit)
        self.preview_bus_volume_spin.valueChanged.connect(self._emit_preview_bus_state_changed)
        self.preview_bus_mute_check.checkStateChanged.connect(self._emit_preview_bus_state_changed)
        self.preview_parameter_name_combo.currentIndexChanged.connect(self._handle_preview_parameter_selection_changed)
        self.preview_parameter_scope_combo.currentIndexChanged.connect(self._handle_preview_parameter_selection_changed)
        self.preview_parameter_value_spin.valueChanged.connect(lambda _value: self._handle_preview_parameter_value_changed())
        self.preview_parameter_slider.sliderMoved.connect(self._preview_parameter_slider_preview)
        self.preview_parameter_slider.valueChanged.connect(self._handle_preview_parameter_slider_changed)
        self.preview_state_group_combo.currentIndexChanged.connect(self._handle_preview_state_group_changed)
        self.preview_state_name_combo.currentIndexChanged.connect(self._handle_preview_state_value_changed)
        self.preview_switch_group_combo.currentIndexChanged.connect(self._handle_preview_switch_group_changed)
        self.preview_switch_name_combo.currentIndexChanged.connect(self._handle_preview_switch_value_changed)
        self.import_template_bus_combo.currentIndexChanged.connect(self._update_event_import_template_defaults_from_controls)
        self.import_template_asset_prefix_edit.editingFinished.connect(self._update_event_import_template_defaults_from_controls)
        self.import_template_tags_edit.editingFinished.connect(self._update_event_import_template_defaults_from_controls)
        self.export_root_browse_button.clicked.connect(self._request_export_root_browse)
        self.export_root_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.volume_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.volume_rand_min_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.volume_rand_max_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.pitch_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.pitch_rand_min_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.pitch_rand_max_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.cooldown_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.max_instances_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.max_instances_spin.valueChanged.connect(self._sync_event_mode_ui)
        self.combo_pitch_step_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.combo_reset_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.combo_max_step_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.avoid_repeat_check.checkStateChanged.connect(self._emit_audio_properties_changed)
        self.notes_edit.textChanged.connect(self._emit_event_properties_changed)
        self.tags_summary_edit.editingFinished.connect(self._emit_audio_properties_changed)
        self.event_rtpc_list.itemSelectionChanged.connect(lambda: self._load_event_binding_editor("rtpc"))
        self.event_rtpc_add_button.clicked.connect(lambda: self._create_event_binding("rtpc"))
        self.event_rtpc_remove_button.clicked.connect(lambda: self._remove_event_binding("rtpc"))
        self.event_rtpc_parameter_edit.currentIndexChanged.connect(self._handle_event_rtpc_curve_context_changed)
        self.event_rtpc_target_combo.currentIndexChanged.connect(self._handle_event_rtpc_curve_context_changed)
        self.event_rtpc_scope_combo.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.event_rtpc_curve_table.pointsChanged.connect(self._emit_audio_properties_changed)
        self.event_rtpc_curve_table.selectionChanged.connect(lambda _index: self._sync_curve_interpolation_combo(self.event_rtpc_curve_table, self.event_rtpc_interpolation_combo))
        self.event_rtpc_curve_table.selectionChanged.connect(lambda _index: self._sync_curve_point_controls(self.event_rtpc_curve_table, self.event_rtpc_selected_input_spin, self.event_rtpc_selected_output_spin))
        self.event_rtpc_curve_table.pointPreviewChanged.connect(lambda: self._sync_curve_point_controls(self.event_rtpc_curve_table, self.event_rtpc_selected_input_spin, self.event_rtpc_selected_output_spin))
        self.event_rtpc_interpolation_combo.currentIndexChanged.connect(lambda: self._update_curve_interpolation(self.event_rtpc_curve_table, self.event_rtpc_interpolation_combo, self._emit_audio_properties_changed))
        self.event_rtpc_add_point_button.clicked.connect(lambda: self._append_curve_point(self.event_rtpc_curve_table, self._emit_audio_properties_changed))
        self.event_rtpc_remove_point_button.clicked.connect(lambda: self._remove_curve_point(self.event_rtpc_curve_table, self._emit_audio_properties_changed))
        self.event_rtpc_selected_input_spin.valueChanged.connect(lambda _value: self._update_curve_point_from_controls(self.event_rtpc_curve_table, self.event_rtpc_selected_input_spin, self.event_rtpc_selected_output_spin))
        self.event_rtpc_selected_output_spin.valueChanged.connect(lambda _value: self._update_curve_point_from_controls(self.event_rtpc_curve_table, self.event_rtpc_selected_input_spin, self.event_rtpc_selected_output_spin))
        self.event_rtpc_snap_check.checkStateChanged.connect(lambda _state: self._apply_curve_snap_settings(self.event_rtpc_curve_table, self.event_rtpc_snap_check, self.event_rtpc_snap_x_spin, self.event_rtpc_snap_y_spin))
        self.event_rtpc_snap_x_spin.valueChanged.connect(lambda _value: self._apply_curve_snap_settings(self.event_rtpc_curve_table, self.event_rtpc_snap_check, self.event_rtpc_snap_x_spin, self.event_rtpc_snap_y_spin))
        self.event_rtpc_snap_y_spin.valueChanged.connect(lambda _value: self._apply_curve_snap_settings(self.event_rtpc_curve_table, self.event_rtpc_snap_check, self.event_rtpc_snap_x_spin, self.event_rtpc_snap_y_spin))
        self.event_rtpc_notes_edit.textChanged.connect(self._emit_audio_properties_changed)
        self.event_state_list.itemSelectionChanged.connect(lambda: self._load_event_binding_editor("state"))
        self.event_state_add_button.clicked.connect(lambda: self._create_event_binding("state"))
        self.event_state_remove_button.clicked.connect(lambda: self._remove_event_binding("state"))
        self.event_state_group_edit.currentIndexChanged.connect(lambda: self._refresh_event_state_name_options())
        self.event_state_group_edit.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.event_state_name_edit.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.event_state_volume_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.event_state_pitch_spin.valueChanged.connect(self._emit_audio_properties_changed)
        self.event_state_mute_check.checkStateChanged.connect(self._emit_audio_properties_changed)
        self.event_state_notes_edit.textChanged.connect(self._emit_audio_properties_changed)
        self.event_switch_list.itemSelectionChanged.connect(lambda: self._load_event_binding_editor("switch"))
        self.event_switch_add_button.clicked.connect(lambda: self._create_event_binding("switch"))
        self.event_switch_remove_button.clicked.connect(lambda: self._remove_event_binding("switch"))
        self.event_switch_group_edit.currentIndexChanged.connect(lambda: self._refresh_event_switch_name_options())
        self.event_switch_group_edit.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.event_switch_name_edit.currentIndexChanged.connect(self._emit_audio_properties_changed)
        self.event_switch_clip_ids_edit.editingFinished.connect(self._emit_audio_properties_changed)
        self.event_switch_notes_edit.textChanged.connect(self._emit_audio_properties_changed)
        self.clip_source_detail_edit.editingFinished.connect(lambda: self._emit_selected_clip_detail_change("source_path", self.clip_source_detail_edit.text()))
        self.clip_asset_detail_edit.editingFinished.connect(lambda: self._emit_selected_clip_detail_change("asset_key", self.clip_asset_detail_edit.text()))
        self.clip_weight_detail_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("weight", str(value)))
        self.clip_weight_detail_spin.valueChanged.connect(lambda value: self._sync_weight_preset_combo(self.clip_weight_preset_combo, value))
        self.clip_weight_preset_combo.currentIndexChanged.connect(lambda: self._apply_weight_preset(self.clip_weight_detail_spin, self.clip_weight_preset_combo))
        self.clip_trim_start_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("trim_start_ms", value))
        self.clip_trim_end_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("trim_end_ms", value))
        self.clip_fade_in_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("fade_in_ms", value))
        self.clip_fade_out_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("fade_out_ms", value))
        self.clip_loop_start_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("loop_start_ms", value))
        self.clip_loop_end_spin.valueChanged.connect(lambda value: self._handle_clip_timing_spin_change("loop_end_ms", value))
        self.clip_waveform_editor.selectionChanged.connect(self._handle_clip_waveform_change)
        self.clip_waveform_editor.loopChanged.connect(self._handle_clip_waveform_loop_change)
        self.clip_waveform_editor.playheadChanged.connect(self._handle_clip_waveform_playhead_change)
        self.clip_waveform_zoom_out_button.clicked.connect(self.clip_waveform_editor.zoom_out)
        self.clip_waveform_zoom_reset_button.clicked.connect(self.clip_waveform_editor.reset_view)
        self.clip_waveform_frame_selection_button.clicked.connect(self.clip_waveform_editor.frame_selection)
        self.clip_waveform_zoom_in_button.clicked.connect(self.clip_waveform_editor.zoom_in)
        self.clip_set_start_from_playhead_button.clicked.connect(self._set_clip_trim_start_from_playhead)
        self.clip_set_end_from_playhead_button.clicked.connect(self._set_clip_trim_end_from_playhead)
        self.clip_set_loop_from_selection_button.clicked.connect(self._set_clip_loop_from_selection)
        self.clip_clear_loop_button.clicked.connect(self._clear_clip_loop)
        self.clip_tags_detail_edit.editingFinished.connect(lambda: self._emit_selected_clip_detail_change("tags", self.clip_tags_detail_edit.text()))
        self.bulk_clip_weight_spin.valueChanged.connect(lambda value: self._sync_weight_preset_combo(self.bulk_weight_preset_combo, value))
        self.bulk_weight_preset_combo.currentIndexChanged.connect(lambda: self._apply_weight_preset(self.bulk_clip_weight_spin, self.bulk_weight_preset_combo))

        self.new_folder_button.clicked.connect(self.createFolderRequested.emit)
        self.save_as_project_button.clicked.connect(self.saveProjectAsRequested.emit)
        self.open_recent_project_button.clicked.connect(self._request_open_recent_project)
        self.new_event_button.clicked.connect(self.createEventRequested.emit)
        self.rename_button.clicked.connect(self.renameSelectedRequested.emit)
        self.delete_button.clicked.connect(self.deleteSelectedRequested.emit)
        self.bulk_event_bus_button.clicked.connect(self._request_bulk_event_bus)
        self.undo_button.clicked.connect(self.undoRequested.emit)
        self.redo_button.clicked.connect(self.redoRequested.emit)
        self.preview_button.clicked.connect(self.previewRequested.emit)
        self.stop_preview_event_button.clicked.connect(self.stopPreviewEventRequested.emit)
        self.stop_preview_bus_button.clicked.connect(self.stopPreviewBusRequested.emit)
        self.import_clips_button.clicked.connect(self._request_clip_import)
        self.remove_clips_button.clicked.connect(self._request_remove_clips)
        self.bulk_weight_button.clicked.connect(self._request_bulk_weight)
        self.batch_rename_button.clicked.connect(self._request_batch_rename)
        self.apply_bulk_clip_button.clicked.connect(self._request_bulk_clip_properties)
        self.sort_clips_button.clicked.connect(self._request_sort_clips)
        self.preview_export_diff_button.clicked.connect(self.previewExportDiffRequested.emit)
        self.apply_default_bus_button.clicked.connect(self.applyDefaultBusToAllRequested.emit)
        self.clip_table.filesDropped.connect(self.importClipsRequested.emit)
        self.clip_table.clipEdited.connect(self.clipEdited.emit)
        self.clip_table.rowsReordered.connect(self.reorderClipsRequested.emit)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_context_menu)
        self.source_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.source_tree.customContextMenuRequested.connect(self._show_source_tree_context_menu)
        self.audio_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.audio_tree.customContextMenuRequested.connect(self._show_audio_tree_context_menu)
        self.source_tree.sourceSelected.connect(lambda _source_path: self._update_source_browser_status())
        self.source_tree.sourceActivated.connect(lambda _source_path: self._locate_selected_source_asset())
        self.source_tree.itemDoubleClicked.connect(lambda _item, _column: self._handle_open_shortcut())
        self.audio_tree.audioSelected.connect(lambda _audio_id: self._update_audio_browser_status())
        self.audio_tree.audioActivated.connect(lambda _audio_id: self._open_selected_audio_bindings())
        self.clip_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.clip_table.customContextMenuRequested.connect(self._show_clip_context_menu)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._handle_open_shortcut())
        self.clip_table.itemDoubleClicked.connect(lambda item: self._handle_open_shortcut())
        self.validation_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.validation_issue_list, self.validation_report_output))
        self.validation_issue_list.itemSelectionChanged.connect(self._sync_validation_issue_actions)
        self.build_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.build_issue_list, self.build_report_output))
        self.loudness_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.loudness_issue_list, self.loudness_report_output))
        self.diagnostic_section_list.itemSelectionChanged.connect(
            lambda: self._update_report_detail_from_item(self.diagnostic_section_list, self.diagnostic_section_detail_output)
        )
        self.build_profile_list.itemSelectionChanged.connect(
            lambda: self._update_report_detail_from_item(self.build_profile_list, self.build_profile_detail_output)
        )
        self.validation_issue_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.validation_issue_list))
        self.loudness_issue_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.loudness_issue_list))
        self.diagnostic_section_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.diagnostic_section_list))
        self.build_profile_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.build_profile_list))
        self.explorer_tabs.currentChanged.connect(lambda _index: self._sync_explorer_browser_state())
        self.tree_filter_edit.textChanged.connect(self._apply_explorer_filter)
        self.tree_filter_edit.returnPressed.connect(self._advance_explorer_search)
        self.tree_search_button.clicked.connect(self._advance_explorer_search)
        self.clip_filter_edit.textChanged.connect(self._apply_clip_filter)
        self.recent_projects_list.itemDoubleClicked.connect(lambda item: self.openRecentProjectRequested.emit(item.text()))

    def _emit_event_properties_changed(self, *args) -> None:
        if not self._loading_event and self.property_group.isEnabled():
            self._sync_event_binding_editor_to_state("rtpc")
            self._sync_event_binding_editor_to_state("state")
            self._sync_event_binding_editor_to_state("switch")
            self.eventPropertiesChanged.emit()

    def _emit_audio_properties_changed(self, *args) -> None:
        if not self._loading_event and self.property_group.isEnabled():
            self._sync_event_binding_editor_to_state("rtpc")
            self._sync_event_binding_editor_to_state("state")
            self._sync_event_binding_editor_to_state("switch")
            self.audioPropertiesChanged.emit()

    def _emit_project_settings_changed(self, *args) -> None:
        sender = self.sender()
        if sender is self.export_root_edit and not self.export_root_edit.isModified():
            return
        if self._loading_project_bus_details:
            return
        if not self._loading_event and self._sync_project_bus_editor_to_state(show_errors=True):
            if sender is self.export_root_edit:
                self.export_root_edit.setModified(False)
            change_source = "project-settings-form"
            if sender is self.export_root_edit:
                change_source = "export-root"
            elif sender is self.source_audio_format_combo:
                change_source = "source-audio-format"
            elif sender is self.runtime_audio_format_combo:
                change_source = "runtime-audio-format"
            elif sender is self.default_bus_combo:
                change_source = "default-bus"
            elif sender is self.auto_assign_bus_by_name_check:
                change_source = "auto-assign-bus"
            self._queue_project_settings_changed(change_source)

    def _queue_project_settings_changed(self, source: str) -> None:
        self._project_settings_change_source = source
        self.projectSettingsChanged.emit()

    def consume_project_settings_change_source(self) -> str:
        source = self._project_settings_change_source
        self._project_settings_change_source = ""
        return source

    def _emit_gamesync_changed(self, *args) -> None:
        if not self._loading_gamesync:
            current_key = {
                1: "game_parameters",
                2: "state_groups",
                3: "switch_groups",
            }.get(self.gamesync_workspace_tabs.currentIndex())
            if current_key is not None:
                self._sync_gamesync_editor_to_state(current_key)
            self.gameSyncChanged.emit()

    def _emit_preview_bus_state_changed(self, *args) -> None:
        if not self._loading_event:
            self.previewBusStateChanged.emit()

    def _request_clip_import(self) -> None:
        file_paths = self.ask_import_clip_paths()
        if file_paths:
            self.importClipsRequested.emit(file_paths)

    def _request_selected_clip_preview(self) -> None:
        clip_ids = self.selected_clip_ids()
        if clip_ids:
            self.previewClipRequested.emit(clip_ids[0])

    def _copy_selected_clip_ids(self) -> None:
        clip_ids = self.selected_clip_ids()
        if not clip_ids:
            return
        QApplication.clipboard().setText("\n".join(clip_ids))
        self.report_detail_label.setText(f"已复制 {len(clip_ids)} 个片段 ID。")
        self.report_detail_label.setToolTip("\n".join(clip_ids[:12]))

    def _copy_selected_clip_asset_keys(self) -> None:
        clip_ids = self.selected_clip_ids()
        if not clip_ids:
            return
        asset_keys: list[str] = []
        for row in sorted({index.row() for index in self.clip_table.selectedIndexes()}):
            item = self.clip_table.item(row, 2)
            if item is not None and item.text().strip():
                asset_keys.append(item.text().strip())
        if not asset_keys:
            return
        QApplication.clipboard().setText("\n".join(asset_keys))
        self.report_detail_label.setText(f"已复制 {len(asset_keys)} 个资源键到剪贴板。")
        self.report_detail_label.setToolTip("\n".join(asset_keys[:12]))

    def _locate_selected_clip_source(self) -> None:
        clip_ids = self.selected_clip_ids()
        if not clip_ids:
            return
        source_path = ""
        for row in sorted({index.row() for index in self.clip_table.selectedIndexes()}):
            item = self.clip_table.item(row, 1)
            if item is not None and item.text().strip():
                source_path = item.text().strip()
                break
        if not source_path:
            self.report_detail_label.setText("当前片段没有可定位的源文件。")
            return
        if os.path.exists(source_path):
            os.startfile(source_path)
            self.report_detail_label.setText(f"已定位源文件：{source_path}")
        else:
            self.report_detail_label.setText(f"源文件不存在：{source_path}")

    def set_source_browser_entries(self, entries: list[dict[str, object]]) -> None:
        self._source_browser_entries = list(entries)
        self._refresh_source_browser_tree()
        self._refresh_event_source_binding_state()

    def _normalized_name_list_from_text(self, text: str) -> list[str]:
        seen: set[str] = set()
        values: list[str] = []
        for raw_value in text.split(","):
            value = raw_value.strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(value)
        return values

    def _default_curve_point_payloads(self, input_range: tuple[float, float] = (0.0, 100.0), output_range: tuple[float, float] = (0.0, 1.0)) -> list[dict[str, object]]:
        input_min, input_max = input_range
        output_min, output_max = output_range
        return [
            {"input_value": float(input_min), "output_value": float(output_min), "interpolation": "Linear"},
            {"input_value": float(input_max), "output_value": float(output_max), "interpolation": "Linear"},
        ]

    def _rtpc_input_range(self, parameter_name: str) -> tuple[float, float]:
        normalized = parameter_name.strip().casefold()
        for entry in self._gamesync_models.get("game_parameters", []):
            if str(entry.get("name", "")).strip().casefold() == normalized:
                return float(entry.get("min_value", 0.0)), float(entry.get("max_value", 100.0))
        return 0.0, 100.0

    def _rtpc_output_range(self, target: str) -> tuple[float, float]:
        if target == "EventPitchCents":
            return float(MIN_PITCH_CENTS), float(MAX_PITCH_CENTS)
        return float(MIN_VOLUME_DB), float(MAX_VOLUME_DB)

    def _configure_curve_editor_ranges(
        self,
        table: RtpcCurveEditor,
        input_spin: QDoubleSpinBox,
        output_spin: QDoubleSpinBox,
        *,
        parameter_name: str,
        target: str,
    ) -> None:
        input_min, input_max = self._rtpc_input_range(parameter_name)
        output_min, output_max = self._rtpc_output_range(target)
        table.set_axis_ranges(input_min, input_max, output_min, output_max)
        input_spin.blockSignals(True)
        output_spin.blockSignals(True)
        input_spin.setRange(input_min, input_max)
        output_spin.setRange(output_min, output_max)
        input_spin.blockSignals(False)
        output_spin.blockSignals(False)

    def _refresh_event_rtpc_curve_editor_ranges(self) -> None:
        self._configure_curve_editor_ranges(
            self.event_rtpc_curve_table,
            self.event_rtpc_selected_input_spin,
            self.event_rtpc_selected_output_spin,
            parameter_name=self.event_rtpc_parameter_edit.currentText(),
            target=self.event_rtpc_target_combo.currentText(),
        )

    def _refresh_bus_rtpc_curve_editor_ranges(self) -> None:
        self._configure_curve_editor_ranges(
            self.bus_rtpc_curve_table,
            self.bus_rtpc_selected_input_spin,
            self.bus_rtpc_selected_output_spin,
            parameter_name=self.bus_rtpc_parameter_edit.text(),
            target=self.bus_rtpc_target_combo.currentText(),
        )

    def _copy_curve_point_payloads(self, points: list[dict[str, object]] | None) -> list[dict[str, object]]:
        normalized = [
            {
                "input_value": float(point.get("input_value", 0.0)),
                "output_value": float(point.get("output_value", 0.0)),
                "interpolation": "Constant" if str(point.get("interpolation", "Linear")) == "Constant" else "Linear",
            }
            for point in (points or [])
            if isinstance(point, dict)
        ]
        if not normalized:
            normalized = self._default_curve_point_payloads()
        normalized.sort(key=lambda point: float(point["input_value"]))
        return normalized

    def _set_curve_table_points(self, table: RtpcCurveEditor, points: list[dict[str, object]] | None) -> None:
        table.blockSignals(True)
        table.set_points(self._copy_curve_point_payloads(points))
        table.blockSignals(False)

    def _curve_table_points(self, table: RtpcCurveEditor) -> list[dict[str, object]]:
        return self._copy_curve_point_payloads(table.points())

    def _append_curve_point(self, table: RtpcCurveEditor, change_handler) -> None:
        table.append_point()

    def _remove_curve_point(self, table: RtpcCurveEditor, change_handler) -> None:
        table.remove_selected_point()

    def _sync_curve_interpolation_combo(self, table: RtpcCurveEditor, combo: QComboBox) -> None:
        combo.blockSignals(True)
        combo.setEnabled(table.selected_index() >= 0)
        combo.setCurrentText(table.selected_interpolation())
        combo.blockSignals(False)

    def _update_curve_interpolation(self, table: RtpcCurveEditor, combo: QComboBox, change_handler) -> None:
        if table.selected_index() < 0:
            return
        table.set_selected_interpolation(combo.currentText())

    def _sync_curve_point_controls(self, table: RtpcCurveEditor, input_spin: QDoubleSpinBox, output_spin: QDoubleSpinBox) -> None:
        point = table.selected_point()
        has_selection = point is not None
        input_spin.blockSignals(True)
        output_spin.blockSignals(True)
        input_spin.setEnabled(has_selection)
        output_spin.setEnabled(has_selection)
        if has_selection:
            input_spin.setValue(float(point.get("input_value", 0.0)))
            output_spin.setValue(float(point.get("output_value", 0.0)))
        else:
            input_spin.setValue(0.0)
            output_spin.setValue(0.0)
        input_spin.blockSignals(False)
        output_spin.blockSignals(False)

    def _update_curve_point_from_controls(self, table: RtpcCurveEditor, input_spin: QDoubleSpinBox, output_spin: QDoubleSpinBox) -> None:
        if table.selected_point() is None:
            return
        table.update_selected_point(
            input_value=float(input_spin.value()),
            output_value=float(output_spin.value()),
        )

    def _apply_curve_snap_settings(
        self,
        table: RtpcCurveEditor,
        snap_check: QCheckBox,
        snap_x_spin: QDoubleSpinBox,
        snap_y_spin: QDoubleSpinBox,
    ) -> None:
        table.set_snap_settings(
            snap_check.isChecked(),
            float(snap_x_spin.value()),
            float(snap_y_spin.value()),
        )

    def _game_parameter_payload(self, parameter: GameParameterModel | dict[str, object]) -> dict[str, object]:
        if isinstance(parameter, GameParameterModel):
            return {
                "name": parameter.name,
                "default_value": float(parameter.default_value),
                "min_value": float(parameter.min_value),
                "max_value": float(parameter.max_value),
                "notes": parameter.notes,
            }
        return {
            "name": str(parameter.get("name", "")).strip(),
            "default_value": float(parameter.get("default_value", 0.0)),
            "min_value": float(parameter.get("min_value", 0.0)),
            "max_value": float(parameter.get("max_value", 100.0)),
            "notes": str(parameter.get("notes", "")),
        }

    def _gamesync_child_effect_payload(self, payload: dict[str, object] | object) -> dict[str, object]:
        if isinstance(payload, dict):
            return {
                "volume_db": float(payload.get("volume_db", 0.0)),
                "pitch_cents": int(payload.get("pitch_cents", 0)),
                "is_muted": bool(payload.get("is_muted", False)),
                "notes": str(payload.get("notes", "")),
            }
        return {
            "volume_db": float(getattr(payload, "volume_db", 0.0)),
            "pitch_cents": int(getattr(payload, "pitch_cents", 0)),
            "is_muted": bool(getattr(payload, "is_muted", False)),
            "notes": str(getattr(payload, "notes", "")),
        }

    def _normalized_gamesync_child_effects(self, effects: dict[str, object] | None) -> dict[str, dict[str, object]]:
        normalized: dict[str, dict[str, object]] = {}
        for raw_name, raw_payload in (effects or {}).items():
            name = str(raw_name).strip()
            if not name:
                continue
            normalized[name] = self._gamesync_child_effect_payload(raw_payload)
        return normalized

    def _state_group_payload(self, group: StateGroupModel | dict[str, object]) -> dict[str, object]:
        if isinstance(group, StateGroupModel):
            return {
                "name": group.name,
                "states": list(group.states),
                "default_state": group.default_state,
                "state_effects": self._normalized_gamesync_child_effects(group.state_effects),
                "notes": group.notes,
            }
        return {
            "name": str(group.get("name", "")).strip(),
            "states": self._normalized_name_list_from_text(", ".join(str(value) for value in group.get("states", []))),
            "default_state": str(group.get("default_state", "")).strip(),
            "state_effects": self._normalized_gamesync_child_effects(group.get("state_effects", {})),
            "notes": str(group.get("notes", "")),
        }

    def _switch_group_payload(self, group: SwitchGroupModel | dict[str, object]) -> dict[str, object]:
        if isinstance(group, SwitchGroupModel):
            return {
                "name": group.name,
                "switches": list(group.switches),
                "default_switch": group.default_switch,
                "use_game_parameter": bool(group.use_game_parameter),
                "mapped_game_parameter": group.mapped_game_parameter,
                "switch_effects": self._normalized_gamesync_child_effects(group.switch_effects),
                "notes": group.notes,
            }
        return {
            "name": str(group.get("name", "")).strip(),
            "switches": self._normalized_name_list_from_text(", ".join(str(value) for value in group.get("switches", []))),
            "default_switch": str(group.get("default_switch", "")).strip(),
            "use_game_parameter": bool(group.get("use_game_parameter", False)),
            "mapped_game_parameter": str(group.get("mapped_game_parameter", "")).strip(),
            "switch_effects": self._normalized_gamesync_child_effects(group.get("switch_effects", {})),
            "notes": str(group.get("notes", "")),
        }

    def _refresh_gamesync_entries_from_models(self) -> None:
        self._gamesync_entries = {
            "game_parameters": [
                {
                    "name": str(entry.get("name", "")).strip(),
                    "summary": (
                        f"默认 {float(entry.get('default_value', 0.0)):.2f} | 范围 {float(entry.get('min_value', 0.0)):.2f} - {float(entry.get('max_value', 100.0)):.2f}"
                    ),
                    "detail": str(entry.get("notes", "")).strip() or "连续 Game Parameter，可用于 RTPC authoring。",
                }
                for entry in self._gamesync_models["game_parameters"]
            ],
            "state_groups": [
                {
                    "name": str(entry.get("name", "")).strip(),
                    "summary": f"默认 {str(entry.get('default_state', '')).strip() or '-'} | 状态 {len(entry.get('states', []))} 个",
                    "detail": str(entry.get("notes", "")).strip() or ("、".join(entry.get("states", [])) if entry.get("states", []) else "当前还没有可用 State。"),
                }
                for entry in self._gamesync_models["state_groups"]
            ],
            "switch_groups": [
                {
                    "name": str(entry.get("name", "")).strip(),
                    "summary": (
                        f"默认 {str(entry.get('default_switch', '')).strip() or '-'} | Switch {len(entry.get('switches', []))} 个"
                        + (
                            f" | RTPC 映射 {str(entry.get('mapped_game_parameter', '')).strip()}"
                            if bool(entry.get("use_game_parameter", False)) and str(entry.get("mapped_game_parameter", "")).strip()
                            else ""
                        )
                    ),
                    "detail": str(entry.get("notes", "")).strip() or ("、".join(entry.get("switches", [])) if entry.get("switches", []) else "当前还没有可用 Switch。"),
                }
                for entry in self._gamesync_models["switch_groups"]
            ],
        }

    def set_gamesync_definitions(
        self,
        game_parameters: list[GameParameterModel],
        state_groups: list[StateGroupModel],
        switch_groups: list[SwitchGroupModel],
    ) -> None:
        self._loading_gamesync = True
        self._gamesync_models = {
            "game_parameters": [self._game_parameter_payload(parameter) for parameter in game_parameters],
            "state_groups": [self._state_group_payload(group) for group in state_groups],
            "switch_groups": [self._switch_group_payload(group) for group in switch_groups],
        }
        self._preview_gamesync_definitions = {
            "game_parameters": [dict(entry) for entry in self._gamesync_models["game_parameters"]],
            "state_groups": [dict(entry) for entry in self._gamesync_models["state_groups"]],
            "switch_groups": [dict(entry) for entry in self._gamesync_models["switch_groups"]],
        }
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        self._refresh_event_binding_option_sets()
        self._load_preview_gamesync_editor()
        self._load_gamesync_editor("game_parameters")
        self._load_gamesync_editor("state_groups")
        self._load_gamesync_editor("switch_groups")
        self._loading_gamesync = False

    def _set_combo_box_values(self, combo: QComboBox, values: list[str], current_value: str = "") -> None:
        seen: set[str] = set()
        candidates = [*values, current_value.strip()] if current_value.strip() else list(values)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        for raw_value in candidates:
            value = str(raw_value).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            combo.addItem(value)
        if current_value.strip() and current_value.strip().casefold() in seen:
            combo.setCurrentText(current_value.strip())
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _available_game_parameter_names(self) -> list[str]:
        return [
            str(entry.get("name", "")).strip()
            for entry in self._gamesync_models.get("game_parameters", [])
            if str(entry.get("name", "")).strip()
        ]

    def _available_state_group_names(self) -> list[str]:
        return [
            str(entry.get("name", "")).strip()
            for entry in self._gamesync_models.get("state_groups", [])
            if str(entry.get("name", "")).strip()
        ]

    def _available_states_for_group(self, group_name: str) -> list[str]:
        normalized = group_name.strip().casefold()
        for entry in self._gamesync_models.get("state_groups", []):
            if str(entry.get("name", "")).strip().casefold() == normalized:
                return [str(value).strip() for value in entry.get("states", []) if str(value).strip()]
        return []

    def _available_switch_group_names(self) -> list[str]:
        return [
            str(entry.get("name", "")).strip()
            for entry in self._gamesync_models.get("switch_groups", [])
            if str(entry.get("name", "")).strip()
        ]

    def _available_switches_for_group(self, group_name: str) -> list[str]:
        normalized = group_name.strip().casefold()
        for entry in self._gamesync_models.get("switch_groups", []):
            if str(entry.get("name", "")).strip().casefold() == normalized:
                return [str(value).strip() for value in entry.get("switches", []) if str(value).strip()]
        return []

    def _refresh_event_state_name_options(self, current_value: str | None = None) -> None:
        selected_group = self.event_state_group_edit.currentText().strip()
        current_state = self.event_state_name_edit.currentText().strip() if current_value is None else current_value.strip()
        self._set_combo_box_values(self.event_state_name_edit, self._available_states_for_group(selected_group), current_state)

    def _refresh_event_switch_name_options(self, current_value: str | None = None) -> None:
        selected_group = self.event_switch_group_edit.currentText().strip()
        current_switch = self.event_switch_name_edit.currentText().strip() if current_value is None else current_value.strip()
        self._set_combo_box_values(self.event_switch_name_edit, self._available_switches_for_group(selected_group), current_switch)

    def _refresh_event_binding_option_sets(self) -> None:
        self._set_combo_box_values(self.event_rtpc_parameter_edit, self._available_game_parameter_names(), self.event_rtpc_parameter_edit.currentText())
        self._set_combo_box_values(self.event_state_group_edit, self._available_state_group_names(), self.event_state_group_edit.currentText())
        self._refresh_event_state_name_options()
        self._set_combo_box_values(self.event_switch_group_edit, self._available_switch_group_names(), self.event_switch_group_edit.currentText())
        self._refresh_event_switch_name_options()

    def _default_event_rtpc_binding_payload(self) -> dict[str, object]:
        payload = self._rtpc_binding_payload({})
        parameter_names = self._available_game_parameter_names()
        if parameter_names:
            payload["parameter_name"] = parameter_names[0]
        payload["curve_points"] = self._default_curve_point_payloads(
            self._rtpc_input_range(str(payload.get("parameter_name", ""))),
            self._rtpc_output_range(str(payload.get("target", "EventVolumeDb"))),
        )
        return payload

    def _default_bus_rtpc_binding_payload(self) -> dict[str, object]:
        payload = self._rtpc_binding_payload({"target": "BusVolumeDb"})
        payload["curve_points"] = self._default_curve_point_payloads(
            self._rtpc_input_range(str(payload.get("parameter_name", ""))),
            self._rtpc_output_range("BusVolumeDb"),
        )
        return payload

    def _handle_event_rtpc_curve_context_changed(self) -> None:
        self._refresh_event_rtpc_curve_editor_ranges()
        self._emit_event_properties_changed()

    def _handle_bus_rtpc_curve_context_changed(self) -> None:
        self._refresh_bus_rtpc_curve_editor_ranges()
        self._emit_project_settings_changed()

    def _default_event_state_override_payload(self) -> dict[str, object]:
        payload = self._state_override_payload({})
        group_names = self._available_state_group_names()
        if group_names:
            payload["group_name"] = group_names[0]
            states = self._available_states_for_group(group_names[0])
            if states:
                payload["state_name"] = states[0]
        return payload

    def _default_event_switch_variant_payload(self) -> dict[str, object]:
        payload = self._switch_variant_payload({})
        group_names = self._available_switch_group_names()
        if group_names:
            payload["group_name"] = group_names[0]
            switches = self._available_switches_for_group(group_names[0])
            if switches:
                payload["switch_name"] = switches[0]
        return payload

    def set_preview_gamesync_enabled(self, enabled: bool) -> None:
        has_definitions = any(self._preview_gamesync_definitions.values())
        is_enabled = bool(enabled and has_definitions)
        self.preview_gamesync_group.setEnabled(is_enabled)
        self.preview_parameter_slider.setEnabled(is_enabled and bool(self.preview_parameter_name_combo.currentText().strip()))

    def _preview_definition_names(self, key: str) -> list[str]:
        return [
            str(entry.get("name", "")).strip()
            for entry in self._preview_gamesync_definitions.get(key, [])
            if str(entry.get("name", "")).strip()
        ]

    def _preview_group_entry(self, key: str, name: str) -> dict[str, object] | None:
        normalized = name.strip().casefold()
        for entry in self._preview_gamesync_definitions.get(key, []):
            if str(entry.get("name", "")).strip().casefold() == normalized:
                return entry
        return None

    def _default_preview_parameter_name(self) -> str:
        names = self._preview_definition_names("game_parameters")
        return names[0] if names else ""

    def _default_preview_state_group_name(self) -> str:
        names = self._preview_definition_names("state_groups")
        return names[0] if names else ""

    def _default_preview_switch_group_name(self) -> str:
        names = self._preview_definition_names("switch_groups")
        return names[0] if names else ""

    def _preview_states_for_group(self, group_name: str) -> list[str]:
        entry = self._preview_group_entry("state_groups", group_name)
        if entry is None:
            return []
        return [str(value).strip() for value in entry.get("states", []) if str(value).strip()]

    def _preview_switches_for_group(self, group_name: str) -> list[str]:
        entry = self._preview_group_entry("switch_groups", group_name)
        if entry is None:
            return []
        return [str(value).strip() for value in entry.get("switches", []) if str(value).strip()]

    def _preview_parameter_default_value(self, parameter_name: str) -> float:
        entry = self._preview_group_entry("game_parameters", parameter_name)
        return float(entry.get("default_value", 0.0)) if entry is not None else 0.0

    def _preview_parameter_limits(self, parameter_name: str) -> tuple[float, float]:
        entry = self._preview_group_entry("game_parameters", parameter_name)
        if entry is None:
            return -99999.0, 99999.0
        return float(entry.get("min_value", -99999.0)), float(entry.get("max_value", 99999.0))

    def _preview_parameter_slider_steps(self) -> int:
        return max(1, int(self.preview_parameter_slider.maximum() - self.preview_parameter_slider.minimum()))

    def _format_preview_parameter_value_text(self, value: float) -> str:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text if text not in {"", "-0"} else "0"

    def _preview_parameter_slider_value(self, parameter_name: str, value: float) -> int:
        minimum, maximum = self._preview_parameter_limits(parameter_name)
        slider_minimum = int(self.preview_parameter_slider.minimum())
        slider_maximum = int(self.preview_parameter_slider.maximum())
        if maximum <= minimum:
            return slider_minimum
        normalized = (float(value) - minimum) / (maximum - minimum)
        normalized = min(max(normalized, 0.0), 1.0)
        return slider_minimum + int(round(normalized * (slider_maximum - slider_minimum)))

    def _preview_parameter_value_from_slider(self, parameter_name: str, slider_value: int) -> float:
        minimum, maximum = self._preview_parameter_limits(parameter_name)
        slider_minimum = int(self.preview_parameter_slider.minimum())
        slider_maximum = int(self.preview_parameter_slider.maximum())
        if slider_maximum <= slider_minimum or maximum <= minimum:
            return minimum
        normalized = (int(slider_value) - slider_minimum) / float(slider_maximum - slider_minimum)
        value = minimum + normalized * (maximum - minimum)
        return min(max(value, minimum), maximum)

    def _update_preview_parameter_transport_labels(self, parameter_name: str, value: float) -> None:
        minimum, maximum = self._preview_parameter_limits(parameter_name)
        has_parameter = bool(parameter_name)
        self.preview_parameter_min_label.setText(self._format_preview_parameter_value_text(minimum) if has_parameter else "-")
        self.preview_parameter_max_label.setText(self._format_preview_parameter_value_text(maximum) if has_parameter else "-")
        self.preview_parameter_current_label.setText(self._format_preview_parameter_value_text(value) if has_parameter else "RTPC -")

    def _sync_preview_parameter_transport_value(self, parameter_name: str, value: float) -> None:
        self._update_preview_parameter_transport_labels(parameter_name, value)
        self.preview_parameter_slider.blockSignals(True)
        self.preview_parameter_slider.setValue(self._preview_parameter_slider_value(parameter_name, value))
        self.preview_parameter_slider.blockSignals(False)

    def _preview_default_state_name(self, group_name: str) -> str:
        entry = self._preview_group_entry("state_groups", group_name)
        if entry is None:
            return ""
        default_state = str(entry.get("default_state", "")).strip()
        if default_state:
            return default_state
        states = self._preview_states_for_group(group_name)
        return states[0] if states else ""

    def _preview_default_switch_name(self, group_name: str) -> str:
        entry = self._preview_group_entry("switch_groups", group_name)
        if entry is None:
            return ""
        default_switch = str(entry.get("default_switch", "")).strip()
        if default_switch:
            return default_switch
        switches = self._preview_switches_for_group(group_name)
        return switches[0] if switches else ""

    def _preview_parameter_values(self, scope: str) -> dict[str, float]:
        key = "emitter_parameters" if scope == "Emitter" else "global_parameters"
        values = self._preview_gamesync_state.get(key, {})
        if not isinstance(values, dict):
            values = {}
            self._preview_gamesync_state[key] = values
        return values

    def _preview_selected_parameter_name(self) -> str:
        selected = str(self._preview_gamesync_state.get("selected_parameter_name", "")).strip()
        names = self._preview_definition_names("game_parameters")
        if selected in names:
            return selected
        return self._default_preview_parameter_name()

    def _preview_selected_parameter_scope(self) -> str:
        selected = str(self._preview_gamesync_state.get("selected_parameter_scope", "Emitter")).strip()
        return selected if selected in {"Global", "Emitter"} else "Emitter"

    def _preview_selected_state_group(self) -> str:
        selected = str(self._preview_gamesync_state.get("selected_state_group", "")).strip()
        names = self._preview_definition_names("state_groups")
        if selected in names:
            return selected
        return self._default_preview_state_group_name()

    def _preview_selected_switch_group(self) -> str:
        selected = str(self._preview_gamesync_state.get("selected_switch_group", "")).strip()
        names = self._preview_definition_names("switch_groups")
        if selected in names:
            return selected
        return self._default_preview_switch_group_name()

    def _preview_parameter_value(self, parameter_name: str, scope: str) -> float:
        if not parameter_name:
            return 0.0
        values = self._preview_parameter_values(scope)
        if parameter_name in values:
            return float(values[parameter_name])
        return self._preview_parameter_default_value(parameter_name)

    def _preview_state_value(self, group_name: str) -> str:
        if not group_name:
            return ""
        states = self._preview_gamesync_state.get("states", {})
        if isinstance(states, dict):
            value = str(states.get(group_name, "")).strip()
            if value:
                return value
        return self._preview_default_state_name(group_name)

    def _preview_switch_value(self, group_name: str) -> str:
        if not group_name:
            return ""
        switches = self._preview_gamesync_state.get("switches", {})
        if isinstance(switches, dict):
            value = str(switches.get(group_name, "")).strip()
            if value:
                return value
        return self._preview_default_switch_name(group_name)

    def _load_preview_gamesync_editor(self) -> None:
        self._preview_gamesync_loading = True
        parameter_name = self._preview_selected_parameter_name()
        parameter_scope = self._preview_selected_parameter_scope()
        state_group = self._preview_selected_state_group()
        switch_group = self._preview_selected_switch_group()
        self._preview_gamesync_state["selected_parameter_name"] = parameter_name
        self._preview_gamesync_state["selected_parameter_scope"] = parameter_scope
        self._preview_gamesync_state["selected_state_group"] = state_group
        self._preview_gamesync_state["selected_switch_group"] = switch_group
        self._set_combo_box_values(self.preview_parameter_name_combo, self._preview_definition_names("game_parameters"), parameter_name)
        self._set_combo_box_values(self.preview_parameter_scope_combo, ["Global", "Emitter"], parameter_scope)
        minimum, maximum = self._preview_parameter_limits(parameter_name)
        parameter_value = self._preview_parameter_value(parameter_name, parameter_scope)
        self.preview_parameter_value_spin.blockSignals(True)
        self.preview_parameter_value_spin.setRange(minimum, maximum)
        self.preview_parameter_value_spin.setValue(parameter_value)
        self.preview_parameter_value_spin.blockSignals(False)
        self.preview_parameter_slider.setEnabled(bool(parameter_name))
        self._sync_preview_parameter_transport_value(parameter_name, parameter_value)
        self._set_combo_box_values(self.preview_state_group_combo, self._preview_definition_names("state_groups"), state_group)
        self._set_combo_box_values(self.preview_state_name_combo, self._preview_states_for_group(state_group), self._preview_state_value(state_group))
        self._set_combo_box_values(self.preview_switch_group_combo, self._preview_definition_names("switch_groups"), switch_group)
        self._set_combo_box_values(self.preview_switch_name_combo, self._preview_switches_for_group(switch_group), self._preview_switch_value(switch_group))
        self.set_preview_gamesync_enabled(self._active_event_id is not None)
        self._preview_gamesync_loading = False

    def _handle_preview_parameter_selection_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        self._preview_gamesync_state["selected_parameter_name"] = self.preview_parameter_name_combo.currentText().strip()
        self._preview_gamesync_state["selected_parameter_scope"] = self.preview_parameter_scope_combo.currentText().strip() or "Emitter"
        self._load_preview_gamesync_editor()
        self.previewGameSyncChanged.emit()

    def _handle_preview_parameter_value_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        parameter_name = self.preview_parameter_name_combo.currentText().strip()
        if not parameter_name:
            return
        scope = self.preview_parameter_scope_combo.currentText().strip() or "Emitter"
        value = float(self.preview_parameter_value_spin.value())
        self._preview_parameter_values(scope)[parameter_name] = value
        self._sync_preview_parameter_transport_value(parameter_name, value)
        self.previewGameSyncChanged.emit()

    def _preview_parameter_slider_preview(self, slider_value: int) -> None:
        parameter_name = self.preview_parameter_name_combo.currentText().strip()
        if not parameter_name:
            self.preview_parameter_current_label.setText("RTPC -")
            return
        self.preview_parameter_current_label.setText(
            self._format_preview_parameter_value_text(self._preview_parameter_value_from_slider(parameter_name, slider_value))
        )

    def _handle_preview_parameter_slider_changed(self, slider_value: int) -> None:
        if self._preview_gamesync_loading:
            return
        parameter_name = self.preview_parameter_name_combo.currentText().strip()
        if not parameter_name:
            return
        self.preview_parameter_value_spin.setValue(self._preview_parameter_value_from_slider(parameter_name, slider_value))

    def _handle_preview_state_group_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        group_name = self.preview_state_group_combo.currentText().strip()
        self._preview_gamesync_state["selected_state_group"] = group_name
        self._load_preview_gamesync_editor()
        self.previewGameSyncChanged.emit()

    def _handle_preview_state_value_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        group_name = self.preview_state_group_combo.currentText().strip()
        if not group_name:
            return
        states = self._preview_gamesync_state.get("states", {})
        if isinstance(states, dict):
            states[group_name] = self.preview_state_name_combo.currentText().strip()
        self.previewGameSyncChanged.emit()

    def _handle_preview_switch_group_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        group_name = self.preview_switch_group_combo.currentText().strip()
        self._preview_gamesync_state["selected_switch_group"] = group_name
        self._load_preview_gamesync_editor()
        self.previewGameSyncChanged.emit()

    def _handle_preview_switch_value_changed(self) -> None:
        if self._preview_gamesync_loading:
            return
        group_name = self.preview_switch_group_combo.currentText().strip()
        if not group_name:
            return
        switches = self._preview_gamesync_state.get("switches", {})
        if isinstance(switches, dict):
            switches[group_name] = self.preview_switch_name_combo.currentText().strip()
        self.previewGameSyncChanged.emit()

    def current_preview_gamesync_context_data(self) -> dict[str, object]:
        if not self._preview_gamesync_loading:
            self._preview_gamesync_state["selected_parameter_name"] = self.preview_parameter_name_combo.currentText().strip()
            self._preview_gamesync_state["selected_parameter_scope"] = self.preview_parameter_scope_combo.currentText().strip() or "Emitter"
            self._preview_gamesync_state["selected_state_group"] = self.preview_state_group_combo.currentText().strip()
            self._preview_gamesync_state["selected_switch_group"] = self.preview_switch_group_combo.currentText().strip()
        return {
            "global_parameters": dict(self._preview_gamesync_state.get("global_parameters", {})),
            "emitter_parameters": dict(self._preview_gamesync_state.get("emitter_parameters", {})),
            "states": dict(self._preview_gamesync_state.get("states", {})),
            "switches": dict(self._preview_gamesync_state.get("switches", {})),
            "selected_parameter_name": str(self._preview_gamesync_state.get("selected_parameter_name", "")),
            "selected_parameter_scope": str(self._preview_gamesync_state.get("selected_parameter_scope", "Emitter")),
            "selected_state_group": str(self._preview_gamesync_state.get("selected_state_group", "")),
            "selected_switch_group": str(self._preview_gamesync_state.get("selected_switch_group", "")),
        }

    def set_preview_gamesync_resolution_snapshot(self, snapshot) -> None:
        self.preview_parameter_source_chip.setText(str(getattr(snapshot, "parameter_source", "Default") or "Default"))
        self.preview_state_scope_chip.setText("Global")
        self.preview_switch_source_chip.setText(str(getattr(snapshot, "switch_mode", "Default") or "Default"))
        switch_parameter_source = str(getattr(snapshot, "switch_parameter_source", "None") or "None")
        self.preview_switch_parameter_source_chip.setText("参数 -" if switch_parameter_source in {"None", ""} else f"参数 {switch_parameter_source}")
        summary = str(getattr(snapshot, "summary", "") or "当前没有额外的 GameSync 覆盖。")
        self.preview_gamesync_summary_label.setText(summary)
        self.preview_gamesync_summary_label.setToolTip(summary)

    def current_gamesync_form_data(self) -> dict[str, object]:
        self._sync_gamesync_editor_to_state("game_parameters")
        self._sync_gamesync_editor_to_state("state_groups")
        self._sync_gamesync_editor_to_state("switch_groups")
        return {
            "game_parameters": [dict(entry) for entry in self._gamesync_models["game_parameters"]],
            "state_groups": [
                {
                    **dict(entry),
                    "states": list(entry.get("states", [])),
                }
                for entry in self._gamesync_models["state_groups"]
            ],
            "switch_groups": [
                {
                    **dict(entry),
                    "switches": list(entry.get("switches", [])),
                }
                for entry in self._gamesync_models["switch_groups"]
            ],
        }

    def _gamesync_workspace_list_widget(self, key: str) -> QListWidget:
        return {
            "game_parameters": self.gamesync_parameter_workspace_list,
            "state_groups": self.gamesync_state_workspace_list,
            "switch_groups": self.gamesync_switch_workspace_list,
        }[key]

    def _gamesync_selected_row(self, key: str) -> int:
        return self._gamesync_workspace_list_widget(key).currentRow()

    def _load_gamesync_editor(self, key: str) -> None:
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        has_selection = 0 <= row < len(entries)
        self._loading_gamesync = True
        if key == "game_parameters":
            self.gamesync_parameter_remove_button.setEnabled(has_selection)
            if not has_selection:
                self.gamesync_parameter_name_edit.clear()
                self.gamesync_parameter_default_spin.setValue(0.0)
                self.gamesync_parameter_min_spin.setValue(0.0)
                self.gamesync_parameter_max_spin.setValue(100.0)
                self.gamesync_parameter_notes_edit.clear()
            else:
                entry = entries[row]
                self.gamesync_parameter_name_edit.setText(str(entry.get("name", "")))
                self.gamesync_parameter_default_spin.setValue(float(entry.get("default_value", 0.0)))
                self.gamesync_parameter_min_spin.setValue(float(entry.get("min_value", 0.0)))
                self.gamesync_parameter_max_spin.setValue(float(entry.get("max_value", 100.0)))
                self.gamesync_parameter_notes_edit.setPlainText(str(entry.get("notes", "")))
        elif key == "state_groups":
            self.gamesync_state_remove_button.setEnabled(has_selection)
            if not has_selection:
                self.gamesync_state_name_edit.clear()
                self.gamesync_state_value_list.clear()
                self.gamesync_state_values_edit.clear()
                self.gamesync_state_default_edit.clear()
                self.gamesync_state_value_volume_spin.setValue(0.0)
                self.gamesync_state_value_pitch_spin.setValue(0)
                self.gamesync_state_value_mute_check.setChecked(False)
                self.gamesync_state_value_notes_edit.clear()
                self.gamesync_state_notes_edit.clear()
            else:
                entry = entries[row]
                self.gamesync_state_name_edit.setText(str(entry.get("name", "")))
                self.gamesync_state_default_edit.setText(str(entry.get("default_state", "")))
                self.gamesync_state_notes_edit.setPlainText(str(entry.get("notes", "")))
            self._refresh_gamesync_child_values("state_groups")
            self._load_gamesync_child_value_editor("state_groups")
        else:
            self.gamesync_switch_remove_button.setEnabled(has_selection)
            if not has_selection:
                self.gamesync_switch_name_edit.clear()
                self.gamesync_switch_value_list.clear()
                self.gamesync_switch_values_edit.clear()
                self.gamesync_switch_default_edit.clear()
                self.gamesync_switch_value_volume_spin.setValue(0.0)
                self.gamesync_switch_value_pitch_spin.setValue(0)
                self.gamesync_switch_value_mute_check.setChecked(False)
                self.gamesync_switch_value_notes_edit.clear()
                self.gamesync_switch_use_rtpc_check.setChecked(False)
                self.gamesync_switch_mapped_parameter_edit.clear()
                self.gamesync_switch_notes_edit.clear()
            else:
                entry = entries[row]
                self.gamesync_switch_name_edit.setText(str(entry.get("name", "")))
                self.gamesync_switch_default_edit.setText(str(entry.get("default_switch", "")))
                self.gamesync_switch_use_rtpc_check.setChecked(bool(entry.get("use_game_parameter", False)))
                self.gamesync_switch_mapped_parameter_edit.setText(str(entry.get("mapped_game_parameter", "")))
                self.gamesync_switch_notes_edit.setPlainText(str(entry.get("notes", "")))
            self._refresh_gamesync_child_values("switch_groups")
            self._load_gamesync_child_value_editor("switch_groups")
        self._loading_gamesync = False

    def _sync_gamesync_editor_to_state(self, key: str) -> None:
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        if row < 0 or row >= len(entries):
            return
        if key == "game_parameters":
            min_value = float(self.gamesync_parameter_min_spin.value())
            max_value = float(self.gamesync_parameter_max_spin.value())
            if max_value < min_value:
                min_value, max_value = max_value, min_value
            default_value = min(max(float(self.gamesync_parameter_default_spin.value()), min_value), max_value)
            entries[row] = {
                "name": self.gamesync_parameter_name_edit.text().strip() or str(entries[row].get("name", "GameParameter")),
                "default_value": default_value,
                "min_value": min_value,
                "max_value": max_value,
                "notes": self.gamesync_parameter_notes_edit.toPlainText().strip(),
            }
        elif key == "state_groups":
            self._sync_gamesync_child_value_editor_to_state(key)
            states = [str(value) for value in entries[row].get("states", []) if str(value).strip()]
            state_effects = self._normalized_gamesync_child_effects(entries[row].get("state_effects", {}))
            default_state = self.gamesync_state_default_edit.text().strip()
            if default_state and default_state.casefold() not in {value.casefold() for value in states}:
                states.append(default_state)
            entries[row] = {
                "name": self.gamesync_state_name_edit.text().strip() or str(entries[row].get("name", "StateGroup")),
                "states": states,
                "default_state": default_state or (states[0] if states else ""),
                "state_effects": {name: payload for name, payload in state_effects.items() if name in states},
                "notes": self.gamesync_state_notes_edit.toPlainText().strip(),
            }
        else:
            self._sync_gamesync_child_value_editor_to_state(key)
            switches = [str(value) for value in entries[row].get("switches", []) if str(value).strip()]
            switch_effects = self._normalized_gamesync_child_effects(entries[row].get("switch_effects", {}))
            default_switch = self.gamesync_switch_default_edit.text().strip()
            if default_switch and default_switch.casefold() not in {value.casefold() for value in switches}:
                switches.append(default_switch)
            entries[row] = {
                "name": self.gamesync_switch_name_edit.text().strip() or str(entries[row].get("name", "SwitchGroup")),
                "switches": switches,
                "default_switch": default_switch or (switches[0] if switches else ""),
                "use_game_parameter": self.gamesync_switch_use_rtpc_check.isChecked(),
                "mapped_game_parameter": self.gamesync_switch_mapped_parameter_edit.text().strip(),
                "switch_effects": {name: payload for name, payload in switch_effects.items() if name in switches},
                "notes": self.gamesync_switch_notes_edit.toPlainText().strip(),
            }
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()

    def _gamesync_child_value_list_widget(self, key: str) -> QListWidget:
        return {
            "state_groups": self.gamesync_state_value_list,
            "switch_groups": self.gamesync_switch_value_list,
        }[key]

    def _gamesync_child_value_edit(self, key: str) -> QLineEdit:
        return {
            "state_groups": self.gamesync_state_values_edit,
            "switch_groups": self.gamesync_switch_values_edit,
        }[key]

    def _gamesync_child_value_keys(self, key: str) -> tuple[str, str]:
        return {
            "state_groups": ("states", "Default"),
            "switch_groups": ("switches", "Default"),
        }[key]

    def _gamesync_child_effect_key(self, key: str) -> str:
        return {
            "state_groups": "state_effects",
            "switch_groups": "switch_effects",
        }[key]

    def _gamesync_child_effect_controls(self, key: str) -> tuple[QDoubleSpinBox, QSpinBox, QCheckBox, QPlainTextEdit]:
        return {
            "state_groups": (
                self.gamesync_state_value_volume_spin,
                self.gamesync_state_value_pitch_spin,
                self.gamesync_state_value_mute_check,
                self.gamesync_state_value_notes_edit,
            ),
            "switch_groups": (
                self.gamesync_switch_value_volume_spin,
                self.gamesync_switch_value_pitch_spin,
                self.gamesync_switch_value_mute_check,
                self.gamesync_switch_value_notes_edit,
            ),
        }[key]

    def _gamesync_child_effect_summary(self, payload: dict[str, object]) -> str:
        parts: list[str] = []
        volume_db = float(payload.get("volume_db", 0.0))
        pitch_cents = int(payload.get("pitch_cents", 0))
        is_muted = bool(payload.get("is_muted", False))
        if volume_db:
            parts.append(f"Vol {volume_db:+.1f}dB")
        if pitch_cents:
            parts.append(f"Pitch {pitch_cents:+d}")
        if is_muted:
            parts.append("Mute")
        return " | ".join(parts)

    def _refresh_gamesync_child_values(self, key: str) -> None:
        list_widget = self._gamesync_child_value_list_widget(key)
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        value_key, _default_name = self._gamesync_child_value_keys(key)
        effect_key = self._gamesync_child_effect_key(key)
        values = list(entries[row].get(value_key, [])) if 0 <= row < len(entries) else []
        effect_map = self._normalized_gamesync_child_effects(entries[row].get(effect_key, {})) if 0 <= row < len(entries) else {}
        current_row = list_widget.currentRow()
        list_widget.blockSignals(True)
        list_widget.clear()
        for value in values:
            effect_summary = self._gamesync_child_effect_summary(effect_map.get(str(value), {}))
            item = QListWidgetItem(str(value) if not effect_summary else f"{value}  [{effect_summary}]")
            item.setData(Qt.ItemDataRole.UserRole, str(value))
            list_widget.addItem(item)
        if values:
            list_widget.setCurrentRow(min(max(current_row, 0), len(values) - 1))
        list_widget.blockSignals(False)

    def _load_gamesync_child_value_editor(self, key: str) -> None:
        list_widget = self._gamesync_child_value_list_widget(key)
        editor = self._gamesync_child_value_edit(key)
        volume_spin, pitch_spin, mute_check, notes_edit = self._gamesync_child_effect_controls(key)
        row = list_widget.currentRow()
        has_selection = row >= 0 and row < list_widget.count()
        parent_row = self._gamesync_selected_row(key)
        effect_key = self._gamesync_child_effect_key(key)
        effect_map = self._normalized_gamesync_child_effects(
            self._gamesync_models.get(key, [])[parent_row].get(effect_key, {})
        ) if 0 <= parent_row < len(self._gamesync_models.get(key, [])) else {}
        child_name = str(list_widget.item(row).data(Qt.ItemDataRole.UserRole) or "") if has_selection else ""
        effect_payload = effect_map.get(child_name, self._gamesync_child_effect_payload({}))
        if key == "state_groups":
            self.gamesync_state_value_remove_button.setEnabled(has_selection)
        else:
            self.gamesync_switch_value_remove_button.setEnabled(has_selection)
        editor.setEnabled(has_selection)
        volume_spin.setEnabled(has_selection)
        pitch_spin.setEnabled(has_selection)
        mute_check.setEnabled(has_selection)
        notes_edit.setEnabled(has_selection)
        editor.blockSignals(True)
        editor.setText(child_name)
        editor.blockSignals(False)
        volume_spin.blockSignals(True)
        volume_spin.setValue(float(effect_payload.get("volume_db", 0.0)))
        volume_spin.blockSignals(False)
        pitch_spin.blockSignals(True)
        pitch_spin.setValue(int(effect_payload.get("pitch_cents", 0)))
        pitch_spin.blockSignals(False)
        mute_check.blockSignals(True)
        mute_check.setChecked(bool(effect_payload.get("is_muted", False)))
        mute_check.blockSignals(False)
        notes_edit.blockSignals(True)
        notes_edit.setPlainText(str(effect_payload.get("notes", "")))
        notes_edit.blockSignals(False)

    def _sync_gamesync_child_value_editor_to_state(self, key: str) -> None:
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        if row < 0 or row >= len(entries):
            return
        list_widget = self._gamesync_child_value_list_widget(key)
        child_row = list_widget.currentRow()
        value_key, _default_name = self._gamesync_child_value_keys(key)
        effect_key = self._gamesync_child_effect_key(key)
        default_key = "default_state" if key == "state_groups" else "default_switch"
        volume_spin, pitch_spin, mute_check, notes_edit = self._gamesync_child_effect_controls(key)
        values = [str(value) for value in entries[row].get(value_key, [])]
        if child_row < 0 or child_row >= len(values):
            return
        previous_value = values[child_row]
        updated_value = self._gamesync_child_value_edit(key).text().strip()
        if not updated_value:
            return
        values[child_row] = updated_value
        entries[row][value_key] = self._normalized_name_list_from_text(", ".join(values))
        effect_map = self._normalized_gamesync_child_effects(entries[row].get(effect_key, {}))
        if previous_value != updated_value and previous_value in effect_map:
            effect_map[updated_value] = effect_map.pop(previous_value)
        effect_map[updated_value] = {
            "volume_db": float(volume_spin.value()),
            "pitch_cents": int(pitch_spin.value()),
            "is_muted": bool(mute_check.isChecked()),
            "notes": notes_edit.toPlainText().strip(),
        }
        entries[row][effect_key] = {name: payload for name, payload in effect_map.items() if name in entries[row][value_key]}
        if str(entries[row].get(default_key, "")).strip() == previous_value:
            entries[row][default_key] = updated_value
        self._refresh_gamesync_child_values(key)

    def _create_gamesync_child_value(self, key: str) -> None:
        self._sync_gamesync_editor_to_state(key)
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        if row < 0 or row >= len(entries):
            return
        value_key, default_name = self._gamesync_child_value_keys(key)
        effect_key = self._gamesync_child_effect_key(key)
        values = [str(value) for value in entries[row].get(value_key, [])]
        index = 1
        existing = {value.casefold() for value in values}
        while f"{default_name}{index}".casefold() in existing:
            index += 1
        child_name = f"{default_name}{index}"
        values.append(child_name)
        entries[row][value_key] = values
        effect_map = self._normalized_gamesync_child_effects(entries[row].get(effect_key, {}))
        effect_map[child_name] = self._gamesync_child_effect_payload({})
        entries[row][effect_key] = effect_map
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        self._refresh_gamesync_child_values(key)
        self._gamesync_child_value_list_widget(key).setCurrentRow(len(values) - 1)
        self._load_gamesync_child_value_editor(key)

    def _remove_gamesync_child_value(self, key: str) -> None:
        entries = self._gamesync_models.get(key, [])
        row = self._gamesync_selected_row(key)
        if row < 0 or row >= len(entries):
            return
        list_widget = self._gamesync_child_value_list_widget(key)
        child_row = list_widget.currentRow()
        value_key, _default_name = self._gamesync_child_value_keys(key)
        effect_key = self._gamesync_child_effect_key(key)
        default_key = "default_state" if key == "state_groups" else "default_switch"
        values = [str(value) for value in entries[row].get(value_key, [])]
        if child_row < 0 or child_row >= len(values):
            return
        removed_value = values[child_row]
        del values[child_row]
        entries[row][value_key] = values
        effect_map = self._normalized_gamesync_child_effects(entries[row].get(effect_key, {}))
        effect_map.pop(removed_value, None)
        entries[row][effect_key] = effect_map
        if str(entries[row].get(default_key, "")).strip() == removed_value:
            entries[row][default_key] = values[0] if values else ""
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        self._refresh_gamesync_child_values(key)
        if values:
            list_widget.setCurrentRow(min(child_row, len(values) - 1))
        self._load_gamesync_child_value_editor(key)
        self._emit_gamesync_changed()

    def _commit_gamesync_child_value(self, key: str) -> None:
        if self._loading_gamesync:
            return
        self._sync_gamesync_child_value_editor_to_state(key)
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        self._refresh_gamesync_child_values(key)
        self.gameSyncChanged.emit()

    def _create_gamesync_item(self, key: str) -> None:
        self._sync_gamesync_editor_to_state(key)
        entries = self._gamesync_models[key]
        base_name = {
            "game_parameters": "GameParameter",
            "state_groups": "StateGroup",
            "switch_groups": "SwitchGroup",
        }[key]
        existing = {str(entry.get("name", "")).casefold() for entry in entries}
        index = 1
        while f"{base_name}{index}".casefold() in existing:
            index += 1
        if key == "game_parameters":
            entries.append({"name": f"{base_name}{index}", "default_value": 0.0, "min_value": 0.0, "max_value": 100.0, "notes": ""})
        elif key == "state_groups":
            entries.append({"name": f"{base_name}{index}", "states": [], "default_state": "", "state_effects": {}, "notes": ""})
        else:
            entries.append(
                {
                    "name": f"{base_name}{index}",
                    "switches": [],
                    "default_switch": "",
                    "use_game_parameter": False,
                    "mapped_game_parameter": "",
                    "switch_effects": {},
                    "notes": "",
                }
            )
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        self._gamesync_workspace_list_widget(key).setCurrentRow(len(entries) - 1)
        self._load_gamesync_editor(key)
        self._emit_gamesync_changed()

    def _remove_gamesync_item(self, key: str) -> None:
        entries = self._gamesync_models[key]
        row = self._gamesync_selected_row(key)
        if row < 0 or row >= len(entries):
            return
        del entries[row]
        self._refresh_gamesync_entries_from_models()
        self._refresh_gamesync_views()
        if entries:
            self._gamesync_workspace_list_widget(key).setCurrentRow(min(row, len(entries) - 1))
        self._load_gamesync_editor(key)
        self._emit_gamesync_changed()

    def set_gamesync_entries(self, entries: dict[str, list[dict[str, object]]]) -> None:
        self._gamesync_entries = {
            "game_parameters": list(entries.get("game_parameters", [])),
            "state_groups": list(entries.get("state_groups", [])),
            "switch_groups": list(entries.get("switch_groups", [])),
        }
        self._refresh_gamesync_views()

    def _gamesync_filtered_entries(self, key: str, query: str = "") -> list[dict[str, object]]:
        entries = list(self._gamesync_entries.get(key, []))
        normalized = query.strip().casefold()
        if not normalized:
            return entries
        filtered: list[dict[str, object]] = []
        for entry in entries:
            haystack = " ".join(
                [
                    str(entry.get("name", "")),
                    str(entry.get("summary", "")),
                    str(entry.get("detail", "")),
                ]
            ).casefold()
            if normalized in haystack:
                filtered.append(entry)
        return filtered

    def _refresh_gamesync_list_widget(self, list_widget: QListWidget, entries: list[dict[str, object]], empty_label: str) -> None:
        current_name = ""
        current_item = list_widget.currentItem()
        if current_item is not None:
            payload = current_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                current_name = str(payload.get("name", "")).strip()

        list_widget.blockSignals(True)
        list_widget.clear()
        for entry in entries:
            item = QListWidgetItem(str(entry.get("name", "未命名对象")))
            item.setToolTip(f"{entry.get('summary', '')}\n{entry.get('detail', '')}".strip())
            item.setData(Qt.ItemDataRole.UserRole, entry)
            list_widget.addItem(item)
        if list_widget.count() == 0:
            placeholder = QListWidgetItem(empty_label)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(placeholder)
        else:
            selected_row = 0
            if current_name:
                for index in range(list_widget.count()):
                    payload = list_widget.item(index).data(Qt.ItemDataRole.UserRole)
                    if isinstance(payload, dict) and str(payload.get("name", "")).strip() == current_name:
                        selected_row = index
                        break
            list_widget.setCurrentRow(selected_row)
        list_widget.blockSignals(False)

    def _update_gamesync_detail_label(self, list_widget: QListWidget, detail_label: QLabel, empty_label: str) -> None:
        item = list_widget.currentItem()
        if item is None:
            detail_label.setText(empty_label)
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            detail_label.setText(empty_label)
            return
        name = str(payload.get("name", "")).strip() or "未命名对象"
        summary = str(payload.get("summary", "")).strip()
        detail = str(payload.get("detail", "")).strip()
        detail_label.setText(f"{name}\n{summary}\n\n{detail}".strip())

    def _update_gamesync_browser_status(self) -> None:
        tab_key_map = {
            0: (self.gamesync_parameter_browser_list, "当前还没有 Game Parameter。"),
            1: (self.gamesync_state_browser_list, "当前还没有 State Group。"),
            2: (self.gamesync_switch_browser_list, "当前还没有 Switch Group。"),
        }
        list_widget, empty_label = tab_key_map.get(self.gamesync_browser_tabs.currentIndex(), (self.gamesync_parameter_browser_list, "当前还没有 GameSync 定义。"))
        item = list_widget.currentItem()
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        total_count = sum(len(self._gamesync_entries.get(key, [])) for key in ("game_parameters", "state_groups", "switch_groups"))
        self.gamesync_browser_summary_label.setText(
            f"GameSync 浏览页当前汇总 {total_count} 个项目级对象，可作为 phase3 authoring 与 Schema v2 的前置入口。"
        )
        if not isinstance(payload, dict):
            self.gamesync_browser_status_label.setText(empty_label)
            return
        self.gamesync_browser_status_label.setText(
            f"{payload.get('name', '-')}\n{payload.get('summary', '')}\n{payload.get('detail', '')}"
        )

    def _refresh_gamesync_views(self) -> None:
        browser_query = self.tree_filter_edit.text() if self._active_explorer_page_key() == "gamesync" else ""
        self._refresh_gamesync_list_widget(
            self.gamesync_parameter_browser_list,
            self._gamesync_filtered_entries("game_parameters", browser_query),
            "当前还没有 Game Parameter。",
        )
        self._refresh_gamesync_list_widget(
            self.gamesync_state_browser_list,
            self._gamesync_filtered_entries("state_groups", browser_query),
            "当前还没有 State Group。",
        )
        self._refresh_gamesync_list_widget(
            self.gamesync_switch_browser_list,
            self._gamesync_filtered_entries("switch_groups", browser_query),
            "当前还没有 Switch Group。",
        )
        self._refresh_gamesync_list_widget(
            self.gamesync_parameter_workspace_list,
            self._gamesync_filtered_entries("game_parameters"),
            "当前还没有 Game Parameter。",
        )
        self._refresh_gamesync_list_widget(
            self.gamesync_state_workspace_list,
            self._gamesync_filtered_entries("state_groups"),
            "当前还没有 State Group。",
        )
        self._refresh_gamesync_list_widget(
            self.gamesync_switch_workspace_list,
            self._gamesync_filtered_entries("switch_groups"),
            "当前还没有 Switch Group。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_parameter_browser_list,
            self.gamesync_parameter_browser_detail_label,
            "当前还没有 Game Parameter。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_state_browser_list,
            self.gamesync_state_browser_detail_label,
            "当前还没有 State Group。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_switch_browser_list,
            self.gamesync_switch_browser_detail_label,
            "当前还没有 Switch Group。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_parameter_workspace_list,
            self.gamesync_parameter_workspace_detail_label,
            "当前还没有 Game Parameter。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_state_workspace_list,
            self.gamesync_state_workspace_detail_label,
            "当前还没有 State Group。",
        )
        self._update_gamesync_detail_label(
            self.gamesync_switch_workspace_list,
            self.gamesync_switch_workspace_detail_label,
            "当前还没有 Switch Group。",
        )
        total_parameters = len(self._gamesync_entries.get("game_parameters", []))
        total_states = len(self._gamesync_entries.get("state_groups", []))
        total_switches = len(self._gamesync_entries.get("switch_groups", []))
        self.gamesync_overview_total_label.setText(
            f"Game Parameters {total_parameters} | State Groups {total_states} | Switch Groups {total_switches}"
        )
        self.gamesync_overview_detail_label.setText(
            "phase3 当前先把项目级对象和浏览入口接入工程模型；下一步再把它们映射到事件、总线、导出与 runtime。"
            if total_parameters or total_states or total_switches
            else "当前工程还没有任何 GameSync 定义。可先从项目级对象开始，逐步补齐 RTPC / State / Switch authoring。"
        )
        self._update_gamesync_browser_status()

    def _rtpc_binding_payload(self, binding: RtpcBindingModel | dict[str, object]) -> dict[str, object]:
        if isinstance(binding, RtpcBindingModel):
            return {
                "parameter_name": binding.parameter_name,
                "target": binding.target,
                "scope": binding.scope,
                "curve_points": [
                    {
                        "input_value": float(point.input_value),
                        "output_value": float(point.output_value),
                        "interpolation": point.interpolation,
                    }
                    for point in binding.curve_points
                ],
                "notes": binding.notes,
            }
        return {
            "parameter_name": str(binding.get("parameter_name", "")).strip(),
            "target": str(binding.get("target", "EventVolumeDb")).strip() or "EventVolumeDb",
            "scope": str(binding.get("scope", "Global")).strip() or "Global",
            "curve_points": self._copy_curve_point_payloads(binding.get("curve_points", [])),
            "notes": str(binding.get("notes", "")),
        }

    def _state_override_payload(self, override: StateOverrideModel | dict[str, object]) -> dict[str, object]:
        if isinstance(override, StateOverrideModel):
            return {
                "group_name": override.group_name,
                "state_name": override.state_name,
                "volume_db": float(override.volume_db),
                "pitch_cents": int(override.pitch_cents),
                "is_muted": bool(override.is_muted),
                "notes": override.notes,
            }
        return {
            "group_name": str(override.get("group_name", "")).strip(),
            "state_name": str(override.get("state_name", "")).strip(),
            "volume_db": float(override.get("volume_db", 0.0)),
            "pitch_cents": int(override.get("pitch_cents", 0)),
            "is_muted": bool(override.get("is_muted", False)),
            "notes": str(override.get("notes", "")),
        }

    def _switch_variant_payload(self, variant: SwitchVariantModel | dict[str, object]) -> dict[str, object]:
        if isinstance(variant, SwitchVariantModel):
            return {
                "group_name": variant.group_name,
                "switch_name": variant.switch_name,
                "clip_ids": list(variant.clip_ids),
                "notes": variant.notes,
            }
        return {
            "group_name": str(variant.get("group_name", "")).strip(),
            "switch_name": str(variant.get("switch_name", "")).strip(),
            "clip_ids": self._normalized_name_list_from_text(", ".join(str(value) for value in variant.get("clip_ids", []))),
            "notes": str(variant.get("notes", "")),
        }

    def _refresh_named_payload_list(
        self,
        list_widget: QListWidget,
        payloads: list[dict[str, object]],
        *,
        name_builder,
        empty_text: str,
    ) -> None:
        current_text = ""
        current_item = list_widget.currentItem()
        if current_item is not None:
            payload = current_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                current_text = str(name_builder(payload))
        list_widget.blockSignals(True)
        list_widget.clear()
        if not payloads:
            placeholder = QListWidgetItem(empty_text)
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(placeholder)
            list_widget.blockSignals(False)
            return
        selected_row = 0
        for index, payload in enumerate(payloads):
            title = str(name_builder(payload)).strip() or empty_text
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, payload)
            list_widget.addItem(item)
            if current_text and title == current_text:
                selected_row = index
        list_widget.setCurrentRow(selected_row)
        list_widget.blockSignals(False)

    def _refresh_event_binding_views(self) -> None:
        self._refresh_named_payload_list(
            self.event_rtpc_list,
            self._event_rtpc_bindings,
            name_builder=lambda payload: str(payload.get("parameter_name", "")).strip() or "未命名 RTPC",
            empty_text="当前还没有 RTPC 绑定。",
        )
        self._refresh_named_payload_list(
            self.event_state_list,
            self._event_state_overrides,
            name_builder=lambda payload: f"{payload.get('group_name', '-')}/{payload.get('state_name', '-')}",
            empty_text="当前还没有 State Override。",
        )
        self._refresh_named_payload_list(
            self.event_switch_list,
            self._event_switch_variants,
            name_builder=lambda payload: f"{payload.get('group_name', '-')}/{payload.get('switch_name', '-')}",
            empty_text="当前还没有 Switch Variant。",
        )

    def _load_event_binding_editor(self, kind: str) -> None:
        self._loading_event = True
        if kind == "rtpc":
            row = self.event_rtpc_list.currentRow()
            has_selection = 0 <= row < len(self._event_rtpc_bindings)
            self.event_rtpc_remove_button.setEnabled(has_selection)
            payload = self._event_rtpc_bindings[row] if has_selection else self._default_event_rtpc_binding_payload()
            self._set_combo_box_values(self.event_rtpc_parameter_edit, self._available_game_parameter_names(), str(payload.get("parameter_name", "")))
            self.event_rtpc_target_combo.setCurrentText(str(payload.get("target", "EventVolumeDb")))
            self.event_rtpc_scope_combo.setCurrentText(str(payload.get("scope", "Global")))
            self._refresh_event_rtpc_curve_editor_ranges()
            self._set_curve_table_points(self.event_rtpc_curve_table, payload.get("curve_points", []))
            self._sync_curve_interpolation_combo(self.event_rtpc_curve_table, self.event_rtpc_interpolation_combo)
            self._sync_curve_point_controls(self.event_rtpc_curve_table, self.event_rtpc_selected_input_spin, self.event_rtpc_selected_output_spin)
            self.event_rtpc_notes_edit.setPlainText(str(payload.get("notes", "")))
        elif kind == "state":
            row = self.event_state_list.currentRow()
            has_selection = 0 <= row < len(self._event_state_overrides)
            self.event_state_remove_button.setEnabled(has_selection)
            payload = self._event_state_overrides[row] if has_selection else self._state_override_payload({})
            self._set_combo_box_values(self.event_state_group_edit, self._available_state_group_names(), str(payload.get("group_name", "")))
            self._refresh_event_state_name_options(str(payload.get("state_name", "")))
            self.event_state_volume_spin.setValue(float(payload.get("volume_db", 0.0)))
            self.event_state_pitch_spin.setValue(int(payload.get("pitch_cents", 0)))
            self.event_state_mute_check.setChecked(bool(payload.get("is_muted", False)))
            self.event_state_notes_edit.setPlainText(str(payload.get("notes", "")))
        else:
            row = self.event_switch_list.currentRow()
            has_selection = 0 <= row < len(self._event_switch_variants)
            self.event_switch_remove_button.setEnabled(has_selection)
            payload = self._event_switch_variants[row] if has_selection else self._switch_variant_payload({})
            self._set_combo_box_values(self.event_switch_group_edit, self._available_switch_group_names(), str(payload.get("group_name", "")))
            self._refresh_event_switch_name_options(str(payload.get("switch_name", "")))
            self.event_switch_clip_ids_edit.setText(", ".join(str(value) for value in payload.get("clip_ids", [])))
            self.event_switch_notes_edit.setPlainText(str(payload.get("notes", "")))
        self._loading_event = False

    def _sync_event_binding_editor_to_state(self, kind: str) -> None:
        if kind == "rtpc":
            row = self.event_rtpc_list.currentRow()
            if row < 0 or row >= len(self._event_rtpc_bindings):
                return
            self._event_rtpc_bindings[row] = {
                "parameter_name": self.event_rtpc_parameter_edit.currentText().strip(),
                "target": self.event_rtpc_target_combo.currentText(),
                "scope": self.event_rtpc_scope_combo.currentText(),
                "curve_points": self._curve_table_points(self.event_rtpc_curve_table),
                "notes": self.event_rtpc_notes_edit.toPlainText().strip(),
            }
        elif kind == "state":
            row = self.event_state_list.currentRow()
            if row < 0 or row >= len(self._event_state_overrides):
                return
            self._event_state_overrides[row] = {
                "group_name": self.event_state_group_edit.currentText().strip(),
                "state_name": self.event_state_name_edit.currentText().strip(),
                "volume_db": float(self.event_state_volume_spin.value()),
                "pitch_cents": int(self.event_state_pitch_spin.value()),
                "is_muted": self.event_state_mute_check.isChecked(),
                "notes": self.event_state_notes_edit.toPlainText().strip(),
            }
        else:
            row = self.event_switch_list.currentRow()
            if row < 0 or row >= len(self._event_switch_variants):
                return
            self._event_switch_variants[row] = {
                "group_name": self.event_switch_group_edit.currentText().strip(),
                "switch_name": self.event_switch_name_edit.currentText().strip(),
                "clip_ids": self._normalized_name_list_from_text(self.event_switch_clip_ids_edit.text()),
                "notes": self.event_switch_notes_edit.toPlainText().strip(),
            }
        self._refresh_event_binding_views()

    def _create_event_binding(self, kind: str) -> None:
        self._sync_event_binding_editor_to_state(kind)
        if kind == "rtpc":
            self._event_rtpc_bindings.append(self._default_event_rtpc_binding_payload())
            self._refresh_event_binding_views()
            self.event_rtpc_list.setCurrentRow(len(self._event_rtpc_bindings) - 1)
        elif kind == "state":
            self._event_state_overrides.append(self._default_event_state_override_payload())
            self._refresh_event_binding_views()
            self.event_state_list.setCurrentRow(len(self._event_state_overrides) - 1)
        else:
            self._event_switch_variants.append(self._default_event_switch_variant_payload())
            self._refresh_event_binding_views()
            self.event_switch_list.setCurrentRow(len(self._event_switch_variants) - 1)
        self._load_event_binding_editor(kind)
        self._emit_event_properties_changed()

    def _remove_event_binding(self, kind: str) -> None:
        if kind == "rtpc":
            row = self.event_rtpc_list.currentRow()
            if row < 0 or row >= len(self._event_rtpc_bindings):
                return
            del self._event_rtpc_bindings[row]
            self._refresh_event_binding_views()
            if self._event_rtpc_bindings:
                self.event_rtpc_list.setCurrentRow(min(row, len(self._event_rtpc_bindings) - 1))
        elif kind == "state":
            row = self.event_state_list.currentRow()
            if row < 0 or row >= len(self._event_state_overrides):
                return
            del self._event_state_overrides[row]
            self._refresh_event_binding_views()
            if self._event_state_overrides:
                self.event_state_list.setCurrentRow(min(row, len(self._event_state_overrides) - 1))
        else:
            row = self.event_switch_list.currentRow()
            if row < 0 or row >= len(self._event_switch_variants):
                return
            del self._event_switch_variants[row]
            self._refresh_event_binding_views()
            if self._event_switch_variants:
                self.event_switch_list.setCurrentRow(min(row, len(self._event_switch_variants) - 1))
        self._load_event_binding_editor(kind)
        self._emit_event_properties_changed()

    def _load_bus_binding_editors(self, bus_config: dict[str, object] | None) -> None:
        self._loading_event = True
        rtpc_bindings = list(bus_config.get("rtpc_bindings", [])) if isinstance(bus_config, dict) else []
        state_overrides = list(bus_config.get("state_overrides", [])) if isinstance(bus_config, dict) else []
        self._refresh_named_payload_list(
            self.bus_rtpc_list,
            rtpc_bindings,
            name_builder=lambda payload: str(payload.get("parameter_name", "")).strip() or "未命名 RTPC",
            empty_text="当前 Bus 还没有 RTPC。",
        )
        self._refresh_named_payload_list(
            self.bus_state_list,
            state_overrides,
            name_builder=lambda payload: f"{payload.get('group_name', '-')}/{payload.get('state_name', '-')}",
            empty_text="当前 Bus 还没有 State Override。",
        )
        if rtpc_bindings and self.bus_rtpc_list.currentRow() >= 0:
            payload = rtpc_bindings[self.bus_rtpc_list.currentRow()]
            self.bus_rtpc_parameter_edit.setText(str(payload.get("parameter_name", "")))
            self.bus_rtpc_target_combo.setCurrentText(str(payload.get("target", "BusVolumeDb")))
            self.bus_rtpc_scope_combo.setCurrentText(str(payload.get("scope", "Global")))
            self._refresh_bus_rtpc_curve_editor_ranges()
            self._set_curve_table_points(self.bus_rtpc_curve_table, payload.get("curve_points", []))
            self._sync_curve_interpolation_combo(self.bus_rtpc_curve_table, self.bus_rtpc_interpolation_combo)
            self._sync_curve_point_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin)
            self.bus_rtpc_notes_edit.setPlainText(str(payload.get("notes", "")))
        else:
            self.bus_rtpc_parameter_edit.clear()
            self.bus_rtpc_target_combo.setCurrentText("BusVolumeDb")
            self.bus_rtpc_scope_combo.setCurrentText("Global")
            self._refresh_bus_rtpc_curve_editor_ranges()
            self._set_curve_table_points(
                self.bus_rtpc_curve_table,
                self._default_curve_point_payloads(
                    self._rtpc_input_range(self.bus_rtpc_parameter_edit.text()),
                    self._rtpc_output_range(self.bus_rtpc_target_combo.currentText()),
                ),
            )
            self._sync_curve_interpolation_combo(self.bus_rtpc_curve_table, self.bus_rtpc_interpolation_combo)
            self._sync_curve_point_controls(self.bus_rtpc_curve_table, self.bus_rtpc_selected_input_spin, self.bus_rtpc_selected_output_spin)
            self.bus_rtpc_notes_edit.clear()
        if state_overrides and self.bus_state_list.currentRow() >= 0:
            payload = state_overrides[self.bus_state_list.currentRow()]
            self.bus_state_group_edit.setText(str(payload.get("group_name", "")))
            self.bus_state_name_edit.setText(str(payload.get("state_name", "")))
            self.bus_state_volume_spin.setValue(float(payload.get("volume_db", 0.0)))
            self.bus_state_pitch_spin.setValue(int(payload.get("pitch_cents", 0)))
            self.bus_state_mute_check.setChecked(bool(payload.get("is_muted", False)))
            self.bus_state_notes_edit.setPlainText(str(payload.get("notes", "")))
        else:
            self.bus_state_group_edit.clear()
            self.bus_state_name_edit.clear()
            self.bus_state_volume_spin.setValue(0.0)
            self.bus_state_pitch_spin.setValue(0)
            self.bus_state_mute_check.setChecked(False)
            self.bus_state_notes_edit.clear()
        self.bus_rtpc_remove_button.setEnabled(bool(rtpc_bindings))
        self.bus_state_remove_button.setEnabled(bool(state_overrides))
        self._loading_event = False

    def _sync_bus_binding_editor_to_state(self, bus_config: dict[str, object] | None) -> None:
        if not isinstance(bus_config, dict):
            return
        rtpc_bindings = list(bus_config.get("rtpc_bindings", []))
        state_overrides = list(bus_config.get("state_overrides", []))
        rtpc_row = self.bus_rtpc_list.currentRow()
        if 0 <= rtpc_row < len(rtpc_bindings):
            rtpc_bindings[rtpc_row] = {
                "parameter_name": self.bus_rtpc_parameter_edit.text().strip(),
                "target": self.bus_rtpc_target_combo.currentText(),
                "scope": self.bus_rtpc_scope_combo.currentText(),
                "curve_points": self._curve_table_points(self.bus_rtpc_curve_table),
                "notes": self.bus_rtpc_notes_edit.toPlainText().strip(),
            }
        state_row = self.bus_state_list.currentRow()
        if 0 <= state_row < len(state_overrides):
            state_overrides[state_row] = {
                "group_name": self.bus_state_group_edit.text().strip(),
                "state_name": self.bus_state_name_edit.text().strip(),
                "volume_db": float(self.bus_state_volume_spin.value()),
                "pitch_cents": int(self.bus_state_pitch_spin.value()),
                "is_muted": self.bus_state_mute_check.isChecked(),
                "notes": self.bus_state_notes_edit.toPlainText().strip(),
            }
        bus_config["rtpc_bindings"] = rtpc_bindings
        bus_config["state_overrides"] = state_overrides

    def _add_current_bus_binding(self, kind: str) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        current_config = self._project_bus_configs[row]
        self._sync_bus_binding_editor_to_state(current_config)
        if kind == "rtpc":
            current_config.setdefault("rtpc_bindings", []).append(self._default_bus_rtpc_binding_payload())
            self._load_bus_binding_editors(current_config)
            self.bus_rtpc_list.setCurrentRow(len(current_config.get("rtpc_bindings", [])) - 1)
        else:
            current_config.setdefault("state_overrides", []).append(self._state_override_payload({}))
            self._load_bus_binding_editors(current_config)
            self.bus_state_list.setCurrentRow(len(current_config.get("state_overrides", [])) - 1)
        self._emit_project_settings_changed()

    def _remove_current_bus_binding(self, kind: str) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        current_config = self._project_bus_configs[row]
        collection_key = "rtpc_bindings" if kind == "rtpc" else "state_overrides"
        list_widget = self.bus_rtpc_list if kind == "rtpc" else self.bus_state_list
        bindings = list(current_config.get(collection_key, []))
        binding_row = list_widget.currentRow()
        if binding_row < 0 or binding_row >= len(bindings):
            return
        del bindings[binding_row]
        current_config[collection_key] = bindings
        self._load_bus_binding_editors(current_config)
        if bindings:
            list_widget.setCurrentRow(min(binding_row, len(bindings) - 1))
        self._emit_project_settings_changed()

    def _update_source_browser_status(self) -> None:
        selected_entries = self.source_tree.selected_source_entries()
        entry = self.source_tree.current_source_entry()
        current_audio_id = self.audio_tree.current_audio_id() or self._active_audio_id or ""
        if not selected_entries or not entry:
            self.source_browser_status_label.setText("选择一个源音频，可查看路径、引用 Audio 和缺失状态。")
            self.source_browser_locate_button.setEnabled(False)
            self.source_browser_copy_button.setEnabled(False)
            self.source_browser_locate_event_button.setEnabled(False)
            self.source_browser_add_to_event_button.setEnabled(False)
            return

        source_path = str(entry.get("source_path", "")).strip()
        reference_count = int(entry.get("reference_count", 0))
        state_fragments: list[str] = []
        if bool(entry.get("missing", False)):
            state_fragments.append("文件缺失")
        if bool(entry.get("unreferenced", False)):
            state_fragments.append("当前未被 Audio 引用")
        audio_ids = [str(value) for value in entry.get("audio_ids", []) if str(value).strip()]
        if current_audio_id and current_audio_id in audio_ids:
            state_fragments.append("当前 Audio 已绑定")
        state_text = "；".join(state_fragments) if state_fragments else "状态正常"
        audio_preview = "、".join(audio_ids[:4]) if audio_ids else "-"
        if len(selected_entries) > 1:
            self.source_browser_status_label.setText(
                f"已选择 {len(selected_entries)} 条源音频\n当前项：{source_path}\n引用 Audio {reference_count} 个：{audio_preview}\n{state_text}"
            )
        else:
            self.source_browser_status_label.setText(
                f"{source_path}\n引用 Audio {reference_count} 个：{audio_preview}\n{state_text}"
            )
        self.source_browser_locate_button.setEnabled(bool(source_path))
        self.source_browser_copy_button.setEnabled(any(str(item.get("source_path", "")).strip() for item in selected_entries))
        self.source_browser_locate_event_button.setEnabled(bool(audio_ids))
        self.source_browser_add_to_event_button.setEnabled(
            any(str(item.get("source_path", "")).strip() for item in selected_entries) and bool(current_audio_id)
        )

    def _locate_selected_source_asset(self) -> None:
        entry = self.source_tree.current_source_entry()
        if not entry:
            self.report_detail_label.setText("当前没有选中的源音频。")
            return
        source_path = str(entry.get("source_path", "")).strip()
        if not source_path:
            self.report_detail_label.setText("当前源音频没有可定位的源路径。")
            return
        if os.path.exists(source_path):
            os.startfile(source_path)
            self.report_detail_label.setText(f"已定位源文件：{source_path}")
        else:
            self.report_detail_label.setText(f"源文件不存在：{source_path}")
        self.report_detail_label.setToolTip(source_path)

    def _copy_selected_source_asset_path(self) -> None:
        entries = self.source_tree.selected_source_entries()
        if not entries:
            return
        source_paths = [str(entry.get("source_path", "")).strip() for entry in entries if str(entry.get("source_path", "")).strip()]
        if not source_paths:
            return
        copied_text = "\n".join(source_paths)
        QApplication.clipboard().setText(copied_text)
        if len(source_paths) == 1:
            self.report_detail_label.setText(f"已复制源路径：{source_paths[0]}")
            self.report_detail_label.setToolTip(source_paths[0])
        else:
            self.report_detail_label.setText(f"已复制 {len(source_paths)} 条源路径。")
            self.report_detail_label.setToolTip(copied_text)

    def _follow_current_event_bus(self) -> None:
        self._project_bus_selection_overridden = False
        self._sync_current_event_bus_selection(force=True)
        self.set_active_property_category("音频属性")
        self._set_workspace_mode("buses")
        self._update_object_bus_status()

    def _show_tree_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if item is None:
            item = self.tree.currentItem()
        selected_event_ids = self.selected_tree_event_ids()
        has_event_target = bool(selected_event_ids)
        has_source_binding_target = False
        menu = QMenu(self)
        new_folder_action = menu.addAction("新建文件夹")
        new_event_action = menu.addAction("新建事件")
        import_action = menu.addAction("批量导入音频为事件...")
        menu.addSeparator()
        bulk_bus_action = menu.addAction(f"批量改事件{WWISE_OUTPUT_BUS_LABEL}...")
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        copy_id_action = menu.addAction("复制对象标识")
        property_action = menu.addAction("打开属性编辑器")
        contents_action = menu.addAction("打开内容编辑器")
        report_action = menu.addAction("打开问题中心")
        contents_action.setEnabled(False)
        bulk_bus_action.setEnabled(bool(selected_event_ids))
        if item is not None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if payload is not None and payload[0] == "event":
                has_event_target = True
                contents_action.setEnabled(True)
            elif payload is not None and payload[0] == "source_binding":
                has_source_binding_target = True
                contents_action.setEnabled(True)
                rename_action.setEnabled(False)
        preview_actions: dict[QAction, str] = {}
        preview_specs = self._tree_preview_context_actions(has_event_target=has_event_target)
        if preview_specs:
            menu.addSeparator()
            for action_key, label in preview_specs:
                preview_action = menu.addAction(label)
                preview_actions[preview_action] = action_key
        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        if action is None:
            return
        if action == new_folder_action:
            self.createFolderRequested.emit()
        elif action == new_event_action:
            self.createEventRequested.emit()
        elif action == import_action:
            file_paths = self.ask_import_audio_event_paths()
            if not file_paths:
                return
            template = self.ask_event_import_template([self.default_bus_combo.itemText(i) for i in range(self.default_bus_combo.count())], self.default_bus_combo.currentText())
            if template is None:
                return
            target_folder_id = None
            if item is not None:
                payload = item.data(0, Qt.ItemDataRole.UserRole)
                if payload is not None:
                    if payload[0] == "folder":
                        target_folder_id = payload[1]
                    elif payload[0] == "event" and item.parent() is not None:
                        parent_payload = item.parent().data(0, Qt.ItemDataRole.UserRole)
                        if parent_payload is not None:
                            target_folder_id = parent_payload[1]
                    elif payload[0] == "source_binding":
                        current_item = item.parent()
                        while current_item is not None:
                            parent_payload = current_item.data(0, Qt.ItemDataRole.UserRole)
                            if parent_payload is not None and parent_payload[0] == "folder":
                                target_folder_id = parent_payload[1]
                                break
                            current_item = current_item.parent()
            self.importAudioAsEventsRequested.emit(file_paths, target_folder_id, template)
        elif action == bulk_bus_action:
            self._request_bulk_event_bus()
        elif action == rename_action:
            self.renameSelectedRequested.emit()
        elif action == delete_action:
            self.deleteSelectedRequested.emit()
        elif action == copy_id_action:
            self._handle_copy_shortcut()
        elif action == property_action:
            payload = self._selected_tree_payload()
            if payload is not None and payload[0] in {"event", "source_binding"}:
                self.set_active_property_category("事件")
            else:
                self.set_active_property_category("工程")
        elif action == contents_action:
            self.set_active_contents_category("片段")
            if has_source_binding_target:
                self.select_clip_ids(self.selected_tree_source_binding_clip_ids())
        elif action == report_action:
            self.show_report_tab(1)
        elif action in preview_actions:
            self._dispatch_tree_preview_context_action(preview_actions[action])

    def _show_clip_context_menu(self, position) -> None:
        menu = QMenu(self)
        preview_action = menu.addAction("试听片段")
        copy_action = menu.addAction("复制资源键")
        copy_clip_id_action = menu.addAction("复制片段 ID")
        locate_action = menu.addAction("定位源文件")
        focus_detail_action = menu.addAction("聚焦片段详情")
        menu.addSeparator()
        bulk_weight_action = menu.addAction("批量设权重")
        rename_action = menu.addAction("批量重命名")
        remove_action = menu.addAction("移除片段")
        has_selection = bool(self.selected_clip_ids())
        for action in [preview_action, copy_action, copy_clip_id_action, locate_action, focus_detail_action, bulk_weight_action, rename_action, remove_action]:
            action.setEnabled(has_selection)
        action = menu.exec(self.clip_table.viewport().mapToGlobal(position))
        if action == preview_action:
            self._request_selected_clip_preview()
        elif action == copy_action:
            self._copy_selected_clip_asset_keys()
        elif action == copy_clip_id_action:
            self._copy_selected_clip_ids()
        elif action == locate_action:
            self._locate_selected_clip_source()
        elif action == focus_detail_action:
            self._handle_open_shortcut()
        elif action == bulk_weight_action:
            self._request_bulk_weight()
        elif action == rename_action:
            self._request_batch_rename()
        elif action == remove_action:
            self._request_remove_clips()

    def _request_remove_clips(self) -> None:
        clip_ids = self.selected_clip_ids()
        if clip_ids:
            self.removeClipsRequested.emit(clip_ids)

    def set_history_actions_enabled(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo)
        self.redo_button.setEnabled(can_redo)

    def _request_bulk_weight(self) -> None:
        value = self.ask_bulk_weight()
        if value is not None:
            self.bulkWeightRequested.emit(value)

    def _request_bulk_event_bus(self) -> None:
        event_ids = self.selected_tree_event_ids()
        if not event_ids:
            self.report_detail_label.setText("请先在工程浏览器里选择至少一个事件。")
            return
        bus_names = [self.default_bus_combo.itemText(index) for index in range(self.default_bus_combo.count())]
        current_bus = self.bus_combo.currentText() or self.default_bus_combo.currentText()
        bus_name = self.ask_batch_event_bus(bus_names, current_bus)
        if bus_name:
            self.bulkEventBusRequested.emit(bus_name)

    def _request_batch_rename(self) -> None:
        result = self.ask_batch_rename()
        if result is not None:
            self.batchRenameRequested.emit(result[0], result[1])

    def _search_next_tree_event(self) -> None:
        query = self.tree_filter_edit.text().strip()
        if not query:
            self.report_detail_label.setText("先输入事件关键字，再执行搜索。")
            return
        event_id = self.tree.select_next_matching_event(query)
        if event_id is None:
            self.report_detail_label.setText(f"没有找到匹配“{query}”的事件。")
            return
        self.report_detail_label.setText(f"已定位事件：{event_id}")
        self.report_detail_label.setToolTip(event_id)

    def _advance_explorer_search(self) -> None:
        active_page = self._active_explorer_page_key()
        if active_page == "buses":
            self._search_next_project_bus()
            return
        if active_page == "sources":
            self._search_next_source_asset()
            return
        if active_page == "audios":
            self._search_next_audio_object()
            return
        self._search_next_tree_event()

    def _search_next_audio_object(self) -> None:
        query = self.tree_filter_edit.text().strip()
        if not query:
            self.report_detail_label.setText("先输入 Audio 关键字，再执行搜索。")
            return
        audio_id = self.audio_tree.select_next_matching_audio(query)
        if audio_id is None:
            self.report_detail_label.setText(f"没有找到匹配“{query}”的 Audio。")
            return
        self.report_detail_label.setText(f"已定位 Audio：{audio_id}")
        self.report_detail_label.setToolTip(audio_id)

    def _search_next_project_bus(self) -> None:
        query = self.tree_filter_edit.text().strip().lower()
        if not query:
            self.report_detail_label.setText("先输入总线关键字，再执行搜索。")
            return
        matching_items = self._visible_project_bus_items(query)
        if not matching_items:
            self.report_detail_label.setText(f"没有找到匹配“{query}”的总线。")
            return

        current_bus_name = self.current_project_bus_name()
        target_index = 0
        if current_bus_name:
            for index, item in enumerate(matching_items):
                bus_name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
                if bus_name == current_bus_name:
                    target_index = (index + 1) % len(matching_items)
                    break

        target_item = matching_items[target_index]
        self.project_bus_list.setCurrentItem(target_item)
        bus_name = str(target_item.data(0, Qt.ItemDataRole.UserRole) or "")
        self.report_detail_label.setText(f"已定位总线：{bus_name}")
        self.report_detail_label.setToolTip(bus_name)

    def _visible_project_bus_items(self, query: str) -> list[QTreeWidgetItem]:
        items: list[QTreeWidgetItem] = []
        pending = [self.project_bus_list.topLevelItem(index) for index in range(self.project_bus_list.topLevelItemCount())]
        while pending:
            item = pending.pop(0)
            if item is None:
                continue
            bus_name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            if not item.isHidden() and (query in item.text(0).lower() or query in bus_name.lower()):
                items.append(item)
            for child_index in range(item.childCount()):
                pending.append(item.child(child_index))
        return items

    def _search_next_source_asset(self) -> None:
        query = self.tree_filter_edit.text().strip()
        if not query:
            self.report_detail_label.setText("先输入源音频关键字，再执行搜索。")
            return
        source_path = self.source_tree.select_next_matching_asset(query)
        if not source_path:
            self.report_detail_label.setText(f"没有找到匹配“{query}”的源音频。")
            return
        self.report_detail_label.setText(f"已定位源音频：{source_path}")
        self.report_detail_label.setToolTip(source_path)

    def _request_bulk_clip_properties(self) -> None:
        self.bulkClipPropertiesRequested.emit(self.current_bulk_clip_form_data())

    def _request_sort_clips(self) -> None:
        field_name, ascending = self.current_clip_sort_request()
        self.sortClipsRequested.emit(field_name, ascending)

    def _request_open_recent_project(self) -> None:
        file_path = self.recent_projects_combo.currentText().strip()
        if file_path:
            self.openRecentProjectRequested.emit(file_path)

    def _request_export_root_browse(self) -> None:
        selected_path = self.ask_export_root_path(self.export_root_edit.text().strip())
        if not selected_path:
            return
        self.export_root_edit.setText(selected_path)
        self.export_root_edit.setModified(True)
        self._emit_project_settings_changed()

    def _build_toolbar_section_label(self, title: str) -> QLabel:
        label = QLabel(title)
        label.setProperty("role", "toolbarSection")
        return label

    def _build_report_jump_button(self, title: str, tab_index: int) -> QToolButton:
        button = QToolButton()
        button.setText(title)
        button.setAutoRaise(True)
        button.setProperty("role", "reportJump")
        button.clicked.connect(lambda checked=False, index=tab_index: self.show_report_tab(index))
        return button

    def _build_panel_header(self, title: str, panel_key: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("PanelHeader")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(10, 6, 10, 6)
        panel_icon = QLabel()
        panel_icon_map = {
            "explorer": load_app_icon("folder"),
            "property": load_app_icon("event"),
            "contents": load_app_icon("content"),
            "meter": load_app_icon("audio"),
            "log": load_app_icon("report"),
        }
        icon = panel_icon_map.get(panel_key, QIcon())
        if not icon.isNull():
            panel_icon.setPixmap(icon.pixmap(QSize(16, 16)))
        title_label = QLabel(title)
        title_label.setProperty("role", "panelTitle")
        focus_button = QToolButton()
        focus_button.setIcon(load_app_icon("focus_panel"))
        focus_button.setToolTip(f"放大{title}")
        focus_button.clicked.connect(lambda: self.focus_panel(panel_key))
        detach_button = None
        if panel_key == "explorer":
            detach_button = QToolButton()
            detach_button.setIcon(load_app_icon("open_project"))
            detach_button.setToolTip("分离或重新停靠工程浏览器")
            detach_button.clicked.connect(self.toggle_explorer_detached)
        reset_button = QToolButton()
        reset_button.setIcon(load_app_icon("reset_layout"))
        reset_button.setToolTip("恢复默认布局")
        reset_button.clicked.connect(self.restore_default_layout)
        layout.addWidget(panel_icon)
        layout.addWidget(title_label)
        layout.addStretch(1)
        if detach_button is not None:
            layout.addWidget(detach_button)
        layout.addWidget(focus_button)
        layout.addWidget(reset_button)
        return panel

    def _apply_button_icons(self) -> None:
        icon_pairs = [
            (self.new_project_button, load_app_icon("new_project")),
            (self.open_project_button, load_app_icon("open_project")),
            (self.save_project_button, load_app_icon("save_project")),
            (self.save_as_project_button, load_app_icon("save_project")),
            (self.new_folder_button, load_app_icon("folder")),
            (self.new_event_button, load_app_icon("event")),
            (self.bulk_event_bus_button, load_app_icon("bus")),
            (self.preview_button, load_app_icon("play")),
            (self.stop_preview_event_button, load_app_icon("validate")),
            (self.stop_preview_bus_button, load_app_icon("audio")),
            (self.loudness_scan_button, load_app_icon("audio")),
            (self.validate_button, load_app_icon("validate")),
            (self.build_button, load_app_icon("generate")),
            (self.import_clips_button, load_app_icon("content")),
            (self.open_recent_project_button, load_app_icon("open_project")),
            (self.apply_default_bus_button, load_app_icon("bus")),
            (self.project_bus_add_button, load_app_icon("bus")),
            (self.project_bus_remove_button, load_app_icon("delete")),
            (self.project_bus_browser_button, load_app_icon("bus")),
            (self.source_browser_locate_button, load_app_icon("open_project")),
            (self.source_browser_copy_button, load_app_icon("generate")),
            (self.source_browser_locate_event_button, load_app_icon("event")),
            (self.source_browser_add_to_event_button, load_app_icon("content")),
            (self.object_preview_button, load_app_icon("play")),
            (self.object_contents_button, load_app_icon("content")),
            (self.object_follow_bus_button, load_app_icon("bus")),
            (self.object_report_button, load_app_icon("validate")),
            (self.clip_preview_button, load_app_icon("play")),
            (self.clip_copy_asset_key_button, load_app_icon("generate")),
            (self.clip_locate_source_button, load_app_icon("open_project")),
            (self.inline_bus_new_button, load_app_icon("bus")),
            (self.inline_bus_set_default_button, load_app_icon("generate")),
            (self.inline_bus_to_master_button, load_app_icon("route")),
            (self.inline_bus_open_parent_button, load_app_icon("navigate_parent")),
            (self.project_bus_focus_audio_button, load_app_icon("audio")),
            (self.command_button, load_app_icon("focus_panel")),
            (self.gamesync_parameter_add_button, load_app_icon("rtpc")),
            (self.gamesync_parameter_remove_button, load_app_icon("delete")),
            (self.gamesync_state_add_button, load_app_icon("state")),
            (self.gamesync_state_remove_button, load_app_icon("delete")),
            (self.gamesync_switch_add_button, load_app_icon("switch")),
            (self.gamesync_switch_remove_button, load_app_icon("delete")),
            (self.event_rtpc_add_button, load_app_icon("rtpc")),
            (self.event_rtpc_remove_button, load_app_icon("delete")),
            (self.event_rtpc_add_point_button, load_app_icon("curve")),
            (self.event_rtpc_remove_point_button, load_app_icon("delete")),
            (self.event_state_add_button, load_app_icon("state")),
            (self.event_state_remove_button, load_app_icon("delete")),
            (self.event_switch_add_button, load_app_icon("switch")),
            (self.event_switch_remove_button, load_app_icon("delete")),
            (self.bus_rtpc_add_button, load_app_icon("rtpc")),
            (self.bus_rtpc_remove_button, load_app_icon("delete")),
            (self.bus_rtpc_add_point_button, load_app_icon("curve")),
            (self.bus_rtpc_remove_point_button, load_app_icon("delete")),
            (self.bus_state_add_button, load_app_icon("state")),
            (self.bus_state_remove_button, load_app_icon("delete")),
        ]
        for button, icon in icon_pairs:
            if not icon.isNull():
                button.setIcon(icon)
        transport_icon_pairs = [
            (self.preview_transport_play_button, load_app_icon("play")),
            (self.preview_transport_restart_button, load_app_icon("restart")),
            (self.preview_transport_stop_button, load_app_icon("stop")),
            (self.open_loudness_view_button, load_app_icon("audio")),
        ]
        for button, icon in transport_icon_pairs:
            if not icon.isNull():
                button.setIcon(icon)
            button.setIconSize(QSize(22, 22))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.set_preview_transport_state(
            self._preview_transport_state,
            has_target=self._preview_transport_has_target,
            can_replay=self._preview_transport_can_replay,
        )
        self.tree_search_button.setIcon(load_app_icon("open_project"))
        self.tree_search_button.setToolTip("定位下一个匹配的事件")
        self.global_search_button.setIcon(load_app_icon("open_project"))
        self.global_search_button.setToolTip("搜索并定位当前工程中的对象")
        self.command_button.setToolTip("打开导航与隐藏动作面板（Ctrl+Shift+P）")
        self.object_parent_button.setIcon(load_app_icon("navigate_parent"))
        self.object_parent_button.setToolTip("跳转到父级")
        self.object_parent_button.setAutoRaise(True)
        self.reference_parent_value_button.setIcon(load_app_icon("navigate_parent"))
        self.reference_bus_value_button.setIcon(load_app_icon("bus"))
        self.reference_assets_value_button.setIcon(load_app_icon("content"))
        self.reference_generation_value_button.setIcon(load_app_icon("generate"))
        self.zoom_out_button.setText("A-")
        self.zoom_out_button.setIcon(load_app_icon("content"))
        self.zoom_out_button.setToolTip("缩小界面")
        self.zoom_reset_button.setText("100%")
        self.zoom_reset_button.setIcon(load_app_icon("reset_layout"))
        self.zoom_reset_button.setToolTip("重置界面缩放")
        self.zoom_in_button.setText("A+")
        self.zoom_in_button.setIcon(load_app_icon("focus_panel"))
        self.zoom_in_button.setToolTip("放大界面")
        self.reset_layout_button.setText("布局")
        self.reset_layout_button.setIcon(load_app_icon("reset_layout"))
        self.reset_layout_button.setToolTip("恢复默认布局")
        sidebar_icon_map = {
            "home": load_app_icon("app"),
            "resources": load_app_icon("content"),
            "events": load_app_icon("event"),
            "buses": load_app_icon("bus"),
            "gamesync": load_app_icon("curve"),
            "validation": load_app_icon("validate"),
            "build": load_app_icon("generate"),
            "results": load_app_icon("report"),
        }
        for mode, icon in sidebar_icon_map.items():
            button = self.task_sidebar.button(mode)
            if button is not None and not icon.isNull():
                button.setIcon(icon)

    def _apply_clip_filter(self, text: str) -> None:
        normalized = text.strip().lower()
        for row in range(self.clip_table.rowCount()):
            row_text = " ".join(
                (self.clip_table.item(row, column).text() if self.clip_table.item(row, column) is not None else "")
                for column in range(min(9, self.clip_table.columnCount()))
            ).lower()
            self.clip_table.setRowHidden(row, bool(normalized and normalized not in row_text))

    def _apply_wwise_style(self) -> None:
        scale = self._ui_scale
        toolbar_padding = int(6 * scale)
        button_padding_v = int(6 * scale)
        button_padding_h = int(12 * scale)
        radius = int(4 * scale)
        group_radius = int(8 * scale)
        hero_radius = int(10 * scale)
        field_padding = int(4 * scale)
        tab_padding_v = int(8 * scale)
        tab_padding_h = int(14 * scale)
        object_type_size = int(11 * scale)
        object_title_size = int(16 * scale)
        self._preview_transport_compact_min_width = max(236, int(248 * scale))
        self._preview_transport_compact_max_width = max(self._preview_transport_compact_min_width + 40, int(320 * scale))
        self._preview_transport_expanded_min_width = max(300, int(312 * scale))
        self._preview_transport_expanded_max_width = max(self._preview_transport_expanded_min_width + 40, int(420 * scale))
        transport_button_size = max(34, int(38 * scale))
        transport_button_radius = transport_button_size // 2
        transport_strip_radius = max(10, int(12 * scale))
        transport_toggle_size = max(22, int(24 * scale))
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background-color: #262a30;
                color: #dfe6ee;
            }}
            QToolBar {{
                background-color: #171a1f;
                border-bottom: 1px solid #393f48;
                spacing: 8px;
                padding: {toolbar_padding}px;
            }}
            QPushButton, QToolButton {{
                background-color: #353c45;
                border: 1px solid #596372;
                border-radius: {radius}px;
                padding: {button_padding_v}px {button_padding_h}px;
                min-height: 24px;
                font-weight: 500;
            }}
            QPushButton:hover, QToolButton:hover {{
                background-color: #495463;
            }}
            QPushButton:pressed, QToolButton:pressed {{
                background-color: #2b3138;
            }}
            QPushButton[role="clipCompactButton"] {{
                padding: 4px 8px;
                min-height: 20px;
            }}
            QPushButton[role="activityCompactButton"] {{
                padding: 3px 8px;
                min-height: 18px;
            }}
            #PreviewTransportFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #20262d, stop:1 #29313a);
                border: 1px solid #445160;
                border-radius: {transport_strip_radius}px;
            }}
            #PreviewTransportFrame[transportState="playing"] {{
                border-color: #5f8db7;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #223648, stop:1 #2a4257);
            }}
            #PreviewTransportFrame[transportState="paused"] {{
                border-color: #a8844d;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #352c1f, stop:1 #403325);
            }}
            #PreviewMetricsFrame {{
                background: transparent;
                border: none;
            }}
            #PreviewRtpcTransportFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1f2a34, stop:1 #253441);
                border: 1px solid #4a6076;
                border-radius: {group_radius}px;
            }}
            #PreviewGameSyncModesFrame {{
                background-color: #1d252d;
                border: 1px solid #445160;
                border-radius: {group_radius}px;
            }}
            #PreviewMetricColumn {{
                background-color: #1e242b;
                border: 1px solid #3f4d5c;
                border-radius: {group_radius}px;
            }}
            #PreviewMetricStat {{
                background-color: #262d35;
                border: 1px solid #394554;
                border-radius: {radius}px;
            }}
            QToolButton[role="previewTransportButton"] {{
                padding: 0px;
                min-width: {transport_button_size}px;
                max-width: {transport_button_size}px;
                min-height: {transport_button_size}px;
                max-height: {transport_button_size}px;
                border-radius: {transport_button_radius}px;
                border: 1px solid transparent;
                background-color: transparent;
            }}
            QToolButton[role="previewTransportButton"]:hover {{
                background-color: #465361;
                border-color: #738599;
            }}
            QToolButton[role="previewTransportButton"]:pressed {{
                background-color: #25303a;
                border-color: #5e6d7f;
            }}
            QToolButton[role="previewTransportButton"][transportKind="primary"] {{
                background-color: #2b4154;
                border-color: #5d85ab;
            }}
            QToolButton[role="previewTransportButton"][transportKind="primary"][transportState="active"] {{
                background-color: #3c6387;
                border-color: #98cdfd;
            }}
            QToolButton[role="previewTransportButton"][transportKind="secondary"][transportState="active"] {{
                background-color: #5a482d;
                border-color: #d0a15d;
                color: #f3ddbf;
            }}
            QToolButton[role="previewTransportButton"][transportKind="danger"] {{
                color: #efc5c0;
            }}
            QToolButton[role="previewTransportButton"][transportKind="danger"]:hover {{
                background-color: #573538;
                border-color: #a46e74;
            }}
            QToolButton[role="previewTransportButton"][transportKind="monitor"] {{
                color: #c8d6e6;
            }}
            QToolButton[role="previewTransportButton"]:disabled {{
                background-color: transparent;
                border: 1px solid transparent;
                color: #708094;
            }}
            QToolButton[role="previewTransportToggle"] {{
                padding: 0px;
                min-width: {transport_toggle_size}px;
                max-width: {transport_toggle_size}px;
                min-height: {transport_toggle_size}px;
                max-height: {transport_toggle_size}px;
                border-radius: {radius}px;
                background-color: #20262d;
                border: 1px solid #445160;
            }}
            QToolButton[role="previewTransportToggle"]:hover {{
                background-color: #28323d;
                border-color: #6e8296;
            }}
            QToolButton[role="previewTransportToggle"][expanded="true"] {{
                background-color: #2a3948;
                border-color: #7da3c8;
            }}
            QSpinBox[role="clipCompactSpin"], QLineEdit[role="clipCompactField"] {{
                min-height: 22px;
                padding: 2px 6px;
            }}
            QLabel[role="clipPreviewHint"] {{
                color: #b9c7d8;
                font-size: 11px;
            }}
            #HeroPanel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1d2228, stop:1 #29323d);
                border: 1px solid #425162;
                border-radius: {hero_radius}px;
            }}
            #HeroPanel QLabel {{
                background: transparent;
                border: none;
            }}
            #ObjectHeader {{
                background-color: #1f242a;
                border: 1px solid #4a5563;
                border-radius: {group_radius}px;
            }}
            #PanelHeader {{
                background-color: #171a1f;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
            }}
            #WorkspaceStatusBar, #ReportHeader {{
                background-color: #1b2026;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
            }}
            #AppShell {{
                background-color: #262a30;
                border: none;
            }}
            #TopAppBar {{
                background-color: #171a1f;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
            }}
            #WelcomeHero {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #182129, stop:1 #283849);
                border: 1px solid #4c6278;
                border-radius: {hero_radius}px;
            }}
            #WorkspaceActionBar {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1c2229, stop:1 #222b34);
                border: 1px solid #506172;
                border-radius: {group_radius}px;
            }}
            #WorkspaceOverviewPanel {{
                background: transparent;
                border: none;
                min-width: 318px;
            }}
            #WorkspaceOverviewCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1c232a, stop:1 #222c35);
                border: 1px solid #4d6070;
                border-radius: {group_radius}px;
            }}
            #EmphasisCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1b232b, stop:1 #24303a);
                border: 1px solid #5a7085;
                border-radius: {group_radius}px;
            }}
            #EmptyStateCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #172028, stop:1 #1f2a34);
                border: 1px dashed #62809d;
                border-radius: {group_radius}px;
            }}
            #ModeIntroCard, #ActivityPanel {{
                background-color: #1b2026;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
            }}
            #TaskSidebar {{
                background-color: #1b2026;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
                min-width: 164px;
                max-width: 196px;
            }}
            #InlineBusHeader {{
                background-color: #1d232b;
                border: 1px solid #41505f;
                border-radius: {group_radius}px;
            }}
            #MeterStatCard, #ChannelMeter {{
                background-color: #1f242a;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
            }}
            #CollapsibleSection {{
                background-color: transparent;
                border: none;
            }}
            QLabel {{
                color: #c8d0da;
            }}
            QLabel[role="badge"] {{
                color: #8fc7ff;
            }}
            QLabel[role="objectType"] {{
                color: #87a8c5;
                font-size: {object_type_size}px;
                text-transform: uppercase;
            }}
            QLabel[role="objectTitle"] {{
                color: #edf3f9;
                font-size: {object_title_size}px;
                font-weight: 700;
            }}
            QLabel[role="panelTitle"] {{
                color: #edf3f9;
                font-weight: 600;
            }}
            QLabel[role="toolbarSection"] {{
                color: #8aa4bf;
                font-size: {object_type_size}px;
                font-weight: 700;
                padding: 0 4px;
            }}
            QLabel[role="sidebarTitle"] {{
                color: #8aa4bf;
                font-size: {object_type_size}px;
                font-weight: 700;
                padding: 2px 4px 6px 4px;
            }}
            QLabel[role="appTitle"] {{
                color: #9ec6f0;
                font-size: {object_type_size + 1}px;
                font-weight: 700;
            }}
            QLabel[role="appProjectTitle"] {{
                color: #edf3f9;
                font-size: {object_title_size}px;
                font-weight: 700;
            }}
            QLabel[role="appProjectPath"] {{
                color: #8f9ba9;
            }}
            QLabel[role="appMetaCaption"] {{
                color: #7f8a97;
                font-size: {object_type_size}px;
            }}
            QLabel[role="appModeTitle"] {{
                color: #dce8f5;
                font-size: {object_title_size - 1}px;
                font-weight: 600;
            }}
            QLabel[role="welcomeTitle"] {{
                color: #f2f7fb;
                font-size: {object_title_size + 4}px;
                font-weight: 700;
            }}
            QLabel[role="welcomeDescription"], QLabel[role="modeCardDescription"] {{
                color: #b9c7d6;
            }}
            QLabel[role="modeCardTitle"] {{
                color: #eef5fb;
                font-size: {object_title_size - 1}px;
                font-weight: 600;
            }}
            QLabel[role="workspaceSectionTitle"] {{
                color: #f0f6fc;
                font-size: {object_title_size}px;
                font-weight: 700;
            }}
            QLabel[role="workspaceSectionSummary"] {{
                color: #b9c7d6;
            }}
            QLabel[role="workspaceChecklistLine"] {{
                color: #c2cfdb;
            }}
            QLabel[role="emptyStateTitle"] {{
                color: #eef6fe;
                font-size: {object_title_size - 1}px;
                font-weight: 700;
            }}
            QLabel[role="emptyStateBody"] {{
                color: #b8c9d9;
            }}
            QLabel[role="cardEyebrow"] {{
                color: #8da9c5;
                font-size: {object_type_size - 1}px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }}
            QLabel[role="cardIconBubble"] {{
                background-color: #2b3947;
                border: 1px solid #6f8aa4;
                border-radius: 18px;
                padding: 0px;
            }}
            QLabel[role="cardIconBubble"][cardTone="event"] {{
                background-color: #21374a;
                border-color: #77a9d6;
            }}
            QLabel[role="cardIconBubble"][cardTone="content"] {{
                background-color: #213844;
                border-color: #75b4c8;
            }}
            QLabel[role="cardIconBubble"][cardTone="bus"] {{
                background-color: #233729;
                border-color: #7fcf95;
            }}
            QLabel[role="cardIconBubble"][cardTone="validate"] {{
                background-color: #463027;
                border-color: #d4a36f;
            }}
            QLabel[role="cardIconBubble"][cardTone="generate"] {{
                background-color: #4b3123;
                border-color: #e0ac73;
            }}
            QLabel[role="cardIconBubble"][cardTone="audio"] {{
                background-color: #2b314a;
                border-color: #8fa2de;
            }}
            QLabel[role="cardIconBubble"][cardTone="report"] {{
                background-color: #2b3842;
                border-color: #7eb3d3;
            }}
            QLabel[role="cardIconBubble"][cardTone="app"] {{
                background-color: #3a2f22;
                border-color: #d0a26f;
            }}
            QLabel[role="meterTitle"] {{
                color: #8e9aa8;
                font-size: {object_type_size}px;
            }}
            QLabel[role="meterValue"] {{
                color: #49d17d;
                font-size: {object_title_size + 6}px;
                font-weight: 700;
            }}
            QLabel[role="meterInlineValue"] {{
                color: #edf3f9;
                font-size: {object_title_size - 1}px;
                font-weight: 600;
            }}
            QLabel[role="meterUnit"] {{
                color: #7f8a97;
            }}
            QLabel[role="meterContext"] {{
                color: #b5c4d4;
            }}
            QLabel[role="previewTransportTitle"] {{
                color: #eef6fd;
                font-size: {object_title_size - 1}px;
                font-weight: 700;
            }}
            QLabel[role="previewTransportDetail"] {{
                color: #9fb5ca;
            }}
            QLabel[role="previewTransportStatusChip"] {{
                background-color: #283442;
                border: 1px solid #5a6c80;
                border-radius: {radius}px;
                color: #dbe8f5;
                padding: 3px 8px;
                font-size: {object_type_size}px;
                font-weight: 700;
            }}
            QLabel[role="previewTransportStatusChip"][transportState="playing"] {{
                background-color: #21415d;
                border-color: #84c3ff;
                color: #eef7ff;
            }}
            QLabel[role="previewTransportStatusChip"][transportState="paused"] {{
                background-color: #493721;
                border-color: #d9aa69;
                color: #fff0d9;
            }}
            QLabel[role="previewTransportCaption"] {{
                color: #8ca4ba;
                font-size: {object_type_size}px;
                font-weight: 700;
            }}
            QLabel[role="previewTransportReadout"] {{
                background-color: #1a232b;
                border: 1px solid #5d7890;
                border-radius: {radius}px;
                color: #eff7ff;
                padding: 2px 8px;
                font-weight: 700;
            }}
            QSlider::groove:horizontal {{
                height: 6px;
                border-radius: 3px;
                background: #0f151a;
                border: 1px solid #34414d;
            }}
            QSlider::sub-page:horizontal {{
                border-radius: 3px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6099c7, stop:1 #89c0e8);
            }}
            QSlider::add-page:horizontal {{
                border-radius: 3px;
                background: #253240;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
                background: #dceaf7;
                border: 1px solid #5d7ea1;
            }}
            QSlider::handle:horizontal:hover {{
                background: #f2f8fd;
                border-color: #8fb6de;
            }}
            QLabel[role="previewMetricHeading"] {{
                color: #8aa4bf;
                font-size: {object_type_size}px;
                font-weight: 700;
            }}
            QLabel[role="previewMetricContext"] {{
                color: #edf3f9;
                font-weight: 600;
            }}
            QLabel[role="previewMetricCaption"] {{
                color: #7f8a97;
                font-size: {object_type_size}px;
            }}
            QLabel[role="previewMetricValue"] {{
                color: #d9e6f3;
                font-weight: 700;
            }}
            #PreviewTransportHeader {{
                background: transparent;
                border: none;
            }}
            QLabel[role="busHeaderChip"] {{
                background-color: #2b3440;
                border: 1px solid #536275;
                border-radius: {radius}px;
                color: #e4eef8;
                padding: {button_padding_v}px {button_padding_h}px;
                font-weight: 600;
            }}
            QLabel[role="topStatusChip"] {{
                background-color: #24303b;
        self._sync_preview_transport_presentation()
                border: 1px solid #55677a;
                border-radius: {radius}px;
                color: #e4eef8;
                padding: {button_padding_v}px {button_padding_h}px;
                font-weight: 600;
            }}
            QPushButton[role="taskNavButton"] {{
                text-align: left;
                background-color: #20262d;
                border: 1px solid #434f5c;
                border-radius: {group_radius}px;
                padding: {button_padding_v + 3}px {button_padding_h}px;
                min-height: 32px;
            }}
            QPushButton[role="taskNavButton"]:hover {{
                background-color: #2b3540;
            }}
            QPushButton[role="taskNavButton"]:checked {{
                background-color: #32404f;
                border-color: #7ca7d6;
                color: #f3f8fd;
            }}
            QPushButton[role="workspaceActionButton"] {{
                background-color: #24303b;
                border: 1px solid #566a7c;
                border-radius: {radius}px;
                padding: {button_padding_v}px {button_padding_h}px;
                min-height: 26px;
            }}
            QPushButton[role="workspaceActionButton"]:hover {{
                background-color: #2e3d4b;
            }}
            QPushButton[role="topSubtleButton"] {{
                background-color: #212830;
                border-color: #4b5a69;
            }}
            QPushButton[role="topSubtleButton"]:hover {{
                background-color: #2b3640;
            }}
            QPushButton[role="topAccentButton"] {{
                background-color: #23364a;
                border-color: #6f97c0;
                color: #eef6fd;
            }}
            QPushButton[role="topAccentButton"]:hover {{
                background-color: #2c4560;
            }}
            QPushButton[role="topPrimaryButton"] {{
                background-color: #8d5a34;
                border-color: #d29a64;
                color: #fff7ef;
                font-weight: 700;
            }}
            QPushButton[role="topPrimaryButton"]:hover {{
                background-color: #a0663b;
            }}
            QPushButton[role="workspaceShortcutButton"] {{
                background-color: #24303b;
                border: 1px solid #546677;
                border-radius: {radius}px;
                padding: {button_padding_v + 1}px {button_padding_h}px;
                min-height: 30px;
                text-align: left;
            }}
            QPushButton[role="workspaceShortcutButton"]:hover {{
                background-color: #30414f;
            }}
            QToolButton[role="reportJump"] {{
                background-color: transparent;
                border: 1px solid #4b5d70;
                border-radius: {radius}px;
                color: #d8e7f6;
                padding: {button_padding_v - 1}px {button_padding_h - 2}px;
                min-height: 20px;
            }}
            QToolButton[role="reportJump"]:hover {{
                background-color: #28323d;
            }}
            QToolButton[role="collapsibleHeader"] {{
                background-color: #171a1f;
                border: 1px solid #3f4854;
                border-radius: {group_radius}px;
                font-weight: 600;
                padding: {button_padding_v}px {button_padding_h}px;
            }}
            QToolButton[role="routeChip"] {{
                background-color: #222a33;
                border: 1px solid #4b5d70;
                border-radius: {radius}px;
                color: #d8e7f6;
                padding: {button_padding_v}px {button_padding_h}px;
                min-height: 22px;
            }}
            QToolButton[role="routeChip"]:hover {{
                background-color: #2b3947;
                border-color: #79a8d8;
            }}
            QToolButton[role="routeNode"] {{
                background-color: #222a33;
                border: 1px solid #4b5d70;
                border-radius: {group_radius}px;
                color: #d8e7f6;
                padding: {button_padding_v + 1}px {button_padding_h + 2}px;
                min-height: 38px;
                font-weight: 700;
                text-align: left;
            }}
            QToolButton[role="routeNode"]:hover {{
                background-color: #2c3947;
                border-color: #79a8d8;
            }}
            QToolButton[role="routeNode"][routeTone="current"] {{
                background-color: #233729;
                border-color: #7fcf95;
                color: #eefaf1;
            }}
            QToolButton[role="routeNode"][routeTone="master"] {{
                background-color: #3a2f22;
                border-color: #d0a26f;
                color: #fff4e8;
            }}
            QLabel[role="routeConnector"] {{
                color: #7f8a97;
                font-weight: 700;
                padding: 0px 2px;
            }}
            QLineEdit[role="topSearchField"] {{
                background-color: #12171c;
                border: 1px solid #5a7087;
                border-radius: {group_radius}px;
                padding: {field_padding + 2}px {button_padding_h}px;
                min-height: 28px;
            }}
            QToolButton[role="topSearchButton"] {{
                background-color: #253443;
                border: 1px solid #617990;
                border-radius: {group_radius}px;
                padding: {button_padding_v}px {button_padding_h - 2}px;
            }}
            QToolButton {{
                text-align: left;
            }}
            QGroupBox[title="{WWISE_MASTER_MIXER_TITLE}"] QLabel {{
                color: #b9c7d6;
            }}
            QGroupBox[title="{WWISE_PROPERTY_EDITOR_TITLE}"] QLabel {{
                background: transparent;
            }}
            QLineEdit::placeholder, QPlainTextEdit::placeholder {{
                color: #6f7d8a;
            }}
            QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget {{
                background-color: #14191f;
                border: 1px solid #495867;
                border-radius: {radius}px;
                color: #dfe6ee;
                selection-background-color: #5f83a9;
                padding: {field_padding}px;
            }}
            QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus {{
                border: 1px solid #7aa0c9;
            }}
            QTreeWidget[role="navigationTree"], QListWidget[role="resultList"] {{
                background-color: #161b21;
                border-color: #536679;
            }}
            QTableWidget[role="editorTable"] {{
                background-color: #171d24;
                border-color: #5a6f83;
                gridline-color: #32404e;
                alternate-background-color: #1c232b;
            }}
            QPlainTextEdit[role="resultSurface"] {{
                background-color: #11161b;
                border-color: #54697d;
                selection-background-color: #476685;
            }}
            QGroupBox {{
                border: 1px solid #4a5866;
                border-radius: {group_radius}px;
                margin-top: 12px;
                font-weight: 600;
                background-color: #20262d;
            }}
            QGroupBox[role="contentCardInner"] {{
                border: none;
                border-radius: 0px;
                margin-top: 0px;
                padding-top: 0px;
                background-color: transparent;
            }}
            QGroupBox[role="inlineRecentPreview"] {{
                border: none;
                border-radius: 0px;
                margin-top: 0px;
                padding-top: 0px;
                background-color: transparent;
            }}
            QGroupBox[role="contentCardInner"]::title {{
                color: transparent;
                left: 0px;
                padding: 0px;
                margin: 0px;
            }}
            QGroupBox[role="inlineRecentPreview"]::title {{
                color: transparent;
                left: 0px;
                padding: 0px;
                margin: 0px;
            }}
            #ActivityPreviewHost {{
                background: transparent;
                border: none;
            }}
            QFrame[role="contentCardInnerFrame"] {{
                background-color: transparent;
                border: none;
                border-radius: 0px;
            }}
            QFrame#ObjectHeader[role="contentCardInnerFrame"] QLabel {{
                background: transparent;
                border: none;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #eef4fb;
            }}
            QTabWidget::pane {{
                border: 1px solid #4f6172;
                border-radius: {group_radius}px;
                top: -1px;
                background-color: #1a2027;
            }}
            QTabBar::tab {{
                background: #1b2128;
                border: 1px solid #435262;
                border-bottom: none;
                border-top-left-radius: {radius}px;
                border-top-right-radius: {radius}px;
                padding: {tab_padding_v}px {tab_padding_h}px;
                margin-right: 4px;
                color: #b7c5d4;
            }}
            QTabBar::tab:selected {{
                background: #2d3945;
                color: #f2f7fb;
                border-color: #7599bf;
                font-weight: 700;
            }}
            QTabBar::tab:hover:!selected {{
                background: #24303a;
            }}
            QHeaderView::section {{
                background-color: #20262e;
                color: #d8e4ef;
                border: 1px solid #435262;
                padding: {field_padding}px;
                font-weight: 600;
            }}
            QListWidget::item, QTreeWidget::item, QTableWidget::item {{
                padding: {field_padding}px;
            }}
            QListWidget::item:selected, QTreeWidget::item:selected, QTableWidget::item:selected {{
                background-color: #33485f;
                color: #f6fbff;
            }}
            QListWidget[role="resultList"]::item {{
                border-radius: {radius}px;
                margin: 3px 2px;
                padding: {field_padding + 2}px;
            }}
            QTreeWidget::item:hover, QListWidget::item:hover {{
                background-color: #25313d;
            }}
            QSplitter::handle {{
                background-color: #1a2027;
            }}
            QSplitter::handle:hover {{
                background-color: #324354;
            }}
            QScrollBar:vertical {{
                background: #161b20;
                width: 10px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: #435565;
                min-height: 28px;
                border-radius: {radius}px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #587088;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
            QScrollBar:horizontal, QScrollBar::handle:horizontal,
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: transparent;
                border: none;
                height: 0px;
            }}
            QProgressBar {{
                background-color: #242a31;
                border: 1px solid #44505d;
                border-radius: {radius}px;
                width: 28px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                    stop:0 #304e74, stop:0.55 #49d17d, stop:1 #e7cf47);
                border-radius: {radius}px;
            }}
            """
        )
        self._apply_button_icons()
        self.project_badge.setProperty("role", "badge")
        self.object_type_label.setProperty("role", "objectType")
        self.object_name_label.setProperty("role", "objectTitle")
        self.object_event_bus_chip.setProperty("role", "busHeaderChip")
        self.object_bus_browser_chip.setProperty("role", "busHeaderChip")
        self.object_context_hint_label.setProperty("role", "meterContext")
        self.audio_meter_context_label.setProperty("role", "meterContext")
        self.validation_summary_label.setProperty("role", "meterContext")
        self.build_summary_label.setProperty("role", "meterContext")
        self.loudness_summary_label.setProperty("role", "meterContext")
        self.tree.setProperty("role", "navigationTree")
        self.project_bus_list.setProperty("role", "navigationTree")
        self.source_tree.setProperty("role", "navigationTree")
        self.clip_table.setProperty("role", "editorTable")
        self.validation_issue_list.setProperty("role", "resultList")
        self.build_issue_list.setProperty("role", "resultList")
        self.loudness_issue_list.setProperty("role", "resultList")
        self.recent_projects_list.setProperty("role", "resultList")
        self.log_output.setProperty("role", "resultSurface")
        self.resources_preview_output.setProperty("role", "resultSurface")
        self.build_preview_output.setProperty("role", "resultSurface")
        self.validation_report_output.setProperty("role", "resultSurface")
        self.build_report_output.setProperty("role", "resultSurface")
        self.loudness_report_output.setProperty("role", "resultSurface")
        self.toolbar_dirty_label.setProperty("role", "topStatusChip")
        self.workspace_dirty_label.setProperty("role", "busHeaderChip")
        self.workspace_report_focus_label.setProperty("role", "busHeaderChip")
        self.activity_dirty_label.setProperty("role", "busHeaderChip")
        self.activity_report_focus_label.setProperty("role", "busHeaderChip")
        self.report_focus_label.setProperty("role", "busHeaderChip")
        self.report_detail_label.setProperty("role", "meterContext")
        self.activity_summary_label.setProperty("role", "modeCardTitle")