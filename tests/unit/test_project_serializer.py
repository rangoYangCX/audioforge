from __future__ import annotations

from pathlib import Path

import pytest

from audioforge.app.services.project_serializer import ProjectSerializer

from tests.helpers import build_sample_project


def test_project_serializer_roundtrip_preserves_bus_routes_and_clips(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path, bus_volume_db=2.5, event_volume_db=-1.0)
    project.settings.auto_assign_bus_by_name = False
    serializer = ProjectSerializer()
    project_path = tmp_path / "sample.afproj"

    serializer.save(project, project_path)
    loaded = serializer.load(project_path)

    assert loaded.file_path == str(project_path)
    assert loaded.events["UiClick"].clips[0].source_path == str(wav_path)
    assert loaded.events["UiClick"].clips[0].asset_key == "ui/click_primary"
    assert loaded.settings.default_bus == "UI"
    assert loaded.settings.auto_assign_bus_by_name is False
    assert loaded.settings.bus_configs[-1].name == "UI"
    assert loaded.settings.bus_configs[-1].parent_bus == "SFX"
    assert loaded.settings.bus_configs[-1].volume_db == 2.5
    assert str(wav_path) in loaded.asset_registry


def test_project_serializer_preserves_existing_file_when_atomic_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _ = build_sample_project(tmp_path)
    serializer = ProjectSerializer()
    project_path = tmp_path / "sample.afproj"
    temp_path = project_path.with_suffix(".tmp")

    serializer.save(project, project_path)
    original_payload = project_path.read_text(encoding="utf-8")
    project.name = "Changed Project"

    original_replace = Path.replace

    def failing_replace(self: Path, target: Path) -> Path:
        if self == temp_path and target == project_path:
            raise OSError("disk full")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        serializer.save(project, project_path)

    assert project_path.read_text(encoding="utf-8") == original_payload
    assert temp_path.exists() is False