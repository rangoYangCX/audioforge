from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audioforge.app.controllers.main_controller import AuditionSession, MainController
from audioforge.app.models.audio_project import ClipModel, EventModel, GameParameterModel, RtpcBindingModel, StateGroupModel, SwitchGroupModel, ValidationIssue
from audioforge.app.services.recovery_service import RecoveryService
from audioforge.app.services.preview_service import PreviewResult
from audioforge.app.utils.constants import MAX_PITCH_CENTS, MIN_PITCH_CENTS, WWISE_BUS_VIEW_LABEL, WWISE_MASTER_MIXER_TITLE
from audioforge.app.widgets.event_tree import encode_source_binding_token
from PySide6.QtWidgets import QAbstractItemView
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from PySide6.QtCore import QSize
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import QToolButton
from shiboken6 import isValid


def _wait_for_build_completion(controller: MainController, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        thread = getattr(controller, "_build_thread", None)
        if thread is None or not thread.isRunning():
            QApplication.processEvents()
            return
    raise AssertionError("Timed out waiting for background build to finish.")


def test_selecting_folder_does_not_reset_active_property_tab(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.set_active_property_category("音频属性")

    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 1

    folder_id = controller.project.root_folder_ids[0]
    controller.select_node("folder", folder_id)

    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 1

    controller.window.close()


def test_switching_from_contents_to_property_editor_keeps_clip_edit_stable(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.property_tabs.setCurrentIndex(1)
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(0)
    controller.window.clip_table.selectRow(0)
    controller.window._sync_clip_detail_from_table()

    controller.window.clip_asset_detail_edit.setText("ui/test_asset")
    controller.window.clip_asset_detail_edit.editingFinished.emit()
    QApplication.processEvents()
    controller.window.editor_tabs.setCurrentIndex(0)
    QApplication.processEvents()

    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.current_event is not None
    assert controller.current_event.clips[0].asset_key == "ui/test_asset"
    assert controller.window.property_tabs.currentIndex() == 1

    controller.is_dirty = False
    controller.window.close()


def test_preview_current_event_uses_preview_gamesync_context(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)]
    controller.project.state_groups = [StateGroupModel(name="CombatState", states=["Explore", "Combat"], default_state="Explore")]
    controller.project.switch_groups = [SwitchGroupModel(name="SurfaceType", switches=["Grass", "Stone"], default_switch="Grass")]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.preview_parameter_name_combo.setCurrentText("PlayerSpeed")
    controller.window.preview_parameter_scope_combo.setCurrentText("Emitter")
    controller.window.preview_parameter_value_spin.setValue(6.0)
    controller.window.preview_state_group_combo.setCurrentText("CombatState")
    controller.window.preview_state_name_combo.setCurrentText("Combat")
    controller.window.preview_switch_group_combo.setCurrentText("SurfaceType")
    controller.window.preview_switch_name_combo.setCurrentText("Stone")
    QApplication.processEvents()

    captured: dict[str, object] = {}

    def fake_preview_event(event, **kwargs):
        captured["event_id"] = event.id
        captured.update(kwargs)
        return PreviewResult(accepted=False, reason="Muted by state override.")

    monkeypatch.setattr(controller.preview_service, "preview_event", fake_preview_event)

    controller.preview_current_event(silent_log=True)

    context = captured["preview_gamesync"]
    assert captured["event_id"] == controller.current_event.id
    assert context.emitter_game_parameters["PlayerSpeed"] == 6.0
    assert context.states["CombatState"] == "Combat"
    assert context.switches["SurfaceType"] == "Stone"

    controller.is_dirty = False
    controller.window.close()


def test_preview_gamesync_change_retriggers_current_event_audition(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)]
    controller._refresh_ui()
    QApplication.processEvents()

    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    controller._audition_session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )

    calls: list[bool] = []
    monkeypatch.setattr(controller, "preview_current_event", lambda silent_log=False: calls.append(silent_log))

    controller.window.preview_parameter_name_combo.setCurrentText("PlayerSpeed")
    controller.window.preview_parameter_scope_combo.setCurrentText("Emitter")
    controller.window.preview_parameter_value_spin.setValue(4.0)
    QApplication.processEvents()

    assert controller.window.activity_preview_host.isAncestorOf(controller.window.preview_gamesync_group)
    assert calls and calls[-1] is True

    controller.is_dirty = False
    controller.window.close()


def test_clip_edit_and_tab_switch_preserve_navigation_layout(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.property_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(1)
    controller.window.content_top_splitter.setSizes([520, 480])
    QApplication.processEvents()
    expected_content_sizes = controller.window.content_top_splitter.sizes()
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(0)
    controller.window.clip_table.selectRow(0)
    controller.window._sync_clip_detail_from_table()

    controller.window.clip_asset_detail_edit.setText("ui/layout_lock")
    controller.window.clip_asset_detail_edit.editingFinished.emit()
    QApplication.processEvents()
    controller.window.editor_tabs.setCurrentIndex(0)
    QApplication.processEvents()

    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 1
    assert controller.window.contents_tabs.currentIndex() == 0
    assert controller.window.content_top_splitter.sizes() == expected_content_sizes

    controller.is_dirty = False
    controller.window.close()


def test_clip_editor_switches_to_compact_layout_when_detail_column_is_narrow(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    controller.window._activate_workspace_mode("resources")
    QApplication.processEvents()

    assert isValid(controller.window.clip_playhead_label)
    controller.window.content_top_splitter.setSizes([540, 260])
    QApplication.processEvents()
    controller.window._apply_clip_editor_responsive_layout()
    QApplication.processEvents()

    sizes = controller.window.content_top_splitter.sizes()

    assert controller.window._clip_editor_layout_mode == "compact"
    assert controller.window.clip_waveform_action_panel.property("layoutMode") == "compact"
    assert controller.window.clip_action_row.property("layoutMode") == "compact"
    assert isValid(controller.window.clip_playhead_label)
    assert sizes[1] >= sizes[0]

    controller.is_dirty = False
    controller.window.close()


def test_two_column_splitters_stack_vertically_at_compact_width(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    event_splitter = controller.window.findChild(QSplitter, "EventDesignPageSplitter")
    route_splitter = controller.window.findChild(QSplitter, "CurrentBusRoutePageSplitter")

    assert event_splitter is not None
    assert route_splitter is not None

    controller.window._apply_responsive_two_column_splitter(event_splitter, available_width=640)
    controller.window._apply_responsive_two_column_splitter(route_splitter, available_width=640)

    assert event_splitter.orientation() == Qt.Orientation.Vertical
    assert route_splitter.orientation() == Qt.Orientation.Vertical

    controller.window._apply_responsive_two_column_splitter(event_splitter, available_width=980)
    controller.window._apply_responsive_two_column_splitter(route_splitter, available_width=980)

    assert event_splitter.orientation() == Qt.Orientation.Horizontal
    assert route_splitter.orientation() == Qt.Orientation.Horizontal

    controller.is_dirty = False
    controller.window.close()


def test_stale_clip_edit_signal_is_ignored_after_clip_list_changes(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    stale_clip_id = controller.current_event.clips[0].id

    controller.current_event.clips.clear()
    controller.window.set_event_details(controller.current_event)

    controller.window.clipEdited.emit(stale_clip_id, "asset_key", "ui/ignored_asset")
    QApplication.processEvents()

    assert controller.current_event is not None
    assert controller.current_event.clips == []

    controller.is_dirty = False
    controller.window.close()


def test_stale_event_property_signal_is_ignored_after_switching_to_folder(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    original_event_id = controller.selected_event_id
    folder_id = controller.project.root_folder_ids[0]

    controller.select_node("folder", folder_id)
    controller.window.eventPropertiesChanged.emit()
    QApplication.processEvents()

    assert controller.selected_event_id is None
    assert original_event_id in controller.project.events

    controller.is_dirty = False
    controller.window.close()


def test_switching_project_bus_selection_commits_previous_bus_editor(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.set_active_property_category("音频属性")
    controller.window._select_project_bus_by_name("UI")
    controller.window.project_bus_name_edit.setText("UI_Custom")

    controller.window._select_project_bus_by_name("SFX")
    QApplication.processEvents()

    bus_names = [config.name for config in controller.project.settings.bus_configs]
    assert "UI_Custom" in bus_names
    assert "SFX" in bus_names
    assert "UI" not in bus_names

    controller.is_dirty = False
    controller.window.close()


def test_switching_to_master_after_adding_child_bus_does_not_raise_invalid_parent_warning(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._select_project_bus_by_name("SFX")
    monkeypatch.setattr(controller.window, "ask_new_bus_name", lambda: "SFX_Sub")

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )

    controller.window._request_add_project_bus()
    QApplication.processEvents()
    controller.window._select_project_bus_by_name("Master")
    QApplication.processEvents()

    assert controller.window.current_project_bus_name() == "Master"
    assert warnings == []

    controller.is_dirty = False
    controller.window.close()


def test_export_root_browse_updates_project_settings(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    selected_path = str(tmp_path / "BuildOutput")
    monkeypatch.setattr(controller.window, "ask_export_root_path", lambda initial_path: selected_path)

    controller.window.export_root_browse_button.click()
    QApplication.processEvents()

    assert controller.window.export_root_edit.text() == selected_path
    assert controller.project.settings.export_root == selected_path

    controller.is_dirty = False
    controller.window.close()


def test_settings_dialog_shows_recent_projects(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.set_recent_projects(["C:/AudioForge/Demo.afproj"])

    controller.window.open_settings_dialog()
    QApplication.processEvents()

    assert controller.window.settings_dialog.isVisible()
    assert controller.window.recent_projects_combo.count() == 1
    assert controller.window.recent_projects_combo.currentText() == "C:/AudioForge/Demo.afproj"

    controller.window.settings_dialog.close()
    controller.is_dirty = False
    controller.window.close()


def test_settings_dialog_import_template_defaults_flow_into_ui_preferences(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    bus_index = controller.window.import_template_bus_combo.findData("UI")

    controller.window.open_settings_dialog()
    controller.window.import_template_bus_combo.setCurrentIndex(bus_index)
    controller.window.import_template_asset_prefix_edit.setText("ui/default")
    controller.window.import_template_asset_prefix_edit.editingFinished.emit()
    controller.window.import_template_tags_edit.setText("ui, default")
    controller.window.import_template_tags_edit.editingFinished.emit()
    QApplication.processEvents()

    preferences = controller.window.ui_preferences()
    assert preferences["event_import_template"] == {
        "bus_name": "UI",
        "asset_prefix": "ui/default",
        "tags": ["ui", "default"],
    }

    controller.window.settings_dialog.close()
    controller.is_dirty = False
    controller.window.close()


def test_project_settings_toggle_smart_bus_assignment(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    controller.window.auto_assign_bus_by_name_check.setChecked(False)
    QApplication.processEvents()

    assert controller.project.settings.auto_assign_bus_by_name is False
    assert controller.window.current_project_settings_form_data()["auto_assign_bus_by_name"] is False

    created = controller._make_casual_event_template(
        "UI_Button_Click",
        display_name="UI Button Click",
        default_bus="SFX",
        available_buses=["BGM", "SFX", "UI"],
    )

    assert created.bus == "SFX"

    controller.is_dirty = False
    controller.window.close()


def test_refresh_ui_keeps_manual_project_bus_selection(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    assert controller.current_event.bus == "UI"

    controller.window._select_project_bus_by_name("SFX")
    QApplication.processEvents()
    controller._refresh_ui()
    QApplication.processEvents()

    assert controller.window.current_project_bus_name() == "SFX"

    controller.is_dirty = False
    controller.window.close()


def test_refresh_ui_preserves_editor_and_splitter_state(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.property_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(2)
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.main_splitter.setSizes([410, 990])
    controller.window.workspace_splitter.setSizes([760, 240])
    controller.window.content_top_splitter.setSizes([540, 460])
    QApplication.processEvents()
    expected_main_sizes = controller.window.main_splitter.sizes()
    expected_workspace_sizes = controller.window.workspace_splitter.sizes()
    expected_content_sizes = controller.window.content_top_splitter.sizes()

    controller._refresh_ui()
    QApplication.processEvents()

    assert controller.window.editor_tabs.currentIndex() == 1
    assert controller.window.property_tabs.currentIndex() == 1
    assert controller.window.contents_tabs.currentIndex() == 2
    assert controller.window.main_splitter.sizes() == expected_main_sizes
    assert controller.window.workspace_splitter.sizes() == expected_workspace_sizes
    assert controller.window.content_top_splitter.sizes() == expected_content_sizes

    controller.is_dirty = False
    controller.window.close()


def test_workspace_mode_switch_keeps_main_editor_width(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1280, 800)
    controller.window.show()
    QApplication.processEvents()

    controller.window._activate_workspace_mode("events")
    controller.window.main_splitter.setSizes([290, 788])
    QApplication.processEvents()
    expected_main_sizes = controller.window.main_splitter.sizes()

    for mode in ["build", "validation", "results", "gamesync", "events"]:
        controller.window._activate_workspace_mode(mode)
        QApplication.processEvents()

        assert controller.window.main_splitter.sizes() == expected_main_sizes
        assert controller.window.workspace_mode_stack.width() == expected_main_sizes[1]
        assert controller.window.workspace_mode_stack.currentWidget() is not None
        assert controller.window.workspace_mode_stack.currentWidget().width() == expected_main_sizes[1]

    controller.is_dirty = False
    controller.window.close()


def test_gamesync_workspace_and_explorer_tab_are_available(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    explorer_tabs = [controller.window.explorer_tabs.tabText(index) for index in range(controller.window.explorer_tabs.count())]
    assert "GameSync" in explorer_tabs
    assert controller.window.task_sidebar.button("gamesync") is not None

    controller.window._activate_workspace_mode("gamesync")
    QApplication.processEvents()

    assert controller.window.workspace_mode_stack.currentWidget() == controller.window._workspace_mode_pages["gamesync"]
    assert controller.window.status_label.text() == "当前工作区：GameSync"

    controller.is_dirty = False
    controller.window.close()


def test_activity_panel_defaults_to_compact_and_can_expand(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    compact_height = controller.window.workspace_splitter.sizes()[1]
    assert compact_height == controller.window._minimum_report_panel_height
    assert not controller.window.activity_detail_container.isVisible()
    assert controller.window.activity_toggle_button.text() == "展开"

    controller.window.activity_toggle_button.click()
    QApplication.processEvents()

    expanded_height = controller.window.workspace_splitter.sizes()[1]
    assert expanded_height >= controller.window._expanded_report_panel_min_height
    assert controller.window.activity_detail_container.isVisible()
    assert controller.window.activity_toggle_button.text() == "收起"

    controller.window.activity_toggle_button.click()
    QApplication.processEvents()

    assert controller.window.workspace_splitter.sizes()[1] == controller.window._minimum_report_panel_height
    assert not controller.window.activity_detail_container.isVisible()
    assert controller.window.activity_toggle_button.text() == "展开"

    controller.is_dirty = False
    controller.window.close()


def test_home_page_keeps_direct_workspace_entry_actions(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("home")
    QApplication.processEvents()

    home_page = controller.window.workspace_mode_stack.currentWidget()
    buttons = {
        button.text(): button
        for button in home_page.findChildren(QPushButton)
        if button.text() in {"新建工程", "打开工程", "进入事件设计", "查看结果中心", "事件设计", "资源整理", WWISE_MASTER_MIXER_TITLE, "结果中心"}
    }

    assert "新建工程" in buttons
    assert "打开工程" in buttons
    assert "进入事件设计" in buttons
    assert "查看结果中心" in buttons
    assert "事件设计" in buttons
    assert "资源整理" in buttons
    assert WWISE_MASTER_MIXER_TITLE in buttons
    assert "结果中心" in buttons

    controller.is_dirty = False
    controller.window.close()


def test_focus_panel_log_expands_activity_panel_and_restore_default_layout_compacts_it(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    assert controller.window.workspace_splitter.sizes()[1] == controller.window._minimum_report_panel_height

    controller.window.focus_panel("log")
    QApplication.processEvents()

    assert controller.window.workspace_splitter.sizes()[1] >= controller.window._expanded_report_panel_min_height
    assert controller.window.activity_detail_container.isVisible()

    controller.window.restore_default_layout()
    QApplication.processEvents()

    assert controller.window.workspace_splitter.sizes()[1] == controller.window._minimum_report_panel_height
    assert not controller.window.activity_detail_container.isVisible()

    controller.is_dirty = False
    controller.window.close()


def test_restore_default_layout_resets_tabs_and_reports(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.property_tabs.setCurrentIndex(2)
    controller.window.contents_tabs.setCurrentIndex(2)
    controller.window.report_tabs.setCurrentIndex(3)

    controller.window.restore_default_layout()
    QApplication.processEvents()

    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 0
    assert controller.window.contents_tabs.currentIndex() == 0
    assert controller.window.report_tabs.currentIndex() == 0
    assert controller.window.report_detail_label.text() == "已恢复默认布局。"

    controller.is_dirty = False
    controller.window.close()


def test_switching_contents_tabs_keeps_log_panel_visible(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    controller.window.set_active_contents_category("片段")
    QApplication.processEvents()
    controller.window.set_active_contents_category("批处理")
    QApplication.processEvents()
    controller.window.set_active_contents_category("生成")
    QApplication.processEvents()
    controller.window.set_active_contents_category("片段")
    QApplication.processEvents()

    bottom_height = controller.window.workspace_splitter.sizes()[1]
    assert bottom_height >= controller.window._minimum_report_panel_height
    assert controller.window.log_panel.isVisible()

    controller.is_dirty = False
    controller.window.close()


def test_switching_editor_tabs_keeps_log_panel_visible(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    controller.window.editor_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    controller.window.editor_tabs.setCurrentIndex(2)
    QApplication.processEvents()
    controller.window.editor_tabs.setCurrentIndex(0)
    QApplication.processEvents()
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.set_active_contents_category("片段")
    QApplication.processEvents()

    bottom_height = controller.window.workspace_splitter.sizes()[1]
    assert bottom_height >= controller.window._minimum_report_panel_height
    assert controller.window.log_panel.isVisible()

    controller.is_dirty = False
    controller.window.close()


def test_detaching_explorer_opens_floating_window_and_frees_main_space(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    docked_sizes = controller.window.main_splitter.sizes()
    controller.window.detach_explorer_panel()
    QApplication.processEvents()

    assert controller.window._explorer_detached is True
    assert controller.window.explorer_window.isVisible()
    assert controller.window.explorer_window.isWindow() is True
    detached_sizes = controller.window.main_splitter.sizes()
    assert detached_sizes[1] > docked_sizes[1]
    assert controller.window.tree.parentWidget() is not None

    controller.is_dirty = False
    controller.window.close()


def test_closing_detached_explorer_reattaches_panel(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(1440, 900)
    controller.window.show()
    QApplication.processEvents()

    controller.window.detach_explorer_panel()
    QApplication.processEvents()
    expected_sizes = list(controller.window._last_docked_main_splitter_sizes)

    controller.window.explorer_window.close()
    QApplication.processEvents()

    assert controller.window._explorer_detached is False
    assert controller.window.explorer_window.isVisible() is False
    assert controller.window.main_splitter.widget(0) is controller.window.explorer_panel
    assert controller.window._effective_main_splitter_sizes() == expected_sizes

    controller.is_dirty = False
    controller.window.close()


def test_selecting_different_event_resets_project_bus_selection_to_event_bus(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    bgm_event = controller._make_casual_event_template(
        "BGM_Menu",
        display_name="菜单音乐",
        default_bus=controller.project.settings.default_bus,
        available_buses=controller.project.settings.buses,
        suggested_bus="BGM",
    )
    bgm_event.clips.append(
        ClipModel(
            id="bgm_menu_01",
            source_path="",
            export_path="bgm/menu_01",
            asset_key="bgm/menu_01",
        )
    )
    controller.project.add_event(root_folder_id, bgm_event)

    controller.window._select_project_bus_by_name("SFX")
    QApplication.processEvents()
    controller.select_node("event", "BGM_Menu")
    QApplication.processEvents()

    assert controller.window.current_project_bus_name() == "BGM"

    controller.is_dirty = False
    controller.window.close()


def test_manual_project_bus_selection_updates_object_status(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._select_project_bus_by_name("SFX")
    QApplication.processEvents()

    assert controller.window.object_event_bus_chip.text() == "输出 Bus UI"
    assert controller.window.object_bus_browser_chip.text() == "Bus 视图 SFX"

    controller.is_dirty = False
    controller.window.close()


def test_explorer_tabs_include_bus_source_event_and_source_tree_uses_project_assets(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_file = tmp_path / "ui" / "click.wav"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"fake-wav")

    controller.current_event.clips[0].source_path = str(source_file)
    controller.current_event.clips[0].asset_key = "ui/click"
    controller.project.register_source_asset(str(source_file))
    controller._refresh_ui()
    QApplication.processEvents()

    assert controller.window.explorer_tabs.count() == 5
    assert [controller.window.explorer_tabs.tabText(index) for index in range(controller.window.explorer_tabs.count())] == [
        "总线树",
        "源音频树",
        "Audio 树",
        "事件树",
        "GameSync",
    ]

    controller.window.source_tree.select_source_path(str(source_file))
    QApplication.processEvents()

    assert controller.window.source_tree.current_source_path() == str(source_file)
    assert controller.window.source_browser_summary_label.text().startswith("源音频 1 条")
    assert "引用 Audio 1 个" in controller.window.source_browser_status_label.text()

    controller.is_dirty = False
    controller.window.close()


def test_route_graph_master_node_switches_to_master_bus_view(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    controller.window._activate_workspace_mode("buses")
    controller.window._select_project_bus_by_name("SFX")
    QApplication.processEvents()

    route_nodes = [
        button
        for button in controller.window.project_bus_route_bar.findChildren(QToolButton)
        if button.property("role") == "routeNode"
    ]
    master_node = next(button for button in route_nodes if button.text().startswith("Master\n"))

    master_node.click()
    QApplication.processEvents()

    assert controller.window.current_project_bus_name() == "Master"
    assert controller.window.object_bus_browser_chip.text() == f"{WWISE_BUS_VIEW_LABEL} Master"
    assert controller.window.project_master_volume_spin.hasFocus()

    controller.is_dirty = False
    controller.window.close()


def test_resources_batch_feedback_persists_after_bulk_weight(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(0)
    controller.window.clip_table.selectRow(0)
    QApplication.processEvents()

    controller.apply_bulk_weight(7)
    QApplication.processEvents()

    assert controller.window.resources_batch_feedback_title_label.text() == "批量权重已应用"
    assert controller.window.resources_batch_feedback_field_label.text() == "字段 权重"
    assert controller.window.resources_batch_feedback_summary_label.text() == "已将 1 个片段的权重统一为 7。"

    controller._refresh_ui()
    QApplication.processEvents()

    assert controller.window.resources_batch_feedback_title_label.text() == "批量权重已应用"
    assert controller.window.resources_batch_feedback_summary_label.text() == "已将 1 个片段的权重统一为 7。"

    controller.is_dirty = False
    controller.window.close()


def test_command_palette_and_global_search_aliases_cover_bus_workspace_and_batch_feedback(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    commands = controller.window._command_palette_items()
    command_titles = [command["title"] for command in commands]

    bus_alias_matches = controller.window._filter_command_palette_items("父bus", commands)
    english_alias_matches = controller.window._filter_command_palette_items("master-mixer", commands)

    assert any(command["title"] == f"切到 {WWISE_MASTER_MIXER_TITLE}" for _index, command in bus_alias_matches)
    assert any(command["title"] == f"切到 {WWISE_MASTER_MIXER_TITLE}" for _index, command in english_alias_matches)
    assert "打开日志结果" not in command_titles
    assert "打开校验结果" not in command_titles
    assert "打开构建结果" not in command_titles
    assert "打开响度结果" not in command_titles

    global_candidates = controller.window._global_search_candidates()
    global_matches = controller.window._filter_global_search_candidates("批量反馈", global_candidates)
    assert any(candidate["title"] == "工作区 | 资源整理" for candidate in global_matches)
    assert any(candidate["title"] == "工作区 | 结果中心" for candidate in global_candidates)
    assert not any(str(candidate["title"]).startswith("结果页 | ") for candidate in global_candidates)

    controller.is_dirty = False
    controller.window.close()


def test_current_event_source_bindings_can_append_and_replace_via_controller(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_a = tmp_path / "ui" / "click_a.wav"
    source_b = tmp_path / "ui" / "click_b.wav"
    source_c = tmp_path / "ui" / "click_c.wav"
    for path in [source_a, source_b, source_c]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="click_a", source_path=str(source_a), export_path="ui/click_a", asset_key="ui/click_a")
    ]
    for path in [source_a, source_b, source_c]:
        controller.project.register_source_asset(str(path))
    controller._refresh_ui()
    QApplication.processEvents()

    controller.assign_source_assets_to_current_audio([str(source_b), str(source_c)], replace_existing=False)
    QApplication.processEvents()

    assert {clip.source_path for clip in controller.current_event.clips} == {str(source_a), str(source_b), str(source_c)}
    assert "当前 Audio 已绑定 3 个源音频" in controller.window.event_source_binding_summary_label.text()

    controller.assign_source_assets_to_current_audio([str(source_c)], replace_existing=True)
    QApplication.processEvents()

    assert [clip.source_path for clip in controller.current_event.clips] == [str(source_c)]
    assert "当前 Audio 已绑定 1 个源音频" in controller.window.event_source_binding_summary_label.text()

    controller.is_dirty = False
    controller.window.close()


def test_event_and_audio_design_pages_are_split(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    event_page = controller.window.event_design_scroll.widget()
    event_splitter = event_page.layout().itemAt(0).widget().layout().itemAt(0).widget()
    event_left_container = event_splitter.widget(0)
    event_right_container = event_splitter.widget(1)
    audio_page = controller.window.audio_design_scroll.widget()
    audio_splitter = audio_page.layout().itemAt(0).widget().layout().itemAt(0).widget()
    audio_right_container = audio_splitter.widget(1)

    assert event_right_container.layout().itemAt(0).widget() is controller.window.event_audio_reference_group.parentWidget()
    assert event_right_container.layout().itemAt(1).widget() is controller.window.notes_group.parentWidget()
    assert audio_right_container.layout().itemAt(1).widget() is controller.window.event_source_binding_group.parentWidget()
    assert audio_page.layout().itemAt(1).widget() is controller.window.event_gamesync_group.parentWidget()

    controller.is_dirty = False
    controller.window.close()


def test_gamesync_workspace_edits_update_project_models(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("gamesync")
    controller.window.gamesync_workspace_tabs.setCurrentIndex(1)

    controller.window.gamesync_parameter_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_parameter_name_edit.setText("PlayerSpeed")
    controller.window.gamesync_parameter_name_edit.editingFinished.emit()
    controller.window.gamesync_parameter_default_spin.setValue(3.5)
    controller.window.gamesync_parameter_min_spin.setValue(0.0)
    controller.window.gamesync_parameter_max_spin.setValue(10.0)
    controller.window.gamesync_parameter_notes_edit.setPlainText("驱动 RTPC。")
    QApplication.processEvents()

    assert len(controller.project.game_parameters) == 1
    assert controller.project.game_parameters[0].name == "PlayerSpeed"
    assert controller.project.game_parameters[0].default_value == 3.5

    controller.is_dirty = False
    controller.window.close()


def test_gamesync_workspace_supports_explicit_state_and_switch_children(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("gamesync")

    controller.window.gamesync_workspace_tabs.setCurrentIndex(2)
    controller.window.gamesync_state_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_state_name_edit.setText("QuestState")
    controller.window.gamesync_state_name_edit.editingFinished.emit()
    controller.window.gamesync_state_value_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_state_values_edit.setText("Yes")
    controller.window.gamesync_state_values_edit.editingFinished.emit()
    controller.window.gamesync_state_value_volume_spin.setValue(2.5)
    controller.window.gamesync_state_value_pitch_spin.setValue(45)
    controller.window.gamesync_state_value_notes_edit.setPlainText("肯定分支更亮。")
    QApplication.processEvents()
    controller.window.gamesync_state_value_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_state_values_edit.setText("No")
    controller.window.gamesync_state_values_edit.editingFinished.emit()

    controller.window.gamesync_workspace_tabs.setCurrentIndex(3)
    controller.window.gamesync_switch_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_switch_name_edit.setText("SurfaceType")
    controller.window.gamesync_switch_name_edit.editingFinished.emit()
    controller.window.gamesync_switch_value_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_switch_values_edit.setText("Grass")
    controller.window.gamesync_switch_values_edit.editingFinished.emit()
    controller.window.gamesync_switch_value_add_button.click()
    QApplication.processEvents()
    controller.window.gamesync_switch_values_edit.setText("Stone")
    controller.window.gamesync_switch_values_edit.editingFinished.emit()
    controller.window.gamesync_switch_value_volume_spin.setValue(-1.5)
    controller.window.gamesync_switch_value_mute_check.setChecked(True)
    QApplication.processEvents()

    assert controller.project.state_groups[0].states == ["Yes", "No"]
    assert controller.project.state_groups[0].state_effects["Yes"].volume_db == 2.5
    assert controller.project.state_groups[0].state_effects["Yes"].pitch_cents == 45
    assert controller.project.switch_groups[0].switches == ["Grass", "Stone"]
    assert controller.project.switch_groups[0].switch_effects["Stone"].volume_db == -1.5
    assert controller.project.switch_groups[0].switch_effects["Stone"].is_muted is True

    controller.is_dirty = False
    controller.window.close()


def test_gamesync_workspace_mutation_preserves_active_tab(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("gamesync")
    controller.window.gamesync_workspace_tabs.setCurrentIndex(2)

    controller.window.gamesync_state_add_button.click()
    QApplication.processEvents()

    assert controller.window.gamesync_workspace_tabs.currentIndex() == 2
    assert len(controller.project.state_groups) == 1

    controller.is_dirty = False
    controller.window.close()


def test_navigation_state_restores_gamesync_workspace_tab(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("gamesync")
    controller.window.gamesync_workspace_tabs.setCurrentIndex(3)
    QApplication.processEvents()

    state = controller.window.navigation_state()
    controller.window.gamesync_workspace_tabs.setCurrentIndex(0)
    controller.window.apply_navigation_state(state)

    assert controller.window.gamesync_workspace_tabs.currentIndex() == 3

    controller.is_dirty = False
    controller.window.close()


def test_buses_workspace_uses_tabs_and_restores_selected_tab(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window._activate_workspace_mode("buses")
    QApplication.processEvents()

    assert controller.window.buses_workspace_tabs.count() == 3
    assert [controller.window.buses_workspace_tabs.tabText(index) for index in range(controller.window.buses_workspace_tabs.count())] == [
        "当前 Bus",
        "工程总览",
        "Bus GameSync",
    ]
    assert controller.window.current_bus_detail_tabs.count() == 2
    assert [controller.window.current_bus_detail_tabs.tabText(index) for index in range(controller.window.current_bus_detail_tabs.count())] == [
        "路由",
        "电平/导出",
    ]

    controller.window.buses_workspace_tabs.setCurrentIndex(2)
    controller.window.current_bus_detail_tabs.setCurrentIndex(1)
    QApplication.processEvents()
    state = controller.window.navigation_state()
    controller.window.buses_workspace_tabs.setCurrentIndex(0)
    controller.window.current_bus_detail_tabs.setCurrentIndex(0)
    controller.window.apply_navigation_state(state)

    assert controller.window.buses_workspace_tabs.currentIndex() == 2
    assert controller.window.current_bus_detail_tabs.currentIndex() == 1

    controller.is_dirty = False
    controller.window.close()


def test_event_and_bus_gamesync_bindings_update_project_models(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="PlayerSpeed")]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.event_rtpc_add_button.click()
    QApplication.processEvents()
    controller.window.event_rtpc_parameter_edit.setCurrentText("PlayerSpeed")
    controller.window.event_rtpc_scope_combo.setCurrentText("Emitter")
    QApplication.processEvents()

    controller.window._select_project_bus_by_name("UI")
    QApplication.processEvents()
    controller.window.bus_state_add_button.click()
    QApplication.processEvents()
    controller.window.bus_state_group_edit.setText("MusicState")
    controller.window.bus_state_group_edit.editingFinished.emit()
    controller.window.bus_state_name_edit.setText("Combat")
    controller.window.bus_state_name_edit.editingFinished.emit()
    controller.window.bus_state_volume_spin.setValue(2.0)
    QApplication.processEvents()

    assert controller.current_event is not None
    assert controller.current_event.rtpc_bindings[0].parameter_name == "PlayerSpeed"
    assert controller.current_event.rtpc_bindings[0].scope == "Emitter"
    ui_bus = next(config for config in controller.project.settings.bus_configs if config.name == "UI")
    assert ui_bus.state_overrides[0].group_name == "MusicState"
    assert ui_bus.state_overrides[0].state_name == "Combat"
    assert ui_bus.state_overrides[0].volume_db == 2.0

    controller.is_dirty = False
    controller.window.close()


def test_event_gamesync_bindings_only_select_project_definitions(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="PlayerSpeed")]
    controller.project.state_groups = [StateGroupModel(name="QuestState", states=["Completed", "Failed"], default_state="Completed")]
    controller.project.switch_groups = [SwitchGroupModel(name="SurfaceType", switches=["Grass", "Stone"], default_switch="Grass")]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.event_rtpc_add_button.click()
    QApplication.processEvents()
    controller.window.event_rtpc_parameter_edit.setCurrentText("PlayerSpeed")

    controller.window.event_state_add_button.click()
    QApplication.processEvents()
    controller.window.event_state_group_edit.setCurrentText("QuestState")
    controller.window.event_state_name_edit.setCurrentText("Completed")

    controller.window.event_switch_add_button.click()
    QApplication.processEvents()
    controller.window.event_switch_group_edit.setCurrentText("SurfaceType")
    controller.window.event_switch_name_edit.setCurrentText("Stone")
    controller.window.event_rtpc_parameter_edit.setCurrentText("UnknownParameter")
    QApplication.processEvents()

    assert [parameter.name for parameter in controller.project.game_parameters] == ["PlayerSpeed"]
    assert controller.project.state_groups[0].states == ["Completed", "Failed"]
    assert controller.project.switch_groups[0].switches == ["Grass", "Stone"]
    assert controller.window.event_rtpc_parameter_edit.isEditable() is False
    assert controller.window.event_state_group_edit.isEditable() is False
    assert controller.window.event_switch_group_edit.isEditable() is False
    assert controller.current_event is not None
    assert controller.current_event.rtpc_bindings[0].parameter_name == "PlayerSpeed"
    assert controller.current_event.state_overrides[0].group_name == "QuestState"
    assert controller.current_event.state_overrides[0].state_name == "Completed"
    assert controller.current_event.switch_variants[0].group_name == "SurfaceType"
    assert controller.current_event.switch_variants[0].switch_name == "Stone"

    controller.is_dirty = False
    controller.window.close()


def test_preview_gamesync_parameter_editor_supports_negative_ranges(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="SignedBlend", default_value=-3.0, min_value=-12.0, max_value=6.0)]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.preview_parameter_name_combo.setCurrentText("SignedBlend")
    QApplication.processEvents()

    assert controller.window.preview_parameter_value_spin.keyboardTracking() is False
    assert controller.window.preview_parameter_value_spin.minimum() == -12.0
    assert controller.window.preview_parameter_value_spin.maximum() == 6.0
    assert controller.window.preview_parameter_slider.isEnabled() is True
    assert controller.window.preview_parameter_min_label.text() == "-12"
    assert controller.window.preview_parameter_max_label.text() == "6"

    controller.window.preview_parameter_slider.setValue(controller.window.preview_parameter_slider.maximum())
    QApplication.processEvents()

    assert controller.window.preview_parameter_value_spin.value() == 6.0
    assert controller.window.preview_parameter_current_label.text() == "6"

    controller.is_dirty = False
    controller.window.close()


def test_rtpc_curve_editor_uses_parameter_and_target_ranges(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="SignedBlend", default_value=0.0, min_value=-10.0, max_value=8.0)]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.event_rtpc_add_button.click()
    QApplication.processEvents()
    controller.window.event_rtpc_parameter_edit.setCurrentText("SignedBlend")
    controller.window.event_rtpc_target_combo.setCurrentText("EventPitchCents")
    QApplication.processEvents()

    assert controller.window.event_rtpc_selected_input_spin.minimum() == -10.0
    assert controller.window.event_rtpc_selected_input_spin.maximum() == 8.0
    assert controller.window.event_rtpc_selected_output_spin.minimum() == float(MIN_PITCH_CENTS)
    assert controller.window.event_rtpc_selected_output_spin.maximum() == float(MAX_PITCH_CENTS)
    assert controller.window.event_rtpc_curve_table._x_range() == (-10.0, 8.0)
    assert controller.window.event_rtpc_curve_table._y_range() == (float(MIN_PITCH_CENTS), float(MAX_PITCH_CENTS))

    controller.is_dirty = False
    controller.window.close()


def test_audio_source_binding_summary_panel_is_read_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_a = tmp_path / "ui" / "read_only_a.wav"
    source_b = tmp_path / "ui" / "read_only_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="read_only_a", source_path=str(source_a), export_path="ui/read_only_a", asset_key="ui/read_only_a"),
        ClipModel(id="read_only_b", source_path=str(source_b), export_path="ui/read_only_b", asset_key="ui/read_only_b"),
    ]
    controller._refresh_ui()
    controller.window.show()
    controller.window._activate_workspace_mode("events")
    controller.window.set_active_property_category("音频属性")
    QApplication.processEvents()

    overview_cards = [
        controller.window.event_source_binding_overview_layout.itemAt(index).widget()
        for index in range(controller.window.event_source_binding_overview_layout.count())
        if controller.window.event_source_binding_overview_layout.itemAt(index).widget() is not None
    ]

    assert controller.window.event_source_binding_overview_scroll.isVisibleTo(controller.window) is True
    assert len(overview_cards) == 2
    assert "当前 Audio 已绑定 2 个源音频" in controller.window.event_source_binding_summary_label.text()
    assert "Audio 树中定位当前对象后打开 Audio 绑定" in controller.window.event_source_binding_detail_label.text()

    controller.is_dirty = False
    controller.window.close()


def test_audio_bindings_popup_drop_zone_appends_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    controller.current_event.play_mode = "Random"
    controller.current_event.clips = []
    controller._refresh_ui()
    QApplication.processEvents()

    source_a = tmp_path / "ui" / "drag_a.wav"
    source_b = tmp_path / "ui" / "drag_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.open_audio_bindings_popup(controller.current_event.id, controller.window.mapToGlobal(controller.window.rect().center()))
    QApplication.processEvents()

    popup = controller.window._ensure_audio_bindings_popup()
    popup.drop_zone.sourceAssetsDropped.emit([str(source_a), str(source_b)])
    QApplication.processEvents()

    assert controller.current_event is not None
    assert {clip.source_path for clip in controller.current_event.clips} == {str(source_a), str(source_b)}
    assert all(clip.active for clip in controller.current_event.clips)
    assert controller.window.event_source_binding_detail_label.text().startswith("已成功向事件")

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_can_append_multiple_selected_sources_to_current_audio(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    controller.current_event.clips = []

    source_a = tmp_path / "ui" / "multi_a.wav"
    source_b = tmp_path / "ui" / "multi_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
        controller.project.register_source_asset(str(path))

    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.source_tree.set_selected_source_paths([str(source_a), str(source_b)])
    controller.window._refresh_source_browser_tree()
    QApplication.processEvents()
    controller.window.source_browser_add_to_event_button.click()
    QApplication.processEvents()

    assert controller.current_event is not None
    assert {clip.source_path for clip in controller.current_event.clips} == {str(source_a), str(source_b)}
    assert set(controller.window.source_tree.selected_source_paths()) == {str(source_a), str(source_b)}
    assert controller.window.source_tree.selectionMode() == QAbstractItemView.SelectionMode.MultiSelection

    controller.is_dirty = False
    controller.window.close()


def test_audio_gamesync_group_title_tracks_current_audio_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    root_folder_id = controller.project.root_folder_ids[0]

    source_path = tmp_path / "ui" / "audio_ctx.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")

    other_event = EventModel(
        id="UI_Audio_Context",
        display_name="UI Audio Context",
        clips=[ClipModel(id="audio_ctx", source_path=str(source_path), export_path="ui/audio_ctx", asset_key="ui/audio_ctx")],
    )
    other_event.audio.rtpc_bindings = [
        RtpcBindingModel(parameter_name="PlayerSpeed", target="EventVolumeDb", scope="Emitter", curve_points=[])
    ]
    controller.project.add_event(root_folder_id, other_event)
    controller._refresh_ui()
    QApplication.processEvents()

    controller.select_node("event", other_event.id)
    QApplication.processEvents()

    assert controller.window.event_gamesync_group.title() == "Audio GameSync 绑定 | UI Audio Context"
    assert controller.window.event_gamesync_context_label.text() == f"当前 Audio：{other_event.audio_id}"

    controller.is_dirty = False
    controller.window.close()


def test_source_binding_tree_selection_and_delete_remove_clip_only(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_a = tmp_path / "ui" / "click_a.wav"
    source_b = tmp_path / "ui" / "click_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="click_a", source_path=str(source_a), export_path="ui/click_a", asset_key="ui/click_a"),
        ClipModel(id="click_b", source_path=str(source_b), export_path="ui/click_b", asset_key="ui/click_b"),
    ]
    controller.project.register_source_asset(str(source_a))
    controller.project.register_source_asset(str(source_b))
    controller._refresh_ui()
    QApplication.processEvents()

    source_binding_token = encode_source_binding_token(controller.current_event.id, "click_b")
    controller.select_node("source_binding", source_binding_token)
    QApplication.processEvents()

    assert controller.selected_event_id == controller.current_event.id
    assert controller.window.selected_clip_ids() == ["click_b"]

    monkeypatch.setattr(controller.window, "confirm_delete", lambda label: True)
    controller.delete_selected()
    QApplication.processEvents()

    assert controller.selected_event_id == controller.current_event.id
    assert controller.current_event is not None
    assert controller.current_event.id in controller.project.events
    assert [clip.id for clip in controller.current_event.clips] == ["click_a"]

    controller.is_dirty = False
    controller.window.close()


def test_event_tree_source_asset_drop_creates_audio_source_binding(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    event_id = controller.current_event.id
    controller.current_event.clips = []
    controller._refresh_ui()
    QApplication.processEvents()
    source_path = tmp_path / "ui" / "drag_source.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")

    controller.window.tree.sourceAssetsDroppedToAudio.emit([str(source_path)], event_id)
    QApplication.processEvents()

    assert controller.current_event is not None
    assert [clip.source_path for clip in controller.current_event.clips] == [str(source_path)]
    created_clip_id = controller.current_event.clips[0].id
    source_binding_token = encode_source_binding_token(event_id, created_clip_id)
    assert controller.window.tree._find_item("source_binding", source_binding_token) is None
    assert controller.window.selected_clip_ids() == [created_clip_id]

    controller.is_dirty = False
    controller.window.close()


def test_audio_tree_external_drop_without_event_creation_creates_audio_object(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_path = tmp_path / "ui" / "library_click.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")
    monkeypatch.setattr(controller.window, "ask_audio_import_create_events", lambda count: False)

    controller.window.audio_tree.audioFilesDropped.emit([str(source_path)], None)
    QApplication.processEvents()

    assert controller.selected_event_id is None
    assert controller.selected_audio_id is not None
    audio = controller.project.audio_objects[controller.selected_audio_id]
    assert [clip.source_path for clip in audio.clips] == [str(source_path)]

    controller.window.source_tree.select_source_path(str(source_path))
    entry = controller.window.source_tree.current_source_entry()
    assert entry is not None
    assert entry["audio_ids"] == [audio.id]
    assert entry["event_ids"] == []
    assert entry["reference_count"] == 1
    assert entry["unreferenced"] is False

    controller.is_dirty = False
    controller.window.close()


def test_audio_tree_external_drop_with_event_creation_creates_same_name_event(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_path = tmp_path / "ui" / "hover.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")
    monkeypatch.setattr(controller.window, "ask_audio_import_create_events", lambda count: True)

    controller.window.audio_tree.audioFilesDropped.emit([str(source_path)], None)
    QApplication.processEvents()

    assert controller.selected_event_id is not None
    assert controller.current_event is not None
    assert controller.current_event.audio_id in controller.project.audio_objects
    audio = controller.project.audio_objects[controller.current_event.audio_id]
    assert audio.display_name == "hover"
    assert [clip.source_path for clip in audio.clips] == [str(source_path)]

    controller.is_dirty = False
    controller.window.close()


def test_audio_tree_external_drop_to_existing_audio_appends_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    target_audio_id = controller.current_event.audio_id

    source_a = tmp_path / "ui" / "base.wav"
    source_b = tmp_path / "ui" / "append.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
    controller.current_event.clips = [ClipModel(id="base", source_path=str(source_a), export_path="ui/base", asset_key="ui/base")]
    controller.project.register_source_asset(str(source_a))
    controller._refresh_ui()
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_audio_import_binding_mode", lambda audio_name: "append")

    controller.window.audio_tree.audioFilesDropped.emit([str(source_b)], target_audio_id)
    QApplication.processEvents()

    assert controller.current_event is not None
    assert [clip.source_path for clip in controller.current_event.clips] == [str(source_a), str(source_b)]

    controller.is_dirty = False
    controller.window.close()


def test_source_tree_external_drop_registers_unreferenced_asset(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_path = tmp_path / "ui" / "library_only.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")

    controller.window.source_tree.importFilesDropped.emit([str(source_path)])
    QApplication.processEvents()

    assert str(source_path) in controller.project.asset_registry
    controller.window.source_tree.select_source_path(str(source_path))
    entry = controller.window.source_tree.current_source_entry()
    assert entry is not None
    assert entry["audio_ids"] == []
    assert entry["event_ids"] == []
    assert entry["reference_count"] == 0
    assert entry["unreferenced"] is True

    controller.is_dirty = False
    controller.window.close()


def test_audio_bindings_popup_can_toggle_multiple_active_states_for_random(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    event_id = controller.current_event.id
    controller.current_event.play_mode = "Random"

    source_a = tmp_path / "ui" / "popup_a.wav"
    source_b = tmp_path / "ui" / "popup_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="popup_a", source_path=str(source_a), export_path="ui/popup_a", asset_key="ui/popup_a", enabled=True, active=True),
        ClipModel(id="popup_b", source_path=str(source_b), export_path="ui/popup_b", asset_key="ui/popup_b", enabled=True, active=True),
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.open_audio_bindings_popup(event_id, controller.window.mapToGlobal(controller.window.rect().center()))
    QApplication.processEvents()

    assert controller.window.current_audio_bindings_popup_event_id() == event_id

    controller.window.audioSourceBindingActiveChangedRequested.emit(event_id, "popup_b", False)
    QApplication.processEvents()

    assert controller.current_event is not None
    assert controller.current_event.clips[0].active is True
    assert controller.current_event.clips[1].active is False

    controller.window.audioSourceBindingEnabledChangedRequested.emit(event_id, "popup_a", False)
    QApplication.processEvents()

    assert controller.current_event.clips[0].enabled is False
    assert controller.current_event.clips[0].active is False
    assert controller.current_event.clips[1].active is True

    assert controller.window.event_source_binding_detail_label.text().startswith("已将 Audio 绑定 popup_a 标记为停用")

    controller.is_dirty = False
    controller.window.close()


def test_audio_bindings_popup_keeps_one_active_binding_for_one_shot(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    event_id = controller.current_event.id
    controller.current_event.play_mode = "OneShot"

    source_a = tmp_path / "ui" / "oneshot_a.wav"
    source_b = tmp_path / "ui" / "oneshot_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="oneshot_a", source_path=str(source_a), export_path="ui/oneshot_a", asset_key="ui/oneshot_a", enabled=True, active=True),
        ClipModel(id="oneshot_b", source_path=str(source_b), export_path="ui/oneshot_b", asset_key="ui/oneshot_b", enabled=True, active=False),
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.audioSourceBindingActiveChangedRequested.emit(event_id, "oneshot_b", True)
    QApplication.processEvents()

    assert controller.current_event.clips[0].active is False
    assert controller.current_event.clips[1].active is True
    assert controller.window.event_source_binding_detail_label.text().startswith("已将 Active Audio Source Binding 切换为 oneshot_b")

    controller.is_dirty = False
    controller.window.close()


def test_play_mode_combo_serializes_one_shot_internal_value(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    controller.window.play_mode_combo.setCurrentIndex(controller.window.play_mode_combo.findData("OneShot"))
    QApplication.processEvents()
    assert controller.window.current_event_form_data()["play_mode"] == "OneShot"

    controller.window.play_mode_combo.setCurrentIndex(controller.window.play_mode_combo.findData("Combo"))
    QApplication.processEvents()
    assert controller.window.current_event_form_data()["play_mode"] == "Combo"

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_filter_actions_and_event_navigation(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    root_folder_id = controller.project.root_folder_ids[0]
    sibling_event = controller._make_casual_event_template("UI_Click_Alt", display_name="备用点击")
    controller.project.add_event(root_folder_id, sibling_event)

    source_shared = tmp_path / "ui" / "shared.wav"
    source_unused = tmp_path / "ui" / "unused.wav"
    source_missing = tmp_path / "ui" / "missing.wav"
    source_shared.parent.mkdir(parents=True, exist_ok=True)
    source_shared.write_bytes(b"fake-wav")
    source_unused.write_bytes(b"fake-wav")

    controller.current_event.clips = [
        ClipModel(id="shared_a", source_path=str(source_shared), export_path="ui/shared_a", asset_key="ui/shared_a")
    ]
    sibling_event.clips = [
        ClipModel(id="shared_b", source_path=str(source_shared), export_path="ui/shared_b", asset_key="ui/shared_b")
    ]
    controller.project.register_source_asset(str(source_shared))
    controller.project.register_source_asset(str(source_unused))
    controller.project.register_source_asset(str(source_missing))
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_browser_filter_combo.setCurrentIndex(4)
    QApplication.processEvents()

    assert controller.window.source_tree._find_source_item(str(source_shared)) is not None
    assert controller.window.source_tree._find_source_item(str(source_unused)) is None

    controller.window.source_browser_filter_combo.setCurrentIndex(0)
    controller.window.source_tree.select_source_path(str(source_unused))
    controller.window._append_selected_source_to_current_event()
    QApplication.processEvents()

    assert {clip.source_path for clip in controller.current_event.clips} == {str(source_shared), str(source_unused)}

    original_event_id = controller.selected_event_id
    original_audio_id = controller.selected_audio_id
    controller.window.source_tree.select_source_path(str(source_shared))
    controller.window._locate_selected_source_reference_audio()
    QApplication.processEvents()

    assert controller.selected_event_id == original_event_id
    assert controller.selected_audio_id == original_audio_id
    assert controller.window.explorer_tabs.currentIndex() == 2

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_shortcuts_and_navigation_state_follow_active_tab(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_file = tmp_path / "ui" / "focus.wav"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"fake-wav")

    controller.current_event.clips[0].source_path = str(source_file)
    controller.current_event.clips[0].asset_key = "ui/focus"
    controller.project.register_source_asset(str(source_file))
    controller._refresh_ui()

    controller.window.show()
    QApplication.processEvents()
    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.select_source_path(str(source_file))
    controller.window.source_tree.setFocus()
    QApplication.processEvents()

    called = {"count": 0}
    monkeypatch.setattr(controller.window, "_locate_selected_source_asset", lambda: called.__setitem__("count", called["count"] + 1))

    controller.window._handle_copy_shortcut()
    controller.window._handle_open_shortcut()
    QApplication.processEvents()

    assert QApplication.clipboard().text() == str(source_file)
    assert called["count"] == 1

    state = controller.window.navigation_state()
    controller.window.explorer_tabs.setCurrentIndex(2)
    controller.window.apply_navigation_state(state)
    QApplication.processEvents()

    assert controller.window.explorer_tabs.currentIndex() == 1

    controller.is_dirty = False
    controller.window.close()


def test_audio_tree_shortcut_delete_removes_selected_audio_without_deleting_unrelated_event(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    preserved_event_id = controller.current_event.id

    source_path = tmp_path / "ui" / "library_only.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")
    monkeypatch.setattr(controller.window, "ask_audio_import_create_events", lambda count: False)

    controller.window.audio_tree.audioFilesDropped.emit([str(source_path)], None)
    QApplication.processEvents()
    created_audio_id = controller.selected_audio_id
    assert created_audio_id is not None

    controller.window.explorer_tabs.setCurrentIndex(2)
    controller.window.audio_tree.select_audio_id(created_audio_id)
    controller.window.audio_tree.setFocus()
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "confirm_delete_audio", lambda audio_id, event_ids: True)

    controller.window._handle_delete_shortcut()
    QApplication.processEvents()

    assert created_audio_id not in controller.project.audio_objects
    assert preserved_event_id in controller.project.events

    controller.is_dirty = False
    controller.window.close()


def test_audio_tree_rename_selected_updates_audio_id_and_event_reference(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    old_audio_id = controller.current_event.audio_id

    controller.window.explorer_tabs.setCurrentIndex(2)
    controller.window.audio_tree.select_audio_id(old_audio_id)
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_rename_value", lambda title, label, initial: "UI_Click_Audio")

    controller.rename_selected()
    QApplication.processEvents()

    assert "UI_Click_Audio" in controller.project.audio_objects
    assert old_audio_id not in controller.project.audio_objects
    assert controller.project.events[controller.current_event.id].audio_id == "UI_Click_Audio"
    assert controller.window.audio_tree.current_audio_id() == "UI_Click_Audio"

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_delete_from_current_audio_removes_binding_but_keeps_event(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    event_id = controller.current_event.id

    source_a = tmp_path / "ui" / "bound_a.wav"
    source_b = tmp_path / "ui" / "bound_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
        controller.project.register_source_asset(str(path))
    controller.current_event.clips = [
        ClipModel(id="bound_a", source_path=str(source_a), export_path="ui/bound_a", asset_key="ui/bound_a"),
        ClipModel(id="bound_b", source_path=str(source_b), export_path="ui/bound_b", asset_key="ui/bound_b"),
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.select_source_path(str(source_b))
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_source_delete_action", lambda count, **kwargs: "remove_from_audio")
    monkeypatch.setattr(controller.window, "confirm_delete", lambda label: True)

    controller.delete_selected()
    QApplication.processEvents()

    assert event_id in controller.project.events
    assert [clip.source_path for clip in controller.project.events[event_id].clips] == [str(source_a)]

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_delete_from_registry_only_removes_unreferenced_entries(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    referenced_path = tmp_path / "ui" / "referenced.wav"
    unreferenced_path = tmp_path / "ui" / "library_only.wav"
    for path in [referenced_path, unreferenced_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
        controller.project.register_source_asset(str(path))
    controller.current_event.clips = [
        ClipModel(id="referenced", source_path=str(referenced_path), export_path="ui/referenced", asset_key="ui/referenced")
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.set_selected_source_paths([str(referenced_path), str(unreferenced_path)])
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_source_delete_action", lambda count, **kwargs: "remove_from_registry")
    monkeypatch.setattr(controller.window, "confirm_delete", lambda label: True)

    controller.delete_selected()
    QApplication.processEvents()

    assert str(referenced_path) in controller.project.asset_registry
    assert str(unreferenced_path) not in controller.project.asset_registry

    controller.is_dirty = False
    controller.window.close()


def test_source_browser_delete_from_disk_marks_source_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_path = tmp_path / "ui" / "delete_me.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")
    controller.current_event.clips = [
        ClipModel(id="delete_me", source_path=str(source_path), export_path="ui/delete_me", asset_key="ui/delete_me")
    ]
    controller.project.register_source_asset(str(source_path))
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.select_source_path(str(source_path))
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_source_delete_action", lambda count, **kwargs: "delete_files")
    monkeypatch.setattr(controller.window, "confirm_delete", lambda label: True)

    controller.delete_selected()
    QApplication.processEvents()

    assert source_path.exists() is False
    controller.window.source_tree.select_source_path(str(source_path))
    entry = controller.window.source_tree.current_source_entry()
    assert entry is not None
    assert entry["missing"] is True

    controller.is_dirty = False
    controller.window.close()


def test_browser_primary_actions_follow_active_explorer_tab(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_path = tmp_path / "ui" / "state.wav"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"fake-wav")
    controller.project.register_source_asset(str(source_path))
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(3)
    QApplication.processEvents()
    assert controller.window.rename_button.text() == "重命名"
    assert controller.window.delete_button.text() == "删除"
    assert controller.window.rename_button.isEnabled() is True

    controller.window.explorer_tabs.setCurrentIndex(2)
    QApplication.processEvents()
    assert controller.window.rename_button.text() == "重命名 Audio"
    assert controller.window.delete_button.text() == "删除 Audio"

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.select_source_path(str(source_path))
    QApplication.processEvents()
    assert controller.window.rename_button.isEnabled() is False
    assert controller.window.delete_button.text() == "删除源音频..."


def test_audio_tree_context_menu_targets_clicked_audio(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    source_a = tmp_path / "ui" / "ctx_a.wav"
    source_b = tmp_path / "ui" / "ctx_b.wav"
    for path in [source_a, source_b]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
    monkeypatch.setattr(controller.window, "ask_audio_import_create_events", lambda count: False)
    controller.window.audio_tree.audioFilesDropped.emit([str(source_a)], None)
    QApplication.processEvents()
    first_audio_id = controller.selected_audio_id
    controller.window.audio_tree.audioFilesDropped.emit([str(source_b)], None)
    QApplication.processEvents()
    second_audio_id = controller.selected_audio_id
    assert first_audio_id is not None and second_audio_id is not None and first_audio_id != second_audio_id

    controller.window.explorer_tabs.setCurrentIndex(2)
    controller.window.audio_tree.select_audio_id(first_audio_id)
    QApplication.processEvents()

    target_item = controller.window.audio_tree.topLevelItem(1)
    target_position = controller.window.audio_tree.visualItemRect(target_item).center()
    controller.window._select_audio_context_menu_target(target_position)
    QApplication.processEvents()

    assert controller.window.audio_tree.current_audio_id() == second_audio_id

    controller.is_dirty = False
    controller.window.close()


def test_source_tree_context_menu_targets_clicked_source(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None

    referenced_path = tmp_path / "ui" / "ctx_ref.wav"
    removable_path = tmp_path / "ui" / "ctx_remove.wav"
    for path in [referenced_path, removable_path]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-wav")
        controller.project.register_source_asset(str(path))
    controller.current_event.clips = [
        ClipModel(id="ctx_ref", source_path=str(referenced_path), export_path="ui/ctx_ref", asset_key="ui/ctx_ref")
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.explorer_tabs.setCurrentIndex(1)
    controller.window.source_tree.select_source_path(str(referenced_path))
    QApplication.processEvents()

    target_item = controller.window.source_tree._find_source_item(str(removable_path))
    assert target_item is not None
    target_position = controller.window.source_tree.visualItemRect(target_item).center()
    controller.window._select_source_context_menu_target(target_position)
    QApplication.processEvents()

    assert controller.window.source_tree.selected_source_paths() == [str(removable_path)]

    controller.is_dirty = False
    controller.window.close()


def test_tree_shortcuts_copy_identifier_and_open_editor(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    controller.window.show()
    QApplication.processEvents()
    controller.window.tree.setFocus()
    QApplication.processEvents()

    controller.window._handle_copy_shortcut()
    controller.window._handle_open_shortcut()
    QApplication.processEvents()

    assert QApplication.clipboard().text() == controller.current_event.id
    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 1
    assert controller.window.explorer_tabs.currentIndex() == 2
    assert controller.window.audio_tree.current_audio_id() == controller.current_event.audio_id

    controller.is_dirty = False
    controller.window.close()


def test_multi_event_selection_switches_to_batch_affordance(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    second_event = controller._make_casual_event_template("UI_Click_Alt", display_name="按钮点击备用")
    controller.project.add_event(root_folder_id, second_event)
    controller._refresh_ui()

    controller.window.tree.select_nodes([("event", "UI_Click_Normal"), ("event", "UI_Click_Alt")], current_node=("event", "UI_Click_Normal"))
    QApplication.processEvents()

    assert controller.selected_event_ids == ["UI_Click_Normal", "UI_Click_Alt"]
    assert controller.window.rename_button.text() == "批量重命名"
    assert controller.window.delete_button.text() == "批量删除"
    assert controller.window.bulk_event_bus_button.isEnabled() is True
    assert controller.window.property_group.isEnabled() is False
    assert controller.window.object_type_label.text() == "多选事件"

    controller.is_dirty = False
    controller.window.close()


def test_bulk_event_bus_updates_all_selected_events(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    second_event = controller._make_casual_event_template("Ambience_Menu", display_name="菜单氛围", suggested_bus="SFX")
    controller.project.add_event(root_folder_id, second_event)
    controller._refresh_ui()

    controller.window.tree.select_nodes([("event", "UI_Click_Normal"), ("event", "Ambience_Menu")], current_node=("event", "UI_Click_Normal"))
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_batch_event_bus", lambda bus_names, current_bus: "BGM")

    controller.window._request_bulk_event_bus()
    QApplication.processEvents()

    assert controller.project.events["UI_Click_Normal"].bus == "BGM"
    assert controller.project.events["Ambience_Menu"].bus == "BGM"
    assert "批量切换到总线：BGM" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_batch_rename_selected_events_updates_ids(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    second_event = controller._make_casual_event_template("UI_Click_Alt", display_name="按钮点击备用")
    controller.project.add_event(root_folder_id, second_event)
    controller._refresh_ui()

    controller.window.tree.select_nodes([("event", "UI_Click_Normal"), ("event", "UI_Click_Alt")], current_node=("event", "UI_Click_Normal"))
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "ask_batch_event_rename", lambda: ("UI_Group", 1))

    controller.rename_selected()
    QApplication.processEvents()

    assert "UI_Group_01" in controller.project.events
    assert "UI_Group_02" in controller.project.events
    assert "UI_Click_Normal" not in controller.project.events
    assert "UI_Click_Alt" not in controller.project.events
    assert controller.selected_event_ids == ["UI_Group_01", "UI_Group_02"]

    controller.is_dirty = False
    controller.window.close()


def test_delete_selected_events_removes_multi_selection(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    second_event = controller._make_casual_event_template("UI_Click_Alt", display_name="按钮点击备用")
    controller.project.add_event(root_folder_id, second_event)
    controller._refresh_ui()

    controller.window.tree.select_nodes([("event", "UI_Click_Normal"), ("event", "UI_Click_Alt")], current_node=("event", "UI_Click_Normal"))
    QApplication.processEvents()
    monkeypatch.setattr(controller.window, "confirm_delete", lambda label: True)

    controller.delete_selected()
    QApplication.processEvents()

    assert "UI_Click_Normal" not in controller.project.events
    assert "UI_Click_Alt" not in controller.project.events
    assert controller.selected_event_ids == []
    assert len(controller.project.events) == 0

    controller.is_dirty = False
    controller.window.close()


def test_tree_search_cycles_through_matching_events(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    battle_start = controller._make_casual_event_template("Battle_Start", display_name="战斗开始")
    battle_loop = controller._make_casual_event_template("Battle_Loop", display_name="战斗循环")
    controller.project.add_event(root_folder_id, battle_start)
    controller.project.add_event(root_folder_id, battle_loop)
    controller._refresh_ui()

    controller.window.tree_filter_edit.setText("Battle")
    controller.window._search_next_tree_event()
    QApplication.processEvents()
    first_selected = controller.selected_event_id

    controller.window._search_next_tree_event()
    QApplication.processEvents()
    second_selected = controller.selected_event_id

    assert first_selected in {"Battle_Start", "Battle_Loop"}
    assert second_selected in {"Battle_Start", "Battle_Loop"}
    assert first_selected != second_selected
    assert controller.window.report_detail_label.text().startswith("已定位事件：")

    controller.is_dirty = False
    controller.window.close()


def test_clip_shortcuts_copy_asset_key_and_delete_selection(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    controller.window.editor_tabs.setCurrentIndex(1)
    controller.window.contents_tabs.setCurrentIndex(0)
    controller.window.clip_table.selectRow(0)
    controller.window.clip_table.setFocus()
    QApplication.processEvents()

    controller.window._handle_copy_shortcut()
    assert QApplication.clipboard().text() == controller.current_event.clips[0].asset_key

    controller.window._handle_delete_shortcut()
    QApplication.processEvents()

    assert controller.current_event.clips == []

    controller.is_dirty = False
    controller.window.close()


def test_validate_project_populates_problem_center(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    controller.current_event.clips.clear()

    controller.validate_project()
    QApplication.processEvents()

    assert controller.window.report_tabs.currentIndex() == 1
    assert controller.window.validation_issue_list.count() >= 1

    controller.is_dirty = False
    controller.window.close()


def test_navigation_state_restores_report_selection_and_scroll(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    issues = [
        ValidationIssue(
            severity="Warning",
            code=f"W{i:02d}",
            message=(f"Issue {i} detail\n" * 18).strip(),
            target=f"event_{i:02d}",
        )
        for i in range(20)
    ]
    controller.window.set_validation_report("Validation Report\n" * 40, issues)
    controller.window.show_report_tab(1)
    controller.window.validation_issue_list.setCurrentRow(12)
    QApplication.processEvents()

    issue_scroll_bar = controller.window.validation_issue_list.verticalScrollBar()
    detail_scroll_bar = controller.window.validation_report_output.verticalScrollBar()
    issue_scroll_bar.setValue(min(max(issue_scroll_bar.maximum() // 2, 1), issue_scroll_bar.maximum()))
    detail_scroll_bar.setValue(min(max(detail_scroll_bar.maximum() // 2, 1), detail_scroll_bar.maximum()))
    QApplication.processEvents()
    expected_issue_scroll = issue_scroll_bar.value()
    expected_detail_scroll = detail_scroll_bar.value()

    state = controller.window.navigation_state()
    controller.window.show_report_tab(0)
    controller.window.validation_issue_list.setCurrentRow(0)
    issue_scroll_bar.setValue(0)
    detail_scroll_bar.setValue(0)
    QApplication.processEvents()

    controller.window.apply_navigation_state(state)
    QApplication.processEvents()

    current_item = controller.window.validation_issue_list.currentItem()
    assert controller.window.report_tabs.currentIndex() == 1
    assert current_item is not None
    assert current_item.data(0x0100)["target_id"] == "event_12"
    assert issue_scroll_bar.value() == expected_issue_scroll
    assert detail_scroll_bar.value() == expected_detail_scroll

    controller.is_dirty = False
    controller.window.close()


def test_refreshing_validation_report_preserves_problem_center_context(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    issues = [
        ValidationIssue(
            severity="Warning",
            code=f"W{i:02d}",
            message=(f"Issue {i} detail\n" * 18).strip(),
            target=f"event_{i:02d}",
        )
        for i in range(24)
    ]
    report_text = "Validation Report\n" * 48
    controller.window.set_validation_report(report_text, issues)
    controller.window.show_report_tab(1)
    controller.window.validation_issue_list.setCurrentRow(15)
    QApplication.processEvents()

    issue_scroll_bar = controller.window.validation_issue_list.verticalScrollBar()
    detail_scroll_bar = controller.window.validation_report_output.verticalScrollBar()
    issue_scroll_bar.setValue(min(max(issue_scroll_bar.maximum() // 2, 1), issue_scroll_bar.maximum()))
    detail_scroll_bar.setValue(min(max(detail_scroll_bar.maximum() // 2, 1), detail_scroll_bar.maximum()))
    QApplication.processEvents()
    expected_issue_scroll = issue_scroll_bar.value()
    expected_detail_scroll = detail_scroll_bar.value()

    controller.window.set_validation_report(report_text, issues)
    QApplication.processEvents()

    current_item = controller.window.validation_issue_list.currentItem()
    assert current_item is not None
    assert current_item.data(0x0100)["target_id"] == "event_15"
    assert issue_scroll_bar.value() == expected_issue_scroll
    assert detail_scroll_bar.value() == expected_detail_scroll

    controller.is_dirty = False
    controller.window.close()


def test_diagnostic_results_page_reuses_existing_report_state(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    issues = [
        ValidationIssue(
            severity="Warning",
            code="BUS_ROUTE_WARNING",
            message="Bus route needs review.",
            target="UI_Click_Normal",
        )
    ]
    controller.window.append_log("诊断链路已刷新。")
    controller.window.set_validation_report("Validation Report", issues)
    controller.window.set_build_status("构建摘要：等待签收。", "构建报告已准备，等待进一步确认。")
    controller.window.set_loudness_report("Loudness Report", summary_text="响度扫描完成，当前无超标项。")
    controller.window.show_report_tab(4)
    QApplication.processEvents()

    assert controller.window.report_tabs.count() == 5
    assert controller.window.report_tabs.tabText(4) == "诊断概览"
    assert "诊断链路已刷新" in controller.window.diagnostic_log_summary_label.toolTip()
    assert "BUS_ROUTE_WARNING" in controller.window.diagnostic_validation_summary_label.toolTip()
    assert "构建报告已准备" in controller.window.diagnostic_build_summary_label.toolTip()
    assert "响度扫描完成" in controller.window.diagnostic_loudness_summary_label.toolTip()
    assert controller.window.current_project_bus_name() in controller.window.diagnostic_bus_summary_label.toolTip()
    assert controller.window.activity_diagnostic_summary_label.text().strip()
    assert controller.window.diagnostic_section_list.count() == 5
    current_item = controller.window.diagnostic_section_list.currentItem()
    assert current_item is not None
    current_payload = current_item.data(0x0100)
    assert current_payload["section"] == "validation"
    assert "BUS_ROUTE_WARNING" in current_payload["title"]
    assert "Bus route needs review." in controller.window.diagnostic_section_detail_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_controller_tracks_structured_diagnostic_sections(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    issues = [
        ValidationIssue(
            severity="Warning",
            code="BUS_ROUTE_WARNING",
            message="Bus route needs review.",
            target="UI_Click_Normal",
        )
    ]
    controller.window.append_log("诊断链路已刷新。")
    controller.window.set_validation_report("Validation Report", issues)
    controller.window.set_build_status("构建摘要：等待签收。", "构建报告已准备，等待进一步确认。")
    controller.window.set_loudness_report("Loudness Report", summary_text="响度扫描完成，当前无超标项。")
    QApplication.processEvents()

    snapshot = controller._diagnostic_snapshot
    assert "BUS_ROUTE_WARNING" in snapshot.summary

    log_section = snapshot.section("log")
    assert log_section.detail == "诊断链路已刷新。"
    assert log_section.metadata["message"] == "诊断链路已刷新。"

    validation_section = snapshot.section("validation")
    assert validation_section.status == "warning"
    assert validation_section.target_type == "auto"
    assert validation_section.target_id == "UI_Click_Normal"
    assert validation_section.metadata["issue_count"] == 1
    assert validation_section.metadata["first_issue_code"] == "BUS_ROUTE_WARNING"

    build_section = snapshot.section("build")
    assert build_section.status == "info"
    assert build_section.detail == "构建报告已准备，等待进一步确认。"
    assert build_section.metadata["summary"] == "构建摘要：等待签收。"

    loudness_section = snapshot.section("loudness")
    assert loudness_section.status == "success"
    assert loudness_section.summary == "响度扫描完成，当前无超标项。"
    assert loudness_section.metadata["summary_text"] == "响度扫描完成，当前无超标项。"

    bus_section = snapshot.section("bus")
    assert bus_section.status == "info"
    assert bus_section.metadata["default_bus"] == controller.project.settings.default_bus
    assert bus_section.metadata["current_project_bus"] == controller.window.current_project_bus_name()

    controller._set_build_diagnostic_summary(
        "构建完成。",
        "模式：选中构建 -> 增量构建 | 已导出到：AudioData.json | 清单：AudioManifest.json",
        status="success",
        metadata={
            "requested_scope": "selection",
            "requested_scope_label": "选中构建",
            "effective_scope": "incremental",
            "effective_scope_label": "增量构建",
            "selection_label": "事件 UI_Click_Normal",
            "rebuilt_asset_count": 2,
            "reused_asset_count": 5,
            "removed_asset_count": 1,
            "export_root": "./Export",
            "data_file": "AudioData.json",
            "manifest_file": "AudioManifest.json",
        },
    )
    controller._publish_diagnostic_snapshot()
    QApplication.processEvents()

    build_profile_titles = [controller.window.build_profile_list.item(index).text() for index in range(controller.window.build_profile_list.count())]
    assert any("请求 选中构建 | 实际 增量构建" in title for title in build_profile_titles)
    assert any("重建 2 | 复用 5 | 移除 1" in title for title in build_profile_titles)
    controller.window.build_profile_list.setCurrentRow(controller.window.build_profile_list.count() - 1)
    QApplication.processEvents()
    assert "AudioManifest.json" in controller.window.build_profile_detail_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_refresh_ui_preserves_property_scroll_position(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    controller.window.set_active_property_category("工程")
    QApplication.processEvents()

    property_scroll = controller.window.property_tabs.currentWidget()
    property_scroll_bar = property_scroll.verticalScrollBar()
    property_scroll_bar.setValue(property_scroll_bar.maximum())
    QApplication.processEvents()
    expected_scroll = property_scroll_bar.value()

    controller._refresh_ui()
    QApplication.processEvents()

    restored_scroll = controller.window.property_tabs.currentWidget().verticalScrollBar().value()
    assert restored_scroll == expected_scroll

    controller.is_dirty = False
    controller.window.close()


def test_import_audio_events_template_applies_bus_prefix_and_tags(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_path = tmp_path / "Button_Click.wav"
    source_path.write_bytes(b"RIFF")

    controller.import_audio_files_as_events(
        [str(source_path)],
        template={
            "bus_name": "UI",
            "asset_prefix": "ui/buttons",
            "tags": ["ui", "button"],
        },
    )

    assert controller.current_event is not None
    assert controller.current_event.bus == "UI"
    assert controller.current_event.clips[0].asset_key == "ui/buttons/Button_Click"
    assert controller.current_event.clips[0].tags == ["ui", "button"]
    assert controller.window.editor_tabs.currentIndex() == 0
    assert controller.window.property_tabs.currentIndex() == 0

    controller.is_dirty = False
    controller.window.close()


def test_event_import_template_preferences_round_trip(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.apply_ui_preferences(
        {
            **controller.window.ui_preferences(),
            "event_import_template": {
                "bus_name": "UI",
                "asset_prefix": "ui/casual",
                "tags": ["ui", "casual"],
            },
        }
    )

    preferences = controller.window.ui_preferences()

    assert preferences["event_import_template"] == {
        "bus_name": "UI",
        "asset_prefix": "ui/casual",
        "tags": ["ui", "casual"],
    }

    controller.is_dirty = False
    controller.window.close()


def test_controller_window_preferences_round_trip_persists_layout_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)
    stored_values: dict[str, object] = {}

    class FakeSettings:
        def __init__(self, *_args, **_kwargs) -> None:
            self._store = stored_values

        def value(self, key: str, default: object = None) -> object:
            return self._store.get(key, default)

        def setValue(self, key: str, value: object) -> None:
            self._store[key] = value

    monkeypatch.setattr("audioforge.app.controllers.main_controller.QSettings", FakeSettings)

    controller = MainController()
    controller.window.resize(1520, 920)
    controller.window.show()
    QApplication.processEvents()

    controller.window.show_report_tab(2)
    controller.window._activate_workspace_mode("buses")
    controller.window.property_tabs.setCurrentIndex(1)
    controller.window.workspace_splitter.setSizes([770, 250])
    controller.window.main_splitter.setSizes([310, 1180])
    controller.window.project_splitter.setSizes([290, 640])
    route_splitter = controller.window.findChild(QSplitter, "CurrentBusRoutePageSplitter")
    level_splitter = controller.window.findChild(QSplitter, "CurrentBusLevelPageSplitter")
    assert route_splitter is not None
    assert level_splitter is not None
    route_splitter.setSizes([360, 560])
    level_splitter.setSizes([340, 520])
    controller.window.settings_dialog.resize(840, 660)
    controller.window.detach_explorer_panel()
    QApplication.processEvents()

    controller._save_window_preferences()

    controller.is_dirty = False
    controller.window.close()
    QApplication.processEvents()

    stored_preferences = json.loads(str(stored_values["uiPreferencesJson"]))

    assert stored_preferences["workspace_mode"] == "buses"
    assert stored_preferences["property_tab"] == 1
    assert stored_preferences["report_tab"] == 2
    assert stored_preferences["explorer_detached"] is True
    assert stored_preferences["window_geometry"]
    assert stored_preferences["explorer_window_geometry"]
    assert stored_preferences["settings_dialog_geometry"]
    assert len(stored_preferences["named_splitter_sizes"]["ProjectSplitter"]) == 2
    assert len(stored_preferences["named_splitter_sizes"]["CurrentBusRoutePageSplitter"]) == 2
    assert len(stored_preferences["named_splitter_sizes"]["CurrentBusLevelPageSplitter"]) == 2

    restored = MainController()
    restored.window.show()
    for _ in range(5):
        QApplication.processEvents()

    assert restored.window._active_workspace_mode == "buses"
    assert restored.window.property_tabs.currentIndex() == 1
    assert restored.window._active_report_index == 2
    assert restored.window._explorer_detached is True
    assert restored.window._last_docked_main_splitter_sizes == stored_preferences["main_splitter_sizes"]

    restored.is_dirty = False
    restored.window.close()
    QApplication.processEvents()

    round_trip_preferences = json.loads(str(stored_values["uiPreferencesJson"]))

    assert round_trip_preferences["main_splitter_sizes"] == stored_preferences["main_splitter_sizes"]
    assert round_trip_preferences["named_splitter_sizes"]["ProjectSplitter"] == stored_preferences["named_splitter_sizes"]["ProjectSplitter"]
    assert round_trip_preferences["named_splitter_sizes"]["CurrentBusRoutePageSplitter"] == stored_preferences["named_splitter_sizes"]["CurrentBusRoutePageSplitter"]
    assert round_trip_preferences["named_splitter_sizes"]["CurrentBusLevelPageSplitter"] == stored_preferences["named_splitter_sizes"]["CurrentBusLevelPageSplitter"]
    assert round_trip_preferences["named_splitter_sizes"]["WorkspaceSplitter"] == stored_preferences["named_splitter_sizes"]["WorkspaceSplitter"]


def test_adaptive_top_level_sizes_shrink_for_small_resolution(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    minimum_size, target_size = controller.window._adaptive_top_level_sizes(
        (1440, 900),
        (1180, 760),
        available_geometry=QRect(0, 0, 1024, 768),
    )

    assert minimum_size.width() < 1180
    assert minimum_size.height() < 760
    assert target_size.width() <= 1024
    assert target_size.height() <= 768
    assert target_size.width() >= minimum_size.width()
    assert target_size.height() >= minimum_size.height()

    controller.is_dirty = False
    controller.window.close()


def test_fit_top_level_geometry_clamps_to_available_screen(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()

    fitted = controller.window._fit_top_level_geometry(
        QRect(-180, -120, 1600, 980),
        QRect(0, 0, 1280, 720),
        QSize(640, 520),
    )

    assert fitted.left() >= 0
    assert fitted.top() >= 0
    assert fitted.width() <= 1280
    assert fitted.height() <= 720
    assert fitted.width() >= 640
    assert fitted.height() >= 520

    controller.is_dirty = False
    controller.window.close()


def test_import_audio_files_as_events_warns_when_no_supported_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    controller = MainController()
    event_count_before = len(controller.project.events)
    unsupported_path = tmp_path / "notes.txt"
    unsupported_path.write_text("not audio", encoding="utf-8")

    controller.import_audio_files_as_events([str(unsupported_path), str(tmp_path / "missing.wav")])

    assert len(controller.project.events) == event_count_before
    assert warnings
    assert "没有可导入的音频文件" in warnings[0][1]

    controller.is_dirty = False
    controller.window.close()


def test_import_audio_files_as_events_creates_one_shot_for_single_source(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_path = tmp_path / "Single_Click.wav"
    source_path.write_bytes(b"RIFF")

    controller.import_audio_files_as_events([str(source_path)])

    assert controller.current_event is not None
    assert controller.current_event.play_mode == "OneShot"
    assert len(controller.current_event.clips) == 1

    controller.is_dirty = False
    controller.window.close()


def test_import_audio_files_as_events_from_folder_creates_nested_folders(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    root_folder_id = controller.project.root_folder_ids[0]
    bundle_dir = tmp_path / "Ambience"
    forest_dir = bundle_dir / "Forest"
    cave_dir = bundle_dir / "Cave"
    forest_dir.mkdir(parents=True)
    cave_dir.mkdir(parents=True)
    wind_path = bundle_dir / "Wind.wav"
    bird_path = forest_dir / "Bird.wav"
    drip_path = cave_dir / "Drip.ogg"
    unsupported_path = cave_dir / "notes.txt"
    wind_path.write_bytes(b"RIFF")
    bird_path.write_bytes(b"RIFF")
    drip_path.write_bytes(b"OggS")
    unsupported_path.write_text("skip", encoding="utf-8")

    controller.import_audio_files_as_events([str(bundle_dir)])

    imported_root_id = next(
        folder_id
        for folder_id in controller.project.folders[root_folder_id].child_folder_ids
        if controller.project.folders[folder_id].name == "Ambience"
    )
    imported_root = controller.project.folders[imported_root_id]
    forest_folder_id = next(
        folder_id
        for folder_id in imported_root.child_folder_ids
        if controller.project.folders[folder_id].name == "Forest"
    )
    cave_folder_id = next(
        folder_id
        for folder_id in imported_root.child_folder_ids
        if controller.project.folders[folder_id].name == "Cave"
    )

    assert "Wind" in imported_root.child_event_ids
    assert "Bird" in controller.project.folders[forest_folder_id].child_event_ids
    assert "Drip" in controller.project.folders[cave_folder_id].child_event_ids
    assert controller.project.events["Wind"].clips[0].source_path == str(wind_path)
    assert controller.project.events["Bird"].clips[0].source_path == str(bird_path)
    assert controller.project.events["Drip"].clips[0].source_path == str(drip_path)

    import_log = controller.window.log_output.toPlainText()
    assert "已导入 3 个音频并创建事件" in import_log
    assert "新增文件夹：3 个" in import_log
    assert "跳过 1 个不支持的文件" in import_log

    controller.is_dirty = False
    controller.window.close()


def test_import_audio_files_as_events_warns_when_folder_contains_no_supported_audio(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda parent, title, message: warnings.append((title, message)),
    )

    controller = MainController()
    event_count_before = len(controller.project.events)
    empty_bundle_dir = tmp_path / "EmptyBundle"
    (empty_bundle_dir / "SubFolder").mkdir(parents=True)

    controller.import_audio_files_as_events([str(empty_bundle_dir)])

    assert len(controller.project.events) == event_count_before
    assert warnings
    assert "不包含支持音频的文件夹" in warnings[0][1]

    controller.is_dirty = False
    controller.window.close()


def test_import_clips_logs_skipped_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip_count_before = len(controller.current_event.clips)
    audio_path = tmp_path / "click.wav"
    audio_path.write_bytes(b"RIFF")
    unsupported_path = tmp_path / "click.txt"
    unsupported_path.write_text("text", encoding="utf-8")

    controller.import_clips([str(audio_path), str(unsupported_path), str(tmp_path / "missing.wav")])

    assert controller.current_event is not None
    assert len(controller.current_event.clips) == clip_count_before + 1
    assert "跳过 1 个不支持的文件" in controller.window.log_output.toPlainText()
    assert "跳过 1 个不存在的文件" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_build_project_handles_export_failure(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: criticals.append((title, message)),
    )

    controller = MainController()

    class BoomExporter:
        def plan_export(self, project, export_root, request=None):
            return controller.exporter.plan_export(project, export_root, request)

        def export(self, *args, **kwargs):
            raise RuntimeError("export boom")

    monkeypatch.setattr(controller, "_create_build_exporter", lambda: BoomExporter())

    controller.build_project()
    _wait_for_build_completion(controller)

    assert criticals
    assert criticals[0][0] == "构建失败"
    assert "export boom" in criticals[0][1]
    assert controller.window.report_tabs.currentIndex() == 2
    assert "构建失败" in controller.window.build_report_output.toPlainText()
    assert "export boom" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_build_project_resolves_relative_export_root_from_project_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.file_path = str(tmp_path / "portable.afproj")
    controller.project.settings.export_root = "./Export"
    captured: dict[str, Path] = {}

    def capture_start(project, export_root, build_request) -> None:
        captured["export_root"] = export_root

    monkeypatch.setattr(controller, "_start_build_worker", capture_start)

    controller.build_project()

    assert captured["export_root"] == (tmp_path / "Export").resolve(strict=False)

    controller.is_dirty = False
    controller.window.close()


def test_tree_preview_actions_and_preview_strip_replace_bottom_transport_card(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    paused = {"value": False}
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session

    def has_active_event(event_id: str) -> bool:
        return event_id == session.playback_owner_id

    def is_event_paused(_event_id: str) -> bool:
        return paused["value"]

    def pause_event(event_id: str) -> bool:
        if event_id != session.playback_owner_id:
            return False
        paused["value"] = True
        return True

    def resume_event(event_id: str) -> bool:
        if event_id != session.playback_owner_id:
            return False
        paused["value"] = False
        return True

    monkeypatch.setattr(controller.playback_service, "has_active_event", has_active_event)
    monkeypatch.setattr(controller.playback_service, "is_event_paused", is_event_paused)
    monkeypatch.setattr(controller.playback_service, "pause_event", pause_event)
    monkeypatch.setattr(controller.playback_service, "resume_event", resume_event)

    controller.window.resize(2048, 1118)
    controller.window.show()
    controller.window._activate_workspace_mode("resources")
    QApplication.processEvents()
    controller._publish_audition_session(session)

    preview_host = controller.window.activity_preview_host
    current_page = controller.window._workspace_mode_pages["resources"]

    assert preview_host is not None
    assert preview_host.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert controller.window.activity_panel.isAncestorOf(controller.window.loudness_group)
    assert controller.window.workspace_status_bar.isAncestorOf(controller.window.loudness_group) is False
    assert current_page.isAncestorOf(controller.window.loudness_group) is False
    assert controller.window.loudness_group.parentWidget() is preview_host
    assert controller.window.activity_panel.height() >= controller.window.loudness_group.height()
    assert controller.window.loudness_group.isAncestorOf(controller.window.preview_waveform_strip)
    assert controller.window.preview_transport_title_label.wordWrap() is False
    assert controller.window.preview_transport_detail_label.wordWrap() is False
    assert controller.window.preview_transport_detail_label.isVisible() is True
    assert controller.window.loudness_group.isAncestorOf(controller.window.preview_inline_momentary_max_value)
    assert controller.window.loudness_group.isAncestorOf(controller.window.preview_transport_play_button) is False
    assert controller.window.loudness_group.isAncestorOf(controller.window.preview_transport_metrics_frame) is False

    controller.window.set_preview_transport_state("idle", has_target=True, can_replay=False)
    assert controller.window.preview_transport_status_chip.text() == "可试听"
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [("preview", "试听事件")]

    controller.window.set_preview_transport_state("idle", has_target=False, can_replay=True)
    assert controller.window.preview_transport_status_chip.text() == "可重播"
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [
        ("preview", "试听事件"),
        ("restart", "从头播放最近试听"),
    ]

    signals: list[str] = []
    controller.window.pausePreviewRequested.connect(lambda: signals.append("pause"))
    controller.window.resumePreviewRequested.connect(lambda: signals.append("resume"))

    controller.window.set_preview_transport_state("playing", has_target=True, can_replay=True)
    assert controller.window.preview_transport_status_chip.text() == "播放中"
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [
        ("preview", "试听事件"),
        ("pause", "暂停当前试听"),
        ("stop", "停止当前试听"),
        ("restart", "从头播放最近试听"),
    ]

    controller.window._dispatch_tree_preview_context_action("pause")
    QApplication.processEvents()

    controller.window.set_preview_transport_state("paused", has_target=True, can_replay=True)
    controller.window._dispatch_tree_preview_context_action("resume")
    QApplication.processEvents()

    assert signals == ["pause", "resume"]

    controller.is_dirty = False
    controller.window.close()


def test_preview_transport_controller_syncs_pause_resume_and_restart(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    paused = {"value": False}
    calls: list[tuple[str, object]] = []
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session

    def has_active_event(event_id: str) -> bool:
        return event_id == session.playback_owner_id

    def is_event_paused(_event_id: str) -> bool:
        return paused["value"]

    def pause_event(event_id: str) -> bool:
        calls.append(("pause", event_id))
        paused["value"] = True
        return True

    def resume_event(event_id: str) -> bool:
        calls.append(("resume", event_id))
        paused["value"] = False
        return True

    def stop_playback(event_id: str) -> None:
        calls.append(("stop-playback", event_id))

    def stop_preview(event_id: str) -> None:
        calls.append(("stop-preview", event_id))

    def replay_preview(play_session: AuditionSession) -> str:
        calls.append(("replay", play_session.clip_id))
        paused["value"] = False
        return "Replay ok"

    monkeypatch.setattr(controller.playback_service, "has_active_event", has_active_event)
    monkeypatch.setattr(controller.playback_service, "is_event_paused", is_event_paused)
    monkeypatch.setattr(controller.playback_service, "pause_event", pause_event)
    monkeypatch.setattr(controller.playback_service, "resume_event", resume_event)
    monkeypatch.setattr(controller.playback_service, "stop_event", stop_playback)
    monkeypatch.setattr(controller.preview_service, "stop_event", stop_preview)
    monkeypatch.setattr(controller, "_play_audition_session", replay_preview)

    controller._sync_preview_transport_state()
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [
        ("preview", "试听事件"),
        ("pause", "暂停当前试听"),
        ("stop", "停止当前试听"),
        ("restart", "从头播放最近试听"),
    ]
    assert controller.window.preview_transport_title_label.text() == session.title

    controller.pause_current_event_preview()
    QApplication.processEvents()
    assert paused["value"] is True
    assert controller.window.preview_transport_status_chip.text() == "已暂停"

    controller.resume_current_event_preview()
    QApplication.processEvents()
    assert paused["value"] is False
    assert controller.window.preview_transport_status_chip.text() == "播放中"

    controller.restart_current_event_preview()
    QApplication.processEvents()
    assert ("replay", clip.id) in calls
    assert ("stop-playback", session.playback_owner_id) in calls
    assert ("stop-preview", controller.current_event.id) in calls

    controller.stop_current_event_preview()
    QApplication.processEvents()
    assert calls.count(("stop-playback", session.playback_owner_id)) >= 2
    assert calls.count(("stop-preview", controller.current_event.id)) >= 2

    controller.is_dirty = False
    controller.window.close()


def test_preview_transport_monitor_resets_playing_state_after_playback_finishes(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session
    active = {"value": True}

    monkeypatch.setattr(controller.playback_service, "has_active_event", lambda _event_id: active["value"])
    monkeypatch.setattr(controller.playback_service, "is_event_paused", lambda _event_id: False)

    controller._sync_preview_transport_state()

    assert controller.window.preview_transport_status_chip.text() == "播放中"
    assert controller.window.preview_transport_detail_label.isHidden() is False
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [
        ("preview", "试听事件"),
        ("pause", "暂停当前试听"),
        ("stop", "停止当前试听"),
        ("restart", "从头播放最近试听"),
    ]
    assert controller._preview_transport_timer.isActive() is True

    active["value"] = False
    controller._poll_preview_transport_state()

    assert controller.window.preview_transport_status_chip.text() == "可重播"
    assert controller.window.preview_transport_detail_label.text().endswith("可重播")
    assert controller.window.preview_transport_detail_label.isHidden() is False
    assert controller.window._tree_preview_context_actions(has_event_target=True) == [
        ("preview", "试听事件"),
        ("restart", "从头播放最近试听"),
    ]
    assert controller._preview_transport_timer.isActive() is False

    controller.is_dirty = False
    controller.window.close()


def test_recent_preview_transport_survives_switching_to_folder(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="clip",
        title=f"片段 {clip.id}",
        detail=f"事件 {controller.current_event.display_name or controller.current_event.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session
    calls: list[tuple[str, str]] = []
    paused = {"value": False}

    monkeypatch.setattr(
        controller.playback_service,
        "has_active_event",
        lambda event_id: event_id == session.playback_owner_id,
    )
    monkeypatch.setattr(controller.playback_service, "is_event_paused", lambda _event_id: paused["value"])

    def pause_event(event_id: str) -> bool:
        calls.append(("pause", event_id))
        paused["value"] = True
        return True

    def resume_event(event_id: str) -> bool:
        calls.append(("resume", event_id))
        paused["value"] = False
        return True

    monkeypatch.setattr(controller.playback_service, "pause_event", pause_event)
    monkeypatch.setattr(controller.playback_service, "resume_event", resume_event)

    folder_id = controller.project.root_folder_ids[0]
    controller.select_node("folder", folder_id)
    controller._sync_preview_transport_state()
    QApplication.processEvents()

    assert controller.current_event is None
    assert controller.window.preview_transport_title_label.text() == session.title
    assert controller.window._tree_preview_context_actions(has_event_target=False) == []

    controller.pause_current_event_preview()
    controller.resume_current_event_preview()
    QApplication.processEvents()

    assert calls == [("pause", session.playback_owner_id), ("resume", session.playback_owner_id)]

    controller.is_dirty = False
    controller.window.close()


def test_recent_preview_play_replays_session_without_current_event(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(controller.playback_service, "has_active_event", lambda _event_id: False)

    def replay_preview(play_session: AuditionSession) -> str:
        calls.append(("replay", play_session.playback_owner_id))
        return "Replay ok"

    def fallback_preview() -> None:
        calls.append(("fallback", "current"))

    monkeypatch.setattr(controller, "_play_audition_session", replay_preview)
    monkeypatch.setattr(controller, "preview_current_event", fallback_preview)

    folder_id = controller.project.root_folder_ids[0]
    controller.select_node("folder", folder_id)
    controller._sync_preview_transport_state()
    controller.play_recent_preview_transport()
    QApplication.processEvents()

    assert controller.current_event is None
    assert calls == [("replay", session.playback_owner_id)]

    controller.is_dirty = False
    controller.window.close()


def test_recent_preview_play_republishes_session_metrics(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    clip = controller.current_event.clips[0]
    session = AuditionSession(
        playback_owner_id=f"event:{controller.current_event.id}",
        event_id=controller.current_event.id,
        event_name=controller.current_event.display_name or controller.current_event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path or "preview.wav",
        target_kind="event",
        title=f"事件 {controller.current_event.display_name or controller.current_event.id}",
        detail=f"片段 {clip.id} | 资源 {clip.asset_key} | Bus {controller.current_event.bus}",
        bus_name=controller.current_event.bus,
        effective_volume_db=controller.current_event.volume_db,
        tracked_base_volume_db=controller.current_event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=controller.current_event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
    )
    controller._audition_session = session
    published_sessions: list[str] = []
    replay_calls: list[str] = []

    monkeypatch.setattr(controller.playback_service, "has_active_event", lambda _event_id: False)
    monkeypatch.setattr(
        controller,
        "_publish_audition_session",
        lambda play_session: published_sessions.append(play_session.playback_owner_id),
    )
    monkeypatch.setattr(
        controller,
        "_play_audition_session",
        lambda play_session: replay_calls.append(play_session.playback_owner_id) or "Replay ok",
    )

    controller.play_recent_preview_transport()

    assert replay_calls == [session.playback_owner_id]
    assert published_sessions == [session.playback_owner_id]

    controller.is_dirty = False
    controller.window.close()


def test_recent_preview_session_refreshes_metrics_after_event_volume_change(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    assert controller.current_event is not None
    event = controller.current_event
    clip = event.clips[0]
    clip.source_path = "preview.wav"
    session = AuditionSession(
        playback_owner_id=f"event:{event.id}",
        event_id=event.id,
        event_name=event.display_name or event.id,
        clip_id=clip.id,
        asset_key=clip.asset_key,
        file_path=clip.source_path,
        target_kind="clip",
        title=f"片段 {clip.id}",
        detail=f"事件 {event.display_name or event.id} | 资源 {clip.asset_key} | Bus {event.bus}",
        bus_name=event.bus,
        effective_volume_db=event.volume_db,
        tracked_base_volume_db=event.volume_db,
        pitch_cents=0,
        preserve_timing_pitch_cents=event.pitch_cents,
        trim_start_ms=clip.trim_start_ms,
        trim_end_ms=clip.trim_end_ms,
        fade_in_ms=clip.fade_in_ms,
        fade_out_ms=clip.fade_out_ms,
        event_volume_db_at_capture=event.volume_db,
        event_pitch_cents_at_capture=event.pitch_cents,
    )
    controller._audition_session = session
    published_sessions: list[AuditionSession] = []

    monkeypatch.setattr(
        controller,
        "_publish_audition_session",
        lambda refreshed_session: published_sessions.append(refreshed_session),
    )
    monkeypatch.setattr(
        controller,
        "_resolve_effective_preview_volume_db",
        lambda _bus_name, tracked_volume_db: tracked_volume_db + 3.0,
    )

    event.volume_db = session.event_volume_db_at_capture + 6.0

    assert controller._refresh_recent_preview_session() is True
    assert published_sessions
    assert published_sessions[-1].tracked_base_volume_db == event.volume_db
    assert published_sessions[-1].effective_volume_db == event.volume_db + 3.0

    controller.is_dirty = False
    controller.window.close()


def test_navigate_to_report_target_logs_missing_target(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.navigate_to_report_target("event", "missing_event")

    assert "问题定位失败：未找到目标 event:missing_event" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()