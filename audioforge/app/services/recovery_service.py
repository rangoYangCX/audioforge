from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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

    def load_snapshot(self) -> RecoverySnapshot:
        payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        project_payload = payload.get("Project", {})
        project = project_from_dict(project_payload, file_path=payload.get("OriginalProjectPath"))
        return RecoverySnapshot(
            project=project,
            saved_at=str(payload.get("SavedAt", "")),
            original_project_path=payload.get("OriginalProjectPath"),
        )

    def clear_snapshot(self) -> None:
        if self.snapshot_path.exists():
            self.snapshot_path.unlink()
