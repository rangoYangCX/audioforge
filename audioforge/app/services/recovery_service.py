from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from audioforge.app.models.audio_project import AudioProject, project_from_dict


@dataclass(slots=True)
class RecoverySnapshot:
    project: AudioProject
    saved_at: str
    original_project_path: str | None


class RecoveryService:
    def __init__(self, recovery_root: Path | None = None) -> None:
        if recovery_root is None:
            local_app_data = os.getenv("LOCALAPPDATA")
            base_root = Path(local_app_data) if local_app_data else Path.home() / ".audioforge"
            recovery_root = base_root / "AudioForge" / "Recovery"
        self.recovery_root = Path(recovery_root)

    @property
    def snapshot_path(self) -> Path:
        return self.recovery_root / "autosave_recovery.json"

    @property
    def history_dir(self) -> Path:
        return self.recovery_root / "history"

    def has_snapshot(self) -> bool:
        return self.snapshot_path.exists()

    def save_snapshot(self, project: AudioProject) -> Path:
        self.recovery_root.mkdir(parents=True, exist_ok=True)
        payload = {
            "SavedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "OriginalProjectPath": project.file_path,
            "Project": project.to_dict(),
        }
        temp_path = self.snapshot_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.snapshot_path)
        return self.snapshot_path

    def save_history_snapshot(self, project: AudioProject, *, max_entries: int = 10) -> Path:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        saved_at = datetime.now(UTC)
        payload = {
            "SavedAt": saved_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "OriginalProjectPath": project.file_path,
            "Project": project.to_dict(),
        }
        snapshot_path = self.history_dir / f"autosave_{saved_at.strftime('%Y%m%d_%H%M%S_%f')}.json"
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshots = self.list_history_snapshots()
        for stale_path in snapshots[max_entries:]:
            stale_path.unlink(missing_ok=True)
        return snapshot_path

    def load_snapshot(self, snapshot_path: Path | None = None) -> RecoverySnapshot:
        target_path = snapshot_path or self.snapshot_path
        payload = json.loads(target_path.read_text(encoding="utf-8"))
        project_payload = payload.get("Project", {})
        project = project_from_dict(project_payload, file_path=payload.get("OriginalProjectPath"))
        return RecoverySnapshot(
            project=project,
            saved_at=str(payload.get("SavedAt", "")),
            original_project_path=payload.get("OriginalProjectPath"),
        )

    def list_history_snapshots(self) -> list[Path]:
        if not self.history_dir.exists():
            return []
        return sorted(self.history_dir.glob("autosave_*.json"), reverse=True)

    def clear_snapshot(self) -> None:
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
