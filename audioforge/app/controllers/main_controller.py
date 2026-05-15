from __future__ import annotations

import copy
import json
import logging
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from audioforge.app.models.audio_project import (
    AudioObjectModel,
    AudioProject,
    BusConfig,
    ClipModel,
    EventModel,
    FolderModel,
    GameParameterModel,
    MASTER_BUS_NAME,
    RtpcBindingModel,
    StateGroupModel,
    StateOverrideModel,
    SwitchGroupModel,
    SwitchVariantModel,
    ValidationIssue,
    new_id,
    normalize_event_binding_states,
)
from audioforge.app.services.audio_meter_service import AudioMeterService
from audioforge.app.services.command_history import CommandHistory, EditorSnapshot
from audioforge.app.services.exporter import ExportPlan, ExportRequest, RuntimeExporter
from audioforge.app.services.playback_service import PlaybackService
from audioforge.app.services.preview_audio_renderer import PreviewAudioRenderer
from audioforge.app.services.preview_bus_mixer import MASTER_BUS_NAME, PreviewBusMixer
from audioforge.app.services.preview_service import PreviewGameSyncContext, PreviewService
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
    WWISE_DEFAULT_BUS_LABEL,
    WWISE_OUTPUT_BUS_LABEL,
    WWISE_TRANSPORT_TITLE,
)
from audioforge.app.utils.runtime_logging import get_runtime_log_config
from audioforge.app.views.main_window import MainWindow
from audioforge.app.widgets.event_tree import decode_source_binding_token, encode_source_binding_token


LOUDNESS_SCAN_THRESHOLDS = {
    "integrated_max_lufs": -16.0,
    "momentary_max_lufs": -10.0,
    "true_peak_max_dbtp": -1.0,
}

logger = logging.getLogger(__name__)

DIAGNOSTIC_FALLBACK_SUMMARY = "诊断概览已接入结果中心；等待新的日志、校验、构建或响度结果。"
DIAGNOSTIC_SECTION_DEFAULTS = {
    "log": "最近日志：等待运行输出。",
    "validation": "等待校验。",
    "build": "等待构建或差异预览。",
    "loudness": "等待响度扫描。",
    "bus": "等待 Bus 上下文。",
}
DIAGNOSTIC_PRIORITY_ORDER = ("validation", "build", "loudness", "bus", "log")
DIAGNOSTIC_SECTION_TITLES = {
    "validation": "校验",
    "build": "构建",
    "loudness": "响度",
    "bus": "Bus 状态",
    "log": "日志",
}


@dataclass(slots=True)
class DiagnosticSection:
    name: str
    default_summary: str
    summary: str = ""
    detail: str = ""
    status: str = "idle"
    target_type: str = ""
    target_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.summary:
            self.summary = self.default_summary
        if not self.detail:
            self.detail = self.summary

    def reset(self) -> None:
        self.summary = self.default_summary
        self.detail = self.default_summary
        self.status = "idle"
        self.target_type = ""
        self.target_id = ""
        self.metadata = {}

    def update(
        self,
        *,
        summary: str,
        detail: str | None = None,
        status: str = "info",
        target_type: str = "",
        target_id: str = "",
        metadata: dict[str, object] | None = None,
    ) -> None:
        normalized_summary = summary.strip() or self.default_summary
        normalized_detail = (detail if detail is not None else normalized_summary).strip() or normalized_summary
        self.summary = normalized_summary
        self.detail = normalized_detail
        self.status = status
        self.target_type = target_type.strip()
        self.target_id = target_id.strip()
        self.metadata = dict(metadata or {})


def _create_default_diagnostic_sections() -> dict[str, DiagnosticSection]:
    return {
        name: DiagnosticSection(name=name, default_summary=default_summary)
        for name, default_summary in DIAGNOSTIC_SECTION_DEFAULTS.items()
    }


@dataclass(slots=True)
class DiagnosticSnapshot:
    summary: str = DIAGNOSTIC_FALLBACK_SUMMARY
    sections: dict[str, DiagnosticSection] = field(default_factory=_create_default_diagnostic_sections)

    def section(self, name: str) -> DiagnosticSection:
        return self.sections[name]

    def as_payload(self) -> dict[str, object]:
        return {
            "summary": self.summary,
            "log_summary": self.section("log").summary,
            "validation_summary": self.section("validation").summary,
            "build_summary": self.section("build").summary,
            "loudness_summary": self.section("loudness").summary,
            "bus_summary": self.section("bus").summary,
        }


@dataclass(slots=True)
class AuditionSession:
    playback_owner_id: str
    event_id: str | None
    event_name: str
    clip_id: str
    asset_key: str
    file_path: str
    target_kind: str
    title: str
    detail: str
    bus_name: str
    effective_volume_db: float
    tracked_base_volume_db: float
    pitch_cents: int
    preserve_timing_pitch_cents: int
    trim_start_ms: int
    trim_end_ms: int
    fade_in_ms: int
    fade_out_ms: int
    event_volume_db_at_capture: float | None = None
    event_pitch_cents_at_capture: int | None = None


class _BuildWorker(QObject):
    succeeded = Signal(object, object)
    validation_blocked = Signal(object, int)
    failed = Signal(str, object)
    finished = Signal()

    def __init__(
        self,
        project: AudioProject,
        export_root: Path,
        build_request: ExportRequest,
        validator: ProjectValidator,
        exporter: RuntimeExporter,
    ) -> None:
        super().__init__()
        self.project = project
        self.export_root = export_root
        self.build_request = build_request
        self.validator = validator
        self.exporter = exporter

    @Slot()
    def run(self) -> None:
        plan: ExportPlan | None = None
        try:
            logger.info(
                "Build worker started scope=%s selection=%s export_root=%s event_count=%d",
                self.build_request.scope,
                self.build_request.selection_label,
                self.export_root,
                len(self.project.events),
            )
            issues = self.validator.validate(self.project)
            error_count = sum(1 for issue in issues if issue.severity == "Error")
            logger.info(
                "Build worker validation completed scope=%s selection=%s errors=%d warnings=%d",
                self.build_request.scope,
                self.build_request.selection_label,
                error_count,
                sum(1 for issue in issues if issue.severity == "Warning"),
            )
            if error_count:
                self.validation_blocked.emit(issues, error_count)
                return

            plan = self.exporter.plan_export(self.project, self.export_root, self.build_request)
            logger.info(
                "Build worker export plan prepared requested_scope=%s effective_scope=%s rebuilt_assets=%d reused_assets=%d",
                plan.requested_scope,
                plan.effective_scope,
                len(plan.rebuilt_asset_keys),
                len(plan.reused_asset_keys),
            )
            result = self.exporter.export(
                self.project,
                self.export_root,
                issues,
                copy_assets=True,
                request=self.build_request,
                plan=plan,
            )
            logger.info(
                "Build worker succeeded export_root=%s report_file=%s",
                result.export_root,
                result.report_file,
            )
            self.succeeded.emit(result, issues)
        except Exception as exc:
            logger.exception(
                "Build worker failed scope=%s selection=%s export_root=%s",
                self.build_request.scope,
                self.build_request.selection_label,
                self.export_root,
            )
            self.failed.emit(str(exc), plan)
        finally:
            logger.info(
                "Build worker finished scope=%s selection=%s export_root=%s",
                self.build_request.scope,
                self.build_request.selection_label,
                self.export_root,
            )
            self.finished.emit()


class MainController(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.application = QApplication.instance() or QApplication([])
        if sys.platform == "darwin":
            self.application.setStyle("Fusion")
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
        self.selected_audio_id: str | None = None
        self.selected_folder_id: str | None = None
        self.selected_source_binding_tokens: list[str] = []
        self.is_dirty = False
        self._analysis_status: dict[str, dict[str, str]] = {}
        self._diagnostic_snapshot = DiagnosticSnapshot()
        self._build_thread: QThread | None = None
        self._build_worker: _BuildWorker | None = None
        self._active_build_scope_label: str | None = None
        self._active_build_export_root: Path | None = None
        self._audition_session: AuditionSession | None = None
        self._preview_transport_timer = QTimer(self)
        self._preview_transport_timer.setInterval(200)
        self._preview_transport_timer.timeout.connect(self._poll_preview_transport_state)
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
        resolved_bus = fallback_bus
        current_settings = getattr(getattr(self, "project", None), "settings", None)
        if current_settings is None or bool(current_settings.auto_assign_bus_by_name):
            resolved_bus = self._suggest_bus_for_event_name(display_name or event_id, fallback_bus, buses)
        if suggested_bus in buses:
            resolved_bus = str(suggested_bus)
        event = EventModel(
            id=event_id,
            display_name=display_name or event_id.replace("_", " "),
            bus=resolved_bus,
            play_mode="OneShot",
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
        self.window.audio_tree.audioSelected.connect(self.select_audio)
        self.window.tree.audioFilesDropped.connect(self.import_audio_files_as_events)
        self.window.tree.sourceAssetsDroppedToAudio.connect(lambda source_paths, event_id: self.assign_source_assets_to_audio(event_id, source_paths, replace_existing=False))
        self.window.audio_tree.audioFilesDropped.connect(self.import_audio_files_to_audio)
        self.window.audio_tree.sourceAssetsDroppedToAudio.connect(lambda source_paths, audio_id: self.assign_source_assets_to_audio_object(audio_id, source_paths, replace_existing=False))
        self.window.source_tree.importFilesDropped.connect(self.import_audio_files_to_source_registry)
        self.window.removeSourceAssetsFromCurrentAudioRequested.connect(self.remove_source_assets_from_current_audio)
        self.window.removeSourceAssetsFromRegistryRequested.connect(self.remove_source_assets_from_registry)
        self.window.deleteSourceFilesRequested.connect(self.delete_source_files)
        self.window.tree.eventAudioRequested.connect(self.navigate_to_event_audio)
        self.window.eventPropertiesChanged.connect(self.update_current_event_from_form)
        self.window.audioPropertiesChanged.connect(self.update_current_audio_from_form)
        self.window.projectSettingsChanged.connect(self.update_project_settings_from_form)
        self.window.gameSyncChanged.connect(self.update_gamesync_from_form)
        self.window.previewGameSyncChanged.connect(self.update_preview_gamesync_from_form)
        self.window.previewBusSelectionChanged.connect(self.sync_preview_bus_editor)
        self.window.previewBusStateChanged.connect(self.update_preview_bus_state_from_form)
        self.window.previewTransportPlayRequested.connect(self.play_recent_preview_transport)
        self.window.pausePreviewRequested.connect(self.pause_current_event_preview)
        self.window.resumePreviewRequested.connect(self.resume_current_event_preview)
        self.window.restartPreviewRequested.connect(self.restart_current_event_preview)
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
        self.window.assignSourceAssetsToCurrentAudioRequested.connect(self.assign_source_assets_to_current_audio)
        self.window.assignSourceAssetsToAudioRequested.connect(self.assign_source_assets_to_audio)
        self.window.audioSourceBindingEnabledChangedRequested.connect(self.update_audio_source_binding_enabled)
        self.window.audioSourceBindingActiveChangedRequested.connect(self.update_audio_source_binding_active)
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
        self.window.openAudioBindingsForAudioRequested.connect(self.open_audio_bindings_for_audio)
        self.window.source_tree.sourceSelected.connect(lambda _source_path: self._sync_browser_action_affordances())
        self.window.audio_tree.audioSelected.connect(lambda _audio_id: self._sync_browser_action_affordances())
        self.window.explorer_tabs.currentChanged.connect(lambda _index: self._sync_browser_action_affordances())
        self.window.logAppended.connect(self._handle_log_appended)
        self.window.diagnosticContextChanged.connect(self._publish_diagnostic_snapshot)
        self.window.validationReportUpdated.connect(self._handle_validation_report_updated)
        self.window.buildStatusUpdated.connect(self._handle_build_status_updated)
        self.window.loudnessReportUpdated.connect(self._handle_loudness_report_updated)

    def _refresh_ui(self) -> None:
        navigation_state = self.window.navigation_state()
        if self._audition_session is not None and self._audition_session.event_id not in {None, *self.project.events.keys()}:
            self._audition_session = None
        self.selected_event_ids = [event_id for event_id in self.selected_event_ids if event_id in self.project.events]
        resolved_binding_pairs = self._resolved_source_binding_pairs()
        self.selected_source_binding_tokens = [encode_source_binding_token(event_id, clip_id) for event_id, clip_id in resolved_binding_pairs]
        binding_event_ids = [event_id for event_id, _clip_id in resolved_binding_pairs if event_id in self.project.events]
        for event_id in binding_event_ids:
            if event_id not in self.selected_event_ids:
                self.selected_event_ids.append(event_id)
        preserve_audio_only_selection = (
            self.selected_audio_id in self.project.audio_objects
            and not self._event_ids_for_audio(self.selected_audio_id)
        )
        if self.selected_event_id not in self.project.events:
            if self.selected_event_ids:
                self.selected_event_id = self.selected_event_ids[0]
            elif preserve_audio_only_selection:
                self.selected_event_id = None
            else:
                self.selected_event_id = next(iter(self.project.events), None)
        if self.selected_event_id is not None and self.selected_event_id not in self.selected_event_ids:
            self.selected_event_ids = [self.selected_event_id, *self.selected_event_ids]
        if self.selected_audio_id not in self.project.audio_objects:
            self.selected_audio_id = self.current_event.audio_id if self.current_event is not None else next(iter(self.project.audio_objects), None)
        if self.selected_folder_id not in self.project.folders:
            self.selected_folder_id = next(iter(self.project.root_folder_ids), None)
        self.window.tree.rebuild(self.project)
        self.window.tree.set_analysis_status(self._analysis_status)
        if binding_event_ids:
            self.window.tree.select_nodes(
                [("event", event_id) for event_id in binding_event_ids],
                current_node=("event", self.selected_event_id) if self.selected_event_id in binding_event_ids else ("event", binding_event_ids[0]),
            )
        elif self.selected_event_ids:
            self.window.tree.select_nodes(
                [("event", event_id) for event_id in self.selected_event_ids],
                current_node=("event", self.selected_event_id) if self.selected_event_id is not None else None,
            )
        elif self.selected_event_id is not None:
            self.window.tree.select_node("event", self.selected_event_id)
        elif self.selected_folder_id is not None:
            self.window.tree.select_node("folder", self.selected_folder_id, emit_signal=not preserve_audio_only_selection)
        self.window.set_source_browser_entries(self._build_source_browser_entries())
        self.window.set_audio_browser_entries(self._build_audio_browser_entries())
        self.window.select_audio_browser_audio(self.selected_audio_id)
        self.window.set_gamesync_entries(self._build_gamesync_entries())
        self.window.set_gamesync_definitions(self.project.game_parameters, self.project.state_groups, self.project.switch_groups)
        self._sync_preview_gamesync_resolution()
        self.window.set_project_settings(self.project.settings)
        self._sync_preview_bus_mixer()
        self.sync_preview_bus_editor()
        self.window.set_event_details(self.current_event)
        popup_event_id = self.window.current_audio_bindings_popup_event_id()
        self.window.refresh_audio_bindings_popup(self.project.events.get(popup_event_id) if popup_event_id else None)
        self._sync_source_binding_selection_to_clip_table()
        self._sync_preview_transport_state()
        self.window.set_project_title(self.project.name, self.project.file_path)
        self.window.set_history_actions_enabled(self.history.can_undo(), self.history.can_redo())
        self.window.set_dirty_state(self.is_dirty)
        self._update_object_context()
        self._sync_build_selection_context()
        self.window.apply_navigation_state(navigation_state)
        self._sync_browser_action_affordances()
        self._publish_diagnostic_snapshot()

    def _build_source_browser_entries(self) -> list[dict[str, object]]:
        event_ids_by_audio: dict[str, set[str]] = {}
        for event in self.project.events.values():
            event_ids_by_audio.setdefault(event.audio_id, set()).add(event.id)

        references_by_source: dict[str, dict[str, set[str]]] = {}
        for audio_id, audio in self.project.audio_objects.items():
            linked_event_ids = event_ids_by_audio.get(audio_id, set())
            for clip in audio.clips:
                source_path = str(clip.source_path).strip()
                if not source_path:
                    continue
                bucket = references_by_source.setdefault(
                    source_path,
                    {
                        "audio_ids": set(),
                        "event_ids": set(),
                        "asset_keys": set(),
                    },
                )
                bucket["audio_ids"].add(audio_id)
                bucket["event_ids"].update(linked_event_ids)
                if clip.asset_key:
                    bucket["asset_keys"].add(str(clip.asset_key))

        all_sources = sorted({*self.project.asset_registry.keys(), *references_by_source.keys()}, key=lambda value: value.casefold())
        entries: list[dict[str, object]] = []
        for source_path in all_sources:
            source_text = str(source_path).strip()
            if not source_text:
                continue
            reference_bucket = references_by_source.get(source_text, {"event_ids": set(), "asset_keys": set()})
            try:
                is_missing = not Path(source_text).exists()
            except OSError:
                is_missing = True
            audio_ids = sorted(reference_bucket.get("audio_ids", set()))
            event_ids = sorted(reference_bucket["event_ids"])
            asset_keys = sorted(reference_bucket["asset_keys"])
            entries.append(
                {
                    "source_path": source_text,
                    "audio_ids": audio_ids,
                    "event_ids": event_ids,
                    "asset_keys": asset_keys,
                    "reference_count": len(audio_ids),
                    "missing": is_missing,
                    "unreferenced": len(audio_ids) == 0,
                }
            )
        return entries

    def _build_audio_browser_entries(self) -> list[dict[str, object]]:
        event_ids_by_audio: dict[str, list[str]] = {}
        for event in self.project.events.values():
            event_ids_by_audio.setdefault(event.audio_id, []).append(event.id)

        entries: list[dict[str, object]] = []
        for audio_id, audio in sorted(self.project.audio_objects.items(), key=lambda item: (item[1].display_name.casefold(), item[0].casefold())):
            event_ids = sorted(event_ids_by_audio.get(audio_id, []))
            entries.append(
                {
                    "audio_id": audio_id,
                    "display_name": audio.display_name,
                    "play_mode": audio.play_mode,
                    "bus": audio.bus,
                    "clip_count": len(audio.clips),
                    "event_ids": event_ids,
                    "event_count": len(event_ids),
                }
            )
        return entries

    def _make_unique_audio_id(self, base_id: str, reserved_audio_ids: set[str] | None = None) -> str:
        blocked_ids = set(self.project.audio_objects.keys())
        if reserved_audio_ids is not None:
            blocked_ids.update(reserved_audio_ids)
        candidate = base_id
        index = 1
        while candidate in blocked_ids:
            index += 1
            candidate = f"{base_id}_{index}"
        return candidate

    def _normalize_audio_binding_states(self, audio: AudioObjectModel) -> None:
        reference_event = next((event for event in self.project.events.values() if event.audio_id == audio.id), None)
        if reference_event is None:
            reference_event = EventModel(id=f"{audio.id}_binding", display_name=audio.display_name, audio=audio, audio_id=audio.id)
        normalize_event_binding_states(reference_event)

    def _build_gamesync_entries(self) -> dict[str, list[dict[str, object]]]:
        return {
            "game_parameters": [
                {
                    "name": parameter.name,
                    "summary": f"默认 {parameter.default_value:.2f} | 范围 {parameter.min_value:.2f} - {parameter.max_value:.2f}",
                    "detail": parameter.notes.strip() or "连续 Game Parameter，可用于 phase3 的 RTPC 绑定。",
                }
                for parameter in self.project.game_parameters
            ],
            "state_groups": [
                {
                    "name": group.name,
                    "summary": f"默认 {group.default_state or '-'} | 状态 {len(group.states)} 个",
                    "detail": group.notes.strip() or ("、".join(group.states) if group.states else "当前还没有可用 State。"),
                }
                for group in self.project.state_groups
            ],
            "switch_groups": [
                {
                    "name": group.name,
                    "summary": (
                        f"默认 {group.default_switch or '-'} | Switch {len(group.switches)} 个"
                        + (f" | RTPC 映射 {group.mapped_game_parameter}" if group.use_game_parameter and group.mapped_game_parameter else "")
                    ),
                    "detail": group.notes.strip() or ("、".join(group.switches) if group.switches else "当前还没有可用 Switch。"),
                }
                for group in self.project.switch_groups
            ],
        }

    def _reset_diagnostic_snapshot(self) -> None:
        self._diagnostic_snapshot = DiagnosticSnapshot()

    def _current_navigation_target(self) -> tuple[str, str]:
        if self.selected_event_id is not None and self.selected_event_id in self.project.events:
            return "event", self.selected_event_id
        if self.selected_folder_id is not None and self.selected_folder_id in self.project.folders:
            return "folder", self.selected_folder_id
        return "", ""

    def _current_build_target_summary(self) -> tuple[str, str, str, str]:
        target_type, target_id = self._current_navigation_target()
        _, summary, detail = self._resolve_build_selection_context()
        selection_label = summary.replace("当前范围：", "", 1).strip() or "整个工程"
        return target_type, target_id, selection_label, detail

    def _set_validation_diagnostic_summary(self, issues: list[ValidationIssue]) -> None:
        section = self._diagnostic_snapshot.section("validation")
        if not issues:
            section.update(
                summary="校验通过，没有发现问题。",
                status="success",
                metadata={"issue_count": 0, "error_count": 0, "warning_count": 0, "info_count": 0},
            )
            return
        error_count = sum(1 for issue in issues if issue.severity == "Error")
        warning_count = sum(1 for issue in issues if issue.severity == "Warning")
        info_count = sum(1 for issue in issues if issue.severity == "Info")
        first_issue = issues[0]
        target = first_issue.target.strip() or "-"
        section.update(
            summary=f"{first_issue.severity} | {target} | {first_issue.code} | {first_issue.message}",
            detail=(
                f"目标：{target} | 级别：{first_issue.severity} | 代码：{first_issue.code} | "
                f"错误 {error_count} | 警告 {warning_count} | 信息 {info_count}\n\n{first_issue.message}"
            ),
            status={"Error": "error", "Warning": "warning", "Info": "info"}.get(first_issue.severity, "info"),
            target_type="auto",
            target_id=target,
            metadata={
                "issue_count": len(issues),
                "error_count": error_count,
                "warning_count": warning_count,
                "info_count": info_count,
                "first_issue_code": first_issue.code,
            },
        )

    def _set_build_diagnostic_summary(
        self,
        summary: str,
        detail: str | None = None,
        *,
        status: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None:
        section = self._diagnostic_snapshot.section("build")
        normalized = (detail or summary).strip()
        target_type, target_id, selection_label, selection_detail = self._current_build_target_summary()
        section.update(
            summary=normalized or DIAGNOSTIC_SECTION_DEFAULTS["build"],
            detail=detail or summary,
            status=status,
            target_type=target_type,
            target_id=target_id,
            metadata={
                "summary": summary,
                "detail": detail or summary,
                "selection_label": selection_label,
                "selection_detail": selection_detail,
                **(metadata or {}),
            },
        )

    def _set_loudness_diagnostic_summary(self, report: dict[str, object]) -> None:
        section = self._diagnostic_snapshot.section("loudness")
        rows = report.get("rows") or []
        flagged_events = int(report.get("flagged_events") or 0)
        analyzed_events = int(report.get("analyzed_events") or 0)
        if not rows:
            section.update(
                summary="没有可分析的事件或片段。",
                status="info",
                metadata={"analyzed_events": analyzed_events, "flagged_events": flagged_events},
            )
            return
        first_row = rows[0]
        findings = first_row.get("findings") or []
        detail = "；".join(findings) if findings else "未发现超标项"
        section.update(
            summary=f"事件 {first_row['event_id']} | {detail}",
            detail=(
                f"事件 {first_row['event_id']} | 片段 {first_row['clip_id']} | 资源 {first_row['asset_key']} | "
                f"Integrated {first_row['integrated_lufs']:.1f} LUFS | "
                f"Momentary Max {first_row['momentary_max_lufs']:.1f} LUFS | True Peak {first_row['true_peak_db']:.1f} dBTP"
            ),
            status="warning" if flagged_events else "success",
            target_type="event",
            target_id=str(first_row["event_id"]),
            metadata={
                "analyzed_events": analyzed_events,
                "flagged_events": flagged_events,
                "clip_id": first_row["clip_id"],
                "asset_key": first_row["asset_key"],
            },
        )

    def _set_bus_diagnostic_summary(self) -> None:
        section = self._diagnostic_snapshot.section("bus")
        current_project_bus = self.window.current_project_bus_name() or self.project.settings.default_bus or "-"
        current_event_bus = self.current_event.bus if self.current_event is not None else current_project_bus
        default_bus = self.project.settings.default_bus or "-"
        summary = (
            f"Bus 视图 {current_project_bus} | {WWISE_OUTPUT_BUS_LABEL} {current_event_bus} | "
            f"{WWISE_DEFAULT_BUS_LABEL} {default_bus}"
        )
        section.update(
            summary=summary,
            detail=(
                f"当前 Bus 视图 {current_project_bus} | 当前对象输出 {current_event_bus} | 默认 Bus {default_bus} | "
                f"总线数 {len(self.project.settings.buses)}"
            ),
            status="info",
            target_type="event" if self.current_event is not None else ("folder" if self.selected_folder_id else ""),
            target_id=self.current_event.id if self.current_event is not None else (self.selected_folder_id or ""),
            metadata={
                "current_project_bus": current_project_bus,
                "current_event_bus": current_event_bus,
                "default_bus": default_bus,
                "bus_count": len(self.project.settings.buses),
            },
        )

    def _build_diagnostic_section_items(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for section_name in DIAGNOSTIC_PRIORITY_ORDER:
            section = self._diagnostic_snapshot.section(section_name)
            items.append(
                {
                    "title": f"{DIAGNOSTIC_SECTION_TITLES[section_name]} | {section.summary}",
                    "detail": section.detail,
                    "target_type": section.target_type,
                    "target_id": section.target_id,
                    "severity": section.status,
                    "section": section_name,
                }
            )
        return items

    def _build_build_profile_items(self) -> list[dict[str, object]]:
        section = self._diagnostic_snapshot.section("build")
        metadata = section.metadata
        target_type, target_id, selection_label, selection_detail = self._current_build_target_summary()
        requested_scope_label = str(metadata.get("requested_scope_label") or "").strip()
        effective_scope_label = str(metadata.get("effective_scope_label") or "").strip()
        requested_scope = str(metadata.get("requested_scope") or "").strip()
        effective_scope = str(metadata.get("effective_scope") or "").strip()
        requested_scope_label = requested_scope_label or self._build_scope_label(requested_scope or self.window.current_build_scope())
        effective_scope_label = effective_scope_label or (self._build_scope_label(effective_scope) if effective_scope else requested_scope_label)
        rebuilt_asset_count = int(metadata.get("rebuilt_asset_count", -1))
        reused_asset_count = int(metadata.get("reused_asset_count", -1))
        removed_asset_count = int(metadata.get("removed_asset_count", -1))
        out_of_scope_dirty_count = int(metadata.get("out_of_scope_dirty_count", -1))
        export_root = str(metadata.get("export_root") or self.project.settings.export_root)
        data_file = str(metadata.get("data_file") or "").strip()
        manifest_file = str(metadata.get("manifest_file") or "").strip()

        asset_detail = "等待预览导出差异或执行构建后，这里会显示重建、复用和移除画像。"
        if rebuilt_asset_count >= 0 or reused_asset_count >= 0 or removed_asset_count >= 0:
            asset_detail = (
                f"重建 {max(rebuilt_asset_count, 0)} | 复用 {max(reused_asset_count, 0)} | "
                f"移除 {max(removed_asset_count, 0)}"
            )
            if out_of_scope_dirty_count >= 0:
                asset_detail = f"{asset_detail} | 选区外附带脏资源 {max(out_of_scope_dirty_count, 0)}"

        delivery_detail = f"导出目录：{export_root} | 运行时格式：{self.project.settings.runtime_audio_format}"
        if data_file or manifest_file:
            delivery_detail = f"{delivery_detail} | 数据：{data_file or '-'} | 清单：{manifest_file or '-'}"

        return [
            {
                "title": f"状态 | {section.summary}",
                "detail": section.detail,
                "severity": section.status,
                "target_type": section.target_type,
                "target_id": section.target_id,
            },
            {
                "title": f"范围 | 请求 {requested_scope_label} | 实际 {effective_scope_label}",
                "detail": f"当前模式画像以最近一次构建状态为准；若未构建，则显示当前选中的构建范围。",
                "severity": "info",
            },
            {
                "title": f"目标 | {str(metadata.get('selection_label') or selection_label)}",
                "detail": str(metadata.get("selection_detail") or selection_detail),
                "severity": "info",
                "target_type": target_type,
                "target_id": target_id,
            },
            {
                "title": f"资源 | {asset_detail}",
                "detail": asset_detail,
                "severity": section.status if rebuilt_asset_count >= 0 else "info",
            },
            {
                "title": f"交付 | {self.project.settings.source_audio_format} -> {self.project.settings.runtime_audio_format}",
                "detail": delivery_detail,
                "severity": "success" if data_file or manifest_file else "info",
            },
        ]

    def _compose_diagnostic_summary(self) -> str:
        for section_name in DIAGNOSTIC_PRIORITY_ORDER:
            section = self._diagnostic_snapshot.section(section_name)
            if section.summary != section.default_summary:
                return section.summary
        return "诊断概览已接入结果中心；这里统一汇总日志、校验、构建、响度和 Bus 状态。"

    @Slot(str)
    def _handle_log_appended(self, message: str) -> None:
        normalized = message.strip()
        self._diagnostic_snapshot.section("log").update(
            summary=f"最近日志：{normalized}" if normalized else DIAGNOSTIC_SECTION_DEFAULTS["log"],
            detail=normalized or DIAGNOSTIC_SECTION_DEFAULTS["log"],
            status="info" if normalized else "idle",
            metadata={"message": normalized},
        )
        self._publish_diagnostic_snapshot()

    @Slot(object)
    def _handle_validation_report_updated(self, issues: object) -> None:
        self._set_validation_diagnostic_summary(list(issues or []))
        self._publish_diagnostic_snapshot()

    @Slot(str, str)
    def _handle_build_status_updated(self, summary: str, detail: str) -> None:
        self._set_build_diagnostic_summary(summary, detail)
        self._publish_diagnostic_snapshot()

    @Slot(str)
    def _handle_loudness_report_updated(self, summary_text: str) -> None:
        normalized = summary_text.strip()
        self._diagnostic_snapshot.section("loudness").update(
            summary=normalized or DIAGNOSTIC_SECTION_DEFAULTS["loudness"],
            detail=normalized or DIAGNOSTIC_SECTION_DEFAULTS["loudness"],
            status="success" if normalized else "idle",
            metadata={"summary_text": normalized},
        )
        self._publish_diagnostic_snapshot()

    @Slot()
    def _publish_diagnostic_snapshot(self) -> None:
        self._set_bus_diagnostic_summary()
        self._diagnostic_snapshot.summary = self._compose_diagnostic_summary()
        payload = self._diagnostic_snapshot.as_payload()
        payload["sections"] = self._build_diagnostic_section_items()
        payload["build_profile"] = self._build_build_profile_items()
        self.window.set_diagnostic_snapshot(payload)

    @property
    def current_event(self) -> EventModel | None:
        if self.selected_event_id is None:
            return None
        return self.project.events.get(self.selected_event_id)

    @property
    def current_audio(self):
        if self.selected_audio_id is None:
            return None
        return self.project.audio_objects.get(self.selected_audio_id)

    def _event_ids_for_audio(self, audio_id: str) -> list[str]:
        return self.project.event_ids_for_audio(audio_id)

    def _audio_ids_for_source(self, source_path: str) -> list[str]:
        return self.project.audio_ids_for_source(source_path)

    def _selected_audio_browser_id(self) -> str | None:
        entry = self.window.current_audio_browser_entry()
        if entry is not None:
            audio_id = str(entry.get("audio_id", "")).strip()
            if audio_id:
                return audio_id
        if self.selected_audio_id in self.project.audio_objects:
            return self.selected_audio_id
        return None

    def _selected_source_paths(self) -> list[str]:
        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        for raw_path in self.window.source_tree.selected_source_paths():
            source_path = str(raw_path).strip()
            if not source_path:
                continue
            lookup_key = source_path.casefold()
            if lookup_key in seen_paths:
                continue
            seen_paths.add(lookup_key)
            normalized_paths.append(source_path)
        return normalized_paths

    @property
    def current_events(self) -> list[EventModel]:
        return [self.project.events[event_id] for event_id in self.selected_event_ids if event_id in self.project.events]

    def _resolved_source_binding_pairs(self, tokens: list[str] | None = None) -> list[tuple[str, str]]:
        resolved_pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for token in tokens or self.selected_source_binding_tokens:
            event_id, clip_id = decode_source_binding_token(token)
            if event_id not in self.project.events or not clip_id:
                continue
            if not any(clip.id == clip_id for clip in self.project.events[event_id].clips):
                continue
            pair = (event_id, clip_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            resolved_pairs.append(pair)
        return resolved_pairs

    def _sync_source_binding_selection_to_clip_table(self) -> None:
        if len(self.selected_event_ids) != 1 or self.selected_event_id is None:
            return
        clip_ids = [clip_id for event_id, clip_id in self._resolved_source_binding_pairs() if event_id == self.selected_event_id]
        if clip_ids:
            self.window.select_clip_ids(clip_ids)

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
        self._reset_diagnostic_snapshot()
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
        self._reset_diagnostic_snapshot()
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

    def _resolve_project_relative_path(self, raw_path: str) -> Path:
        normalized = str(raw_path).strip() or str(DEFAULT_EXPORT_ROOT)
        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate
        if self.project.file_path:
            return (Path(self.project.file_path).resolve().parent / candidate).resolve(strict=False)
        return (Path.cwd() / candidate).resolve(strict=False)

    def select_node(self, node_type: str, node_id: str) -> None:
        if node_type == "source_binding":
            event_id, clip_id = decode_source_binding_token(node_id)
            if event_id not in self.project.events or not any(clip.id == clip_id for clip in self.project.events[event_id].clips):
                return
            self.selected_event_id = event_id
            self.selected_event_ids = [event_id]
            self.selected_audio_id = self.project.events[event_id].audio_id
            self.selected_folder_id = self.project.find_event_folder_id(event_id)
            self.selected_source_binding_tokens = [encode_source_binding_token(event_id, clip_id)]
        elif node_type == "event":
            self.selected_event_id = node_id
            self.selected_event_ids = [node_id]
            if node_id in self.project.events:
                self.selected_audio_id = self.project.events[node_id].audio_id
            self.selected_folder_id = self.project.find_event_folder_id(node_id)
            self.selected_source_binding_tokens = []
        else:
            self.selected_folder_id = node_id
            self.selected_event_id = None
            self.selected_event_ids = []
            self.selected_audio_id = None
            self.selected_source_binding_tokens = []
        if node_type in {"source_binding", "event", "folder"}:
            self.window.explorer_tabs.setCurrentIndex(3)
        if node_type in {"event", "folder"}:
            self.window.tree.select_node(node_type, node_id, emit_signal=False)
        self.window.audio_tree.select_audio_id(self.selected_audio_id, emit_signal=False)
        self.window.set_event_details(self.current_event if len(self.selected_event_ids) <= 1 else None)
        self._sync_source_binding_selection_to_clip_table()
        self._sync_multi_selection_affordances()
        self._update_object_context()
        self._sync_build_selection_context()
        self._sync_browser_action_affordances()

    def select_nodes(self, nodes: list[tuple[str, str]]) -> None:
        event_ids = [node_id for node_type, node_id in nodes if node_type == "event" and node_id in self.project.events]
        binding_pairs = self._resolved_source_binding_pairs([node_id for node_type, node_id in nodes if node_type == "source_binding"])
        binding_event_ids = [event_id for event_id, _clip_id in binding_pairs]
        for event_id in binding_event_ids:
            if event_id not in event_ids:
                event_ids.append(event_id)
        if event_ids:
            self.selected_event_ids = event_ids
            current_event = self.current_event
            current_event_id = current_event.id if current_event is not None else None
            self.selected_event_id = current_event_id if current_event_id in event_ids else event_ids[0]
            self.selected_audio_id = self.project.events[self.selected_event_id].audio_id if self.selected_event_id in self.project.events else None
            self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id)
            self.selected_source_binding_tokens = [encode_source_binding_token(event_id, clip_id) for event_id, clip_id in binding_pairs]
            self.window.explorer_tabs.setCurrentIndex(3)
        elif nodes:
            folder_ids = [node_id for node_type, node_id in nodes if node_type == "folder" and node_id in self.project.folders]
            self.selected_event_ids = []
            self.selected_event_id = None
            self.selected_audio_id = None
            self.selected_source_binding_tokens = []
            if folder_ids:
                self.selected_folder_id = folder_ids[0]
                self.window.explorer_tabs.setCurrentIndex(3)
        self.window.set_event_details(self.current_event if len(self.selected_event_ids) <= 1 else None)
        self._sync_source_binding_selection_to_clip_table()
        self._sync_multi_selection_affordances()
        self._update_object_context()
        self._sync_build_selection_context()
        self._sync_browser_action_affordances()

    def navigate_to_parent(self) -> None:
        if self.selected_event_id is not None:
            folder_id = self.project.find_event_folder_id(self.selected_event_id)
            if folder_id is None:
                return
            self.selected_folder_id = folder_id
            self.selected_event_id = None
            self.selected_event_ids = []
            self.selected_audio_id = None
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
        self.selected_audio_id = None
        self._refresh_ui()

    def select_audio(self, audio_id: str) -> None:
        if audio_id not in self.project.audio_objects:
            return
        self.selected_audio_id = audio_id
        event_ids = self._event_ids_for_audio(audio_id)
        if event_ids:
            self.selected_event_id = event_ids[0]
            self.selected_event_ids = [self.selected_event_id]
            self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id)
        else:
            self.selected_event_id = None
            self.selected_event_ids = []
        self.selected_source_binding_tokens = []
        self.window.audio_tree.select_audio_id(audio_id, emit_signal=False)
        self.window.set_event_details(self.current_event if len(self.selected_event_ids) <= 1 else None)
        self._sync_source_binding_selection_to_clip_table()
        self._sync_multi_selection_affordances()
        self._update_object_context()
        self._sync_build_selection_context()
        self._sync_browser_action_affordances()

    def navigate_to_event_audio(self, event_id: str) -> None:
        event = self.project.events.get(event_id)
        if event is None:
            return
        self.select_audio(event.audio_id)
        self.window.focus_current_audio_browser()

    def update_current_event_from_form(self) -> None:
        event = self.current_event
        if event is None:
            return

        form_data = self.window.current_event_identity_form_data()

        def mutate() -> bool:
            current_event = self.current_event
            if current_event is None:
                return False
            changed = False

            new_id_value = str(form_data["id"])
            if new_id_value and new_id_value != current_event.id:
                self.project.rename_event(current_event.id, new_id_value)
                self.selected_event_id = new_id_value
                self.selected_event_ids = [new_id_value if event_id == current_event.id else event_id for event_id in self.selected_event_ids or [current_event.id]]
                current_event = self.project.events[new_id_value]
                self.selected_audio_id = current_event.audio_id
                changed = True

            updated_display_name = str(form_data["display_name"])
            if current_event.display_name != updated_display_name:
                current_event.display_name = updated_display_name
                changed = True
            updated_steal_policy = str(form_data["steal_policy"])
            if current_event.steal_policy != updated_steal_policy:
                current_event.steal_policy = updated_steal_policy
                changed = True
            updated_cooldown_seconds = float(form_data["cooldown_seconds"])
            if current_event.cooldown_seconds != updated_cooldown_seconds:
                current_event.cooldown_seconds = updated_cooldown_seconds
                changed = True
            updated_max_instances = int(form_data["max_instances"])
            if current_event.max_instances != updated_max_instances:
                current_event.max_instances = updated_max_instances
                changed = True
            updated_notes = str(form_data["notes"])
            if current_event.notes != updated_notes:
                current_event.notes = updated_notes
                changed = True
            if changed:
                self.project.touch()
            return changed

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

    def update_current_audio_from_form(self) -> None:
        event = self.current_event
        if event is None:
            return

        form_data = self.window.current_audio_form_data()
        rtpc_bindings = [RtpcBindingModel(**binding) for binding in form_data.get("rtpc_bindings", [])]
        state_overrides = [StateOverrideModel(**override) for override in form_data.get("state_overrides", [])]
        switch_variants = [SwitchVariantModel(**variant) for variant in form_data.get("switch_variants", [])]

        def mutate() -> bool:
            current_event = self.current_event
            if current_event is None:
                return False
            current_audio = current_event.audio
            previous_play_mode = current_audio.play_mode
            changed = False

            updated_bus = str(form_data["bus"])
            if current_audio.bus != updated_bus:
                current_audio.bus = updated_bus
                changed = True
            updated_play_mode = str(form_data["play_mode"])
            if current_audio.play_mode != updated_play_mode:
                current_audio.play_mode = updated_play_mode
                changed = True
            updated_load_policy = str(form_data["load_policy"])
            if current_audio.load_policy != updated_load_policy:
                current_audio.load_policy = updated_load_policy
                changed = True
            updated_volume_db = float(form_data["volume_db"])
            if current_audio.volume_db != updated_volume_db:
                current_audio.volume_db = updated_volume_db
                changed = True
            updated_volume_rand_min_db = float(form_data["volume_rand_min_db"])
            if current_audio.volume_rand_min_db != updated_volume_rand_min_db:
                current_audio.volume_rand_min_db = updated_volume_rand_min_db
                changed = True
            updated_volume_rand_max_db = float(form_data["volume_rand_max_db"])
            if current_audio.volume_rand_max_db != updated_volume_rand_max_db:
                current_audio.volume_rand_max_db = updated_volume_rand_max_db
                changed = True
            updated_pitch_cents = int(form_data["pitch_cents"])
            if current_audio.pitch_cents != updated_pitch_cents:
                current_audio.pitch_cents = updated_pitch_cents
                changed = True
            updated_pitch_rand_min_cents = int(form_data["pitch_rand_min_cents"])
            if current_audio.pitch_rand_min_cents != updated_pitch_rand_min_cents:
                current_audio.pitch_rand_min_cents = updated_pitch_rand_min_cents
                changed = True
            updated_pitch_rand_max_cents = int(form_data["pitch_rand_max_cents"])
            if current_audio.pitch_rand_max_cents != updated_pitch_rand_max_cents:
                current_audio.pitch_rand_max_cents = updated_pitch_rand_max_cents
                changed = True
            updated_combo_pitch_step_cents = int(form_data["combo_pitch_step_cents"])
            if current_audio.combo_pitch_step_cents != updated_combo_pitch_step_cents:
                current_audio.combo_pitch_step_cents = updated_combo_pitch_step_cents
                changed = True
            updated_combo_reset_seconds = float(form_data["combo_reset_seconds"])
            if current_audio.combo_reset_seconds != updated_combo_reset_seconds:
                current_audio.combo_reset_seconds = updated_combo_reset_seconds
                changed = True
            updated_combo_max_step = int(form_data["combo_max_step"])
            if current_audio.combo_max_step != updated_combo_max_step:
                current_audio.combo_max_step = updated_combo_max_step
                changed = True
            updated_avoid_repeat = bool(form_data["avoid_immediate_repeat"])
            if current_audio.avoid_immediate_repeat != updated_avoid_repeat:
                current_audio.avoid_immediate_repeat = updated_avoid_repeat
                changed = True
            event_tags = [str(tag) for tag in form_data["tags"]]
            for clip in current_event.clips:
                if clip.tags != list(event_tags):
                    clip.tags = list(event_tags)
                    changed = True
            if current_audio.rtpc_bindings != rtpc_bindings:
                current_audio.rtpc_bindings = rtpc_bindings
                changed = True
            if current_audio.state_overrides != state_overrides:
                current_audio.state_overrides = state_overrides
                changed = True
            if current_audio.switch_variants != switch_variants:
                current_audio.switch_variants = switch_variants
                changed = True
            if previous_play_mode == "OneShot" and current_audio.play_mode != "OneShot":
                for clip in current_event.clips:
                    if clip.enabled:
                        clip.active = True
                        changed = True
            normalize_event_binding_states(current_event)
            changed = self._merge_gamesync_definitions(
                rtpc_bindings=current_audio.rtpc_bindings,
                state_overrides=current_audio.state_overrides,
                switch_variants=current_audio.switch_variants,
            ) or changed
            if changed:
                self.project.touch()
            return changed

        changed = self._apply_mutation(
            "Update Audio Properties",
            mutate,
            merge_key=f"audio-properties:{self.selected_audio_id}",
        )
        if changed:
            self.window.append_log("已更新 Audio 属性。")
            navigation_state = self.window.navigation_state()
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def update_project_settings_from_form(self) -> None:
        form_data = self.window.current_project_settings_form_data()
        change_source = self.window.consume_project_settings_change_source()
        source_audio_format = str(form_data["source_audio_format"])
        runtime_audio_format = str(form_data["runtime_audio_format"])
        auto_assign_bus_by_name = bool(form_data.get("auto_assign_bus_by_name", True))
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
                rtpc_bindings=[RtpcBindingModel(**binding) for binding in bus_config.get("rtpc_bindings", [])],
                state_overrides=[StateOverrideModel(**override) for override in bus_config.get("state_overrides", [])],
            )
            for bus_config in form_data["bus_configs"]
        ]
        default_bus = str(form_data["default_bus"])
        export_root = str(form_data["export_root"])
        if change_source == "project-bus-selection":
            source_audio_format = self.project.settings.source_audio_format
            runtime_audio_format = self.project.settings.runtime_audio_format
            auto_assign_bus_by_name = self.project.settings.auto_assign_bus_by_name
            default_bus = self.project.settings.default_bus
            export_root = self.project.settings.export_root
        if not self.window.export_root_edit.isModified():
            export_root = self.project.settings.export_root
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
            if self.project.settings.auto_assign_bus_by_name != auto_assign_bus_by_name:
                self.project.settings.auto_assign_bus_by_name = auto_assign_bus_by_name
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
            changed = self._merge_gamesync_definitions(
                rtpc_bindings=[binding for config in self.project.settings.bus_configs for binding in config.rtpc_bindings],
                state_overrides=[override for config in self.project.settings.bus_configs for override in config.state_overrides],
            ) or changed
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Update Project Settings", mutate, merge_key="project-settings"):
            self.window.append_log("已更新工程设置。")
            navigation_state = self.window.navigation_state()
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def update_gamesync_from_form(self) -> None:
        form_data = self.window.current_gamesync_form_data()
        game_parameters = [GameParameterModel(**payload) for payload in form_data.get("game_parameters", [])]
        state_groups = [StateGroupModel(**payload) for payload in form_data.get("state_groups", [])]
        switch_groups = [SwitchGroupModel(**payload) for payload in form_data.get("switch_groups", [])]

        def mutate() -> bool:
            changed = False
            if self.project.game_parameters != game_parameters:
                self.project.game_parameters = game_parameters
                changed = True
            if self.project.state_groups != state_groups:
                self.project.state_groups = state_groups
                changed = True
            if self.project.switch_groups != switch_groups:
                self.project.switch_groups = switch_groups
                changed = True
            if changed:
                self.project.touch()
            return changed

        if self._apply_mutation("Update GameSync Definitions", mutate, merge_key="gamesync-definitions"):
            self.window.append_log("已更新 GameSync 定义。")
            navigation_state = self.window.navigation_state()
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def _merge_gamesync_definitions(
        self,
        *,
        rtpc_bindings: Iterable[RtpcBindingModel] = (),
        state_overrides: Iterable[StateOverrideModel] = (),
        switch_variants: Iterable[SwitchVariantModel] = (),
    ) -> bool:
        changed = False

        for binding in rtpc_bindings:
            parameter_name = binding.parameter_name.strip()
            if not parameter_name or self._find_game_parameter(parameter_name) is not None:
                continue
            self.project.game_parameters.append(GameParameterModel(name=parameter_name))
            changed = True

        for override in state_overrides:
            group_name = override.group_name.strip()
            state_name = override.state_name.strip()
            if not group_name:
                continue
            existing_group = self._find_state_group(group_name)
            if existing_group is None:
                self.project.state_groups.append(
                    StateGroupModel(
                        name=group_name,
                        states=[state_name] if state_name else [],
                        default_state=state_name,
                    )
                )
                changed = True
                continue
            if state_name and state_name.casefold() not in {value.casefold() for value in existing_group.states}:
                existing_group.states.append(state_name)
                if not existing_group.default_state:
                    existing_group.default_state = state_name
                changed = True

        for variant in switch_variants:
            group_name = variant.group_name.strip()
            switch_name = variant.switch_name.strip()
            if not group_name:
                continue
            existing_group = self._find_switch_group(group_name)
            if existing_group is None:
                self.project.switch_groups.append(
                    SwitchGroupModel(
                        name=group_name,
                        switches=[switch_name] if switch_name else [],
                        default_switch=switch_name,
                    )
                )
                changed = True
                continue
            if switch_name and switch_name.casefold() not in {value.casefold() for value in existing_group.switches}:
                existing_group.switches.append(switch_name)
                if not existing_group.default_switch:
                    existing_group.default_switch = switch_name
                changed = True

        return changed

    def _find_game_parameter(self, name: str) -> GameParameterModel | None:
        normalized = name.strip().casefold()
        for parameter in self.project.game_parameters:
            if parameter.name.casefold() == normalized:
                return parameter
        return None

    def _find_state_group(self, name: str) -> StateGroupModel | None:
        normalized = name.strip().casefold()
        for group in self.project.state_groups:
            if group.name.casefold() == normalized:
                return group
        return None

    def _find_switch_group(self, name: str) -> SwitchGroupModel | None:
        normalized = name.strip().casefold()
        for group in self.project.switch_groups:
            if group.name.casefold() == normalized:
                return group
        return None

    def _current_preview_gamesync_context(self) -> PreviewGameSyncContext:
        payload = self.window.current_preview_gamesync_context_data()
        return PreviewGameSyncContext(
            global_game_parameters=payload.get("global_parameters", {}),
            emitter_game_parameters=payload.get("emitter_parameters", {}),
            states=payload.get("states", {}),
            switches=payload.get("switches", {}),
        )

    def _sync_preview_gamesync_resolution(self) -> None:
        payload = self.window.current_preview_gamesync_context_data()
        snapshot = self.preview_service.build_preview_resolution_snapshot(
            PreviewGameSyncContext(
                global_game_parameters=payload.get("global_parameters", {}),
                emitter_game_parameters=payload.get("emitter_parameters", {}),
                states=payload.get("states", {}),
                switches=payload.get("switches", {}),
            ),
            game_parameters=self.project.game_parameters,
            state_groups=self.project.state_groups,
            switch_groups=self.project.switch_groups,
            selected_parameter_name=str(payload.get("selected_parameter_name", "")),
            selected_parameter_scope=str(payload.get("selected_parameter_scope", "Emitter")),
            selected_state_group=str(payload.get("selected_state_group", "")),
            selected_switch_group=str(payload.get("selected_switch_group", "")),
        )
        self.window.set_preview_gamesync_resolution_snapshot(snapshot)

    def _resolve_preview_event_mix(self, event: EventModel) -> tuple[float, int, bool]:
        return self.preview_service.resolve_mix_adjustment(
            event.rtpc_bindings,
            event.state_overrides,
            base_volume_db=event.volume_db,
            base_pitch_cents=event.pitch_cents,
            preview_gamesync=self._current_preview_gamesync_context(),
            game_parameters=self.project.game_parameters,
            state_groups=self.project.state_groups,
            switch_groups=self.project.switch_groups,
        )

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
        self._refresh_recent_preview_session()
        self._sync_preview_transport_state()
        self.window.append_log(
            f"{WWISE_TRANSPORT_TITLE} 已更新：{state.name} 音量={state.volume_linear * 100:.0f}% 静音={'是' if state.is_muted else '否'}"
        )

    def update_preview_gamesync_from_form(self) -> None:
        self._sync_preview_gamesync_resolution()
        event = self.current_event
        if event is None:
            return
        session = self._current_audition_session()
        if session is not None and session.event_id == event.id:
            self.preview_current_event(silent_log=True)

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
            self.window.append_log(f"已将 {WWISE_DEFAULT_BUS_LABEL} “{default_bus}”应用到所有事件。")
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
        active_page = self.window.current_explorer_page_key()
        if active_page == "audios":
            self.rename_selected_audio()
            return
        if active_page == "sources":
            self.window.show_context_feedback("源音频路径重命名请在外部文件系统中处理；浏览器内暂不提供路径重命名。")
            return

        binding_pairs = self._resolved_source_binding_pairs()
        if binding_pairs:
            affected_event_ids = list(dict.fromkeys(event_id for event_id, _clip_id in binding_pairs))
            if len(affected_event_ids) != 1:
                self.window.append_log("跨事件 Source Binding 暂不支持批量重命名。")
                return
            event_id = affected_event_ids[0]
            self.selected_event_id = event_id
            self.selected_event_ids = [event_id]
            self.selected_folder_id = self.project.find_event_folder_id(event_id)
            self.selected_source_binding_tokens = [encode_source_binding_token(bound_event_id, clip_id) for bound_event_id, clip_id in binding_pairs]
            self.window.set_event_details(self.current_event)
            self._sync_source_binding_selection_to_clip_table()
            result = self.window.ask_batch_rename()
            if result is None:
                return
            self.batch_rename_clips(result[0], result[1])
            return

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
        active_page = self.window.current_explorer_page_key()
        if active_page == "audios":
            self.delete_selected_audio()
            return
        if active_page == "sources":
            self.delete_selected_sources()
            return

        binding_pairs = self._resolved_source_binding_pairs()
        if binding_pairs:
            label = f"确认删除所选 {len(binding_pairs)} 个 Source Binding？"
            if not self.window.confirm_delete(label):
                return
            remaining_event_ids = list(dict.fromkeys(event_id for event_id, _clip_id in binding_pairs))

            def mutate() -> bool:
                for event_id, clip_id in binding_pairs:
                    self.project.remove_clip_from_event(event_id, clip_id)
                self.selected_source_binding_tokens = []
                self.selected_event_ids = remaining_event_ids
                self.selected_event_id = remaining_event_ids[0] if remaining_event_ids else None
                self.selected_folder_id = (
                    self.project.find_event_folder_id(self.selected_event_id)
                    if self.selected_event_id is not None
                    else next(iter(self.project.root_folder_ids), None)
                )
                return True

            if self._apply_mutation("Delete Source Binding", mutate):
                self.window.append_log(f"已删除 {len(binding_pairs)} 个 Source Binding。")
                self.window.set_active_contents_category("片段")
                self._refresh_ui()
            return

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

    def rename_selected_audio(self) -> None:
        audio_id = self._selected_audio_browser_id()
        if audio_id is None:
            self.window.show_context_feedback("先在 Audio 树中选择一个 Audio Object。")
            return
        new_id = self.window.ask_rename_value("重命名 Audio", "Audio ID", audio_id)
        if not new_id or new_id == audio_id:
            return

        def mutate() -> bool:
            self.project.rename_audio_object(audio_id, new_id)
            self.selected_audio_id = new_id
            return True

        try:
            changed = self._apply_mutation("Rename Audio", mutate)
        except ValueError as exc:
            QMessageBox.warning(self.window, "重命名 Audio 失败", str(exc))
            return
        if changed:
            self.window.append_log(f"已重命名 Audio：{audio_id} -> {new_id}")
            self.window.set_active_property_category("音频属性")
            self._refresh_ui()

    def delete_selected_audio(self) -> None:
        audio_id = self._selected_audio_browser_id()
        if audio_id is None:
            self.window.show_context_feedback("先在 Audio 树中选择一个 Audio Object。")
            return

        linked_event_ids = self._event_ids_for_audio(audio_id)
        if not self.window.confirm_delete_audio(audio_id, linked_event_ids):
            return

        def mutate() -> bool:
            removed_event_ids = set(self.project.remove_audio_object(audio_id, cascade_events=bool(linked_event_ids)))
            if self.selected_event_id in removed_event_ids:
                self.selected_event_id = None
            self.selected_event_ids = [event_id for event_id in self.selected_event_ids if event_id not in removed_event_ids]
            self.selected_source_binding_tokens = []
            if self.selected_event_id is None and self.selected_event_ids:
                self.selected_event_id = self.selected_event_ids[0]
            if self.selected_event_id is not None:
                self.selected_folder_id = self.project.find_event_folder_id(self.selected_event_id)
            elif self.selected_folder_id not in self.project.folders:
                self.selected_folder_id = next(iter(self.project.root_folder_ids), None)
            if self.selected_audio_id == audio_id or self.selected_audio_id not in self.project.audio_objects:
                self.selected_audio_id = next(iter(self.project.audio_objects), None)
            return True

        if self._apply_mutation("Delete Audio", mutate):
            if linked_event_ids:
                self.window.append_log(f"已删除 Audio：{audio_id}，并级联删除 {len(linked_event_ids)} 个引用 Event。")
            else:
                self.window.append_log(f"已删除 Audio：{audio_id}")
            self._refresh_ui()

    def delete_selected_sources(self) -> None:
        source_paths = self._selected_source_paths()
        if not source_paths:
            self.window.show_context_feedback("先在源音频树中选择至少一条源音频。")
            return

        delete_action = self.window.ask_source_delete_action(
            len(source_paths),
            allow_remove_from_audio=bool(self._selected_audio_browser_id()),
            allow_remove_from_registry=True,
            allow_delete_files=True,
        )
        if delete_action == "remove_from_audio":
            self.remove_source_assets_from_current_audio(source_paths)
        elif delete_action == "remove_from_registry":
            self.remove_source_assets_from_registry(source_paths)
        elif delete_action == "delete_files":
            self.delete_source_files(source_paths)

    def remove_source_assets_from_current_audio(self, source_paths: list[str]) -> None:
        audio_id = self._selected_audio_browser_id()
        if audio_id is None:
            self.window.show_context_feedback("先在 Audio 树中选择一个 Audio Object，再从源音频树移除绑定。")
            return
        audio = self.project.audio_objects.get(audio_id)
        if audio is None:
            self.window.show_context_feedback("当前 Audio 不存在，无法移除绑定。")
            return

        normalized_sources = {str(path).strip().casefold() for path in source_paths if str(path).strip()}
        clip_ids_to_remove = [clip.id for clip in audio.clips if str(clip.source_path).strip().casefold() in normalized_sources]
        if not clip_ids_to_remove:
            self.window.show_context_feedback(f"Audio {audio_id} 当前没有命中所选源音频绑定。")
            return

        if not self.window.confirm_delete(f"确认从 Audio“{audio_id}”移除 {len(clip_ids_to_remove)} 条 Source Binding？"):
            return

        def mutate() -> bool:
            for clip_id in clip_ids_to_remove:
                self.project.remove_clip_from_audio_object(audio_id, clip_id)
            self.selected_audio_id = audio_id
            self.selected_source_binding_tokens = []
            linked_event_ids = self._event_ids_for_audio(audio_id)
            if linked_event_ids:
                self.selected_event_id = linked_event_ids[0]
                self.selected_event_ids = [linked_event_ids[0]]
                self.selected_folder_id = self.project.find_event_folder_id(linked_event_ids[0])
            else:
                self.selected_event_id = None
                self.selected_event_ids = []
            return True

        if self._apply_mutation("Remove Sources From Audio", mutate):
            self.window.append_log(f"已从 Audio {audio_id} 移除 {len(clip_ids_to_remove)} 条源音频绑定。")
            self._refresh_ui()

    def remove_source_assets_from_registry(self, source_paths: list[str]) -> None:
        removable_paths: list[str] = []
        skipped_paths: list[str] = []
        for source_path in source_paths:
            if source_path not in self.project.asset_registry:
                continue
            if self._audio_ids_for_source(source_path):
                skipped_paths.append(source_path)
                continue
            removable_paths.append(source_path)

        if not removable_paths:
            if skipped_paths:
                self.window.show_context_feedback("所选源音频仍被 Audio 引用，不能从项目注册表移除。")
            else:
                self.window.show_context_feedback("所选源音频当前不在项目注册表中。")
            return

        label = f"确认从项目注册表移除 {len(removable_paths)} 条未引用源音频？"
        if skipped_paths:
            label += f"\n另有 {len(skipped_paths)} 条仍被 Audio 引用，本次会跳过。"
        if not self.window.confirm_delete(label):
            return

        def mutate() -> bool:
            for source_path in removable_paths:
                self.project.remove_source_asset(source_path)
            return True

        if self._apply_mutation("Remove Source Assets From Registry", mutate):
            self.window.append_log(f"已从项目注册表移除 {len(removable_paths)} 条源音频。")
            if skipped_paths:
                self.window.show_context_feedback(f"已移除 {len(removable_paths)} 条未引用源音频；跳过 {len(skipped_paths)} 条仍被 Audio 引用的项目。")
            self._refresh_ui()

    def delete_source_files(self, source_paths: list[str]) -> None:
        existing_paths = [Path(path) for path in source_paths if str(path).strip()]
        existing_paths = [path for path in existing_paths if path.exists() and path.is_file()]
        if not existing_paths:
            self.window.show_context_feedback("所选源音频文件当前不存在，无法从磁盘删除。")
            self._refresh_ui()
            return

        if not self.window.confirm_delete(f"确认从磁盘删除 {len(existing_paths)} 条源文件？"):
            return

        deleted_paths: list[str] = []
        failed_paths: list[str] = []
        for path in existing_paths:
            try:
                path.unlink()
            except OSError:
                failed_paths.append(str(path))
                continue
            deleted_paths.append(str(path))

        if deleted_paths:
            self.window.append_log(f"已从磁盘删除 {len(deleted_paths)} 条源文件。")
        if failed_paths:
            self.window.show_context_feedback(f"有 {len(failed_paths)} 条源文件删除失败，请检查文件占用或权限。")
        self._refresh_ui()

    def import_clips(self, file_paths: list[str]) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "导入音频", "请先选择一个事件，再导入音频片段。")
            return

        supported_paths, skipped_unsupported, skipped_missing = self._classify_import_file_paths(file_paths)
        imported_clips = []
        reserved_clip_ids = {clip.id for clip in event.clips}
        for source_path in supported_paths:
            clip = self._build_clip_from_path(source_path, reserved_clip_ids)
            reserved_clip_ids.add(clip.id)
            imported_clips.append(clip)

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

    def assign_source_assets_to_audio(self, event_id: str, source_paths: list[str], replace_existing: bool) -> None:
        event = self.project.events.get(event_id)
        if event is None:
            return

        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        for raw_path in source_paths:
            normalized = str(raw_path).strip()
            if not normalized:
                continue
            lookup_key = normalized.casefold()
            if lookup_key in seen_paths:
                continue
            seen_paths.add(lookup_key)
            normalized_paths.append(normalized)
        if not normalized_paths:
            return

        navigation_state = self.window.navigation_state()
        selected_tokens: list[str] = []
        added_count = 0
        skipped_count = 0
        replaced_count = 0

        def mutate() -> bool:
            nonlocal added_count, skipped_count, replaced_count
            if replace_existing:
                existing_by_source: dict[str, list[ClipModel]] = {}
                for clip in event.clips:
                    existing_by_source.setdefault(str(clip.source_path).strip(), []).append(clip)

                reserved_clip_ids = {clip.id for clip in event.clips}
                rebuilt_clips: list[ClipModel] = []
                for source_path in normalized_paths:
                    existing_clips = existing_by_source.get(source_path, [])
                    if existing_clips:
                        clip = existing_clips.pop(0)
                    else:
                        clip = self._build_clip_from_path(Path(source_path), reserved_clip_ids)
                    if event.play_mode != "OneShot" and clip.enabled:
                        clip.active = True
                    reserved_clip_ids.add(clip.id)
                    rebuilt_clips.append(clip)
                    selected_tokens.append(encode_source_binding_token(event.id, clip.id))
                    self.project.register_source_asset(source_path)

                before_signature = [(clip.id, clip.source_path, bool(clip.enabled), bool(clip.active)) for clip in event.clips]
                replaced_count = len(rebuilt_clips)
                self.selected_event_id = event.id
                self.selected_event_ids = [event.id]
                self.selected_folder_id = self.project.find_event_folder_id(event.id)
                self.selected_source_binding_tokens = list(selected_tokens)
                event.clips = rebuilt_clips
                normalize_event_binding_states(event)
                after_signature = [(clip.id, clip.source_path, bool(clip.enabled), bool(clip.active)) for clip in event.clips]
                if before_signature == after_signature:
                    return False
                self.project.touch()
                return True

            existing_clips_by_path = {
                str(clip.source_path).strip().casefold(): clip
                for clip in event.clips
                if str(clip.source_path).strip()
            }
            before_signature = [(clip.id, clip.source_path, bool(clip.enabled), bool(clip.active)) for clip in event.clips]
            reserved_clip_ids = {clip.id for clip in event.clips}
            for source_path in normalized_paths:
                existing_clip = existing_clips_by_path.get(source_path.casefold())
                if existing_clip is not None:
                    selected_tokens.append(encode_source_binding_token(event.id, existing_clip.id))
                    skipped_count += 1
                    continue
                clip = self._build_clip_from_path(Path(source_path), reserved_clip_ids)
                if event.play_mode != "OneShot" and clip.enabled:
                    clip.active = True
                reserved_clip_ids.add(clip.id)
                event.clips.append(clip)
                selected_tokens.append(encode_source_binding_token(event.id, clip.id))
                self.project.register_source_asset(source_path)
                added_count += 1
            self.selected_event_id = event.id
            self.selected_event_ids = [event.id]
            self.selected_folder_id = self.project.find_event_folder_id(event.id)
            self.selected_source_binding_tokens = list(selected_tokens)
            normalize_event_binding_states(event)
            after_signature = [(clip.id, clip.source_path, bool(clip.enabled), bool(clip.active)) for clip in event.clips]
            if before_signature == after_signature:
                return False
            self.project.touch()
            return True

        if self._apply_mutation("Assign Source Assets", mutate):
            operation_label = "替换" if replace_existing else "追加"
            self.window.append_log(f"已为事件 {event.id} 的 Audio {operation_label} {len(normalized_paths)} 条源音频绑定。")
            if replace_existing:
                feedback_message = f"已将事件 {event.id} 的 Audio 源音频绑定替换为 {replaced_count} 条。"
            else:
                feedback_message = f"已成功向事件 {event.id} 的 Audio 追加 {added_count} 条源音频。"
                if skipped_count:
                    feedback_message += f" 已跳过 {skipped_count} 条重复项。"
            self.window.set_audio_source_binding_feedback(event.id, feedback_message)
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)
        elif self.selected_source_binding_tokens:
            if replace_existing:
                self.window.set_audio_source_binding_feedback(event.id, f"事件 {event.id} 的 Audio 源音频绑定未发生变化。")
            else:
                self.window.set_audio_source_binding_feedback(event.id, f"事件 {event.id} 的 Audio 没有新增绑定；{skipped_count} 条源音频均已存在。")
            self._refresh_ui()
            self.window.apply_navigation_state(navigation_state)

    def assign_source_assets_to_current_audio(self, source_paths: list[str], replace_existing: bool) -> None:
        audio_id = self._selected_audio_browser_id()
        if audio_id is None:
            return
        self.assign_source_assets_to_audio_object(audio_id, source_paths, replace_existing)

    def assign_source_assets_to_audio_object(self, audio_id: str, source_paths: list[str], replace_existing: bool) -> None:
        audio = self.project.audio_objects.get(audio_id)
        if audio is None:
            return

        normalized_paths: list[str] = []
        seen_paths: set[str] = set()
        for raw_path in source_paths:
            normalized = str(raw_path).strip()
            if not normalized:
                continue
            lookup_key = normalized.casefold()
            if lookup_key in seen_paths:
                continue
            seen_paths.add(lookup_key)
            normalized_paths.append(normalized)
        if not normalized_paths:
            return

        linked_event_ids = self._event_ids_for_audio(audio_id)
        selected_tokens: list[str] = []
        added_count = 0
        skipped_count = 0
        replaced_count = 0

        def mutate() -> bool:
            nonlocal added_count, skipped_count, replaced_count
            before_signature = [(clip.id, str(clip.source_path), bool(clip.enabled), bool(clip.active)) for clip in audio.clips]
            if replace_existing:
                existing_by_source: dict[str, list[ClipModel]] = {}
                for clip in audio.clips:
                    existing_by_source.setdefault(str(clip.source_path).strip(), []).append(clip)

                reserved_clip_ids = {clip.id for clip in audio.clips}
                rebuilt_clips: list[ClipModel] = []
                for source_path in normalized_paths:
                    existing_clips = existing_by_source.get(source_path, [])
                    if existing_clips:
                        clip = existing_clips.pop(0)
                    else:
                        clip = self._build_clip_from_path(Path(source_path), reserved_clip_ids)
                    reserved_clip_ids.add(clip.id)
                    rebuilt_clips.append(clip)
                    self.project.register_source_asset(source_path)
                    if linked_event_ids:
                        selected_tokens.append(encode_source_binding_token(linked_event_ids[0], clip.id))
                audio.clips = rebuilt_clips
                replaced_count = len(rebuilt_clips)
            else:
                existing_clips_by_path = {
                    str(clip.source_path).strip().casefold(): clip
                    for clip in audio.clips
                    if str(clip.source_path).strip()
                }
                reserved_clip_ids = {clip.id for clip in audio.clips}
                for source_path in normalized_paths:
                    existing_clip = existing_clips_by_path.get(source_path.casefold())
                    if existing_clip is not None:
                        if linked_event_ids:
                            selected_tokens.append(encode_source_binding_token(linked_event_ids[0], existing_clip.id))
                        skipped_count += 1
                        continue
                    clip = self._build_clip_from_path(Path(source_path), reserved_clip_ids)
                    reserved_clip_ids.add(clip.id)
                    audio.clips.append(clip)
                    self.project.register_source_asset(source_path)
                    if linked_event_ids:
                        selected_tokens.append(encode_source_binding_token(linked_event_ids[0], clip.id))
                    added_count += 1

            self.selected_audio_id = audio.id
            if linked_event_ids:
                self.selected_event_id = linked_event_ids[0]
                self.selected_event_ids = [linked_event_ids[0]]
                self.selected_folder_id = self.project.find_event_folder_id(linked_event_ids[0])
                self.selected_source_binding_tokens = list(selected_tokens)
            else:
                self.selected_event_id = None
                self.selected_event_ids = []
                self.selected_source_binding_tokens = []
            self._normalize_audio_binding_states(audio)
            after_signature = [(clip.id, str(clip.source_path), bool(clip.enabled), bool(clip.active)) for clip in audio.clips]
            if before_signature == after_signature:
                return False
            self.project.touch()
            return True

        if self._apply_mutation("Assign Source Assets To Audio", mutate):
            operation_label = "替换" if replace_existing else "追加"
            event_hint = f"；引用 Event：{linked_event_ids[0]}" if linked_event_ids else "；当前尚未创建引用 Event"
            if replace_existing:
                feedback_message = f"已将 Audio {audio.id} 的源音频替换为 {replaced_count} 条。"
            else:
                feedback_message = f"已成功向 Audio {audio.id} 追加 {added_count} 条源音频。"
                if skipped_count:
                    feedback_message += f" 已跳过 {skipped_count} 条重复项。"
            self.window.append_log(f"已为 Audio {audio.id} {operation_label} {len(normalized_paths)} 条源音频绑定{event_hint}。")
            if linked_event_ids:
                self.window.set_audio_source_binding_feedback(linked_event_ids[0], feedback_message)
                self.window.set_active_property_category("音频属性")
            self._refresh_ui()
            self.window.explorer_tabs.setCurrentIndex(2)
            self.window.select_audio_browser_audio(audio.id)
        elif linked_event_ids:
            if replace_existing:
                self.window.set_audio_source_binding_feedback(linked_event_ids[0], f"Audio {audio.id} 的源音频绑定未发生变化。")
            else:
                self.window.set_audio_source_binding_feedback(linked_event_ids[0], f"Audio {audio.id} 没有新增绑定；{skipped_count} 条源音频均已存在。")
            self._refresh_ui()

    def import_audio_files_to_audio(self, file_paths: list[str], target_audio_id=None) -> None:
        import_entries, skipped_unsupported, skipped_missing, skipped_empty_directories = self._classify_event_import_paths(file_paths)
        if not import_entries:
            self._notify_import_skip(
                "导入音频到 Audio",
                skipped_unsupported,
                skipped_missing,
                skipped_empty_directories,
            )
            return

        target_audio = self.project.audio_objects.get(str(target_audio_id)) if target_audio_id is not None else None
        if target_audio is not None:
            binding_mode = "append"
            if target_audio.clips:
                binding_mode = self.window.ask_audio_import_binding_mode(target_audio.display_name or target_audio.id)
                if binding_mode is None:
                    return
            self.assign_source_assets_to_audio_object(
                target_audio.id,
                [str(source_path) for _folder_parts, source_path in import_entries],
                replace_existing=binding_mode == "replace",
            )
            return

        create_events = self.window.ask_audio_import_create_events(len(import_entries))
        if create_events is None:
            return

        imported_audio: list[tuple[tuple[str, ...], AudioObjectModel, EventModel | None]] = []
        reserved_audio_ids = set(self.project.audio_objects.keys())
        reserved_event_ids = set(self.project.events.keys())
        for folder_parts, source_path in import_entries:
            audio = self._build_audio_object_from_path(source_path, reserved_audio_ids)
            reserved_audio_ids.add(audio.id)
            event = self._build_event_for_audio_object(audio, source_path, reserved_event_ids) if create_events else None
            if event is not None:
                reserved_event_ids.add(event.id)
            imported_audio.append((folder_parts, audio, event))

        folder_id = self._resolve_target_folder_for_creation()
        last_audio_id = imported_audio[-1][1].id
        last_event_id = imported_audio[-1][2].id if imported_audio[-1][2] is not None else None
        created_folder_count = 0
        last_event_folder_id = folder_id

        def mutate() -> bool:
            nonlocal created_folder_count, last_event_folder_id
            folder_cache: dict[tuple[str, ...], str] = {(): folder_id}
            for folder_parts, audio, event in imported_audio:
                self.project.add_audio_object(audio)
                if event is not None:
                    event_folder_id, new_folder_count = self._ensure_import_folder_path(folder_id, folder_parts, folder_cache)
                    created_folder_count += new_folder_count
                    self.project.add_event(event_folder_id, event)
                    last_event_folder_id = event_folder_id
                else:
                    for clip in audio.clips:
                        self.project.register_source_asset(str(clip.source_path))
            self.selected_audio_id = last_audio_id
            if last_event_id is not None:
                self.selected_event_id = last_event_id
                self.selected_event_ids = [last_event_id]
                self.selected_folder_id = last_event_folder_id
            else:
                self.selected_event_id = None
                self.selected_event_ids = []
                self.selected_source_binding_tokens = []
            return True

        if self._apply_mutation("Import Audio To Audio Objects", mutate):
            folder_suffix = f"；新增文件夹：{created_folder_count} 个" if created_folder_count else ""
            skipped_suffix = self._format_import_skip_suffix(skipped_unsupported, skipped_missing, skipped_empty_directories)
            if create_events:
                self.window.append_log(
                    f"已导入 {len(imported_audio)} 个音频并创建 Audio Object/同名 Event{folder_suffix}；当前 Audio：{last_audio_id}。{skipped_suffix}"
                )
                self.window.set_active_property_category("音频属性")
            else:
                self.window.append_log(
                    f"已导入 {len(imported_audio)} 个音频并创建 Audio Object；未自动创建 Event；当前 Audio：{last_audio_id}。{skipped_suffix}"
                )
            self._refresh_ui()
            self.window.explorer_tabs.setCurrentIndex(2)
            self.window.select_audio_browser_audio(last_audio_id)

    def import_audio_files_to_source_registry(self, file_paths: list[str]) -> None:
        import_entries, skipped_unsupported, skipped_missing, skipped_empty_directories = self._classify_event_import_paths(file_paths)
        if not import_entries:
            self._notify_import_skip(
                "导入音频到源资源库",
                skipped_unsupported,
                skipped_missing,
                skipped_empty_directories,
            )
            return

        source_paths: list[str] = []
        seen_paths: set[str] = set()
        for _folder_parts, source_path in import_entries:
            normalized = str(source_path)
            lookup_key = normalized.casefold()
            if lookup_key in seen_paths:
                continue
            seen_paths.add(lookup_key)
            source_paths.append(normalized)

        registered_count = 0

        def mutate() -> bool:
            nonlocal registered_count
            changed = False
            for source_path in source_paths:
                if source_path not in self.project.asset_registry:
                    registered_count += 1
                self.project.register_source_asset(source_path)
                changed = True
            return changed

        if self._apply_mutation("Import Audio To Source Registry", mutate):
            skipped_suffix = self._format_import_skip_suffix(skipped_unsupported, skipped_missing, skipped_empty_directories)
            self.window.append_log(f"已导入 {len(source_paths)} 条源音频到资源库；新增未引用资源 {registered_count} 条。{skipped_suffix}")
            self._refresh_ui()
            self.window.explorer_tabs.setCurrentIndex(1)

    def open_audio_bindings_popup(self, event_id: str, anchor) -> None:
        event = self.project.events.get(event_id)
        if event is None:
            return
        self.window.show_audio_bindings_popup(event, anchor)

    def open_audio_bindings_for_audio(self, audio_id: str) -> None:
        event_ids = self._event_ids_for_audio(audio_id)
        if not event_ids:
            self.window.append_log(f"Audio 绑定打开失败：{audio_id} 当前没有引用 Event。")
            return
        anchor = self.window.mapToGlobal(self.window.rect().center())
        self.open_audio_bindings_popup(event_ids[0], anchor)

    def update_audio_source_binding_enabled(self, event_id: str, clip_id: str, enabled: bool) -> None:
        event = self.project.events.get(event_id)
        if event is None:
            return

        def mutate() -> bool:
            clip = next((item for item in event.clips if item.id == clip_id), None)
            if clip is None:
                return False
            if clip.enabled == enabled and (enabled or not clip.active):
                return False
            clip.enabled = enabled
            normalize_event_binding_states(event)
            self.project.touch()
            return True

        merge_key = f"source-binding-enabled:{event_id}:{clip_id}"
        if self._apply_mutation("Update Source Binding State", mutate, merge_key=merge_key):
            state_label = "启用" if enabled else "停用"
            self.window.append_log(f"已将事件 {event_id} 的 Audio 绑定 {clip_id} 标记为{state_label}。")
            self.window.set_audio_source_binding_feedback(event_id, f"已将 Audio 绑定 {clip_id} 标记为{state_label}。")
            self._refresh_ui()

    def set_active_source_binding(self, event_id: str, clip_id: str) -> None:
        self.update_audio_source_binding_active(event_id, clip_id, True)

    def update_audio_source_binding_active(self, event_id: str, clip_id: str, active: bool) -> None:
        event = self.project.events.get(event_id)
        if event is None:
            return

        def mutate() -> bool:
            clip = next((item for item in event.clips if item.id == clip_id), None)
            if clip is None:
                return False
            if event.play_mode == "OneShot" and not active:
                return False

            changed = False
            if active and not clip.enabled:
                clip.enabled = True
                changed = True
            if event.play_mode == "OneShot" and active:
                for candidate in event.clips:
                    desired_active = bool(candidate.id == clip_id and candidate.enabled)
                    if candidate.active != desired_active:
                        candidate.active = desired_active
                        changed = True
                normalize_event_binding_states(event)
                if not changed:
                    return False
                self.project.touch()
                return True

            desired_active = bool(active and clip.enabled)
            if clip.active != desired_active:
                clip.active = desired_active
                changed = True
            normalize_event_binding_states(event)
            if not changed:
                return False
            self.project.touch()
            return True

        merge_key = f"source-binding-active:{event_id}"
        if self._apply_mutation("Set Active Source Binding", mutate, merge_key=merge_key):
            if event.play_mode == "OneShot":
                message = f"已将 Active Audio Source Binding 切换为 {clip_id}。"
            else:
                state_label = "激活" if active else "取消激活"
                message = f"已将 Audio 绑定 {clip_id} 标记为{state_label}。"
            self.window.append_log(f"已更新事件 {event_id} 的 Audio 绑定状态：{message}")
            self.window.set_audio_source_binding_feedback(event_id, message)
            self._refresh_ui()

    def import_audio_files_as_events(self, file_paths: list[str], target_folder_id=None, template: dict[str, object] | None = None) -> None:
        import_entries, skipped_unsupported, skipped_missing, skipped_empty_directories = self._classify_event_import_paths(file_paths)
        imported_events: list[tuple[tuple[str, ...], EventModel]] = []
        reserved_event_ids = set(self.project.events.keys())
        reserved_audio_ids = set(self.project.audio_objects.keys())
        for folder_parts, source_path in import_entries:
            event = self._build_event_from_audio_path(source_path, reserved_event_ids, reserved_audio_ids)
            self._apply_event_import_template(event, template)
            reserved_event_ids.add(event.id)
            reserved_audio_ids.add(event.audio_id)
            imported_events.append((folder_parts, event))

        if not imported_events:
            self._notify_import_skip(
                "导入音频为事件",
                skipped_unsupported,
                skipped_missing,
                skipped_empty_directories,
            )
            return

        folder_id = target_folder_id if target_folder_id in self.project.folders else self._resolve_target_folder_for_creation()
        last_event_id = imported_events[-1][1].id
        created_folder_count = 0
        last_event_folder_id = folder_id

        def mutate() -> bool:
            nonlocal created_folder_count, last_event_folder_id
            folder_cache: dict[tuple[str, ...], str] = {(): folder_id}
            for folder_parts, event in imported_events:
                event_folder_id, new_folder_count = self._ensure_import_folder_path(folder_id, folder_parts, folder_cache)
                created_folder_count += new_folder_count
                self.project.add_event(event_folder_id, event)
                last_event_folder_id = event_folder_id
            self.selected_folder_id = last_event_folder_id
            self.selected_event_id = last_event_id
            self.selected_event_ids = [last_event_id] if last_event_id is not None else []
            return True

        if self._apply_mutation("Import Audio As Events", mutate):
            template_suffix = self._describe_event_import_template(template)
            folder_name = self.project.folders[folder_id].name if folder_id in self.project.folders else self.project.name
            folder_suffix = f"；新增文件夹：{created_folder_count} 个" if created_folder_count else ""
            skipped_suffix = self._format_import_skip_suffix(skipped_unsupported, skipped_missing, skipped_empty_directories)
            self.window.append_log(
                f"已导入 {len(imported_events)} 个音频并创建事件；目标目录：{folder_name}{folder_suffix}；当前事件：{last_event_id}.{template_suffix}{skipped_suffix}"
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
            self.window.set_resources_batch_feedback(
                event_id=event.id,
                title="批量权重已应用",
                summary=f"已将 {len(clip_ids)} 个片段的权重统一为 {normalized_weight}。",
                detail="返回片段编排即可核对表格中的权重列和单片段详情。",
                field_summary="权重",
                affected_count=len(clip_ids),
            )
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
            field_labels = ["权重", "标签"]
            if asset_prefix:
                field_labels.append("资源前缀")
            self.window.append_log(f"已批量更新 {len(clip_ids)} 个片段的属性。")
            self.window.set_resources_batch_feedback(
                event_id=event.id,
                title="批量属性已同步",
                summary=f"已批量更新 {len(clip_ids)} 个片段的 {'、'.join(field_labels)}。",
                detail=(
                    f"权重 -> {weight} | 标签 -> {', '.join(tags) if tags else '清空'}"
                    + (f" | 资源键前缀 -> {asset_prefix}/<clip_id>" if asset_prefix else "")
                ),
                field_summary="/".join(field_labels),
                affected_count=len(clip_ids),
            )
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
            self.window.set_resources_batch_feedback(
                event_id=event.id,
                title="批量重命名已完成",
                summary=f"已按基础名 {base_name} 重命名 {len(clip_ids)} 个片段。",
                detail=f"起始序号 {start_index:02d}；资源键与导出路径已同步为新的片段 ID。",
                field_summary="ID/资源键/导出路径",
                affected_count=len(clip_ids),
            )
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
            field_label = {
                "id": "片段 ID",
                "asset_key": "资源键",
                "weight": "权重",
                "source_path": "源路径",
            }.get(field_name, field_name)
            self.window.append_log(f"已按 {field_name} {order_label} 排序片段。")
            self.window.set_resources_batch_feedback(
                event_id=event.id,
                title="片段排序已更新",
                summary=f"已按 {field_label} {order_label} 重排 {len(event.clips)} 个片段。",
                detail="片段表、生成预览和后续批量操作都会沿用当前排序结果。",
                field_summary=f"排序/{field_label}",
                affected_count=len(event.clips),
            )
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
            self.window.set_resources_batch_feedback(
                event_id=event.id,
                title="拖拽顺序已保存",
                summary=f"已按拖拽结果重排 {len(clip_ids)} 个片段。",
                detail="当前列表顺序会直接影响片段编排视图和后续导出顺序。",
                field_summary="拖拽顺序",
                affected_count=len(clip_ids),
            )
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

    def _clear_audition_session(self, event_id: str | None = None) -> None:
        if self._audition_session is None:
            return
        if event_id is not None and self._audition_session.event_id != event_id:
            return
        self._audition_session = None
        self._preview_transport_timer.stop()

    def _current_audition_session(self) -> AuditionSession | None:
        session = self._audition_session
        if session is None:
            return None
        if session.event_id is not None and session.event_id not in self.project.events:
            self._audition_session = None
            return None
        return session

    def _remember_audition_session(self, session: AuditionSession) -> None:
        self._audition_session = session

    def _refresh_recent_preview_session(self) -> bool:
        session = self._current_audition_session()
        if session is None:
            return False
        refreshed_session = self._rebuild_recent_preview_session(session)
        if refreshed_session is None or refreshed_session == session:
            return False
        self._audition_session = refreshed_session
        self._publish_audition_session(refreshed_session)
        return True

    def _rebuild_recent_preview_session(self, session: AuditionSession) -> AuditionSession | None:
        if session.event_id is None:
            return None
        event = self.project.events.get(session.event_id)
        if event is None:
            return None
        clip = next((item for item in event.clips if item.id == session.clip_id), None)
        if clip is None or not clip.source_path:
            return None
        captured_volume_db = session.event_volume_db_at_capture
        if captured_volume_db is None:
            captured_volume_db = session.tracked_base_volume_db
        captured_pitch_cents = session.event_pitch_cents_at_capture
        if captured_pitch_cents is None:
            captured_pitch_cents = session.preserve_timing_pitch_cents
        tracked_base_volume_db = event.volume_db + (session.tracked_base_volume_db - captured_volume_db)
        preserve_timing_pitch_cents = event.pitch_cents + (session.preserve_timing_pitch_cents - captured_pitch_cents)
        if session.target_kind == "segment":
            trim_start_ms = session.trim_start_ms
            trim_end_ms = session.trim_end_ms
            fade_in_ms = session.fade_in_ms
            fade_out_ms = session.fade_out_ms
        else:
            trim_start_ms = clip.trim_start_ms
            trim_end_ms = clip.trim_end_ms
            fade_in_ms = clip.fade_in_ms
            fade_out_ms = clip.fade_out_ms
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, tracked_base_volume_db)
        return self._create_audition_session(
            event=event,
            clip=clip,
            target_kind=session.target_kind,
            effective_volume_db=effective_volume_db,
            tracked_base_volume_db=tracked_base_volume_db,
            pitch_cents=session.pitch_cents,
            preserve_timing_pitch_cents=preserve_timing_pitch_cents,
            trim_start_ms=trim_start_ms,
            trim_end_ms=trim_end_ms,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

    def _create_audition_session(
        self,
        *,
        event: EventModel,
        clip: ClipModel,
        target_kind: str,
        effective_volume_db: float,
        tracked_base_volume_db: float,
        pitch_cents: int,
        preserve_timing_pitch_cents: int,
        trim_start_ms: int,
        trim_end_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
    ) -> AuditionSession:
        asset_key = clip.asset_key or Path(clip.source_path).stem
        event_name = event.display_name or event.id
        if target_kind == "segment":
            title = f"局部片段 {clip.id}"
            detail = f"{trim_start_ms}-{trim_end_ms} ms | 事件 {event_name} | 资源 {asset_key}"
        elif target_kind == "clip":
            title = f"片段 {clip.id}"
            detail = f"事件 {event_name} | 资源 {asset_key} | Bus {event.bus}"
        else:
            title = f"事件 {event_name}"
            detail = f"片段 {clip.id} | 资源 {asset_key} | Bus {event.bus}"
        return AuditionSession(
            playback_owner_id=f"event:{event.id}",
            event_id=event.id,
            event_name=event_name,
            clip_id=clip.id,
            asset_key=asset_key,
            file_path=clip.source_path,
            target_kind=target_kind,
            title=title,
            detail=detail,
            bus_name=event.bus,
            effective_volume_db=effective_volume_db,
            tracked_base_volume_db=tracked_base_volume_db,
            pitch_cents=pitch_cents,
            preserve_timing_pitch_cents=preserve_timing_pitch_cents,
            trim_start_ms=trim_start_ms,
            trim_end_ms=trim_end_ms,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
            event_volume_db_at_capture=event.volume_db,
            event_pitch_cents_at_capture=event.pitch_cents,
        )

    def _publish_audition_session(self, session: AuditionSession) -> None:
        self.window.set_recent_preview_session_summary(session.title, session.detail)
        self.window.set_recent_preview_source(session.file_path, session.clip_id, session.asset_key)
        self.window.set_preview_audio_metrics(
            self.audio_meter_service.analyze_file(
                session.file_path,
                session.effective_volume_db,
                pitch_cents=session.pitch_cents,
                preserve_timing_pitch_cents=session.preserve_timing_pitch_cents,
                trim_start_ms=session.trim_start_ms,
                trim_end_ms=session.trim_end_ms,
                fade_in_ms=session.fade_in_ms,
                fade_out_ms=session.fade_out_ms,
            ),
            clip_id=session.clip_id,
            asset_key=session.asset_key,
        )

    def _play_audition_session(self, session: AuditionSession) -> str:
        return self.playback_service.play_file(
            session.file_path,
            session.effective_volume_db,
            tracked_base_volume_db=session.tracked_base_volume_db,
            bus_name=session.bus_name,
            event_id=session.playback_owner_id,
            pitch_cents=session.pitch_cents,
            preserve_timing_pitch_cents=session.preserve_timing_pitch_cents,
            trim_start_ms=session.trim_start_ms,
            trim_end_ms=session.trim_end_ms,
            fade_in_ms=session.fade_in_ms,
            fade_out_ms=session.fade_out_ms,
        )

    def _handoff_audition_session(self, session: AuditionSession) -> None:
        current_session = self._current_audition_session()
        if current_session is None or current_session.playback_owner_id == session.playback_owner_id:
            return
        self.playback_service.stop_event(current_session.playback_owner_id)
        if current_session.event_id is not None:
            self.preview_service.stop_event(current_session.event_id)

    def _start_audition_session(self, session: AuditionSession) -> str:
        self._handoff_audition_session(session)
        playback_message = self._play_audition_session(session)
        self._remember_audition_session(session)
        self._publish_audition_session(session)
        return playback_message

    def _sync_recent_preview_summary(self, state: str) -> None:
        session = self._current_audition_session()
        if session is not None:
            state_suffix = {
                "playing": "播放中",
                "paused": "已暂停",
                "idle": "可重播",
            }[state]
            self.window.set_recent_preview_session_summary(session.title, f"{session.detail} | {state_suffix}")
            return
        event = self.current_event
        if event is not None:
            event_name = event.display_name or event.id
            self.window.clear_recent_preview_insight()
            self.window.set_recent_preview_session_summary(
                "当前对象可试听",
                f"事件 {event_name} | 开始试听后，可在不同流程继续控制这次试听。",
            )
            return
        self.window.clear_recent_preview_insight()
        self.window.set_recent_preview_session_summary(
            "最近试听",
            "切换事件、资源或流程时，会保留最近一次试听会话。",
        )

    def _sync_preview_transport_state(self) -> None:
        session = self._current_audition_session()
        has_target = self.current_event is not None
        can_replay = session is not None
        state = "idle"
        if session is not None and self.playback_service.has_active_event(session.playback_owner_id):
            state = "paused" if self.playback_service.is_event_paused(session.playback_owner_id) else "playing"
        self.window.set_preview_transport_state(state, has_target=has_target, can_replay=can_replay)
        self._sync_recent_preview_summary(state)
        if state == "playing":
            if not self._preview_transport_timer.isActive():
                self._preview_transport_timer.start()
            return
        self._preview_transport_timer.stop()

    def _poll_preview_transport_state(self) -> None:
        if self._current_audition_session() is None:
            self._preview_transport_timer.stop()
            return
        self._sync_preview_transport_state()

    def preview_current_event(self, silent_log: bool = False) -> None:
        event = self.current_event
        if event is None:
            QMessageBox.information(self.window, "试听事件", "请先选择一个事件，再执行试听。")
            return
        preview_gamesync = self._current_preview_gamesync_context()
        result = self.preview_service.preview_event(
            event,
            preview_duration_resolver=self._resolve_preview_duration_seconds,
            preview_gamesync=preview_gamesync,
            game_parameters=self.project.game_parameters,
            state_groups=self.project.state_groups,
            switch_groups=self.project.switch_groups,
        )
        if not result.accepted:
            self.window.clear_preview_audio_metrics(result.reason)
            self._clear_audition_session(event.id)
            if not silent_log:
                self.window.append_log(f"试听被拒绝：{event.id}，原因：{result.reason}")
            self._sync_preview_transport_state()
            return
        clip = next((item for item in event.clips if item.id == result.clip_id), None)
        playback_message = "Simulated only"
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, result.volume_db, preview_gamesync=preview_gamesync)
        if clip is not None and clip.source_path:
            preview_preserve_timing_pitch_cents = result.pitch_cents + result.combo_pitch_cents
            session = self._create_audition_session(
                event=event,
                clip=clip,
                target_kind="event",
                effective_volume_db=effective_volume_db,
                tracked_base_volume_db=result.volume_db,
                pitch_cents=0,
                preserve_timing_pitch_cents=preview_preserve_timing_pitch_cents,
                trim_start_ms=clip.trim_start_ms,
                trim_end_ms=clip.trim_end_ms,
                fade_in_ms=clip.fade_in_ms,
                fade_out_ms=clip.fade_out_ms,
            )
            if result.stolen_oldest:
                self.playback_service.stop_oldest(session.playback_owner_id)
            playback_message = self._start_audition_session(session)
        else:
            self.window.clear_preview_audio_metrics("当前试听片段没有可分析的源文件。")
            self._clear_audition_session(event.id)
        if not silent_log:
            self.window.append_log(
                f"试听 {event.id}：片段={result.clip_id} 资源={result.asset_key} 事件音量={result.volume_db:.2f}dB 总线后={effective_volume_db:.2f}dB 基础音高={result.pitch_cents} 连击加成={result.combo_pitch_cents} 连击={result.combo_step} 活动实例={result.active_instances} 时长={result.playback_duration_seconds:.2f}s 播放={playback_message}"
            )
        self._sync_preview_transport_state()

    def preview_selected_clip(self, clip_id: str) -> None:
        event = self.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self._clear_audition_session(event.id)
            self.window.append_log(f"试听片段被拒绝：{clip_id} 没有源文件。")
            self._sync_preview_transport_state()
            return
        resolved_volume_db, resolved_pitch_cents, is_muted = self._resolve_preview_event_mix(event)
        if is_muted:
            self.window.clear_preview_audio_metrics("当前事件被 State Override 静音。")
            self._clear_audition_session(event.id)
            self.window.append_log(f"试听片段被拒绝：{event.id} 当前被 State Override 静音。")
            self._sync_preview_transport_state()
            return
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, resolved_volume_db, preview_gamesync=self._current_preview_gamesync_context())
        session = self._create_audition_session(
            event=event,
            clip=clip,
            target_kind="clip",
            effective_volume_db=effective_volume_db,
            tracked_base_volume_db=resolved_volume_db,
            pitch_cents=0,
            preserve_timing_pitch_cents=resolved_pitch_cents,
            trim_start_ms=clip.trim_start_ms,
            trim_end_ms=clip.trim_end_ms,
            fade_in_ms=clip.fade_in_ms,
            fade_out_ms=clip.fade_out_ms,
        )
        playback_message = self._start_audition_session(session)
        self.window.append_log(
            f"试听片段 {clip.id}：资源={clip.asset_key} 事件={event.id} 总线后={effective_volume_db:.2f}dB 播放={playback_message}"
        )
        self._sync_preview_transport_state()

    def preview_selected_clip_segment(self, clip_id: str, start_ms: int, end_ms: int) -> None:
        event = self.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self._clear_audition_session(event.id)
            self.window.append_log(f"局部试听被拒绝：{clip_id} 没有源文件。")
            self._sync_preview_transport_state()
            return
        segment_start_ms = max(MIN_CLIP_TIME_MS, int(start_ms))
        segment_end_ms = max(segment_start_ms + 1, int(end_ms))
        segment_length_ms = max(1, segment_end_ms - segment_start_ms)
        segment_fade_ms = min(40, max(8, segment_length_ms // 12))
        resolved_volume_db, resolved_pitch_cents, is_muted = self._resolve_preview_event_mix(event)
        if is_muted:
            self.window.clear_preview_audio_metrics("当前事件被 State Override 静音。")
            self._clear_audition_session(event.id)
            self.window.append_log(f"局部试听被拒绝：{event.id} 当前被 State Override 静音。")
            self._sync_preview_transport_state()
            return
        effective_volume_db = self._resolve_effective_preview_volume_db(event.bus, resolved_volume_db, preview_gamesync=self._current_preview_gamesync_context())
        session = self._create_audition_session(
            event=event,
            clip=clip,
            target_kind="segment",
            effective_volume_db=effective_volume_db,
            tracked_base_volume_db=resolved_volume_db,
            pitch_cents=0,
            preserve_timing_pitch_cents=resolved_pitch_cents,
            trim_start_ms=segment_start_ms,
            trim_end_ms=segment_end_ms,
            fade_in_ms=segment_fade_ms,
            fade_out_ms=segment_fade_ms,
        )
        playback_message = self._start_audition_session(session)
        self.window.append_log(
            f"局部试听片段 {clip.id}：资源={clip.asset_key} 区间={segment_start_ms}-{segment_end_ms} ms 总线后={effective_volume_db:.2f}dB 播放={playback_message}"
        )
        self._sync_preview_transport_state()

    def play_recent_preview_transport(self) -> None:
        self._refresh_recent_preview_session()
        session = self._current_audition_session()
        if session is None:
            self.preview_current_event()
            return
        if self.playback_service.has_active_event(session.playback_owner_id):
            self.window.append_log(f"最近试听已在播放：{session.title}")
            self._sync_preview_transport_state()
            return
        playback_message = self._play_audition_session(session)
        self._publish_audition_session(session)
        self.window.append_log(f"已播放最近试听：{session.title} 播放={playback_message}")
        self._sync_preview_transport_state()

    def pause_current_event_preview(self) -> None:
        session = self._current_audition_session()
        if session is None:
            QMessageBox.information(self.window, "暂停试听", "当前没有可暂停的试听会话。")
            return
        if not self.playback_service.pause_event(session.playback_owner_id):
            self.window.append_log(f"暂停试听被忽略：{session.title} 当前没有可暂停的播放。")
            self._sync_preview_transport_state()
            return
        self.window.append_log(f"已暂停试听：{session.title}")
        self._sync_preview_transport_state()

    def resume_current_event_preview(self) -> None:
        session = self._current_audition_session()
        if session is None:
            QMessageBox.information(self.window, "继续试听", "当前没有暂停中的试听会话。")
            return
        if not self.playback_service.resume_event(session.playback_owner_id):
            self.window.append_log(f"继续试听被忽略：{session.title} 当前没有暂停中的播放。")
            self._sync_preview_transport_state()
            return
        self.window.append_log(f"已继续试听：{session.title}")
        self._sync_preview_transport_state()

    def restart_current_event_preview(self) -> None:
        session = self._current_audition_session()
        if session is None:
            QMessageBox.information(self.window, "从头播放", "当前对象还没有可重播的试听内容。")
            return
        self.playback_service.stop_event(session.playback_owner_id)
        if session.event_id is not None:
            self.preview_service.stop_event(session.event_id)
        playback_message = self._play_audition_session(session)
        self._publish_audition_session(session)
        self.window.append_log(
            f"从头播放 {session.title}：片段={session.clip_id} 资源={session.asset_key} 播放={playback_message}"
        )
        self._sync_preview_transport_state()

    def stop_current_event_preview(self) -> None:
        session = self._current_audition_session()
        if session is None:
            QMessageBox.information(self.window, "停止试听", "当前没有可停止的试听会话。")
            return
        self.playback_service.stop_event(session.playback_owner_id)
        if session.event_id is not None:
            self.preview_service.stop_event(session.event_id)
        self.window.append_log(f"已停止试听：{session.title}")
        self._sync_preview_transport_state()

    def stop_current_bus_preview(self) -> None:
        session = self._current_audition_session()
        event = self.current_event
        if event is None and session is not None and session.event_id is not None:
            event = self.project.events.get(session.event_id)
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
        self._sync_preview_transport_state()

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

    def _resolve_effective_preview_volume_db(
        self,
        bus_name: str,
        base_volume_db: float,
        *,
        preview_gamesync: PreviewGameSyncContext | None = None,
    ) -> float:
        preview_context = preview_gamesync or self._current_preview_gamesync_context()
        config_map = self._project_bus_config_map()
        resolved_volume_db = float(base_volume_db)
        current_name = bus_name
        visited: set[str] = set()
        while current_name in config_map:
            config = config_map[current_name]
            if config.is_muted:
                return -96.0
            resolved_volume_db += config.volume_db
            bus_gamesync_db, is_muted = self.preview_service.resolve_bus_adjustment(
                config.rtpc_bindings,
                config.state_overrides,
                preview_gamesync=preview_context,
                game_parameters=self.project.game_parameters,
                state_groups=self.project.state_groups,
                switch_groups=self.project.switch_groups,
            )
            resolved_volume_db += bus_gamesync_db
            if is_muted:
                return -96.0
            if current_name == MASTER_BUS_NAME:
                break
            parent_name = config.parent_bus or MASTER_BUS_NAME
            if parent_name in visited:
                return -96.0
            visited.add(parent_name)
            current_name = parent_name
        return resolved_volume_db + self.preview_bus_mixer.effective_gain_db(bus_name)

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
        self._set_loudness_diagnostic_summary(report)
        self._publish_diagnostic_snapshot()

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

    def _find_child_folder_by_name(self, parent_folder_id: str, folder_name: str) -> str | None:
        parent_folder = self.project.folders.get(parent_folder_id)
        normalized_name = folder_name.strip()
        if parent_folder is None or not normalized_name:
            return None
        for child_folder_id in parent_folder.child_folder_ids:
            child_folder = self.project.folders.get(child_folder_id)
            if child_folder is None:
                continue
            if child_folder.name.casefold() == normalized_name.casefold():
                return child_folder_id
        return None

    def _ensure_import_folder_path(
        self,
        base_folder_id: str,
        folder_parts: tuple[str, ...],
        folder_cache: dict[tuple[str, ...], str],
    ) -> tuple[str, int]:
        current_folder_id = base_folder_id
        current_parts: tuple[str, ...] = ()
        created_folder_count = 0
        for folder_name in folder_parts:
            current_parts = (*current_parts, folder_name)
            cached_folder_id = folder_cache.get(current_parts)
            if cached_folder_id is not None:
                current_folder_id = cached_folder_id
                continue
            child_folder_id = self._find_child_folder_by_name(current_folder_id, folder_name)
            if child_folder_id is None:
                folder = FolderModel(id=new_id("folder"), name=folder_name)
                self.project.add_folder(current_folder_id, folder)
                child_folder_id = folder.id
                created_folder_count += 1
            folder_cache[current_parts] = child_folder_id
            current_folder_id = child_folder_id
        return current_folder_id, created_folder_count

    def _build_clip_from_path(self, source_path: Path, reserved_clip_ids: set[str] | None = None) -> ClipModel:
        existing_clip_ids = {clip.id for clip in self.current_event.clips} if self.current_event is not None else set()
        if reserved_clip_ids:
            existing_clip_ids.update(reserved_clip_ids)
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

    def _build_audio_object_from_path(self, source_path: Path, reserved_audio_ids: set[str] | None = None) -> AudioObjectModel:
        base_audio_id = self._normalize_event_id(source_path.stem)
        audio_id = self._make_unique_audio_id(base_audio_id, reserved_audio_ids)
        clip = self._build_clip_from_path(source_path)
        audio = AudioObjectModel(
            id=audio_id,
            display_name=source_path.stem,
            play_mode="OneShot",
            clips=[clip],
        )
        self._normalize_audio_binding_states(audio)
        return audio

    def _build_event_for_audio_object(
        self,
        audio: AudioObjectModel,
        source_path: Path,
        reserved_event_ids: set[str] | None = None,
    ) -> EventModel:
        event_id = self._make_unique_event_id(audio.id, reserved_event_ids)
        event = self._make_casual_event_template(
            event_id,
            display_name=source_path.stem,
            default_bus=self.project.settings.default_bus,
            available_buses=self.project.settings.buses,
        )
        event.audio_id = audio.id
        event.audio = audio
        return event

    def _build_event_from_audio_path(
        self,
        source_path: Path,
        reserved_event_ids: set[str] | None = None,
        reserved_audio_ids: set[str] | None = None,
    ) -> EventModel:
        audio = self._build_audio_object_from_path(source_path, reserved_audio_ids)
        return self._build_event_for_audio_object(audio, source_path, reserved_event_ids)

    def _normalize_event_id(self, raw_name: str) -> str:
        normalized = "".join(character if character.isalnum() else "_" for character in raw_name.strip())
        normalized = normalized.strip("_")
        return normalized or "New_Event"

    def _sync_multi_selection_affordances(self) -> None:
        is_multi_event_selection = len(self.selected_event_ids) > 1
        if is_multi_event_selection:
            self.window.set_active_property_category("工程")
            self.window.set_event_details(None)
        self._sync_browser_action_affordances()

    def _sync_browser_action_affordances(self) -> None:
        active_page = self.window.current_explorer_page_key()
        if active_page == "audios":
            has_audio = self._selected_audio_browser_id() is not None
            self.window.set_explorer_action_state(
                rename_enabled=has_audio,
                delete_enabled=has_audio,
                bulk_bus_enabled=False,
                rename_text="重命名 Audio",
                delete_text="删除 Audio",
                rename_tooltip="重命名当前选中的 AudioObject。" if has_audio else "先在 Audio 树中选择一个 AudioObject。",
                delete_tooltip="删除当前选中的 AudioObject；若仍被 Event 引用，会要求级联确认。" if has_audio else "先在 Audio 树中选择一个 AudioObject。",
            )
            return

        if active_page == "sources":
            has_sources = bool(self._selected_source_paths())
            self.window.set_explorer_action_state(
                rename_enabled=False,
                delete_enabled=has_sources,
                bulk_bus_enabled=False,
                rename_text="重命名",
                delete_text="删除源音频...",
                rename_tooltip="源音频路径重命名请在外部文件系统中处理。",
                delete_tooltip="选择删除方式：从当前 Audio 移除绑定、从项目注册表移除或从磁盘删除源文件。" if has_sources else "先在源音频树中选择至少一条源音频。",
            )
            return

        if active_page != "events":
            self.window.set_explorer_action_state(
                rename_enabled=False,
                delete_enabled=False,
                bulk_bus_enabled=False,
                rename_tooltip="当前浏览页没有可重命名对象。",
                delete_tooltip="当前浏览页没有可删除对象。",
            )
            return

        has_target = bool(self.selected_source_binding_tokens or self.selected_event_ids or self.selected_event_id or self.selected_folder_id)
        is_multi_event_selection = len(self.selected_event_ids) > 1
        self.window.set_explorer_action_state(
            rename_enabled=has_target,
            delete_enabled=has_target,
            bulk_bus_enabled=bool(self.selected_event_ids),
            rename_text="批量重命名" if is_multi_event_selection else "重命名",
            delete_text="批量删除" if is_multi_event_selection else "删除",
            rename_tooltip="重命名当前选中的事件、文件夹或片段绑定。" if has_target else "先在工程浏览器中选择一个对象。",
            delete_tooltip="删除当前选中的事件、文件夹或片段绑定。" if has_target else "先在工程浏览器中选择一个对象。",
        )

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
                summary_primary=f"Bus {self._selected_events_bus_summary()} | 可批量改 Bus/重命名/删除",
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
                summary_primary=f"Audio {event.play_mode} | {WWISE_OUTPUT_BUS_LABEL} {event.bus} | 试听 {self.preview_bus_mixer.describe_bus(event.bus)}",
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
                summary_primary=f"{WWISE_DEFAULT_BUS_LABEL} {self.project.settings.default_bus} | Bus 数 {len(self.project.settings.buses)}",
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
            summary_primary=f"{WWISE_DEFAULT_BUS_LABEL} {self.project.settings.default_bus} | Bus 数 {len(self.project.settings.buses)}",
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
        if self._is_build_running():
            QMessageBox.warning(self.window, "构建进行中", "当前仍有构建任务在后台执行，请等待构建完成后再关闭窗口。")
            return False
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
        if self._is_build_running():
            QMessageBox.warning(self.window, "构建进行中", "当前仍有构建任务在后台执行，请等待构建完成后再切换工程。")
            return False
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
            self.window.append_log(f"自动恢复快照保存失败：{type(exc).__name__}: {exc}")
            try:
                self.recovery_service.clear_snapshot()
            except Exception as cleanup_exc:
                self.window.append_log(f"自动恢复快照清理失败：{type(cleanup_exc).__name__}: {cleanup_exc}")

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
        self._reset_diagnostic_snapshot()
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
        preferences = dict(default_preferences)
        stored_preferences = self.settings.value("uiPreferencesJson", "")
        if isinstance(stored_preferences, str) and stored_preferences.strip():
            try:
                parsed_preferences = json.loads(stored_preferences)
            except json.JSONDecodeError:
                parsed_preferences = None
            if isinstance(parsed_preferences, dict):
                preferences.update(parsed_preferences)
        else:
            preferences.update(
                {
                    "ui_scale": self.settings.value("uiScale", default_preferences["ui_scale"]),
                    "workspace_splitter_sizes": self.settings.value("workspaceSplitterSizes", default_preferences["workspace_splitter_sizes"]),
                    "main_splitter_sizes": self.settings.value("mainSplitterSizes", default_preferences["main_splitter_sizes"]),
                    "active_editor_tab": self.settings.value("activeEditorTab", default_preferences["active_editor_tab"]),
                    "inspector_splitter_sizes": self.settings.value("inspectorSplitterSizes", default_preferences["inspector_splitter_sizes"]),
                    "content_top_splitter_sizes": self.settings.value("contentTopSplitterSizes", default_preferences["content_top_splitter_sizes"]),
                    "active_contents_tab": self.settings.value("activeContentsTab", default_preferences["active_contents_tab"]),
                    "event_import_template": self.settings.value("eventImportTemplate", default_preferences["event_import_template"]),
                }
            )
        self.window.apply_ui_preferences(preferences)

    def _save_window_preferences(self) -> None:
        preferences = self.window.ui_preferences()
        self.settings.setValue("uiPreferencesJson", json.dumps(preferences, ensure_ascii=False))
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
        self._set_validation_diagnostic_summary(issues)
        self._publish_diagnostic_snapshot()

    def build_project(self) -> None:
        if self._is_build_running():
            logger.warning("Build request ignored because another build is already running.")
            self.window.append_log("构建请求已忽略：当前已有构建任务在执行。")
            self.window.set_build_status(
                "构建正在进行中。",
                "请等待当前构建完成后再发起新的构建请求。",
                activate_results=True,
            )
            self._set_build_diagnostic_summary(
                "构建正在进行中。",
                "请等待当前构建完成后再发起新的构建请求。",
                status="warning",
            )
            self._publish_diagnostic_snapshot()
            return

        build_request = self._current_build_request()
        if build_request is None:
            message = self._selection_build_unavailable_message()
            self.window.set_build_plan_summary("选中构建未就绪。", message)
            self.window.set_build_status("选中构建无法开始。", message, activate_results=True)
            self.window.set_build_report("构建未开始\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self.window.show_report_tab(2)
            self.window.append_log(f"选中构建已中止：{message}")
            self._set_build_diagnostic_summary("选中构建无法开始。", message, status="warning")
            self._publish_diagnostic_snapshot()
            return

        requested_scope_label = self._build_scope_label(build_request.scope)
        project_snapshot = copy.deepcopy(self.project)
        log_config = get_runtime_log_config()
        self.window.build_execute_button.setEnabled(False)
        self.window.build_button.setEnabled(False)
        self.window.set_build_status(
            "正在构建导出，请稍候。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 正在导出到：{self.project.settings.export_root}",
            activate_results=True,
        )
        self.window.set_build_plan_summary(
            "正在生成构建计划。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 已切换到后台构建，界面保持可响应。",
        )
        self.window.append_log(f"已开始构建导出：模式={requested_scope_label} 目标={build_request.selection_label}")
        self._set_build_diagnostic_summary(
            "正在构建导出，请稍候。",
            f"模式：{requested_scope_label} | 目标：{build_request.selection_label} | 正在导出到：{self.project.settings.export_root}",
            status="info",
            metadata={
                "requested_scope": build_request.scope,
                "requested_scope_label": requested_scope_label,
                "selection_label": build_request.selection_label,
                "export_root": self.project.settings.export_root,
            },
        )
        if log_config is not None:
            self.window.append_log(f"诊断日志路径：{log_config.latest_log}")
        logger.info(
            "Build requested scope=%s selection=%s export_root=%s project_name=%s",
            build_request.scope,
            build_request.selection_label,
            self.project.settings.export_root,
            self.project.name,
        )
        self.window.show_report_tab(2)
        self._publish_diagnostic_snapshot()

        export_root = self._resolve_project_relative_path(self.project.settings.export_root)
        self._active_build_scope_label = requested_scope_label
        self._active_build_export_root = export_root
        self._start_build_worker(project_snapshot, export_root, build_request)

    def preview_export_diff(self) -> None:
        self.window.clear_build_status()
        build_request = self._current_build_request()
        if build_request is None:
            message = self._selection_build_unavailable_message()
            self.window.set_build_plan_summary("选中构建未就绪。", message)
            self.window.set_build_report("构建计划不可用\n\n原因：当前选区没有可导出的事件。\n请先选择事件或包含事件的文件夹。")
            self.window.show_report_tab(2)
            self.window.append_log(f"选中构建预览已中止：{message}")
            self._set_build_diagnostic_summary("构建计划不可用。", message, status="warning")
            self._publish_diagnostic_snapshot()
            return
        export_root = self._resolve_project_relative_path(self.project.settings.export_root)
        try:
            plan = self.exporter.plan_export(self.project, export_root, build_request)
            plan_summary, plan_detail = self._format_build_plan_summary(plan)
            self.window.set_build_plan_summary(plan_summary, plan_detail)
            self._set_build_diagnostic_summary(
                plan_summary,
                plan_detail,
                status="info",
                metadata={
                    "requested_scope": plan.requested_scope,
                    "requested_scope_label": self._build_scope_label(plan.requested_scope),
                    "effective_scope": plan.effective_scope,
                    "effective_scope_label": self._build_scope_label(plan.effective_scope),
                    "selection_label": plan.selection_label,
                    "rebuilt_asset_count": len(plan.rebuilt_asset_keys),
                    "reused_asset_count": len(plan.reused_asset_keys),
                    "removed_asset_count": len(plan.removed_asset_keys),
                    "out_of_scope_dirty_count": len(plan.out_of_scope_dirty_asset_keys),
                    "export_root": str(export_root),
                },
            )
            report = self._format_export_diff_preview(export_root, plan)
        except Exception as exc:
            self.window.set_build_plan_summary("构建计划生成失败。", str(exc))
            self._set_build_diagnostic_summary("构建计划生成失败。", str(exc), status="error")
            report = f"导出差异预览失败\n\n导出目录：{export_root}\n原因：{exc}"
            self.window.append_log(f"导出差异预览失败：{exc}")
        self.window.set_build_report(report)
        self.window.show_report_tab(2)
        self.window.append_log("已生成导出差异预览。")
        self._publish_diagnostic_snapshot()

    def _create_build_validator(self) -> ProjectValidator:
        return ProjectValidator()

    def _create_build_exporter(self) -> RuntimeExporter:
        return RuntimeExporter()

    def _is_build_running(self) -> bool:
        return self._build_thread is not None and self._build_thread.isRunning()

    def _start_build_worker(self, project: AudioProject, export_root: Path, build_request: ExportRequest) -> None:
        validator = self._create_build_validator()
        exporter = self._create_build_exporter()
        thread = QThread(self.window)
        worker = _BuildWorker(project, export_root, build_request, validator, exporter)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._handle_build_success)
        worker.validation_blocked.connect(self._handle_build_validation_blocked)
        worker.failed.connect(self._handle_build_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._finalize_build_worker)
        self._build_thread = thread
        self._build_worker = worker
        thread.start()

    @Slot(object, int)
    def _handle_build_validation_blocked(self, issues: list[ValidationIssue], error_count: int) -> None:
        requested_scope_label = self._active_build_scope_label or "当前构建"
        logger.info(
            "Build blocked by validation scope=%s errors=%d",
            requested_scope_label,
            error_count,
        )
        self.window.set_validation_report(self._format_validation_report(issues), issues)
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
        self._set_validation_diagnostic_summary(issues)
        self._set_build_diagnostic_summary(
            "构建已中止。",
            f"{requested_scope_label} 在校验阶段被拦截：存在 {error_count} 个错误。",
            status="error",
            metadata={
                "error_count": error_count,
                "requested_scope_label": requested_scope_label,
                "export_root": str(self._active_build_export_root or self.project.settings.export_root),
            },
        )
        self._publish_diagnostic_snapshot()

    @Slot(str, object)
    def _handle_build_failure(self, error_message: str, plan: ExportPlan | None) -> None:
        requested_scope_label = self._active_build_scope_label or "当前构建"
        export_root = self._active_build_export_root or self._resolve_project_relative_path(self.project.settings.export_root)
        logger.error(
            "Build failed scope=%s export_root=%s error=%s",
            requested_scope_label,
            export_root,
            error_message,
        )
        failure_message = f"构建失败：{error_message}"
        self.window.append_log(failure_message)
        self.window.set_build_status(
            "构建失败。",
            f"模式：{requested_scope_label} | 导出目录：{export_root} | 原因：{error_message}",
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
                    f"原因：{error_message}",
                ]
            )
        )
        self.window.show_report_tab(2)
        self._set_build_diagnostic_summary(
            "构建失败。",
            f"模式：{requested_scope_label} | 导出目录：{export_root} | 原因：{error_message}",
            status="error",
            metadata={
                "requested_scope_label": requested_scope_label,
                "export_root": str(export_root),
                "selection_label": self._active_build_scope_label or requested_scope_label,
            },
        )
        self._publish_diagnostic_snapshot()
        QMessageBox.critical(self.window, "构建失败", error_message)

    @Slot(object, object)
    def _handle_build_success(self, result, issues: list[ValidationIssue]) -> None:
        logger.info(
            "Build succeeded export_root=%s report_file=%s rebuilt_assets=%d reused_assets=%d",
            result.export_root,
            result.report_file,
            len(result.plan.rebuilt_asset_keys),
            len(result.plan.reused_asset_keys),
        )
        requested_scope_label = self._active_build_scope_label or self._build_scope_label(result.plan.requested_scope)
        build_report = self._format_build_report(result.report_file, result.manifest_file)
        self.window.set_validation_report(self._format_validation_report(issues), issues)
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
        self._set_validation_diagnostic_summary(issues)
        self._set_build_diagnostic_summary(
            "构建完成。",
            f"模式：{scope_display} | 已导出到：{result.data_file} | 清单：{result.manifest_file}",
            status="success",
            metadata={
                "requested_scope": result.plan.requested_scope,
                "requested_scope_label": requested_scope_label,
                "effective_scope": result.plan.effective_scope,
                "effective_scope_label": effective_scope_label,
                "selection_label": result.plan.selection_label,
                "rebuilt_asset_count": len(result.plan.rebuilt_asset_keys),
                "reused_asset_count": len(result.plan.reused_asset_keys),
                "removed_asset_count": len(result.plan.removed_asset_keys),
                "out_of_scope_dirty_count": len(result.plan.out_of_scope_dirty_asset_keys),
                "export_root": str(result.export_root),
                "data_file": str(result.data_file),
                "manifest_file": str(result.manifest_file),
            },
        )
        self._publish_diagnostic_snapshot()

    @Slot()
    def _finalize_build_worker(self) -> None:
        logger.info("Build worker cleanup finished.")
        self.window.build_execute_button.setEnabled(True)
        self.window.build_button.setEnabled(True)
        self._build_thread = None
        self._build_worker = None
        self._active_build_scope_label = None
        self._active_build_export_root = None

    def navigate_to_report_target(self, target_type: str, target_id: str) -> None:
        if not target_id:
            return
        if (target_type == "event" and target_id in self.project.events) or (target_type == "auto" and target_id in self.project.events):
            self.select_node("event", target_id)
            self.window.set_active_property_category("事件")
            return
        if target_type == "audio":
            if target_id in self.project.events:
                self.navigate_to_event_audio(target_id)
                return
            if target_id in self.project.audio_objects:
                self.select_audio(target_id)
                self.window.focus_current_audio_browser()
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

    def _classify_event_import_paths(
        self,
        file_paths: list[str],
    ) -> tuple[list[tuple[tuple[str, ...], Path]], list[Path], list[Path], list[Path]]:
        supported_paths: list[tuple[tuple[str, ...], Path]] = []
        skipped_unsupported: list[Path] = []
        skipped_missing: list[Path] = []
        skipped_empty_directories: list[Path] = []
        seen_supported_paths: set[str] = set()

        def add_supported_path(folder_parts: tuple[str, ...], source_path: Path) -> None:
            normalized_key = str(source_path.resolve()).casefold()
            if normalized_key in seen_supported_paths:
                return
            seen_supported_paths.add(normalized_key)
            supported_paths.append((folder_parts, source_path))

        for file_path in file_paths:
            source_path = Path(file_path)
            if not source_path.exists():
                skipped_missing.append(source_path)
                continue
            if source_path.is_dir():
                has_supported_audio = False
                for nested_path in sorted(source_path.rglob("*"), key=lambda candidate: str(candidate.relative_to(source_path)).lower()):
                    if nested_path.is_dir():
                        continue
                    if nested_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                        skipped_unsupported.append(nested_path)
                        continue
                    has_supported_audio = True
                    relative_parent_parts = nested_path.relative_to(source_path).parent.parts
                    folder_parts = (source_path.name, *relative_parent_parts) if relative_parent_parts else (source_path.name,)
                    add_supported_path(folder_parts, nested_path)
                if not has_supported_audio:
                    skipped_empty_directories.append(source_path)
                continue
            if source_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                skipped_unsupported.append(source_path)
                continue
            add_supported_path((), source_path)
        return supported_paths, skipped_unsupported, skipped_missing, skipped_empty_directories

    def _format_import_skip_suffix(
        self,
        skipped_unsupported: list[Path],
        skipped_missing: list[Path],
        skipped_empty_directories: list[Path] | None = None,
    ) -> str:
        skipped_segments: list[str] = []
        if skipped_unsupported:
            skipped_segments.append(f"跳过 {len(skipped_unsupported)} 个不支持的文件")
        if skipped_missing:
            skipped_segments.append(f"跳过 {len(skipped_missing)} 个不存在的文件")
        if skipped_empty_directories:
            skipped_segments.append(f"跳过 {len(skipped_empty_directories)} 个不包含支持音频的文件夹")
        if not skipped_segments:
            return ""
        return " 已忽略：" + "，".join(skipped_segments) + "。"

    def _notify_import_skip(
        self,
        title: str,
        skipped_unsupported: list[Path],
        skipped_missing: list[Path],
        skipped_empty_directories: list[Path] | None = None,
    ) -> None:
        reason = self._format_import_skip_suffix(
            skipped_unsupported,
            skipped_missing,
            skipped_empty_directories,
        ).strip()
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
