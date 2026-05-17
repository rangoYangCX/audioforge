from __future__ import annotations

from PySide6.QtWidgets import QApplication, QSizePolicy

from audioforge.app.controllers.main_controller import AuditionSession, MainController
from audioforge.app.services.recovery_service import RecoveryService


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

    assert preview_host is not None
    assert preview_host.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert controller.window.activity_panel.isAncestorOf(controller.window.preview_gamesync_group)
    assert controller.window.activity_panel.isAncestorOf(controller.window.loudness_group) is False
    assert controller.window.loudness_group.isAncestorOf(controller.window.preview_waveform_strip)
    assert controller.window.preview_transport_title_label.wordWrap() is False
    assert controller.window.preview_transport_detail_label.wordWrap() is False
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