from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from audioforge.app.models.audio_project import AudioProject, BusConfig, ClipModel, EventModel, FolderModel, MASTER_BUS_NAME, ProjectSettings, new_id
from audioforge.app.services.exporter import RuntimeExporter
from audioforge.app.services.project_serializer import ProjectSerializer
from audioforge.app.services.validator import ProjectValidator


@dataclass(slots=True)
class CoverageEntry:
    event_id: str
    bus: str
    play_mode: str
    clip_count: int
    covered_points: list[str]
    source_files: list[str]
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a broad AudioForge sample project from test WAVs and emit a developer handoff document.")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    source_dir = args.source_dir.resolve()
    report_root = (args.report_root or (workspace / "reports" / "developer_handoff_sample")).resolve()
    export_root = report_root / "export"
    checks_root = report_root / "checks"
    project_path = report_root / "developer_handoff_sample.afproj"

    wav_files = sorted(source_dir.rglob("*.wav"))
    if not wav_files:
        print(f"No WAV files found under {source_dir}")
        return 1

    project, coverage_entries = build_developer_handoff_project(wav_files, export_root)
    validator = ProjectValidator()
    issues = validator.validate(project)
    error_count = sum(1 for issue in issues if issue.severity == "Error")
    warning_count = sum(1 for issue in issues if issue.severity == "Warning")
    if error_count:
        print(f"Validation failed before export: errors={error_count} warnings={warning_count}")
        for issue in issues:
            print(f"- {issue.severity} {issue.code} {issue.target}: {issue.message}")
        return 1

    report_root.mkdir(parents=True, exist_ok=True)
    ProjectSerializer().save(project, project_path)
    RuntimeExporter().export(project, export_root, issues)

    command = [
        sys.executable,
        str(workspace / "tools" / "run_full_chain_check.py"),
        "--workspace",
        str(workspace),
        "--export-dir",
        str(export_root),
        "--report-dir",
        str(checks_root),
    ]
    completed = subprocess.run(command, cwd=workspace)
    write_developer_handoff_docs(
        report_root=report_root,
        project=project,
        project_path=project_path,
        export_root=export_root,
        checks_root=checks_root,
        coverage_entries=coverage_entries,
        source_dir=source_dir,
        warning_count=warning_count,
        passed=completed.returncode == 0,
    )
    print(f"Developer handoff project saved to {project_path}")
    print(f"Export directory: {export_root}")
    print(f"Coverage events: {len(coverage_entries)}")
    print(f"Warnings: {warning_count}")
    return completed.returncode


def build_developer_handoff_project(wav_files: list[Path], export_root: Path) -> tuple[AudioProject, list[CoverageEntry]]:
    selector = SourceSelector(wav_files)
    project = AudioProject.create_empty(name="DeveloperHandoffSample")
    project.settings = ProjectSettings(
        default_bus="UI",
        export_root=str(export_root),
        buses=["BGM", "SFX", "UI"],
        bus_configs=[
            BusConfig(name=MASTER_BUS_NAME),
            BusConfig(name="BGM", volume_db=-3.0),
            BusConfig(name="SFX", volume_db=-1.5),
            BusConfig(name="UI", parent_bus="SFX", volume_db=-1.0),
        ],
        source_audio_format="wav",
        runtime_audio_format="wav",
    )
    root_folder_id = project.root_folder_ids[0]
    project.folders[root_folder_id].name = "Developer Handoff"

    ui_folder = FolderModel(id=new_id("folder"), name="UI")
    sfx_folder = FolderModel(id=new_id("folder"), name="SFX")
    bgm_folder = FolderModel(id=new_id("folder"), name="BGM Proxy")
    project.add_folder(root_folder_id, ui_folder)
    project.add_folder(root_folder_id, sfx_folder)
    project.add_folder(root_folder_id, bgm_folder)

    coverage_entries: list[CoverageEntry] = []

    random_click_files = selector.take("UICLICK_CLICK", 4)
    event = EventModel(
        id="UI_Click_RandomWeighted",
        display_name="UI Click Random Weighted",
        bus="UI",
        play_mode="Random",
        avoid_immediate_repeat=True,
        volume_db=-2.0,
        volume_rand_min_db=-1.0,
        volume_rand_max_db=0.0,
        clips=build_clips(random_click_files, "ui/click/random", weights=[5, 3, 2, 1]),
        notes="覆盖 Random、AvoidImmediateRepeat、Weight、VolumeRandDb。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["Random", "AvoidImmediateRepeat", "Weight", "VolumeRandDb"], [path.name for path in random_click_files], event.notes)
    )

    confirm_sequence_files = selector.take("UICLICK_CONFIRM", 4)
    event = EventModel(
        id="UI_Confirm_Sequence",
        display_name="UI Confirm Sequence",
        bus="UI",
        play_mode="Sequence",
        volume_db=-1.5,
        clips=build_clips(confirm_sequence_files, "ui/confirm/sequence"),
        notes="覆盖 Sequence 顺序轮转。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["Sequence"], [path.name for path in confirm_sequence_files], event.notes)
    )

    combo_files = selector.take("UIMISC_ZAP", 3)
    event = EventModel(
        id="UI_Zap_Combo",
        display_name="UI Zap Combo",
        bus="UI",
        play_mode="Combo",
        volume_db=-2.0,
        pitch_rand_min_cents=-50,
        pitch_rand_max_cents=50,
        combo_pitch_step_cents=200,
        combo_reset_seconds=1.2,
        combo_max_step=4,
        clips=build_clips(combo_files, "ui/zap/combo"),
        notes="覆盖 ComboPitchStepCents、ComboResetSeconds、ComboMaxStep、PitchRandCents。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["Combo", "ComboPitchStepCents", "ComboResetSeconds", "ComboMaxStep", "PitchRandCents"], [path.name for path in combo_files], event.notes)
    )

    deny_files = selector.take("UIMISC_DENY", 2)
    event = EventModel(
        id="UI_Deny_Cooldown",
        display_name="UI Deny Cooldown",
        bus="UI",
        play_mode="Random",
        cooldown_seconds=0.35,
        volume_db=-2.5,
        clips=build_clips(deny_files, "ui/deny/cooldown"),
        notes="覆盖 CooldownSeconds。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["CooldownSeconds"], [path.name for path in deny_files], event.notes)
    )

    reject_files = selector.take("UIMVMT_WHOOSH NEUTRAL", 1)
    event = EventModel(
        id="UI_Whoosh_RejectNew",
        display_name="UI Whoosh Reject New",
        bus="UI",
        play_mode="Random",
        max_instances=1,
        steal_policy="RejectNew",
        clips=build_clips(reject_files, "ui/whoosh/reject_new"),
        notes="覆盖 MaxInstances=1 与 StealPolicy=RejectNew。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["MaxInstances", "StealPolicy=RejectNew"], [path.name for path in reject_files], event.notes)
    )

    stop_oldest_files = selector.take("UIMVMT_WHOOSH POSITIVE", 1)
    event = EventModel(
        id="UI_Whoosh_StopOldest",
        display_name="UI Whoosh Stop Oldest",
        bus="UI",
        play_mode="Random",
        max_instances=1,
        steal_policy="StopOldest",
        clips=build_clips(stop_oldest_files, "ui/whoosh/stop_oldest"),
        notes="覆盖 MaxInstances=1 与 StealPolicy=StopOldest。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["MaxInstances", "StealPolicy=StopOldest"], [path.name for path in stop_oldest_files], event.notes)
    )

    popup_files = selector.take("UIMVMT_POP UP", 2)
    popup_clips = build_clips(popup_files, "ui/popup/trim_loop")
    popup_clips[0].trim_start_ms = 5
    popup_clips[0].trim_end_ms = 10
    popup_clips[0].loop_start_ms = 15
    popup_clips[0].loop_end_ms = 40
    event = EventModel(
        id="UI_Popup_TrimLoop_Metadata",
        display_name="UI Popup Trim Loop Metadata",
        bus="UI",
        play_mode="Random",
        clips=popup_clips,
        notes="覆盖 TrimStartMs、TrimEndMs、LoopStartMs、LoopEndMs 元数据。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["TrimStartMs", "TrimEndMs", "LoopStartMs", "LoopEndMs"], [path.name for path in popup_files], event.notes)
    )

    match_files = selector.take("UIMISC_MATCH", 3)
    event = EventModel(
        id="UI_Match_PitchRandom",
        display_name="UI Match Pitch Random",
        bus="UI",
        play_mode="Random",
        pitch_cents=100,
        pitch_rand_min_cents=-100,
        pitch_rand_max_cents=150,
        clips=build_clips(match_files, "ui/match/pitch_random", weights=[4, 3, 2]),
        notes="覆盖 PitchCents、PitchRandCents。",
    )
    project.add_event(ui_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["PitchCents", "PitchRandCents"], [path.name for path in match_files], event.notes)
    )

    poof_random_files = selector.take("MAGPOOF_POOF", 5)
    event = EventModel(
        id="SFX_Poof_RandomWeighted",
        display_name="SFX Poof Random Weighted",
        bus="SFX",
        play_mode="Random",
        avoid_immediate_repeat=True,
        volume_db=-3.0,
        clips=build_clips(poof_random_files, "sfx/poof/random", weights=[5, 4, 3, 2, 1]),
        notes="覆盖 SFX 总线、Random、AvoidImmediateRepeat、Weight。",
    )
    project.add_event(sfx_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["SFX Bus", "Random", "AvoidImmediateRepeat", "Weight"], [path.name for path in poof_random_files], event.notes)
    )

    poof_sequence_files = selector.take("MAGPOOF_POOF", 3)
    event = EventModel(
        id="SFX_Poof_Sequence",
        display_name="SFX Poof Sequence",
        bus="SFX",
        play_mode="Sequence",
        clips=build_clips(poof_sequence_files, "sfx/poof/sequence"),
        notes="覆盖 SFX 总线下的 Sequence。",
    )
    project.add_event(sfx_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["SFX Bus", "Sequence"], [path.name for path in poof_sequence_files], event.notes)
    )

    bgm_proxy_files = selector.take("UIMVMT_WHOOSH POSITIVE", 1)
    bgm_clips = build_clips(bgm_proxy_files, "bgm/proxy/menu")
    bgm_clips[0].loop_start_ms = 20
    bgm_clips[0].loop_end_ms = 60
    event = EventModel(
        id="BGM_Menu_ProxyLoop",
        display_name="BGM Menu Proxy Loop",
        bus="BGM",
        play_mode="Random",
        volume_db=-4.0,
        max_instances=1,
        steal_policy="RejectNew",
        clips=bgm_clips,
        notes="测试 WAV 包不含真实音乐素材，此事件使用 whoosh 代理素材，仅用于 BGM 总线、Loop 元数据和资源路径契约验证。",
    )
    project.add_event(bgm_folder.id, event)
    coverage_entries.append(
        CoverageEntry(event.id, event.bus, event.play_mode, len(event.clips), ["BGM Bus", "Loop Metadata", "Proxy Asset"], [path.name for path in bgm_proxy_files], event.notes)
    )

    return project, coverage_entries


class SourceSelector:
    def __init__(self, wav_files: list[Path]) -> None:
        self.wav_files = sorted(wav_files)
        self._used: set[Path] = set()

    def take(self, prefix: str, count: int) -> list[Path]:
        matches = [
            path
            for path in self.wav_files
            if path not in self._used and path.stem.upper().startswith(prefix)
        ]
        if len(matches) < count:
            raise ValueError(f"Not enough WAV files for prefix '{prefix}'. Need {count}, got {len(matches)}.")
        selected = matches[:count]
        self._used.update(selected)
        return selected


def build_clips(source_files: list[Path], asset_prefix: str, *, weights: list[int] | None = None) -> list[ClipModel]:
    clips: list[ClipModel] = []
    for index, source_path in enumerate(source_files, start=1):
        asset_key = f"{asset_prefix}/{index:02d}_{slugify(source_path.stem)}"
        clip = ClipModel.from_path(source_path, asset_key)
        if weights and index - 1 < len(weights):
            clip.weight = weights[index - 1]
        clips.append(clip)
    return clips


def slugify(stem: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in stem)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_") or "clip"


def write_developer_handoff_docs(
    *,
    report_root: Path,
    project: AudioProject,
    project_path: Path,
    export_root: Path,
    checks_root: Path,
    coverage_entries: list[CoverageEntry],
    source_dir: Path,
    warning_count: int,
    passed: bool,
) -> None:
    full_chain_report_path = checks_root / "full_chain_report.json"
    full_chain_report = json.loads(full_chain_report_path.read_text(encoding="utf-8")) if full_chain_report_path.exists() else {}
    build_report_path = export_root / "BuildReport.json"
    build_report = json.loads(build_report_path.read_text(encoding="utf-8")) if build_report_path.exists() else {}
    export_issues = build_report.get("Issues", []) if isinstance(build_report, dict) else []
    payload = {
        "result": "PASS" if passed else "FAIL",
        "source_dir": str(source_dir),
        "project_path": str(project_path),
        "export_root": str(export_root),
        "checks_root": str(checks_root),
        "event_count": len(project.events),
        "clip_count": sum(len(event.clips) for event in project.events.values()),
        "warning_count": warning_count,
        "bus_configs": [config.to_dict() for config in project.settings.bus_configs],
        "coverage_entries": [asdict(entry) for entry in coverage_entries],
        "export_issues": export_issues,
        "full_chain_report": full_chain_report,
        "residual_risks": [
            "BGM 事件使用代理素材，仅用于数据契约验证，不代表最终音乐听感。",
            "Trim 与 Loop 字段当前主要作为元数据导出，运行时是否实现样本级处理由接入方决定。",
            "本次文档只覆盖运行时消费契约，不包含 Unity 场景搭建或联调步骤。",
        ],
    }
    (report_root / "developer_handoff.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AudioForge 运行时开发对接文档（测试 WAV 模拟工程）",
        "",
        "## 1. 文档目标",
        "",
        "- 本文档面向运行时开发，交付一套基于真实测试 WAV 自动生成的模拟工程。",
        "- 本文档只说明导出产物、事件语义、总线关系和验收重点，不包含 Unity 联调步骤。",
        f"- 当前结果：{'PASS' if passed else 'FAIL'}。",
        "",
        "## 2. 交付物",
        "",
        f"- 工程文件：{project_path}",
        f"- 导出目录：{export_root}",
        f"- 全链路检查：{checks_root}",
        f"- 源 WAV 目录：{source_dir}",
        "",
        "导出目录固定包含：",
        "",
        "- AudioData.json",
        "- AudioManifest.json",
        "- AudioEventID.cs",
        "- BuildReport.json",
        "- Assets/**",
        "",
        "## 3. 总线拓扑",
        "",
        "- Master -> BGM",
        "- Master -> SFX -> UI",
        "- 默认总线：UI",
        "- RuntimeAudioFormat：wav",
        "",
        "## 4. 覆盖范围",
        "",
        f"- 事件数：{len(project.events)}",
        f"- 片段数：{sum(len(event.clips) for event in project.events.values())}",
        f"- 校验警告数：{warning_count}",
        "",
        "本工程覆盖以下运行时消费点：",
        "",
        "- Random",
        "- Sequence",
        "- Combo",
        "- AvoidImmediateRepeat",
        "- Weight",
        "- CooldownSeconds",
        "- MaxInstances",
        "- StealPolicy=RejectNew",
        "- StealPolicy=StopOldest",
        "- VolumeDb / VolumeRandDb",
        "- PitchCents / PitchRandCents",
        "- TrimStartMs / TrimEndMs",
        "- LoopStartMs / LoopEndMs",
        "- BusConfigs / ParentBus / IsMuted / VolumeDb",
        "",
    ]
    if export_issues:
        lines.extend([
            "## 4.1 当前警告说明",
            "",
        ])
        for issue in export_issues:
            if not isinstance(issue, dict):
                continue
            lines.append(f"- {issue.get('code', 'UNKNOWN')} / {issue.get('target', '-')}: {issue.get('message', '')}")
        lines.append("")

    lines.extend([
        "## 5. 事件清单",
        "",
        "| EventId | Bus | PlayMode | ClipCount | 覆盖点 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for entry in coverage_entries:
        lines.append(f"| {entry.event_id} | {entry.bus} | {entry.play_mode} | {entry.clip_count} | {'; '.join(entry.covered_points)} |")

    lines.extend([
        "",
        "## 6. 事件说明",
        "",
    ])
    for entry in coverage_entries:
        lines.append(f"### {entry.event_id}")
        lines.append("")
        lines.append(f"- 总线：{entry.bus}")
        lines.append(f"- 播放模式：{entry.play_mode}")
        lines.append(f"- 覆盖点：{'、'.join(entry.covered_points)}")
        lines.append(f"- 源 WAV：{'；'.join(entry.source_files)}")
        lines.append(f"- 说明：{entry.notes}")
        lines.append("")

    lines.extend([
        "## 7. 开发对接要求",
        "",
        "开发侧消费本样板工程时，至少需要做到：",
        "",
        "1. 以 AudioData.json 作为唯一真源建立事件索引与总线索引。",
        "2. 通过 EventId 精确找到事件，并读取 Bus、PlayMode、Clips 与各行为参数。",
        "3. 通过 AssetKey + RuntimeAudioFormat 拼接运行时资源路径，而不是依赖 SourcePath。",
        "4. 读取 BusConfigs 还原父子路由、初始音量和静音状态。",
        "5. 对 Random、Sequence、Combo、Cooldown、MaxInstances 按字段语义执行。",
        "6. 把 Trim 和 Loop 字段至少当作元数据保留到运行时对象，而不是在消费阶段丢弃。",
        "",
        "## 8. 建议的开发验收点",
        "",
        "1. UI_Click_RandomWeighted 连续触发时，应按权重离散随机，并避免立即重复。",
        "2. UI_Confirm_Sequence 应按固定顺序轮转四个片段。",
        "3. UI_Zap_Combo 在连续触发窗口内应递增 Combo 音高，超时后重置。",
        "4. UI_Deny_Cooldown 在冷却窗口内应拒绝新触发。",
        "5. UI_Whoosh_RejectNew 与 UI_Whoosh_StopOldest 应体现不同的并发上限策略。",
        "6. UI_Popup_TrimLoop_Metadata 与 BGM_Menu_ProxyLoop 应保留 Trim / Loop 元数据。",
        "7. 所有事件的 Clip.AssetKey 都应能在 AudioManifest.json 找到对应条目。",
        "",
        "## 9. 已知说明",
        "",
        "- BGM_Menu_ProxyLoop 使用代理素材，因为测试 WAV 包不含真实音乐资源。",
        "- 当前文档针对运行时数据对接，不要求你在此轮做 Unity 场景联调。",
        "- 全链路检查报告可作为本次交付的机器验证附件。",
        "",
    ])
    (report_root / "developer_handoff.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())