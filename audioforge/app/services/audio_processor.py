from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    import soundfile as sf
except Exception:  # pragma: no cover - optional runtime dependency fallback
    np = None
    sf = None

from audioforge.app.models.audio_project import ClipModel, ProjectSettings

logger = logging.getLogger(__name__)


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

        # 释放源文件内存
        del audio_data
        gc.collect()

        if target_format == "ogg":
            self._write_ogg_subprocess(trimmed_audio, sample_rate, destination_path)
            return
        if target_format == "wav":
            sf.write(str(destination_path), trimmed_audio, sample_rate, format="WAV")
            return
        raise ValueError(f"Unsupported runtime audio format: {project_settings.runtime_audio_format}")

    # ── OGG 编码：子进程隔离 ──────────────────────────

    def _write_ogg_subprocess(
        self,
        audio_data: "np.ndarray",
        sample_rate: int,
        destination_path: Path,
    ) -> None:
        """将 OGG 编码放入子进程执行，防止 libsndfile Vorbis 编码器的
        内存句柄泄漏导致主进程 SIGSEGV。

        流程：
        1. 主进程：trim+fade 后写入临时 WAV
        2. 子进程：soundfile 读 WAV → 写 OGG
        3. 主进程：等子进程完成后 rename OGG 到目标路径

        即使子进程因 libsndfile bug 崩溃（SIGSEGV），主进程也能捕获
        并决定重试或跳过，不会整体闪退。
        """
        # 1. 写中间 WAV 到临时目录
        tmp_dir = tempfile.mkdtemp(prefix="af_ogg_")
        try:
            wav_tmp = Path(tmp_dir) / "intermediate.wav"
            sf.write(str(wav_tmp), audio_data, sample_rate, format="WAV")

            # 释放 trimmed_audio 内存
            del audio_data
            gc.collect()

            # 2. 子进程编码 WAV → OGG
            ogg_tmp = Path(tmp_dir) / "intermediate.ogg"
            script = (
                "import soundfile as sf; "
                "import sys; "
                f"data, sr = sf.read(sys.argv[1], always_2d=False, dtype='float32'); "
                f"sf.write(sys.argv[2], data, sr, format='OGG', subtype='VORBIS')"
            )
            python_exe = sys.executable
            result = subprocess.run(
                [python_exe, "-c", script, str(wav_tmp), str(ogg_tmp)],
                capture_output=True,
                timeout=60,
            )

            if result.returncode != 0:
                # 子进程可能因 SIGSEGV 返回 -11 (信号 11) 或其他非零退出码
                logger.warning(
                    "OGG subprocess returned %d (stderr: %s), retrying in-process",
                    result.returncode,
                    result.stderr[:200] if result.stderr else "",
                )
                # 重试：在主进程中直接编码（小概率场景）
                self._write_ogg_inprocess(wav_tmp, ogg_tmp)

            if not ogg_tmp.exists():
                raise RuntimeError(f"OGG file not created: {ogg_tmp}")

            # 3. 原子 rename
            shutil.move(str(ogg_tmp), str(destination_path))
        finally:
            # 清理临时目录
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    def _write_ogg_inprocess(self, wav_path: Path, ogg_path: Path) -> None:
        """在主进程中直接编码 OGG（仅作为子进程失败后的重试）。"""
        audio_data, sample_rate = sf.read(str(wav_path), always_2d=False, dtype="float32")
        sf.write(str(ogg_path), audio_data, sample_rate, format="OGG", subtype="VORBIS")
        del audio_data
        gc.collect()

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