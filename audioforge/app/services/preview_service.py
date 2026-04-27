from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from audioforge.app.models.audio_project import ClipModel, EventModel


@dataclass(slots=True)
class PreviewEventState:
    last_clip_id: str | None = None
    sequence_index: int = 0
    combo_step: int = 0
    last_trigger_time: float | None = None
    active_until_times: list[float] = field(default_factory=list)


@dataclass(slots=True)
class PreviewResult:
    accepted: bool
    reason: str
    clip_id: str | None = None
    asset_key: str | None = None
    volume_db: float = 0.0
    pitch_cents: int = 0
    combo_pitch_cents: int = 0
    combo_step: int = 0
    active_instances: int = 0
    stolen_oldest: bool = False
    playback_duration_seconds: float = 0.0


class PreviewService:
    def __init__(self, seed: int | None = None, preview_hold_seconds: float = 0.25) -> None:
        self._rng = random.Random(seed)
        self._preview_hold_seconds = preview_hold_seconds
        self._states: dict[str, PreviewEventState] = {}

    def clear(self) -> None:
        self._states.clear()

    def stop_event(self, event_id: str) -> None:
        state = self._states.get(event_id)
        if state is None:
            return
        state.active_until_times.clear()

    def stop_events(self, event_ids: list[str]) -> None:
        for event_id in event_ids:
            self.stop_event(event_id)

    def preview_event(
        self,
        event: EventModel,
        now: float | None = None,
        preview_duration_resolver: Callable[[ClipModel, int, int], float | None] | None = None,
    ) -> PreviewResult:
        trigger_time = time.monotonic() if now is None else now
        state = self._states.setdefault(event.id, PreviewEventState())
        self._cleanup_expired(state, trigger_time)
        stolen_oldest = False

        if not event.clips:
            return PreviewResult(accepted=False, reason="No clips configured.")

        if event.cooldown_seconds > 0 and state.last_trigger_time is not None:
            if trigger_time - state.last_trigger_time < event.cooldown_seconds:
                return PreviewResult(
                    accepted=False,
                    reason="Blocked by cooldown.",
                    active_instances=len(state.active_until_times),
                    combo_step=state.combo_step,
                )

        if event.max_instances > 0 and len(state.active_until_times) >= event.max_instances:
            if event.steal_policy == "RejectNew":
                return PreviewResult(
                    accepted=False,
                    reason="Blocked by max instances.",
                    active_instances=len(state.active_until_times),
                    combo_step=state.combo_step,
                )
            state.active_until_times.sort()
            state.active_until_times.pop(0)
            stolen_oldest = True

        clip = self._select_clip(event, state)
        if clip is None:
            return PreviewResult(accepted=False, reason="No clip was selected.")

        combo_step = self._resolve_combo_step(event, state, trigger_time)
        volume_db = event.volume_db + self._rng.uniform(event.volume_rand_min_db, event.volume_rand_max_db)
        pitch_cents = event.pitch_cents + int(round(self._rng.uniform(event.pitch_rand_min_cents, event.pitch_rand_max_cents)))
        combo_pitch_cents = 0
        if event.play_mode == "Combo":
            combo_pitch_cents = combo_step * event.combo_pitch_step_cents

        playback_duration_seconds = self._preview_hold_seconds
        if preview_duration_resolver is not None:
            resolved_duration = preview_duration_resolver(clip, pitch_cents, combo_pitch_cents)
            if resolved_duration is not None:
                playback_duration_seconds = max(0.0, resolved_duration)

        state.last_clip_id = clip.id
        state.last_trigger_time = trigger_time
        state.active_until_times.append(trigger_time + playback_duration_seconds)

        return PreviewResult(
            accepted=True,
            reason="Preview simulated.",
            clip_id=clip.id,
            asset_key=clip.asset_key,
            volume_db=volume_db,
            pitch_cents=pitch_cents,
            combo_pitch_cents=combo_pitch_cents,
            combo_step=combo_step,
            active_instances=len(state.active_until_times),
            stolen_oldest=stolen_oldest,
            playback_duration_seconds=playback_duration_seconds,
        )

    def _cleanup_expired(self, state: PreviewEventState, now: float) -> None:
        state.active_until_times = [expiry for expiry in state.active_until_times if expiry > now]

    def _resolve_combo_step(self, event: EventModel, state: PreviewEventState, trigger_time: float) -> int:
        if event.play_mode != "Combo":
            state.combo_step = 0
            return 0
        if state.last_trigger_time is None or trigger_time - state.last_trigger_time > event.combo_reset_seconds:
            state.combo_step = 0
        else:
            state.combo_step += 1
        if event.combo_max_step > 0:
            state.combo_step = min(state.combo_step, event.combo_max_step)
        return state.combo_step

    def _select_clip(self, event: EventModel, state: PreviewEventState) -> ClipModel | None:
        if event.play_mode == "Sequence":
            clip = event.clips[state.sequence_index % len(event.clips)]
            state.sequence_index = (state.sequence_index + 1) % len(event.clips)
            return clip

        candidates = list(event.clips)
        if event.avoid_immediate_repeat and state.last_clip_id is not None and len(candidates) > 1:
            filtered = [clip for clip in candidates if clip.id != state.last_clip_id]
            if filtered:
                candidates = filtered

        total_weight = sum(max(clip.weight, 1) for clip in candidates)
        pick = self._rng.uniform(0, total_weight)
        cumulative = 0.0
        for clip in candidates:
            cumulative += max(clip.weight, 1)
            if pick <= cumulative:
                return clip
        return candidates[-1] if candidates else None