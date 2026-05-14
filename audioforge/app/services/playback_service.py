from __future__ import annotations

import math
import sys
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
    is_paused: bool = False


class PlaybackService:
    def __init__(self) -> None:
        self._initialized = False
        self._initialized_frequency: int | None = None
        self._initialization_error = ""
        self._renderer = PreviewAudioRenderer()
        self._active_voices: dict[str, list[ActivePreviewVoice]] = {}

    def is_available(self) -> bool:
        return pygame is not None and np is not None and self._renderer.is_available()

    def availability_reason(self) -> str:
        if pygame is None or np is None:
            return "pygame 或 numpy 不可用。"
        if not self._renderer.is_available():
            return "scipy 或 soundfile 不可用。"
        if self._initialization_error:
            return self._initialization_error
        return ""

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
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
    ) -> str:
        if not self.is_available():
            reason = self.availability_reason() or "pygame、numpy、scipy 或 soundfile 不可用；真实试听不可用。"
            return f"真实试听不可用：{reason}"

        try:
            rendered = self._renderer.render_file(
                file_path,
                trim_start_ms=trim_start_ms,
                trim_end_ms=trim_end_ms,
                fade_in_ms=fade_in_ms,
                fade_out_ms=fade_out_ms,
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

        try:
            self._ensure_initialized(rendered.sample_rate)
        except Exception as exc:
            self._initialization_error = str(exc)
            return f"真实试听不可用：{exc}"

        sample_buffer = np.ascontiguousarray((rendered.audio_data * 32767.0).astype(np.int16, copy=False))
        sound = pygame.sndarray.make_sound(sample_buffer)
        sound.set_volume(self._db_to_linear(volume_db))
        channel = sound.play()
        if channel is None:
            return "真实试听失败：未分配到可用播放通道。"
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
        return f"本地试听成功（音量 {volume_db:.2f} dB，音高 {total_pitch_cents} cents，裁剪 {trim_start_ms}-{trim_end_ms} ms，淡入 {fade_in_ms} ms，淡出 {fade_out_ms} ms）"

    def refresh_bus_volumes(self, effective_volume_db_resolver: Callable[[str, float], float]) -> None:
        self._cleanup_finished_voices()
        for voices in self._active_voices.values():
            for voice in voices:
                try:
                    voice.channel.set_volume(self._db_to_linear(effective_volume_db_resolver(voice.bus_name, voice.base_volume_db)))
                except Exception:
                    continue

    def pause_event(self, event_id: str) -> bool:
        self._cleanup_finished_voices()
        voices = self._active_voices.get(event_id)
        if not voices:
            return False
        paused_any = False
        for voice in voices:
            if voice.is_paused:
                continue
            try:
                voice.channel.pause()
                voice.is_paused = True
                paused_any = True
            except Exception:
                continue
        return paused_any

    def resume_event(self, event_id: str) -> bool:
        self._cleanup_finished_voices()
        voices = self._active_voices.get(event_id)
        if not voices:
            return False
        resumed_any = False
        for voice in voices:
            if not voice.is_paused:
                continue
            try:
                voice.channel.unpause()
                voice.is_paused = False
                resumed_any = True
            except Exception:
                continue
        return resumed_any

    def has_active_event(self, event_id: str) -> bool:
        self._cleanup_finished_voices()
        return bool(self._active_voices.get(event_id))

    def is_event_paused(self, event_id: str) -> bool:
        self._cleanup_finished_voices()
        voices = self._active_voices.get(event_id)
        return bool(voices) and any(voice.is_paused for voice in voices)


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
        if self._initialized and self._initialized_frequency == sample_rate:
            return

        if self._initialized:
            try:
                pygame.mixer.quit()
            except Exception:
                pass
            self._initialized = False
            self._initialized_frequency = None

        attempts = [
            {"frequency": sample_rate, "size": -16, "channels": 2, "buffer": 512},
            {"frequency": sample_rate, "size": -16, "channels": 2, "buffer": 1024},
        ]
        if sample_rate != 44100:
            attempts.append({"frequency": 44100, "size": -16, "channels": 2, "buffer": 1024})
        if sys.platform == "darwin":
            attempts.append({"frequency": 48000, "size": -16, "channels": 2, "buffer": 2048})

        errors: list[str] = []
        for options in attempts:
            try:
                pygame.mixer.init(**options)
                self._initialized = True
                self._initialized_frequency = int(options["frequency"])
                self._initialization_error = ""
                return
            except Exception as exc:
                errors.append(
                    f"freq={options['frequency']} buffer={options['buffer']} failed: {exc}"
                )

        raise RuntimeError("pygame mixer 初始化失败；" + " | ".join(errors))

    def _cleanup_finished_voices(self) -> None:
        for event_id, voices in list(self._active_voices.items()):
            alive: list[ActivePreviewVoice] = []
            for voice in voices:
                if voice.is_paused:
                    alive.append(voice)
                    continue
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