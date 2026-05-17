"""音频计量数据传输对象（DTO）。

从 services/audio_meter_service.py 提取至 models 层，
解除 View → Service 的跨层耦合。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LoudnessReading:
    """响度读数数据结构。"""

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
    """音频计量快照数据结构。"""

    available: bool
    reason: str = ""
    source: LoudnessReading | None = None
    processed: LoudnessReading | None = None