from __future__ import annotations

from pathlib import Path

try:
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    sf = None

from audioforge.app.models.audio_project import ClipModel, ProjectSettings


class AudioProcessor:
    def can_process(self) -> bool:
        return sf is not None

    def export_clip(self, clip: ClipModel, project_settings: ProjectSettings, destination_path: Path) -> None:
        source_path = Path(clip.source_path)
        if not source_path.exists():
            raise FileNotFoundError(clip.source_path)
        if sf is None:
            raise RuntimeError("soundfile is not available; audio conversion cannot run.")

        audio_data, sample_rate = sf.read(str(source_path), always_2d=False)
        total_frames = len(audio_data)

        start_frame = self._ms_to_frame(clip.trim_start_ms, sample_rate)
        end_frame = self._resolve_end_frame(clip.trim_end_ms, sample_rate, total_frames)
        trimmed_audio = audio_data[start_frame:end_frame]

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target_format = project_settings.runtime_audio_format.lower()
        if target_format == "ogg":
            sf.write(str(destination_path), trimmed_audio, sample_rate, format="OGG", subtype="VORBIS")
            return
        if target_format == "wav":
            sf.write(str(destination_path), trimmed_audio, sample_rate, format="WAV")
            return
        raise ValueError(f"Unsupported runtime audio format: {project_settings.runtime_audio_format}")

    def _ms_to_frame(self, value_ms: int, sample_rate: int) -> int:
        if value_ms <= 0:
            return 0
        return max(0, int(sample_rate * (value_ms / 1000.0)))

    def _resolve_end_frame(self, end_ms: int, sample_rate: int, total_frames: int) -> int:
        if end_ms <= 0:
            return total_frames
        return min(total_frames, int(sample_rate * (end_ms / 1000.0)))