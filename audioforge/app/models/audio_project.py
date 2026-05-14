from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from audioforge.app.utils.constants import DEFAULT_BUSES, DEFAULT_PROJECT_NAME, PROJECT_VERSION

PlayMode = Literal["OneShot", "Random", "Sequence", "Combo"]
StealPolicy = Literal["RejectNew", "StopOldest", "StopQuietest"]
LoadPolicy = Literal["OnDemand", "Preload", "Stream"]
Severity = Literal["Error", "Warning", "Info"]
CurveInterpolation = Literal["Linear", "Constant"]
MASTER_BUS_NAME = "Master"


def normalize_bus_names(bus_names: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in bus_names or []:
        bus_name = str(raw_name).strip()
        if not bus_name:
            continue
        key = bus_name.casefold()
        if key in seen:
            continue
        normalized.append(bus_name)
        seen.add(key)
    return normalized or list(DEFAULT_BUSES)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def normalize_named_values(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        value = str(raw_value).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        normalized.append(value)
        seen.add(key)
    return normalized


def _coerce_curve_points(values: list[object] | None) -> list["CurvePointModel"]:
    points: list[CurvePointModel] = []
    for raw_value in values or []:
        if isinstance(raw_value, CurvePointModel):
            points.append(raw_value)
            continue
        if not isinstance(raw_value, dict):
            continue
        points.append(
            CurvePointModel(
                input_value=float(raw_value.get("input_value", 0.0)),
                output_value=float(raw_value.get("output_value", 0.0)),
                interpolation=str(raw_value.get("interpolation", "Linear")),
            )
        )
    if not points:
        points = [
            CurvePointModel(input_value=0.0, output_value=0.0),
            CurvePointModel(input_value=100.0, output_value=1.0),
        ]
    points.sort(key=lambda point: point.input_value)
    return points


def _coerce_string_list(values: list[object] | None) -> list[str]:
    return normalize_named_values([str(value) for value in values or []])


def _coerce_gamesync_effect_map(values: object) -> dict[str, "GameSyncValueEffectModel"]:
    if not isinstance(values, dict):
        return {}
    normalized: dict[str, GameSyncValueEffectModel] = {}
    for raw_name, raw_value in values.items():
        name = str(raw_name).strip()
        if not name:
            continue
        if isinstance(raw_value, GameSyncValueEffectModel):
            normalized[name] = raw_value
            continue
        if not isinstance(raw_value, dict):
            continue
        normalized[name] = GameSyncValueEffectModel(
            volume_db=float(raw_value.get("volume_db", 0.0)),
            pitch_cents=int(raw_value.get("pitch_cents", 0)),
            is_muted=bool(raw_value.get("is_muted", False)),
            notes=str(raw_value.get("notes", "")),
        )
    return normalized


@dataclass(slots=True)
class CurvePointModel:
    input_value: float = 0.0
    output_value: float = 0.0
    interpolation: CurveInterpolation = "Linear"

    def __post_init__(self) -> None:
        self.input_value = float(self.input_value)
        self.output_value = float(self.output_value)
        interpolation = str(self.interpolation).strip()
        self.interpolation = "Constant" if interpolation == "Constant" else "Linear"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RtpcBindingModel:
    parameter_name: str = ""
    target: str = "EventVolumeDb"
    scope: str = "Global"
    curve_points: list[CurvePointModel] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.parameter_name = str(self.parameter_name).strip()
        self.target = str(self.target).strip() or "EventVolumeDb"
        self.scope = str(self.scope).strip() or "Global"
        self.curve_points = _coerce_curve_points(list(self.curve_points))
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "target": self.target,
            "scope": self.scope,
            "curve_points": [point.to_dict() for point in self.curve_points],
            "notes": self.notes,
        }


@dataclass(slots=True)
class StateOverrideModel:
    group_name: str = ""
    state_name: str = ""
    volume_db: float = 0.0
    pitch_cents: int = 0
    is_muted: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        self.group_name = str(self.group_name).strip()
        self.state_name = str(self.state_name).strip()
        self.volume_db = float(self.volume_db)
        self.pitch_cents = int(self.pitch_cents)
        self.is_muted = bool(self.is_muted)
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SwitchVariantModel:
    group_name: str = ""
    switch_name: str = ""
    clip_ids: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        self.group_name = str(self.group_name).strip()
        self.switch_name = str(self.switch_name).strip()
        self.clip_ids = _coerce_string_list(list(self.clip_ids))
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClipModel:
    id: str
    source_path: str
    export_path: str
    asset_key: str
    enabled: bool = True
    active: bool = False
    weight: int = 1
    trim_start_ms: int = 0
    trim_end_ms: int = 0
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    loop_start_ms: int = 0
    loop_end_ms: int = 0
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, source_path: Path, asset_key: str) -> "ClipModel":
        return cls(
            id=source_path.stem,
            source_path=str(source_path),
            export_path=asset_key,
            asset_key=asset_key.replace("\\", "/"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AssetRegistryEntry:
    source_path: str
    discovered_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GameParameterModel:
    name: str
    default_value: float = 0.0
    min_value: float = 0.0
    max_value: float = 100.0
    notes: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.default_value = float(self.default_value)
        self.min_value = float(self.min_value)
        self.max_value = float(self.max_value)
        if self.max_value < self.min_value:
            self.min_value, self.max_value = self.max_value, self.min_value
        self.default_value = min(max(self.default_value, self.min_value), self.max_value)
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GameSyncValueEffectModel:
    volume_db: float = 0.0
    pitch_cents: int = 0
    is_muted: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        self.volume_db = float(self.volume_db)
        self.pitch_cents = int(self.pitch_cents)
        self.is_muted = bool(self.is_muted)
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StateGroupModel:
    name: str
    states: list[str] = field(default_factory=list)
    default_state: str = ""
    state_effects: dict[str, GameSyncValueEffectModel] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.states = normalize_named_values(self.states)
        default_state = str(self.default_state).strip()
        if default_state and default_state.casefold() not in {state.casefold() for state in self.states}:
            self.states.append(default_state)
        self.default_state = default_state or (self.states[0] if self.states else "")
        self.state_effects = _coerce_gamesync_effect_map(self.state_effects)
        for state_name in list(self.state_effects.keys()):
            if state_name.casefold() not in {state.casefold() for state in self.states}:
                self.states.append(state_name)
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "states": list(self.states),
            "default_state": self.default_state,
            "state_effects": {name: effect.to_dict() for name, effect in self.state_effects.items()},
            "notes": self.notes,
        }


@dataclass(slots=True)
class SwitchGroupModel:
    name: str
    switches: list[str] = field(default_factory=list)
    default_switch: str = ""
    use_game_parameter: bool = False
    mapped_game_parameter: str = ""
    switch_effects: dict[str, GameSyncValueEffectModel] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        self.name = str(self.name).strip()
        self.switches = normalize_named_values(self.switches)
        default_switch = str(self.default_switch).strip()
        if default_switch and default_switch.casefold() not in {switch_value.casefold() for switch_value in self.switches}:
            self.switches.append(default_switch)
        self.default_switch = default_switch or (self.switches[0] if self.switches else "")
        self.use_game_parameter = bool(self.use_game_parameter)
        self.mapped_game_parameter = str(self.mapped_game_parameter).strip()
        self.switch_effects = _coerce_gamesync_effect_map(self.switch_effects)
        for switch_name in list(self.switch_effects.keys()):
            if switch_name.casefold() not in {switch_value.casefold() for switch_value in self.switches}:
                self.switches.append(switch_name)
        self.notes = str(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "switches": list(self.switches),
            "default_switch": self.default_switch,
            "use_game_parameter": self.use_game_parameter,
            "mapped_game_parameter": self.mapped_game_parameter,
            "switch_effects": {name: effect.to_dict() for name, effect in self.switch_effects.items()},
            "notes": self.notes,
        }


def _coerce_clips(values: list[object] | None) -> list[ClipModel]:
    clips: list[ClipModel] = []
    for raw_value in values or []:
        if isinstance(raw_value, ClipModel):
            clips.append(raw_value)
            continue
        if isinstance(raw_value, dict):
            clips.append(ClipModel(**raw_value))
    return clips


def _coerce_rtpc_bindings(values: list[object] | None) -> list[RtpcBindingModel]:
    bindings: list[RtpcBindingModel] = []
    for raw_value in values or []:
        if isinstance(raw_value, RtpcBindingModel):
            bindings.append(raw_value)
            continue
        if not isinstance(raw_value, dict):
            continue
        bindings.append(
            RtpcBindingModel(
                parameter_name=str(raw_value.get("parameter_name", "")).strip(),
                target=str(raw_value.get("target", "EventVolumeDb")).strip(),
                scope=str(raw_value.get("scope", "Global")).strip(),
                curve_points=_coerce_curve_points(list(raw_value.get("curve_points", []))),
                notes=str(raw_value.get("notes", "")),
            )
        )
    return bindings


def _coerce_state_overrides(values: list[object] | None) -> list[StateOverrideModel]:
    overrides: list[StateOverrideModel] = []
    for raw_value in values or []:
        if isinstance(raw_value, StateOverrideModel):
            overrides.append(raw_value)
            continue
        if not isinstance(raw_value, dict):
            continue
        overrides.append(
            StateOverrideModel(
                group_name=str(raw_value.get("group_name", "")).strip(),
                state_name=str(raw_value.get("state_name", "")).strip(),
                volume_db=float(raw_value.get("volume_db", 0.0)),
                pitch_cents=int(raw_value.get("pitch_cents", 0)),
                is_muted=bool(raw_value.get("is_muted", False)),
                notes=str(raw_value.get("notes", "")),
            )
        )
    return overrides


def _coerce_switch_variants(values: list[object] | None) -> list[SwitchVariantModel]:
    variants: list[SwitchVariantModel] = []
    for raw_value in values or []:
        if isinstance(raw_value, SwitchVariantModel):
            variants.append(raw_value)
            continue
        if not isinstance(raw_value, dict):
            continue
        variants.append(
            SwitchVariantModel(
                group_name=str(raw_value.get("group_name", "")).strip(),
                switch_name=str(raw_value.get("switch_name", "")).strip(),
                clip_ids=[str(value) for value in raw_value.get("clip_ids", [])],
                notes=str(raw_value.get("notes", "")),
            )
        )
    return variants


@dataclass(slots=True)
class AudioObjectModel:
    id: str = ""
    display_name: str = ""
    bus: str = "SFX"
    play_mode: PlayMode = "Random"
    avoid_immediate_repeat: bool = False
    volume_db: float = 0.0
    volume_rand_min_db: float = 0.0
    volume_rand_max_db: float = 0.0
    pitch_cents: int = 0
    pitch_rand_min_cents: int = 0
    pitch_rand_max_cents: int = 0
    combo_pitch_step_cents: int = 100
    combo_reset_seconds: float = 1.5
    combo_max_step: int = 0
    load_policy: LoadPolicy = "OnDemand"
    clips: list[ClipModel] = field(default_factory=list)
    rtpc_bindings: list[RtpcBindingModel] = field(default_factory=list)
    state_overrides: list[StateOverrideModel] = field(default_factory=list)
    switch_variants: list[SwitchVariantModel] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = str(self.id).strip() or new_id("audio")
        self.display_name = str(self.display_name).strip() or self.id
        self.bus = str(self.bus).strip() or "SFX"
        self.play_mode = str(self.play_mode or "Random")
        self.avoid_immediate_repeat = bool(self.avoid_immediate_repeat)
        self.volume_db = float(self.volume_db)
        self.volume_rand_min_db = float(self.volume_rand_min_db)
        self.volume_rand_max_db = float(self.volume_rand_max_db)
        self.pitch_cents = int(self.pitch_cents)
        self.pitch_rand_min_cents = int(self.pitch_rand_min_cents)
        self.pitch_rand_max_cents = int(self.pitch_rand_max_cents)
        self.combo_pitch_step_cents = int(self.combo_pitch_step_cents)
        self.combo_reset_seconds = float(self.combo_reset_seconds)
        self.combo_max_step = int(self.combo_max_step)
        self.load_policy = str(self.load_policy or "OnDemand")
        self.clips = _coerce_clips(list(self.clips))
        self.rtpc_bindings = _coerce_rtpc_bindings(list(self.rtpc_bindings))
        self.state_overrides = _coerce_state_overrides(list(self.state_overrides))
        self.switch_variants = _coerce_switch_variants(list(self.switch_variants))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "bus": self.bus,
            "play_mode": self.play_mode,
            "avoid_immediate_repeat": self.avoid_immediate_repeat,
            "volume_db": self.volume_db,
            "volume_rand_min_db": self.volume_rand_min_db,
            "volume_rand_max_db": self.volume_rand_max_db,
            "pitch_cents": self.pitch_cents,
            "pitch_rand_min_cents": self.pitch_rand_min_cents,
            "pitch_rand_max_cents": self.pitch_rand_max_cents,
            "combo_pitch_step_cents": self.combo_pitch_step_cents,
            "combo_reset_seconds": self.combo_reset_seconds,
            "combo_max_step": self.combo_max_step,
            "load_policy": self.load_policy,
            "clips": [clip.to_dict() for clip in self.clips],
            "rtpc_bindings": [binding.to_dict() for binding in self.rtpc_bindings],
            "state_overrides": [override.to_dict() for override in self.state_overrides],
            "switch_variants": [variant.to_dict() for variant in self.switch_variants],
        }


EventAudioModel = AudioObjectModel


@dataclass(slots=True, init=False)
class EventModel:
    id: str
    display_name: str
    max_instances: int
    cooldown_seconds: float
    steal_policy: StealPolicy
    notes: str
    audio_id: str
    audio: AudioObjectModel

    def __init__(
        self,
        id: str,
        display_name: str = "",
        max_instances: int = 0,
        cooldown_seconds: float = 0.0,
        steal_policy: StealPolicy = "RejectNew",
        notes: str = "",
        audio_id: str = "",
        audio_display_name: str = "",
        audio: AudioObjectModel | dict[str, Any] | None = None,
        **legacy_audio_fields: Any,
    ) -> None:
        audio_payload = dict(audio) if isinstance(audio, dict) else {}

        def _audio_value(name: str, default: Any) -> Any:
            if name in audio_payload:
                return audio_payload[name]
            return legacy_audio_fields.pop(name, default)

        self.id = id
        self.display_name = display_name
        self.max_instances = int(max_instances)
        self.cooldown_seconds = float(cooldown_seconds)
        self.steal_policy = str(steal_policy or "RejectNew")
        self.notes = str(notes)
        if isinstance(audio, AudioObjectModel):
            resolved_audio = audio
            if str(audio_id).strip():
                resolved_audio.id = str(audio_id).strip()
            if str(audio_display_name).strip():
                resolved_audio.display_name = str(audio_display_name).strip()
        else:
            default_audio_id = str(audio_payload.get("id", audio_id)).strip() or new_id("audio")
            default_audio_name = str(audio_payload.get("display_name", audio_display_name)).strip() or f"{display_name or id} Audio"
            resolved_audio = AudioObjectModel(
                id=default_audio_id,
                display_name=default_audio_name,
                bus=str(_audio_value("bus", "SFX") or "SFX"),
                play_mode=str(_audio_value("play_mode", "Random") or "Random"),
                avoid_immediate_repeat=bool(_audio_value("avoid_immediate_repeat", False)),
                volume_db=float(_audio_value("volume_db", 0.0)),
                volume_rand_min_db=float(_audio_value("volume_rand_min_db", 0.0)),
                volume_rand_max_db=float(_audio_value("volume_rand_max_db", 0.0)),
                pitch_cents=int(_audio_value("pitch_cents", 0)),
                pitch_rand_min_cents=int(_audio_value("pitch_rand_min_cents", 0)),
                pitch_rand_max_cents=int(_audio_value("pitch_rand_max_cents", 0)),
                combo_pitch_step_cents=int(_audio_value("combo_pitch_step_cents", 100)),
                combo_reset_seconds=float(_audio_value("combo_reset_seconds", 1.5)),
                combo_max_step=int(_audio_value("combo_max_step", 0)),
                load_policy=str(_audio_value("load_policy", "OnDemand") or "OnDemand"),
                clips=_coerce_clips(_audio_value("clips", [])),
                rtpc_bindings=_coerce_rtpc_bindings(_audio_value("rtpc_bindings", [])),
                state_overrides=_coerce_state_overrides(_audio_value("state_overrides", [])),
                switch_variants=_coerce_switch_variants(_audio_value("switch_variants", [])),
            )
        self.audio = resolved_audio
        self.audio_id = resolved_audio.id

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "max_instances": self.max_instances,
            "cooldown_seconds": self.cooldown_seconds,
            "steal_policy": self.steal_policy,
            "notes": self.notes,
            "audio_id": self.audio.id,
        }

    @property
    def bus(self) -> str:
        return self.audio.bus

    @bus.setter
    def bus(self, value: str) -> None:
        self.audio.bus = str(value)

    @property
    def play_mode(self) -> PlayMode:
        return self.audio.play_mode

    @play_mode.setter
    def play_mode(self, value: PlayMode) -> None:
        self.audio.play_mode = str(value)

    @property
    def avoid_immediate_repeat(self) -> bool:
        return self.audio.avoid_immediate_repeat

    @avoid_immediate_repeat.setter
    def avoid_immediate_repeat(self, value: bool) -> None:
        self.audio.avoid_immediate_repeat = bool(value)

    @property
    def volume_db(self) -> float:
        return self.audio.volume_db

    @volume_db.setter
    def volume_db(self, value: float) -> None:
        self.audio.volume_db = float(value)

    @property
    def volume_rand_min_db(self) -> float:
        return self.audio.volume_rand_min_db

    @volume_rand_min_db.setter
    def volume_rand_min_db(self, value: float) -> None:
        self.audio.volume_rand_min_db = float(value)

    @property
    def volume_rand_max_db(self) -> float:
        return self.audio.volume_rand_max_db

    @volume_rand_max_db.setter
    def volume_rand_max_db(self, value: float) -> None:
        self.audio.volume_rand_max_db = float(value)

    @property
    def pitch_cents(self) -> int:
        return self.audio.pitch_cents

    @pitch_cents.setter
    def pitch_cents(self, value: int) -> None:
        self.audio.pitch_cents = int(value)

    @property
    def pitch_rand_min_cents(self) -> int:
        return self.audio.pitch_rand_min_cents

    @pitch_rand_min_cents.setter
    def pitch_rand_min_cents(self, value: int) -> None:
        self.audio.pitch_rand_min_cents = int(value)

    @property
    def pitch_rand_max_cents(self) -> int:
        return self.audio.pitch_rand_max_cents

    @pitch_rand_max_cents.setter
    def pitch_rand_max_cents(self, value: int) -> None:
        self.audio.pitch_rand_max_cents = int(value)

    @property
    def combo_pitch_step_cents(self) -> int:
        return self.audio.combo_pitch_step_cents

    @combo_pitch_step_cents.setter
    def combo_pitch_step_cents(self, value: int) -> None:
        self.audio.combo_pitch_step_cents = int(value)

    @property
    def combo_reset_seconds(self) -> float:
        return self.audio.combo_reset_seconds

    @combo_reset_seconds.setter
    def combo_reset_seconds(self, value: float) -> None:
        self.audio.combo_reset_seconds = float(value)

    @property
    def combo_max_step(self) -> int:
        return self.audio.combo_max_step

    @combo_max_step.setter
    def combo_max_step(self, value: int) -> None:
        self.audio.combo_max_step = int(value)

    @property
    def load_policy(self) -> LoadPolicy:
        return self.audio.load_policy

    @load_policy.setter
    def load_policy(self, value: LoadPolicy) -> None:
        self.audio.load_policy = str(value)

    @property
    def clips(self) -> list[ClipModel]:
        return self.audio.clips

    @clips.setter
    def clips(self, value: list[ClipModel]) -> None:
        self.audio.clips = value

    @property
    def rtpc_bindings(self) -> list[RtpcBindingModel]:
        return self.audio.rtpc_bindings

    @rtpc_bindings.setter
    def rtpc_bindings(self, value: list[RtpcBindingModel]) -> None:
        self.audio.rtpc_bindings = value

    @property
    def state_overrides(self) -> list[StateOverrideModel]:
        return self.audio.state_overrides

    @state_overrides.setter
    def state_overrides(self, value: list[StateOverrideModel]) -> None:
        self.audio.state_overrides = value

    @property
    def switch_variants(self) -> list[SwitchVariantModel]:
        return self.audio.switch_variants

    @switch_variants.setter
    def switch_variants(self, value: list[SwitchVariantModel]) -> None:
        self.audio.switch_variants = value


def normalize_audio_binding_states(audio: AudioObjectModel) -> None:
    if not audio.clips:
        return

    for clip in audio.clips:
        clip.enabled = bool(clip.enabled)

    enabled_clips = [clip for clip in audio.clips if bool(clip.enabled)]
    if not enabled_clips:
        for clip in audio.clips:
            clip.active = False
        return

    if audio.play_mode == "OneShot":
        active_clip = next((clip for clip in enabled_clips if bool(clip.active)), None)
        if active_clip is None:
            active_clip = enabled_clips[0]

        for clip in audio.clips:
            clip.active = bool(clip.enabled and clip is active_clip)
        return

    has_any_active = any(bool(clip.active) for clip in enabled_clips)
    for clip in audio.clips:
        clip.active = bool(clip.enabled and (clip.active or not has_any_active))


def normalize_event_binding_states(event: EventModel) -> None:
    normalize_audio_binding_states(event.audio)


def effective_event_clips(event: EventModel) -> list[ClipModel]:
    normalize_event_binding_states(event)
    audio = event.audio
    active_clips = [clip for clip in audio.clips if bool(clip.enabled and clip.active)]
    if audio.play_mode == "OneShot":
        active_clip = next((clip for clip in active_clips if bool(clip.active)), None)
        return [active_clip] if active_clip is not None else []
    return active_clips


@dataclass(slots=True)
class FolderModel:
    id: str
    name: str
    child_folder_ids: list[str] = field(default_factory=list)
    child_event_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BusConfig:
    name: str
    parent_bus: str = MASTER_BUS_NAME
    volume_db: float = 0.0
    is_muted: bool = False
    rtpc_bindings: list[RtpcBindingModel] = field(default_factory=list)
    state_overrides: list[StateOverrideModel] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "Name": self.name,
            "ParentBus": self.parent_bus,
            "VolumeDb": self.volume_db,
            "IsMuted": self.is_muted,
        }

    def to_project_dict(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload["RtpcBindings"] = [binding.to_dict() for binding in self.rtpc_bindings]
        payload["StateOverrides"] = [override.to_dict() for override in self.state_overrides]
        return payload


def default_bus_configs() -> list[BusConfig]:
    return [BusConfig(name=MASTER_BUS_NAME)] + [BusConfig(name=bus_name) for bus_name in DEFAULT_BUSES]


def normalize_bus_configs(bus_configs: list[BusConfig] | None, fallback_bus_names: list[str] | None = None) -> list[BusConfig]:
    master_config = BusConfig(name=MASTER_BUS_NAME)
    normalized: list[BusConfig] = []
    seen: set[str] = set()
    source_configs = bus_configs or [BusConfig(name=bus_name) for bus_name in normalize_bus_names(fallback_bus_names)]
    for config in source_configs:
        bus_name = str(config.name).strip()
        if not bus_name:
            continue
        key = bus_name.casefold()
        if key in seen:
            continue
        if key == MASTER_BUS_NAME.casefold():
            master_config = BusConfig(
                name=MASTER_BUS_NAME,
                parent_bus=MASTER_BUS_NAME,
                volume_db=float(config.volume_db),
                is_muted=bool(config.is_muted),
                rtpc_bindings=list(getattr(config, "rtpc_bindings", [])),
                state_overrides=list(getattr(config, "state_overrides", [])),
            )
            seen.add(key)
            continue
        normalized.append(
            BusConfig(
                name=bus_name,
                parent_bus=str(getattr(config, "parent_bus", MASTER_BUS_NAME) or MASTER_BUS_NAME).strip() or MASTER_BUS_NAME,
                volume_db=float(config.volume_db),
                is_muted=bool(config.is_muted),
                rtpc_bindings=list(getattr(config, "rtpc_bindings", [])),
                state_overrides=list(getattr(config, "state_overrides", [])),
            )
        )
        seen.add(key)
    valid_bus_names = {config.name.casefold() for config in normalized}
    for config in normalized:
        parent_bus = str(config.parent_bus).strip() or MASTER_BUS_NAME
        if parent_bus.casefold() == config.name.casefold() or parent_bus.casefold() not in {MASTER_BUS_NAME.casefold(), *valid_bus_names}:
            config.parent_bus = MASTER_BUS_NAME
        elif parent_bus.casefold() == MASTER_BUS_NAME.casefold():
            config.parent_bus = MASTER_BUS_NAME
        else:
            for candidate in normalized:
                if candidate.name.casefold() == parent_bus.casefold():
                    config.parent_bus = candidate.name
                    break
    if not normalized:
        normalized = [BusConfig(name=bus_name) for bus_name in DEFAULT_BUSES]
    return [master_config, *normalized]


@dataclass(slots=True)
class ProjectSettings:
    default_bus: str = "SFX"
    auto_assign_bus_by_name: bool = True
    supported_formats: list[str] = field(default_factory=lambda: ["wav", "ogg"])
    export_root: str = "./Export"
    buses: list[str] = field(default_factory=lambda: list(DEFAULT_BUSES))
    bus_configs: list[BusConfig] = field(default_factory=default_bus_configs)
    source_audio_format: str = "wav"
    runtime_audio_format: str = "ogg"

    def __post_init__(self) -> None:
        self.bus_configs = normalize_bus_configs(self.bus_configs, self.buses)
        self.buses = [config.name for config in self.bus_configs if config.name != MASTER_BUS_NAME]
        if self.default_bus not in self.buses:
            self.default_bus = self.buses[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "DefaultBus": self.default_bus,
            "AutoAssignBusByName": self.auto_assign_bus_by_name,
            "SupportedFormats": list(self.supported_formats),
            "ExportRoot": self.export_root,
            "Buses": list(self.buses),
            "BusConfigs": [config.to_project_dict() for config in self.bus_configs],
            "SourceAudioFormat": self.source_audio_format,
            "RuntimeAudioFormat": self.runtime_audio_format,
        }


@dataclass(slots=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    target: str


@dataclass(slots=True)
class AudioProject:
    name: str = DEFAULT_PROJECT_NAME
    project_version: int = PROJECT_VERSION
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    root_folder_ids: list[str] = field(default_factory=list)
    folders: dict[str, FolderModel] = field(default_factory=dict)
    events: dict[str, EventModel] = field(default_factory=dict)
    audio_objects: dict[str, AudioObjectModel] = field(default_factory=dict)
    game_parameters: list[GameParameterModel] = field(default_factory=list)
    state_groups: list[StateGroupModel] = field(default_factory=list)
    switch_groups: list[SwitchGroupModel] = field(default_factory=list)
    asset_registry: dict[str, AssetRegistryEntry] = field(default_factory=dict)
    file_path: str | None = None

    @classmethod
    def create_empty(cls, name: str = DEFAULT_PROJECT_NAME) -> "AudioProject":
        project = cls(name=name)
        root_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
        project.folders[root_folder.id] = root_folder
        project.root_folder_ids.append(root_folder.id)
        return project

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def register_source_asset(self, source_path: str) -> None:
        normalized = str(source_path).strip()
        if not normalized:
            return
        if normalized not in self.asset_registry:
            self.asset_registry[normalized] = AssetRegistryEntry(source_path=normalized)
            self.touch()

    def add_audio_object(self, audio: AudioObjectModel) -> AudioObjectModel:
        audio.id = str(audio.id).strip() or new_id("audio")
        if audio.id in self.audio_objects and self.audio_objects[audio.id] is not audio:
            self.audio_objects[audio.id] = audio
        else:
            self.audio_objects[audio.id] = audio
        self.touch()
        return audio

    def event_ids_for_audio(self, audio_id: str) -> list[str]:
        normalized_audio_id = str(audio_id).strip()
        if not normalized_audio_id:
            return []
        return [event.id for event in self.events.values() if event.audio_id == normalized_audio_id]

    def audio_ids_for_source(self, source_path: str) -> list[str]:
        normalized_source_path = str(source_path).strip()
        if not normalized_source_path:
            return []
        audio_ids: list[str] = []
        seen_audio_ids: set[str] = set()
        for audio_id, audio in self.audio_objects.items():
            if audio_id in seen_audio_ids:
                continue
            if any(str(clip.source_path).strip() == normalized_source_path for clip in audio.clips):
                seen_audio_ids.add(audio_id)
                audio_ids.append(audio_id)
        return audio_ids

    def rename_audio_object(self, old_id: str, new_id: str) -> None:
        normalized_old_id = str(old_id).strip()
        normalized_new_id = str(new_id).strip()
        if normalized_old_id not in self.audio_objects:
            raise KeyError(normalized_old_id)
        if not normalized_new_id:
            raise ValueError("Audio ID cannot be empty")
        if normalized_old_id == normalized_new_id:
            return
        if normalized_new_id in self.audio_objects:
            raise ValueError(f"Audio ID already exists: {normalized_new_id}")

        audio = self.audio_objects.pop(normalized_old_id)
        audio.id = normalized_new_id
        self.audio_objects[normalized_new_id] = audio
        for event in self.events.values():
            if event.audio_id != normalized_old_id:
                continue
            event.audio_id = normalized_new_id
            event.audio = audio
        self.touch()

    def remove_audio_object(self, audio_id: str, *, cascade_events: bool = False) -> list[str]:
        normalized_audio_id = str(audio_id).strip()
        if normalized_audio_id not in self.audio_objects:
            raise KeyError(normalized_audio_id)

        linked_event_ids = self.event_ids_for_audio(normalized_audio_id)
        if linked_event_ids and not cascade_events:
            raise ValueError(f"Audio {normalized_audio_id} is still referenced by events: {', '.join(linked_event_ids)}")

        for event_id in list(linked_event_ids):
            self.remove_event(event_id)
        del self.audio_objects[normalized_audio_id]
        self.touch()
        return linked_event_ids

    def add_event(self, folder_id: str, event: EventModel) -> None:
        normalize_event_binding_states(event)
        event.audio_id = str(event.audio.id).strip() or str(event.audio_id).strip() or new_id("audio")
        event.audio.id = event.audio_id
        if event.audio_id in self.audio_objects:
            event.audio = self.audio_objects[event.audio_id]
        else:
            self.audio_objects[event.audio_id] = event.audio
        self.events[event.id] = event
        self.folders[folder_id].child_event_ids.append(event.id)
        for clip in event.clips:
            self.register_source_asset(clip.source_path)
        self.touch()

    def move_event(self, event_id: str, target_folder_id: str, target_index: int | None = None) -> None:
        if event_id not in self.events:
            raise KeyError(event_id)
        if target_folder_id not in self.folders:
            raise KeyError(target_folder_id)

        current_folder_id = self.find_event_folder_id(event_id)
        if current_folder_id is None:
            raise KeyError(event_id)

        source_children = self.folders[current_folder_id].child_event_ids
        source_children.remove(event_id)
        target_children = self.folders[target_folder_id].child_event_ids
        if target_index is None or target_index < 0 or target_index > len(target_children):
            target_children.append(event_id)
        else:
            target_children.insert(target_index, event_id)
        self.touch()

    def rename_event(self, old_id: str, new_id: str) -> None:
        if old_id not in self.events:
            raise KeyError(old_id)
        if old_id == new_id:
            return
        if new_id in self.events:
            raise ValueError(f"Event ID already exists: {new_id}")

        event = self.events.pop(old_id)
        event.id = new_id
        self.events[new_id] = event

        folder_id = self.find_event_folder_id(old_id)
        if folder_id is not None:
            child_event_ids = self.folders[folder_id].child_event_ids
            self.folders[folder_id].child_event_ids = [new_id if event_id == old_id else event_id for event_id in child_event_ids]
        self.touch()

    def remove_event(self, event_id: str) -> None:
        if event_id not in self.events:
            raise KeyError(event_id)

        folder_id = self.find_event_folder_id(event_id)
        if folder_id is not None:
            child_event_ids = self.folders[folder_id].child_event_ids
            self.folders[folder_id].child_event_ids = [child_id for child_id in child_event_ids if child_id != event_id]

        del self.events[event_id]
        self.touch()

    def add_folder(self, parent_folder_id: str | None, folder: FolderModel) -> None:
        self.folders[folder.id] = folder
        if parent_folder_id is None:
            self.root_folder_ids.append(folder.id)
        else:
            self.folders[parent_folder_id].child_folder_ids.append(folder.id)
        self.touch()

    def rename_folder(self, folder_id: str, new_name: str) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)
        self.folders[folder_id].name = new_name
        self.touch()

    def move_folder(self, folder_id: str, target_parent_folder_id: str | None, target_index: int | None = None) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)
        if target_parent_folder_id is not None and target_parent_folder_id not in self.folders:
            raise KeyError(target_parent_folder_id)
        if target_parent_folder_id == folder_id or self.is_folder_descendant(target_parent_folder_id, folder_id):
            raise ValueError("Cannot move a folder into itself or one of its descendants.")

        current_parent_folder_id = self.find_folder_parent_id(folder_id)
        if current_parent_folder_id is None:
            self.root_folder_ids = [root_id for root_id in self.root_folder_ids if root_id != folder_id]
        else:
            current_parent = self.folders[current_parent_folder_id]
            current_parent.child_folder_ids = [child_id for child_id in current_parent.child_folder_ids if child_id != folder_id]

        if target_parent_folder_id is None:
            target_children = self.root_folder_ids
        else:
            target_children = self.folders[target_parent_folder_id].child_folder_ids

        if target_index is None or target_index < 0 or target_index > len(target_children):
            target_children.append(folder_id)
        else:
            target_children.insert(target_index, folder_id)
        self.touch()

    def remove_folder(self, folder_id: str) -> None:
        if folder_id not in self.folders:
            raise KeyError(folder_id)

        folder = self.folders[folder_id]
        for child_event_id in list(folder.child_event_ids):
            self.remove_event(child_event_id)
        for child_folder_id in list(folder.child_folder_ids):
            self.remove_folder(child_folder_id)

        parent_folder_id = self.find_folder_parent_id(folder_id)
        if parent_folder_id is None:
            self.root_folder_ids = [root_id for root_id in self.root_folder_ids if root_id != folder_id]
        else:
            parent = self.folders[parent_folder_id]
            parent.child_folder_ids = [child_id for child_id in parent.child_folder_ids if child_id != folder_id]

        del self.folders[folder_id]

        if not self.root_folder_ids and not self.folders:
            default_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
            self.folders[default_folder.id] = default_folder
            self.root_folder_ids.append(default_folder.id)
        self.touch()

    def add_clip_to_event(self, event_id: str, clip: ClipModel) -> None:
        if self.events[event_id].play_mode != "OneShot" and clip.enabled:
            clip.active = True
        self.events[event_id].clips.append(clip)
        normalize_event_binding_states(self.events[event_id])
        self.register_source_asset(clip.source_path)
        self.touch()

    def sync_asset_registry(self) -> None:
        for audio in self.audio_objects.values():
            for clip in audio.clips:
                normalized = str(clip.source_path).strip()
                if normalized and normalized not in self.asset_registry:
                    self.asset_registry[normalized] = AssetRegistryEntry(source_path=normalized)

    def remove_clip_from_audio_object(self, audio_id: str, clip_id: str) -> None:
        normalized_audio_id = str(audio_id).strip()
        if normalized_audio_id not in self.audio_objects:
            raise KeyError(normalized_audio_id)
        audio = self.audio_objects[normalized_audio_id]
        audio.clips = [clip for clip in audio.clips if clip.id != clip_id]
        normalize_audio_binding_states(audio)
        for event in self.events.values():
            if event.audio_id == normalized_audio_id:
                normalize_event_binding_states(event)
        self.touch()

    def remove_source_asset(self, source_path: str, *, force: bool = False) -> None:
        normalized_source_path = str(source_path).strip()
        if not normalized_source_path:
            raise ValueError("Source path cannot be empty")
        if not force and self.audio_ids_for_source(normalized_source_path):
            raise ValueError(f"Source asset is still referenced: {normalized_source_path}")
        if normalized_source_path in self.asset_registry:
            del self.asset_registry[normalized_source_path]
            self.touch()

    def remove_clip_from_event(self, event_id: str, clip_id: str) -> None:
        event = self.events[event_id]
        event.clips = [clip for clip in event.clips if clip.id != clip_id]
        normalize_event_binding_states(event)
        self.touch()

    def find_event_folder_id(self, event_id: str) -> str | None:
        for folder_id, folder in self.folders.items():
            if event_id in folder.child_event_ids:
                return folder_id
        return None

    def find_folder_parent_id(self, folder_id: str) -> str | None:
        for parent_id, folder in self.folders.items():
            if folder_id in folder.child_folder_ids:
                return parent_id
        return None

    def is_folder_descendant(self, folder_id: str | None, ancestor_folder_id: str) -> bool:
        if folder_id is None:
            return False
        current_parent_id = self.find_folder_parent_id(folder_id)
        while current_parent_id is not None:
            if current_parent_id == ancestor_folder_id:
                return True
            current_parent_id = self.find_folder_parent_id(current_parent_id)
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ProjectVersion": self.project_version,
            "ProjectName": self.name,
            "CreatedAt": self.created_at,
            "UpdatedAt": self.updated_at,
            "Settings": self.settings.to_dict(),
            "Tree": {
                "RootFolderIds": list(self.root_folder_ids),
                "Folders": {folder_id: folder.to_dict() for folder_id, folder in self.folders.items()},
            },
            "AudioObjects": {audio_id: audio.to_dict() for audio_id, audio in self.audio_objects.items()},
            "Events": {event_id: event.to_dict() for event_id, event in self.events.items()},
            "GameSync": {
                "GameParameters": [parameter.to_dict() for parameter in self.game_parameters],
                "StateGroups": [group.to_dict() for group in self.state_groups],
                "SwitchGroups": [group.to_dict() for group in self.switch_groups],
            },
            "Assets": {source_path: entry.to_dict() for source_path, entry in self.asset_registry.items()},
        }


def project_from_dict(payload: dict[str, Any], file_path: str | None = None) -> AudioProject:
    settings_payload = payload.get("Settings", {})
    tree_payload = payload.get("Tree", {})
    gamesync_payload = payload.get("GameSync", {})
    bus_config_payloads = settings_payload.get("BusConfigs", [])
    bus_configs = [
        BusConfig(
            name=str(bus_payload.get("Name", "")).strip(),
            parent_bus=str(bus_payload.get("ParentBus", MASTER_BUS_NAME)).strip() or MASTER_BUS_NAME,
            volume_db=float(bus_payload.get("VolumeDb", 0.0)),
            is_muted=bool(bus_payload.get("IsMuted", False)),
            rtpc_bindings=[
                RtpcBindingModel(
                    parameter_name=str(binding_payload.get("parameter_name", "")).strip(),
                    target=str(binding_payload.get("target", "EventVolumeDb")).strip(),
                    scope=str(binding_payload.get("scope", "Global")).strip(),
                    curve_points=_coerce_curve_points(list(binding_payload.get("curve_points", []))),
                    notes=str(binding_payload.get("notes", "")),
                )
                for binding_payload in bus_payload.get("RtpcBindings", [])
                if isinstance(binding_payload, dict)
            ],
            state_overrides=[
                StateOverrideModel(
                    group_name=str(override_payload.get("group_name", "")).strip(),
                    state_name=str(override_payload.get("state_name", "")).strip(),
                    volume_db=float(override_payload.get("volume_db", 0.0)),
                    pitch_cents=int(override_payload.get("pitch_cents", 0)),
                    is_muted=bool(override_payload.get("is_muted", False)),
                    notes=str(override_payload.get("notes", "")),
                )
                for override_payload in bus_payload.get("StateOverrides", [])
                if isinstance(override_payload, dict)
            ],
        )
        for bus_payload in bus_config_payloads
        if isinstance(bus_payload, dict)
    ]
    game_parameters = [
        GameParameterModel(
            name=str(parameter_payload.get("name", "")).strip(),
            default_value=float(parameter_payload.get("default_value", 0.0)),
            min_value=float(parameter_payload.get("min_value", 0.0)),
            max_value=float(parameter_payload.get("max_value", 100.0)),
            notes=str(parameter_payload.get("notes", "")),
        )
        for parameter_payload in gamesync_payload.get("GameParameters", [])
        if isinstance(parameter_payload, dict) and str(parameter_payload.get("name", "")).strip()
    ]
    state_groups = [
        StateGroupModel(
            name=str(group_payload.get("name", "")).strip(),
            states=[str(value) for value in group_payload.get("states", [])],
            default_state=str(group_payload.get("default_state", "")).strip(),
            state_effects=group_payload.get("state_effects", {}),
            notes=str(group_payload.get("notes", "")),
        )
        for group_payload in gamesync_payload.get("StateGroups", [])
        if isinstance(group_payload, dict) and str(group_payload.get("name", "")).strip()
    ]
    switch_groups = [
        SwitchGroupModel(
            name=str(group_payload.get("name", "")).strip(),
            switches=[str(value) for value in group_payload.get("switches", [])],
            default_switch=str(group_payload.get("default_switch", "")).strip(),
            use_game_parameter=bool(group_payload.get("use_game_parameter", False)),
            mapped_game_parameter=str(group_payload.get("mapped_game_parameter", "")).strip(),
            switch_effects=group_payload.get("switch_effects", {}),
            notes=str(group_payload.get("notes", "")),
        )
        for group_payload in gamesync_payload.get("SwitchGroups", [])
        if isinstance(group_payload, dict) and str(group_payload.get("name", "")).strip()
    ]
    project = AudioProject(
        name=payload.get("ProjectName", DEFAULT_PROJECT_NAME),
        project_version=payload.get("ProjectVersion", PROJECT_VERSION),
        created_at=payload.get("CreatedAt", utc_now_iso()),
        updated_at=payload.get("UpdatedAt", utc_now_iso()),
        settings=ProjectSettings(
            default_bus=settings_payload.get("DefaultBus", "SFX"),
            auto_assign_bus_by_name=bool(settings_payload.get("AutoAssignBusByName", True)),
            supported_formats=settings_payload.get("SupportedFormats", ["wav", "ogg"]),
            export_root=settings_payload.get("ExportRoot", "./Export"),
            buses=settings_payload.get("Buses", list(DEFAULT_BUSES)),
            bus_configs=bus_configs,
            source_audio_format=settings_payload.get("SourceAudioFormat", "wav"),
            runtime_audio_format=settings_payload.get("RuntimeAudioFormat", "ogg"),
        ),
        root_folder_ids=list(tree_payload.get("RootFolderIds", [])),
        game_parameters=game_parameters,
        state_groups=state_groups,
        switch_groups=switch_groups,
        file_path=file_path,
    )

    asset_payloads = payload.get("Assets", {})
    for source_path, asset_data in asset_payloads.items():
        if not isinstance(asset_data, dict):
            continue
        normalized = str(asset_data.get("source_path", source_path)).strip() or str(source_path).strip()
        if not normalized:
            continue
        project.asset_registry[normalized] = AssetRegistryEntry(
            source_path=normalized,
            discovered_at=str(asset_data.get("discovered_at", utc_now_iso())),
        )

    folder_payloads = tree_payload.get("Folders", {})
    for folder_id, folder_data in folder_payloads.items():
        project.folders[folder_id] = FolderModel(
            id=folder_id,
            name=folder_data["name"],
            child_folder_ids=list(folder_data.get("child_folder_ids", [])),
            child_event_ids=list(folder_data.get("child_event_ids", [])),
        )

    audio_payloads = payload.get("AudioObjects", {})
    for audio_id, audio_data in audio_payloads.items():
        if not isinstance(audio_data, dict):
            continue
        audio = AudioObjectModel(
            id=str(audio_data.get("id", audio_id)).strip() or str(audio_id).strip(),
            display_name=str(audio_data.get("display_name", "")).strip() or f"{audio_id}",
            bus=audio_data.get("bus", "SFX"),
            play_mode=audio_data.get("play_mode", "Random"),
            avoid_immediate_repeat=audio_data.get("avoid_immediate_repeat", False),
            volume_db=audio_data.get("volume_db", 0.0),
            volume_rand_min_db=audio_data.get("volume_rand_min_db", 0.0),
            volume_rand_max_db=audio_data.get("volume_rand_max_db", 0.0),
            pitch_cents=audio_data.get("pitch_cents", 0),
            pitch_rand_min_cents=audio_data.get("pitch_rand_min_cents", 0),
            pitch_rand_max_cents=audio_data.get("pitch_rand_max_cents", 0),
            combo_pitch_step_cents=audio_data.get("combo_pitch_step_cents", 100),
            combo_reset_seconds=audio_data.get("combo_reset_seconds", 1.5),
            combo_max_step=audio_data.get("combo_max_step", 0),
            load_policy=audio_data.get("load_policy", "OnDemand"),
            clips=audio_data.get("clips", []),
            rtpc_bindings=audio_data.get("rtpc_bindings", []),
            state_overrides=audio_data.get("state_overrides", []),
            switch_variants=audio_data.get("switch_variants", []),
        )
        project.audio_objects[audio.id] = audio

    event_payloads = payload.get("Events", {})
    for event_id, event_data in event_payloads.items():
        audio_id = str(event_data.get("audio_id", "")).strip()
        linked_audio = project.audio_objects.get(audio_id)
        if linked_audio is None:
            linked_audio = AudioObjectModel(id=audio_id or new_id("audio"), display_name=f"{event_data.get('display_name', event_id)} Audio")
            project.audio_objects[linked_audio.id] = linked_audio
        event = EventModel(
            id=event_id,
            display_name=event_data.get("display_name", ""),
            max_instances=event_data.get("max_instances", 0),
            cooldown_seconds=event_data.get("cooldown_seconds", 0.0),
            steal_policy=event_data.get("steal_policy", "RejectNew"),
            notes=event_data.get("notes", ""),
            audio_id=linked_audio.id,
            audio=linked_audio,
        )
        normalize_event_binding_states(event)
        project.events[event_id] = event

    if not project.root_folder_ids and not project.folders:
        default_folder = FolderModel(id=new_id("folder"), name="Default Work Unit")
        project.folders[default_folder.id] = default_folder
        project.root_folder_ids.append(default_folder.id)

    project.sync_asset_registry()

    return project