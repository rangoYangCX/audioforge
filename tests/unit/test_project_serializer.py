from __future__ import annotations

from pathlib import Path

from audioforge.app.services.project_serializer import ProjectSerializer

from tests.helpers import build_sample_project


def test_project_serializer_roundtrip_preserves_bus_routes_and_clips(tmp_path: Path) -> None:
    project, wav_path = build_sample_project(tmp_path, bus_volume_db=2.5, event_volume_db=-1.0)
    serializer = ProjectSerializer()
    project_path = tmp_path / "sample.afproj"

    serializer.save(project, project_path)
    loaded = serializer.load(project_path)

    assert loaded.file_path == str(project_path)
    assert loaded.events["UiClick"].clips[0].source_path == str(wav_path)
    assert loaded.events["UiClick"].clips[0].asset_key == "ui/click_primary"
    assert loaded.settings.default_bus == "UI"
    assert loaded.settings.bus_configs[-1].name == "UI"
    assert loaded.settings.bus_configs[-1].parent_bus == "SFX"
    assert loaded.settings.bus_configs[-1].volume_db == 2.5
    assert str(wav_path) in loaded.asset_registry