from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from audioforge.app.models.audio_project import (
    ClipModel,
    CurvePointModel,
    EventModel,
    GameParameterModel,
    RtpcBindingModel,
    StateGroupModel,
    StateOverrideModel,
    SwitchGroupModel,
    SwitchVariantModel,
    effective_event_clips,
)


@dataclass(slots=True)
class PreviewGameSyncContext:
    global_game_parameters: dict[str, float] = field(default_factory=dict)
    emitter_game_parameters: dict[str, float] = field(default_factory=dict)
    states: dict[str, str] = field(default_factory=dict)
    switches: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.global_game_parameters = {
            str(name).strip(): float(value)
            for name, value in self.global_game_parameters.items()
            if str(name).strip()
        }
        self.emitter_game_parameters = {
            str(name).strip(): float(value)
            for name, value in self.emitter_game_parameters.items()
            if str(name).strip()
        }
        self.states = {
            str(name).strip(): str(value).strip()
            for name, value in self.states.items()
            if str(name).strip()
        }
        self.switches = {
            str(name).strip(): str(value).strip()
            for name, value in self.switches.items()
            if str(name).strip()
        }


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
    is_muted: bool = False


@dataclass(slots=True)
class PreviewGameSyncResolutionSnapshot:
    parameter_name: str = ""
    parameter_scope: str = "Emitter"
    parameter_source: str = "Default"
    parameter_value: float = 0.0
    parameter_summary: str = "未选择 RTPC。"
    state_group: str = ""
    state_value: str = ""
    state_source: str = "Default"
    state_summary: str = "当前没有 State 作用。"
    switch_group: str = ""
    switch_value: str = ""
    switch_mode: str = "Default"
    switch_parameter_name: str = ""
    switch_parameter_source: str = "None"
    switch_summary: str = "当前使用默认 Switch。"
    summary: str = "当前没有额外的 GameSync 覆盖。"


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
        preview_gamesync: PreviewGameSyncContext | None = None,
        game_parameters: list[GameParameterModel] | None = None,
        state_groups: list[StateGroupModel] | None = None,
        switch_groups: list[SwitchGroupModel] | None = None,
    ) -> PreviewResult:
        trigger_time = time.monotonic() if now is None else now
        state = self._states.setdefault(event.id, PreviewEventState())
        self._cleanup_expired(state, trigger_time)
        stolen_oldest = False
        preview_context = preview_gamesync or PreviewGameSyncContext()
        runtime_clips = self._resolve_event_candidate_clips(event, preview_context, game_parameters or [], switch_groups or [])

        if not runtime_clips:
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

        audio = event.audio
        volume_db = audio.volume_db + self._rng.uniform(audio.volume_rand_min_db, audio.volume_rand_max_db)
        pitch_cents = audio.pitch_cents + int(round(self._rng.uniform(audio.pitch_rand_min_cents, audio.pitch_rand_max_cents)))
        volume_db, pitch_cents, is_muted = self.resolve_mix_adjustment(
            audio.rtpc_bindings,
            audio.state_overrides,
            base_volume_db=volume_db,
            base_pitch_cents=pitch_cents,
            preview_gamesync=preview_context,
            game_parameters=game_parameters or [],
            state_groups=state_groups or [],
            switch_groups=switch_groups or [],
        )
        if is_muted:
            return PreviewResult(
                accepted=False,
                reason="Muted by state override.",
                volume_db=volume_db,
                pitch_cents=pitch_cents,
                combo_step=state.combo_step,
                active_instances=len(state.active_until_times),
                is_muted=True,
            )

        clip = self._select_clip(event, state, runtime_clips)
        if clip is None:
            return PreviewResult(accepted=False, reason="No clip was selected.")
        clip_source_path = str(clip.source_path or "").strip()
        if not clip_source_path:
            return PreviewResult(accepted=False, reason=f"Clip source file is missing: {clip.id}")
        try:
            if not Path(clip_source_path).exists():
                return PreviewResult(accepted=False, reason=f"Clip source file not found: {clip_source_path}")
        except OSError:
            return PreviewResult(accepted=False, reason=f"Clip source path is invalid: {clip_source_path}")

        combo_step = self._resolve_combo_step(event, state, trigger_time)
        combo_pitch_cents = 0
        if audio.play_mode == "Combo":
            combo_pitch_cents = combo_step * audio.combo_pitch_step_cents

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
            is_muted=False,
        )

    def resolve_mix_adjustment(
        self,
        rtpc_bindings: list[RtpcBindingModel],
        state_overrides: list[StateOverrideModel],
        *,
        base_volume_db: float,
        base_pitch_cents: int,
        preview_gamesync: PreviewGameSyncContext | None = None,
        game_parameters: list[GameParameterModel] | None = None,
        state_groups: list[StateGroupModel] | None = None,
        switch_groups: list[SwitchGroupModel] | None = None,
    ) -> tuple[float, int, bool]:
        preview_context = preview_gamesync or PreviewGameSyncContext()
        resolved_volume_db_ref = [float(base_volume_db)]
        resolved_pitch_cents_ref = [int(base_pitch_cents)]
        is_muted_ref = [False]
        self._apply_active_gamesync_effects(
            state_groups or [],
            switch_groups or [],
            game_parameters or [],
            preview_context,
            resolved_volume_db_ref,
            resolved_pitch_cents_ref,
            is_muted_ref,
        )
        self._apply_state_overrides(
            state_overrides,
            state_groups or [],
            preview_context,
            resolved_volume_db_ref,
            resolved_pitch_cents_ref,
            is_muted_ref,
        )
        self._apply_rtpc_bindings(rtpc_bindings, game_parameters or [], preview_context, resolved_volume_db_ref, resolved_pitch_cents_ref)
        return resolved_volume_db_ref[0], resolved_pitch_cents_ref[0], is_muted_ref[0]

    def resolve_bus_adjustment(
        self,
        rtpc_bindings: list[RtpcBindingModel],
        state_overrides: list[StateOverrideModel],
        *,
        preview_gamesync: PreviewGameSyncContext | None = None,
        game_parameters: list[GameParameterModel] | None = None,
        state_groups: list[StateGroupModel] | None = None,
        switch_groups: list[SwitchGroupModel] | None = None,
    ) -> tuple[float, bool]:
        volume_db, _pitch_cents, is_muted = self.resolve_mix_adjustment(
            rtpc_bindings,
            state_overrides,
            base_volume_db=0.0,
            base_pitch_cents=0,
            preview_gamesync=preview_gamesync,
            game_parameters=game_parameters,
            state_groups=state_groups,
            switch_groups=switch_groups,
        )
        return volume_db, is_muted

    def build_preview_resolution_snapshot(
        self,
        preview_gamesync: PreviewGameSyncContext | None = None,
        *,
        game_parameters: list[GameParameterModel] | None = None,
        state_groups: list[StateGroupModel] | None = None,
        switch_groups: list[SwitchGroupModel] | None = None,
        selected_parameter_name: str = "",
        selected_parameter_scope: str = "Emitter",
        selected_state_group: str = "",
        selected_switch_group: str = "",
    ) -> PreviewGameSyncResolutionSnapshot:
        preview_context = preview_gamesync or PreviewGameSyncContext()
        resolved_scope = selected_parameter_scope if selected_parameter_scope in {"Emitter", "Global"} else "Emitter"
        parameter_source, parameter_value = self._resolve_game_parameter_source(
            selected_parameter_name,
            resolved_scope,
            game_parameters or [],
            preview_context,
        )
        parameter_summary = "未选择 RTPC。"
        if selected_parameter_name:
            parameter_summary = f"RTPC {selected_parameter_name} 当前按 {resolved_scope} 绑定求值，命中 {parameter_source} {parameter_value:.2f}。"

        state_value, state_source = self._resolve_state_resolution(
            selected_state_group,
            state_groups or [],
            preview_context,
        )
        state_summary = "当前没有 State 作用。"
        if selected_state_group:
            state_summary = f"State {selected_state_group} 当前值 {state_value or '-'}，作用域固定为 Global。"

        switch_value, switch_mode, switch_parameter_name, switch_parameter_source = self._resolve_switch_resolution(
            selected_switch_group,
            switch_groups or [],
            game_parameters or [],
            preview_context,
        )
        switch_summary = "当前使用默认 Switch。"
        if selected_switch_group:
            if switch_mode == "Manual":
                switch_summary = f"Switch {selected_switch_group} 当前由试听对象手动指定为 {switch_value or '-'}。"
            elif switch_mode == "Mapped":
                switch_summary = f"Switch {selected_switch_group} 当前由参数 {switch_parameter_name or '-'} 的 {switch_parameter_source} 值映射到 {switch_value or '-'}。"
            else:
                switch_summary = f"Switch {selected_switch_group} 当前回退默认值 {switch_value or '-'}。"

        summary_parts = [
            parameter_summary,
            state_summary if selected_state_group else "State 当前无额外覆盖。",
            switch_summary if selected_switch_group else "Switch 当前回退默认路径。",
        ]
        return PreviewGameSyncResolutionSnapshot(
            parameter_name=selected_parameter_name,
            parameter_scope=resolved_scope,
            parameter_source=parameter_source,
            parameter_value=parameter_value,
            parameter_summary=parameter_summary,
            state_group=selected_state_group,
            state_value=state_value,
            state_source=state_source,
            state_summary=state_summary,
            switch_group=selected_switch_group,
            switch_value=switch_value,
            switch_mode=switch_mode,
            switch_parameter_name=switch_parameter_name,
            switch_parameter_source=switch_parameter_source,
            switch_summary=switch_summary,
            summary=" | ".join(summary_parts),
        )

    def _cleanup_expired(self, state: PreviewEventState, now: float) -> None:
        state.active_until_times = [expiry for expiry in state.active_until_times if expiry > now]

    def _resolve_combo_step(self, event: EventModel, state: PreviewEventState, trigger_time: float) -> int:
        audio = event.audio
        if audio.play_mode != "Combo":
            state.combo_step = 0
            return 0
        if state.last_trigger_time is None or trigger_time - state.last_trigger_time > audio.combo_reset_seconds:
            state.combo_step = 0
        else:
            state.combo_step += 1
        if audio.combo_max_step > 0:
            state.combo_step = min(state.combo_step, audio.combo_max_step)
        return state.combo_step

    def _select_clip(self, event: EventModel, state: PreviewEventState, runtime_clips: list[ClipModel]) -> ClipModel | None:
        audio = event.audio
        if audio.play_mode == "OneShot":
            return runtime_clips[0] if runtime_clips else None
        if audio.play_mode == "Sequence":
            clip = runtime_clips[state.sequence_index % len(runtime_clips)]
            state.sequence_index = (state.sequence_index + 1) % len(runtime_clips)
            return clip

        candidates = list(runtime_clips)
        if audio.avoid_immediate_repeat and state.last_clip_id is not None and len(candidates) > 1:
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

    def _resolve_event_candidate_clips(
        self,
        event: EventModel,
        preview_gamesync: PreviewGameSyncContext,
        game_parameters: list[GameParameterModel],
        switch_groups: list[SwitchGroupModel],
    ) -> list[ClipModel]:
        audio = event.audio
        clips_by_id = {clip.id: clip for clip in audio.clips}
        for variant in audio.switch_variants:
            if not variant.group_name.strip():
                continue
            if self._resolve_switch_value(variant.group_name, switch_groups, game_parameters, preview_gamesync) != variant.switch_name:
                continue
            matched_clips = [clips_by_id[clip_id] for clip_id in variant.clip_ids if clip_id in clips_by_id]
            if matched_clips:
                return matched_clips
        default_clips = effective_event_clips(event)
        return default_clips if default_clips else list(audio.clips)

    def _apply_active_gamesync_effects(
        self,
        state_groups: list[StateGroupModel],
        switch_groups: list[SwitchGroupModel],
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
        volume_db_ref: list[float],
        pitch_cents_ref: list[int],
        is_muted_ref: list[bool],
    ) -> None:
        for group in state_groups:
            effect = group.state_effects.get(self._resolve_state_value(group.name, state_groups, preview_gamesync))
            if effect is not None:
                self._apply_gamesync_effect(effect, volume_db_ref, pitch_cents_ref, is_muted_ref)
        for group in switch_groups:
            effect = group.switch_effects.get(self._resolve_switch_value(group.name, switch_groups, game_parameters, preview_gamesync))
            if effect is not None:
                self._apply_gamesync_effect(effect, volume_db_ref, pitch_cents_ref, is_muted_ref)

    def _apply_gamesync_effect(
        self,
        effect,
        volume_db_ref: list[float],
        pitch_cents_ref: list[int],
        is_muted_ref: list[bool],
    ) -> None:
        volume_db_ref[0] += float(effect.volume_db)
        pitch_cents_ref[0] += int(effect.pitch_cents)
        is_muted_ref[0] = bool(is_muted_ref[0] or effect.is_muted)

    def _apply_state_overrides(
        self,
        state_overrides: list[StateOverrideModel],
        state_groups: list[StateGroupModel],
        preview_gamesync: PreviewGameSyncContext,
        volume_db_ref: list[float],
        pitch_cents_ref: list[int],
        is_muted_ref: list[bool],
    ) -> None:
        for item in state_overrides:
            if not item.group_name.strip():
                continue
            if self._resolve_state_value(item.group_name, state_groups, preview_gamesync) != item.state_name:
                continue
            volume_db_ref[0] += float(item.volume_db)
            pitch_cents_ref[0] += int(item.pitch_cents)
            is_muted_ref[0] = bool(is_muted_ref[0] or item.is_muted)

    def _apply_rtpc_bindings(
        self,
        rtpc_bindings: list[RtpcBindingModel],
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
        volume_db_ref: list[float],
        pitch_cents_ref: list[int],
    ) -> None:
        for binding in rtpc_bindings:
            if not binding.parameter_name.strip():
                continue
            resolved_value = self._evaluate_rtpc_binding(binding, game_parameters, preview_gamesync)
            if binding.target == "EventPitchCents":
                pitch_cents_ref[0] += int(round(resolved_value))
            else:
                volume_db_ref[0] += float(resolved_value)

    def _evaluate_rtpc_binding(
        self,
        binding: RtpcBindingModel,
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> float:
        input_value = self._resolve_game_parameter_value(binding.parameter_name, binding.scope, game_parameters, preview_gamesync)
        return self._evaluate_curve(binding.curve_points, input_value)

    def _resolve_game_parameter_value(
        self,
        name: str,
        scope: str,
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> float:
        parameter = self._find_game_parameter(name, game_parameters)
        normalized_name = parameter.name if parameter is not None else name.strip()
        if scope == "Emitter" and normalized_name in preview_gamesync.emitter_game_parameters:
            return self._clamp_game_parameter_value(parameter, preview_gamesync.emitter_game_parameters[normalized_name])
        if normalized_name in preview_gamesync.global_game_parameters:
            return self._clamp_game_parameter_value(parameter, preview_gamesync.global_game_parameters[normalized_name])
        if parameter is not None:
            return float(parameter.default_value)
        return 0.0

    def _resolve_game_parameter_source(
        self,
        name: str,
        scope: str,
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> tuple[str, float]:
        if not name.strip():
            return "Default", 0.0
        parameter = self._find_game_parameter(name, game_parameters)
        normalized_name = parameter.name if parameter is not None else name.strip()
        if scope == "Emitter" and normalized_name in preview_gamesync.emitter_game_parameters:
            return "Emitter", self._clamp_game_parameter_value(parameter, preview_gamesync.emitter_game_parameters[normalized_name])
        if normalized_name in preview_gamesync.global_game_parameters:
            return "Global", self._clamp_game_parameter_value(parameter, preview_gamesync.global_game_parameters[normalized_name])
        if parameter is not None:
            return "Default", float(parameter.default_value)
        return "Default", 0.0

    def _resolve_state_resolution(
        self,
        group_name: str,
        state_groups: list[StateGroupModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> tuple[str, str]:
        if not group_name.strip():
            return "", "Default"
        group = self._find_state_group(group_name, state_groups)
        normalized_name = group.name if group is not None else group_name.strip()
        explicit_state = preview_gamesync.states.get(normalized_name, "").strip()
        if explicit_state:
            return explicit_state, "Global"
        if group is not None:
            return group.default_state, "Default"
        return "", "Default"

    def _resolve_state_value(
        self,
        group_name: str,
        state_groups: list[StateGroupModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> str:
        group = self._find_state_group(group_name, state_groups)
        normalized_name = group.name if group is not None else group_name.strip()
        explicit_state = preview_gamesync.states.get(normalized_name, "").strip()
        if explicit_state:
            return explicit_state
        if group is not None:
            return group.default_state
        return ""

    def _resolve_switch_value(
        self,
        group_name: str,
        switch_groups: list[SwitchGroupModel],
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> str:
        group = self._find_switch_group(group_name, switch_groups)
        normalized_name = group.name if group is not None else group_name.strip()
        explicit_switch = preview_gamesync.switches.get(normalized_name, "").strip()
        if explicit_switch:
            return explicit_switch
        if group is None:
            return ""
        if group.use_game_parameter and group.mapped_game_parameter and group.switches:
            parameter = self._find_game_parameter(group.mapped_game_parameter, game_parameters)
            parameter_scope = "Emitter" if group.mapped_game_parameter in preview_gamesync.emitter_game_parameters else "Global"
            parameter_value = self._resolve_game_parameter_value(group.mapped_game_parameter, parameter_scope, game_parameters, preview_gamesync)
            for minimum, maximum, switch_name in self._switch_thresholds(group, parameter):
                if parameter_value >= minimum and parameter_value <= maximum:
                    return switch_name
        return group.default_switch

    def _resolve_switch_resolution(
        self,
        group_name: str,
        switch_groups: list[SwitchGroupModel],
        game_parameters: list[GameParameterModel],
        preview_gamesync: PreviewGameSyncContext,
    ) -> tuple[str, str, str, str]:
        if not group_name.strip():
            return "", "Default", "", "None"
        group = self._find_switch_group(group_name, switch_groups)
        normalized_name = group.name if group is not None else group_name.strip()
        explicit_switch = preview_gamesync.switches.get(normalized_name, "").strip()
        if explicit_switch:
            return explicit_switch, "Manual", "", "None"
        if group is None:
            return "", "Default", "", "None"
        if group.use_game_parameter and group.mapped_game_parameter and group.switches:
            parameter_source, parameter_value = self._resolve_game_parameter_source(
                group.mapped_game_parameter,
                "Emitter",
                game_parameters,
                preview_gamesync,
            )
            parameter = self._find_game_parameter(group.mapped_game_parameter, game_parameters)
            for minimum, maximum, switch_name in self._switch_thresholds(group, parameter):
                if parameter_value >= minimum and parameter_value <= maximum:
                    return switch_name, "Mapped", group.mapped_game_parameter, parameter_source
        return group.default_switch, "Default", group.mapped_game_parameter, "None"

    def _switch_thresholds(
        self,
        group: SwitchGroupModel,
        parameter: GameParameterModel | None,
    ) -> list[tuple[float, float, str]]:
        if parameter is None or not group.switches:
            return []
        step = (parameter.max_value - parameter.min_value) / max(1, len(group.switches))
        thresholds: list[tuple[float, float, str]] = []
        current_min = parameter.min_value
        for index, switch_name in enumerate(group.switches):
            current_max = parameter.max_value if index == len(group.switches) - 1 else parameter.min_value + step * (index + 1)
            thresholds.append((float(current_min), float(current_max), switch_name))
            current_min = current_max
        return thresholds

    def _evaluate_curve(self, points: list[CurvePointModel], input_value: float) -> float:
        if not points:
            return 0.0
        if len(points) == 1:
            return float(points[0].output_value)
        ordered = sorted(points, key=lambda point: point.input_value)
        if input_value <= ordered[0].input_value:
            return float(ordered[0].output_value)
        for current, following in zip(ordered, ordered[1:]):
            if input_value > following.input_value:
                continue
            if current.interpolation == "Constant":
                return float(current.output_value)
            span = following.input_value - current.input_value
            if span <= 0:
                return float(following.output_value)
            ratio = (input_value - current.input_value) / span
            return float(current.output_value + (following.output_value - current.output_value) * ratio)
        return float(ordered[-1].output_value)

    def _find_game_parameter(self, name: str, game_parameters: list[GameParameterModel]) -> GameParameterModel | None:
        normalized = name.strip().casefold()
        for parameter in game_parameters:
            if parameter.name.casefold() == normalized:
                return parameter
        return None

    def _find_state_group(self, name: str, state_groups: list[StateGroupModel]) -> StateGroupModel | None:
        normalized = name.strip().casefold()
        for group in state_groups:
            if group.name.casefold() == normalized:
                return group
        return None

    def _find_switch_group(self, name: str, switch_groups: list[SwitchGroupModel]) -> SwitchGroupModel | None:
        normalized = name.strip().casefold()
        for group in switch_groups:
            if group.name.casefold() == normalized:
                return group
        return None

    def _clamp_game_parameter_value(self, parameter: GameParameterModel | None, value: float) -> float:
        if parameter is None:
            return float(value)
        return max(parameter.min_value, min(parameter.max_value, float(value)))