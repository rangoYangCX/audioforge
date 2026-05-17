from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.services.recovery_service import RecoveryService


def test_window_shows_experiment_status_strip_and_snapshot_history(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.show()
    controller.window.set_experiment_status_strip(
        summary="实验上下文：底板 demo.afproj | 任务 任务1 | 方案 方案A",
        detail="当前对象 E1 相对底板的差异：音量、Bus",
        preview_base_enabled=True,
        compare_enabled=True,
        restore_enabled=False,
    )
    controller.window.set_experiment_autosave_history(
        [
            {
                "label": "2025-01-01T00:00:00Z | variant.afproj",
                "path": "/tmp/variant.snapshot.json",
                "detail": "variant snapshot",
            }
        ]
    )
    QApplication.processEvents()

    assert controller.window.experiment_status_frame.isHidden() is False
    assert controller.window.experiment_status_summary_label.text().startswith("实验上下文：底板 demo.afproj")
    assert controller.window.object_preview_base_button.isEnabled() is True
    assert controller.window.object_compare_experiment_button.isEnabled() is True
    assert controller.window.object_restore_snapshot_button.isEnabled() is False
    assert controller.window.experiment_panel._autosave_history_list.count() == 1

    controller.window.close()


def test_source_browser_shows_experiment_origin_label(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    source_file = tmp_path / "ui" / "origin_click.wav"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"fake-wav")

    controller.current_event.clips[0].source_path = str(source_file)
    controller.current_event.clips[0].asset_key = "ui/origin_click"
    controller.project.register_source_asset(str(source_file))
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.source_tree.select_source_path(str(source_file))
    QApplication.processEvents()

    entry = controller.window.source_tree.current_source_entry()
    assert entry is not None
    entry["origin_label"] = "底板继承"
    controller.window.set_source_browser_entries([entry])
    controller.window.source_tree.select_source_path(str(source_file))
    QApplication.processEvents()

    current_entry = controller.window.source_tree.current_source_entry()
    assert current_entry is not None
    assert current_entry.get("origin_label") == "底板继承"
    assert "归属 底板继承" in controller.window.source_browser_status_label.text()
    assert "底板继承" in controller.window.source_tree.currentItem().text(2)

    controller.is_dirty = False
    controller.window.close()


def test_event_and_audio_tree_highlight_experiment_origin_labels(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.window.tree.set_experiment_origin_labels({controller.current_event.id: "实验修改"})
    controller.window.audio_tree.rebuild([
        {
            "audio_id": controller.current_event.audio_id,
            "display_name": controller.current_event.audio.display_name,
            "play_mode": controller.current_event.audio.play_mode,
            "clip_count": len(controller.current_event.audio.clips),
            "event_count": 1,
            "event_ids": [controller.current_event.id],
            "origin_label": "实验修改",
        }
    ])
    QApplication.processEvents()

    event_item = controller.window.tree.topLevelItem(0).child(0)
    audio_item = controller.window.audio_tree.topLevelItem(0)
    assert "实验修改" in event_item.text(2)
    assert "实验修改" in audio_item.text(2)

    controller.is_dirty = False
    controller.window.close()