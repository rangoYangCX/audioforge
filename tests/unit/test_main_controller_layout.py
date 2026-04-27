from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.models.audio_project import ClipModel, ValidationIssue
from audioforge.app.services.recovery_service import RecoveryService
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QApplication


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

    assert controller.window.object_event_bus_chip.text() == "事件总线 UI"
    assert controller.window.object_bus_browser_chip.text() == "手动浏览 SFX"

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
    assert controller.window.property_tabs.currentIndex() == 0
    assert controller.window.event_id_edit.hasFocus()

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
    monkeypatch.setattr(controller.exporter, "export", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("export boom")))

    controller.build_project()

    assert criticals
    assert criticals[0][0] == "构建失败"
    assert "export boom" in criticals[0][1]
    assert controller.window.report_tabs.currentIndex() == 2
    assert "构建失败" in controller.window.build_report_output.toPlainText()
    assert "export boom" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_navigate_to_report_target_logs_missing_target(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.navigate_to_report_target("event", "missing_event")

    assert "问题定位失败：未找到目标 event:missing_event" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()