from __future__ import annotations

import json
import re
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from audioforge.app.models.audio_project import AudioProject, BusConfig, ClipModel, EventModel, FolderModel, MASTER_BUS_NAME, new_id
from audioforge.app.services.audio_meter_service import AudioMeterService
from audioforge.app.services.command_history import CommandHistory, EditorSnapshot
from audioforge.app.services.exporter import ExportPlan, ExportRequest, RuntimeExporter
from audioforge.app.services.playback_service import PlaybackService
from audioforge.app.services.preview_audio_renderer import PreviewAudioRenderer
from audioforge.app.services.preview_bus_mixer import MASTER_BUS_NAME, PreviewBusMixer
from audioforge.app.services.preview_service import PreviewService
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.services.recovery_service import RecoveryService
from audioforge.app.services.validator import ProjectValidator
from audioforge.app.utils.constants import (
    DEFAULT_EXPORT_ROOT,
    MAX_CLIP_TIME_MS,
    MAX_CLIP_WEIGHT,
    MIN_CLIP_TIME_MS,
    MIN_CLIP_WEIGHT,
    PROJECT_EXTENSION,
    SUPPORTED_AUDIO_EXTENSIONS,
)
from audioforge.app.views.main_window import MainWindow


LOUDNESS_SCAN_THRESHOLDS = {
    "integrated_max_lufs": -16.0,
    "momentary_max_lufs": -10.0,
    "true_peak_max_dbtp": -1.0,
}


class MainController:
    def __init__(self) -> None:
        self.application = QApplication.instance() or QApplication([])
        self.window = MainWindow()
        self.window.set_close_handler(self._handle_close_request)
        self.serializer = ProjectSerializer()
        self.recovery_service = RecoveryService()
        self.validator = ProjectValidator()
        self.exporter = RuntimeExporter()
        self.preview_service = PreviewService(seed=7)
        self.preview_audio_renderer = PreviewAudioRenderer()
        self.preview_bus_mixer = PreviewBusMixer()
        self.playback_service = PlaybackService()
        self.audio_meter_service = AudioMeterService()
        self.history = CommandHistory()
        self.settings = QSettings("AudioForge", "Workbench")
        self.project = self._create_default_project()
        self.selected_event_id: str | None = None
        self.selected_event_ids: list[str] = []
        self.selected_folder_id: str | None = None
        self.is_dirty = False
        self._analysis_status: dict[str, dict[str, str]] = {}
        self._bind_events()
        self._restore_window_preferences()
        self.application.aboutToQuit.connect(self._save_window_preferences)
        self._sync_recent_projects_ui()
        self._refresh_ui()
        self._restore_recovery_snapshot_if_available()

    def _create_default_project(self) -> AudioProject:
        project = AudioProject.create_empty()
        root_folder_id = project.root_folder_ids[0]
        demo_event = self._make_casual_event_template(
            "UI_Click_Normal",
            display_name="按钮点击",
            default_bus=project.settings.default_bus,
            available_buses=project.settings.buses,
            suggested_bus="UI",
        )
        demo_event.clips.append(
            ClipModel(
                id="ui_click_01",
                source_path="",
                export_path="ui/click_01",
                asset_key="ui/click_01",
            )
        )
        project.add_event(root_folder_id, demo_event)
        return project

    def _make_casual_event_template(
        self,
        event_id: str,
        display_name: str = "",
        *,
        default_bus: str | None = None,
        available_buses: list[str] | None = None,
        suggested_bus: str | None = None,
    ) -> EventModel:
        buses = list(available_buses or self.project.settings.buses)
        fallback_bus = default_bus or (buses[0] if buses else "SFX")
        resolved_bus = self._suggest_bus_for_event_name(display_name or event_id, fallback_bus, buses)
        if suggested_bus in buses:
            resolved_bus = str(suggested_bus)
        event = EventModel(
            id=event_id,
            display_name=display_name or event_id.replace("_", " "),
            bus=resolved_bus,
            play_mode="Random",
            avoid_immediate_repeat=False,
            max_instances=0,
            cooldown_seconds=0.0,
            steal_policy="RejectNew",
            combo_pitch_step_cents=100,
            combo_reset_seconds=1.5,
            combo_max_step=0,
            load_policy="OnDemand",
        )
        return event

    def _suggest_bus_for_event_name(self, raw_name: str, default_bus: str, available_buses: list[str]) -> str:
        if not available_buses:
            return default_bus
        bus_lookup = {bus.casefold(): bus for bus in available_buses}
        tokens = {token for token in re.split(r"[^a-z0-9]+", raw_name.casefold()) if token}
        if bus_lookup.get("ui") and tokens & {"ui", "button", "click", "tap", "popup", "panel"}:
            return bus_lookup["ui"]
        if bus_lookup.get("bgm") and tokens & {"bgm", "music", "theme", "loop", "ambient"}:
            return bus_lookup["bgm"]
        return bus_lookup.get(default_bus.casefold(), available_buses[0])

    def _bind_events(self) -> None:
        self.window.new_project_button.clicked.connect(self.new_project)
        self.window.open_project_button.clicked.connect(self.open_project)
        self.window.save_project_button.clicked.connect(self.save_project)
        self.window.saveProjectAsRequested.connect(self.save_project_as)
        self.window.validate_button.clicked.connect(self.validate_project)
        self.window.buildRequested.connect(self.build_project)
        self.window.tree.nodeSelected.connect(self.select_node)
        self.window.tree.nodesSelectionChanged.connect(self.select_nodes)
        self.window.tree.nodeMoved.connect(self.handle_tree_move)
        self.window.tree.audioFilesDropped.connect(self.import_audio_files_as_events)
        self.window.eventPropertiesChanged.connect(self.update_current_event_from_form)
        self.window.projectSettingsChanged.connect(self.update_project_settings_from_form)
        self.window.previewBusSelectionChanged.connect(self.sync_preview_bus_editor)
        self.window.previewBusStateChanged.connect(self.update_preview_bus_state_from_form)
        self.window.stopPreviewEventRequested.connect(self.stop_current_event_preview)
        self.window.stopPreviewBusRequested.connect(self.stop_current_bus_preview)
        self.window.createFolderRequested.connect(self.create_folder)
        self.window.createEventRequested.connect(self.create_event)
        self.window.renameSelectedRequested.connect(self.rename_selected)
        self.window.deleteSelectedRequested.connect(self.delete_selected)
        self.window.undoRequested.connect(self.undo)
        self.window.redoRequested.connect(self.redo)
        self.window.previewRequested.connect(self.preview_current_event)
        self.window.previewClipRequested.connect(self.preview_selected_clip)
        self.window.previewClipSegmentRequested.connect(self.preview_selected_clip_segment)
        self.window.importClipsRequested.connect(self.import_clips)
        self.window.importAudioAsEventsRequested.connect(self.import_audio_files_as_events)
        self.window.removeClipsRequested.connect(self.remove_selected_clips)
        self.window.bulkWeightRequested.connect(self.apply_bulk_weight)
        self.window.batchRenameRequested.connect(self.batch_rename_clips)
        self.window.bulkClipPropertiesRequested.connect(self.apply_bulk_clip_properties)
        self.window.sortClipsRequested.connect(self.sort_current_event_clips)
        self.window.reorderClipsRequested.connect(self.reorder_current_event_clips)
        self.window.previewExportDiffRequested.connect(self.preview_export_diff)
        self.window.openRecentProjectRequested.connect(self.open_recent_project)
        self.window.navigateParentRequested.connect(self.navigate_to_parent)
        self.window.applyDefaultBusToAllRequested.connect(self.apply_default_bus_to_all_events)
        self.window.bulkEventBusRequested.connect(self.apply_bus_to_selected_events)
        self.window.clipEdited.connect(self.update_clip_field)
        self.window.loudnessScanRequested.connect(self.scan_project_loudness)
        self.window.reportTargetRequested.connect(self.navigate_to_report_target)

    def _refresh_ui(self) -> None:
        navigation_state = self.window.navigation_state()
        self.selected_event_ids = [event_id for event_id in self.selected_event_ids if event_id in self.project.events]
        if self.selected_event_id not in self.project.events:
            self.selected_event_id = self.selected_event_ids[0] if self.selected_event_ids else next(iter(self.project.events), None)
        if self.selected_event_id is not None and self.selected_event_id not in self.selected_event_ids:
            self.selected_event_ids = [self.selected_event_id, *self.selected_event_ids]
        if self.selected_folder_id not in self.project.folders:
            self.selected_folder_id = next(iter(self.project.root_folder_ids), None)
        self.window.tree.rebuild(self.project)
        self.window.tree.set_analysis_status(self._analysis_status)
        if self.selected_event_ids:
            self.window.tree.select_nodes(
                [("event", event_id) for event_id in self.selected_event_ids],
                current_node=("event", self.selected_event_id) if self.selected_event_id is not None else None,
            )
        elif self.selected_event_id is not None:
            self.window.tree.select_node("event", self.selected_event_id)
        elif self.selected_folder_id is not None:
            self.window.tree.select_node("folder", self.selected_folder_id)
        self.window.set_project_settings(self.project.settings)
        self._sync_preview_bus_mixer()
        self.sync_preview_bus_editor()
        self.window.set_event_details(self.current_event)
        self.window.set_project_title(self.project.name, self.project.file_path)
        self.window.set_history_actions_enabled(self.history.can_undo(), self.history.can_redo())
        self.window.set_dirty_state(self.is_dirty)
        self._update_object_context()
        self._sync_build_selection_context()
        self.window.apply_navigation_state(navigation_state)

    @property
    def current_event(self) -> EventModel | None:
        if self.selected_event_id is None:
            return None
        return self.project.events.get(self.selected_event_id)

    @property
    def current_events(self) -> list[EventModel]:
        return [self.project.events[event_id] for event_id in self.selected_event_ids if event_id in self.project.events]

    def show(self) -> None:
        self.window.show()

    def run(self) -> int:
        return self.application.exec()

    def new_project(self) -> None:
        if not self._confirm_abandon_unsaved_changes():
            return
        self.project = AudioProject.create_empty()
        self.preview_service.clear()
        self.history.clear()
        self.selected_event_id = None
        self.selected_event_ids = []
        self.selected_folder_id = self.project.root_folder_ids[0]
        self.is_dirty = False
        self._clear_recovery_snapshot()
        self.window.append_log("已新建工程。")
        self._refresh_ui()

    def open_project(self) -> None:
        if not self._confirm_abandon_unsaved_changes():
            return
        file_path = self.window.ask_open_project_path()
        if not file_path:
            return

        self._open_project_path(Path(file_path))

    def open_recent_project(self, file_path: str) -> None:
        if not file_path:
            return
        if not self._confirm_abandon_unsaved_changes():
            return
        self._open_project_path(Path(file_path))

    def _open_project_path(self, file_path: Path) -> None:
        if not file_path.exists():
            QMessageBox.warning(self.window, "打开工程失败", f"找不到工程文件：{file_path}")
            self._remove_recent_project(str(file_path))
            return

        try:
            self.project = self.serializer.load(file_path)
        except Exception as exc:
            QMessageBox.critical(self.window, "打开工程失败", str(exc))
            return

        self.preview_service.clear()
        self.history.clear()
        self.is_dirty = False
        self._clear_recovery_snapshot()
        self.selected_event_id = next(iter(self.project.events), None)
        self.selected_event_ids = [self.selected_event_id] if self.selected_event_id else []
        self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id) if self.selected_event_id else next(iter(self.project.root_folder_ids), None)
        self.window.append_log(f"已打开工程：{file_path}")
        self._remember_recent_project(str(file_path))
        self._refresh_ui()

    def save_project(self) -> bool:
        file_path = self.project.file_path
        if not file_path:
            suggested_name = f"{self.project.name}{PROJECT_EXTENSION}"
            file_path = self.window.ask_save_project_path(suggested_name)
        if not file_path:
            return False

        save_path = Path(file_path)
        if save_path.suffix != PROJECT_EXTENSION:
            save_path = save_path.with_suffix(PROJECT_EXTENSION)

        try:
            self.serializer.save(self.project, save_path)
        except Exception as exc:
            QMessageBox.critical(self.window, "保存工程失败", str(exc))
            return False

        self.is_dirty = False
        self._clear_recovery_snapshot()
        self._remember_recent_project(str(save_path))
        self.window.append_log(f"已保存工程：{save_path}")
        self._refresh_ui()
        return True

    def save_project_as(self) -> bool:
        suggested_name = f"{self.project.name}{PROJECT_EXTENSION}"
        file_path = self.window.ask_save_project_path(suggested_name)
        if not file_path:
            return False

        save_path = Path(file_path)
        if save_path.suffix != PROJECT_EXTENSION:
            save_path = save_path.with_suffix(PROJECT_EXTENSION)

        try:
            self.serializer.save(self.project, save_path)
        except Exception as exc:
            QMessageBox.critical(self.window, "另存工程失败", str(exc))
            return False

        self.is_dirty = False
        self._clear_recovery_snapshot()
        self._remember_recent_project(str(save_path))
        self.window.append_log(f"已另存工程：{save_path}")
        self._refresh_ui()
        return True

    def select_node(self, node_type: str, node_id: str) -> None:
        navigation_state = self.window.navigation_state()
        if node_type == "event":
            self.selected_event_id = node_id
            self.selected_event_ids = [node_id]
            self.selected_folder_id = self.project.find_event_folder_id(node_id)
        else:
            self.selected_folder_id = node_id
            self.selected_event_id = None
            self.selected_event_ids = []
        self.window.set_event_details(self.current_event if len(self.selected_event_ids) <= 1 else None)
        self._sync_multi_selection_affordances()
        self._update_object_context()
        self._sync_build_selection_context()
        self.window.apply_navigation_state(navigation_state)

    def select_nodes(self, nodes: list[tuple[str, str]]) -> None:
        event_ids = [node_id for node_type, node_id in nodes if node_type == "event" and node_id in self.project.events]
        if event_ids:
            self.selected_event_ids = event_ids
            current_event = self.current_event
            current_event_id = current_event.id if current_event is not None else None
            self.selected_event_id = current_event_id if current_event_id in event_ids else event_ids[0]
            self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id)
        elif nodes:
            folder_ids = [node_id for node_type, node_id in nodes if node_type == "folder" and node_id in self.project.folders]
            self.selected_event_ids = []
            self.selected_event_id = None
            if folder_ids:
                self.selected_folder_id = folder_ids[0]
        self.window.set_event_details(self.current_event if len(self.selected_event_ids) <= 1 else None)
        self._sync_multi_selection_affordances()
        self._update_object_context()
        self._sync_build_selection_context()

    def navigate_to_parent(self) -> None:
        if self.selected_event_id is not None:
            folder_id = self.project.find_event_folder_id(self.selected_event_id)
            if folder_id is None:
                return
            self.selected_folder_id = folder_id
            self.selected_event_id = None
            self.selected_event_ids = []
            self._refresh_ui()
            return

        if self.selected_folder_id is None:
            return
        parent_folder_id = self.project.find_folder_parent_id(self.selected_folder_id)
        if parent_folder_id is None:
            return
        self.selected_folder_id = parent_folder_id
        self.selected_event_id = None
        self.selected_event_ids = []
        self._refresh_ui()

    def update_current_event_from_form(self) -> None:
        event = self.current_event
        if event is None:
            return

        form_data = self.window.current_event_form_data()

        def mutate() -> bool:
            current_event = self.current_event
            if current_event is None:
                return False

            new_id_value = str(form_data["id"])
            if new_id_value and new_id_value != current_event.id:
                self.project.rename_event(current_event.id, new_id_value)
                self.selected_event_id = new_id_value
                self.selected_event_ids = [new_id_value if event_id == current_event.id else event_id for event_id in self.selected_event_ids or [current_event.id]]
                current_event = self.project.events[new_id_value]

            current_event.display_name = str(form_data["display_name"])
            current_event.bus = str(form_data["bus"])
            current_event.play_mode = str(form_data["play_mode"])
            current_event.steal_policy = str(form_data["steal_policy"])
            current_event.load_policy = str(form_data["load_policy"])
            current_event.volume_db = float(form_data["volume_db"])
            current_event.volume_rand_min_db = float(form_data["volume_rand_min_db"])
            current_event.volume_rand_max_db = float(form_data["volume_rand_max_db"])
            current_event.pitch_cents = int(form_data["pitch_cents"])
            current_event.pitch_rand_min_cents = int(form_data["pitch_rand_min_cents"])
            current_event.pitch_rand_max_cents = int(form_data["pitch_rand_max_cents"])
            current_event.cooldown_seconds = float(form_data["cooldown_seconds"])
            current_event.max_instances = int(form_data["max_instances"])
            current_event.combo_pitch_step_cents = int(form_data["combo_pitch_step_cents"])
            current_event.combo_reset_seconds = float(form_data["combo_reset_seconds"])
            current_event.combo_max_step = int(form_data["combo_max_step"])
            current_event.avoid_immediate_repeat = bool(form_data["avoid_immediate_repeat"])
            event_tags = [str(tag) for tag in form_data["tags"]]
            for clip in current_event.clips:
                clip.tags = list(event_tags)
            current_event.notes = str(form_data["notes"])
            self.project.touch()
            return True

        try:
            changed = self._apply_mutation(
                "Update Event Properties",
                mutate,
                merge_key=f"event-properties:{self.selected_event_id}",
            )
        except ValueError as exc:
            QMessageBox.warning(self.window, "更新事件失败", str(exc))
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(event)
            self.window.apply_navigation_state(navigation_state)
            return

        if changed:
            self.window.append_log("已更新事件属性。")
            navigation_state = self.window.navigation_state()
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def update_project_settings_from_form(self) -> None:
        form_data = self.window.current_project_settings_form_data()
        source_audio_format = str(form_data["source_audio_format"])
        runtime_audio_format = str(form_data["runtime_audio_format"])
        buses = [str(bus) for bus in form_data["buses"]]
        rename_map = {
            str(bus_config["original_name"]): str(bus_config["name"])
            for bus_config in form_data["bus_configs"]
            if str(bus_config["original_name"]).strip() and str(bus_config["original_name"]) != str(bus_config["name"])
        }
        bus_configs = [
            BusConfig(
                name=str(bus_config["name"]),
                parent_bus=str(bus_config.get("parent_bus", MASTER_BUS_NAME) or MASTER_BUS_NAME),
                volume_db=float(bus_config["volume_db"]),
                is_muted=bool(bus_config["is_muted"]),
            )
            for bus_config in form_data["bus_configs"]
        ]
        default_bus = str(form_data["default_bus"])
        export_root = str(form_data["export_root"])
        if default_bus not in buses and buses:
            default_bus = buses[0]

        def mutate() -> bool:
            changed = False
            if self.project.settings.buses != buses:
                self.project.settings.buses = buses
                changed = True
            if self.project.settings.bus_configs != bus_configs:
                self.project.settings.bus_configs = bus_configs
                changed = True
            if self.project.settings.source_audio_format != source_audio_format:
                self.project.settings.source_audio_format = source_audio_format
                changed = True
            if self.project.settings.runtime_audio_format != runtime_audio_format:
                self.project.settings.runtime_audio_format = runtime_audio_format
                changed = True
            if self.project.settings.export_root != export_root:
                self.project.settings.export_root = export_root
                changed = True
            if self.project.settings.default_bus != default_bus:
                self.project.settings.default_bus = default_bus
                changed = True
            for event in self.project.events.values():
                if event.bus in rename_map:
                    event.bus = rename_map[event.bus]
                    changed = True
                if event.bus not in buses:
                    event.bus = default_bus
                    changed = True
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Update Project Settings", mutate, merge_key="project-settings"):
            self.window.append_log("已更新工程设置。")
            navigation_state = self.window.navigation_state()
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def sync_preview_bus_editor(self) -> None:
        self._sync_preview_bus_mixer()
        bus_names = self.preview_bus_mixer.editable_bus_names(self.project.settings.buses, self._project_bus_parent_map())
        selected_bus = self.window.current_preview_bus_name() or bus_names[0]
        state = self.preview_bus_mixer.get_state(selected_bus)
        effective_linear = self.preview_bus_mixer.effective_gain_linear(selected_bus)
        effective_text = f"{self.preview_bus_mixer.describe_bus(selected_bus)} | 有效输出 {effective_linear * 100:.0f}%"
        self.window.set_preview_bus_editor(
            bus_names=bus_names,
            selected_bus=selected_bus,
            volume_percent=state.volume_linear * 100.0,
            is_muted=state.is_muted,
            effective_output_text=effective_text,
        )
        self._update_object_context()

    def update_preview_bus_state_from_form(self) -> None:
        form_data = self.window.current_preview_bus_form_data()
        bus_name = str(form_data["bus_name"])
        volume_percent = float(form_data["volume_percent"])
        is_muted = bool(form_data["is_muted"])
        state = self.preview_bus_mixer.set_state(
            bus_name,
            volume_linear=volume_percent / 100.0,
            is_muted=is_muted,
        )
        self.playback_service.refresh_bus_volumes(self._resolve_effective_preview_volume_db)
        self.sync_preview_bus_editor()
        self.window.append_log(
            f"试听总线已更新：{state.name} 音量={state.volume_linear * 100:.0f}% 静音={'是' if state.is_muted else '否'}"
        )

    def apply_default_bus_to_all_events(self) -> None:
        default_bus = self.project.settings.default_bus

        def mutate() -> bool:
            changed = False
            for event in self.project.events.values():
                if event.bus != default_bus:
                    event.bus = default_bus
                    changed = True
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Apply Default Bus To All Events", mutate):
            self.window.append_log(f"已将默认总线“{default_bus}”应用到所有事件。")
            self.window.set_active_property_category("事件")
            self._refresh_ui()

    def create_folder(self) -> None:
        folder_name = self.window.ask_new_folder_name()
        if not folder_name:
            return
        parent_folder_id = self._resolve_target_folder_for_creation()
        folder = FolderModel(id=new_id("folder"), name=folder_name)

        def mutate() -> bool:
            self.project.add_folder(parent_folder_id, folder)
            self.selected_folder_id = folder.id
            self.selected_event_id = None
            self.selected_event_ids = []
            return True

        if self._apply_mutation("Create Folder", mutate):
            parent_name = self.project.folders[parent_folder_id].name if parent_folder_id in self.project.folders else self.project.name
            self.window.append_log(f"已创建文件夹：{folder.name}（父级：{parent_name}）。")
            self.window.set_active_property_category("工程")
            self._refresh_ui()

    def create_event(self) -> None:
        folder_id = self._resolve_target_folder_for_creation()
        event_id = self.window.ask_new_event_id() or self._make_unique_event_id("New_Event")
        if event_id in self.project.events:
            QMessageBox.warning(self.window, "新建事件失败", f"事件 ID 已存在：{event_id}")
            return
        event = self._make_casual_event_template(
            event_id,
            default_bus=self.project.settings.default_bus,
            available_buses=self.project.settings.buses,
        )

        def mutate() -> bool:
            self.project.add_event(folder_id, event)
            self.selected_event_id = event.id
            self.selected_event_ids = [event.id]
            self.selected_folder_id = folder_id
            return True

        if self._apply_mutation("Create Event", mutate):
            folder_name = self.project.folders[folder_id].name if folder_id in self.project.folders else self.project.name
            self.window.append_log(f"已创建事件：{event.id}（目录：{folder_name}，总线：{event.bus}）。")
            self.window.set_active_property_category("事件")
            self._refresh_ui()

    def rename_selected(self) -> None:
        if len(self.selected_event_ids) > 1:
            result = self.window.ask_batch_event_rename()
            if result is None:
                return
            self.batch_rename_events(result[0], result[1])
            return

        if self.selected_event_id is not None:
            current_id = self.selected_event_id
            new_id = self.window.ask_rename_value("Rename Event", "Event ID", current_id)
            if not new_id or new_id == current_id:
                return

            def mutate() -> bool:
                self.project.rename_event(current_id, new_id)
                self.selected_event_id = new_id
                self.selected_event_ids = [new_id if event_id == current_id else event_id for event_id in self.selected_event_ids or [current_id]]
                self.selected_folder_id = self.project.find_event_folder_id(new_id)
                return True

            try:
                changed = self._apply_mutation("Rename Event", mutate)
            except ValueError as exc:
                QMessageBox.warning(self.window, "重命名事件失败", str(exc))
                return
            if changed:
                self.window.append_log(f"已重命名事件：{current_id} -> {new_id}")
                self.window.set_active_property_category("事件")
                self._refresh_ui()
            return

        if self.selected_folder_id is not None:
            folder = self.project.folders[self.selected_folder_id]
            new_name = self.window.ask_rename_value("重命名文件夹", "文件夹名称", folder.name)
            if not new_name or new_name == folder.name:
                return

            def mutate() -> bool:
                self.project.rename_folder(folder.id, new_name)
                return True

            if self._apply_mutation("Rename Folder", mutate):
                self.window.append_log(f"已重命名文件夹：{folder.name} -> {new_name}")
                self.window.set_active_property_category("工程")
                self._refresh_ui()

    def delete_selected(self) -> None:
        if len(self.selected_event_ids) > 1:
            label = f"确认删除所选 {len(self.selected_event_ids)} 个事件？"
            if not self.window.confirm_delete(label):
                return
            self.delete_events(self.selected_event_ids)
            return

        if self.selected_event_id is not None:
            label = f"确认删除事件“{self.selected_event_id}”？"
            if not self.window.confirm_delete(label):
                return
            removed_event_id = self.selected_event_id

            def mutate() -> bool:
                self.project.remove_event(removed_event_id)
                self.selected_event_id = None
                self.selected_event_ids = []
                return True

            if self._apply_mutation("Delete Event", mutate):
                self.window.append_log(f"已删除事件：{removed_event_id}")
                self._refresh_ui()
            return

        if self.selected_folder_id is not None:
            label = f"确认删除文件夹“{self.project.folders[self.selected_folder_id].name}”及其全部子项？"
            if not self.window.confirm_delete(label):
                return
            removed_folder_id = self.selected_folder_id

            def mutate() -> bool:
                self.project.remove_folder(removed_folder_id)
                self.selected_folder_id = next(iter(self.project.root_folder_ids), None)
                self.selected_event_id = None
                self.selected_event_ids = []
                return True

            if self._apply_mutation("Delete Folder", mutate):
                self.window.append_log(f"已删除文件夹：{removed_folder_id}")
                self._refresh_ui()

    def import_clips(self, file_paths: list[str]) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "导入音频", "请先选择一个事件，再导入音频片段。")
            return

        supported_paths, skipped_unsupported, skipped_missing = self._classify_import_file_paths(file_paths)
        imported_clips = []
        for source_path in supported_paths:
            imported_clips.append(self._build_clip_from_path(source_path))

        if not imported_clips:
            self._notify_import_skip("导入片段", skipped_unsupported, skipped_missing)
            return

        def mutate() -> bool:
            for clip in imported_clips:
                self.project.add_clip_to_event(event.id, clip)
            return True

        if self._apply_mutation("Import Clips", mutate):
            skipped_suffix = self._format_import_skip_suffix(skipped_unsupported, skipped_missing)
            self.window.append_log(f"已向 {event.id} 导入 {len(imported_clips)} 个片段。{skipped_suffix}")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def import_audio_files_as_events(self, file_paths: list[str], target_folder_id=None, template: dict[str, object] | None = None) -> None:
        supported_paths, skipped_unsupported, skipped_missing = self._classify_import_file_paths(file_paths)
        imported_events: list[EventModel] = []
        reserved_event_ids = set(self.project.events.keys())
        for source_path in supported_paths:
            event = self._build_event_from_audio_path(source_path, reserved_event_ids)
            self._apply_event_import_template(event, template)
            reserved_event_ids.add(event.id)
            imported_events.append(event)

        if not imported_events:
            self._notify_import_skip("导入音频为事件", skipped_unsupported, skipped_missing)
            return

        folder_id = target_folder_id if target_folder_id in self.project.folders else self._resolve_target_folder_for_creation()
        last_event_id = imported_events[-1].id

        def mutate() -> bool:
            for event in imported_events:
                self.project.add_event(folder_id, event)
            self.selected_folder_id = folder_id
            self.selected_event_id = last_event_id
            self.selected_event_ids = [last_event_id] if last_event_id is not None else []
            return True

        if self._apply_mutation("Import Audio As Events", mutate):
            template_suffix = self._describe_event_import_template(template)
            folder_name = self.project.folders[folder_id].name if folder_id in self.project.folders else self.project.name
            skipped_suffix = self._format_import_skip_suffix(skipped_unsupported, skipped_missing)
            self.window.append_log(
                f"已导入 {len(imported_events)} 个音频并创建事件；目标目录：{folder_name}；当前事件：{last_event_id}.{template_suffix}{skipped_suffix}"
            )
            self.window.set_active_property_category("事件")
            self._refresh_ui()

    def remove_selected_clips(self, clip_ids: list[str]) -> None:
        event = self.current_event
        if event is None or not clip_ids:
            return

        def mutate() -> bool:
            for clip_id in clip_ids:
                self.project.remove_clip_from_event(event.id, clip_id)
            return True

        if self._apply_mutation("Remove Clips", mutate):
            self.window.append_log(f"已从 {event.id} 移除 {len(clip_ids)} 个片段。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def apply_bulk_weight(self, weight: int) -> None:
        event = self.current_event
        if event is None:
            return
        clip_ids = self.window.selected_clip_ids()
        if not clip_ids:
            return

        normalized_weight = min(MAX_CLIP_WEIGHT, max(MIN_CLIP_WEIGHT, int(weight)))

        def mutate() -> bool:
            changed = False
            for clip in event.clips:
                if clip.id in clip_ids and clip.weight != normalized_weight:
                    clip.weight = normalized_weight
                    changed = True
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Bulk Set Clip Weight", mutate):
            self.window.append_log(f"已将 {len(clip_ids)} 个片段的权重设置为 {normalized_weight}。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def apply_bulk_clip_properties(self, payload: dict[str, object]) -> None:
        event = self.current_event
        if event is None:
            return
        clip_ids = self.window.selected_clip_ids()
        if not clip_ids:
            return

        weight = min(MAX_CLIP_WEIGHT, max(MIN_CLIP_WEIGHT, int(payload.get("weight", 1))))
        asset_prefix = str(payload.get("asset_prefix", "")).strip().strip("/")
        tags = [str(tag) for tag in payload.get("tags", [])]

        def mutate() -> bool:
            changed = False
            for clip in event.clips:
                if clip.id not in clip_ids:
                    continue
                if clip.weight != weight:
                    clip.weight = weight
                    changed = True
                if asset_prefix:
                    new_asset_key = f"{asset_prefix}/{clip.id}".replace("\\", "/")
                    if clip.asset_key != new_asset_key:
                        clip.asset_key = new_asset_key
                        clip.export_path = new_asset_key
                        changed = True
                if clip.tags != tags:
                    clip.tags = list(tags)
                    changed = True
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Bulk Edit Clips", mutate):
            self.window.append_log(f"已批量更新 {len(clip_ids)} 个片段的属性。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def batch_rename_clips(self, base_name: str, start_index: int) -> None:
        event = self.current_event
        if event is None:
            return
        clip_ids = self.window.selected_clip_ids()
        if not clip_ids:
            return

        def mutate() -> bool:
            selected = [clip for clip in event.clips if clip.id in clip_ids]
            if not selected:
                return False
            index = start_index
            used_ids = {clip.id for clip in event.clips if clip.id not in clip_ids}
            for clip in selected:
                new_clip_id = f"{base_name}_{index:02d}"
                while new_clip_id in used_ids:
                    index += 1
                    new_clip_id = f"{base_name}_{index:02d}"
                clip.id = new_clip_id
                clip.asset_key = new_clip_id
                clip.export_path = new_clip_id
                used_ids.add(new_clip_id)
                index += 1
            self.project.touch()
            return True

        if self._apply_mutation("Batch Rename Clips", mutate):
            self.window.append_log(f"已按基础名“{base_name}”重命名 {len(clip_ids)} 个片段。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def update_clip_field(self, clip_id: str, field_name: str, raw_value: str) -> None:
        event = self.current_event
        if event is None:
            return

        def mutate() -> bool:
            clip = next((item for item in event.clips if item.id == clip_id), None)
            if clip is None:
                return False
            if field_name == "weight":
                try:
                    new_value = min(MAX_CLIP_WEIGHT, max(MIN_CLIP_WEIGHT, int(raw_value)))
                except ValueError:
                    return False
            elif field_name in {"trim_start_ms", "trim_end_ms", "fade_in_ms", "fade_out_ms", "loop_start_ms", "loop_end_ms"}:
                try:
                    new_value = min(MAX_CLIP_TIME_MS, max(MIN_CLIP_TIME_MS, int(raw_value)))
                except ValueError:
                    return False
            elif field_name == "tags":
                new_value = [item.strip() for item in raw_value.split(",") if item.strip()]
            else:
                new_value = raw_value.strip()
            if getattr(clip, field_name) == new_value:
                return False
            setattr(clip, field_name, new_value)
            if field_name == "asset_key":
                clip.export_path = new_value
            self.project.touch()
            return True

        merge_key = f"clip-edit:{self.selected_event_id}:{clip_id}:{field_name}"
        if self._apply_mutation("Edit Clip Field", mutate, merge_key=merge_key):
            self.window.append_log(f"已更新片段 {clip_id} 的字段：{field_name}。")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def sort_current_event_clips(self, field_name: str, ascending: bool) -> None:
        event = self.current_event
        if event is None or len(event.clips) < 2:
            return

        def mutate() -> bool:
            before = [clip.id for clip in event.clips]
            event.clips.sort(key=lambda clip: getattr(clip, field_name), reverse=not ascending)
            after = [clip.id for clip in event.clips]
            if before == after:
                return False
            self.project.touch()
            return True

        if self._apply_mutation("Sort Clips", mutate):
            order_label = "升序" if ascending else "降序"
            self.window.append_log(f"已按 {field_name} {order_label} 排序片段。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def reorder_current_event_clips(self, clip_ids: list[str]) -> None:
        event = self.current_event
        if event is None or not clip_ids:
            return

        def mutate() -> bool:
            clip_map = {clip.id: clip for clip in event.clips}
            if set(clip_ids) != set(clip_map):
                return False
            if [clip.id for clip in event.clips] == clip_ids:
                return False
            event.clips = [clip_map[clip_id] for clip_id in clip_ids]
            self.project.touch()
            return True

        if self._apply_mutation("Reorder Clips", mutate):
            self.window.append_log("已按拖拽结果重排片段顺序。")
            self.window.set_active_contents_category("片段")
            navigation_state = self.window.navigation_state()
            self.window.set_event_details(self.project.events[event.id])
            self.window.apply_navigation_state(navigation_state)

    def apply_bus_to_selected_events(self, bus_name: str) -> None:
        event_ids = [event_id for event_id in self.selected_event_ids if event_id in self.project.events]
        if not event_ids or bus_name not in self.project.settings.buses:
            return

        def mutate() -> bool:
            changed = False
            for event_id in event_ids:
                event = self.project.events[event_id]
                if event.bus == bus_name:
                    continue
                event.bus = bus_name
                changed = True
            if not changed:
                return False
            self.project.touch()
            self.selected_event_id = event_ids[0]
            self.selected_event_ids = list(event_ids)
            self.selected_folder_id = self.project.find_event_folder_id(event_ids[0])
            return True

        if self._apply_mutation("Bulk Set Event Bus", mutate):
            self.window.append_log(f"已将 {len(event_ids)} 个事件批量切换到总线：{bus_name}")
            self.window.set_active_property_category("事件")
            self._refresh_ui()

    def batch_rename_events(self, base_name: str, start_index: int) -> None:
        event_ids = [event_id for event_id in self.selected_event_ids if event_id in self.project.events]
        if not event_ids:
            return

        def mutate() -> bool:
            index = start_index
            ordered_ids = list(event_ids)
            used_ids = {event_id for event_id in self.project.events if event_id not in ordered_ids}
            renamed_ids: list[str] = []
            for event_id in ordered_ids:
                new_event_id = f"{base_name}_{index:02d}"
                while new_event_id in used_ids:
                    index += 1
                    new_event_id = f"{base_name}_{index:02d}"
                self.project.rename_event(event_id, new_event_id)
                renamed_ids.append(new_event_id)
                used_ids.add(new_event_id)
                index += 1
            self.selected_event_ids = renamed_ids
            self.selected_event_id = renamed_ids[0] if renamed_ids else None
            self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id) if self.selected_event_id else self.selected_folder_id
            return True

        try:
            changed = self._apply_mutation("Batch Rename Events", mutate)
        except ValueError as exc:
            QMessageBox.warning(self.window, "批量重命名事件失败", str(exc))
            return
        if changed:
            self.window.append_log(f"已按基础名“{base_name}”重命名 {len(event_ids)} 个事件。")
            self.window.set_active_property_category("事件")
            self._refresh_ui()

    def delete_events(self, event_ids: list[str]) -> None:
        resolved_event_ids = [event_id for event_id in event_ids if event_id in self.project.events]
        if not resolved_event_ids:
            return

        def mutate() -> bool:
            for event_id in resolved_event_ids:
                if event_id in self.project.events:
                    self.project.remove_event(event_id)
            self.selected_event_ids = []
            self.selected_event_id = next(iter(self.project.events), None)
            self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id) if self.selected_event_id else next(iter(self.project.root_folder_ids), None)
            return True

        if self._apply_mutation("Delete Events", mutate):
            self.window.append_log(f"已删除 {len(resolved_event_ids)} 个事件。")
            self._refresh_ui()

    def handle_tree_move(self, node_type: str, node_id: str, parent_folder_id: object, index: int) -> None:
        target_folder_id = parent_folder_id if isinstance(parent_folder_id, str) else None

        def mutate() -> bool:
            if node_type == "event":
                if target_folder_id is None:
                    return False
                self.project.move_event(node_id, target_folder_id, index)
                self.selected_event_id = node_id
                self.selected_event_ids = [node_id]
                self.selected_folder_id = target_folder_id
                return True
            try:
                self.project.move_folder(node_id, target_folder_id, index)
            except ValueError:
                return False
            self.selected_folder_id = node_id
            self.selected_event_id = None
            self.selected_event_ids = []
            return True

        if self._apply_mutation("Move Tree Node", mutate):
            self.window.append_log(f"已移动{node_type}：{node_id}")
            self._refresh_ui()
        else:
            self._refresh_ui()

    def undo(self) -> None:
        snapshot = self.history.undo()
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)
        self.window.append_log("已执行撤销。")
        self._refresh_ui()

    def redo(self) -> None:
        snapshot = self.history.redo()
        if snapshot is None:
            return
        self._restore_snapshot(snapshot)
        self.window.append_log("已执行重做。")
        self._refresh_ui()

    def preview_current_event(self) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "试听事件", "请先选择一个事件，再执行试听。")
            return
        result = self.preview_service.preview_event(
            event,
            preview_duration_resolver=self._resolve_preview_duration_seconds,
        )
        if not result.accepted:
            self.window.clear_preview_audio_metrics(result.reason)
            self.window.append_log(f"试听被拒绝：{event.id}，原因：{result.reason}")
            return
        clip = next((item for item in event.clips if item.id == result.clip_id), None)
        playback_message = "Simulated only"
        if clip is not None and clip.source_path:
            if result.stolen_oldest:
                self.playback_service.stop_oldest(event.id)
            effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, result.volume_db)
            preview_preserve_timing_pitch_cents = result.pitch_cents + result.combo_pitch_cents
            playback_message = self.playback_service.play_file(
                clip.source_path,
                effective_volume_db,
                tracked_base_volume_db=result.volume_db,
                bus_name=event.bus,
                event_id=event.id,
                pitch_cents=0,
                preserve_timing_pitch_cents=preview_preserve_timing_pitch_cents,
                trim_start_ms=clip.trim_start_ms,
                trim_end_ms=clip.trim_end_ms,
                fade_in_ms=clip.fade_in_ms,
                fade_out_ms=clip.fade_out_ms,
            )
            self.window.set_preview_audio_metrics(
                self.audio_meter_service.analyze_file(
                    clip.source_path,
                    effective_volume_db,
                    pitch_cents=0,
                    preserve_timing_pitch_cents=preview_preserve_timing_pitch_cents,
                    trim_start_ms=clip.trim_start_ms,
                    trim_end_ms=clip.trim_end_ms,
                    fade_in_ms=clip.fade_in_ms,
                    fade_out_ms=clip.fade_out_ms,
                ),
                clip_id=result.clip_id or "-",
                asset_key=result.asset_key or "-",
            )
        else:
            self.window.clear_preview_audio_metrics("当前试听片段没有可分析的源文件。")
        self.window.append_log(
            f"试听 {event.id}：片段={result.clip_id} 资源={result.asset_key} 事件音量={result.volume_db:.2f}dB 总线后={self._resolve_effective_preview_volume_db(event.bus, result.volume_db):.2f}dB 基础音高={result.pitch_cents} 连击加成={result.combo_pitch_cents} 连击={result.combo_step} 活动实例={result.active_instances} 时长={result.playback_duration_seconds:.2f}s 播放={playback_message}"
        )

    def preview_selected_clip(self, clip_id: str) -> None:
        event = self.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self.window.append_log(f"试听片段被拒绝：{clip_id} 没有源文件。")
            return
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, event.volume_db)
        playback_message = self.playback_service.play_file(
            clip.source_path,
            effective_volume_db,
            tracked_base_volume_db=event.volume_db,
            bus_name=event.bus,
            event_id=event.id,
            pitch_cents=0,
            preserve_timing_pitch_cents=event.pitch_cents,
            trim_start_ms=clip.trim_start_ms,
            trim_end_ms=clip.trim_end_ms,
            fade_in_ms=clip.fade_in_ms,
            fade_out_ms=clip.fade_out_ms,
        )
        self.window.set_preview_audio_metrics(
            self.audio_meter_service.analyze_file(
                clip.source_path,
                effective_volume_db,
                pitch_cents=0,
                preserve_timing_pitch_cents=event.pitch_cents,
                trim_start_ms=clip.trim_start_ms,
                trim_end_ms=clip.trim_end_ms,
                fade_in_ms=clip.fade_in_ms,
                fade_out_ms=clip.fade_out_ms,
            ),
            clip_id=clip.id,
            asset_key=clip.asset_key,
        )
        self.window.append_log(
            f"试听片段 {clip.id}：资源={clip.asset_key} 事件={event.id} 总线后={effective_volume_db:.2f}dB 播放={playback_message}"
        )

    def preview_selected_clip_segment(self, clip_id: str, start_ms: int, end_ms: int) -> None:
        event = self.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self.window.append_log(f"局部试听被拒绝：{clip_id} 没有源文件。")
            return
        segment_start_ms = max(MIN_CLIP_TIME_MS, int(start_ms))
        segment_end_ms = max(segment_start_ms + 1, int(end_ms))
        segment_length_ms = max(1, segment_end_ms - segment_start_ms)
        segment_fade_ms = min(40, max(8, segment_length_ms // 12))
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, event.volume_db)
        playback_message = self.playback_service.play_file(
            clip.source_path,
            effective_volume_db,
            tracked_base_volume_db=event.volume_db,
            bus_name=event.bus,
            event_id=event.id,
            pitch_cents=0,
            preserve_timing_pitch_cents=event.pitch_cents,
            trim_start_ms=segment_start_ms,
            trim_end_ms=segment_end_ms,
            fade_in_ms=segment_fade_ms,
            fade_out_ms=segment_fade_ms,
        )
        self.window.set_preview_audio_metrics(
            self.audio_meter_service.analyze_file(
                clip.source_path,
                effective_volume_db,
                pitch_cents=0,
                preserve_timing_pitch_cents=event.pitch_cents,
                trim_start_ms=segment_start_ms,
                trim_end_ms=segment_end_ms,
                fade_in_ms=segment_fade_ms,
                fade_out_ms=segment_fade_ms,
            ),
            clip_id=clip.id,
            asset_key=clip.asset_key,
        )
        self.window.append_log(
            f"局部试听片段 {clip.id}：资源={clip.asset_key} 区间={segment_start_ms}-{segment_end_ms} ms 总线后={effective_volume_db:.2f}dB 播放={playback_message}"
        )

    def stop_current_event_preview(self) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "停止事件试听", "请先选择一个事件。")
            return
        self.playback_service.stop_event(event.id)
        self.preview_service.stop_event(event.id)
        self.window.append_log(f"已停止事件试听：{event.id}")

    def stop_current_bus_preview(self) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "停止总线试听", "请先选择一个事件，以确定要停止的总线。")
            return
        affected_bus_names = {
            bus_name
            for bus_name in self.project.settings.buses
            if self._bus_routes_through(bus_name, event.bus)
        }
        affected_bus_names.add(event.bus)
        bus_event_ids = [item.id for item in self.project.events.values() if item.bus in affected_bus_names]
        self.playback_service.stop_buses(affected_bus_names)
        self.preview_service.stop_events(bus_event_ids)
        self.window.append_log(
            f"已停止总线试听：{event.bus}（覆盖总线 {len(affected_bus_names)} 个，事件 {len(bus_event_ids)} 个）"
        )

    def _bus_routes_through(self, bus_name: str, target_bus_name: str) -> bool:
        config_map = self._project_bus_config_map()
        current_name = bus_name
        normalized_target = str(target_bus_name).strip() or MASTER_BUS_NAME
        visited: set[str] = set()
        while current_name:
            normalized_current = str(current_name).strip() or MASTER_BUS_NAME
            if normalized_current == normalized_target:
                return True
            if normalized_current == MASTER_BUS_NAME or normalized_current in visited:
                return False
            visited.add(normalized_current)
            config = config_map.get(normalized_current)
            if config is None:
                return False
            current_name = str(config.parent_bus).strip() or MASTER_BUS_NAME
        return False

    def _resolve_preview_duration_seconds(
        self,
        clip: ClipModel,
        pitch_cents: int,
        combo_pitch_cents: int,
    ) -> float | None:
        if not clip.source_path:
            return None
        return self.preview_audio_renderer.estimate_duration_seconds(
            clip.source_path,
            trim_start_ms=clip.trim_start_ms,
            trim_end_ms=clip.trim_end_ms,
            pitch_cents=0,
            preserve_timing_pitch_cents=pitch_cents + combo_pitch_cents,
        )

    def _sync_preview_bus_mixer(self) -> None:
        self.preview_bus_mixer.sync_buses(self.project.settings.buses, self._project_bus_parent_map())

    def _project_bus_parent_map(self) -> dict[str, str]:
        return {config.name: config.parent_bus for config in self.project.settings.bus_configs}

    def _project_bus_config_map(self) -> dict[str, BusConfig]:
        return {config.name: config for config in self.project.settings.bus_configs}

    def _resolve_authored_bus_gain_db(self, bus_name: str) -> float:
        config_map = self._project_bus_config_map()
        current_name = bus_name
        gain_db = 0.0
        visited: set[str] = set()
        while current_name in config_map:
            config = config_map[current_name]
            if config.is_muted:
                return -96.0
            gain_db += config.volume_db
            if current_name == MASTER_BUS_NAME:
                return gain_db
            parent_name = config.parent_bus or MASTER_BUS_NAME
            if parent_name in visited:
                return -96.0
            visited.add(parent_name)
            current_name = parent_name
        return gain_db

    def _resolve_effective_preview_volume_db(self, bus_name: str, base_volume_db: float) -> float:
        authored_gain_db = self._resolve_authored_bus_gain_db(bus_name)
        if authored_gain_db <= -96.0:
            return -96.0
        return base_volume_db + authored_gain_db + self.preview_bus_mixer.effective_gain_db(bus_name)

    def scan_project_loudness(self) -> None:
        report = self._scan_project_loudness()
        self._analysis_status = report["status_map"]
        self.window.tree.set_analysis_status(self._analysis_status)
        self.window.set_loudness_report(
            self._format_loudness_report(report),
            rows=report["rows"],
            summary_text=f"响度问题中心：已分析 {report['analyzed_events']} 个事件，超标 {report['flagged_events']} 个。双击条目可跳转到事件。",
        )
        self.window.show_report_tab(3)
        self.window.append_log(f"响度扫描完成：共分析 {report['analyzed_events']} 个事件，超标 {report['flagged_events']} 个。")

    def _scan_project_loudness(self) -> dict[str, object]:
        rows: list[dict[str, object]] = []
        status_map: dict[str, dict[str, str]] = {}
        analyzed_events = 0
        flagged_events = 0
        for event_id, event in self.project.events.items():
            loudest_row = None
            for clip in event.clips:
                if not clip.source_path:
                    continue
                snapshot = self.audio_meter_service.analyze_file(clip.source_path, event.volume_db)
                if not snapshot.available or snapshot.processed is None:
                    continue
                processed = snapshot.processed
                findings: list[str] = []
                if processed.integrated_lufs > LOUDNESS_SCAN_THRESHOLDS["integrated_max_lufs"]:
                    findings.append(f"Integrated {processed.integrated_lufs:.1f} > {LOUDNESS_SCAN_THRESHOLDS['integrated_max_lufs']:.1f}")
                if processed.momentary_max_lufs > LOUDNESS_SCAN_THRESHOLDS["momentary_max_lufs"]:
                    findings.append(f"Momentary Max {processed.momentary_max_lufs:.1f} > {LOUDNESS_SCAN_THRESHOLDS['momentary_max_lufs']:.1f}")
                if processed.true_peak_db > LOUDNESS_SCAN_THRESHOLDS["true_peak_max_dbtp"]:
                    findings.append(f"True Peak {processed.true_peak_db:.1f} > {LOUDNESS_SCAN_THRESHOLDS['true_peak_max_dbtp']:.1f}")
                row = {
                    "event_id": event_id,
                    "clip_id": clip.id,
                    "asset_key": clip.asset_key,
                    "integrated_lufs": processed.integrated_lufs,
                    "momentary_max_lufs": processed.momentary_max_lufs,
                    "true_peak_db": processed.true_peak_db,
                    "findings": findings,
                }
                if loudest_row is None or processed.true_peak_db > loudest_row["true_peak_db"]:
                    loudest_row = row
            if loudest_row is None:
                continue
            analyzed_events += 1
            rows.append(loudest_row)
            if loudest_row["findings"]:
                flagged_events += 1
                status_map[event_id] = {
                    "level": "error",
                    "summary": " | ".join(loudest_row["findings"]),
                }
        rows.sort(key=lambda item: (len(item["findings"]), item["true_peak_db"], item["momentary_max_lufs"]), reverse=True)
        return {
            "thresholds": dict(LOUDNESS_SCAN_THRESHOLDS),
            "rows": rows,
            "status_map": status_map,
            "analyzed_events": analyzed_events,
            "flagged_events": flagged_events,
        }

    def _format_loudness_report(self, report: dict[str, object]) -> str:
        thresholds = report["thresholds"]
        lines = [
            "AudioForge 响度扫描",
            "",
            f"阈值: Integrated <= {thresholds['integrated_max_lufs']:.1f} LUFS | Momentary Max <= {thresholds['momentary_max_lufs']:.1f} LUFS | True Peak <= {thresholds['true_peak_max_dbtp']:.1f} dBTP",
            f"结果: 已分析 {report['analyzed_events']} 个事件，超标 {report['flagged_events']} 个。",
            "",
        ]
        rows = report["rows"]
        if not rows:
            lines.append("没有可分析的事件或片段。")
            return "\n".join(lines)
        for row in rows:
            findings = row["findings"]
            status = "超标" if findings else "通过"
            detail = "；".join(findings) if findings else "未发现超标项"
            lines.append(
                f"[{status}] 事件 {row['event_id']} | 片段 {row['clip_id']} | 资源 {row['asset_key']} | I {row['integrated_lufs']:.1f} LUFS | MMax {row['momentary_max_lufs']:.1f} LUFS | TP {row['true_peak_db']:.1f} dBTP"
            )
            lines.append(f"  说明: {detail}")
        return "\n".join(lines)

    def _resolve_target_folder_for_creation(self) -> str:
        if self.selected_folder_id in self.project.folders:
            return self.selected_folder_id
        if self.selected_event_id is not None:
            folder_id = self.project.find_event_folder_id(self.selected_event_id)
            if folder_id is not None:
                return folder_id
        return self.project.root_folder_ids[0]

    def _make_unique_event_id(self, base_id: str, reserved_event_ids: set[str] | None = None) -> str:
        blocked_ids = set(self.project.events.keys())
        if reserved_event_ids is not None:
            blocked_ids.update(reserved_event_ids)
        candidate = base_id
        index = 1
        while candidate in blocked_ids:
            index += 1
            candidate = f"{base_id}_{index}"
        return candidate

    def _build_clip_from_path(self, source_path: Path) -> ClipModel:
        existing_clip_ids = {clip.id for clip in self.current_event.clips} if self.current_event is not None else set()
        base_id = source_path.stem
        clip_id = base_id
        index = 1
        while clip_id in existing_clip_ids:
            index += 1
            clip_id = f"{base_id}_{index}"

        asset_key = clip_id.replace("\\", "/")
        return ClipModel(
            id=clip_id,
            source_path=str(source_path),
            export_path=asset_key,
            asset_key=asset_key,
        )

    def _build_event_from_audio_path(self, source_path: Path, reserved_event_ids: set[str] | None = None) -> EventModel:
        base_event_id = self._normalize_event_id(source_path.stem)
        event_id = self._make_unique_event_id(base_event_id, reserved_event_ids)
        event = self._make_casual_event_template(
            event_id,
            display_name=source_path.stem,
            default_bus=self.project.settings.default_bus,
            available_buses=self.project.settings.buses,
        )
        clip = ClipModel(
            id=event_id,
            source_path=str(source_path),
            export_path=event_id,
            asset_key=event_id,
        )
        event.clips.append(clip)
        return event

    def _normalize_event_id(self, raw_name: str) -> str:
        normalized = "".join(character if character.isalnum() else "_" for character in raw_name.strip())
        normalized = normalized.strip("_")
        return normalized or "New_Event"

    def _sync_multi_selection_affordances(self) -> None:
        is_multi_event_selection = len(self.selected_event_ids) > 1
        self.window.bulk_event_bus_button.setEnabled(bool(self.selected_event_ids))
        self.window.rename_button.setText("批量重命名" if is_multi_event_selection else "重命名")
        self.window.delete_button.setText("批量删除" if is_multi_event_selection else "删除")
        if is_multi_event_selection:
            self.window.set_active_property_category("工程")
            self.window.set_event_details(None)

    def _selected_events_bus_summary(self) -> str:
        bus_names = sorted({event.bus for event in self.current_events})
        return "、".join(bus_names) if bus_names else "-"

    def _build_scope_label(self, scope: str) -> str:
        return {
            "full": "全量构建",
            "incremental": "增量构建",
            "selection": "选中构建",
        }.get(scope, scope or "构建")

    def _collect_folder_event_ids(self, folder_id: str | None) -> list[str]:
        if folder_id is None or folder_id not in self.project.folders:
            return []
        folder = self.project.folders[folder_id]
        event_ids = [event_id for event_id in folder.child_event_ids if event_id in self.project.events]
        for child_folder_id in folder.child_folder_ids:
            event_ids.extend(self._collect_folder_event_ids(child_folder_id))
        return event_ids

    def _resolve_build_selection_context(self) -> tuple[list[str], str, str]:
        if self.selected_event_ids:
            event_ids = [event_id for event_id in self.selected_event_ids if event_id in self.project.events]
            if len(event_ids) == 1:
                return (
                    event_ids,
                    f"当前范围：事件 {event_ids[0]}",
                    "选中构建会以当前事件为脏根；若选区外也有脏资源，会自动扩展为增量构建。",
                )
            return (
                event_ids,
                f"当前范围：{len(event_ids)} 个选中事件",
                f"选中构建会以这 {len(event_ids)} 个事件为脏根；元数据文件仍会全量刷新。",
            )
        if self.selected_event_id is not None and self.selected_event_id in self.project.events:
            return (
                [self.selected_event_id],
                f"当前范围：事件 {self.selected_event_id}",
                "选中构建会以当前事件为脏根；若选区外也有脏资源，会自动扩展为增量构建。",
            )
        if self.selected_folder_id is not None and self.selected_folder_id in self.project.folders:
            folder = self.project.folders[self.selected_folder_id]
            event_ids = self._collect_folder_event_ids(folder.id)
            return (
                event_ids,
                f"当前范围：文件夹 {folder.name}（{len(event_ids)} 个事件）",
                "选中构建会覆盖当前文件夹及其子文件夹内的事件；若工程还有其他脏资源，会自动扩展为增量构建。",
            )
        return (
            [],
            "当前范围：整个工程",
            "增量和全量构建覆盖整个工程；如需选中构建，请先选择事件或包含事件的文件夹。",
        )

    def _sync_build_selection_context(self) -> None:
        _, summary, detail = self._resolve_build_selection_context()
        self.window.set_build_selection_context(summary, detail)

    def _selection_build_unavailable_message(self) -> str:
        return "当前选区没有可导出的事件，请先选择事件或包含事件的文件夹。"

    def _current_build_request(self) -> ExportRequest | None:
        scope = self.window.current_build_scope()
        selected_event_ids, summary, detail = self._resolve_build_selection_context()
        self.window.set_build_selection_context(summary, detail)
        selection_label = summary.replace("当前范围：", "", 1).strip() or "整个工程"
        if scope == "selection" and not selected_event_ids:
            return None
        return ExportRequest(
            scope=scope,
            selected_event_ids=tuple(selected_event_ids if scope == "selection" else ()),
            selection_label=selection_label,
        )

    def _format_build_plan_summary(self, plan: ExportPlan) -> tuple[str, str]:
        summary = (
            f"请求 {self._build_scope_label(plan.requested_scope)} | 实际 {self._build_scope_label(plan.effective_scope)} | "
            f"重建 {len(plan.rebuilt_asset_keys)} | 复用 {len(plan.reused_asset_keys)} | 移除 {len(plan.removed_asset_keys)}"
        )
        detail_parts = [
            f"目标 {plan.selection_label}",
            f"事件 新增 {len(plan.added_event_ids)} / 变更 {len(plan.changed_event_ids)} / 移除 {len(plan.removed_event_ids)}",
            plan.reason,
        ]
        if plan.out_of_scope_dirty_asset_keys:
            detail_parts.append(f"选区外附带脏资源 {len(plan.out_of_scope_dirty_asset_keys)}")
        return summary, " | ".join(detail_parts)

    def _update_object_context(self) -> None:
        if len(self.selected_event_ids) > 1:
            selected_events = self.current_events
            clip_count = sum(len(event.clips) for event in selected_events)
            folder_count = len({self.project.find_event_folder_id(event.id) for event in selected_events})
            self.window.set_object_context(
                object_type="多选事件",
                object_name=f"已选 {len(selected_events)} 个事件",
                breadcrumb=self.project.name,
                stats_text=f"片段 {clip_count} | 目录 {folder_count}",
                summary_primary=f"总线 {self._selected_events_bus_summary()} | 可批量改总线/重命名/删除",
                summary_secondary=f"当前主事件 {self.selected_event_id or '-'} | 导出 {self.project.settings.runtime_audio_format}",
                can_navigate_parent=False,
            )
            self.window.set_reference_context(
                parent_name="-",
                bus_name=self._selected_events_bus_summary(),
                assets_name=f"{clip_count} 个片段",
                generation_name=f"{self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
                work_unit_text="Work Unit：多目录",
                output_text=f"输出：{self.project.settings.default_bus} / {self.project.settings.export_root}",
                has_parent=False,
            )
            return

        if self.selected_event_id is not None and self.current_event is not None:
            event = self.current_event
            folder_id = self.project.find_event_folder_id(event.id)
            parent_name = self.project.folders[folder_id].name if folder_id in self.project.folders else "-"
            breadcrumb_parts = [self.project.name, *self._folder_path_names(folder_id), event.id]
            clip_tags = {tag for clip in event.clips for tag in clip.tags}
            cooldown_text = f"{event.cooldown_seconds:.2f}s" if event.cooldown_seconds else "无冷却"
            instances_text = "不限" if event.max_instances == 0 else str(event.max_instances)
            self.window.set_object_context(
                object_type="事件",
                object_name=event.display_name or event.id,
                breadcrumb=" / ".join(part for part in breadcrumb_parts if part),
                stats_text=f"片段 {len(event.clips)} | 标签 {len(clip_tags)} | 冷却 {cooldown_text}",
                summary_primary=f"模式 {event.play_mode} | 总线 {event.bus} | 试听 {self.preview_bus_mixer.describe_bus(event.bus)}",
                summary_secondary=f"实例 {instances_text} | 负载 {event.load_policy} | 输出 {self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
                can_navigate_parent=folder_id is not None,
            )
            self.window.set_reference_context(
                parent_name=parent_name,
                bus_name=f"{event.bus} / {self.preview_bus_mixer.describe_bus(event.bus)}",
                assets_name=f"{len(event.clips)} 个片段",
                generation_name=f"{self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
                work_unit_text=f"Work Unit：{self._folder_path_names(folder_id)[0] if self._folder_path_names(folder_id) else '-'}",
                output_text=f"输出：{event.bus} / {self.project.settings.export_root}",
                has_parent=folder_id is not None,
            )
            if self.window.property_tabs.currentIndex() == 3:
                self.window.set_active_property_category("事件")
            return

        if self.selected_folder_id is not None and self.selected_folder_id in self.project.folders:
            folder = self.project.folders[self.selected_folder_id]
            breadcrumb_parts = [self.project.name, *self._folder_path_names(folder.id)]
            parent_folder_id = self.project.find_folder_parent_id(folder.id)
            parent_name = self.project.folders[parent_folder_id].name if parent_folder_id in self.project.folders else "-"
            self.window.set_object_context(
                object_type="文件夹",
                object_name=folder.name,
                breadcrumb=" / ".join(part for part in breadcrumb_parts if part),
                stats_text=f"子文件夹 {len(folder.child_folder_ids)} | 事件 {len(folder.child_event_ids)}",
                summary_primary=f"默认总线 {self.project.settings.default_bus} | 总线数 {len(self.project.settings.buses)}",
                summary_secondary=f"导出目录 {self.project.settings.export_root} | 运行时 {self.project.settings.runtime_audio_format} | 最近对象 {self.selected_event_id or '无'}",
                can_navigate_parent=self.project.find_folder_parent_id(folder.id) is not None,
            )
            self.window.set_reference_context(
                parent_name=parent_name,
                bus_name=f"{self.project.settings.default_bus} / {self.preview_bus_mixer.describe_bus(self.project.settings.default_bus)}",
                assets_name=f"{len(folder.child_event_ids)} 个事件",
                generation_name=f"{self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
                work_unit_text=f"Work Unit：{self._folder_path_names(folder.id)[0] if self._folder_path_names(folder.id) else folder.name}",
                output_text=f"输出：{self.project.settings.default_bus} / {self.project.settings.export_root}",
                has_parent=parent_folder_id is not None,
            )
            return

        self.window.set_object_context(
            object_type="工程",
            object_name=self.project.name,
            breadcrumb=self.project.name,
            stats_text=f"事件 {len(self.project.events)} | 文件夹 {len(self.project.folders)}",
            summary_primary=f"默认总线 {self.project.settings.default_bus} | 总线数 {len(self.project.settings.buses)}",
            summary_secondary=f"导出目录 {self.project.settings.export_root} | 运行时 {self.project.settings.runtime_audio_format}",
            can_navigate_parent=False,
        )
        self.window.set_reference_context(
            parent_name="-",
            bus_name=f"{self.project.settings.default_bus} / {self.preview_bus_mixer.describe_bus(self.project.settings.default_bus)}",
            assets_name=f"{len(self.project.events)} 个事件",
            generation_name=f"{self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
            work_unit_text=f"Work Unit：{self.project.folders[self.project.root_folder_ids[0]].name if self.project.root_folder_ids else '-'}",
            output_text=f"输出：{self.project.settings.default_bus} / {self.project.settings.export_root}",
            has_parent=False,
        )

    def _folder_path_names(self, folder_id: str | None) -> list[str]:
        if folder_id is None or folder_id not in self.project.folders:
            return []
        names: list[str] = []
        current_folder_id: str | None = folder_id
        while current_folder_id is not None and current_folder_id in self.project.folders:
            folder = self.project.folders[current_folder_id]
            names.append(folder.name)
            current_folder_id = self.project.find_folder_parent_id(current_folder_id)
        return list(reversed(names))

    def _apply_mutation(self, description: str, mutation, merge_key: str | None = None) -> bool:
        before = self._capture_snapshot()
        changed = bool(mutation())
        after = self._capture_snapshot()
        if not changed:
            return False
        pushed = self.history.push(description, before, after, merge_key=merge_key)
        if pushed:
            self.is_dirty = True
            self._save_recovery_snapshot()
        return pushed

    def _capture_snapshot(self) -> EditorSnapshot:
        return self.history.capture(self.project, self.selected_event_id, self.selected_folder_id)

    def _restore_snapshot(self, snapshot: EditorSnapshot) -> None:
        self.project = snapshot.project
        self.selected_event_id = snapshot.selected_event_id
        self.selected_event_ids = [snapshot.selected_event_id] if snapshot.selected_event_id else []
        self.selected_folder_id = snapshot.selected_folder_id
        self.is_dirty = True
        self._save_recovery_snapshot()

    def _handle_close_request(self) -> bool:
        if not self.is_dirty:
            return True
        action = self.window.confirm_save_before_close()
        if action == "cancel":
            return False
        if action == "discard":
            self._clear_recovery_snapshot()
            return True
        return self.save_project()

    def _confirm_abandon_unsaved_changes(self) -> bool:
        if not self.is_dirty:
            return True
        action = self.window.confirm_save_before_close()
        if action == "cancel":
            return False
        if action == "discard":
            self._clear_recovery_snapshot()
            return True
        return self.save_project()

    def _save_recovery_snapshot(self) -> None:
        try:
            self.recovery_service.save_snapshot(self.project)
        except Exception as exc:
            self.window.append_log(f"自动恢复快照保存失败：{exc}")

    def _clear_recovery_snapshot(self) -> None:
        try:
            self.recovery_service.clear_snapshot()
        except Exception as exc:
            self.window.append_log(f"自动恢复快照清理失败：{exc}")

    def _restore_recovery_snapshot_if_available(self) -> None:
        if not self.recovery_service.has_snapshot():
            return
        try:
            snapshot = self.recovery_service.load_snapshot()
        except Exception as exc:
            self.window.append_log(f"自动恢复快照损坏，已忽略：{exc}")
            self._clear_recovery_snapshot()
            return

        prompt = (
            f"检测到未保存的自动恢复快照。\n\n"
            f"工程路径：{snapshot.original_project_path or '未保存工程'}\n"
            f"快照时间：{snapshot.saved_at}\n\n"
            f"是否恢复这份快照？"
        )
        result = QMessageBox.question(self.window, "恢复自动保存快照", prompt)
        if result != QMessageBox.StandardButton.Yes:
            self._clear_recovery_snapshot()
            return

        self.project = snapshot.project
        self.preview_service.clear()
        self.history.clear()
        self.is_dirty = True
        self.selected_event_id = next(iter(self.project.events), None)
        self.selected_event_ids = [self.selected_event_id] if self.selected_event_id else []
        self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id) if self.selected_event_id else next(iter(self.project.root_folder_ids), None)
        self.window.append_log("已恢复自动保存快照。")
        self._refresh_ui()

    def _recent_projects(self) -> list[str]:
        value = self.settings.value("recentProjects", [])
        if isinstance(value, str):
            return [value] if value else []
        return [str(item) for item in value or []]

    def _remember_recent_project(self, file_path: str) -> None:
        recent = [item for item in self._recent_projects() if item != file_path]
        recent.insert(0, file_path)
        self.settings.setValue("recentProjects", recent[:10])
        self._sync_recent_projects_ui()

    def _remove_recent_project(self, file_path: str) -> None:
        recent = [item for item in self._recent_projects() if item != file_path]
        self.settings.setValue("recentProjects", recent)
        self._sync_recent_projects_ui()

    def _sync_recent_projects_ui(self) -> None:
        self.window.set_recent_projects(self._recent_projects())

    def _restore_window_preferences(self) -> None:
        default_preferences = self.window.ui_preferences()
        preferences = {
            "ui_scale": self.settings.value("uiScale", 1.0),
            "workspace_splitter_sizes": self.settings.value("workspaceSplitterSizes", default_preferences["workspace_splitter_sizes"]),
            "main_splitter_sizes": self.settings.value("mainSplitterSizes", default_preferences["main_splitter_sizes"]),
            "active_editor_tab": self.settings.value("activeEditorTab", default_preferences["active_editor_tab"]),
            "inspector_splitter_sizes": self.settings.value("inspectorSplitterSizes", default_preferences["inspector_splitter_sizes"]),
            "content_top_splitter_sizes": self.settings.value("contentTopSplitterSizes", default_preferences["content_top_splitter_sizes"]),
            "active_contents_tab": self.settings.value("activeContentsTab", default_preferences["active_contents_tab"]),
            "event_import_template": self.settings.value("eventImportTemplate", default_preferences["event_import_template"]),
        }
        self.window.apply_ui_preferences(preferences)

    def _save_window_preferences(self) -> None:
        preferences = self.window.ui_preferences()
        self.settings.setValue("uiScale", preferences["ui_scale"])
        self.settings.setValue("workspaceSplitterSizes", preferences["workspace_splitter_sizes"])
        self.settings.setValue("mainSplitterSizes", preferences["main_splitter_sizes"])
        self.settings.setValue("activeEditorTab", preferences["active_editor_tab"])
        self.settings.setValue("inspectorSplitterSizes", preferences["inspector_splitter_sizes"])
        self.settings.setValue("contentTopSplitterSizes", preferences["content_top_splitter_sizes"])
        self.settings.setValue("activeContentsTab", preferences["active_contents_tab"])
        self.settings.setValue("eventImportTemplate", preferences["event_import_template"])

    def validate_project(self) -> None:
        issues = self.validator.validate(self.project)
        self.window.append_log(f"校验完成，共发现 {len(issues)} 个问题。")
        self.window.set_validation_report(self._format_validation_report(issues), issues)
        self.window.show_report_tab(1)
        self.window.show_validation_summary(issues)

    def build_project(self) -> None:
        build_request = self._current_build_request()
        if build_request is None:
            message = self._selection_build_unavailable_message()
            self.window.set_build_plan_summary("选中构建未就绪。", message)
            self.window.set_build_status("选中构建无法开始。", message, activate_results=True)
            self.window.set_build_report("构建未开始\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self.window.show_report_tab(2)
            self.window.append_log(f"选中构建已中止：{message}")
            return

        requested_scope_label = self._build_scope_label(build_request.scope)
        self.window.build_execute_button.setEnabled(False)
        self.window.build_button.setEnabled(False)
        self.window.set_build_status(
            "正在构建导出，请稍候。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 正在导出到：{self.project.settings.export_root}",
            activate_results=True,
        )
        self.window.append_log(f"已开始构建导出：模式={requested_scope_label} 目标={build_request.selection_label}")
        self.window.show_report_tab(2)
        self.application.processEvents()

        issues = self.validator.validate(self.project)
        error_count = sum(1 for issue in issues if issue.severity == "Error")
        self.window.set_validation_report(self._format_validation_report(issues), issues)
        if error_count:
            self.window.append_log(f"构建已中止，存在 {error_count} 个错误。")
            self.window.set_build_plan_summary(
                "构建已中止。",
                f"{requested_scope_label} 在校验阶段被拦截：存在 {error_count} 个错误。",
            )
            self.window.set_build_status(
                "构建已中止。",
                f"校验阶段发现 {error_count} 个错误，请先在校验修复页处理后再重新构建。",
            )
            self.window.show_report_tab(1)
            self.window.show_validation_summary(issues)
            self.window.build_execute_button.setEnabled(True)
            self.window.build_button.setEnabled(True)
            return

        export_root = Path(self.project.settings.export_root)
        if not export_root.is_absolute():
            export_root = Path.cwd() / export_root

        plan: ExportPlan | None = None
        try:
            plan = self.exporter.plan_export(self.project, export_root, build_request)
            plan_summary, plan_detail = self._format_build_plan_summary(plan)
            self.window.set_build_plan_summary(plan_summary, plan_detail)
            result = self.exporter.export(self.project, export_root, issues, copy_assets=True, request=build_request, plan=plan)
            build_report = self._format_build_report(result.report_file, result.manifest_file)
        except Exception as exc:
            failure_message = f"构建失败：{exc}"
            self.window.append_log(failure_message)
            self.window.set_build_status(
                "构建失败。",
                f"模式：{requested_scope_label} | 导出目录：{export_root} | 原因：{exc}",
                activate_results=True,
            )
            if plan is not None:
                plan_summary, plan_detail = self._format_build_plan_summary(plan)
                self.window.set_build_plan_summary(plan_summary, plan_detail)
            self.window.set_build_report(
                "\n".join(
                    [
                        "构建失败",
                        "",
                        f"工程：{self.project.name}",
                        f"请求范围：{requested_scope_label}",
                        f"导出目录：{export_root}",
                        f"原因：{exc}",
                    ]
                )
            )
            self.window.show_report_tab(2)
            QMessageBox.critical(self.window, "构建失败", str(exc))
            self.window.build_execute_button.setEnabled(True)
            self.window.build_button.setEnabled(True)
            return

        self.window.append_log(f"构建完成：{result.data_file}")
        self.window.append_log(f"已生成清单：{result.manifest_file}")
        effective_scope_label = self._build_scope_label(result.plan.effective_scope)
        scope_display = requested_scope_label if effective_scope_label == requested_scope_label else f"{requested_scope_label} -> {effective_scope_label}"
        plan_summary, plan_detail = self._format_build_plan_summary(result.plan)
        self.window.set_build_plan_summary(plan_summary, plan_detail)
        self.window.set_build_status(
            "构建完成。",
            f"模式：{scope_display} | 已导出到：{result.data_file} | 清单：{result.manifest_file}",
            activate_results=True,
        )
        self.window.set_build_report(build_report)
        self.window.show_report_tab(2)
        self.window.build_execute_button.setEnabled(True)
        self.window.build_button.setEnabled(True)

    def preview_export_diff(self) -> None:
        self.window.clear_build_status()
        build_request = self._current_build_request()
        if build_request is None:
            message = self._selection_build_unavailable_message()
            self.window.set_build_plan_summary("选中构建未就绪。", message)
            self.window.set_build_report("构建计划不可用\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self.window.show_report_tab(2)
            self.window.append_log(f"选中构建预览已中止：{message}")
            return
        export_root = Path(self.project.settings.export_root)
        if not export_root.is_absolute():
            export_root = Path.cwd() / export_root
        try:
            plan = self.exporter.plan_export(self.project, export_root, build_request)
            plan_summary, plan_detail = self._format_build_plan_summary(plan)
            self.window.set_build_plan_summary(plan_summary, plan_detail)
            report = self._format_export_diff_preview(export_root, plan)
        except Exception as exc:
            self.window.set_build_plan_summary("构建计划生成失败。", str(exc))
            report = f"导出差异预览失败\n\n导出目录：{export_root}\n原因：{exc}"
            self.window.append_log(f"导出差异预览失败：{exc}")
        self.window.set_build_report(report)
        self.window.show_report_tab(2)
        self.window.append_log("已生成导出差异预览。")

    def navigate_to_report_target(self, target_type: str, target_id: str) -> None:
        if not target_id:
            return
        if (target_type == "event" and target_id in self.project.events) or (target_type == "auto" and target_id in self.project.events):
            self.select_node("event", target_id)
            self.window.set_active_property_category("事件")
            return
        if (target_type == "folder" and target_id in self.project.folders) or (target_type == "auto" and target_id in self.project.folders):
            self.select_node("folder", target_id)
            self.window.set_active_property_category("工程")
            return
        self.window.append_log(f"问题定位失败：未找到目标 {target_type}:{target_id}")

    def _classify_import_file_paths(self, file_paths: list[str]) -> tuple[list[Path], list[Path], list[Path]]:
        supported_paths: list[Path] = []
        skipped_unsupported: list[Path] = []
        skipped_missing: list[Path] = []
        for file_path in file_paths:
            source_path = Path(file_path)
            if not source_path.exists():
                skipped_missing.append(source_path)
                continue
            if source_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                skipped_unsupported.append(source_path)
                continue
            supported_paths.append(source_path)
        return supported_paths, skipped_unsupported, skipped_missing

    def _format_import_skip_suffix(self, skipped_unsupported: list[Path], skipped_missing: list[Path]) -> str:
        skipped_segments: list[str] = []
        if skipped_unsupported:
            skipped_segments.append(f"跳过 {len(skipped_unsupported)} 个不支持的文件")
        if skipped_missing:
            skipped_segments.append(f"跳过 {len(skipped_missing)} 个不存在的文件")
        if not skipped_segments:
            return ""
        return " 已忽略：" + "，".join(skipped_segments) + "。"

    def _notify_import_skip(self, title: str, skipped_unsupported: list[Path], skipped_missing: list[Path]) -> None:
        reason = self._format_import_skip_suffix(skipped_unsupported, skipped_missing).strip()
        if not reason:
            return
        message = f"没有可导入的音频文件。{reason}"
        self.window.append_log(f"{title}失败：{message}")
        QMessageBox.warning(self.window, title, message)

    def _format_validation_report(self, issues) -> str:
        lines = [
            f"工程：{self.project.name}",
            f"更新时间：{self.project.updated_at}",
            f"问题总数：{len(issues)}",
            "",
        ]
        if not issues:
            lines.append("校验通过，没有发现问题。")
            return "\n".join(lines)

        grouped: dict[str, list[str]] = {"Error": [], "Warning": [], "Info": []}
        for issue in issues:
            grouped.setdefault(issue.severity, []).append(f"{issue.target}: {issue.message} ({issue.code})")

        for severity in ("Error", "Warning", "Info"):
            items = grouped.get(severity, [])
            if not items:
                continue
            severity_cn = {"Error": "错误", "Warning": "警告", "Info": "信息"}.get(severity, severity)
            lines.append(f"[{severity_cn}] {len(items)}")
            lines.extend(f"- {item}" for item in items)
            lines.append("")
        return "\n".join(lines).strip()

    def _format_build_report(self, report_file: Path, manifest_file: Path) -> str:
        report_payload = json.loads(report_file.read_text(encoding="utf-8"))
        manifest_payload = json.loads(manifest_file.read_text(encoding="utf-8"))
        runtime_payload = json.loads((report_file.parent / "AudioData.json").read_text(encoding="utf-8"))
        build_plan = report_payload.get("BuildPlan", {})
        requested_scope = self._build_scope_label(str(build_plan.get("RequestedScope", "full")))
        effective_scope = self._build_scope_label(str(build_plan.get("EffectiveScope", "full")))
        lines = [
            f"请求构建范围：{requested_scope}",
            f"实际执行范围：{effective_scope}",
            f"构建目标：{build_plan.get('SelectionLabel', '整个工程')}",
            f"计划说明：{build_plan.get('Reason', '-')}",
            f"重建资源：{len(build_plan.get('RebuiltAssetKeys', []))}",
            f"复用资源：{len(build_plan.get('ReusedAssetKeys', []))}",
            f"移除资源：{len(build_plan.get('RemovedAssetKeys', []))}",
            "",
            f"工程版本：{report_payload.get('ProjectVersion', 'n/a')}",
            f"Schema 版本：{report_payload.get('SchemaVersion', 'n/a')}",
            f"事件数：{report_payload.get('EventCount', 0)}",
            f"片段数：{report_payload.get('ClipCount', 0)}",
            f"错误数：{report_payload.get('ErrorCount', 0)}",
            f"警告数：{report_payload.get('WarningCount', 0)}",
            f"资源目录：{report_payload.get('AssetsDirectory', 'Assets')}",
            "",
            f"导出总线数：{len(runtime_payload.get('BusConfigs', []))}",
        ]
        if build_plan.get("OutOfScopeDirtyAssetKeys"):
            lines.append(f"选区外附带脏资源：{len(build_plan.get('OutOfScopeDirtyAssetKeys', []))}")
            for asset_key in build_plan.get("OutOfScopeDirtyAssetKeys", [])[:12]:
                lines.append(f"- {asset_key}")
            lines.append("")
        rebuilt_assets = build_plan.get("RebuiltAssetKeys", [])
        if rebuilt_assets:
            lines.append(f"本次实际重建：{len(rebuilt_assets)}")
            for asset_key in rebuilt_assets[:20]:
                lines.append(f"- {asset_key}")
            if len(rebuilt_assets) > 20:
                lines.append(f"…… 还有 {len(rebuilt_assets) - 20} 个重建资源")
            lines.append("")
        for bus_payload in runtime_payload.get("BusConfigs", [])[:10]:
            lines.append(
                f"- {bus_payload.get('Name', '')} -> {bus_payload.get('ParentBus', MASTER_BUS_NAME)} [{bus_payload.get('VolumeDb', 0.0):.1f}dB muted={bus_payload.get('IsMuted', False)}]"
            )
        lines.extend(
            [
                "",
            f"导出资源数：{len(manifest_payload.get('Assets', []))}",
            ]
        )
        for asset in manifest_payload.get("Assets", [])[:20]:
            lines.append(
                f"- {asset.get('AssetKey', '')} -> {asset.get('ExportPath', '')} [{asset.get('RuntimeFormat', '')}]"
            )
        if len(manifest_payload.get("Assets", [])) > 20:
            lines.append(f"…… 还有 {len(manifest_payload.get('Assets', [])) - 20} 个资源")
        return "\n".join(lines)

    def _format_export_diff_preview(self, export_root: Path, plan: ExportPlan) -> str:
        lines = [
            f"导出目录：{export_root}",
            f"请求范围：{self._build_scope_label(plan.requested_scope)}",
            f"实际执行：{self._build_scope_label(plan.effective_scope)}",
            f"构建目标：{plan.selection_label}",
            f"计划说明：{plan.reason}",
            "",
            f"事件变更：新增 {len(plan.added_event_ids)} | 变更 {len(plan.changed_event_ids)} | 移除 {len(plan.removed_event_ids)}",
            f"资源计划：重建 {len(plan.rebuilt_asset_keys)} | 复用 {len(plan.reused_asset_keys)} | 移除 {len(plan.removed_asset_keys)}",
            "",
        ]
        current_runtime_payload = plan.current_runtime_payload
        current_bus_configs = {str(bus.get("Name", "")): bus for bus in current_runtime_payload.get("BusConfigs", [])}
        lines.append(f"当前 BusConfigs：{len(current_bus_configs)}")
        for bus_name, bus_payload in list(current_bus_configs.items())[:12]:
            lines.append(
                f"- {bus_name}: parent={bus_payload.get('ParentBus', MASTER_BUS_NAME)} volume={bus_payload.get('VolumeDb', 0.0):.1f}dB muted={bus_payload.get('IsMuted', False)}"
            )
        lines.append("")
        data_file = export_root / "AudioData.json"
        if data_file.exists():
            previous_runtime_payload = json.loads(data_file.read_text(encoding="utf-8"))
            previous_bus_configs = {str(bus.get("Name", "")): bus for bus in previous_runtime_payload.get("BusConfigs", [])}
            added_buses = sorted(set(current_bus_configs) - set(previous_bus_configs))
            removed_buses = sorted(set(previous_bus_configs) - set(current_bus_configs))
            changed_buses = []
            for bus_name in sorted(set(current_bus_configs) & set(previous_bus_configs)):
                current_bus = current_bus_configs[bus_name]
                previous_bus = previous_bus_configs[bus_name]
                if any(current_bus.get(field) != previous_bus.get(field) for field in ("ParentBus", "VolumeDb", "IsMuted")):
                    changed_buses.append(bus_name)
            if added_buses or removed_buses or changed_buses:
                lines.append("BusConfigs 差异：")
                lines.extend(f"- 新增总线 {bus_name}" for bus_name in added_buses[:12])
                lines.extend(f"- 移除总线 {bus_name}" for bus_name in removed_buses[:12])
                lines.extend(f"- 变更总线 {bus_name}" for bus_name in changed_buses[:12])
                lines.append("")

        if plan.out_of_scope_dirty_asset_keys:
            lines.append(f"选区外附带脏资源：{len(plan.out_of_scope_dirty_asset_keys)}")
            lines.extend(f"- {asset_key}" for asset_key in plan.out_of_scope_dirty_asset_keys[:20])
            lines.append("")

        if not plan.added_asset_keys and not plan.removed_asset_keys and not plan.changed_asset_keys:
            lines.append("没有检测到音频资源差异。")
            if plan.changed_event_ids or plan.added_event_ids or plan.removed_event_ids:
                lines.append("本次仍会刷新元数据文件，以同步事件参数和总线配置变化。")
            return "\n".join(lines)

        if plan.added_asset_keys:
            lines.append(f"新增资源：{len(plan.added_asset_keys)}")
            lines.extend(f"- {asset_key}" for asset_key in plan.added_asset_keys[:20])
            lines.append("")
        if plan.removed_asset_keys:
            lines.append(f"移除资源：{len(plan.removed_asset_keys)}")
            lines.extend(f"- {asset_key}" for asset_key in plan.removed_asset_keys[:20])
            lines.append("")
        if plan.changed_asset_keys:
            lines.append(f"变更资源：{len(plan.changed_asset_keys)}")
            lines.extend(f"- {asset_key}" for asset_key in plan.changed_asset_keys[:20])
            lines.append("")
        if plan.rebuilt_asset_keys:
            lines.append(f"本次将重建资源：{len(plan.rebuilt_asset_keys)}")
            lines.extend(f"- {asset_key}" for asset_key in plan.rebuilt_asset_keys[:20])
            lines.append("")
        if plan.reused_asset_keys:
            lines.append(f"本次将复用资源：{len(plan.reused_asset_keys)}")
        return "\n".join(lines).strip()

    def _apply_event_import_template(self, event: EventModel, template: dict[str, object] | None) -> None:
        if not template:
            return
        bus_name = str(template.get("bus_name", "")).strip()
        asset_prefix = str(template.get("asset_prefix", "")).strip().strip("/")
        tags = [str(tag) for tag in template.get("tags", [])]
        if bus_name and bus_name in self.project.settings.buses:
            event.bus = bus_name
        for clip in event.clips:
            if asset_prefix:
                asset_key = f"{asset_prefix}/{clip.id}".replace("\\", "/")
                clip.asset_key = asset_key
                clip.export_path = asset_key
            if tags:
                clip.tags = list(tags)

    def _describe_event_import_template(self, template: dict[str, object] | None) -> str:
        if not template:
            return ""
        parts: list[str] = []
        bus_name = str(template.get("bus_name", "")).strip()
        asset_prefix = str(template.get("asset_prefix", "")).strip()
        tags = [str(tag) for tag in template.get("tags", [])]
        if bus_name:
            parts.append(f"总线 {bus_name}")
        if asset_prefix:
            parts.append(f"资源前缀 {asset_prefix}")
        if tags:
            parts.append(f"标签 {', '.join(tags)}")
        if not parts:
            return ""
        return " 模板：" + " | ".join(parts)
