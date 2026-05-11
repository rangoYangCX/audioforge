from __future__ import annotations

from audioforge.app.services.preview_service import PreviewService

from tests.helpers import build_sample_project


def test_preview_service_rejects_missing_clip_source_file(tmp_path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    event = project.events["UiClick"]
    wav_path.unlink()

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is False
    assert "not found" in result.reason
    assert str(wav_path) in result.reason