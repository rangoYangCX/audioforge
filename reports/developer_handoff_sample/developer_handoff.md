# AudioForge 运行时开发对接文档（测试 WAV 模拟工程）

## 1. 文档目标

- 本文档面向运行时开发，交付一套基于真实测试 WAV 自动生成的模拟工程。
- 本文档只说明导出产物、事件语义、总线关系和验收重点，不包含 Unity 联调步骤。
- 当前仓库级验证基线：`pytest` 59 项通过，真实 WAV 烟雾工程 PASS，全链路检查 4/4 通过。
- 当前结果：PASS。

## 2. 交付物

- 工程文件：C:\Users\EDY\wwise\reports\developer_handoff_sample\developer_handoff_sample.afproj
- 导出目录：C:\Users\EDY\wwise\reports\developer_handoff_sample\export
- 全链路检查：C:\Users\EDY\wwise\reports\developer_handoff_sample\checks
- 源 WAV 目录：E:\sfx\116 Casual UI\Casual UI\Casual UI DS

导出目录固定包含：

- AudioData.json
- AudioManifest.json
- AudioEventID.cs
- BuildReport.json
- Assets/**

## 3. 总线拓扑

- Master -> BGM
- Master -> SFX -> UI
- 默认总线：UI
- RuntimeAudioFormat：wav

## 4. 覆盖范围

- 事件数：11
- 片段数：29
- 校验警告数：2

本工程覆盖以下运行时消费点：

- Random
- Sequence
- Combo
- AvoidImmediateRepeat
- Weight
- CooldownSeconds
- MaxInstances
- StealPolicy=RejectNew
- StealPolicy=StopOldest
- VolumeDb / VolumeRandDb
- PitchCents / PitchRandCents
- TrimStartMs / TrimEndMs
- LoopStartMs / LoopEndMs
- BusConfigs / ParentBus / IsMuted / VolumeDb

## 4.1 当前警告说明

- CLIP_LOOP_NOT_IMPLEMENTED / UI_Popup_TrimLoop_Metadata: Clip 'UIMvmt_POP UP-Classic Call_B00M_CUDS' loop settings are reserved but not implemented in the current preview/runtime pipeline.
- CLIP_LOOP_NOT_IMPLEMENTED / BGM_Menu_ProxyLoop: Clip 'UIMvmt_WHOOSH POSITIVE-Flipster_B00M_CUDS' loop settings are reserved but not implemented in the current preview/runtime pipeline.

## 5. 事件清单

| EventId | Bus | PlayMode | ClipCount | 覆盖点 |
| --- | --- | --- | --- | --- |
| UI_Click_RandomWeighted | UI | Random | 4 | Random; AvoidImmediateRepeat; Weight; VolumeRandDb |
| UI_Confirm_Sequence | UI | Sequence | 4 | Sequence |
| UI_Zap_Combo | UI | Combo | 3 | Combo; ComboPitchStepCents; ComboResetSeconds; ComboMaxStep; PitchRandCents |
| UI_Deny_Cooldown | UI | Random | 2 | CooldownSeconds |
| UI_Whoosh_RejectNew | UI | Random | 1 | MaxInstances; StealPolicy=RejectNew |
| UI_Whoosh_StopOldest | UI | Random | 1 | MaxInstances; StealPolicy=StopOldest |
| UI_Popup_TrimLoop_Metadata | UI | Random | 2 | TrimStartMs; TrimEndMs; LoopStartMs; LoopEndMs |
| UI_Match_PitchRandom | UI | Random | 3 | PitchCents; PitchRandCents |
| SFX_Poof_RandomWeighted | SFX | Random | 5 | SFX Bus; Random; AvoidImmediateRepeat; Weight |
| SFX_Poof_Sequence | SFX | Sequence | 3 | SFX Bus; Sequence |
| BGM_Menu_ProxyLoop | BGM | Random | 1 | BGM Bus; Loop Metadata; Proxy Asset |

## 6. 事件说明

### UI_Click_RandomWeighted

- 总线：UI
- 播放模式：Random
- 覆盖点：Random、AvoidImmediateRepeat、Weight、VolumeRandDb
- 源 WAV：UIClick_CLICK-Chunky Monkey_B00M_CUDS.wav；UIClick_CLICK-Classic_B00M_CUDS.wav；UIClick_CLICK-Drip_B00M_CUDS.wav；UIClick_CLICK-Peep Show_B00M_CUDS.wav
- 说明：覆盖 Random、AvoidImmediateRepeat、Weight、VolumeRandDb。

### UI_Confirm_Sequence

- 总线：UI
- 播放模式：Sequence
- 覆盖点：Sequence
- 源 WAV：UIClick_CONFIRM-Affirmative_B00M_CUDS.wav；UIClick_CONFIRM-Bubble Shot_B00M_CUDS.wav；UIClick_CONFIRM-Check_B00M_CUDS.wav；UIClick_CONFIRM-Cheers My Dears_B00M_CUDS.wav
- 说明：覆盖 Sequence 顺序轮转。

### UI_Zap_Combo

- 总线：UI
- 播放模式：Combo
- 覆盖点：Combo、ComboPitchStepCents、ComboResetSeconds、ComboMaxStep、PitchRandCents
- 源 WAV：UIMisc_ZAP-Fast Flip_B00M_CUDS.wav；UIMisc_ZAP-Kickflip_B00M_CUDS.wav；UIMisc_ZAP-Pixel Poke_B00M_CUDS.wav
- 说明：覆盖 ComboPitchStepCents、ComboResetSeconds、ComboMaxStep、PitchRandCents。

### UI_Deny_Cooldown

- 总线：UI
- 播放模式：Random
- 覆盖点：CooldownSeconds
- 源 WAV：UIMisc_DENY-Give Way_B00M_CUDS.wav；UIMisc_DENY-Gloopy Glue_B00M_CUDS.wav
- 说明：覆盖 CooldownSeconds。

### UI_Whoosh_RejectNew

- 总线：UI
- 播放模式：Random
- 覆盖点：MaxInstances、StealPolicy=RejectNew
- 源 WAV：UIMvmt_WHOOSH NEUTRAL -Player Swap_B00M_CUDS.wav
- 说明：覆盖 MaxInstances=1 与 StealPolicy=RejectNew。

### UI_Whoosh_StopOldest

- 总线：UI
- 播放模式：Random
- 覆盖点：MaxInstances、StealPolicy=StopOldest
- 源 WAV：UIMvmt_WHOOSH POSITIVE-Breeze Burst_B00M_CUDS.wav
- 说明：覆盖 MaxInstances=1 与 StealPolicy=StopOldest。

### UI_Popup_TrimLoop_Metadata

- 总线：UI
- 播放模式：Random
- 覆盖点：TrimStartMs、TrimEndMs、LoopStartMs、LoopEndMs
- 源 WAV：UIMvmt_POP UP-Classic Call_B00M_CUDS.wav；UIMvmt_POP UP-Short Appearance_B00M_CUDS.wav
- 说明：覆盖 TrimStartMs、TrimEndMs、LoopStartMs、LoopEndMs 元数据。

### UI_Match_PitchRandom

- 总线：UI
- 播放模式：Random
- 覆盖点：PitchCents、PitchRandCents
- 源 WAV：UIMisc_MATCH-Align_B00M_CUDS.wav；UIMisc_MATCH-Black Custard_B00M_CUDS.wav；UIMisc_MATCH-Bubble Blop_B00M_CUDS.wav
- 说明：覆盖 PitchCents、PitchRandCents。

### SFX_Poof_RandomWeighted

- 总线：SFX
- 播放模式：Random
- 覆盖点：SFX Bus、Random、AvoidImmediateRepeat、Weight
- 源 WAV：MAGPoof_POOF-Bubble Stumble_B00M_CUDS.wav；MAGPoof_POOF-Charm_B00M_CUDS.wav；MAGPoof_POOF-Chaser_B00M_CUDS.wav；MAGPoof_POOF-Fizzflip_B00M_CUDS.wav；MAGPoof_POOF-Fizzleburst_B00M_CUDS.wav
- 说明：覆盖 SFX 总线、Random、AvoidImmediateRepeat、Weight。

### SFX_Poof_Sequence

- 总线：SFX
- 播放模式：Sequence
- 覆盖点：SFX Bus、Sequence
- 源 WAV：MAGPoof_POOF-Mystery Box_B00M_CUDS.wav；MAGPoof_POOF-Nerfed_B00M_CUDS.wav；MAGPoof_POOF-Neutral Zap_B00M_CUDS.wav
- 说明：覆盖 SFX 总线下的 Sequence。

### BGM_Menu_ProxyLoop

- 总线：BGM
- 播放模式：Random
- 覆盖点：BGM Bus、Loop Metadata、Proxy Asset
- 源 WAV：UIMvmt_WHOOSH POSITIVE-Flipster_B00M_CUDS.wav
- 说明：测试 WAV 包不含真实音乐素材，此事件使用 whoosh 代理素材，仅用于 BGM 总线、Loop 元数据和资源路径契约验证。

## 7. 开发对接要求

开发侧消费本样板工程时，至少需要做到：

1. 以 AudioData.json 作为唯一真源建立事件索引与总线索引。
2. 通过 EventId 精确找到事件，并读取 Bus、PlayMode、Clips 与各行为参数。
3. 通过 AssetKey + RuntimeAudioFormat 拼接运行时资源路径，而不是依赖 SourcePath。
4. 读取 BusConfigs 还原父子路由、初始音量和静音状态。
5. 对 Random、Sequence、Combo、Cooldown、MaxInstances 按字段语义执行。
6. 把 Trim 和 Loop 字段至少当作元数据保留到运行时对象，而不是在消费阶段丢弃。

## 8. 建议的开发验收点

1. UI_Click_RandomWeighted 连续触发时，应按权重离散随机，并避免立即重复。
2. UI_Confirm_Sequence 应按固定顺序轮转四个片段。
3. UI_Zap_Combo 在连续触发窗口内应递增 Combo 音高，超时后重置。
4. UI_Deny_Cooldown 在冷却窗口内应拒绝新触发。
5. UI_Whoosh_RejectNew 与 UI_Whoosh_StopOldest 应体现不同的并发上限策略。
6. UI_Popup_TrimLoop_Metadata 与 BGM_Menu_ProxyLoop 应保留 Trim / Loop 元数据。
7. 所有事件的 Clip.AssetKey 都应能在 AudioManifest.json 找到对应条目。

## 9. 已知说明

- BGM_Menu_ProxyLoop 使用代理素材，因为测试 WAV 包不含真实音乐资源。
- 当前文档针对运行时数据对接，不要求你在此轮做 Unity 场景联调。
- 全链路检查报告可作为本次交付的机器验证附件。
