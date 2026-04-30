from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, ClipModel, ValidationIssue
from audioforge.app.services.audio_processor import AudioProcessor
from audioforge.app.utils.constants import (
    DEFAULT_AUDIO_MANIFEST_FILENAME,
    DEFAULT_BUILD_REPORT_FILENAME,
    DEFAULT_EVENT_ENUM_FILENAME,
    DEFAULT_EXPORT_ASSETS_DIRNAME,
    DEFAULT_RUNTIME_DATA_FILENAME,
    SCHEMA_VERSION,
)


@dataclass(slots=True)
class ExportRequest:
    scope: str = "full"
    selected_event_ids: tuple[str, ...] = ()
    selection_label: str = "整个工程"


@dataclass(slots=True)
class ExportPlan:
    requested_scope: str
    effective_scope: str
    reason: str
    selection_label: str
    selected_event_ids: tuple[str, ...] = ()
    selected_asset_keys: tuple[str, ...] = ()
    added_event_ids: tuple[str, ...] = ()
    changed_event_ids: tuple[str, ...] = ()
    removed_event_ids: tuple[str, ...] = ()
    added_asset_keys: tuple[str, ...] = ()
    changed_asset_keys: tuple[str, ...] = ()
    removed_asset_keys: tuple[str, ...] = ()
    rebuilt_asset_keys: tuple[str, ...] = ()
    reused_asset_keys: tuple[str, ...] = ()
    out_of_scope_dirty_asset_keys: tuple[str, ...] = ()
    current_asset_entries: list[dict[str, object]] = field(default_factory=list)
    current_runtime_payload: dict[str, object] = field(default_factory=dict)
    previous_asset_paths: dict[str, str] = field(default_factory=dict)

    def to_report_dict(self) -> dict[str, object]:
        return {
            "RequestedScope": self.requested_scope,
            "EffectiveScope": self.effective_scope,
            "Reason": self.reason,
            "SelectionLabel": self.selection_label,
            "SelectedEventIds": list(self.selected_event_ids),
            "SelectedAssetKeys": list(self.selected_asset_keys),
            "AddedEventIds": list(self.added_event_ids),
            "ChangedEventIds": list(self.changed_event_ids),
            "RemovedEventIds": list(self.removed_event_ids),
            "AddedAssetKeys": list(self.added_asset_keys),
            "ChangedAssetKeys": list(self.changed_asset_keys),
            "RemovedAssetKeys": list(self.removed_asset_keys),
            "RebuiltAssetKeys": list(self.rebuilt_asset_keys),
            "ReusedAssetKeys": list(self.reused_asset_keys),
            "OutOfScopeDirtyAssetKeys": list(self.out_of_scope_dirty_asset_keys),
            "TotalEventCount": len(self.current_runtime_payload.get("Events", {})),
            "TotalAssetCount": len(self.current_asset_entries),
        }


@dataclass(slots=True)
class ExportResult:
    export_root: Path
    data_file: Path
    enum_file: Path
    manifest_file: Path
    report_file: Path
    assets_dir: Path
    plan: ExportPlan


class RuntimeExporter:
    def __init__(self) -> None:
        self.audio_processor = AudioProcessor()

    def export(
        self,
        project: AudioProject,
        export_root: Path,
        issues: list[ValidationIssue],
        copy_assets: bool = True,
        request: ExportRequest | None = None,
        plan: ExportPlan | None = None,
    ) -> ExportResult:
        parent = export_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f"{export_root.name}_", dir=str(parent)))
        resolved_plan = plan or self.plan_export(project, export_root, request)

        try:
            result = self._write_export(
                project,
                temp_root,
                issues,
                copy_assets=copy_assets,
                plan=resolved_plan,
                previous_export_root=export_root,
            )
            self._commit_export(temp_root, export_root)
            return ExportResult(
                export_root=export_root,
                data_file=export_root / DEFAULT_RUNTIME_DATA_FILENAME,
                enum_file=export_root / DEFAULT_EVENT_ENUM_FILENAME,
                manifest_file=export_root / DEFAULT_AUDIO_MANIFEST_FILENAME,
                report_file=export_root / DEFAULT_BUILD_REPORT_FILENAME,
                assets_dir=export_root / DEFAULT_EXPORT_ASSETS_DIRNAME,
                plan=resolved_plan,
            )
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def plan_export(self, project: AudioProject, export_root: Path, request: ExportRequest | None = None) -> ExportPlan:
        normalized_request = self._normalize_request(request)
        current_runtime_payload = self._build_runtime_payload(project)
        current_asset_entries = self._collect_asset_entries(project)
        current_manifest_assets = self._build_manifest_payload(current_asset_entries).get("Assets", [])
        current_event_map = dict(current_runtime_payload.get("Events", {}))
        current_asset_map = {str(asset.get("AssetKey", "")): asset for asset in current_manifest_assets}

        previous_manifest_payload = self._load_json_if_exists(export_root / DEFAULT_AUDIO_MANIFEST_FILENAME)
        previous_runtime_payload = self._load_json_if_exists(export_root / DEFAULT_RUNTIME_DATA_FILENAME)
        previous_asset_map = {
            str(asset.get("AssetKey", "")): asset
            for asset in (previous_manifest_payload or {}).get("Assets", [])
        }
        previous_event_map = dict((previous_runtime_payload or {}).get("Events", {}))
        previous_assets_dir = export_root / DEFAULT_EXPORT_ASSETS_DIRNAME

        added_event_ids = sorted(set(current_event_map) - set(previous_event_map))
        removed_event_ids = sorted(set(previous_event_map) - set(current_event_map))
        changed_event_ids = sorted(
            event_id
            for event_id in set(current_event_map) & set(previous_event_map)
            if current_event_map[event_id] != previous_event_map[event_id]
        )

        added_asset_keys = sorted(set(current_asset_map) - set(previous_asset_map))
        removed_asset_keys = sorted(set(previous_asset_map) - set(current_asset_map))
        changed_asset_keys: list[str] = []
        content_dirty_asset_keys: set[str] = set(added_asset_keys)
        previous_asset_paths = {
            asset_key: str(asset.get("ExportPath", ""))
            for asset_key, asset in previous_asset_map.items()
        }
        for asset_key in sorted(set(current_asset_map) & set(previous_asset_map)):
            current_asset = current_asset_map[asset_key]
            previous_asset = previous_asset_map[asset_key]
            metadata_changed = self._asset_metadata_signature(current_asset) != self._asset_metadata_signature(previous_asset)
            content_changed = self._asset_content_signature(current_asset) != self._asset_content_signature(previous_asset)
            previous_export_path = str(previous_asset.get("ExportPath", ""))
            previous_asset_file = previous_assets_dir / previous_export_path if previous_export_path else None
            if metadata_changed:
                changed_asset_keys.append(asset_key)
            if content_changed or previous_asset_file is None or not previous_asset_file.exists():
                content_dirty_asset_keys.add(asset_key)

        runtime_format_changed = bool(previous_runtime_payload) and current_runtime_payload.get("RuntimeAudioFormat") != previous_runtime_payload.get("RuntimeAudioFormat")
        export_is_seeded = previous_manifest_payload is not None and previous_runtime_payload is not None and previous_assets_dir.exists()
        force_full_reason: str | None = None
        if normalized_request.scope == "full":
            force_full_reason = "已按用户请求执行全量构建。"
        elif not export_is_seeded:
            force_full_reason = "目标目录缺少可复用的旧导出，已退回全量构建。"
        elif runtime_format_changed:
            force_full_reason = "运行时音频格式发生变化，必须重建全部资源。"

        selected_event_ids = tuple(sorted(event_id for event_id in normalized_request.selected_event_ids if event_id in current_event_map))
        selected_event_id_set = set(selected_event_ids)
        selected_asset_keys = tuple(
            sorted(
                asset_key
                for asset_key, asset in current_asset_map.items()
                if selected_event_id_set & set(asset.get("ReferencedByEvents", []))
            )
        )

        effective_scope = normalized_request.scope
        out_of_scope_dirty_asset_keys: list[str] = []
        if force_full_reason is not None:
            rebuild_asset_keys = sorted(current_asset_map)
            effective_scope = "full"
            reason = force_full_reason
        else:
            rebuild_asset_key_set = set(content_dirty_asset_keys)
            if normalized_request.scope == "selection":
                selected_asset_key_set = set(selected_asset_keys)
                out_of_scope_dirty_asset_keys = sorted(rebuild_asset_key_set - selected_asset_key_set)
                if out_of_scope_dirty_asset_keys:
                    effective_scope = "incremental"
                    reason = "检测到选区外仍有脏资源；为保证完整包一致性，已自动扩展为增量构建。"
                else:
                    reason = "已按当前选区推导脏资源并执行选中构建；元数据文件仍会全量刷新。"
            else:
                reason = "将复用未变化资源，仅重建受影响音频，并全量刷新元数据文件。"
            rebuild_asset_keys = sorted(rebuild_asset_key_set)

        rebuild_asset_key_set = set(rebuild_asset_keys)
        reused_asset_keys = sorted(asset_key for asset_key in current_asset_map if asset_key not in rebuild_asset_key_set)

        return ExportPlan(
            requested_scope=normalized_request.scope,
            effective_scope=effective_scope,
            reason=reason,
            selection_label=normalized_request.selection_label,
            selected_event_ids=selected_event_ids,
            selected_asset_keys=selected_asset_keys,
            added_event_ids=tuple(added_event_ids),
            changed_event_ids=tuple(changed_event_ids),
            removed_event_ids=tuple(removed_event_ids),
            added_asset_keys=tuple(added_asset_keys),
            changed_asset_keys=tuple(changed_asset_keys),
            removed_asset_keys=tuple(removed_asset_keys),
            rebuilt_asset_keys=tuple(rebuild_asset_keys),
            reused_asset_keys=tuple(reused_asset_keys),
            out_of_scope_dirty_asset_keys=tuple(out_of_scope_dirty_asset_keys),
            current_asset_entries=current_asset_entries,
            current_runtime_payload=current_runtime_payload,
            previous_asset_paths=previous_asset_paths,
        )

    def _write_export(
        self,
        project: AudioProject,
        export_root: Path,
        issues: list[ValidationIssue],
        copy_assets: bool,
        plan: ExportPlan,
        previous_export_root: Path,
    ) -> ExportResult:
        export_root.mkdir(parents=True, exist_ok=True)

        data_file = export_root / DEFAULT_RUNTIME_DATA_FILENAME
        enum_file = export_root / DEFAULT_EVENT_ENUM_FILENAME
        manifest_file = export_root / DEFAULT_AUDIO_MANIFEST_FILENAME
        report_file = export_root / DEFAULT_BUILD_REPORT_FILENAME
        assets_dir = export_root / DEFAULT_EXPORT_ASSETS_DIRNAME

        asset_entries = plan.current_asset_entries
        if copy_assets:
            self._materialize_assets(asset_entries, plan, previous_export_root, assets_dir)

        data_file.write_text(
            json.dumps(plan.current_runtime_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        enum_file.write_text(self._build_event_enum(project), encoding="utf-8")
        manifest_file.write_text(
            json.dumps(self._build_manifest_payload(asset_entries), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_file.write_text(
            json.dumps(
                self._build_report_payload(project, issues, [data_file, enum_file, manifest_file, report_file], assets_dir, plan),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return ExportResult(
            export_root=export_root,
            data_file=data_file,
            enum_file=enum_file,
            manifest_file=manifest_file,
            report_file=report_file,
            assets_dir=assets_dir,
            plan=plan,
        )

    def _commit_export(self, temp_root: Path, export_root: Path) -> None:
        backup_root = export_root.with_name(f"{export_root.name}.bak")
        if backup_root.exists():
            shutil.rmtree(backup_root)

        if export_root.exists():
            export_root.replace(backup_root)

        try:
            temp_root.replace(export_root)
        except Exception:
            if backup_root.exists() and not export_root.exists():
                backup_root.replace(export_root)
            raise
        else:
            if backup_root.exists():
                shutil.rmtree(backup_root)

    def _build_runtime_payload(self, project: AudioProject) -> dict[str, object]:
        events: dict[str, object] = {}
        for event_id in sorted(project.events):
            event = project.events[event_id]
            payload: dict[str, object] = {
                "Bus": event.bus,
                "PlayMode": event.play_mode,
                "AvoidImmediateRepeat": event.avoid_immediate_repeat,
                "VolumeDb": event.volume_db,
                "VolumeRandDb": [event.volume_rand_min_db, event.volume_rand_max_db],
                "PitchCents": event.pitch_cents,
                "PitchRandCents": [event.pitch_rand_min_cents, event.pitch_rand_max_cents],
                "MaxInstances": event.max_instances,
                "CooldownSeconds": event.cooldown_seconds,
                "StealPolicy": event.steal_policy,
                "LoadPolicy": event.load_policy,
                "Clips": [
                    {
                        "ClipId": clip.id,
                        "AssetKey": clip.asset_key,
                        "Weight": clip.weight,
                        "TrimStartMs": clip.trim_start_ms,
                        "TrimEndMs": clip.trim_end_ms,
                        "FadeInMs": clip.fade_in_ms,
                        "FadeOutMs": clip.fade_out_ms,
                        "LoopStartMs": clip.loop_start_ms,
                        "LoopEndMs": clip.loop_end_ms,
                    }
                    for clip in event.clips
                ],
            }
            if event.play_mode == "Combo":
                payload["ComboPitchStepCents"] = event.combo_pitch_step_cents
                payload["ComboResetSeconds"] = event.combo_reset_seconds
                payload["ComboMaxStep"] = event.combo_max_step
            events[event_id] = payload

        return {
            "SchemaVersion": SCHEMA_VERSION,
            "GeneratedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "ProjectName": project.name,
            "RuntimeAudioFormat": project.settings.runtime_audio_format.lower(),
            "Buses": list(project.settings.buses),
            "BusConfigs": [config.to_dict() for config in project.settings.bus_configs],
            "Events": events,
        }

    def _build_event_enum(self, project: AudioProject) -> str:
        members = ",\n".join(f"    {event_id}" for event_id in sorted(project.events))
        return "public enum AudioEventID\n{\n" + members + "\n}\n"

    def _build_manifest_payload(self, asset_entries: list[dict[str, object]]) -> dict[str, object]:
        manifest_entries = []
        for entry in asset_entries:
            manifest_entries.append(
                {
                    "AssetKey": entry["AssetKey"],
                    "SourcePath": entry["SourcePath"],
                    "ExportPath": entry["ExportPath"],
                    "SourceFormat": entry["SourceFormat"],
                    "RuntimeFormat": entry["RuntimeFormat"],
                    "TrimStartMs": entry["TrimStartMs"],
                    "TrimEndMs": entry["TrimEndMs"],
                    "FadeInMs": entry["FadeInMs"],
                    "FadeOutMs": entry["FadeOutMs"],
                    "LoopStartMs": entry["LoopStartMs"],
                    "LoopEndMs": entry["LoopEndMs"],
                    "FileSize": entry["FileSize"],
                    "Hash": entry["Hash"],
                    "BuildFingerprint": entry["BuildFingerprint"],
                    "ReferencedByEvents": entry["ReferencedByEvents"],
                }
            )
        return {"Assets": manifest_entries}

    def _build_report_payload(
        self,
        project: AudioProject,
        issues: list[ValidationIssue],
        exported_files: list[Path],
        assets_dir: Path,
        plan: ExportPlan,
    ) -> dict[str, object]:
        return {
            "ProjectVersion": project.project_version,
            "SchemaVersion": SCHEMA_VERSION,
            "EventCount": len(project.events),
            "ClipCount": sum(len(event.clips) for event in project.events.values()),
            "ErrorCount": sum(1 for issue in issues if issue.severity == "Error"),
            "WarningCount": sum(1 for issue in issues if issue.severity == "Warning"),
            "ExportedFiles": [path.name for path in exported_files],
            "AssetsDirectory": assets_dir.name,
            "Issues": [asdict(issue) for issue in issues],
            "BuildPlan": plan.to_report_dict(),
        }

    def _collect_asset_entries(self, project: AudioProject) -> list[dict[str, object]]:
        owners: dict[str, set[str]] = {}
        source_paths: dict[str, Path | None] = {}
        export_paths: dict[str, str] = {}
        clip_by_asset_key: dict[str, ClipModel] = {}

        for event_id, event in project.events.items():
            for clip in event.clips:
                asset_key = clip.asset_key
                owners.setdefault(asset_key, set()).add(event_id)
                source_path = Path(clip.source_path) if clip.source_path else None
                if clip.source_path and asset_key not in source_paths:
                    source_paths[asset_key] = source_path
                clip_by_asset_key.setdefault(asset_key, clip)
                export_paths.setdefault(
                    asset_key,
                    self._resolve_asset_export_path(clip, project.settings.runtime_audio_format),
                )

        entries: list[dict[str, object]] = []
        runtime_format = project.settings.runtime_audio_format.lower()
        for asset_key in sorted(owners):
            source_path = source_paths.get(asset_key)
            export_path = export_paths[asset_key]
            clip = clip_by_asset_key[asset_key]
            file_size = source_path.stat().st_size if source_path and source_path.exists() else 0
            file_hash = self._hash_file(source_path) if source_path and source_path.exists() else ""
            entries.append(
                {
                    "AssetKey": asset_key,
                    "SourcePath": str(source_path) if source_path else "",
                    "ExportPath": export_path,
                    "SourceFormat": source_path.suffix.lstrip(".").lower() if source_path else "",
                    "RuntimeFormat": runtime_format,
                    "TrimStartMs": clip.trim_start_ms,
                    "TrimEndMs": clip.trim_end_ms,
                    "FadeInMs": clip.fade_in_ms,
                    "FadeOutMs": clip.fade_out_ms,
                    "LoopStartMs": clip.loop_start_ms,
                    "LoopEndMs": clip.loop_end_ms,
                    "FileSize": file_size,
                    "Hash": file_hash,
                    "BuildFingerprint": self._build_asset_fingerprint(file_hash, runtime_format, clip),
                    "ReferencedByEvents": sorted(owners[asset_key]),
                    "Clip": clip,
                    "ProjectSettings": project.settings,
                }
            )
        return entries

    def _materialize_assets(
        self,
        asset_entries: list[dict[str, object]],
        plan: ExportPlan,
        previous_export_root: Path,
        assets_dir: Path,
    ) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        entries_by_key = {str(entry["AssetKey"]): entry for entry in asset_entries}
        for asset_key in plan.rebuilt_asset_keys:
            entry = entries_by_key.get(asset_key)
            if entry is None:
                continue
            self._export_asset_entry(entry, assets_dir)

        previous_assets_dir = previous_export_root / DEFAULT_EXPORT_ASSETS_DIRNAME
        for asset_key in plan.reused_asset_keys:
            entry = entries_by_key.get(asset_key)
            if entry is None:
                continue
            previous_export_path = plan.previous_asset_paths.get(asset_key) or str(entry["ExportPath"])
            previous_asset_path = previous_assets_dir / previous_export_path
            if previous_asset_path.exists():
                target = assets_dir / str(entry["ExportPath"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(previous_asset_path, target)
                continue
            self._export_asset_entry(entry, assets_dir)

    def _export_asset_entry(self, entry: dict[str, object], assets_dir: Path) -> None:
        source_path = str(entry["SourcePath"])
        if not source_path:
            return
        source = Path(source_path)
        if not source.exists():
            return
        target = assets_dir / str(entry["ExportPath"])
        clip = entry["Clip"]
        project_settings = entry["ProjectSettings"]
        self.audio_processor.export_clip(clip, project_settings, target)

    def _resolve_asset_export_path(self, clip: ClipModel, runtime_audio_format: str) -> str:
        base_path = clip.export_path or clip.asset_key or clip.id
        normalized = base_path.replace("\\", "/")
        suffix = f".{runtime_audio_format.lower()}"
        path = Path(normalized)
        if path.suffix:
            return str(path.with_suffix(suffix)).replace("\\", "/")
        return f"{normalized}{suffix}"

    def _hash_file(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _normalize_request(self, request: ExportRequest | None) -> ExportRequest:
        if request is None:
            return ExportRequest()
        normalized_scope = str(request.scope or "full").strip().lower()
        if normalized_scope not in {"full", "incremental", "selection"}:
            normalized_scope = "full"
        selected_event_ids = tuple(dict.fromkeys(str(event_id) for event_id in request.selected_event_ids if str(event_id).strip()))
        selection_label = str(request.selection_label or "整个工程").strip() or "整个工程"
        return ExportRequest(
            scope=normalized_scope,
            selected_event_ids=selected_event_ids,
            selection_label=selection_label,
        )

    def _load_json_if_exists(self, file_path: Path) -> dict[str, object] | None:
        if not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _build_asset_fingerprint(self, file_hash: str, runtime_format: str, clip: ClipModel) -> str:
        payload = {
            "Hash": file_hash,
            "RuntimeFormat": runtime_format,
            "TrimStartMs": clip.trim_start_ms,
            "TrimEndMs": clip.trim_end_ms,
            "FadeInMs": clip.fade_in_ms,
            "FadeOutMs": clip.fade_out_ms,
            "LoopStartMs": clip.loop_start_ms,
            "LoopEndMs": clip.loop_end_ms,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _asset_content_signature(self, asset: dict[str, object]) -> tuple[object, ...]:
        return (
            asset.get("BuildFingerprint") or asset.get("Hash"),
            asset.get("RuntimeFormat"),
            asset.get("TrimStartMs"),
            asset.get("TrimEndMs"),
            asset.get("FadeInMs"),
            asset.get("FadeOutMs"),
            asset.get("LoopStartMs"),
            asset.get("LoopEndMs"),
        )

    def _asset_metadata_signature(self, asset: dict[str, object]) -> tuple[object, ...]:
        return (
            asset.get("SourcePath"),
            asset.get("ExportPath"),
            asset.get("SourceFormat"),
            asset.get("RuntimeFormat"),
            asset.get("TrimStartMs"),
            asset.get("TrimEndMs"),
            asset.get("FadeInMs"),
            asset.get("FadeOutMs"),
            asset.get("LoopStartMs"),
            asset.get("LoopEndMs"),
            tuple(asset.get("ReferencedByEvents", [])),
        )