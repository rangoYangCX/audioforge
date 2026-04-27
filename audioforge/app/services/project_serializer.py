from __future__ import annotations

import json
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, project_from_dict


class ProjectSerializer:
    def save(self, project: AudioProject, file_path: Path) -> None:
        project.file_path = str(file_path)
        project.touch()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(project.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, file_path: Path) -> AudioProject:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        return project_from_dict(payload, file_path=str(file_path))