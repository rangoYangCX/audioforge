from __future__ import annotations

import copy
import json
import os
import re
import shutil
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, project_from_dict


PROJECT_SOURCES_DIRNAME = "Sources"


class ProjectSerializer:
    def save(self, project: AudioProject, file_path: Path) -> None:
        file_path = file_path.resolve()
        staged_project = copy.deepcopy(project)
        self._internalize_project_sources(staged_project, file_path)
        staged_project.file_path = str(file_path)
        staged_project.touch()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.with_suffix(".tmp")
        payload = json.dumps(staged_project.to_dict(), ensure_ascii=False, indent=2)
        try:
            temp_path.write_text(payload, encoding="utf-8")
            temp_path.replace(file_path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        self._copy_project_state(project, staged_project)
        project.file_path = str(file_path)
        self._resolve_loaded_project_sources(project, file_path)

    def load(self, file_path: Path) -> AudioProject:
        file_path = file_path.resolve()
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        project = project_from_dict(payload, file_path=str(file_path))
        self._resolve_loaded_project_sources(project, file_path)
        return project

    def _internalize_project_sources(self, project: AudioProject, file_path: Path) -> None:
        source_root = self._project_root_dir(file_path) / PROJECT_SOURCES_DIRNAME
        path_map: dict[str, str] = {}
        for source_path in self._collect_project_source_paths(project):
            normalized = str(source_path).strip()
            if not normalized:
                continue
            target_path = self._stage_source_file(normalized, file_path, source_root)
            path_map[normalized] = self._serialize_source_path(target_path, file_path.parent)
        self._apply_source_path_map(project, path_map)

    def _resolve_loaded_project_sources(self, project: AudioProject, file_path: Path) -> None:
        project_dir = file_path.parent
        asset_registry: dict[str, object] = {}
        for entry in project.asset_registry.values():
            resolved_path = self._resolve_source_path(entry.source_path, project_dir)
            entry.source_path = resolved_path
            asset_registry[resolved_path] = entry
        project.asset_registry = asset_registry

        for audio in project.audio_objects.values():
            for clip in audio.clips:
                clip.source_path = self._resolve_source_path(clip.source_path, project_dir)
        project.sync_asset_registry()

    def _copy_project_state(self, target: AudioProject, source: AudioProject) -> None:
        target.name = source.name
        target.project_version = source.project_version
        target.created_at = source.created_at
        target.updated_at = source.updated_at
        target.settings = copy.deepcopy(source.settings)
        target.root_folder_ids = list(source.root_folder_ids)
        target.folders = copy.deepcopy(source.folders)
        target.events = copy.deepcopy(source.events)
        target.audio_objects = copy.deepcopy(source.audio_objects)
        for event in target.events.values():
            linked_audio = target.audio_objects.get(event.audio_id)
            if linked_audio is not None:
                event.audio = linked_audio
        target.game_parameters = copy.deepcopy(source.game_parameters)
        target.state_groups = copy.deepcopy(source.state_groups)
        target.switch_groups = copy.deepcopy(source.switch_groups)
        target.asset_registry = copy.deepcopy(source.asset_registry)

    def _collect_project_source_paths(self, project: AudioProject) -> list[str]:
        collected: list[str] = []
        seen: set[str] = set()

        def add_path(raw_path: str) -> None:
            normalized = str(raw_path).strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            collected.append(normalized)

        for entry in project.asset_registry.values():
            add_path(entry.source_path)
        for audio in project.audio_objects.values():
            for clip in audio.clips:
                add_path(clip.source_path)
        return collected

    def _stage_source_file(self, source_path: str, file_path: Path, source_root: Path) -> Path:
        candidate = Path(source_path)
        if not candidate.is_absolute():
            candidate = (file_path.parent / candidate).resolve(strict=False)
        else:
            candidate = candidate.resolve(strict=False)

        project_root = self._project_root_dir(file_path)
        if self._is_relative_to(candidate, project_root):
            return candidate
        if not candidate.exists():
            return candidate

        relative_target = self._managed_relative_source_path(candidate)
        target_path = source_root / relative_target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if candidate != target_path:
            shutil.copy2(candidate, target_path)
        return target_path

    def _apply_source_path_map(self, project: AudioProject, path_map: dict[str, str]) -> None:
        if not path_map:
            return

        for audio in project.audio_objects.values():
            for clip in audio.clips:
                normalized = str(clip.source_path).strip()
                if normalized in path_map:
                    clip.source_path = path_map[normalized]

        rebuilt_registry: dict[str, object] = {}
        for source_path, entry in project.asset_registry.items():
            normalized = str(source_path).strip()
            rebuilt_path = path_map.get(normalized, path_map.get(str(entry.source_path).strip(), normalized))
            entry.source_path = rebuilt_path
            rebuilt_registry[rebuilt_path] = entry
        project.asset_registry = rebuilt_registry

    def _serialize_source_path(self, source_path: Path, base_dir: Path) -> str:
        if source_path.is_absolute() and self._is_relative_to(source_path, base_dir):
            return os.path.relpath(source_path, base_dir)
        return str(source_path)

    def _resolve_source_path(self, source_path: str, base_dir: Path) -> str:
        candidate = Path(str(source_path).strip())
        if not str(candidate):
            return ""
        if candidate.is_absolute():
            return str(candidate)
        return str((base_dir / candidate).resolve(strict=False))

    def _managed_relative_source_path(self, source_path: Path) -> Path:
        anchor = self._sanitize_path_segment(source_path.anchor.rstrip("\\/") or "root")
        tail_parts = [self._sanitize_path_segment(part) for part in source_path.parts[1:]]
        if not tail_parts:
            tail_parts = [self._sanitize_path_segment(source_path.name or "source")]
        return Path(anchor, *tail_parts)

    def _sanitize_path_segment(self, value: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
        return sanitized.strip("._") or "root"

    def _project_root_dir(self, file_path: Path) -> Path:
        return file_path.with_suffix("")

    def _is_relative_to(self, path: Path, base_dir: Path) -> bool:
        try:
            path.relative_to(base_dir)
            return True
        except ValueError:
            return False