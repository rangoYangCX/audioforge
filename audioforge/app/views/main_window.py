from __future__ import annotations

import os

try:
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    sf = None

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCloseEvent, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
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
    QScrollArea,
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

from audioforge.app.models.audio_project import BusConfig, EventModel, ProjectSettings, ValidationIssue
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
)
from audioforge.app.widgets.clip_table import ClipTableWidget
from audioforge.app.widgets.event_tree import EventTreeWidget
from audioforge.app.widgets.loudness_history_plot import LoudnessHistoryPlot
from audioforge.app.views.shell_components import AppShell, CompatibilityTabWidget, DetachedToolWindow, TaskSidebar


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


class MainWindow(QMainWindow):
    eventPropertiesChanged = Signal()
    projectSettingsChanged = Signal()
    previewBusSelectionChanged = Signal()
    previewBusStateChanged = Signal()
    createFolderRequested = Signal()
    createEventRequested = Signal()
    renameSelectedRequested = Signal()
    deleteSelectedRequested = Signal()
    saveProjectAsRequested = Signal()
    undoRequested = Signal()
    redoRequested = Signal()
    previewRequested = Signal()
    stopPreviewEventRequested = Signal()
    stopPreviewBusRequested = Signal()
    importClipsRequested = Signal(list)
    removeClipsRequested = Signal(list)
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
    previewClipRequested = Signal(str)
    importAudioAsEventsRequested = Signal(list, object, dict)
    reportTargetRequested = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(load_app_icon("app"))
        self.resize(*DEFAULT_WINDOW_SIZE)
        self.setMinimumSize(1180, 760)
        self._loading_event = False
        self._close_handler = None
        self._ui_scale = 1.0
        self._default_workspace_splitter_sizes = [930, 150]
        self._default_main_splitter_sizes = [300, 1120]
        self._default_content_top_splitter_sizes = [700, 360]
        self._default_focus_content_splitter_sizes = [760, 320]
        self._minimum_report_panel_height = 140
        self._last_docked_main_splitter_sizes = list(self._default_main_splitter_sizes)
        self._pending_workspace_splitter_sizes: list[int] | None = None
        self._pending_main_splitter_sizes: list[int] | None = None
        self._pending_content_top_splitter_sizes: list[int] | None = None
        self._pending_layout_flush = False
        self._closing_main_window = False
        self._loading_clip_details = False
        self._clip_lookup: dict[str, object] = {}
        self._project_bus_configs: list[dict[str, object]] = []
        self._active_project_bus_name = ""
        self._active_event_id: str | None = None
        self._project_bus_selection_overridden = False
        self._syncing_project_bus_selection = False
        self._explorer_detached = False
        self._active_workspace_mode = "home"
        self._event_import_template_defaults = {
            "bus_name": "",
            "asset_prefix": "",
            "tags": [],
        }

        self.tree = EventTreeWidget()
        self.tree_filter_edit = QLineEdit()
        self.tree_filter_edit.setPlaceholderText("搜索事件与文件夹")
        self.object_type_label = QLabel("Event")
        self.object_name_label = QLabel("未选择对象")
        self.object_scope_label = QLabel("Project / Root")
        self.object_stats_label = QLabel("片段 0 | 标签 0")
        self.object_summary_primary_label = QLabel("模式 - | 总线 -")
        self.object_summary_secondary_label = QLabel("生成 - | 来源 -")
        self.object_event_bus_chip = QLabel("事件总线 -")
        self.object_bus_browser_chip = QLabel("总线浏览 -")
        self.object_context_hint_label = QLabel("当前浏览与编辑状态会在这里显示。")
        self.object_parent_button = QToolButton()
        self.object_preview_button = QPushButton("试听对象")
        self.object_contents_button = QPushButton("片段列表")
        self.object_follow_bus_button = QPushButton("跟随事件总线")
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
        self.play_mode_combo.addItems(["Random", "Sequence", "Combo"])
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
        self.inline_bus_new_button = QPushButton("新建并分配")
        self.inline_bus_set_default_button = QPushButton("设为默认")
        self.inline_bus_to_master_button = QPushButton("挂回 Master")
        self.inline_bus_open_parent_button = QPushButton("切到父总线")
        self.inline_bus_header = QFrame()
        self.inline_bus_name_chip = QLabel("总线 -")
        self.inline_bus_parent_chip = QLabel("父级 -")
        self.inline_bus_default_chip = QLabel("默认 -")
        self.inline_bus_export_chip = QLabel("导出 -")
        self.project_bus_list = ProjectBusTreeWidget()
        self.project_bus_add_button = QPushButton("新建总线")
        self.project_bus_remove_button = QPushButton("删除总线")
        self.project_bus_name_edit = QLineEdit()
        self.project_bus_name_edit.setPlaceholderText("Music")
        self.project_bus_parent_combo = QComboBox()
        self.project_bus_volume_spin = QDoubleSpinBox()
        self.project_bus_volume_spin.setRange(MIN_VOLUME_DB, MAX_VOLUME_DB)
        self.project_bus_volume_spin.setDecimals(1)
        self.project_bus_volume_spin.setSingleStep(0.5)
        self.project_bus_volume_spin.setSuffix(" dB")
        self.project_bus_mute_check = QCheckBox("导出时静音")
        self.project_bus_count_label = QLabel("总线 0 条")
        self.project_bus_default_label = QLabel("默认总线：-")
        self.project_bus_export_label = QLabel("未选择总线")
        self.project_bus_route_label = QLabel("未选择总线")
        self.project_bus_route_bar = QWidget()
        self.project_bus_children_label = QLabel("下游总线：-")
        self.project_bus_effective_value = QLabel("0%")
        self.project_bus_effective_bar = QProgressBar()
        self.project_bus_effective_bar.setRange(0, 100)
        self.project_bus_summary_label = QLabel("在左侧选择总线后，可在音频属性页直接编辑当前总线。")
        self.project_bus_summary_label.setWordWrap(True)
        self.project_bus_focus_audio_button = QPushButton("在音频属性页编辑当前总线")
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
        self.project_master_hint_label = QLabel("Master 现在会作为正式工程总线一起保存和导出；试听总控仍可在下方试听总线面板中单独调整。")
        self.preview_bus_combo = QComboBox()
        self.preview_bus_volume_spin = QDoubleSpinBox()
        self.preview_bus_volume_spin.setRange(0.0, 100.0)
        self.preview_bus_volume_spin.setDecimals(0)
        self.preview_bus_volume_spin.setSuffix(" %")
        self.preview_bus_mute_check = QCheckBox("静音")
        self.preview_bus_effective_label = QLabel("有效输出：100%")
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
        self.clip_source_detail_edit = QLineEdit()
        self.clip_source_detail_edit.setPlaceholderText("源文件路径；可直接修正或粘贴")
        self.clip_asset_detail_edit = QLineEdit()
        self.clip_asset_detail_edit.setPlaceholderText("ui/click_01")
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
        self.clip_loop_start_spin = QSpinBox()
        self.clip_loop_start_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_loop_start_spin.setToolTip("单位 ms。若源文件可读取，将自动按音频实际时长限制。")
        self.clip_loop_start_spin.setEnabled(False)
        self.clip_loop_end_spin = QSpinBox()
        self.clip_loop_end_spin.setRange(MIN_CLIP_TIME_MS, MAX_CLIP_TIME_MS)
        self.clip_loop_end_spin.setToolTip("单位 ms。0 表示不设循环终点；若源文件可读取，将自动按音频实际时长限制。")
        self.clip_loop_end_spin.setEnabled(False)
        self.clip_tags_detail_edit = QLineEdit()
        self.clip_tags_detail_edit.setPlaceholderText("ui, click")
        self.clip_preview_hint_label = QLabel("选择片段后可在此调整资源键、裁剪、循环和标签。")
        self.clip_preview_button = QPushButton("试听片段")
        self.clip_copy_asset_key_button = QPushButton("复制资源键")
        self.clip_locate_source_button = QPushButton("定位源文件")
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
        self.open_loudness_view_button = QPushButton("打开响度监视器")
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
        self.command_button = QPushButton("命令")
        self.scale_status_label = QLabel("100%")
        self.new_folder_button = QPushButton("新建文件夹")
        self.new_event_button = QPushButton("新建事件")
        self.rename_button = QPushButton("重命名")
        self.delete_button = QPushButton("删除")
        self.bulk_event_bus_button = QPushButton("批量改总线")
        self.undo_button = QPushButton("撤销")
        self.redo_button = QPushButton("重做")
        self.validate_button = QPushButton("校验")
        self.preview_button = QPushButton("试听")
        self.stop_preview_event_button = QPushButton("停事件")
        self.stop_preview_bus_button = QPushButton("停总线")
        self.build_button = QPushButton("构建导出")
        self.import_clips_button = QPushButton("导入音频")
        self.remove_clips_button = QPushButton("移除片段")
        self.bulk_weight_button = QPushButton("批量权重")
        self.batch_rename_button = QPushButton("批量重命名")
        self.apply_default_bus_button = QPushButton("默认总线应用到全部事件")
        self.tree_search_button = QToolButton()
        self.global_search_edit = QLineEdit()
        self.global_search_edit.setPlaceholderText("搜索事件并定位")
        self.global_search_button = QToolButton()
        self.task_sidebar = TaskSidebar()
        self.workspace_mode_stack = QStackedWidget()
        self.activity_summary_label = QLabel("欢迎使用新的 AppShell。先从欢迎页进入具体工作模式。")
        self.activity_hint_label = QLabel("这里会持续显示最近的结果入口与当前工作状态。")
        self.events_workspace_status_label = QLabel("等待选择事件。")
        self.event_overview_hint_label = QLabel("从左侧概览快速切到参数、资源或结果页。")
        self.resources_workspace_status_label = QLabel("等待导入或选择片段。")
        self.resources_overview_hint_label = QLabel("先完成片段编排，再进入批处理或生成预览。")
        self.buses_workspace_status_label = QLabel("等待选择事件总线。")
        self.buses_overview_hint_label = QLabel("从左侧概览选择当前要处理的总线工作流。")
        self.build_workspace_status_label = QLabel("等待准备导出配置。")
        self.build_overview_hint_label = QLabel("先确认导出设置，再查看差异和构建结果。")
        self.validation_overview_hint_label = QLabel("按级别与关键字聚焦问题，再回到对象或资源页修复。")
        self.results_overview_hint_label = QLabel("从结果导航进入日志、校验、构建或响度结果。")
        self._validation_issue_items: list[dict[str, object]] = []

        self._build_ui()
        self._bind_internal_signals()
        self._bind_shortcuts()
        self._apply_wwise_style()

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
        reference_layout.addWidget(QLabel("输出总线"), 0, 2)
        reference_layout.addWidget(self.reference_bus_value_button, 0, 3)
        reference_layout.addWidget(QLabel("资源"), 1, 0)
        reference_layout.addWidget(self.reference_assets_value_button, 1, 1)
        reference_layout.addWidget(QLabel("生成"), 1, 2)
        reference_layout.addWidget(self.reference_generation_value_button, 1, 3)
        reference_layout.addWidget(self.reference_work_unit_label, 2, 0, 1, 2)
        reference_layout.addWidget(self.reference_output_label, 2, 2, 1, 2)

        self.event_general_group = QGroupBox("对象设置")
        general_layout = QFormLayout(self.event_general_group)
        general_layout.addRow("名称", self.display_name_edit)
        general_layout.addRow("对象 ID", self.event_id_edit)
        general_layout.addRow("输出总线", self.bus_combo)
        general_layout.addRow("播放机制", self.play_mode_combo)
        general_layout.addRow("加载方式", self.load_policy_combo)
        general_layout.addRow("标签", self.tags_summary_edit)

        self.event_behavior_group = QGroupBox("触发控制")
        voice_layout = QFormLayout(self.event_behavior_group)
        voice_layout.addRow("抢占策略", self.steal_policy_combo)
        voice_layout.addRow("实例上限", self.max_instances_spin)
        voice_layout.addRow("冷却时间（秒）", self.cooldown_spin)
        voice_layout.addRow("避免紧邻重复", self.avoid_repeat_check)

        self.modulation_group = QGroupBox("音调与音量")
        modulation_layout = QFormLayout(self.modulation_group)
        modulation_layout.addRow("基础音量（dB）", self.volume_spin)
        modulation_layout.addRow("音量随机最小（dB）", self.volume_rand_min_spin)
        modulation_layout.addRow("音量随机最大（dB）", self.volume_rand_max_spin)
        modulation_layout.addRow("基础音高（cents）", self.pitch_spin)
        modulation_layout.addRow("音高随机最小（cents）", self.pitch_rand_min_spin)
        modulation_layout.addRow("音高随机最大（cents）", self.pitch_rand_max_spin)

        self.combo_group = QGroupBox("连击加成")
        combo_layout = QFormLayout(self.combo_group)
        combo_layout.addRow("连击步进（半音）", self.combo_pitch_step_spin)
        combo_layout.addRow("重置时间（秒）", self.combo_reset_spin)
        combo_layout.addRow("最大步数", self.combo_max_step_spin)

        self.loudness_group = QGroupBox("最近试听")
        loudness_layout = QFormLayout(self.loudness_group)
        loudness_layout.addRow("监视器", self.open_loudness_view_button)
        loudness_layout.addRow("源文件", self.audio_meter_summary_source_context_label)
        loudness_layout.addRow("源 Integrated", self.audio_meter_summary_source_integrated_value)
        loudness_layout.addRow("源 True Peak", self.audio_meter_summary_source_true_peak_value)
        loudness_layout.addRow("事件后", self.audio_meter_summary_context_label)
        loudness_layout.addRow("后 Integrated", self.audio_meter_summary_integrated_value)
        loudness_layout.addRow("后 True Peak", self.audio_meter_summary_true_peak_value)

        self.notes_group = QGroupBox("备注")
        notes_layout = QVBoxLayout(self.notes_group)
        notes_layout.addWidget(self.notes_edit)

        self.inline_bus_group = QGroupBox("当前输出总线")
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
        route_bar_layout = QHBoxLayout(self.project_bus_route_bar)
        route_bar_layout.setContentsMargins(0, 0, 0, 0)
        route_bar_layout.setSpacing(6)
        self.bus_routing_group = QGroupBox("Routing")
        bus_routing_layout = QVBoxLayout(self.bus_routing_group)
        bus_identity_form = QFormLayout()
        bus_identity_form.addRow("总线名称", self.project_bus_name_edit)
        bus_identity_form.addRow("父总线", self.project_bus_parent_combo)
        bus_routing_layout.addLayout(bus_identity_form)
        route_caption = QLabel("总线路由")
        route_caption.setProperty("role", "meterTitle")
        bus_routing_layout.addWidget(route_caption)
        bus_routing_layout.addWidget(self.project_bus_route_bar)
        child_caption = QLabel("下游总线")
        child_caption.setProperty("role", "meterTitle")
        bus_routing_layout.addWidget(child_caption)
        bus_routing_layout.addWidget(self.project_bus_children_label)
        self.bus_level_group = QGroupBox("Bus Volume")
        bus_level_layout = QFormLayout(self.bus_level_group)
        bus_level_layout.addRow("基础音量（dB）", self.project_bus_volume_spin)
        bus_level_layout.addRow("静音", self.project_bus_mute_check)
        bus_level_layout.addRow("作者态输出", self.project_bus_effective_value)
        bus_level_layout.addRow("输出表", self.project_bus_effective_bar)
        self.bus_validation_group = QGroupBox("导出结果")
        bus_validation_layout = QVBoxLayout(self.bus_validation_group)
        bus_validation_layout.setContentsMargins(12, 10, 12, 10)
        bus_validation_layout.addWidget(self.project_bus_export_label)
        self.inline_bus_content = QSplitter()
        self.inline_bus_content.setOrientation(Qt.Orientation.Horizontal)
        self.inline_bus_content.setChildrenCollapsible(False)
        self.inline_bus_content.addWidget(self.bus_routing_group)
        bus_status_panel = QWidget()
        bus_status_layout = QVBoxLayout(bus_status_panel)
        bus_status_layout.setContentsMargins(0, 0, 0, 0)
        bus_status_layout.addWidget(self.bus_level_group)
        bus_status_layout.addWidget(self.bus_validation_group)
        bus_status_layout.addStretch(1)
        self.inline_bus_content.addWidget(bus_status_panel)
        self.inline_bus_content.setStretchFactor(0, 3)
        self.inline_bus_content.setStretchFactor(1, 2)
        inline_bus_layout.addWidget(self.inline_bus_content)

        self.audio_top_splitter = QSplitter()
        self.audio_top_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.audio_top_splitter.setChildrenCollapsible(False)
        self.audio_top_splitter.addWidget(self.modulation_group)
        self.audio_top_splitter.addWidget(self.loudness_group)
        self.audio_top_splitter.setStretchFactor(0, 3)
        self.audio_top_splitter.setStretchFactor(1, 2)

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
        build_layout.addWidget(self.preview_export_diff_button)
        build_layout.addStretch(1)

        self.project_settings_group = QGroupBox("工程总览")
        project_settings_layout = QFormLayout(self.project_settings_group)
        project_settings_layout.addRow("默认总线", self.default_bus_combo)
        project_settings_layout.addRow("总线概况", self.project_bus_count_label)
        project_settings_layout.addRow("批量操作", self.apply_default_bus_button)

        self.bus_browser_group = QGroupBox("总线浏览器")
        bus_browser_layout = QVBoxLayout(self.bus_browser_group)
        bus_browser_actions = QHBoxLayout()
        bus_browser_actions.addWidget(self.project_bus_add_button)
        bus_browser_actions.addWidget(self.project_bus_remove_button)
        bus_browser_layout.addLayout(bus_browser_actions)
        bus_browser_layout.addWidget(self.project_bus_list)
        bus_browser_layout.addWidget(self.project_bus_default_label)

        self.master_bus_group = QGroupBox("Master 总线")
        master_bus_layout = QFormLayout(self.master_bus_group)
        master_bus_layout.addRow("总线名称", self.project_master_summary_label)
        master_bus_layout.addRow("基础音量（dB）", self.project_master_volume_spin)
        master_bus_layout.addRow("静音", self.project_master_mute_check)
        master_bus_layout.addRow("作者态输出", self.project_master_effective_value)
        master_bus_layout.addRow("输出表", self.project_master_effective_bar)
        master_bus_layout.addRow("说明", self.project_master_hint_label)

        self.project_bus_overview_group = QGroupBox("总线工作区")
        project_bus_overview_layout = QVBoxLayout(self.project_bus_overview_group)
        project_bus_overview_layout.addWidget(self.project_bus_summary_label)
        project_bus_overview_layout.addWidget(self.project_bus_focus_audio_button)

        project_right_panel = QWidget()
        project_right_layout = QVBoxLayout(project_right_panel)
        project_right_layout.setContentsMargins(0, 0, 0, 0)
        project_right_layout.addWidget(self.master_bus_group)
        project_right_layout.addWidget(self.project_settings_group)
        project_right_layout.addWidget(self.project_bus_overview_group)
        project_right_layout.addStretch(1)

        self.project_splitter = QSplitter()
        self.project_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.project_splitter.setChildrenCollapsible(False)
        self.project_splitter.addWidget(self.bus_browser_group)
        self.project_splitter.addWidget(project_right_panel)
        self.project_splitter.setStretchFactor(1, 1)

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

        clip_detail_group = QGroupBox("片段详情")
        clip_detail_layout = QFormLayout(clip_detail_group)
        clip_detail_layout.addRow("当前片段", self.clip_selected_label)
        clip_detail_layout.addRow("源路径", self.clip_source_detail_edit)
        clip_detail_layout.addRow("资源键", self.clip_asset_detail_edit)
        clip_detail_layout.addRow("权重", self.clip_weight_row)
        clip_detail_layout.addRow("起始裁剪", self.clip_trim_start_spin)
        clip_detail_layout.addRow("结束裁剪", self.clip_trim_end_spin)
        clip_detail_layout.addRow("循环起点", self.clip_loop_start_spin)
        clip_detail_layout.addRow("循环终点", self.clip_loop_end_spin)
        clip_detail_layout.addRow("标签", self.clip_tags_detail_edit)
        clip_detail_layout.addRow("提示", self.clip_preview_hint_label)
        clip_action_row = QWidget()
        clip_action_layout = QHBoxLayout(clip_action_row)
        clip_action_layout.setContentsMargins(0, 0, 0, 0)
        clip_action_layout.setSpacing(8)
        clip_action_layout.addWidget(self.clip_preview_button)
        clip_action_layout.addWidget(self.clip_copy_asset_key_button)
        clip_action_layout.addWidget(self.clip_locate_source_button)
        clip_action_layout.addStretch(1)
        clip_detail_layout.addRow("快捷动作", clip_action_row)

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
        self.content_top_splitter.setOrientation(Qt.Orientation.Horizontal)
        self.content_top_splitter.setChildrenCollapsible(False)
        self.content_top_splitter.addWidget(clip_list_group)
        self.content_top_splitter.addWidget(clip_detail_group)
        self._set_content_top_splitter_sizes(self._default_content_top_splitter_sizes)

        batch_page = self._build_two_column_page([clip_tools_group], [batch_guide_group])

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
            1: self._build_property_compat_scroll("音频属性兼容页", "旧兼容接口仍会把这一页视作可滚动属性页；真实编辑已迁到“总线与混音”工作区。"),
            2: self._build_property_compat_scroll("生成兼容页", "旧兼容接口仍会把这一页视作可滚动属性页；真实编辑已迁到“构建交付”工作区。"),
            3: self._build_property_compat_scroll("工程兼容页", "旧兼容接口仍会把这一页视作可滚动属性页；真实工程配置已收口到独立工作区。"),
        }
        self.property_tabs = CompatibilityTabWidget()
        self.property_tabs.addTab(QWidget(), "事件")
        self.property_tabs.addTab(QWidget(), "音频属性")
        self.property_tabs.addTab(QWidget(), "生成")
        self.property_tabs.addTab(QWidget(), "工程")
        self.property_tabs.set_current_widget_resolver(self._current_property_compat_widget)
        self.property_tabs.hide()

        self.editor_tabs = QTabWidget()
        self.editor_tabs.addTab(QWidget(), load_app_icon("event"), "属性编辑器")
        self.editor_tabs.addTab(QWidget(), load_app_icon("content"), "内容编辑器")
        self.editor_tabs.addTab(QWidget(), load_app_icon("audio"), "响度监视器")
        self.editor_tabs.hide()

        self.events_workspace = self._build_events_workspace()
        self.resources_workspace = self._build_resources_workspace()
        self.buses_workspace = self._build_buses_workspace()
        self.build_workspace = self._build_build_workspace()
        self.validation_workspace = self._build_validation_workspace()
        self.property_group = self.events_workspace

        self.report_pages = QStackedWidget()
        self._report_page_titles = ["当前：日志", "当前：校验报告", "当前：构建报告", "当前：响度扫描"]
        self._report_pages: dict[int, QWidget] = {
            0: self._build_log_results_page(),
            1: self._build_validation_results_page(),
            2: self._build_build_results_page(),
            3: self._build_loudness_results_page(),
        }
        for index in range(4):
            self.report_pages.addWidget(self._report_pages[index])
        self._active_report_index = 0

        self.report_tabs = QTabWidget()
        self.report_tabs.addTab(QWidget(), "日志")
        self.report_tabs.addTab(QWidget(), "校验报告")
        self.report_tabs.addTab(QWidget(), "构建报告")
        self.report_tabs.addTab(QWidget(), "响度扫描")
        self.report_tabs.hide()

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
            ("buses", "总线与混音", "将当前事件总线、总线浏览器和 Master 输出整合为独立混音工作区。"),
            ("validation", "校验修复", "直接进入问题中心，按校验结果修复对象与资源。"),
            ("build", "构建交付", "将导出设置、交付预览和构建入口收口到专门页面。"),
            ("results", "结果中心", "统一查看日志、校验报告、构建报告和响度扫描，作为收尾页使用。"),
            ("validation-results", "校验结果", "直接进入校验专页，适合从左侧导航快速回看问题清单并继续修复。"),
            ("build-results", "构建结果", "直接进入构建结果专页，集中查看构建摘要、问题定位和交付预览。"),
            ("loudness-results", "响度结果", "直接进入响度专页，查看超标项、条目细节和完整扫描输出。"),
        ]:
            page, host_layout = self._build_workspace_mode_page(title, description)
            self._workspace_mode_pages[mode] = page
            self._workspace_mode_hosts[mode] = host_layout
            self.workspace_mode_stack.addWidget(page)
        self._workspace_mode_hosts["events"].addWidget(self.events_workspace)
        self._workspace_mode_hosts["resources"].addWidget(self.resources_workspace)
        self._workspace_mode_hosts["buses"].addWidget(self.buses_workspace)
        self._workspace_mode_hosts["build"].addWidget(self.build_workspace)

        self.workspace_status_bar = QFrame()
        self.workspace_status_bar.setObjectName("WorkspaceStatusBar")
        self.status_label = QLabel(self.status_label.text(), self.workspace_status_bar)
        self.workspace_report_focus_label = QLabel(self.workspace_report_focus_label.text(), self.workspace_status_bar)
        self.workspace_dirty_label = QLabel(self.workspace_dirty_label.text(), self.workspace_status_bar)
        workspace_status_layout = QHBoxLayout(self.workspace_status_bar)
        workspace_status_layout.setContentsMargins(12, 8, 12, 8)
        workspace_status_layout.setSpacing(10)
        workspace_status_layout.addWidget(self.status_label)
        workspace_status_layout.addStretch(1)
        workspace_status_layout.addWidget(self.workspace_report_focus_label)
        workspace_status_layout.addWidget(self.workspace_dirty_label)

        self.main_splitter = QSplitter()
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
        left_layout.addWidget(self.tree)
        self.explorer_placeholder = self._build_detached_explorer_placeholder()
        self.explorer_window = DetachedToolWindow()
        self.explorer_window.setWindowTitle(f"{APP_NAME} - 工程浏览器")
        self.explorer_window.setWindowIcon(load_app_icon("app"))
        self.explorer_window.resize(460, 820)
        explorer_window_layout = QVBoxLayout(self.explorer_window)
        explorer_window_layout.setContentsMargins(8, 8, 8, 8)
        explorer_window_layout.setSpacing(8)
        self.explorer_window_layout = explorer_window_layout
        self.explorer_window.closeRequested.connect(self.attach_explorer_panel)
        self.main_splitter.addWidget(self.explorer_panel)
        self.main_splitter.addWidget(self.workspace_mode_stack)
        self.main_splitter.setStretchFactor(1, 1)
        self._set_main_splitter_sizes(self._default_main_splitter_sizes)

        self.workspace_splitter = QSplitter()
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
        self._activate_workspace_mode(self._active_workspace_mode)
        self.task_sidebar.set_active_mode(self._active_workspace_mode)
        self._build_settings_dialog()

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

    def _build_workspace_mode_page(self, title: str, description: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro_card = QFrame()
        intro_card.setObjectName("ModeIntroCard")
        intro_layout = QVBoxLayout(intro_card)
        intro_layout.setContentsMargins(16, 14, 16, 14)
        intro_layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setProperty("role", "modeCardTitle")
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", "modeCardDescription")
        intro_layout.addWidget(title_label)
        intro_layout.addWidget(description_label)

        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)

        layout.addWidget(intro_card)
        layout.addWidget(host, 1)
        return page, host_layout

    def _build_mode_surface_card(self, title: str, description: str, *, role: str = "modeCardDescription") -> QFrame:
        card = QFrame()
        card.setObjectName("ModeIntroCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setProperty("role", "modeCardTitle")
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", role)
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return card

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
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setProperty("role", "workspaceSectionTitle")
        summary_label.setProperty("role", "workspaceSectionSummary")
        summary_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(summary_label)
        if shortcut_specs:
            layout.addLayout(self._build_workspace_shortcut_grid(shortcut_specs))
        return card

    def _build_workspace_note_card(self, title: str, lines: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("WorkspaceOverviewCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setProperty("role", "workspaceSectionTitle")
        layout.addWidget(title_label)
        for line in lines:
            label = QLabel(line)
            label.setWordWrap(True)
            label.setProperty("role", "workspaceChecklistLine")
            layout.addWidget(label)
        return card

    def _build_empty_state_card(self, title: str, description: str) -> QFrame:
        card = QFrame()
        card.setObjectName("EmptyStateCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setProperty("role", "emptyStateTitle")
        description_label = QLabel(description)
        description_label.setWordWrap(True)
        description_label.setProperty("role", "emptyStateBody")
        layout.addWidget(title_label)
        layout.addWidget(description_label)
        return card

    def _build_events_workspace(self) -> QWidget:
        self.events_workspace_tabs = QTabWidget()
        design_page = self._build_two_column_page(
            [self.event_general_group, self.event_behavior_group, self.notes_group],
            [self.modulation_group, self.combo_group, self.loudness_group],
        )
        self.event_design_scroll = self._wrap_scrollable_page(design_page)
        self.events_workspace_tabs.addTab(self.event_design_scroll, load_app_icon("event"), "事件参数")
        self.events_workspace_tabs.addTab(self.loudness_view, load_app_icon("audio"), "响度监视器")

        overview_panel = self._build_event_overview_panel()
        event_splitter = QSplitter()
        event_splitter.setOrientation(Qt.Orientation.Horizontal)
        event_splitter.setChildrenCollapsible(False)
        event_splitter.addWidget(overview_panel)
        event_splitter.addWidget(self.events_workspace_tabs)
        event_splitter.setStretchFactor(0, 2)
        event_splitter.setStretchFactor(1, 5)

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
                    ("资源整理", lambda: self._activate_workspace_mode("resources"), "content"),
                    ("跟随总线", self._follow_current_event_bus, "bus"),
                ],
            )
        )
        layout.addWidget(event_splitter, 1)
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
                    ("校验结果", lambda: self._activate_workspace_mode("validation-results"), "report", 1, 1),
                ],
            )
        )
        layout.addWidget(
            self._build_workspace_note_card(
                "编辑节奏",
                [
                    "先确定对象命名、总线和播放机制，再处理随机范围与连击逻辑。",
                    "响度监视器保持事件内联，便于边试听边校准。",
                ],
            )
        )
        layout.addWidget(self.object_header_frame)
        layout.addWidget(self.reference_group)
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
        layout.addWidget(
            self._build_workspace_note_card(
                "整理建议",
                [
                    "片段编排负责单片段精修，批处理只做成组修改。",
                    "生成预览显示当前导出差异镜像，正式交付在构建页完成。",
                ],
            )
        )
        layout.addStretch(1)
        return panel

    def _build_resources_workspace(self) -> QWidget:
        overview_panel = self._build_resources_overview_panel()
        workspace_splitter = QSplitter()
        workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.addWidget(overview_panel)
        workspace_splitter.addWidget(self.contents_tabs)
        workspace_splitter.setStretchFactor(0, 2)
        workspace_splitter.setStretchFactor(1, 5)

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
                    ("导出差异", self.previewExportDiffRequested.emit, "report"),
                ],
            )
        )
        layout.addWidget(workspace_splitter, 1)
        return workspace

    def _build_buses_overview_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("WorkspaceOverviewPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.hero_panel)
        layout.addWidget(
            self._build_workspace_overview_card(
                "混音导航",
                self.buses_overview_hint_label,
                [
                    ("当前事件总线", self._follow_current_event_bus, "bus", 0, 0),
                    ("新建总线", self._request_add_project_bus, "bus", 0, 1),
                    ("设为默认", self._set_current_bus_as_default, "generate", 1, 0),
                    ("回到事件", lambda: self._activate_workspace_mode("events"), "event", 1, 1),
                ],
            )
        )
        layout.addWidget(self.project_settings_group)
        layout.addStretch(1)
        return panel

    def _build_buses_workspace(self) -> QWidget:
        overview_panel = self._build_buses_overview_panel()
        bus_surface = QSplitter()
        bus_surface.setOrientation(Qt.Orientation.Vertical)
        bus_surface.setChildrenCollapsible(False)
        bus_surface.addWidget(self.inline_bus_group)
        bus_surface.addWidget(self.project_splitter)
        bus_surface.setStretchFactor(0, 2)
        bus_surface.setStretchFactor(1, 3)

        workspace_splitter = QSplitter()
        workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.addWidget(overview_panel)
        workspace_splitter.addWidget(bus_surface)
        workspace_splitter.setStretchFactor(0, 2)
        workspace_splitter.setStretchFactor(1, 5)

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            self._build_workspace_action_bar(
                "总线与混音",
                self.buses_workspace_status_label,
                [
                    ("新建总线", self._request_add_project_bus, "bus"),
                    ("设为默认", self._set_current_bus_as_default, "generate"),
                    ("挂到 Master", self._route_current_bus_to_master, "route"),
                    ("回到事件", lambda: self._activate_workspace_mode("events"), "event"),
                ],
            )
        )
        layout.addWidget(workspace_splitter, 1)
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
                    ("导出设置", lambda: self._activate_workspace_mode("build"), "generate", 0, 0),
                    ("导出差异", self.previewExportDiffRequested.emit, "report", 0, 1),
                    ("构建结果", lambda: self._activate_workspace_mode("build-results"), "report", 1, 0),
                    ("校验修复", lambda: self._activate_workspace_mode("validation"), "validate", 1, 1),
                ],
            )
        )
        layout.addWidget(self.generation_settings_group)
        layout.addWidget(self.build_overview_group)
        layout.addStretch(1)
        return panel

    def _build_build_workspace(self) -> QWidget:
        overview_panel = self._build_build_overview_panel()
        delivery_followup = self._build_workspace_note_card(
            "交付回看",
            [
                "生成预览显示完整导出文本，便于在构建前核对差异。",
                "构建完成后直接切到构建结果页查看摘要与问题定位。",
            ],
        )
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(self.build_preview_group, 1)
        right_layout.addWidget(delivery_followup)

        workspace_splitter = QSplitter()
        workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.addWidget(overview_panel)
        workspace_splitter.addWidget(right_panel)
        workspace_splitter.setStretchFactor(0, 2)
        workspace_splitter.setStretchFactor(1, 5)

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
                    ("构建导出", self.build_button.click, "generate"),
                    ("查看结果", lambda: self._activate_workspace_mode("build-results"), "report"),
                ],
            )
        )
        layout.addWidget(workspace_splitter, 1)
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
                    ("重新校验", self.validate_button.click, "validate", 0, 0),
                    ("定位问题", self._locate_selected_validation_issue, "report", 0, 1),
                    ("事件设计", lambda: self._activate_workspace_mode("events"), "event", 1, 0),
                    ("资源整理", lambda: self._activate_workspace_mode("resources"), "content", 1, 1),
                ],
            )
        )
        layout.addWidget(filter_card)
        layout.addWidget(self.validation_filter_status_label)
        layout.addWidget(
            self._build_workspace_note_card(
                "修复原则",
                [
                    "先处理错误，再看警告；信息级问题只在需要时回看。",
                    "这里负责聚焦和跳转，不继续堆复杂修复逻辑。",
                ],
            )
        )
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

        workspace_splitter = QSplitter()
        workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.addWidget(self._build_validation_overview_panel(filter_card))
        workspace_splitter.addWidget(self._build_report_center_page(self.validation_summary_label, self.validation_issue_list, self.validation_report_output))
        workspace_splitter.setStretchFactor(0, 2)
        workspace_splitter.setStretchFactor(1, 5)

        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("校验修复工作流", "把筛选、定位和结果细节拆分成左右双栏，减少来回切页。"))
        layout.addWidget(workspace_splitter, 1)
        return workspace

    def _current_property_scroll_widget(self) -> QWidget | None:
        return self._current_property_compat_widget()

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        hero = QFrame()
        hero.setObjectName("WelcomeHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(8)
        title = QLabel("欢迎进入新的 AudioForge AppShell")
        title.setProperty("role", "welcomeTitle")
        subtitle = QLabel("现在的首屏不再直接把所有工具堆在一起，而是把入口、流程和结果收口到清晰的页面层。")
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
        project_snapshot.setObjectName("ModeIntroCard")
        project_snapshot_layout = QVBoxLayout(project_snapshot)
        project_snapshot_layout.setContentsMargins(16, 14, 16, 14)
        project_snapshot_layout.setSpacing(6)
        snapshot_title = QLabel("当前工程")
        snapshot_title.setProperty("role", "modeCardTitle")
        project_snapshot_layout.addWidget(snapshot_title)
        project_snapshot_layout.addWidget(self.welcome_project_title_label)
        project_snapshot_layout.addWidget(self.welcome_project_path_label)
        project_snapshot_layout.addWidget(self.welcome_dirty_label)

        quick_start = self._build_workspace_note_card(
            "快速进入",
            [
                "资源整理：先批量导入、清洗资源键，再切到事件设计。",
                "总线与混音：集中看事件总线、父子路由和 Master 输出。",
                "结果中心：所有日志、校验、构建和响度结果都统一收口到这里。",
            ],
        )
        first_run_card = self._build_empty_state_card(
            "从空白工程开始也没关系",
            "如果你还没有最近工程，可以直接新建一个模板工程，然后按“资源整理 -> 事件设计 -> 构建交付”的顺序完成第一次闭环。",
        )
        mode_map = self._build_workspace_note_card(
            "工作区地图",
            [
                "事件设计负责对象参数与响度校准。",
                "资源整理负责片段编排、批处理和预览镜像。",
                "构建交付负责真实导出与交付回看。",
            ],
        )
        welcome_splitter = QSplitter()
        welcome_splitter.setOrientation(Qt.Orientation.Horizontal)
        welcome_splitter.setChildrenCollapsible(False)
        left_column = QWidget()
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(project_snapshot)
        left_layout.addWidget(first_run_card)
        left_layout.addWidget(mode_map)
        left_layout.addStretch(1)
        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.addWidget(quick_start)
        right_layout.addWidget(
            self._build_workspace_overview_card(
                "首屏快捷跳转",
                QLabel("直接进入核心工作区，避免从首页层层钻取。"),
                [
                    ("事件设计", lambda: self._activate_workspace_mode("events"), "event", 0, 0),
                    ("资源整理", lambda: self._activate_workspace_mode("resources"), "content", 0, 1),
                    ("总线与混音", lambda: self._activate_workspace_mode("buses"), "bus", 1, 0),
                    ("结果中心", lambda: self._activate_workspace_mode("results"), "report", 1, 1),
                ],
            )
        )
        right_layout.addStretch(1)
        welcome_splitter.addWidget(left_column)
        welcome_splitter.addWidget(right_column)
        welcome_splitter.setStretchFactor(0, 2)
        welcome_splitter.setStretchFactor(1, 3)

        layout.addWidget(hero)
        layout.addWidget(welcome_splitter, 1)
        layout.addStretch(1)
        return self._wrap_scrollable_page(page)

    def _build_log_results_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_mode_surface_card("日志中心", "集中查看运行日志、导入反馈和交付链路输出；当没有问题时，这里主要承担追踪和回溯职责。"))
        results_splitter = QSplitter()
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
        top_splitter.setOrientation(Qt.Orientation.Horizontal)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(self._build_report_center_page(self.build_summary_label, self.build_issue_list, self.build_report_output))
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
        loudness_splitter.addWidget(self._build_report_center_page(self.loudness_summary_label, self.loudness_issue_list, self.loudness_report_output))
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
                ],
            )
        )
        layout.addWidget(
            self._build_workspace_note_card(
                "收尾建议",
                [
                    "先看校验和构建，再确认响度结果，最后回日志追踪链路。",
                    "结果页用于收尾与回看，不再承担编辑动作本身。",
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
        workspace_splitter = QSplitter()
        workspace_splitter.setOrientation(Qt.Orientation.Horizontal)
        workspace_splitter.setChildrenCollapsible(False)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.report_header)
        right_layout.addWidget(self.report_pages, 1)
        workspace_splitter.addWidget(self._build_results_overview_panel())
        workspace_splitter.addWidget(right_panel)
        workspace_splitter.setStretchFactor(0, 2)
        workspace_splitter.setStretchFactor(1, 5)
        layout.addWidget(workspace_splitter, 1)
        return panel

    def _build_activity_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumHeight(self._minimum_report_panel_height)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_panel_header("活动与结果入口", "log"))

        body = QFrame()
        body.setObjectName("ActivityPanel")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 10)
        body_layout.setSpacing(10)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)
        self.activity_summary_label.setProperty("role", "modeCardTitle")
        self.activity_hint_label.setProperty("role", "modeCardDescription")
        self.activity_hint_label.setWordWrap(True)
        text_column.addWidget(self.activity_summary_label)
        text_column.addWidget(self.activity_hint_label)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        results_button = QPushButton("结果中心")
        validate_button = QPushButton("校验结果")
        build_button = QPushButton("构建结果")
        loudness_button = QPushButton("响度结果")
        results_button.clicked.connect(lambda: self._activate_workspace_mode("results"))
        validate_button.clicked.connect(lambda: self.show_report_tab(1))
        build_button.clicked.connect(lambda: self.show_report_tab(2))
        loudness_button.clicked.connect(lambda: self.show_report_tab(3))
        action_row.addWidget(results_button)
        action_row.addWidget(validate_button)
        action_row.addWidget(build_button)
        action_row.addWidget(loudness_button)
        action_row.addStretch(1)
        text_column.addLayout(action_row)

        body_layout.addLayout(text_column, 1)
        body_layout.addWidget(self.activity_report_focus_label)
        body_layout.addWidget(self.activity_dirty_label)
        layout.addWidget(body)
        self.log_panel = panel
        return panel

    def _mount_workspace_surface(self, mode: str) -> None:
        surface_key = {
            "validation": "validation",
            "results": "results",
            "validation-results": "validation",
            "build-results": "results",
            "loudness-results": "results",
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
        self.settings_dialog.resize(760, 620)

        intro_label = QLabel("把低频的应用级控制集中收纳到这里，避免工程首页堆叠。")
        intro_label.setWordWrap(True)

        preview_bus_group = QGroupBox("试听总线")
        preview_bus_layout = QFormLayout(preview_bus_group)
        preview_bus_layout.addRow("目标总线", self.preview_bus_combo)
        preview_bus_layout.addRow("预览音量", self.preview_bus_volume_spin)
        preview_bus_layout.addRow("静音", self.preview_bus_mute_check)
        preview_bus_layout.addRow("有效输出", self.preview_bus_effective_label)

        import_template_group = QGroupBox("导入模板默认值")
        import_template_layout = QFormLayout(import_template_group)
        import_template_layout.addRow("默认总线", self.import_template_bus_combo)
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
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _show_command_quick_reference(self) -> None:
        QMessageBox.information(
            self,
            f"{APP_NAME} 命令",
            "当前入口已经收口到 AppShell。\n\n"
            "推荐命令：\n"
            "- 顶部搜索：定位事件\n"
            "- 左侧任务导航：切换工作模式\n"
            "- Delete：删除选中对象或片段\n"
            "- F2：重命名\n"
            "- Enter：打开当前编辑焦点\n"
            "- Ctrl+C：复制对象标识或资源键",
        )

    def _set_workspace_mode(self, mode: str) -> None:
        mode_titles = {
            "home": "欢迎页",
            "resources": "资源整理",
            "events": "事件设计",
            "buses": "总线与混音",
            "validation": "校验修复",
            "build": "构建交付",
            "results": "结果中心",
            "validation-results": "校验结果",
            "build-results": "构建结果",
            "loudness-results": "响度结果",
        }
        self._active_workspace_mode = mode
        self.task_sidebar.set_active_mode(mode)
        self.shell_mode_title_label.setText(mode_titles.get(mode, "欢迎页"))
        self.activity_summary_label.setText(f"当前工作模式：{mode_titles.get(mode, '欢迎页')}")
        self.activity_hint_label.setText(self._current_workspace_context_text())

    def _activate_workspace_mode(self, mode: str) -> None:
        if mode == "home":
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["home"])
        elif mode == "resources":
            self._mount_workspace_surface("resources")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["resources"])
            self.editor_tabs.setCurrentIndex(1)
            self.contents_tabs.setCurrentIndex(0)
            self._set_content_top_splitter_sizes(self._default_focus_content_splitter_sizes)
        elif mode == "events":
            self._mount_workspace_surface("events")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["events"])
            self.editor_tabs.setCurrentIndex(0)
            self.property_tabs.setCurrentIndex(0)
            self.events_workspace_tabs.setCurrentIndex(0)
        elif mode == "buses":
            self._mount_workspace_surface("buses")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["buses"])
            self.editor_tabs.setCurrentIndex(0)
            self.property_tabs.setCurrentIndex(1)
            self._project_bus_selection_overridden = False
            self._sync_current_event_bus_selection(force=True)
        elif mode == "validation":
            self._mount_workspace_surface("validation")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["validation"])
            self._active_report_index = 1
            self.report_pages.setCurrentIndex(1)
            self.report_tabs.setCurrentIndex(1)
            workspace_total = max(sum(self.workspace_splitter.sizes()), sum(self._default_workspace_splitter_sizes))
            self._set_workspace_splitter_sizes([int(workspace_total * 0.68), int(workspace_total * 0.32)])
        elif mode == "build":
            self._mount_workspace_surface("build")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["build"])
            self.editor_tabs.setCurrentIndex(0)
            self.property_tabs.setCurrentIndex(2)
        elif mode == "results":
            self._mount_workspace_surface("results")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["results"])
        elif mode == "validation-results":
            self._mount_workspace_surface("validation-results")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["validation-results"])
            self._active_report_index = 1
            self.report_pages.setCurrentIndex(1)
            self.report_tabs.setCurrentIndex(1)
        elif mode == "build-results":
            self._mount_workspace_surface("build-results")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["build-results"])
            self._active_report_index = 2
            self.report_pages.setCurrentIndex(2)
            self.report_tabs.setCurrentIndex(2)
        elif mode == "loudness-results":
            self._mount_workspace_surface("loudness-results")
            self.workspace_mode_stack.setCurrentWidget(self._workspace_mode_pages["loudness-results"])
            self._active_report_index = 3
            self.report_pages.setCurrentIndex(3)
            self.report_tabs.setCurrentIndex(3)
        self._set_workspace_mode(mode)
        self._update_object_bus_status()

    def _sync_global_search_fields(self, text: str) -> None:
        self.tree_filter_edit.setText(text)

    def _request_global_search(self) -> None:
        query = self.global_search_edit.text().strip()
        self.tree_filter_edit.setText(query)
        self._search_next_tree_event()

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
        self._schedule_layout_flush()

    def _schedule_layout_flush(self) -> None:
        if self._pending_layout_flush:
            return
        self._pending_layout_flush = True
        QTimer.singleShot(0, self._flush_pending_layout_sizes)

    def _flush_pending_layout_sizes(self) -> None:
        self._pending_layout_flush = False
        if self._pending_workspace_splitter_sizes is not None:
            sizes = [int(value) for value in self._pending_workspace_splitter_sizes]
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

    def _set_workspace_splitter_sizes(self, sizes: list[int]) -> None:
        self._pending_workspace_splitter_sizes = [int(value) for value in sizes]
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
        self._loading_event = True
        if event is None:
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
            self.clip_table.setRowCount(0)
            self.set_object_context(
                object_type="Folder",
                object_name="未选择对象",
                breadcrumb="Project / Root",
                stats_text="片段 0 | 标签 0",
                summary_primary="模式 - | 总线 -",
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
            self._loading_event = False
            return

        self.status_label.setText(f"当前事件：{event.id}")
        event_tags = sorted({tag for clip in event.clips for tag in getattr(clip, "tags", [])})
        self.set_object_context(
            object_type="Event",
            object_name=event.display_name or event.id,
            breadcrumb=f"Project / Event / {event.id}",
            stats_text=f"片段 {len(event.clips)} | 标签 {len(event_tags)}",
            summary_primary=f"模式 {event.play_mode} | 总线 {event.bus}",
            summary_secondary=f"实例 {'不限' if event.max_instances == 0 else event.max_instances} | 导出 {self.runtime_audio_format_combo.currentText()}",
            can_navigate_parent=True,
        )
        self.event_id_edit.setText(event.id)
        self.display_name_edit.setText(event.display_name)
        self.tags_summary_edit.setText(", ".join(event_tags))
        event_bus_index = self.bus_combo.findData(event.bus)
        if event_bus_index >= 0:
            self.bus_combo.setCurrentIndex(event_bus_index)
        self.play_mode_combo.setCurrentText(event.play_mode)
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
        self._set_clip_rows(event)
        self._clip_lookup = {clip.id: clip for clip in event.clips}
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
        if event.clips and not self.clip_table.selected_clip_ids():
            self.clip_table.selectRow(0)
        self._sync_clip_detail_from_table()
        self.clear_preview_audio_metrics("切换对象后等待新的试听结果。")
        self._loading_event = False

    def _sync_event_mode_ui(self) -> None:
        is_combo_mode = self.play_mode_combo.currentText() == "Combo"
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

    def selected_tree_payloads(self) -> list[tuple[str, str]]:
        return self.tree.selected_payloads()

    def selected_tree_event_ids(self) -> list[str]:
        return self.tree.selected_event_ids()

    def _current_workspace_context_text(self) -> str:
        mode_title = self.shell_mode_title_label.text()
        editor_index = self.editor_tabs.currentIndex()
        if self._active_workspace_mode == "home":
            editor_title = "欢迎页"
        elif self._active_workspace_mode in {"validation", "results", "validation-results", "build-results", "loudness-results"}:
            editor_title = f"结果/{self._report_page_titles[self._active_report_index].replace('当前：', '')}"
        elif self._active_workspace_mode == "events":
            editor_title = f"事件设计/{self.events_workspace_tabs.tabText(self.events_workspace_tabs.currentIndex())}"
        elif self._active_workspace_mode == "buses":
            editor_title = "总线与混音/混音台"
        elif self._active_workspace_mode == "build":
            editor_title = "构建交付/交付准备"
        elif self._active_workspace_mode == "resources":
            editor_title = f"资源整理/{self.contents_tabs.tabText(self.contents_tabs.currentIndex())}"
        elif editor_index == 0:
            editor_title = f"属性/{self.property_tabs.tabText(self.property_tabs.currentIndex())}"
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
        self._apply_scrollable_widget_state(output, state.get("output"))

    def navigation_state(self) -> dict[str, object]:
        return {
            "workspace_mode": self._active_workspace_mode,
            "editor_tab": self.editor_tabs.currentIndex(),
            "property_tab": self.property_tabs.currentIndex(),
            "events_workspace_tab": self.events_workspace_tabs.currentIndex(),
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
        }

    def apply_navigation_state(self, state: dict[str, object] | None) -> None:
        if not state:
            return
        workspace_mode = state.get("workspace_mode")
        workspace_sizes = state.get("workspace_splitter_sizes")
        main_sizes = state.get("main_splitter_sizes")
        content_sizes = state.get("content_top_splitter_sizes")
        editor_tab = state.get("editor_tab")
        property_tab = state.get("property_tab")
        events_workspace_tab = state.get("events_workspace_tab")
        contents_tab = state.get("contents_tab")
        report_tab = state.get("report_tab")
        if isinstance(workspace_sizes, list) and len(workspace_sizes) == 2:
            self._set_workspace_splitter_sizes([int(value) for value in workspace_sizes])
        if isinstance(main_sizes, list) and len(main_sizes) == 2:
            self._set_main_splitter_sizes([int(value) for value in main_sizes])
        if isinstance(content_sizes, list) and len(content_sizes) == 2:
            self._set_content_top_splitter_sizes([int(value) for value in content_sizes])
        if isinstance(editor_tab, int) and 0 <= editor_tab < self.editor_tabs.count():
            self.editor_tabs.setCurrentIndex(editor_tab)
        if isinstance(property_tab, int) and 0 <= property_tab < self.property_tabs.count():
            self.property_tabs.setCurrentIndex(property_tab)
        if isinstance(events_workspace_tab, int) and 0 <= events_workspace_tab < self.events_workspace_tabs.count():
            self.events_workspace_tabs.setCurrentIndex(events_workspace_tab)
        if isinstance(contents_tab, int) and 0 <= contents_tab < self.contents_tabs.count():
            self.contents_tabs.setCurrentIndex(contents_tab)
        if isinstance(report_tab, int) and 0 <= report_tab < len(self._report_page_titles):
            self._active_report_index = report_tab
            self.report_pages.setCurrentIndex(report_tab)
            self.report_tabs.setCurrentIndex(report_tab)
        if isinstance(workspace_mode, str) and workspace_mode in self._workspace_mode_pages:
            self._activate_workspace_mode(workspace_mode)
        self._apply_scrollable_widget_state(self._current_property_scroll_widget(), state.get("property_scroll"))
        self._apply_scrollable_widget_state(self.contents_tabs.currentWidget(), state.get("contents_scroll"))
        self._apply_scrollable_widget_state(self.log_output, state.get("log_scroll"))
        self._restore_report_panel_state(self.validation_issue_list, self.validation_report_output, state.get("validation_report_panel"))
        self._restore_report_panel_state(self.build_issue_list, self.build_report_output, state.get("build_report_panel"))
        self._restore_report_panel_state(self.loudness_issue_list, self.loudness_report_output, state.get("loudness_report_panel"))

    def _update_object_bus_status(self) -> None:
        current_event_bus = self._current_event_bus_name() or "-"
        current_project_bus = self.current_project_bus_name() or "-"
        self.object_event_bus_chip.setText(f"事件总线 {current_event_bus}")
        if self._project_bus_selection_overridden and current_project_bus != current_event_bus:
            self.object_bus_browser_chip.setText(f"手动浏览 {current_project_bus}")
            bus_hint = f"当前正在浏览其他总线 {current_project_bus}；点击“跟随事件总线”可回到当前事件。"
        else:
            self.object_bus_browser_chip.setText(f"跟随事件 {current_project_bus}")
            bus_hint = f"当前总线浏览跟随事件 {current_project_bus}。"
        self.object_context_hint_label.setText(f"{self._current_workspace_context_text()} | {bus_hint}")
        self._update_workspace_summary_labels()

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

        self.events_workspace_status_label.setText(
            f"已选事件 {selected_event_count} | 当前子页 {event_workspace_title} | 事件总线 {current_event_bus}。"
        )
        self.event_overview_hint_label.setText(
            f"对象摘要已前置到左侧。当前浏览 {event_workspace_title}，可快速跳去资源片段或校验结果继续处理。"
        )
        self.resources_workspace_status_label.setText(
            f"已选片段 {selected_clip_count} | 当前页 {resources_workspace_title} | 资源整理后可直接切到生成预览。"
        )
        self.resources_overview_hint_label.setText(
            f"当前浏览 {resources_workspace_title}，已选片段 {selected_clip_count}。先做片段编排，再进批处理或预览镜像。"
        )
        self.buses_workspace_status_label.setText(
            f"浏览总线 {current_project_bus} | 事件总线 {current_event_bus} | 默认总线 {self.default_bus_combo.currentText() or '-'}。"
        )
        self.buses_overview_hint_label.setText(
            f"当前浏览总线 {current_project_bus}。可直接切默认总线、挂到 Master，或回到事件总线继续调整。"
        )
        self.build_workspace_status_label.setText(
            f"导出目录 {export_root} | 运行时格式 {runtime_format} | 最近结果页 {current_results_title}。"
        )
        self.build_overview_hint_label.setText(
            f"导出目录 {export_root}，运行时格式 {runtime_format}。构建后优先回看 {current_results_title}。"
        )
        self.validation_overview_hint_label.setText(
            f"{self.validation_filter_status_label.text()} 当前结果页为 {current_results_title}。"
        )
        self.results_overview_hint_label.setText(
            f"当前结果页 {current_results_title}。可在这里统一回看日志、校验、构建和响度输出。"
        )

    def _build_report_center_page(self, summary_label: QLabel, issue_list: QListWidget, detail_output: QPlainTextEdit) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        summary_label.setWordWrap(True)
        issue_list.setAlternatingRowColors(True)
        splitter = QSplitter()
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
        severity = str(payload.get("severity", "")).strip().casefold()
        if severity == "error":
            return "error"
        if severity == "warning":
            return "warning"
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
                self._activate_workspace_mode("buses")
            elif category == "生成":
                self._activate_workspace_mode("build")
            elif category == "工程":
                self._activate_workspace_mode("buses")
            else:
                self._activate_workspace_mode("events")
            self.editor_tabs.setCurrentIndex(0)
            self.property_tabs.setCurrentIndex(index)
            self._update_object_bus_status()

    def show_loudness_view(self) -> None:
        self._activate_workspace_mode("events")
        self.editor_tabs.setCurrentIndex(2)
        self.events_workspace_tabs.setCurrentIndex(1)
        self._update_object_bus_status()

    def set_active_contents_category(self, category: str) -> None:
        if category == "生成":
            self._activate_workspace_mode("build")
        else:
            self._activate_workspace_mode("resources")
        self.editor_tabs.setCurrentIndex(1)
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
            self.clip_loop_start_spin.setValue(0)
            self.clip_loop_end_spin.setValue(0)
            self.clip_tags_detail_edit.clear()
            self.clip_preview_hint_label.setText("选择片段后可在此调整资源键、裁剪、循环和标签。快捷键：Delete 删除，Ctrl+C 复制资源键。")
            self.clip_preview_button.setEnabled(False)
            self.clip_copy_asset_key_button.setEnabled(False)
            self.clip_locate_source_button.setEnabled(False)
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
        self.clip_loop_start_spin.setValue(clip.loop_start_ms)
        self.clip_loop_end_spin.setValue(clip.loop_end_ms)
        self.clip_tags_detail_edit.setText(", ".join(getattr(clip, "tags", [])))
        hint_segments = [
            f"源文件：{clip.source_path or '未指定'}",
            f"权重：相对值 {MIN_CLIP_WEIGHT}-{MAX_CLIP_WEIGHT}",
            "Loop：一期未开放，当前不参与试听和运行时执行",
        ]
        if clip_duration_ms is not None:
            hint_segments.append(f"可编辑时间范围：0-{clip_duration_ms} ms")
            if any(value > clip_duration_ms for value in [clip.trim_start_ms, clip.loop_start_ms]) or any(value > clip_duration_ms for value in [clip.trim_end_ms, clip.loop_end_ms] if value > 0):
                hint_segments.append("当前裁剪或循环值已超出源文件长度，请修正")
        else:
            hint_segments.append("无法读取音频时长，时间字段使用通用上限")
        selected_count = len(self.selected_clip_ids())
        if selected_count > 1:
            hint_segments.insert(0, f"已选 {selected_count} 个片段，当前正在编辑首条")
        else:
            hint_segments.insert(0, f"当前片段 {clip.id} 可直接精修")
        hint_segments.append("Enter 可聚焦详情，Ctrl+C 可复制资源键")
        self.clip_preview_hint_label.setText(" | ".join(hint_segments))
        self.clip_preview_button.setEnabled(True)
        self.clip_copy_asset_key_button.setEnabled(True)
        self.clip_locate_source_button.setEnabled(True)
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
            self.clip_loop_start_spin,
            self.clip_loop_end_spin,
        ]:
            spin_box.setRange(MIN_CLIP_TIME_MS, maximum_ms)
        return duration_ms

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
        spacer = QWidget()
        spacer.setMinimumHeight(1200)
        layout.addWidget(spacer)
        layout.addStretch(1)
        return self._wrap_scrollable_page(content)

    def _current_property_compat_widget(self) -> QWidget | None:
        index = self.property_tabs.currentIndex()
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

    def _build_two_column_page(self, left_widgets: list[QWidget], right_widgets: list[QWidget]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        left_column = QVBoxLayout()
        right_column = QVBoxLayout()
        for widget in left_widgets:
            left_column.addWidget(widget)
        left_column.addStretch(1)
        for widget in right_widgets:
            right_column.addWidget(widget)
        right_column.addStretch(1)
        left_container = QWidget()
        left_container.setLayout(left_column)
        right_container = QWidget()
        right_container.setLayout(right_column)
        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_container)
        splitter.addWidget(right_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
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
        self.report_detail_label.setText(f"最近日志：{message[:80]}")
        self.report_detail_label.setToolTip(message)
        self._update_workspace_summary_labels()

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
            "active_editor_tab": self.editor_tabs.currentIndex(),
            "inspector_splitter_sizes": None,
            "content_top_splitter_sizes": self.content_top_splitter.sizes(),
            "active_contents_tab": self.contents_tabs.currentIndex(),
            "event_import_template": self.current_event_import_template_defaults(),
        }

    def apply_ui_preferences(self, preferences: dict[str, object]) -> None:
        ui_scale = float(preferences.get("ui_scale", 1.0) or 1.0)
        self.set_ui_scale(ui_scale)
        workspace_sizes = preferences.get("workspace_splitter_sizes")
        main_sizes = preferences.get("main_splitter_sizes")
        active_editor_tab = preferences.get("active_editor_tab")
        content_top_sizes = preferences.get("content_top_splitter_sizes")
        active_contents_tab = preferences.get("active_contents_tab")
        event_import_template = preferences.get("event_import_template")
        if isinstance(workspace_sizes, list) and len(workspace_sizes) == 2:
            self._set_workspace_splitter_sizes([int(value) for value in workspace_sizes])
        if isinstance(main_sizes, list) and len(main_sizes) == 2:
            self._set_main_splitter_sizes([int(value) for value in main_sizes])
        if isinstance(active_editor_tab, int) and 0 <= active_editor_tab < self.editor_tabs.count():
            self.editor_tabs.setCurrentIndex(active_editor_tab)
        if isinstance(content_top_sizes, list) and len(content_top_sizes) == 2:
            self._set_content_top_splitter_sizes([int(value) for value in content_top_sizes])
        if isinstance(active_contents_tab, int) and 0 <= active_contents_tab < self.contents_tabs.count():
            self.contents_tabs.setCurrentIndex(active_contents_tab)
        if isinstance(event_import_template, dict):
            self._event_import_template_defaults = {
                "bus_name": str(event_import_template.get("bus_name", "")),
                "asset_prefix": str(event_import_template.get("asset_prefix", "")),
                "tags": [str(tag) for tag in event_import_template.get("tags", [])],
            }
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
        self.export_root_edit.setText(settings.export_root)
        self.source_audio_format_combo.setCurrentText(settings.source_audio_format)
        self.runtime_audio_format_combo.setCurrentText(settings.runtime_audio_format)
        self.project_bus_default_label.setText(f"默认总线：{settings.default_bus}")
        self._sync_event_import_template_controls(settings.buses)
        self._load_selected_project_bus_details()
        self._loading_event = False

    def _current_event_bus_name(self) -> str:
        current_data = self.bus_combo.currentData()
        if current_data is None:
            return self.bus_combo.currentText().strip()
        return str(current_data).strip()

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
            }
            for config in self._project_bus_configs
        ]
        buses = [config["name"] for config in bus_configs if config["name"] != "Master"]
        return {
            "default_bus": self.default_bus_combo.currentText(),
            "export_root": self.export_root_edit.text().strip() or "./Export",
            "buses": buses or list(DEFAULT_BUSES),
            "bus_configs": bus_configs,
            "source_audio_format": self.source_audio_format_combo.currentText(),
            "runtime_audio_format": self.runtime_audio_format_combo.currentText(),
        }

    def current_project_bus_name(self) -> str:
        item = self.project_bus_list.currentItem()
        if item is None:
            return ""
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

    def _rebuild_project_bus_route_bar(self, route_names: list[str]) -> None:
        layout = self.project_bus_route_bar.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not route_names:
            placeholder = QLabel("未选择总线")
            placeholder.setProperty("role", "meterContext")
            layout.addWidget(placeholder)
            layout.addStretch(1)
            return
        for index, route_name in enumerate(route_names):
            button = QToolButton()
            button.setText(route_name)
            button.setProperty("role", "routeChip")
            button.clicked.connect(lambda _checked=False, name=route_name: self._select_project_bus_by_name(name))
            layout.addWidget(button)
            if index < len(route_names) - 1:
                separator = QLabel("/")
                separator.setProperty("role", "meterContext")
                layout.addWidget(separator)
        layout.addStretch(1)

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
                }
            )
            seen.add(key)
        if not normalized_children:
            normalized_children = [
                {"name": bus_name, "original_name": bus_name, "parent_bus": "Master", "volume_db": 0.0, "is_muted": False}
                for bus_name in DEFAULT_BUSES
            ]
        self._project_bus_configs = [normalized_master, *normalized_children]
        self._rebuild_project_bus_tree(selected_bus_name=selected_bus_name)
        self.project_bus_count_label.setText(f"总线 {len(self._project_bus_configs) - 1} 条")
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
            self._active_project_bus_name = ""
            self.project_bus_name_edit.clear()
            self.project_bus_parent_combo.clear()
            self.project_bus_volume_spin.setValue(0.0)
            self.project_bus_mute_check.setChecked(False)
            self.project_bus_export_label.setText("未选择总线")
            self.project_bus_route_label.setText("未选择总线")
            self._rebuild_project_bus_route_bar([])
            self.project_bus_children_label.setText("下游总线：-")
            self.project_bus_effective_value.setText("0%")
            self.project_bus_effective_bar.setValue(0)
            self.inline_bus_group.setTitle("当前输出总线")
            self.inline_bus_set_default_button.setEnabled(False)
            self.inline_bus_to_master_button.setEnabled(False)
            self.inline_bus_open_parent_button.setEnabled(False)
            self.project_bus_summary_label.setText("在左侧选择总线后，可在音频属性页直接编辑当前总线。")
            self.inline_bus_name_chip.setText("总线 -")
            self.inline_bus_parent_chip.setText("父级 -")
            self.inline_bus_default_chip.setText("默认 -")
            self.inline_bus_export_chip.setText("导出 -")
            return
        config = self._project_bus_configs[row]
        bus_name = str(config["name"])
        self._active_project_bus_name = bus_name
        self.project_bus_name_edit.setText(bus_name)
        self._refresh_project_bus_parent_options(bus_name, str(config.get("parent_bus", "Master")))
        self.project_bus_volume_spin.setValue(float(config["volume_db"]))
        self.project_bus_mute_check.setChecked(bool(config["is_muted"]))
        role_text = "默认输出总线" if self.default_bus_combo.currentText() == bus_name else "普通输出总线"
        route_text = " -> ".join(self._project_bus_route_names(bus_name))
        child_names = [str(item["name"]) for item in self._project_bus_child_configs() if str(item.get("parent_bus", "Master")) == bus_name]
        effective_linear = self._project_bus_effective_linear(bus_name)
        self.project_bus_route_label.setText(route_text)
        self._rebuild_project_bus_route_bar(self._project_bus_route_names(bus_name))
        self.project_bus_children_label.setText("下游总线：" + (", ".join(child_names) if child_names else "-"))
        self.project_bus_effective_value.setText(f"{effective_linear * 100:.0f}%")
        self.project_bus_effective_bar.setValue(int(effective_linear * 100.0))
        self.project_bus_export_label.setText(f"{role_text}，已写入 BusConfigs；Unity 初始化会按该路由链恢复音量与静音。")
        self.inline_bus_group.setTitle(f"当前输出总线：{bus_name}")
        self.inline_bus_set_default_button.setEnabled(self.default_bus_combo.currentText() != bus_name)
        parent_bus_name = str(config.get("parent_bus", "Master") or "Master")
        self.inline_bus_open_parent_button.setEnabled(parent_bus_name != "Master")
        self.inline_bus_name_chip.setText(f"总线 {bus_name}")
        self.inline_bus_parent_chip.setText(f"父级 {parent_bus_name}")
        self.inline_bus_default_chip.setText("默认 是" if self.default_bus_combo.currentText() == bus_name else "默认 否")
        self.inline_bus_export_chip.setText("导出 BusConfigs")
        self.project_bus_summary_label.setText(
            f"当前选中：{bus_name}\n路由：{route_text}\n下游：{', '.join(child_names) if child_names else '无'}\n常用编辑已整合到音频属性页。"
        )

    def _sync_project_bus_editor_to_state(
        self,
        show_errors: bool = True,
        bus_name: str | None = None,
        selected_bus_name: str | None = None,
    ) -> bool:
        target_bus_name = bus_name or self.current_project_bus_name()
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
                QMessageBox.warning(self, "总线名称重复", f"总线“{new_name}”已存在，请换一个名称。")
            return False
        if new_parent_bus.casefold() == new_name.casefold():
            self.project_bus_parent_combo.blockSignals(True)
            self.project_bus_parent_combo.setCurrentText("Master")
            self.project_bus_parent_combo.blockSignals(False)
            if show_errors:
                QMessageBox.warning(self, "父总线非法", "总线不能把自己作为父总线。")
            return False
        if self._would_create_project_bus_cycle(new_name, new_parent_bus):
            self.project_bus_parent_combo.blockSignals(True)
            self.project_bus_parent_combo.setCurrentText("Master")
            self.project_bus_parent_combo.blockSignals(False)
            if show_errors:
                QMessageBox.warning(self, "父总线非法", "当前选择会形成总线路由环，请改为 Master 或其他上游总线。")
            return False
        current_config["name"] = new_name
        current_config["parent_bus"] = new_parent_bus
        current_config["volume_db"] = float(self.project_bus_volume_spin.value())
        current_config["is_muted"] = bool(self.project_bus_mute_check.isChecked())
        current_default_bus = self.default_bus_combo.currentText()
        if current_default_bus.casefold() == current_name.casefold() and current_default_bus != new_name:
            current_default_bus = new_name
        for config in self._project_bus_configs:
            if str(config.get("parent_bus", "Master")).casefold() == current_name.casefold() and config is not current_config:
                config["parent_bus"] = new_name
        self.set_bus_options([str(config["name"]) for config in self._project_bus_child_configs()])
        self.default_bus_combo.setCurrentText(current_default_bus)
        self.project_bus_default_label.setText(f"默认总线：{self.default_bus_combo.currentText() or '-'}")
        self.project_bus_count_label.setText(f"总线 {len(self._project_bus_configs) - 1} 条")
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
            selected_bus_name=selected_bus_name or new_name,
        )
        self.default_bus_combo.setCurrentText(current_default_bus)
        self.project_bus_default_label.setText(f"默认总线：{self.default_bus_combo.currentText() or '-'}")
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
                self.projectSettingsChanged.emit()
        if not self._loading_event and not self._syncing_project_bus_selection:
            self._project_bus_selection_overridden = True
        self._load_selected_project_bus_details()
        self._update_object_bus_status()

    def _select_project_bus_by_name(self, bus_name: str) -> bool:
        if not bus_name:
            return False
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
            self.inline_bus_group.setTitle("当前输出总线")
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
            QMessageBox.warning(self, "新建总线失败", f"总线“{bus_name}”已存在。")
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
        self.project_bus_default_label.setText(f"默认总线：{bus_name}")
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
            QMessageBox.information(self, "切到父总线", "当前总线已经直接挂在 Master 下。")
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
            QMessageBox.warning(self, "新建总线失败", f"总线“{bus_name}”已存在。")
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
        self.project_bus_default_label.setText(f"默认总线：{self.default_bus_combo.currentText() or '-'}")
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def _request_remove_project_bus(self) -> None:
        row = self._selected_project_bus_index()
        if row < 0:
            return
        if str(self._project_bus_configs[row]["name"]) == "Master":
            QMessageBox.information(self, "删除总线", "Master 是固定总线，不能删除。")
            return
        if len(self._project_bus_configs) <= 2:
            QMessageBox.information(self, "删除总线", "工程至少需要保留一条总线。")
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
        self.project_bus_default_label.setText(f"默认总线：{self.default_bus_combo.currentText() or '-'}")
        self._load_selected_project_bus_details()
        self._emit_project_settings_changed()

    def current_event_form_data(self) -> dict[str, object]:
        return {
            "id": self.event_id_edit.text().strip(),
            "display_name": self.display_name_edit.text().strip(),
            "bus": self._current_event_bus_name(),
            "play_mode": self.play_mode_combo.currentText(),
            "steal_policy": self.steal_policy_combo.currentText(),
            "load_policy": self.load_policy_combo.currentText(),
            "source_audio_format": self.source_audio_format_combo.currentText(),
            "runtime_audio_format": self.runtime_audio_format_combo.currentText(),
            "volume_db": self.volume_spin.value(),
            "volume_rand_min_db": self.volume_rand_min_spin.value(),
            "volume_rand_max_db": self.volume_rand_max_spin.value(),
            "pitch_cents": int(self.pitch_spin.value()),
            "pitch_rand_min_cents": self.pitch_rand_min_spin.value(),
            "pitch_rand_max_cents": self.pitch_rand_max_spin.value(),
            "cooldown_seconds": self.cooldown_spin.value(),
            "max_instances": self.max_instances_spin.value(),
            "combo_pitch_step_cents": self.combo_pitch_step_spin.value() * 100,
            "combo_reset_seconds": self.combo_reset_spin.value(),
            "combo_max_step": self.combo_max_step_spin.value(),
            "avoid_immediate_repeat": self.avoid_repeat_check.isChecked(),
            "tags": [tag.strip() for tag in self.tags_summary_edit.text().split(",") if tag.strip()],
            "notes": self.notes_edit.toPlainText().strip(),
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
        self.build_summary_label.setText("构建问题中心：优先看 Schema、BusConfigs、资源差异与导出数量。")
        self.report_detail_label.setText("构建报告已刷新，生成预览已同步。")
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

    def show_report_tab(self, index: int) -> None:
        if not 0 <= index < len(self._report_page_titles):
            return
        self._active_report_index = index
        self.report_pages.setCurrentIndex(index)
        self.report_tabs.setCurrentIndex(index)
        report_title = self._report_page_titles[index]
        self.report_focus_label.setText(report_title)
        self.workspace_report_focus_label.setText(report_title)
        self.activity_report_focus_label.setText(report_title)
        if index == 1:
            self._activate_workspace_mode("validation-results")
        elif index == 2:
            self._activate_workspace_mode("build-results")
        elif index == 3:
            self._activate_workspace_mode("loudness-results")
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
            "导入后挂到哪个总线",
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
        bus_name, accepted = QInputDialog.getText(self, "新建总线", "总线名称")
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
            "批量修改事件总线",
            "目标总线",
            bus_names,
            current=bus_names.index(current_bus) if current_bus in bus_names else 0,
            editable=False,
        )
        return bus_name if accepted and bus_name else None

    def confirm_delete(self, label: str) -> bool:
        result = QMessageBox.question(self, APP_NAME, label)
        return result == QMessageBox.StandardButton.Yes

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
        self.editor_tabs.setCurrentIndex(0)
        self.property_tabs.setCurrentIndex(0)
        self._set_content_top_splitter_sizes(self._default_content_top_splitter_sizes)
        self.contents_tabs.setCurrentIndex(0)
        self._active_report_index = 0
        self.report_pages.setCurrentIndex(0)
        self.report_tabs.setCurrentIndex(0)
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
            self.editor_tabs.setCurrentIndex(0)
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
        elif panel_key == "contents":
            self._activate_workspace_mode("resources")
            self.editor_tabs.setCurrentIndex(1)
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
            self.contents_tabs.setCurrentIndex(0)
            self._set_content_top_splitter_sizes(self._default_focus_content_splitter_sizes)
        elif panel_key == "meter":
            self._activate_workspace_mode("events")
            self.editor_tabs.setCurrentIndex(2)
            self._set_main_splitter_sizes([int(main_total * 0.18), int(main_total * 0.82)])
        elif panel_key == "log":
            self._activate_workspace_mode("results")
            self._set_workspace_splitter_sizes([int(workspace_total * 0.62), int(workspace_total * 0.38)])
        self._update_object_bus_status()

    def _bind_shortcuts(self) -> None:
        self._shortcuts = [
            QShortcut(QKeySequence("Delete"), self),
            QShortcut(QKeySequence("F2"), self),
            QShortcut(QKeySequence("Return"), self),
            QShortcut(QKeySequence("Enter"), self),
            QShortcut(QKeySequence.StandardKey.Copy, self),
        ]
        self._shortcuts[0].activated.connect(self._handle_delete_shortcut)
        self._shortcuts[1].activated.connect(self._handle_rename_shortcut)
        self._shortcuts[2].activated.connect(self._handle_open_shortcut)
        self._shortcuts[3].activated.connect(self._handle_open_shortcut)
        self._shortcuts[4].activated.connect(self._handle_copy_shortcut)

    def _handle_delete_shortcut(self) -> None:
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self._request_remove_clips()
            return
        if self._focus_is_within(self.tree) or self._focus_is_within(self.tree_filter_edit):
            self.deleteSelectedRequested.emit()

    def _handle_rename_shortcut(self) -> None:
        if self._focus_is_within(self.tree) or self._focus_is_within(self.tree_filter_edit):
            self.renameSelectedRequested.emit()
            return
        if self._focus_is_within(self.clip_table) and self.selected_clip_ids():
            self._request_batch_rename()

    def _handle_open_shortcut(self) -> None:
        if self._focus_is_within(self.tree) or self._focus_is_within(self.tree_filter_edit):
            payload = self._selected_tree_payload()
            if payload is None:
                return
            if payload[0] == "event":
                self.set_active_property_category("事件")
                self.event_id_edit.setFocus()
                self.event_id_edit.selectAll()
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
        if self._focus_is_within(self.tree) or self._focus_is_within(self.tree_filter_edit):
            payload = self._selected_tree_payload()
            if payload is None:
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
        self.audio_meter_short_term_value.setText(self._format_meter_value(processed.short_term_lufs))
        self.audio_meter_short_term_max_value.setText(self._format_meter_value(processed.short_term_max_lufs))
        self.audio_meter_integrated_value.setText(self._format_meter_value(processed.integrated_lufs))
        self.audio_meter_momentary_value.setText(self._format_meter_value(processed.momentary_lufs))
        self.audio_meter_momentary_max_value.setText(self._format_meter_value(processed.momentary_max_lufs))
        self.audio_meter_lra_value.setText(f"{processed.loudness_range_lu:.1f}")
        self.audio_meter_true_peak_value.setText(self._format_meter_value(true_peak_db))
        self.audio_meter_summary_source_integrated_value.setText(self._format_meter_value(source.integrated_lufs))
        self.audio_meter_summary_source_true_peak_value.setText(self._format_meter_value(source.true_peak_db))
        self.audio_meter_summary_integrated_value.setText(self._format_meter_value(processed.integrated_lufs))
        self.audio_meter_summary_true_peak_value.setText(self._format_meter_value(true_peak_db))
        self.audio_meter_left_peak_value.setText(self._format_meter_value(left_peak_db))
        self.audio_meter_left_rms_value.setText(self._format_meter_value(processed.left_rms_db))
        self.audio_meter_right_peak_value.setText(self._format_meter_value(right_peak_db))
        self.audio_meter_right_rms_value.setText(self._format_meter_value(processed.right_rms_db))
        self.audio_meter_left_bar.setValue(self._meter_progress(left_peak_db))
        self.audio_meter_right_bar.setValue(self._meter_progress(right_peak_db))
        self.momentary_plot.set_series(source.momentary_history or [], processed.momentary_history or [])
        self.short_term_plot.set_series(source.short_term_history or [], processed.short_term_history or [])
        self.show_loudness_view()

    def clear_preview_audio_metrics(self, reason: str) -> None:
        self._held_true_peak_db = None
        self._held_left_peak_db = None
        self._held_right_peak_db = None
        self.audio_meter_context_label.setText(reason)
        self.audio_meter_summary_source_context_label.setText(reason)
        self.audio_meter_summary_context_label.setText(reason)
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
        self.command_button.clicked.connect(self._show_command_quick_reference)
        self.global_search_edit.returnPressed.connect(self._request_global_search)
        self.global_search_edit.textChanged.connect(self._sync_global_search_fields)
        self.global_search_button.clicked.connect(self._request_global_search)
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
        self.events_workspace_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.contents_tabs.currentChanged.connect(lambda _index: self._update_workspace_summary_labels())
        self.clear_meter_button.clicked.connect(self.clear_peak_hold)
        self.loudness_scan_button.clicked.connect(self.loudnessScanRequested.emit)
        self.clip_preview_button.clicked.connect(self._request_selected_clip_preview)
        self.clip_copy_asset_key_button.clicked.connect(self._copy_selected_clip_asset_keys)
        self.clip_locate_source_button.clicked.connect(self._locate_selected_clip_source)
        self.clip_table.itemSelectionChanged.connect(self._sync_clip_detail_from_table)
        self.event_id_edit.editingFinished.connect(self._emit_event_properties_changed)
        self.display_name_edit.editingFinished.connect(self._emit_event_properties_changed)
        self.bus_combo.currentIndexChanged.connect(self._emit_event_properties_changed)
        self.bus_combo.currentIndexChanged.connect(self._sync_current_event_bus_selection)
        self.play_mode_combo.currentIndexChanged.connect(self._emit_event_properties_changed)
        self.play_mode_combo.currentIndexChanged.connect(self._sync_event_mode_ui)
        self.steal_policy_combo.currentIndexChanged.connect(self._emit_event_properties_changed)
        self.load_policy_combo.currentIndexChanged.connect(self._emit_event_properties_changed)
        self.source_audio_format_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.runtime_audio_format_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.default_bus_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.project_bus_list.itemSelectionChanged.connect(self._handle_project_bus_selection_changed)
        self.project_bus_list.hierarchyChanged.connect(self._handle_project_bus_hierarchy_changed)
        self.project_bus_name_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.project_bus_parent_combo.currentIndexChanged.connect(self._emit_project_settings_changed)
        self.project_bus_volume_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.project_bus_mute_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.project_master_volume_spin.valueChanged.connect(self._emit_project_settings_changed)
        self.project_master_mute_check.checkStateChanged.connect(self._emit_project_settings_changed)
        self.inline_bus_new_button.clicked.connect(self._request_add_and_assign_project_bus)
        self.inline_bus_set_default_button.clicked.connect(self._set_current_bus_as_default)
        self.inline_bus_to_master_button.clicked.connect(self._route_current_bus_to_master)
        self.inline_bus_open_parent_button.clicked.connect(self._select_parent_bus_for_current)
        self.project_bus_focus_audio_button.clicked.connect(lambda: self.set_active_property_category("音频属性"))
        self.project_bus_add_button.clicked.connect(self._request_add_project_bus)
        self.project_bus_remove_button.clicked.connect(self._request_remove_project_bus)
        self.preview_bus_combo.currentIndexChanged.connect(self.previewBusSelectionChanged.emit)
        self.preview_bus_volume_spin.valueChanged.connect(self._emit_preview_bus_state_changed)
        self.preview_bus_mute_check.checkStateChanged.connect(self._emit_preview_bus_state_changed)
        self.import_template_bus_combo.currentIndexChanged.connect(self._update_event_import_template_defaults_from_controls)
        self.import_template_asset_prefix_edit.editingFinished.connect(self._update_event_import_template_defaults_from_controls)
        self.import_template_tags_edit.editingFinished.connect(self._update_event_import_template_defaults_from_controls)
        self.export_root_browse_button.clicked.connect(self._request_export_root_browse)
        self.export_root_edit.editingFinished.connect(self._emit_project_settings_changed)
        self.volume_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.volume_rand_min_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.volume_rand_max_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.pitch_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.pitch_rand_min_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.pitch_rand_max_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.cooldown_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.max_instances_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.max_instances_spin.valueChanged.connect(self._sync_event_mode_ui)
        self.combo_pitch_step_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.combo_reset_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.combo_max_step_spin.valueChanged.connect(self._emit_event_properties_changed)
        self.avoid_repeat_check.checkStateChanged.connect(self._emit_event_properties_changed)
        self.notes_edit.textChanged.connect(self._emit_event_properties_changed)
        self.tags_summary_edit.editingFinished.connect(self._emit_event_properties_changed)
        self.clip_source_detail_edit.editingFinished.connect(lambda: self._emit_selected_clip_detail_change("source_path", self.clip_source_detail_edit.text()))
        self.clip_asset_detail_edit.editingFinished.connect(lambda: self._emit_selected_clip_detail_change("asset_key", self.clip_asset_detail_edit.text()))
        self.clip_weight_detail_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("weight", str(value)))
        self.clip_weight_detail_spin.valueChanged.connect(lambda value: self._sync_weight_preset_combo(self.clip_weight_preset_combo, value))
        self.clip_weight_preset_combo.currentIndexChanged.connect(lambda: self._apply_weight_preset(self.clip_weight_detail_spin, self.clip_weight_preset_combo))
        self.clip_trim_start_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("trim_start_ms", str(value)))
        self.clip_trim_end_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("trim_end_ms", str(value)))
        self.clip_loop_start_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("loop_start_ms", str(value)))
        self.clip_loop_end_spin.valueChanged.connect(lambda value: self._emit_selected_clip_detail_change("loop_end_ms", str(value)))
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
        self.clip_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.clip_table.customContextMenuRequested.connect(self._show_clip_context_menu)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._handle_open_shortcut())
        self.clip_table.itemDoubleClicked.connect(lambda item: self._handle_open_shortcut())
        self.validation_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.validation_issue_list, self.validation_report_output))
        self.validation_issue_list.itemSelectionChanged.connect(self._sync_validation_issue_actions)
        self.build_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.build_issue_list, self.build_report_output))
        self.loudness_issue_list.itemSelectionChanged.connect(lambda: self._update_report_detail_from_item(self.loudness_issue_list, self.loudness_report_output))
        self.validation_issue_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.validation_issue_list))
        self.loudness_issue_list.itemDoubleClicked.connect(lambda item: self._activate_report_item(self.loudness_issue_list))
        self.tree_filter_edit.textChanged.connect(self.tree.apply_filter)
        self.tree_filter_edit.returnPressed.connect(self._search_next_tree_event)
        self.tree_search_button.clicked.connect(self._search_next_tree_event)
        self.clip_filter_edit.textChanged.connect(self._apply_clip_filter)
        self.recent_projects_list.itemDoubleClicked.connect(lambda item: self.openRecentProjectRequested.emit(item.text()))

    def _emit_event_properties_changed(self, *args) -> None:
        if not self._loading_event and self.property_group.isEnabled():
            self.eventPropertiesChanged.emit()

    def _emit_project_settings_changed(self, *args) -> None:
        if not self._loading_event and self._sync_project_bus_editor_to_state(show_errors=True):
            self.projectSettingsChanged.emit()

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
        menu = QMenu(self)
        new_folder_action = menu.addAction("新建文件夹")
        new_event_action = menu.addAction("新建事件")
        import_action = menu.addAction("批量导入音频为事件...")
        menu.addSeparator()
        bulk_bus_action = menu.addAction("批量改事件总线...")
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        copy_id_action = menu.addAction("复制对象标识")
        property_action = menu.addAction("打开属性编辑器")
        preview_action = menu.addAction("试听事件")
        contents_action = menu.addAction("打开内容编辑器")
        report_action = menu.addAction("打开问题中心")
        preview_action.setEnabled(False)
        contents_action.setEnabled(False)
        bulk_bus_action.setEnabled(bool(selected_event_ids))
        if item is not None:
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if payload is not None and payload[0] == "event":
                preview_action.setEnabled(True)
                contents_action.setEnabled(True)
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
            if payload is not None and payload[0] == "event":
                self.set_active_property_category("事件")
            else:
                self.set_active_property_category("工程")
        elif action == preview_action:
            self.previewRequested.emit()
        elif action == contents_action:
            self.set_active_contents_category("片段")
        elif action == report_action:
            self.show_report_tab(1)

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
            (self.open_loudness_view_button, load_app_icon("audio")),
            (self.project_bus_add_button, load_app_icon("bus")),
            (self.project_bus_remove_button, load_app_icon("delete")),
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
        ]
        for button, icon in icon_pairs:
            if not icon.isNull():
                button.setIcon(icon)
        self.tree_search_button.setIcon(load_app_icon("open_project"))
        self.tree_search_button.setToolTip("定位下一个匹配的事件")
        self.global_search_button.setIcon(load_app_icon("open_project"))
        self.global_search_button.setToolTip("搜索并定位事件")
        self.object_parent_button.setIcon(load_app_icon("navigate_parent"))
        self.object_parent_button.setToolTip("跳转到父级")
        self.object_parent_button.setAutoRaise(True)
        self.reference_parent_value_button.setIcon(load_app_icon("navigate_parent"))
        self.reference_bus_value_button.setIcon(load_app_icon("bus"))
        self.reference_assets_value_button.setIcon(load_app_icon("content"))
        self.reference_generation_value_button.setIcon(load_app_icon("generate"))
        self.property_tabs.setTabIcon(0, load_app_icon("event"))
        self.property_tabs.setTabIcon(1, load_app_icon("audio"))
        self.property_tabs.setTabIcon(2, load_app_icon("generate"))
        self.property_tabs.setTabIcon(3, load_app_icon("bus"))
        self.report_tabs.setTabIcon(0, load_app_icon("report"))
        self.report_tabs.setTabIcon(1, load_app_icon("validate"))
        self.report_tabs.setTabIcon(2, load_app_icon("generate"))
        self.report_tabs.setTabIcon(3, load_app_icon("audio"))
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
            "validation": load_app_icon("validate"),
            "build": load_app_icon("generate"),
            "results": load_app_icon("report"),
            "validation-results": load_app_icon("validate"),
            "build-results": load_app_icon("generate"),
            "loudness-results": load_app_icon("audio"),
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
            QGroupBox[title="总线工作区"] QLabel {{
                color: #b9c7d6;
            }}
            QGroupBox[title="当前输出总线"] QLabel {{
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
        self.activity_hint_label.setProperty("role", "modeCardDescription")