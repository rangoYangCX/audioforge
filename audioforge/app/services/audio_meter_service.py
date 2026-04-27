from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

try:
    import numpy as np
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    pyln = None
    resample_poly = None
    sf = None

from audioforge.app.services.preview_audio_renderer import PreviewAudioRenderer


@dataclass(slots=True)
class LoudnessReading:
    short_term_lufs: float = float("-inf")
    short_term_max_lufs: float = float("-inf")
    integrated_lufs: float = float("-inf")
    momentary_lufs: float = float("-inf")
    momentary_max_lufs: float = float("-inf")
    loudness_range_lu: float = 0.0
    true_peak_db: float = float("-inf")
    left_peak_db: float = float("-inf")
    right_peak_db: float = float("-inf")
    left_rms_db: float = float("-inf")
    right_rms_db: float = float("-inf")
    short_term_history: list[float] | None = None
    momentary_history: list[float] | None = None


@dataclass(slots=True)
class AudioMeterSnapshot:
    available: bool
    reason: str = ""
    source: LoudnessReading | None = None
    processed: LoudnessReading | None = None


class AudioMeterService:
    def __init__(self) -> None:
        self._renderer = PreviewAudioRenderer()

    def is_available(self) -> bool:
        return sf is not None and np is not None and pyln is not None and resample_poly is not None and self._renderer.is_available()

    def analyze_file(
        self,
        file_path: str,
        applied_gain_db: float = 0.0,
        *,
        pitch_cents: int = 0,
        preserve_timing_pitch_cents: int = 0,
        trim_start_ms: int = 0,
        trim_end_ms: int = 0,
    ) -> AudioMeterSnapshot:
        if not self.is_available():
            return AudioMeterSnapshot(available=False, reason="soundfile、numpy、pyloudnorm 或 scipy 不可用。")

        source = Path(file_path)
        if not source.exists():
            return AudioMeterSnapshot(available=False, reason=f"音频文件不存在：{file_path}")

        audio_data, sample_rate = sf.read(str(source), always_2d=True)
        if audio_data.size == 0:
            return AudioMeterSnapshot(available=False, reason="音频文件为空。")

        if audio_data.shape[1] == 1:
            audio_data = np.repeat(audio_data, 2, axis=1)
        elif audio_data.shape[1] > 2:
            audio_data = audio_data[:, :2]

        gain = self._db_to_linear(applied_gain_db)
        source_scaled = audio_data.astype(np.float64, copy=False)

        try:
            processed = self._renderer.render_file(
                file_path,
                trim_start_ms=trim_start_ms,
                trim_end_ms=trim_end_ms,
                pitch_cents=pitch_cents,
                preserve_timing_pitch_cents=preserve_timing_pitch_cents,
            )
            processed_scaled = processed.audio_data.astype(np.float64, copy=False) * gain
            processed_sample_rate = processed.sample_rate
        except Exception as exc:
            return AudioMeterSnapshot(available=False, reason=f"试听音频处理失败：{exc}")

        return AudioMeterSnapshot(
            available=True,
            source=self._analyze_reading(source_scaled, sample_rate),
            processed=self._analyze_reading(processed_scaled, processed_sample_rate),
        )

    def _analyze_reading(self, scaled, sample_rate: int) -> LoudnessReading:
        left_channel = scaled[:, 0]
        right_channel = scaled[:, 1]

        momentary_lufs, momentary_max_lufs = self._measure_block_loudness(scaled, sample_rate, 0.4)
        momentary_history = self._block_history(scaled, sample_rate, 0.4)
        short_term_lufs, short_term_max_lufs = self._measure_block_loudness(scaled, sample_rate, 3.0)
        short_term_history = self._block_history(scaled, sample_rate, 3.0)
        integrated_lufs = self._integrated_loudness(scaled, sample_rate)
        loudness_range_lu = self._loudness_range(scaled, sample_rate)

        left_peak_db = self._true_peak_db(left_channel)
        right_peak_db = self._true_peak_db(right_channel)
        left_rms_db = self._rms_db(left_channel)
        right_rms_db = self._rms_db(right_channel)
        true_peak_db = max(left_peak_db, right_peak_db)

        return LoudnessReading(
            short_term_lufs=short_term_lufs,
            short_term_max_lufs=short_term_max_lufs,
            integrated_lufs=integrated_lufs,
            momentary_lufs=momentary_lufs,
            momentary_max_lufs=momentary_max_lufs,
            loudness_range_lu=loudness_range_lu,
            true_peak_db=true_peak_db,
            left_peak_db=left_peak_db,
            right_peak_db=right_peak_db,
            left_rms_db=left_rms_db,
            right_rms_db=right_rms_db,
            short_term_history=short_term_history,
            momentary_history=momentary_history,
        )

    def _db_to_linear(self, value_db: float) -> float:
        if value_db <= -96.0:
            return 0.0
        return math.pow(10.0, value_db / 20.0)

    def _peak_db(self, channel) -> float:
        peak = float(np.max(np.abs(channel)))
        return self._to_db(peak)

    def _true_peak_db(self, channel, oversample_factor: int = 4) -> float:
        oversampled = resample_poly(channel, oversample_factor, 1)
        peak = float(np.max(np.abs(oversampled)))
        return self._to_db(peak)

    def _rms_db(self, channel) -> float:
        rms = float(np.sqrt(np.mean(np.square(channel), dtype=np.float64)))
        return self._to_db(rms)

    def _integrated_loudness(self, data, sample_rate: int) -> float:
        meter = pyln.Meter(sample_rate, block_size=0.4, filter_class="K-weighting")
        return float(meter.integrated_loudness(self._pad_to_block_size(data, sample_rate, 0.4)))

    def _measure_block_loudness(self, data, sample_rate: int, block_size: float) -> tuple[float, float]:
        meter = pyln.Meter(sample_rate, block_size=block_size, filter_class="K-weighting")
        padded = self._pad_to_block_size(data, sample_rate, block_size)
        meter.integrated_loudness(padded)
        block_values = [float(value) for value in getattr(meter, "blockwise_loudness", []) if math.isfinite(value)]
        if not block_values:
            return float("-inf"), float("-inf")
        return block_values[-1], max(block_values)

    def _block_history(self, data, sample_rate: int, block_size: float) -> list[float]:
        meter = pyln.Meter(sample_rate, block_size=block_size, filter_class="K-weighting")
        padded = self._pad_to_block_size(data, sample_rate, block_size)
        meter.integrated_loudness(padded)
        return [float(value) for value in getattr(meter, "blockwise_loudness", [])]

    def _loudness_range(self, data, sample_rate: int) -> float:
        meter = pyln.Meter(sample_rate, block_size=3.0, filter_class="K-weighting")
        return float(meter.loudness_range(self._pad_to_block_size(data, sample_rate, 3.0)))

    def _pad_to_block_size(self, data, sample_rate: int, block_size: float):
        minimum_frames = int(math.ceil(sample_rate * block_size))
        if data.shape[0] >= minimum_frames:
            return data
        padding = np.zeros((minimum_frames - data.shape[0], data.shape[1]), dtype=data.dtype)
        return np.concatenate([data, padding], axis=0)

    def _to_db(self, value: float) -> float:
        if value <= 1e-9:
            return float("-inf")
        return 20.0 * math.log10(value)