from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

try:
    import numpy as np
    from scipy.signal import istft, resample_poly, stft
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    istft = None
    resample_poly = None
    sf = None
    stft = None


@dataclass(slots=True)
class RenderedPreviewAudio:
    audio_data: object
    sample_rate: int


class PreviewAudioRenderer:
    def is_available(self) -> bool:
        return np is not None and resample_poly is not None and sf is not None and stft is not None and istft is not None

    def render_file(
        self,
        file_path: str,
        *,
        trim_start_ms: int = 0,
        trim_end_ms: int = 0,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
        pitch_cents: int = 0,
        preserve_timing_pitch_cents: int = 0,
        target_sample_rate: int | None = None,
    ) -> RenderedPreviewAudio:
        if not self.is_available():
            raise RuntimeError("numpy、scipy 或 soundfile 不可用，无法生成试听音频。")

        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(file_path)

        audio_data, sample_rate = sf.read(str(source), always_2d=True)
        if audio_data.size == 0:
            raise RuntimeError("音频文件为空。")

        processed = self._normalize_channels(audio_data.astype(np.float32, copy=False))
        processed = self._apply_trim(processed, sample_rate, trim_start_ms, trim_end_ms)
        processed = self._apply_fades(processed, sample_rate, fade_in_ms, fade_out_ms)
        processed = self._apply_pitch(processed, pitch_cents)
        processed = self._apply_pitch_preserve_duration(processed, preserve_timing_pitch_cents)
        output_sample_rate = sample_rate

        if target_sample_rate is not None and target_sample_rate > 0 and target_sample_rate != sample_rate:
            processed = self._resample(processed, sample_rate, target_sample_rate)
            output_sample_rate = target_sample_rate

        processed = np.clip(processed, -1.0, 1.0).astype(np.float32, copy=False)
        return RenderedPreviewAudio(audio_data=processed, sample_rate=output_sample_rate)

    def estimate_duration_seconds(
        self,
        file_path: str,
        *,
        trim_start_ms: int = 0,
        trim_end_ms: int = 0,
        pitch_cents: int = 0,
        preserve_timing_pitch_cents: int = 0,
    ) -> float | None:
        if sf is None:
            return None
        source = Path(file_path)
        if not source.exists():
            return None
        try:
            info = sf.info(str(source))
        except Exception:
            return None
        if info.samplerate <= 0:
            return None
        total_duration = info.frames / info.samplerate
        start_seconds = max(0.0, trim_start_ms / 1000.0)
        end_seconds = total_duration if trim_end_ms <= 0 else min(total_duration, trim_end_ms / 1000.0)
        trimmed_duration = max(0.0, end_seconds - start_seconds)
        if trimmed_duration <= 0.0:
            return 0.0
        pitch_ratio = float(2.0 ** (pitch_cents / 1200.0))
        if pitch_ratio <= 0.0:
            return trimmed_duration
        return trimmed_duration / pitch_ratio

    def _normalize_channels(self, audio_data):
        if audio_data.shape[1] == 1:
            return np.repeat(audio_data, 2, axis=1)
        if audio_data.shape[1] > 2:
            return audio_data[:, :2]
        return audio_data

    def _apply_trim(self, audio_data, sample_rate: int, trim_start_ms: int, trim_end_ms: int):
        start_frame = max(0, int(sample_rate * (max(0, trim_start_ms) / 1000.0)))
        end_frame = audio_data.shape[0] if trim_end_ms <= 0 else min(audio_data.shape[0], int(sample_rate * (trim_end_ms / 1000.0)))
        if start_frame >= end_frame:
            return audio_data[0:0]
        return audio_data[start_frame:end_frame]

    def _apply_fades(self, audio_data, sample_rate: int, fade_in_ms: int, fade_out_ms: int):
        if audio_data.size == 0:
            return audio_data
        total_frames = audio_data.shape[0]
        fade_in_frames = min(total_frames, max(0, int(sample_rate * (fade_in_ms / 1000.0))))
        fade_out_frames = min(total_frames, max(0, int(sample_rate * (fade_out_ms / 1000.0))))
        if fade_in_frames <= 0 and fade_out_frames <= 0:
            return audio_data
        envelope = np.ones(total_frames, dtype=np.float32)
        if fade_in_frames > 0:
            envelope[:fade_in_frames] = np.linspace(0.0, 1.0, fade_in_frames, dtype=np.float32)
        if fade_out_frames > 0:
            envelope[-fade_out_frames:] = np.minimum(
                envelope[-fade_out_frames:],
                np.linspace(1.0, 0.0, fade_out_frames, dtype=np.float32),
            )
        return audio_data * envelope[:, np.newaxis]

    def _apply_pitch(self, audio_data, pitch_cents: int):
        if pitch_cents == 0 or audio_data.size == 0:
            return audio_data
        pitch_ratio = float(2.0 ** (pitch_cents / 1200.0))
        ratio_fraction = Fraction(1.0 / pitch_ratio).limit_denominator(1000)
        return resample_poly(audio_data, ratio_fraction.numerator, ratio_fraction.denominator, axis=0)

    def _apply_pitch_preserve_duration(self, audio_data, pitch_cents: int):
        if pitch_cents == 0 or audio_data.size == 0:
            return audio_data
        pitch_ratio = float(2.0 ** (pitch_cents / 1200.0))
        if pitch_ratio <= 0.0:
            return audio_data
        shifted = self._apply_pitch(audio_data, pitch_cents)
        restored = self._time_stretch(shifted, 1.0 / pitch_ratio, target_length=audio_data.shape[0])
        return restored.astype(np.float32, copy=False)

    def _time_stretch(self, audio_data, rate: float, *, target_length: int):
        if audio_data.size == 0 or rate <= 0.0:
            return audio_data
        channels: list[object] = []
        for channel_index in range(audio_data.shape[1]):
            channels.append(self._time_stretch_channel(audio_data[:, channel_index], rate, target_length))
        return np.stack(channels, axis=1)

    def _time_stretch_channel(self, samples, rate: float, target_length: int):
        if samples.size == 0:
            return samples
        n_fft = min(2048, max(256, 1 << (samples.size.bit_length() - 1)))
        if n_fft < 256:
            n_fft = 256
        if n_fft > samples.size:
            n_fft = max(64, 1 << (samples.size.bit_length() - 1))
        hop_length = max(16, n_fft // 4)
        _, _, spectrum = stft(
            samples,
            window="hann",
            nperseg=n_fft,
            noverlap=n_fft - hop_length,
            boundary="zeros",
            padded=True,
        )
        if spectrum.shape[1] <= 1:
            return self._fit_length(samples.astype(np.float32, copy=False), target_length)

        time_steps = np.arange(0, spectrum.shape[1] - 1, rate, dtype=np.float64)
        phase_advance = np.linspace(0.0, np.pi * hop_length, spectrum.shape[0], dtype=np.float64)
        phase_accumulator = np.angle(spectrum[:, 0]).astype(np.float64, copy=True)
        stretched = np.empty((spectrum.shape[0], len(time_steps)), dtype=np.complex128)

        for output_index, time_step in enumerate(time_steps):
            base_index = int(np.floor(time_step))
            alpha = float(time_step - base_index)
            left = spectrum[:, base_index]
            right = spectrum[:, min(base_index + 1, spectrum.shape[1] - 1)]
            magnitude = (1.0 - alpha) * np.abs(left) + alpha * np.abs(right)
            delta = np.angle(right) - np.angle(left) - phase_advance
            delta -= 2.0 * np.pi * np.round(delta / (2.0 * np.pi))
            phase_accumulator += phase_advance + delta
            stretched[:, output_index] = magnitude * np.exp(1j * phase_accumulator)

        _, restored = istft(
            stretched,
            window="hann",
            nperseg=n_fft,
            noverlap=n_fft - hop_length,
            input_onesided=True,
            boundary=True,
        )
        return self._fit_length(restored.astype(np.float32, copy=False), target_length)

    def _fit_length(self, samples, target_length: int):
        if samples.shape[0] == target_length:
            return samples
        if samples.shape[0] > target_length:
            return samples[:target_length]
        padding = np.zeros(target_length - samples.shape[0], dtype=samples.dtype)
        return np.concatenate([samples, padding], axis=0)

    def _resample(self, audio_data, source_rate: int, target_rate: int):
        ratio_fraction = Fraction(target_rate, source_rate).limit_denominator(1000)
        return resample_poly(audio_data, ratio_fraction.numerator, ratio_fraction.denominator, axis=0)