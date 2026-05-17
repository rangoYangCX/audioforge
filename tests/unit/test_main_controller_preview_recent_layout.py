from __future__ import annotations

from PySide6.QtWidgets import QApplication

from audioforge.app.controllers.main_controller import AuditionSession, MainController
from audioforge.app.services.recovery_service import RecoveryService


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