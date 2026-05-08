from __future__ import annotations

import shutil
from pathlib import Path

try:
    import numpy as np
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    sf = None

from audioforge.app.models.audio_project import ClipModel, ProjectSettings


class AudioProcessor:
    def can_process(self) -> bool:
        return sf is not None

    def export_clip(self, clip: ClipModel, project_settings: ProjectSettings, destination_path: Path) -> None:
        source_path = Path(clip.source_path)
        if not source_path.exists():
            raise FileNotFoundError(clip.source_path)

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        target_format = project_settings.runtime_audio_format.lower()
        if self._can_passthrough_copy(clip, source_path, destination_path, target_format):
            if not self._paths_match(source_path, destination_path):
                shutil.copy2(source_path, destination_path)
            return

        if sf is None:
            raise RuntimeError("soundfile is not available; audio conversion cannot run.")

        audio_data, sample_rate = sf.read(str(source_path), always_2d=False, dtype="float32")
        total_frames = len(audio_data)

        start_frame = self._ms_to_frame(clip.trim_start_ms, sample_rate)
        end_frame = self._resolve_end_frame(clip.trim_end_ms, sample_rate, total_frames)
        trimmed_audio = audio_data[start_frame:end_frame]
        trimmed_audio = self._apply_fades(trimmed_audio, sample_rate, clip.fade_in_ms, clip.fade_out_ms)

        if target_format == "ogg":
            sf.write(str(destination_path), trimmed_audio, sample_rate, format="OGG", subtype="VORBIS")
            return
        if target_format == "wav":
            sf.write(str(destination_path), trimmed_audio, sample_rate, format="WAV")
            return
        raise ValueError(f"Unsupported runtime audio format: {project_settings.runtime_audio_format}")

    def _can_passthrough_copy(
        self,
        clip: ClipModel,
        source_path: Path,
        destination_path: Path,
        target_format: str,
    ) -> bool:
        return (
            source_path.suffix.lstrip(".").lower() == target_format
            and clip.trim_start_ms <= 0
            and clip.trim_end_ms <= 0
            and clip.fade_in_ms <= 0
            and clip.fade_out_ms <= 0
            and not self._paths_match(source_path, destination_path)
        )

    def _paths_match(self, first: Path, second: Path) -> bool:
        try:
            return first.resolve() == second.resolve()
        except OSError:
            return first == second

    def _ms_to_frame(self, value_ms: int, sample_rate: int) -> int:
        if value_ms <= 0:
            return 0
        return max(0, int(sample_rate * (value_ms / 1000.0)))

    def _resolve_end_frame(self, end_ms: int, sample_rate: int, total_frames: int) -> int:
        if end_ms <= 0:
            return total_frames
        return min(total_frames, int(sample_rate * (end_ms / 1000.0)))

    def _apply_fades(self, audio_data, sample_rate: int, fade_in_ms: int, fade_out_ms: int):
        if np is None or fade_in_ms <= 0 and fade_out_ms <= 0:
            return audio_data
        total_frames = len(audio_data)
        if total_frames <= 0:
            return audio_data
        envelope = np.ones(total_frames, dtype=np.float32)
        fade_in_frames = min(total_frames, max(0, int(sample_rate * (fade_in_ms / 1000.0))))
        fade_out_frames = min(total_frames, max(0, int(sample_rate * (fade_out_ms / 1000.0))))
        if fade_in_frames > 0:
            envelope[:fade_in_frames] = np.linspace(0.0, 1.0, fade_in_frames, dtype=np.float32)
        if fade_out_frames > 0:
            envelope[-fade_out_frames:] = np.minimum(
                envelope[-fade_out_frames:],
                np.linspace(1.0, 0.0, fade_out_frames, dtype=np.float32),
            )
        if getattr(audio_data, "ndim", 1) > 1:
            return audio_data * envelope[:, np.newaxis]
        return audio_data * envelope