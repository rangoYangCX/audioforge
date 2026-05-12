from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

try:
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    sf = None

from audioforge.app.models.audio_project import AudioProject, MASTER_BUS_NAME, ValidationIssue, effective_event_clips
from audioforge.app.utils.constants import (
    MAX_CLIP_TIME_MS,
    MAX_CLIP_WEIGHT,
    MAX_COOLDOWN_SECONDS,
    MAX_COMBO_MAX_STEP,
    MAX_MAX_INSTANCES,
    MAX_PITCH_CENTS,
    MAX_VOLUME_DB,
    MIN_CLIP_TIME_MS,
    MIN_CLIP_WEIGHT,
    MIN_COOLDOWN_SECONDS,
    MIN_COMBO_MAX_STEP,
    MIN_MAX_INSTANCES,
    MIN_PITCH_CENTS,
    MIN_VOLUME_DB,
    SUPPORTED_RUNTIME_AUDIO_FORMATS,
    SUPPORTED_SOURCE_AUDIO_EXTENSIONS,
)

EVENT_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
ASSET_KEY_RECOMMENDED_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[\/_-][A-Za-z0-9]+)*(?:\.[A-Za-z0-9]+)?$")
PLACEHOLDER_EVENT_ID_PATTERN = re.compile(r"^(New_?Event|Event(?:_[0-9]+)?)$", re.IGNORECASE)
MUSIC_NAME_TOKENS = {"bgm", "music", "theme", "ambient", "loop"}


class ProjectValidator:
    def validate(self, project: AudioProject) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_events(project))
        issues.extend(self._validate_asset_keys(project))
        issues.extend(self._validate_project_settings(project))
        return issues

    def _validate_project_settings(self, project: AudioProject) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if project.settings.source_audio_format.lower() not in {fmt.lstrip('.') for fmt in SUPPORTED_SOURCE_AUDIO_EXTENSIONS}:
            issues.append(
                ValidationIssue(
                    "Error",
                    "SOURCE_AUDIO_FORMAT_INVALID",
                    f"Unsupported source audio format: {project.settings.source_audio_format}",
                    project.name,
                )
            )
        if project.settings.runtime_audio_format.lower() not in SUPPORTED_RUNTIME_AUDIO_FORMATS:
            issues.append(
                ValidationIssue(
                    "Error",
                    "RUNTIME_AUDIO_FORMAT_INVALID",
                    f"Unsupported runtime audio format: {project.settings.runtime_audio_format}",
                    project.name,
                )
            )
        bus_names = {bus_name.casefold(): bus_name for bus_name in project.settings.buses}
        for bus_config in project.settings.bus_configs:
            parent_bus = str(bus_config.parent_bus).strip() or MASTER_BUS_NAME
            if str(bus_config.name).casefold() == MASTER_BUS_NAME.casefold():
                continue
            if parent_bus.casefold() == str(bus_config.name).casefold():
                issues.append(
                    ValidationIssue(
                        "Error",
                        "BUS_PARENT_SELF",
                        f"Bus '{bus_config.name}' cannot route to itself.",
                        project.name,
                    )
                )
            elif parent_bus.casefold() != MASTER_BUS_NAME.casefold() and parent_bus.casefold() not in bus_names:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "BUS_PARENT_INVALID",
                        f"Bus '{bus_config.name}' routes to missing parent '{parent_bus}'.",
                        project.name,
                    )
                )

        parent_map = {config.name: config.parent_bus for config in project.settings.bus_configs}
        for bus_name in parent_map:
            seen: set[str] = set()
            current = bus_name
            while current in parent_map:
                parent_bus = str(parent_map[current]).strip() or MASTER_BUS_NAME
                if parent_bus.casefold() == MASTER_BUS_NAME.casefold():
                    break
                if parent_bus in seen or parent_bus == bus_name:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "BUS_ROUTE_CYCLE",
                            f"Bus routing contains a cycle starting at '{bus_name}'.",
                            project.name,
                        )
                    )
                    break
                seen.add(parent_bus)
                current = parent_bus
        for bus_config in project.settings.bus_configs:
            if bus_config.volume_db > 0.0:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "BUS_GAIN_ABOVE_UNITY_REFERENCE",
                        f"Bus '{bus_config.name}' uses positive gain {bus_config.volume_db:.1f} dB. Reference preview/runtime backends may clip or depend on backend-specific headroom handling.",
                        project.name,
                    )
                )
        return issues

    def _validate_events(self, project: AudioProject) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        bus_gain_map = self._project_bus_gain_map(project)
        event_ids_by_casefold: dict[str, set[str]] = defaultdict(set)

        for event_id in project.events:
            normalized_event_id = str(event_id).strip()
            if normalized_event_id:
                event_ids_by_casefold[normalized_event_id.casefold()].add(normalized_event_id)

        for event_ids in event_ids_by_casefold.values():
            if len(event_ids) > 1:
                details = ", ".join(sorted(event_ids))
                for event_id in sorted(event_ids):
                    issues.append(
                        ValidationIssue(
                            "Warning",
                            "EVENT_ID_CASE_VARIANT_CONFLICT",
                            f"Event IDs differ only by letter case: {details}. This is easy to confuse in tools and code review.",
                            event_id,
                        )
                    )

        for event_id, event in project.events.items():
            runtime_clips = effective_event_clips(event)
            if not event_id:
                issues.append(ValidationIssue("Error", "EVENT_ID_EMPTY", "Event ID is required.", event_id))
                continue
            if not EVENT_ID_PATTERN.match(event_id):
                issues.append(
                    ValidationIssue("Error", "EVENT_ID_INVALID", f"Invalid Event ID: {event_id}", event_id)
                )
            elif PLACEHOLDER_EVENT_ID_PATTERN.match(event_id):
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "EVENT_ID_PLACEHOLDER_NAME",
                        f"Event ID '{event_id}' still uses a placeholder-style name. Rename it before content scales up.",
                        event_id,
                    )
                )
            if event.bus not in project.settings.buses:
                issues.append(
                    ValidationIssue("Error", "BUS_INVALID", f"Bus '{event.bus}' is not registered.", event_id)
                )
            suggested_bus_issue = self._validate_bus_suggestion(project, event_id, event.display_name or event_id, event.bus)
            if suggested_bus_issue is not None:
                issues.append(suggested_bus_issue)
            if event.steal_policy == "StopQuietest":
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "STEAL_POLICY_NOT_IMPLEMENTED",
                        "StopQuietest is not implemented in the current preview/runtime pipeline.",
                        event_id,
                    )
                )
            if event.load_policy != "OnDemand":
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "LOAD_POLICY_NOT_IMPLEMENTED",
                        "LoadPolicy is fixed to OnDemand in the current preview/runtime pipeline.",
                        event_id,
                    )
                )
            if not event.clips:
                issues.append(ValidationIssue("Error", "EVENT_NO_CLIPS", "Event has no clips.", event_id))
            elif not runtime_clips:
                issues.append(ValidationIssue("Error", "EVENT_NO_ENABLED_CLIPS", "Event has no effective active clips.", event_id))
            if not MIN_VOLUME_DB <= event.volume_db <= MAX_VOLUME_DB:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "VOLUME_OUT_OF_RANGE",
                        f"VolumeDb must be between {MIN_VOLUME_DB:.1f} and {MAX_VOLUME_DB:.1f}.",
                        event_id,
                    )
                )
            if not MIN_VOLUME_DB <= event.volume_rand_min_db <= MAX_VOLUME_DB or not MIN_VOLUME_DB <= event.volume_rand_max_db <= MAX_VOLUME_DB:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "VOLUME_RANDOM_OUT_OF_RANGE",
                        f"Volume random range must stay between {MIN_VOLUME_DB:.1f} and {MAX_VOLUME_DB:.1f}.",
                        event_id,
                    )
                )
            if not MIN_PITCH_CENTS <= event.pitch_cents <= MAX_PITCH_CENTS:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "PITCH_OUT_OF_RANGE",
                        f"PitchCents must be between {MIN_PITCH_CENTS} and {MAX_PITCH_CENTS}.",
                        event_id,
                    )
                )
            if not MIN_PITCH_CENTS <= event.pitch_rand_min_cents <= MAX_PITCH_CENTS or not MIN_PITCH_CENTS <= event.pitch_rand_max_cents <= MAX_PITCH_CENTS:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "PITCH_RANDOM_OUT_OF_RANGE",
                        f"Pitch random range must stay between {MIN_PITCH_CENTS} and {MAX_PITCH_CENTS}.",
                        event_id,
                    )
                )
            if not MIN_COOLDOWN_SECONDS <= event.cooldown_seconds <= MAX_COOLDOWN_SECONDS:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "COOLDOWN_OUT_OF_RANGE",
                        f"CooldownSeconds must be between {MIN_COOLDOWN_SECONDS:.1f} and {MAX_COOLDOWN_SECONDS:.1f}.",
                        event_id,
                    )
                )
            if not MIN_MAX_INSTANCES <= event.max_instances <= MAX_MAX_INSTANCES:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "MAX_INSTANCES_OUT_OF_RANGE",
                        f"MaxInstances must be between {MIN_MAX_INSTANCES} and {MAX_MAX_INSTANCES}.",
                        event_id,
                    )
                )
            if not MIN_PITCH_CENTS <= event.combo_pitch_step_cents <= MAX_PITCH_CENTS:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "COMBO_PITCH_STEP_OUT_OF_RANGE",
                        f"ComboPitchStepCents must be between {MIN_PITCH_CENTS} and {MAX_PITCH_CENTS}.",
                        event_id,
                    )
                )
            elif event.combo_pitch_step_cents % 100 != 0:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "COMBO_PITCH_STEP_NOT_SEMITONE",
                        "ComboPitchStepCents must use semitone steps (multiples of 100 cents).",
                        event_id,
                    )
                )
            if not MIN_COOLDOWN_SECONDS <= event.combo_reset_seconds <= MAX_COOLDOWN_SECONDS:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "COMBO_RESET_OUT_OF_RANGE",
                        f"ComboResetSeconds must be between {MIN_COOLDOWN_SECONDS:.1f} and {MAX_COOLDOWN_SECONDS:.1f}.",
                        event_id,
                    )
                )
            if not MIN_COMBO_MAX_STEP <= event.combo_max_step <= MAX_COMBO_MAX_STEP:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "COMBO_MAX_STEP_OUT_OF_RANGE",
                        f"ComboMaxStep must be between {MIN_COMBO_MAX_STEP} and {MAX_COMBO_MAX_STEP}.",
                        event_id,
                    )
                )
            if event.volume_rand_min_db > event.volume_rand_max_db:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "VOLUME_RANDOM_RANGE_INVALID",
                        "Volume random minimum is greater than maximum.",
                        event_id,
                    )
                )
            if event.pitch_rand_min_cents > event.pitch_rand_max_cents:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "PITCH_RANDOM_RANGE_INVALID",
                        "Pitch random minimum is greater than maximum.",
                        event_id,
                    )
                )
            if event.play_mode == "Combo":
                if event.combo_reset_seconds <= 0:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "COMBO_RESET_INVALID",
                            "Combo reset seconds must be greater than 0.",
                            event_id,
                        )
                    )
            if len(runtime_clips) == 1 and event.avoid_immediate_repeat:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "AVOID_REPEAT_REDUNDANT",
                        "AvoidImmediateRepeat has no effect with a single clip.",
                        event_id,
                    )
                )
            if event.play_mode == "Sequence" and len(runtime_clips) == 1:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "SEQUENCE_SINGLE_CLIP",
                        "Sequence mode only has one clip.",
                        event_id,
                    )
                )
            if event.cooldown_seconds > 5:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "COOLDOWN_HIGH",
                        "Cooldown is greater than 5 seconds.",
                        event_id,
                    )
                )
            peak_reference_gain_db = event.volume_db + event.volume_rand_max_db + bus_gain_map.get(event.bus, 0.0)
            if peak_reference_gain_db > 0.0:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "REFERENCE_GAIN_ABOVE_UNITY",
                        f"Event peak reference gain reaches {peak_reference_gain_db:.1f} dB after bus routing. Local preview and the Unity reference runtime may rely on backend-specific clamping above unity.",
                        event_id,
                    )
                )

            for clip in event.clips:
                clip_path = Path(clip.source_path)
                if not MIN_CLIP_WEIGHT <= clip.weight <= MAX_CLIP_WEIGHT:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_WEIGHT_INVALID",
                            f"Clip '{clip.id}' weight must be between {MIN_CLIP_WEIGHT} and {MAX_CLIP_WEIGHT}.",
                            event_id,
                        )
                    )
                if clip_path.suffix.lower() and clip_path.suffix.lower() not in {".wav", ".mp3", ".ogg"}:
                    issues.append(
                        ValidationIssue(
                            "Warning",
                            "CLIP_FORMAT_UNRECOMMENDED",
                            f"Clip '{clip.id}' uses unsupported recommended format '{clip_path.suffix}'.",
                            event_id,
                        )
                    )
                if clip.source_path and not clip_path.exists():
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_SOURCE_MISSING",
                            f"Clip source path does not exist: {clip.source_path}",
                            event_id,
                        )
                    )
                if clip.trim_start_ms < MIN_CLIP_TIME_MS or clip.trim_end_ms < MIN_CLIP_TIME_MS or clip.loop_start_ms < MIN_CLIP_TIME_MS or clip.loop_end_ms < MIN_CLIP_TIME_MS:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_TIME_NEGATIVE",
                            f"Clip '{clip.id}' contains negative trim or loop values.",
                            event_id,
                        )
                    )
                if clip.trim_start_ms > MAX_CLIP_TIME_MS or clip.trim_end_ms > MAX_CLIP_TIME_MS or clip.loop_start_ms > MAX_CLIP_TIME_MS or clip.loop_end_ms > MAX_CLIP_TIME_MS:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_TIME_OUT_OF_RANGE",
                            f"Clip '{clip.id}' trim and loop values must be between {MIN_CLIP_TIME_MS} and {MAX_CLIP_TIME_MS} ms.",
                            event_id,
                        )
                    )
                actual_duration_ms = self._clip_duration_ms(clip_path) if clip.source_path and clip_path.exists() else None
                if actual_duration_ms is not None:
                    if clip.trim_start_ms > actual_duration_ms or clip.loop_start_ms > actual_duration_ms or (clip.trim_end_ms > 0 and clip.trim_end_ms > actual_duration_ms) or (clip.loop_end_ms > 0 and clip.loop_end_ms > actual_duration_ms):
                        issues.append(
                            ValidationIssue(
                                "Error",
                                "CLIP_TIME_EXCEEDS_SOURCE_LENGTH",
                                f"Clip '{clip.id}' trim or loop values exceed source length {actual_duration_ms} ms.",
                                event_id,
                            )
                        )
                if clip.trim_end_ms > 0 and clip.trim_start_ms >= clip.trim_end_ms:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_TRIM_INVALID",
                            f"Clip '{clip.id}' trim start must be smaller than trim end.",
                            event_id,
                        )
                    )
                if clip.loop_end_ms > 0 and clip.loop_start_ms >= clip.loop_end_ms:
                    issues.append(
                        ValidationIssue(
                            "Error",
                            "CLIP_LOOP_INVALID",
                            f"Clip '{clip.id}' loop start must be smaller than loop end.",
                            event_id,
                        )
                    )
                if clip.loop_start_ms > 0 or clip.loop_end_ms > 0:
                    issues.append(
                        ValidationIssue(
                            "Warning",
                            "CLIP_LOOP_NOT_IMPLEMENTED",
                            f"Clip '{clip.id}' loop settings are reserved but not implemented in the current preview/runtime pipeline.",
                            event_id,
                        )
                    )

        return issues

    def _clip_duration_ms(self, clip_path: Path) -> int | None:
        if sf is None:
            return None
        try:
            info = sf.info(str(clip_path))
        except Exception:
            return None
        if info.samplerate <= 0:
            return None
        return int(round(info.frames * 1000.0 / info.samplerate))

    def _validate_asset_keys(self, project: AudioProject) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        owners: dict[str, set[str]] = defaultdict(set)
        sources: dict[str, set[str]] = defaultdict(set)
        asset_keys_by_source: dict[str, set[str]] = defaultdict(set)
        source_owners: dict[str, set[str]] = defaultdict(set)
        export_paths: dict[str, set[str]] = defaultdict(set)
        export_path_owners: dict[str, set[str]] = defaultdict(set)

        for event_id, event in project.events.items():
            for clip in event.clips:
                owners[clip.asset_key].add(event_id)
                sources[clip.asset_key].add(clip.source_path)
                normalized_source = str(clip.source_path).strip()
                if normalized_source:
                    asset_keys_by_source[normalized_source].add(clip.asset_key)
                    source_owners[normalized_source].add(event_id)
                export_path = self._resolve_asset_export_path(clip, project.settings.runtime_audio_format)
                export_paths[export_path.casefold()].add(clip.asset_key)
                export_path_owners[export_path.casefold()].add(event_id)

        for asset_key, source_paths in sources.items():
            path_style_issues: list[str] = []
            if "\\" in asset_key:
                path_style_issues.append("contains backslashes")
            if "//" in asset_key:
                path_style_issues.append("contains repeated '/'")
            if asset_key.startswith("/") or asset_key.endswith("/"):
                path_style_issues.append("starts or ends with '/'")
            if path_style_issues:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "ASSET_KEY_PATH_STYLE_INCONSISTENT",
                        f"AssetKey '{asset_key}' has inconsistent path style ({'; '.join(path_style_issues)}). Use normalized forward-slash paths without leading/trailing separators.",
                        ",".join(sorted(owners[asset_key])),
                    )
                )
            if asset_key and not ASSET_KEY_RECOMMENDED_PATTERN.match(asset_key):
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "ASSET_KEY_STYLE_NON_STANDARD",
                        f"AssetKey '{asset_key}' should avoid spaces and use clean path-style separators like '/', '_' or '-'.",
                        ",".join(sorted(owners[asset_key])),
                    )
                )
            if len(source_paths) > 1:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "ASSET_KEY_CONFLICT",
                        f"AssetKey '{asset_key}' maps to multiple source files.",
                        ",".join(sorted(owners[asset_key])),
                    )
                )

        for source_path, asset_keys in asset_keys_by_source.items():
            normalized_asset_keys = {asset_key for asset_key in asset_keys if str(asset_key).strip()}
            if len(normalized_asset_keys) > 1:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "SOURCE_REUSED_WITH_MULTIPLE_ASSET_KEYS",
                        f"Source file '{source_path}' is exported under multiple AssetKeys: {', '.join(sorted(normalized_asset_keys))}.",
                        ",".join(sorted(source_owners[source_path])),
                    )
                )

        for export_path_key, asset_keys in export_paths.items():
            normalized_asset_keys = {asset_key for asset_key in asset_keys if str(asset_key).strip()}
            if len(normalized_asset_keys) > 1:
                issues.append(
                    ValidationIssue(
                        "Error",
                        "ASSET_EXPORT_PATH_CONFLICT",
                        f"Multiple AssetKeys resolve to the same export path '{export_path_key}': {', '.join(sorted(normalized_asset_keys))}.",
                        ",".join(sorted(export_path_owners[export_path_key])),
                    )
                )

        referenced_sources = {
            str(clip.source_path).strip()
            for event in project.events.values()
            for clip in event.clips
            if str(clip.source_path).strip()
        }
        for source_path in sorted(project.asset_registry):
            if source_path not in referenced_sources:
                issues.append(
                    ValidationIssue(
                        "Warning",
                        "REGISTERED_SOURCE_UNUSED",
                        f"Registered source '{source_path}' is not referenced by any current clip.",
                        project.name,
                    )
                )

        return issues

    def _validate_bus_suggestion(
        self,
        project: AudioProject,
        event_id: str,
        raw_name: str,
        current_bus: str,
    ) -> ValidationIssue | None:
        bus_lookup = {bus.casefold(): bus for bus in project.settings.buses}
        suggested_bgm_bus = bus_lookup.get("bgm")
        if not suggested_bgm_bus:
            return None
        tokens = {token for token in re.split(r"[^a-z0-9]+", raw_name.casefold()) if token}
        if tokens & MUSIC_NAME_TOKENS and current_bus != suggested_bgm_bus:
            return ValidationIssue(
                "Warning",
                "BUS_CLASSIFICATION_SUGGEST_BGM",
                f"Event '{event_id}' looks like music/loop content and is usually better routed to BGM instead of '{current_bus}'.",
                event_id,
            )
        return None

    def _resolve_asset_export_path(self, clip, runtime_audio_format: str) -> str:
        base_path = str(getattr(clip, "export_path", "") or getattr(clip, "asset_key", "") or getattr(clip, "id", ""))
        normalized = base_path.replace("\\", "/")
        suffix = f".{runtime_audio_format.lower()}"
        path = Path(normalized)
        if path.suffix:
            return str(path.with_suffix(suffix)).replace("\\", "/")
        return f"{normalized}{suffix}"

    def _project_bus_gain_map(self, project: AudioProject) -> dict[str, float]:
        config_map = {config.name: config for config in project.settings.bus_configs}
        gain_map: dict[str, float] = {}
        for bus_name in config_map:
            gain_db = 0.0
            current = bus_name
            visited: set[str] = set()
            while current in config_map:
                config = config_map[current]
                gain_db += config.volume_db
                parent_name = str(config.parent_bus).strip() or MASTER_BUS_NAME
                if current == MASTER_BUS_NAME or parent_name == MASTER_BUS_NAME:
                    break
                if current in visited:
                    break
                visited.add(current)
                current = parent_name
            gain_map[bus_name] = gain_db
        return gain_map