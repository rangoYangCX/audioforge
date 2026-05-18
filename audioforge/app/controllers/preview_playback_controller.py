from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from audioforge.app.application.contracts import UserNotification

if TYPE_CHECKING:
    from audioforge.app.controllers.main_controller import AuditionSession


class PreviewPlaybackHost(Protocol):
    window: Any
    project: Any
    preview_service: Any
    playback_service: Any
    current_event: Any

    def _current_preview_gamesync_context(self): ...

    def _load_current_experiment_base_project(self): ...

    def _find_base_event_for_current_event(self, base_project, event): ...

    def _resolve_preview_duration_seconds(self, clip, pitch_cents: int, combo_pitch_cents: int) -> float | None: ...

    def _resolve_effective_preview_volume_db(self, bus_name: str, base_volume_db: float, *, preview_gamesync=None) -> float: ...

    def _clear_audition_session(self, event_id: str | None = None) -> None: ...

    def _sync_preview_transport_state(self) -> None: ...

    def _create_audition_session(
        self,
        *,
        event,
        clip,
        target_kind: str,
        effective_volume_db: float,
        tracked_base_volume_db: float,
        pitch_cents: int,
        preserve_timing_pitch_cents: int,
        trim_start_ms: int,
        trim_end_ms: int,
        fade_in_ms: int,
        fade_out_ms: int,
    ) -> AuditionSession: ...

    def _start_audition_session(self, session: AuditionSession) -> str: ...

    def _current_audition_session(self) -> AuditionSession | None: ...

    def _refresh_recent_preview_session(self) -> bool: ...

    def _play_audition_session(self, session: AuditionSession) -> str: ...

    def _publish_audition_session(self, session: AuditionSession) -> None: ...

    def _resolve_preview_event_mix(self, event) -> tuple[float, int, bool]: ...

    def _bus_routes_through(self, bus_name: str, target_bus_name: str) -> bool: ...


class PreviewPlaybackController:
    def __init__(self, host: PreviewPlaybackHost) -> None:
        self._host = host

    def _append_preview_log(
        self,
        message: str,
        *,
        level: str = "INFO",
        event_id: str = "",
        clip_id: str = "",
        summary: str | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        target_type = "event" if event_id else ""
        target_id = event_id
        payload = dict(context or {})
        if clip_id:
            payload["clip_id"] = clip_id
        self._host.window.append_log(
            message,
            level=level,
            subsystem="preview",
            summary=summary or message,
            target_type=target_type,
            target_id=target_id,
            context=payload,
        )

    def preview_base_event(self, *, silent_log: bool = False) -> None:
        current_event = self._host.current_event
        if current_event is None:
            self._host.window.present_notification(UserNotification(level="info", title="试听底板", message="请先选择一个事件，再试听底板版本。"))
            return
        base_project = self._host._load_current_experiment_base_project()
        if base_project is None:
            self._host.window.present_notification(UserNotification(level="warning", title="试听底板失败", message="当前实验没有可用的底板工程。"))
            return
        base_event = self._host._find_base_event_for_current_event(base_project, current_event)
        if base_event is None:
            self._host.window.present_notification(
                UserNotification(
                    level="info",
                    title="试听底板",
                    message=f"底板中找不到与 {current_event.display_name or current_event.id} 对应的事件。",
                )
            )
            return

        preview_gamesync = self._host._current_preview_gamesync_context()
        result = self._host.preview_service.preview_event(
            base_event,
            preview_duration_resolver=self._host._resolve_preview_duration_seconds,
            preview_gamesync=preview_gamesync,
            game_parameters=base_project.game_parameters,
            state_groups=base_project.state_groups,
            switch_groups=base_project.switch_groups,
        )
        if not result.accepted:
            self._host.window.clear_preview_audio_metrics(result.reason)
            self._host._clear_audition_session(current_event.id)
            if not silent_log:
                self._append_preview_log(
                    f"试听底板被拒绝：{base_event.id}，原因：{result.reason}",
                    level="WARNING",
                    event_id=current_event.id,
                    summary="试听底板被拒绝。",
                    context={"base_event_id": base_event.id, "reason": result.reason},
                )
            self._host._sync_preview_transport_state()
            return

        clip = next((item for item in base_event.clips if item.id == result.clip_id), None)
        playback_message = "Simulated only"
        effective_volume_db = self._host._resolve_effective_preview_volume_db(base_event.bus, result.volume_db, preview_gamesync=preview_gamesync)
        if clip is not None and clip.source_path:
            preview_preserve_timing_pitch_cents = result.pitch_cents + result.combo_pitch_cents
            session = self._host._create_audition_session(
                event=base_event,
                clip=clip,
                target_kind="base-event",
                effective_volume_db=effective_volume_db,
                tracked_base_volume_db=result.volume_db,
                pitch_cents=0,
                preserve_timing_pitch_cents=preview_preserve_timing_pitch_cents,
                trim_start_ms=clip.trim_start_ms,
                trim_end_ms=clip.trim_end_ms,
                fade_in_ms=clip.fade_in_ms,
                fade_out_ms=clip.fade_out_ms,
            )
            session.event_id = current_event.id
            if result.stolen_oldest:
                self._host.playback_service.stop_oldest(session.playback_owner_id)
            playback_message = self._host._start_audition_session(session)
        else:
            self._host.window.clear_preview_audio_metrics("当前试听片段没有可分析的源文件。")
            self._host._clear_audition_session(current_event.id)
        if not silent_log:
            self._append_preview_log(
                f"试听底板 {base_event.id}：片段={result.clip_id} 资源={result.asset_key} 事件音量={result.volume_db:.2f}dB 总线后={effective_volume_db:.2f}dB 播放={playback_message}",
                event_id=current_event.id,
                clip_id=result.clip_id,
                summary="已完成底板试听。",
                context={
                    "base_event_id": base_event.id,
                    "asset_key": result.asset_key,
                    "event_volume_db": result.volume_db,
                    "effective_volume_db": effective_volume_db,
                    "playback": playback_message,
                },
            )
        self._host._sync_preview_transport_state()

    def preview_current_event(self, *, silent_log: bool = False) -> None:
        event = self._host.current_event
        if event is None:
            self._host.window.present_notification(UserNotification(level="info", title="试听事件", message="请先选择一个事件，再执行试听。"))
            return
        preview_gamesync = self._host._current_preview_gamesync_context()
        result = self._host.preview_service.preview_event(
            event,
            preview_duration_resolver=self._host._resolve_preview_duration_seconds,
            preview_gamesync=preview_gamesync,
            game_parameters=self._host.project.game_parameters,
            state_groups=self._host.project.state_groups,
            switch_groups=self._host.project.switch_groups,
        )
        if not result.accepted:
            self._host.window.clear_preview_audio_metrics(result.reason)
            self._host._clear_audition_session(event.id)
            if not silent_log:
                self._append_preview_log(
                    f"试听被拒绝：{event.id}，原因：{result.reason}",
                    level="WARNING",
                    event_id=event.id,
                    summary="事件试听被拒绝。",
                    context={"reason": result.reason},
                )
            self._host._sync_preview_transport_state()
            return
        clip = next((item for item in event.clips if item.id == result.clip_id), None)
        playback_message = "Simulated only"
        effective_volume_db = self._host._resolve_effective_preview_volume_db(event.bus, result.volume_db, preview_gamesync=preview_gamesync)
        if clip is not None and clip.source_path:
            preview_preserve_timing_pitch_cents = result.pitch_cents + result.combo_pitch_cents
            session = self._host._create_audition_session(
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
                self._host.playback_service.stop_oldest(session.playback_owner_id)
            playback_message = self._host._start_audition_session(session)
        else:
            self._host.window.clear_preview_audio_metrics("当前试听片段没有可分析的源文件。")
            self._host._clear_audition_session(event.id)
        if not silent_log:
            self._append_preview_log(
                f"试听 {event.id}：片段={result.clip_id} 资源={result.asset_key} 事件音量={result.volume_db:.2f}dB 总线后={effective_volume_db:.2f}dB 基础音高={result.pitch_cents} 连击加成={result.combo_pitch_cents} 连击={result.combo_step} 活动实例={result.active_instances} 时长={result.playback_duration_seconds:.2f}s 播放={playback_message}",
                event_id=event.id,
                clip_id=result.clip_id,
                summary="已完成事件试听。",
                context={
                    "asset_key": result.asset_key,
                    "event_volume_db": result.volume_db,
                    "effective_volume_db": effective_volume_db,
                    "pitch_cents": result.pitch_cents,
                    "combo_pitch_cents": result.combo_pitch_cents,
                    "combo_step": result.combo_step,
                    "active_instances": result.active_instances,
                    "playback_duration_seconds": result.playback_duration_seconds,
                    "playback": playback_message,
                },
            )
        self._host._sync_preview_transport_state()

    def preview_selected_clip(self, clip_id: str) -> None:
        event = self._host.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self._host.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self._host._clear_audition_session(event.id)
            self._append_preview_log(
                f"试听片段被拒绝：{clip_id} 没有源文件。",
                level="WARNING",
                event_id=event.id,
                clip_id=clip_id,
                summary="片段试听被拒绝。",
            )
            self._host._sync_preview_transport_state()
            return
        resolved_volume_db, resolved_pitch_cents, is_muted = self._host._resolve_preview_event_mix(event)
        if is_muted:
            self._host.window.clear_preview_audio_metrics("当前事件被 State Override 静音。")
            self._host._clear_audition_session(event.id)
            self._append_preview_log(
                f"试听片段被拒绝：{event.id} 当前被 State Override 静音。",
                level="WARNING",
                event_id=event.id,
                clip_id=clip_id,
                summary="片段试听被静音状态拦截。",
            )
            self._host._sync_preview_transport_state()
            return
        effective_volume_db = self._host._resolve_effective_preview_volume_db(
            event.bus,
            resolved_volume_db,
            preview_gamesync=self._host._current_preview_gamesync_context(),
        )
        session = self._host._create_audition_session(
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
        playback_message = self._host._start_audition_session(session)
        self._append_preview_log(
            f"试听片段 {clip.id}：资源={clip.asset_key} 事件={event.id} 总线后={effective_volume_db:.2f}dB 播放={playback_message}",
            event_id=event.id,
            clip_id=clip.id,
            summary="已完成片段试听。",
            context={"asset_key": clip.asset_key, "effective_volume_db": effective_volume_db, "playback": playback_message},
        )
        self._host._sync_preview_transport_state()

    def preview_selected_clip_segment(self, clip_id: str, start_ms: int, end_ms: int) -> None:
        event = self._host.current_event
        if event is None:
            return
        clip = next((item for item in event.clips if item.id == clip_id), None)
        if clip is None:
            return
        if not clip.source_path:
            self._host.window.clear_preview_audio_metrics("当前片段没有可分析的源文件。")
            self._host._clear_audition_session(event.id)
            self._append_preview_log(
                f"局部试听被拒绝：{clip_id} 没有源文件。",
                level="WARNING",
                event_id=event.id,
                clip_id=clip_id,
                summary="局部试听被拒绝。",
            )
            self._host._sync_preview_transport_state()
            return
        segment_start_ms = max(0, int(start_ms))
        segment_end_ms = max(segment_start_ms + 1, int(end_ms))
        segment_length_ms = max(1, segment_end_ms - segment_start_ms)
        segment_fade_ms = min(40, max(8, segment_length_ms // 12))
        resolved_volume_db, resolved_pitch_cents, is_muted = self._host._resolve_preview_event_mix(event)
        if is_muted:
            self._host.window.clear_preview_audio_metrics("当前事件被 State Override 静音。")
            self._host._clear_audition_session(event.id)
            self._append_preview_log(
                f"局部试听被拒绝：{event.id} 当前被 State Override 静音。",
                level="WARNING",
                event_id=event.id,
                clip_id=clip_id,
                summary="局部试听被静音状态拦截。",
            )
            self._host._sync_preview_transport_state()
            return
        effective_volume_db = self._host._resolve_effective_preview_volume_db(
            event.bus,
            resolved_volume_db,
            preview_gamesync=self._host._current_preview_gamesync_context(),
        )
        session = self._host._create_audition_session(
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
        playback_message = self._host._start_audition_session(session)
        self._append_preview_log(
            f"局部试听片段 {clip.id}：资源={clip.asset_key} 区间={segment_start_ms}-{segment_end_ms} ms 总线后={effective_volume_db:.2f}dB 播放={playback_message}",
            event_id=event.id,
            clip_id=clip.id,
            summary="已完成局部试听。",
            context={
                "asset_key": clip.asset_key,
                "segment_start_ms": segment_start_ms,
                "segment_end_ms": segment_end_ms,
                "effective_volume_db": effective_volume_db,
                "playback": playback_message,
            },
        )
        self._host._sync_preview_transport_state()

    def play_recent_preview_transport(self) -> None:
        self._host._refresh_recent_preview_session()
        session = self._host._current_audition_session()
        if session is None:
            self.preview_current_event()
            return
        if self._host.playback_service.has_active_event(session.playback_owner_id):
            self._append_preview_log(f"最近试听已在播放：{session.title}", event_id=session.event_id or "", clip_id=session.clip_id, summary="最近试听已在播放。")
            self._host._sync_preview_transport_state()
            return
        playback_message = self._host._play_audition_session(session)
        self._host._publish_audition_session(session)
        self._append_preview_log(
            f"已播放最近试听：{session.title} 播放={playback_message}",
            event_id=session.event_id or "",
            clip_id=session.clip_id,
            summary="已播放最近试听。",
            context={"playback": playback_message},
        )
        self._host._sync_preview_transport_state()

    def pause_current_event_preview(self) -> None:
        session = self._host._current_audition_session()
        if session is None:
            self._host.window.present_notification(UserNotification(level="info", title="暂停试听", message="当前没有可暂停的试听会话。"))
            return
        if not self._host.playback_service.pause_event(session.playback_owner_id):
            self._append_preview_log(
                f"暂停试听被忽略：{session.title} 当前没有可暂停的播放。",
                level="WARNING",
                event_id=session.event_id or "",
                clip_id=session.clip_id,
                summary="暂停试听被忽略。",
            )
            self._host._sync_preview_transport_state()
            return
        self._append_preview_log(f"已暂停试听：{session.title}", event_id=session.event_id or "", clip_id=session.clip_id, summary="已暂停试听。")
        self._host._sync_preview_transport_state()

    def resume_current_event_preview(self) -> None:
        session = self._host._current_audition_session()
        if session is None:
            self._host.window.present_notification(UserNotification(level="info", title="继续试听", message="当前没有暂停中的试听会话。"))
            return
        if not self._host.playback_service.resume_event(session.playback_owner_id):
            self._append_preview_log(
                f"继续试听被忽略：{session.title} 当前没有暂停中的播放。",
                level="WARNING",
                event_id=session.event_id or "",
                clip_id=session.clip_id,
                summary="继续试听被忽略。",
            )
            self._host._sync_preview_transport_state()
            return
        self._append_preview_log(f"已继续试听：{session.title}", event_id=session.event_id or "", clip_id=session.clip_id, summary="已继续试听。")
        self._host._sync_preview_transport_state()

    def restart_current_event_preview(self) -> None:
        session = self._host._current_audition_session()
        if session is None:
            self._host.window.present_notification(UserNotification(level="info", title="从头播放", message="当前对象还没有可重播的试听内容。"))
            return
        self._host.playback_service.stop_event(session.playback_owner_id)
        if session.event_id is not None:
            self._host.preview_service.stop_event(session.event_id)
        playback_message = self._host._play_audition_session(session)
        self._host._publish_audition_session(session)
        self._append_preview_log(
            f"从头播放 {session.title}：片段={session.clip_id} 资源={session.asset_key} 播放={playback_message}",
            event_id=session.event_id or "",
            clip_id=session.clip_id,
            summary="已从头播放试听。",
            context={"asset_key": session.asset_key, "playback": playback_message},
        )
        self._host._sync_preview_transport_state()

    def stop_current_event_preview(self) -> None:
        session = self._host._current_audition_session()
        if session is None:
            self._host.window.present_notification(UserNotification(level="info", title="停止试听", message="当前没有可停止的试听会话。"))
            return
        self._host.playback_service.stop_event(session.playback_owner_id)
        if session.event_id is not None:
            self._host.preview_service.stop_event(session.event_id)
        self._append_preview_log(f"已停止试听：{session.title}", event_id=session.event_id or "", clip_id=session.clip_id, summary="已停止试听。")
        self._host._sync_preview_transport_state()

    def stop_current_bus_preview(self) -> None:
        session = self._host._current_audition_session()
        event = self._host.current_event
        if event is None and session is not None and session.event_id is not None:
            event = self._host.project.events.get(session.event_id)
        if event is None:
            self._host.window.present_notification(UserNotification(level="info", title="停止总线试听", message="请先选择一个事件，以确定要停止的总线。"))
            return
        affected_bus_names = {
            bus_name
            for bus_name in self._host.project.settings.buses
            if self._host._bus_routes_through(bus_name, event.bus)
        }
        affected_bus_names.add(event.bus)
        bus_event_ids = [item.id for item in self._host.project.events.values() if item.bus in affected_bus_names]
        self._host.playback_service.stop_buses(affected_bus_names)
        self._host.preview_service.stop_events(bus_event_ids)
        self._append_preview_log(
            f"已停止总线试听：{event.bus}（覆盖总线 {len(affected_bus_names)} 个，事件 {len(bus_event_ids)} 个）",
            event_id=event.id,
            summary="已停止总线试听。",
            context={"affected_bus_count": len(affected_bus_names), "event_count": len(bus_event_ids)},
        )
        self._host._sync_preview_transport_state()