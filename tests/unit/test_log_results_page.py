from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.services.recovery_service import RecoveryService


def test_log_results_page_supports_filters_and_export(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    controller.window.append_log(
        "构建完成：AudioData.json",
        subsystem="build",
        summary="构建完成。",
        context={"data_file": "AudioData.json"},
    )
    controller.window.append_log(
        "已导出实验增量：任务A / 方案1",
        subsystem="experiment",
        summary="实验导出完成。",
        experiment_context={"task_name": "任务A", "variant_name": "方案1", "action": "导出增量"},
        context={"export_root": str(tmp_path / "export")},
    )
    QApplication.processEvents()

    assert controller.window.log_entry_list.count() == 2
    assert "构建完成" in controller.window.log_output.toPlainText()
    assert "已导出实验增量" in controller.window.log_output.toPlainText()

    experiment_index = controller.window.log_filter_experiment_combo.findData("only")
    controller.window.log_filter_experiment_combo.setCurrentIndex(experiment_index)
    QApplication.processEvents()

    assert controller.window.log_entry_list.count() == 1
    assert "任务A" in controller.window.log_entry_detail_output.toPlainText()
    assert "方案1" in controller.window.log_entry_detail_output.toPlainText()

    export_path = tmp_path / "logs.json"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "JSON (*.json)"),
    )
    controller.window.export_current_logs()

    export_payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(export_payload["entries"]) == 1
    assert export_payload["entries"][0]["subsystem"] == "experiment"
    assert export_payload["entries"][0]["experiment_context"]["task_name"] == "任务A"

    controller.is_dirty = False
    controller.window.close()


def test_controller_tracks_experiment_diagnostic_section(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.resize(960, 640)
    controller.window.show()
    QApplication.processEvents()

    controller.window.append_log(
        "已导出实验增量：任务B / 方案2",
        subsystem="experiment",
        summary="实验导出完成。",
        experiment_context={"task_name": "任务B", "variant_name": "方案2", "action": "导出增量"},
        context={"export_root": "./Export"},
    )
    QApplication.processEvents()

    experiment_section = controller._diagnostic_snapshot.section("experiment")
    assert "任务=任务B" in experiment_section.summary
    assert experiment_section.metadata["experiment_context"]["variant_name"] == "方案2"
    assert controller.window.diagnostic_section_list.count() == 6

    section_titles = [controller.window.diagnostic_section_list.item(index).text() for index in range(controller.window.diagnostic_section_list.count())]
    assert any("实验 |" in title for title in section_titles)

    controller.is_dirty = False
    controller.window.close()
