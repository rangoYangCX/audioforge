"""AB 实验增量导出器。

对比底板工程与方案工程，生成增量 JSON（含 Op 字段），
并导出新增/变更的音频资源。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audioforge.app.models.audio_project import (
    AudioProject,
    ClipModel,
    EventModel,
)
from audioforge.app.models.experiment_workspace import (
    ExperimentTask,
    ExperimentVariant,
)
from audioforge.app.services.audio_processor import AudioProcessor
from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.utils.constants import DEFAULT_EXPORT_ASSETS_DIRNAME

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExperimentDeltaResult:
    """增量导出结果。"""

    delta_file: Path  # ExperimentDelta_<taskId>_<variantId>.json
    assets_dir: Path  # Assets/ 目录
    report: dict[str, Any]  # 导出报告
    added_count: int = 0
    modified_count: int = 0
    deleted_count: int = 0
    asset_count: int = 0


class ExperimentExporter:
    """对比底板与方案，生成增量导出。"""

    @classmethod
    def create_default(
        cls,
        *,
        audio_processor: AudioProcessor | None = None,
        runtime_exporter: RuntimeExporter | None = None,
    ) -> "ExperimentExporter":
        return cls(
            audio_processor=audio_processor or AudioProcessor(),
            runtime_exporter=runtime_exporter or RuntimeExporter(),
        )

    def __init__(
        self,
        audio_processor: AudioProcessor | None = None,
        runtime_exporter: RuntimeExporter | None = None,
    ) -> None:
        self.audio_processor = audio_processor or AudioProcessor()
        self.runtime_exporter = runtime_exporter or RuntimeExporter()

    def export_delta(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
        task: ExperimentTask,
        variant: ExperimentVariant,
        export_root: Path,
    ) -> ExperimentDeltaResult:
        """执行增量导出。

        Args:
            base_project: 底板工程。
            variant_project: 方案工程（底板副本经过编辑）。
            task: 实验任务元数据。
            variant: 方案元数据。
            export_root: 导出根目录。
        """
        export_root = export_root.resolve()
        parent = export_root.parent
        parent.mkdir(parents=True, exist_ok=True)

        temp_root = Path(tempfile.mkdtemp(prefix="experiment_delta_", dir=str(parent)))

        try:
            # 1. 计算增量差异
            deltas = self._compute_event_deltas(base_project, variant_project)

            # 2. 收集需要导出的资源
            delta_assets = self._collect_delta_assets(variant_project, deltas)

            # 3. 构建增量 JSON
            delta_payload = self._build_delta_payload(
                base_project=base_project,
                variant_project=variant_project,
                task=task,
                variant=variant,
                deltas=deltas,
                assets=delta_assets,
            )

            # 4. 写入文件
            delta_file = temp_root / f"ExperimentDelta_{task.id}_{variant.id}.json"
            delta_file.write_text(
                json.dumps(delta_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 5. 导出资源文件
            assets_dir = temp_root / DEFAULT_EXPORT_ASSETS_DIRNAME
            if delta_assets:
                assets_dir.mkdir(parents=True, exist_ok=True)
                self._materialize_delta_assets(variant_project, delta_assets, assets_dir)

            # 6. 原子提交
            if export_root.exists():
                shutil.rmtree(export_root, ignore_errors=True)
            temp_root.replace(export_root)

            # 统计
            added_count = sum(1 for d in deltas.values() if d.get("Op") == "add")
            modified_count = sum(1 for d in deltas.values() if d.get("Op") == "modify")
            deleted_count = sum(1 for d in deltas.values() if d.get("Op") == "delete")

            report = {
                "TaskId": task.id,
                "TaskName": task.name,
                "VariantId": variant.id,
                "VariantName": variant.name,
                "TotalDeltaEvents": len(deltas),
                "AddedEvents": added_count,
                "ModifiedEvents": modified_count,
                "DeletedEvents": deleted_count,
                "DeltaAssetCount": len(delta_assets),
            }

            result = ExperimentDeltaResult(
                delta_file=export_root / delta_file.name,
                assets_dir=assets_dir if delta_assets else export_root / DEFAULT_EXPORT_ASSETS_DIRNAME,
                report=report,
                added_count=added_count,
                modified_count=modified_count,
                deleted_count=deleted_count,
                asset_count=len(delta_assets),
            )

            logger.info(
                "Experiment delta exported: task=%s variant=%s added=%d modified=%d deleted=%d assets=%d",
                task.id,
                variant.id,
                added_count,
                modified_count,
                deleted_count,
                len(delta_assets),
            )
            return result

        except Exception:
            shutil.rmtree(temp_root, ignore_errors=True)
            raise

    def compute_deltas_preview(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
    ) -> list[dict[str, Any]]:
        """预览增量差异（不写入文件），返回差异列表。"""
        deltas = self._compute_event_deltas(base_project, variant_project)
        preview: list[dict[str, Any]] = []
        for event_name, delta in deltas.items():
            entry: dict[str, Any] = {
                "EventName": event_name,
                "Op": delta.get("Op", ""),
            }
            if delta.get("Op") == "modify":
                entry["DiffFields"] = [
                    k for k in delta.get("Audio", {})
                    if k not in ("AudioId", "DisplayName")
                ]
                event_fields = {k: v for k, v in delta.items() if k not in ("Op", "Audio", "Assets")}
                if event_fields:
                    entry["DiffFields"].extend(event_fields.keys())
            preview.append(entry)
        return preview

    # ── 差异计算 ──────────────────────────────────

    def _compute_event_deltas(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
    ) -> dict[str, dict[str, Any]]:
        """核心差异计算：对比底板与方案的 Event。"""
        base_events = {
            e.display_name: e
            for e in base_project.events.values()
            if e.display_name.strip()
        }
        variant_events = {
            e.display_name: e
            for e in variant_project.events.values()
            if e.display_name.strip()
        }

        deltas: dict[str, dict[str, Any]] = {}

        # 方案有而底板无 → add
        for name in sorted(set(variant_events) - set(base_events)):
            deltas[name] = {
                "Op": "add",
                **self._serialize_full_event(variant_events[name]),
            }

        # 底板有而方案无 → delete
        for name in sorted(set(base_events) - set(variant_events)):
            deltas[name] = {"Op": "delete"}

        # 两边都有 → 检测差异
        for name in sorted(set(base_events) & set(variant_events)):
            diff = self._diff_event(base_events[name], variant_events[name])
            if diff is not None:
                deltas[name] = {"Op": "modify", **diff}

        return deltas

    def _diff_event(self, base: EventModel, variant: EventModel) -> dict[str, Any] | None:
        """对比两个同名 Event，返回差异字段。无差异返回 None。"""
        result: dict[str, Any] = {}
        has_diff = False

        # 对比 Event 级别字段
        event_diff = self._diff_event_level(base, variant)
        if event_diff:
            result.update(event_diff)
            has_diff = True

        # 对比 Audio 级别字段
        audio_diff = self._diff_audio_level(base, variant)
        if audio_diff:
            result["Audio"] = audio_diff
            has_diff = True

        return result if has_diff else None

    def _diff_event_level(self, base: EventModel, variant: EventModel) -> dict[str, Any]:
        """对比 Event 级别参数。"""
        diff: dict[str, Any] = {}
        if base.max_instances != variant.max_instances:
            diff["MaxInstances"] = variant.max_instances
        if base.cooldown_seconds != variant.cooldown_seconds:
            diff["CooldownSeconds"] = variant.cooldown_seconds
        if base.steal_policy != variant.steal_policy:
            diff["StealPolicy"] = variant.steal_policy
        return diff

    def _diff_audio_level(self, base: EventModel, variant: EventModel) -> dict[str, Any] | None:
        """对比 Audio 级别参数和 Clips。"""
        base_audio = base.audio
        variant_audio = variant.audio

        diff: dict[str, Any] = {}
        has_diff = False

        # 基础参数对比
        if base_audio.bus != variant_audio.bus:
            diff["Bus"] = variant_audio.bus
            has_diff = True
        if base_audio.play_mode != variant_audio.play_mode:
            diff["PlayMode"] = variant_audio.play_mode
            has_diff = True
        if base_audio.volume_db != variant_audio.volume_db:
            diff["VolumeDb"] = variant_audio.volume_db
            has_diff = True
        if base_audio.pitch_cents != variant_audio.pitch_cents:
            diff["PitchCents"] = variant_audio.pitch_cents
            has_diff = True
        if base_audio.load_policy != variant_audio.load_policy:
            diff["LoadPolicy"] = variant_audio.load_policy
            has_diff = True
        if base_audio.avoid_immediate_repeat != variant_audio.avoid_immediate_repeat:
            diff["AvoidImmediateRepeat"] = variant_audio.avoid_immediate_repeat
            has_diff = True
        if base_audio.volume_rand_min_db != variant_audio.volume_rand_min_db or base_audio.volume_rand_max_db != variant_audio.volume_rand_max_db:
            diff["VolumeRandDb"] = [variant_audio.volume_rand_min_db, variant_audio.volume_rand_max_db]
            has_diff = True
        if base_audio.pitch_rand_min_cents != variant_audio.pitch_rand_min_cents or base_audio.pitch_rand_max_cents != variant_audio.pitch_rand_max_cents:
            diff["PitchRandCents"] = [variant_audio.pitch_rand_min_cents, variant_audio.pitch_rand_max_cents]
            has_diff = True

        # Clips 对比
        base_clips_sig = self._clips_signature(base_audio.clips)
        variant_clips_sig = self._clips_signature(variant_audio.clips)
        if base_clips_sig != variant_clips_sig:
            diff["Clips"] = self._serialize_clips(variant_audio.clips)
            has_diff = True

        # RTPC Bindings 对比
        base_rtpc_sig = self._rtpc_signature(base_audio.rtpc_bindings)
        variant_rtpc_sig = self._rtpc_signature(variant_audio.rtpc_bindings)
        if base_rtpc_sig != variant_rtpc_sig:
            diff["RtpcBindings"] = self.runtime_exporter.serialize_rtpc_bindings(variant_audio.rtpc_bindings)
            has_diff = True

        # State Overrides 对比
        base_state_sig = self._state_overrides_signature(base_audio.state_overrides)
        variant_state_sig = self._state_overrides_signature(variant_audio.state_overrides)
        if base_state_sig != variant_state_sig:
            diff["StateOverrides"] = self.runtime_exporter.serialize_state_overrides(variant_audio.state_overrides)
            has_diff = True

        # Switch Variants 对比
        base_switch_sig = self._switch_variants_signature(base_audio.switch_variants)
        variant_switch_sig = self._switch_variants_signature(variant_audio.switch_variants)
        if base_switch_sig != variant_switch_sig:
            diff["SwitchVariants"] = self.runtime_exporter.serialize_switch_variants(variant_audio.switch_variants)
            has_diff = True

        return diff if has_diff else None

    # ── 完整 Event 序列化（用于 Op=add）──────────

    def _serialize_full_event(self, event: EventModel) -> dict[str, Any]:
        """序列化完整 Event（新增场景）。"""
        audio = event.audio
        result: dict[str, Any] = {
            "MaxInstances": event.max_instances,
            "CooldownSeconds": event.cooldown_seconds,
            "StealPolicy": event.steal_policy,
        }
        audio_payload: dict[str, Any] = {
            "AudioId": audio.id,
            "DisplayName": audio.display_name,
            "Bus": audio.bus,
            "PlayMode": audio.play_mode,
            "VolumeDb": audio.volume_db,
            "VolumeRandDb": [audio.volume_rand_min_db, audio.volume_rand_max_db],
            "PitchCents": audio.pitch_cents,
            "PitchRandCents": [audio.pitch_rand_min_cents, audio.pitch_rand_max_cents],
            "LoadPolicy": audio.load_policy,
            "AvoidImmediateRepeat": audio.avoid_immediate_repeat,
            "Clips": self._serialize_clips(audio.clips),
        }
        if audio.rtpc_bindings:
            audio_payload["RtpcBindings"] = self.runtime_exporter.serialize_rtpc_bindings(audio.rtpc_bindings)
        if audio.state_overrides:
            audio_payload["StateOverrides"] = self.runtime_exporter.serialize_state_overrides(audio.state_overrides)
        if audio.switch_variants:
            audio_payload["SwitchVariants"] = self.runtime_exporter.serialize_switch_variants(audio.switch_variants)
        result["Audio"] = audio_payload
        return result

    @staticmethod
    def _serialize_clips(clips: list[ClipModel]) -> list[dict[str, Any]]:
        """序列化 Clip 列表。"""
        return [
            {
                "ClipId": clip.id,
                "AssetKey": clip.asset_key,
                "Weight": clip.weight,
                "TrimStartMs": clip.trim_start_ms,
                "TrimEndMs": clip.trim_end_ms,
                "FadeInMs": clip.fade_in_ms,
                "FadeOutMs": clip.fade_out_ms,
                "LoopStartMs": clip.loop_start_ms,
                "LoopEndMs": clip.loop_end_ms,
            }
            for clip in clips
        ]

    # ── 签名 / 哈希工具 ──────────────────────────

    @staticmethod
    def _clips_signature(clips: list[ClipModel]) -> str:
        """Clip 列表的稳定签名。"""
        parts: list[str] = []
        for clip in sorted(clips, key=lambda c: c.id):
            parts.append(
                f"{clip.id}|{clip.asset_key}|{clip.weight}|"
                f"{clip.trim_start_ms}|{clip.trim_end_ms}|"
                f"{clip.fade_in_ms}|{clip.fade_out_ms}|"
                f"{clip.loop_start_ms}|{clip.loop_end_ms}"
            )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    @staticmethod
    def _rtpc_signature(bindings: list) -> str:
        """RTPC 绑定的稳定签名。"""
        parts: list[str] = []
        for b in sorted(bindings, key=lambda x: f"{x.parameter_name}:{x.target}"):
            points_str = ",".join(f"{p.input_value}:{p.output_value}" for p in b.curve_points)
            parts.append(f"{b.parameter_name}|{b.target}|{b.scope}|{points_str}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    @staticmethod
    def _state_overrides_signature(overrides: list) -> str:
        """State 覆盖的稳定签名。"""
        parts: list[str] = []
        for o in sorted(overrides, key=lambda x: f"{x.group_name}:{x.state_name}"):
            parts.append(f"{o.group_name}|{o.state_name}|{o.volume_db}|{o.pitch_cents}|{o.is_muted}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    @staticmethod
    def _switch_variants_signature(variants: list) -> str:
        """Switch 变体的稳定签名。"""
        parts: list[str] = []
        for v in sorted(variants, key=lambda x: f"{x.group_name}:{x.switch_name}"):
            parts.append(f"{v.group_name}|{v.switch_name}|{','.join(v.clip_ids)}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    # ── 资源收集与导出 ────────────────────────────

    def _collect_delta_assets(
        self,
        variant_project: AudioProject,
        deltas: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """收集增量导出需要的资源条目。

        只收集 Op=add 或 Op=modify 且 Clips 有变更的资源。
        """
        asset_keys_in_delta: set[str] = set()

        for event_name, delta in deltas.items():
            op = delta.get("Op", "")
            if op == "add":
                audio_data = delta.get("Audio", {})
                for clip in audio_data.get("Clips", []):
                    asset_key = clip.get("AssetKey", "")
                    if asset_key:
                        asset_keys_in_delta.add(asset_key)
            elif op == "modify":
                audio_data = delta.get("Audio", {})
                clips = audio_data.get("Clips")
                if clips is not None:
                    for clip in clips:
                        asset_key = clip.get("AssetKey", "")
                        if asset_key:
                            asset_keys_in_delta.add(asset_key)

        # 从方案工程中提取这些资源的源路径
        assets: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for audio_obj in variant_project.audio_objects.values():
            for clip in audio_obj.clips:
                if clip.asset_key in asset_keys_in_delta and clip.asset_key not in seen_keys:
                    source_path = str(clip.source_path).strip()
                    if source_path:
                        export_filename = f"{clip.asset_key}.ogg"
                        assets.append({
                            "AssetKey": clip.asset_key,
                            "ExportPath": f"{DEFAULT_EXPORT_ASSETS_DIRNAME}/{export_filename}",
                            "SourcePath": source_path,
                        })
                        seen_keys.add(clip.asset_key)

        return assets

    def _materialize_delta_assets(
        self,
        variant_project: AudioProject,
        assets: list[dict[str, Any]],
        assets_dir: Path,
    ) -> None:
        """将增量资源编码为目标格式并写入目录。"""
        settings = variant_project.settings
        for asset_entry in assets:
            source_path = Path(asset_entry["SourcePath"])
            export_filename = Path(asset_entry["ExportPath"]).name
            target_path = assets_dir / export_filename
            if not source_path.exists():
                logger.warning("Delta asset source not found: %s", source_path)
                continue

            # 查找属于该 asset_key 的 clip（用第一个匹配的）
            clip = self._find_clip_by_asset_key(variant_project, asset_entry["AssetKey"])
            if clip is not None and self.audio_processor.can_process():
                try:
                    self.audio_processor.export_clip(clip, settings, target_path)
                    continue
                except Exception:
                    logger.exception("Failed to encode delta asset: %s → %s", source_path, target_path)

            # 回退：直接复制源文件（保持原始后缀，避免格式不匹配）
            fallback_name = f"{asset_entry['AssetKey']}{source_path.suffix}"
            fallback_path = assets_dir / fallback_name
            try:
                shutil.copy2(source_path, fallback_path)
                # 更新 asset_entry 的 ExportPath 以反映实际导出的文件名
                asset_entry["ExportPath"] = f"{DEFAULT_EXPORT_ASSETS_DIRNAME}/{fallback_name}"
            except Exception:
                logger.exception("Fallback copy also failed: %s", source_path)

    @staticmethod
    def _find_clip_by_asset_key(project: AudioProject, asset_key: str) -> ClipModel | None:
        """在工程中查找指定 asset_key 的第一个 Clip。"""
        for audio_obj in project.audio_objects.values():
            for clip in audio_obj.clips:
                if clip.asset_key == asset_key:
                    return clip
        return None

    # ── 增量 JSON 构建 ────────────────────────────

    def _build_delta_payload(
        self,
        base_project: AudioProject,
        variant_project: AudioProject,
        task: ExperimentTask,
        variant: ExperimentVariant,
        deltas: dict[str, dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """构建增量导出 JSON 的完整 payload。"""
        from audioforge.app.utils.constants import SCHEMA_VERSION
        from audioforge.app.models.audio_project import utc_now_iso

        payload: dict[str, Any] = {
            "SchemaVersion": SCHEMA_VERSION,
            "ExportType": "ExperimentDelta",
            "ExperimentId": variant.id,
            "TaskId": task.id,
            "TaskName": task.name,
            "VariantName": variant.name,
            "BaseProjectHash": self._project_hash(base_project),
            "ExportTimestamp": utc_now_iso(),
            "Events": deltas,
        }
        if assets:
            payload["Assets"] = assets
        return payload

    @staticmethod
    def _project_hash(project: AudioProject) -> str:
        """计算工程的稳定哈希（用于导出时校验底板是否变化）。"""
        data = json.dumps(project.to_dict(), sort_keys=True, ensure_ascii=False)
        return f"sha256:{hashlib.sha256(data.encode()).hexdigest()[:24]}"
