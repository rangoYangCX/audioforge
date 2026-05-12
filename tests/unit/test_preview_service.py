from __future__ import annotations

from audioforge.app.models.audio_project import ClipModel, EventModel
from audioforge.app.services.preview_service import PreviewService

from tests.helpers import build_sample_project, write_wav_fixture


def test_preview_service_rejects_missing_clip_source_file(tmp_path) -> None:
    project, wav_path = build_sample_project(tmp_path)
    event = project.events["UiClick"]
    wav_path.unlink()

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is False
    assert "not found" in result.reason
    assert str(wav_path) in result.reason


def test_preview_service_uses_active_binding_for_one_shot(tmp_path) -> None:
    primary_path = write_wav_fixture(tmp_path / "fixtures" / "primary.wav", frequency_hz=440.0)
    alternate_path = write_wav_fixture(tmp_path / "fixtures" / "alternate.wav", frequency_hz=660.0)
    event = EventModel(
        id="UiClick",
        display_name="UI Click",
        bus="UI",
        play_mode="OneShot",
        clips=[
            ClipModel.from_path(primary_path, "ui/click_primary"),
            ClipModel.from_path(alternate_path, "ui/click_alternate"),
        ],
    )
    event.clips[0].active = False
    event.clips[1].active = True

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is True
    assert result.clip_id == event.clips[1].id
    assert result.asset_key == "ui/click_alternate"


def test_preview_service_ignores_inactive_bindings_for_random_mode(tmp_path) -> None:
    primary_path = write_wav_fixture(tmp_path / "fixtures" / "random_primary.wav", frequency_hz=440.0)
    alternate_path = write_wav_fixture(tmp_path / "fixtures" / "random_alternate.wav", frequency_hz=660.0)
    event = EventModel(
        id="UiRandom",
        display_name="UI Random",
        bus="UI",
        play_mode="Random",
        clips=[
            ClipModel.from_path(primary_path, "ui/random_primary"),
            ClipModel.from_path(alternate_path, "ui/random_alternate"),
        ],
    )
    event.clips[0].active = True
    event.clips[1].active = False

    result = PreviewService(seed=7).preview_event(event)

    assert result.accepted is True
    assert result.clip_id == event.clips[0].id
    assert result.asset_key == "ui/random_primary"