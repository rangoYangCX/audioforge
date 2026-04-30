from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, ClipModel, ValidationIssue
from audioforge.app.services.audio_processor import AudioProcessor
from audioforge.app.utils.constants import (
    DEFAULT_AUDIO_MANIFEST_FILENAME,
    DEFAULT_EXPORT_ASSETS_DIRNAME,
    DEFAULT_BUILD_REPORT_FILENAME,
    DEFAULT_EVENT_ENUM_FILENAME,
    DEFAULT_RUNTIME_DATA_FILENAME,
    SCHEMA_VERSION,
)


@dataclass(slots=True)
class ExportResult:
    export_root: Path
    data_file: Path
    enum_file: Path
    manifest_file: Path
    report_file: Path
    assets_dir: Path


class RuntimeExporter:
    def __init__(self) -> None:
        self.audio_processor = AudioProcessor()

    def export(self, project: AudioProject, export_root: Path, issues: list[ValidationIssue], copy_assets: bool = True) -> ExportResult:
        parent = export_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f"{export_root.name}_", dir=str(parent)))

        try:
            result = self._write_export(project, temp_root, issues, copy_assets=copy_assets)
            self._commit_export(temp_root, export_root)
            return ExportResult(
                export_root=export_root,
                data_file=export_root / DEFAULT_RUNTIME_DATA_FILENAME,
                enum_file=export_root / DEFAULT_EVENT_ENUM_FILENAME,
                manifest_file=export_root / DEFAULT_AUDIO_MANIFEST_FILENAME,
                report_file=export_root / DEFAULT_BUILD_REPORT_FILENAME,
                assets_dir=export_root / DEFAULT_EXPORT_ASSETS_DIRNAME,
            )
        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def _write_export(
        self,
        project: AudioProject,
        export_root: Path,
        issues: list[ValidationIssue],
        copy_assets: bool,
    ) -> ExportResult:
        export_root.mkdir(parents=True, exist_ok=True)

        data_file = export_root / DEFAULT_RUNTIME_DATA_FILENAME
        enum_file = export_root / DEFAULT_EVENT_ENUM_FILENAME
        manifest_file = export_root / DEFAULT_AUDIO_MANIFEST_FILENAME
        report_file = export_root / DEFAULT_BUILD_REPORT_FILENAME
        assets_dir = export_root / DEFAULT_EXPORT_ASSETS_DIRNAME

        asset_entries = self._collect_asset_entries(project)
        if copy_assets:
            self._copy_assets(asset_entries, assets_dir)

        data_file.write_text(
            json.dumps(self._build_runtime_payload(project), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        enum_file.write_text(self._build_event_enum(project), encoding="utf-8")
        manifest_file.write_text(
            json.dumps(self._build_manifest_payload(asset_entries), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report_file.write_text(
            json.dumps(
                self._build_report_payload(project, issues, [data_file, enum_file, manifest_file, report_file], assets_dir),
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
                    "RuntimeFormat": project.settings.runtime_audio_format.lower(),
                    "TrimStartMs": clip.trim_start_ms,
                    "TrimEndMs": clip.trim_end_ms,
                    "FadeInMs": clip.fade_in_ms,
                    "FadeOutMs": clip.fade_out_ms,
                    "LoopStartMs": clip.loop_start_ms,
                    "LoopEndMs": clip.loop_end_ms,
                    "FileSize": file_size,
                    "Hash": file_hash,
                    "ReferencedByEvents": sorted(owners[asset_key]),
                    "Clip": clip,
                    "ProjectSettings": project.settings,
                }
            )
        return entries

    def _copy_assets(self, asset_entries: list[dict[str, object]], assets_dir: Path) -> None:
        assets_dir.mkdir(parents=True, exist_ok=True)
        for entry in asset_entries:
            source_path = entry["SourcePath"]
            if not source_path:
                continue
            source = Path(source_path)
            if not source.exists():
                continue
            target = assets_dir / str(entry["ExportPath"])
            clip = entry["Clip"]
            project_settings = entry["ProjectSettings"]
            self.audio_processor.export_clip(clip, project_settings, target)

    def _resolve_asset_export_path(self, clip, runtime_audio_format: str) -> str:
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