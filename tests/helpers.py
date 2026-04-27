from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, BusConfig, ClipModel, EventModel, MASTER_BUS_NAME, ProjectSettings


def write_wav_fixture(path: Path, *, frequency_hz: float = 440.0, duration_seconds: float = 0.1, sample_rate: int = 22050) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(duration_seconds * sample_rate))
    amplitude = 0.35
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        for frame_index in range(frame_count):
            sample = amplitude * math.sin((2.0 * math.pi * frequency_hz * frame_index) / sample_rate)
            stream.writeframes(struct.pack("<h", int(sample * 32767)))
    return path


def build_sample_project(
    root_dir: Path,
    *,
    bus_volume_db: float = 0.0,
    event_volume_db: float = 0.0,
    runtime_audio_format: str = "wav",
) -> tuple[AudioProject, Path]:
    wav_path = write_wav_fixture(root_dir / "fixtures" / "ui_click.wav")

    project = AudioProject.create_empty(name="InternalReleaseSample")
    project.settings = ProjectSettings(
        default_bus="UI",
        export_root=str(root_dir / "Export"),
        buses=["BGM", "SFX", "UI"],
        bus_configs=[
            BusConfig(name=MASTER_BUS_NAME),
            BusConfig(name="BGM"),
            BusConfig(name="SFX"),
            BusConfig(name="UI", parent_bus="SFX", volume_db=bus_volume_db),
        ],
        source_audio_format="wav",
        runtime_audio_format=runtime_audio_format,
    )
    root_folder_id = project.root_folder_ids[0]
    clip = ClipModel.from_path(wav_path, "ui/click_primary")
    event = EventModel(
        id="UiClick",
        display_name="UI Click",
        bus="UI",
        volume_db=event_volume_db,
        clips=[clip],
    )
    project.add_event(root_folder_id, event)
    return project, wav_path