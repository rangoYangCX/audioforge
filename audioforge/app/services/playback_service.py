from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

try:
    import numpy as np
    import pygame
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    pygame = None

from audioforge.app.services.preview_audio_renderer import PreviewAudioRenderer


PREVIEW_PLAYBACK_SAMPLE_RATE = 48000


@dataclass(slots=True)
class ActivePreviewVoice:
    event_id: str
    started_at: float
    bus_name: str
    base_volume_db: float
    channel: object


class PlaybackService:
    def __init__(self) -> None:
        self._initialized = False
        self._renderer = PreviewAudioRenderer()
        self._active_voices: dict[str, list[ActivePreviewVoice]] = {}

    def is_available(self) -> bool:
        return pygame is not None and np is not None and self._renderer.is_available()

    def play_file(
        self,
        file_path: str,
        volume_db: float,
        *,
        tracked_base_volume_db: float | None = None,
        bus_name: str = "SFX",
        pitch_cents: int = 0,
        preserve_timing_pitch_cents: int = 0,
        trim_start_ms: int = 0,
        event_id: str | None = None,
        trim_end_ms: int = 0,
    ) -> str:
        if not self.is_available():
            return "pygame、numpy、scipy 或 soundfile 不可用；真实试听不可用。"

        try:
            rendered = self._renderer.render_file(
                file_path,
                trim_start_ms=trim_start_ms,
                trim_end_ms=trim_end_ms,
                pitch_cents=pitch_cents,
                preserve_timing_pitch_cents=preserve_timing_pitch_cents,
                target_sample_rate=PREVIEW_PLAYBACK_SAMPLE_RATE,
            )
        except FileNotFoundError:
            return f"Preview source file not found: {file_path}"
        except Exception as exc:
            return f"Preview render failed: {exc}"

        if rendered.audio_data.size == 0:
            return "Preview render produced empty audio."

        self._ensure_initialized(rendered.sample_rate)
        sound = pygame.sndarray.make_sound((rendered.audio_data * 32767.0).astype(np.int16, copy=False))
        sound.set_volume(self._db_to_linear(volume_db))
        channel = sound.play()
        self._cleanup_finished_voices()
        if event_id and channel is not None:
            self._active_voices.setdefault(event_id, []).append(
                ActivePreviewVoice(
                    event_id=event_id,
                    started_at=time.monotonic(),
                    bus_name=bus_name,
                    base_volume_db=volume_db if tracked_base_volume_db is None else tracked_base_volume_db,
                    channel=channel,
                )
            )
        total_pitch_cents = pitch_cents + preserve_timing_pitch_cents
        return f"本地试听成功（音量 {volume_db:.2f} dB，音高 {total_pitch_cents} cents，裁剪 {trim_start_ms}-{trim_end_ms} ms）"

    def refresh_bus_volumes(self, effective_volume_db_resolver: Callable[[str, float], float]) -> None:
        self._cleanup_finished_voices()
        for voices in self._active_voices.values():
            for voice in voices:
                try:
                    voice.channel.set_volume(self._db_to_linear(effective_volume_db_resolver(voice.bus_name, voice.base_volume_db)))
                except Exception:
                    continue


    def stop_oldest(self, event_id: str) -> None:
        self._cleanup_finished_voices()
        voices = self._active_voices.get(event_id)
        if not voices:
            return
        voices.sort(key=lambda voice: voice.started_at)
        oldest = voices.pop(0)
        try:
            oldest.channel.stop()
        except Exception:
            pass
        if not voices:
            self._active_voices.pop(event_id, None)

    def stop_event(self, event_id: str) -> None:
        self._cleanup_finished_voices()
        voices = self._active_voices.pop(event_id, [])
        for voice in voices:
            try:
                voice.channel.stop()
            except Exception:
                continue

    def stop_bus(self, bus_name: str) -> None:
        self.stop_buses({bus_name})

    def stop_buses(self, bus_names: set[str]) -> None:
        self._cleanup_finished_voices()
        normalized_buses = {str(bus_name).strip() for bus_name in bus_names if str(bus_name).strip()}
        if not normalized_buses:
            return
        for event_id, voices in list(self._active_voices.items()):
            remaining: list[ActivePreviewVoice] = []
            for voice in voices:
                if voice.bus_name not in normalized_buses:
                    remaining.append(voice)
                    continue
                try:
                    voice.channel.stop()
                except Exception:
                    pass
            if remaining:
                self._active_voices[event_id] = remaining
            else:
                self._active_voices.pop(event_id, None)

    def _ensure_initialized(self, sample_rate: int) -> None:
        if self._initialized:
            return
        pygame.mixer.init(frequency=sample_rate, size=-16, channels=2)
        self._initialized = True

    def _cleanup_finished_voices(self) -> None:
        for event_id, voices in list(self._active_voices.items()):
            alive: list[ActivePreviewVoice] = []
            for voice in voices:
                try:
                    busy = bool(voice.channel.get_busy())
                except Exception:
                    busy = False
                if busy:
                    alive.append(voice)
            if alive:
                self._active_voices[event_id] = alive
            else:
                self._active_voices.pop(event_id, None)

    def _db_to_linear(self, value_db: float) -> float:
        if value_db <= -96.0:
            return 0.0
        return max(0.0, math.pow(10.0, value_db / 20.0))