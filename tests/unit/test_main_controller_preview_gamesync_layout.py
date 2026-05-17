from __future__ import annotations

from PySide6.QtWidgets import QApplication

from audioforge.app.controllers.main_controller import AuditionSession, MainController
from audioforge.app.models.audio_project import GameParameterModel, StateGroupModel, SwitchGroupModel
from audioforge.app.services.preview_service import PreviewResult
from audioforge.app.services.recovery_service import RecoveryService


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


def test_preview_gamesync_resolution_labels_show_global_and_mapped_sources(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.game_parameters = [GameParameterModel(name="PlayerSpeed", default_value=0.0, min_value=0.0, max_value=10.0)]
    controller.project.state_groups = [StateGroupModel(name="CombatState", states=["Explore", "Combat"], default_state="Explore")]
    controller.project.switch_groups = [
        SwitchGroupModel(
            name="SurfaceType",
            switches=["Grass", "Stone"],
            default_switch="Grass",
            use_game_parameter=True,
            mapped_game_parameter="PlayerSpeed",
        )
    ]
    controller._refresh_ui()
    QApplication.processEvents()

    controller.window.preview_parameter_name_combo.setCurrentText("PlayerSpeed")
    controller.window.preview_parameter_scope_combo.setCurrentText("Global")
    controller.window.preview_parameter_value_spin.setValue(6.0)
    controller.window.preview_state_group_combo.setCurrentText("CombatState")
    controller.window.preview_switch_group_combo.setCurrentText("SurfaceType")
    QApplication.processEvents()

    assert controller.window.preview_parameter_source_chip.text() == "Global"
    assert controller.window.preview_state_scope_chip.text() == "Global"
    assert controller.window.preview_switch_source_chip.text() == "Mapped"
    assert controller.window.preview_switch_parameter_source_chip.text() == "参数 Global"
    assert "PlayerSpeed" in controller.window.preview_gamesync_summary_label.text()

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