AudioForge Unity 端对接开发文档

> 本文档是当前仓库面向 Unity 程序同学的唯一主对接文档。
> 之后涉及 SDK 对接、运行时契约、接入步骤、联调边界和验收标准的更新，优先维护本文档；其他文档仅保留概述、背景或验证补充，不再承载并行版本的详细对接说明。

> 当前文档同步日期：2026-05-14。
> 当前工具版本：AudioForge 0.09.0。

0.1 版本增量

- 2026-05-14 0.09.0 契约更新：导出契约已升级为 `SchemaVersion = 3`，顶层正式输出 `AudioObjects`，事件只保留动作层字段和 `AudioId`，不再导出嵌套 `Audio` 或扁平镜像字段。
- 2026-05-14 0.09.0 运行时更新：Unity runtime、JSON 适配器与全链路检查已统一改为直接消费 `AudioObjects + Events[AudioId]`；缺失 `AudioId` 或缺失目标 `AudioObject` 会被视为契约错误。
- 2026-05-14 0.09.0 工作流更新：编辑器当前已把 Audio 树升级为一等对象面，源音频树引用统计切到“引用 Audio 数”，外部导入规则收口为事件树 / Audio 树 / 源音频树三条路径。
- 2026-05-13 phase3 对接补充：State / Switch 当前支持子项级 child effects，导出会写出 `StateEffects` / `SwitchEffects`，Unity runtime 与 validation 已同步消费。
- 2026-05-13 phase3 体验补充：工具端现已提供 GameSync 工作区、试听中心 GameSync 控件和 transport 风格 RTPC 调参条；这些属于 authoring / preview 层增强，但其底层字段已经进入当前运行时契约。
- 2026-05-12 0.07.0 交付更新：包内文档与仓库主文档都新增了“一期到当前变化总览”，Unity 对接时可以先快速判断本次交付相对一期新增了什么。
- 2026-05-12 0.07.0 对接补充：对象浏览器已升级为“总线树 / 源音频树 / 事件树”三分页，绑定编辑入口收口为事件树 bindings 弹窗；这些变化仍属于编辑器工作流，不新增 Unity 运行时字段。
- 2026-05-12 0.07.0 对接补充：工程设置新增“根据事件命名智能分配总线”开关；它只影响工具端新建/导入事件时的默认总线，不要求 Unity 侧消费新字段。
- 2026-05-12 对接补充：`PlayMode` 已正式纳入 `OneShot`；Unity 侧无需新增 editor-only 字段，只需继续消费导出后的有效 Clip 集合即可。
- 2026-05-12 对接补充：事件树 bindings 弹窗、`Enabled` / `Active` 状态、对象浏览器三分页、拖拽追加反馈与 OneShot 图标均属于编辑器侧交互演进；当前不会新增 `AudioData.json` 字段，也不要求 Unity SDK 改代码。
- 2026-05-11 维护更新：主窗口、分离工程浏览器、设置窗以及各工作区命名 splitter 的布局与大小已统一持久化；属于桌面工具体验增强，不影响 Unity 运行时契约。
- AudioForge 0.06.2 优化：最近试听侧栏卡片收口为更明确的 transport card，标题、状态、控制按钮和响度摘要层级更清晰；Unity 运行时契约不变。
- AudioForge 0.06.2 优化：最近试听按钮进一步放大，并新增播放中、暂停、可试听和可重播状态徽标；Unity 侧无需消费新增字段。
- AudioForge 0.06.2 修复：最近试听卡片与响度监视器摘要标签已拆开，属于桌面工具视图层修复；Unity 侧可继续沿用现有 SDK 代码。
- AudioForge 0.06.1 优化：欢迎页进一步收敛为任务型首页，保留新建工程、打开工程以及直达事件设计、资源整理、Bus 混音台和结果中心的入口；Unity 运行时契约不变。
- AudioForge 0.06.1 优化：结果坞改为默认紧凑、按需展开，工作区重复说明和重复状态继续收口；Unity 侧无需消费新增字段。
- AudioForge 0.06.1 补充：主文档、验证说明和 smoke 报告已刷新到最新 76 项测试基线；Unity 侧可继续沿用现有 SDK 代码。
- 2026-05-08 维护更新：工具端构建改为后台执行，并新增运行期诊断日志与逐资源构建日志，主要用于修复大批量导出时的卡死定位问题；Unity 运行时契约不变。
- 2026-05-08 维护更新：对“源格式与目标格式相同且无 Trim / Fade 处理”的音频资源，导出阶段改为直接复制，不再重复重编码；这会影响未来重新导出的音频文件生成路径，但不要求 Unity 侧改代码。
- AudioForge 0.05 新增：构建交付页支持全量构建、增量构建、选中构建三种范围，并提供构建计划预览与即时构建反馈。
- AudioForge 0.05 新增：导出器会基于上次成功导出结果复用未变化资源，仅重建脏资源；`AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 仍保持全量刷新，因此 Unity 运行时契约不变。
- AudioForge 0.05 新增：`AudioManifest.json` 为每个资源写出 `BuildFingerprint`，`BuildReport.json` 写出 `BuildPlan`（含 `RequestedScope`、`EffectiveScope`、`SelectionLabel`、`RebuiltAssetKeys`、`ReusedAssetKeys` 等字段），便于大工程联调、CI 和差异审计。
- AudioForge 0.04 新增：片段波形编辑台、波形缩放/游标/聚焦选区操作、片段淡入 `FadeInMs`、片段淡出 `FadeOutMs`。
- AudioForge 0.04 新增：导出阶段会把 `TrimStartMs`、`TrimEndMs`、`FadeInMs`、`FadeOutMs` 直接烘焙进导出的运行时音频文件，而不只是停留在编辑器侧试听。
- AudioForge 0.04 新增：`AudioData.json` 与 `AudioManifest.json` 会写出 `FadeInMs`、`FadeOutMs`，用于调试、审计和后续 Unity 端扩展消费。
- AudioForge 0.04 更新：Unity 参考运行时已显式读取 `FadeInMs`、`FadeOutMs`，并在调试记录中展示 Clip 的 Trim / Fade / Loop 元数据；当前仍未将 Fade 作为独立运行时 DSP 规则再次执行。

0.2 相对第一期必须关注的变化

- 当前相对第一期，运行时层真正需要 Unity 程序关注的不再只有 `OneShot`；当前还新增了 `SchemaVersion = 3`、项目级 `AudioObjects`、项目级 Game Sync 定义、Audio/总线级 Game Sync 绑定、emitter context 与 child effects。
- 编辑器层新增了对象浏览器三分页、事件树 bindings 弹窗、`Enabled` / `Active` 切换、拖拽追加反馈、OneShot 图标和智能总线分配工程设置；这些 editor-only 状态本身仍不会原样写进导出，但其过滤后的结果与 GameSync 绑定会进入当前 `AudioData.json`。
- 如果 Unity 同学仍按一期心智理解 SDK，可以先读 `docs/UnitySDK一期到当前变化总览.md`；拿到交付包时，包内对应入口是 `Docs/一期对比变化总览.md`。
- 当前仓库附带的 Unity 参考运行时代码已经能够消费新版导出结果；如果项目内是自研 runtime，则需要同步补齐 v2 解析、Game Sync API 与 emitter 作用域。

0.3 当前 GameSync 口径

- 当前仓库主线已经支持 `SchemaVersion = 3`，运行时主契约不再只有 `BusConfigs` 与 `Events`，而是额外包含项目级 `AudioObjects`、`GameParameters`、`StateGroups`、`SwitchGroups` 和 Audio/总线级 Game Sync 区块。
- 参考 runtime 已实现 `HasGameParameter`、`HasStateGroup`、`HasSwitchGroup`、`RegisterEmitter`、`SetState`、`SetSwitch`、`SetGlobalGameParameter`、`SetGameParameter` 及对应播放求值路径。
- 若你当前接入的仍是旧版 phase2 或 phase3-schema2 导出物，请继续沿用历史 SDK 包；当前最新包与本文档默认以 v3 口径实现，不再承担旧 schema 回退。

0. 当前状态

- 当前工具端适用目标：UI / SFX / BGM 为主、事件驱动为主、接受轻量 SDK 的手游休闲项目。
- 最近一次仓库内完整发布验证结果：`pytest` 112 项通过；真实 WAV 烟雾工程 PASS；全链路检查 4/4 通过；smoke 报告与签收摘要已在 2026-05-12 刷新。
- 本轮 phase3 聚焦回归额外验证了 25 项 Python 测试，并完成 Unity package / validation 关键 C# 文件诊断无错误。
- 当前参考运行时定位：开发参考实现，可直接用于空项目联调与生产版 SDK 的起步实现，不等于最终生产版音频系统。

1. 文档定位

本文档面向 Unity 程序开发人员，定义 AudioForge 当前导出结果的消费方式、运行时建议架构、行为语义、接入步骤、联调边界与验收标准。

如果你是第一次接手该 SDK，推荐阅读顺序固定为：

1. 先通读本文档，明确边界、输入输出和最小验收标准。
2. 再阅读 `CHANGELOG.md`，确认当前版本相对上一版到底改了什么。
3. 再阅读 `unity_package/README.md`，明确独立包与验证镜像的维护边界。
4. 再阅读 `unity_package/Docs/README.md` 和 `unity_package/Docs/QuickStart.md`，按交付包视角完成最小接入。
5. 然后阅读 `unity_validation/README.md`，按空项目验证步骤跑通最小链路。
6. 最后根据需要查阅 `开发文档.md` 了解工具端背景与产品边界。

本期交接的核心原则只有一条：Unity 端只依赖导出产物，不依赖工具源码，不读取 `.afproj`，也不要求在 Unity 项目中嵌入 Python 运行环境。

2. 你会收到什么

第一期建议交接以下目录和文件：

- `<你的实际导出目录>/AudioData.json`
- `<你的实际导出目录>/AudioManifest.json`
- `<你的实际导出目录>/BuildReport.json`
- `<你的实际导出目录>/AudioEventID.cs`
- `<你的实际导出目录>/Assets/**`
- `unity_package/Assets/AudioForgeRuntime/**`
- `unity_validation/README.md`
- `unity_package/README.md`

如果希望像 Wwise 集成包一样直接给 Unity 程序一个版本化压缩包，可直接执行：

`python tools/package_unity_integration_package.py`

该命令会在 `dist/` 下生成版本化目录包和 zip。

2026-05-14 版本说明：当前建议重新生成 Unity SDK 包。主要原因已经不只是文档更新，而是 runtime 代码本体已同步进入 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]`、Game Sync API、emitter context、child effects smoke，以及正式的 Event / AudioObject 职责拆层。重新打包后的目录名为 `dist/AudioForgeUnityPackage-0.09.0/`。

自 2026-05-07 起，生成后的 SDK 包会统一带上以下交接层内容：

- `Docs/README.md` 与 `Docs/QuickStart.md`：包内阅读入口与最短接入路径。
- `Docs/Canonical/`：从仓库主文档同步进包内的 canonical 对接文档副本。
- `Examples/`：带注释的示范代码文件，方便 Unity 程序按需复制和改造。
- `Verification/`：当前机器验证报告与签收摘要，便于交接时说明“这包是怎么验过的”。

推荐直接交给 Unity 程序同学的不是裸目录，而是：

- `dist/AudioForgeUnityPackage-<version>/`
- `dist/AudioForgeUnityPackage-<version>.zip`

建议同时附带以下验证产物给 Unity 程序：

- `reports/internal_release_smoke/release_signoff.md`
- `reports/internal_release_smoke/checks/full_chain_report.md`

推荐放入 Unity 工程后的目标结构：

```text
Assets/
	AudioForgeRuntime/
		Scripts/
	StreamingAssets/
		AudioForge/
			AudioData.json
			AudioManifest.json
			Assets/
				...导出的音频资源...
```

当前标准 SDK 交付包结构建议理解为：

```text
AudioForgeUnityPackage-<version>/
	Assets/
		AudioForgeRuntime/
	Docs/
		README.md
		QuickStart.md
		Canonical/
	Examples/
	Verification/
	README.md
```

当前仓库根目录 `Export/` 样例里，默认可直接拿来验证的事件枚举已同步为：`sfx_level_check_02`、`sfx_level_check_03`、`sfx_tile_hint_02`、`sfx_tile_undo_02`、`sfx_tile_undo_03`。当前 Unity 运行时代码统一维护在 `unity_package`，`unity_validation` 里的 `AudioForgeBootstrap` / `AudioForgeEventPlayer` 镜像也已对齐到 `sfx_level_check_02`，避免空项目验证仍指向旧样例事件。

如果你只是要拿仓库里的最新机器验证样例做联调，优先使用 `reports/internal_release_smoke/export/` 下的导出物，而不是把仓库根目录 `Export/` 误当成唯一基线来源。

如果 Unity 同学已经拿到了之前生成的包，旧代码通常仍可继续对接；但建议至少同步阅读 0.09.0 的对接文档和一期对比总览，确认 Event / AudioObject 边界、`AudioId` 引用关系、`OneShot` 语义和有效 Clip 集合理解一致。

3. 工具端与 Unity 端边界

3.1 工具端负责

- 事件、片段、总线与参数配置。
- `.afproj` 工程保存与读取。
- 静态校验。
- 导出 `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 和运行时音频资源。
- 提供本地试听与响度分析，帮助音频同学确认配置。
- 自 AudioForge 0.04 起，片段裁剪与淡入淡出会在导出时直接烘焙进运行时音频资源。
- 当前工具端的所有音高相关参数，包括基础音高、随机音高和 Combo 连击步进，已统一按保时长变调提供参考听感；该行为当前不写入额外导出字段。
- 当前工具端 UI 已提供问题中心、Bus 视图状态、响度报告、批量导入模板、恢复布局、事件树多选、批量改 Bus 和事件搜索定位等辅助能力，但这些都不影响导出契约本身。

3.2 Unity 端负责

- 加载并解析导出数据。
- 根据事件 ID 执行播放。
- 管理实例并发、冷却、Combo 状态、Sequence 游标和总线状态。
- 将逻辑音量、音高换算为 Unity 可执行参数。
- 决定资源加载方案，例如 `StreamingAssets`、Addressables 或 AssetBundle。

3.3 明确禁止

- 不读取 `.afproj` 作为运行时输入。
- 不从 Python 工具源码反射业务逻辑。
- 不在 Unity 业务代码里另外维护一套与导出数据脱节的事件规则。

4. 最小运行时模块建议

建议 Unity 侧至少拆分为以下模块：

- `AudioForgeDatabase`：负责读取 `AudioData.json` 并构建事件索引。
- `AudioForgeRuntime`：对外提供统一 API，是游戏代码的唯一入口。
- `AudioForgeVoiceManager`：负责冷却、并发限制、Sequence/Combo 状态、活动实例管理；在休闲游戏项目里可以把它当作轻量触发限制器，而不是完整的语音管理系统。
- `IAudioForgeResourceProvider`：负责根据 `AssetKey` 加载 `AudioClip`。
- `AudioForgeBusState`：维护总线音量、静音和扩展状态。

当前仓库自带的 `unity_package/Assets/AudioForgeRuntime/Scripts/AudioForgeRuntime.cs` 已补充一套参考实现：当 `useReferenceTimePreservingPitch = true` 时，会优先对运行时加载到的 `AudioClip` 生成保时长变调版本，并缓存后再交给 `AudioSource` 播放。对应算法入口位于 `AudioForgeTimePreservingPitchProcessor.cs`，可直接作为 Unity 端开发的参考起点。
同时，仓库中已经给出完整参考脚本分工：`IAudioForgeResourceProvider.cs` 与 `AudioForgeStreamingAssetsProvider.cs` 负责资源加载抽象，`AudioForgeEventPlayer.cs` 与 `AudioForgeBootstrap.cs` 负责场景触发与验证引导，`AudioForgeRuntimeDebugPanel.cs` 用于联调观察运行时状态。

自 2026-05-07 起，`AudioForgeRuntime` 还提供了 `SetResourceProvider(IAudioForgeResourceProvider resourceProvider)`。如果项目要把资源加载切到 `Resources`、Addressables、AssetBundle 或自建下载层，建议在第一次 `Initialize()` 之前完成注入，而不是直接改动播放主流程。
当前参考调试面板除了基础事件/总线状态外，还会展示最近事件触发记录、总音高、是否走保时长变调、处理后 Clip 缓存是否命中、当前资源提供器类型、运行时音频格式，以及最近总线状态变化历史，便于 Unity 开发直接定位行为差异。

5. 推荐对外 API

最小可用接口建议如下：

- `Initialize()`
- `bool HasEvent(string eventId)`
- `bool HasGameParameter(string name)`
- `bool HasStateGroup(string groupName)`
- `bool HasSwitchGroup(string groupName)`
- `AudioForgeEmitterHandle RegisterEmitter(GameObject gameObject)`
- `void UnregisterEmitter(AudioForgeEmitterHandle emitter)`
- `void PlayEvent(string eventId)`
- `void PlayEvent(string eventId, AudioSource overrideSource)`
- `void PlayEvent(string eventId, AudioForgeEmitterHandle emitter)`
- `void PlayEvent(string eventId, AudioForgeEmitterHandle emitter, AudioSource overrideSource, float localEventVolumeDbOffset)`
- `void StopEvent(string eventId)`
- `void StopBus(string busName)`
- `void SetBusVolume(string busName, float linearVolume)`
- `void SetBusMuted(string busName, bool isMuted)`
- `void SetGlobalGameParameter(string name, float value)`
- `void SetGameParameter(string name, float value, AudioForgeEmitterHandle emitter)`
- `void SetState(string groupName, string stateName)`
- `void SetSwitch(string groupName, string switchName, AudioForgeEmitterHandle emitter)`
- `void SetUnityEventVolumeOffsetDb(string eventId, float volumeDbOffset)`
- `void SetResourceProvider(IAudioForgeResourceProvider resourceProvider)`

如果项目需要更完整接入，建议再预留：

- `bool TryPlayEvent(string eventId, out AudioForgePlayResult result)`
- `float GetBusVolume(string busName)`
- `bool IsBusMuted(string busName)`
- `int GetActiveVoiceCount(string eventId)`
- `List<string> GetEventIds()`
- `List<string> GetBusNames()`
- `int GetProcessedClipCacheCount()`
- `List<AudioForgeDebugEventRecord> GetRecentDebugEventRecords()`
- `List<AudioForgeDebugBusRecord> GetRecentDebugBusRecords()`

6. 导出产物说明

6.1 AudioData.json

运行时主数据文件。Unity 端必须以它为唯一真源建立事件索引、总线索引和项目级设置。

建议至少解析：

- 项目级默认总线和运行时音频格式。
- `SchemaVersion`。
- 总线列表以及可选的 `BusConfigs` 初始状态。
- `GameParameters`、`StateGroups`、`SwitchGroups` 顶层定义。
- 事件列表，以及事件顶层 `MaxInstances`、`CooldownSeconds`、`StealPolicy`。
- 每个事件下的 `Audio` 子对象，以及 `Audio.Clips`。
- `Audio.DefaultClipIds`、`Audio.RtpcBindings`、`Audio.StateOverrides`、`Audio.SwitchVariants`。
- 总线级 `RtpcBindings`、`StateOverrides`。
- 各类播放行为参数。

6.2 AudioManifest.json

导出资源清单。主要用于资源完整性校验、打包比对和排查资源缺失，不应替代 `AudioData.json` 作为业务播放主数据。

自 AudioForge 0.05 起，每个资源条目会额外写出 `BuildFingerprint`。该字段用于工具端区分“资源内容真的变了，需要重建音频”与“只有引用关系或导出审计信息变化”，便于增量构建和 CI 审计；Unity 运行时不必依赖它建立播放逻辑。

工具端自 AudioForge 0.05 起还会额外输出 `BuildReport.json`。它不是运行时必需文件，但建议在联调、CI 或大工程接入时一并保留，用于解释本次构建的 `RequestedScope`、`EffectiveScope`、`SelectionLabel`、重建资源数、复用资源数，以及是否因选区外脏资源自动升级为增量构建。

6.3 AudioEventID.cs

可选的事件常量文件。用于减少业务层硬编码字符串，但不应让 SDK 强依赖其存在。

6.4 Assets/

运行时音频资源目录。Unity 端建议通过 `AssetKey + RuntimeAudioFormat` 定位文件，而不是依赖源文件路径。

补充说明：自 AudioForge 0.05 起，工具端支持增量构建和选中构建，但这只影响导出阶段如何生成和复用音频资源，不改变 Unity 端收到的目录结构、路径规则或运行时消费方式。

7. 数据字段语义

7.1 Event 顶层字段

对多数休闲游戏项目，建议默认只使用 `BGM`、`SFX`、`UI` 三条子总线；单源、一次性触发的短音效可以直接使用 `OneShot`，多变体音效默认仍建议走 `Random`，`Sequence` 和 `Combo` 作为按需启用的进阶玩法即可。

- `Id`：事件唯一标识，Unity 端主索引键。
- `DisplayName`：仅编辑器展示，不参与运行时查找。
- `CooldownSeconds`：事件冷却时间。
- `MaxInstances`：活动实例上限，`0` 表示无限制。
- `StealPolicy`：达到上限时的处理策略；第一期实际只要求 `RejectNew` 和 `StopOldest`。
- `AudioId`：事件引用的声音层对象标识；`SchemaVersion = 3` 下 Unity 端应通过 `AudioId` 到顶层 `AudioObjects` 建立主真源映射，而不是再从事件对象内取声音配置。

7.2 AudioObject 字段

- `Bus`：所属总线。
- `PlayMode`：`OneShot`、`Random`、`Sequence`、`Combo`。
- `AvoidImmediateRepeat`：若候选 Clip 大于 1，优先排除上次命中的 Clip。
- `VolumeDb`：基础音量，单位 dB。
- `VolumeRandMinDb`、`VolumeRandMaxDb`：随机音量范围。
- `PitchCents`：基础音高，单位 cents。
- `PitchRandMinCents`、`PitchRandMaxCents`：随机音高范围。
- `ComboPitchStepCents`：Combo 每步增加的音高。当前工具端编辑器按“半音”为单位设置，导出时仍以 cents 表达，因此该值应视为 `100` 的整数倍。
- `ComboResetSeconds`：Combo 状态重置时间。
- `ComboMaxStep`：Combo 最大步数，`0` 可视为无限。
- `LoadPolicy`：字段当前保留，但第一期工具与 Unity 验证运行时固定按 `OnDemand` 工作。

7.3 Clip 字段

- `ClipId`：事件内唯一标识。
- `AssetKey`：运行时资源键。
- `Weight`：`Random` 模式下的离散权重，不是百分比。
- `TrimStartMs`、`TrimEndMs`：自 AudioForge 0.04 起，工具端导出时会把裁剪结果直接烘焙进运行时音频文件；字段仍保留在 `AudioData.json` 和 `AudioManifest.json` 中，供 Unity 端调试、校验或后续扩展消费。
- `FadeInMs`、`FadeOutMs`：自 AudioForge 0.04 起新增。工具端导出时会把淡入淡出结果直接烘焙进运行时音频文件；字段同时写入 `AudioData.json` 和 `AudioManifest.json`。当前 Unity 参考运行时已显式读取，并在调试记录中可见，但不会再对已导出的音频做第二次独立 Fade 处理。
- `LoopStartMs`、`LoopEndMs`：为后续完整 Loop 支持预留，第一期不开放编辑，也不要求运行时实现样本级 Loop 点。

7.2.1 Unity 当前消费边界

- 如果 Unity 直接播放 AudioForge 导出的运行时音频文件，那么裁剪和淡入淡出的听感已经同步，无需再在 Unity 里二次执行一遍。
- 当前参考运行时会把 `TrimStartMs`、`TrimEndMs`、`FadeInMs`、`FadeOutMs`、`LoopStartMs`、`LoopEndMs` 读入 `AudioForgeClipConfig`，并在调试面板中展示，便于 Unity 开发核对工具端导出结果。
- 当前参考运行时没有把 `FadeInMs`、`FadeOutMs` 用作独立运行时规则再次处理，这属于后续可选扩展，不影响导出结果落地。

7.3 BusConfig 字段

- `Name`：Bus 名称。
- `ParentBus`：父 Bus 名称；缺省时按 `Master` 处理。
- `VolumeDb`：工具端配置的初始总线音量，单位 dB。
- `IsMuted`：工具端配置的初始总线静音状态。
- `RtpcBindings`：总线级连续调制规则，当前主要驱动 Bus Volume。
- `StateOverrides`：总线级全局 State 覆盖规则。
- 若 `AudioData.json` 中同时存在 `Buses` 与 `BusConfigs`，Unity 端应优先采用 `BusConfigs` 作为初始化总线状态，再将 `Buses` 视为兼容性保底字段。

7.4 GameSync 顶层字段

- `GameParameters`：项目级连续参数定义，包含 `Name`、`DefaultValue`、`MinValue`、`MaxValue`、`Description`。
- `StateGroups`：全局离散模式定义，包含 `Name`、`DefaultState`、`States` 与 `StateEffects`。
- `SwitchGroups`：emitter 级离散分支定义，包含 `Name`、`DefaultSwitch`、`Switches`、`UseGameParameter`、`MappedGameParameter`、`Thresholds` 与 `SwitchEffects`。

7.5 Event GameSync 字段

- `DefaultClipIds`：事件默认候选 Clip 集合；当没有命中 Switch Variant 时，运行时应优先消费这组 Clip。
- `RtpcBindings`：事件级连续调制规则，当前支持 `EventVolumeDb` 与 `EventPitchCents`。
- `StateOverrides`：事件级 State 覆盖规则，可叠加音量、音高与静音。
- `SwitchVariants`：事件级 Switch 分支选片规则。

8. 行为语义要求

8.0 OneShot

- `OneShot` 表示当前事件在导出后只保留 1 个有效 Clip；Unity 侧按普通单 Clip 事件播放即可，不需要额外分支字段。
- 当前工具端会在导出前完成 `Enabled` / `Active` 过滤；Unity 运行时收到的是已经收敛后的有效 Clip 集合，而不是 editor-only 绑定状态。
- 若 `PlayMode = OneShot` 且 `Clips` 只包含 1 项，参考运行时沿用现有随机选片路径即可得到确定结果，因此当前 SDK 代码无需为 `OneShot` 再新增独立调度器。

8.1 Random

- 从当前事件的 Clip 集合中按 `Weight` 做离散随机。
- 若 `AvoidImmediateRepeat = true` 且候选数大于 1，则本次应先排除上次命中的 Clip。
- 若排除后集合为空，则回退为原始全集合。

8.2 Sequence

- 以当前配置顺序作为固定序列。
- 每次成功触发后游标前进 1。
- 到达尾部后回到 0。

8.3 Combo

- 在连续触发窗口内递增 Combo 步数。
- 当前播放音高应在基础音高上额外增加 `ComboPitchStepCents * comboStep`。
- 两次触发间隔超过 `ComboResetSeconds` 时重置为初始步数。
- `ComboMaxStep = 0` 时可视为不设上限。
- 工具端当前将基础音高、随机音高和 Combo 附加音高统一作为“保时长变调”参考听感处理，因此工具试听里所有音高变化默认都不会缩短或拉长片段长度。
- Unity 端若继续直接使用 `AudioSource.pitch = 2^{(cents / 1200)}` 处理任意音高变化，则会同时改变播放速度和片段长度；这与当前工具端试听存在已知差异，不应在联调时误判为工具导出错误。
- 若项目要求 Unity 最终听感与当前工具试听完全一致，Unity 端需要为全部音高相关参数接入独立的保时长变调实现，而不是仅依赖 `AudioSource.pitch`。
- 当前 `unity_validation` 参考运行时已经提供一条默认开启的保时长变调参考路径，可直接用于阅读、替换或重构为生产版实现。

8.4 Cooldown

- 上次成功触发到当前时间小于 `CooldownSeconds` 时，应拒绝本次触发。

8.5 Max Instances

- `MaxInstances = 0` 表示无限制。
- 达到上限后按 `StealPolicy` 决定是拒绝新实例，还是打断旧实例。
- 第一阶段至少支持 `RejectNew` 与 `StopOldest` 两种行为。

9. 运行时换算建议

9.1 音量

建议使用 $linear = 10^{(db / 20)}$ 将 dB 转换为 Unity 可直接使用的线性增益。

9.2 音高

建议使用 $pitch = 2^{(cents / 1200)}$ 将 cents 转为 Unity `AudioSource.pitch` 乘数。

补充说明：

- 上述换算在 Unity 端直接落地时，会同时影响音高与播放速度。
- 对于当前工具端试听中的所有音高相关参数，如果希望保持片段时长不变，则不能只依赖 `AudioSource.pitch`，而需要额外的保时长变调 DSP 或等价算法。
- 参考代码位置：`unity_validation/Assets/AudioForgeRuntime/Scripts/AudioForgeRuntime.cs` 和 `unity_validation/Assets/AudioForgeRuntime/Scripts/AudioForgeTimePreservingPitchProcessor.cs`。

9.3 总线

总线控制应乘到事件最终音量上，而不是回写事件导出数据。运行时建议将总线状态保存在独立表中，但初始化时应先消费 `AudioData.json` 中的 `BusConfigs`，把工具端配置的初始音量、静音和父子路由关系还原到运行时总线表，并沿 `ParentBus -> Master` 链累乘总线增益。

当前参考实现额外区分了两层 Unity 侧微调：

- 总线级微调：以线性倍率表达，叠乘在 AudioForge 导出总线基线之上。
- 事件级微调：以 dB 偏移表达，叠加在 AudioForge 导出事件基线之上。

这样可以在 Inspector 中明确区分“工具导出的原始配置”和“Unity 工程内额外做过的调整”。

9.4 事件级微调

当前参考实现已经补充两层事件级微调：

- 项目级事件偏移：由 `AudioForgeRuntime` 维护，按 `EventId` 存储，适合全局修正某个事件。
- 组件级事件偏移：由 `AudioForgeEventPlayer` 和 `AudioForgeBootstrap` 持有，适合只影响当前场景物体。

建议最终事件音量计算顺序为：

1. AudioForge 事件基线
2. Unity 项目级事件偏移
3. Unity 组件级事件偏移
4. 随机音量偏移
5. AudioForge 总线基线与 Unity 总线微调

其中两层事件偏移都采用 dB 表达，默认 `0 dB` 表示不改动导出事件基线。

当前参考 Inspector 的语义已经固定为两层：

- `导出基线`：来自 AudioForge 导出的总线音量、静音状态和父子关系，只读展示。
- `Unity 附加倍率`：Unity 工程侧的额外微调，默认值为 `1`，表示未改动导出基线。

这意味着 Unity 程序可以一眼区分“工具导出的原始配置”和“项目内额外做过的混音微调”，同时避免把 Unity 侧微调误解为 AudioForge 原始总线值。

10. 资源加载要求

- 默认路径建议为 `StreamingAssets/AudioForge/Assets/<AssetKey>.<RuntimeAudioFormat>`。
- 若项目采用 Addressables 或 AssetBundle，可将 `AssetKey` 作为逻辑键，再由资源提供器自行映射。
- SDK 不应依赖工具工程原始路径。
- 当资源缺失时，必须输出带 `eventId` 和 `assetKey` 的可读日志。

11. 初始化流程建议

建议按以下顺序初始化：

1. 加载 `AudioData.json`。
2. 解析项目设置、事件和总线。
3. 构建事件字典与总线状态表。
4. 初始化资源提供器。
5. 对外暴露可用状态。

建议在初始化完成后额外记录以下调试信息，便于和当前仓库的参考运行时对齐：

- 已注册事件数
- 已注册总线数
- 当前资源提供器类型
- 是否启用保时长变调参考路径
- 最近初始化错误或警告

如果初始化失败，建议让 `AudioForgeRuntime` 进入明确的不可用状态，并记录失败原因，而不是静默继续。

12. 联调建议

接 Unity 端时，建议先只完成最小链路：

1. 能读取 `AudioData.json`。
2. 能按 `eventId` 找到事件。
3. 能根据 `AssetKey` 加载导出音频。
4. 能完成 `OneShot`、`Random`、`Sequence`、`Combo`、`Cooldown`、`MaxInstances` 基础行为。
5. 能处理总线静音与音量。

Combo 联调时请额外确认以下边界：

1. `ComboPitchStepCents` 已约束为半音档位，对接时应按 `100` cents 的整数倍处理。
2. 当前导出数据中没有“保时长变调开关”一类的新字段；工具端试听中的保时长音高仅是现阶段参考听感。
3. 若 Unity 端暂未实现保时长变调，则应将“任意音高变化导致片段长度变化”记录为已知实现差异，而不是数据契约错误。

随后再接：

1. Addressables 或 AssetBundle。
2. Unity AudioMixer。
3. 3D 音频定位。
4. 运行时调试面板。

13. 错误处理要求

严重错误：

- `AudioData.json` 缺失。
- `AudioData.json` 解析失败。
- 运行时关键字段缺失导致数据库无法建立。

可恢复错误：

- 某个事件不存在。
- 某个 `AssetKey` 对应资源不存在。
- 某个事件配置非法但不影响其他事件。

建议日志至少包含：

- `eventId`
- `clipId`
- `assetKey`
- `busName`
- 错误阶段，例如 `initialize`、`lookup`、`load`、`play`

14. 最小验收标准

- 能在 Unity 空项目中成功初始化。
- 能根据事件 ID 播放导出音频。
- `OneShot`、`Random`、`Sequence`、`Combo`、`Cooldown`、`MaxInstances` 行为与工具定义一致。
- 总线音量和静音控制生效。
- 资源丢失和事件缺失时有可读日志。
- 能通过 `unity_validation/README.md` 中的基础验证流程。

建议额外记录一份项目内联调签收，至少包含：

- 当前接入的资源提供方式（StreamingAssets / Addressables / AssetBundle）
- 是否启用保时长变调参考路径
- `OneShot` / `Random` / `Sequence` / `Combo` / `Cooldown` / `MaxInstances` 的抽查结果
- 当前未覆盖的能力边界

14.1 二期改动与 SDK 影响标注

- 需要同步 SDK 文档但若直接采用仓库自带 runtime 通常无需项目额外改代码的内容：`OneShot` 播放模式、导出前有效 binding 过滤语义、GameSync 工作区、试听中心 GameSync 控件、事件树 OneShot 图标。
- 当前明确不进入 SDK 契约的二期内容：对象浏览器三分页、bindings 弹窗、`Enabled` / `Active` 原始状态、拖拽追加反馈、设计页绑定摘要区。
- 只有当未来决定把 `Enabled` / `Active`、ShuffleBag、Loop 或其他 editor-only 状态直接写入 `AudioData.json` 时，才需要升级 SchemaVersion 并同步修改 Unity SDK 解析与运行时行为。

14.2 三期后续扩展路线

- RTPC：当前已支持全局值、emitter 局部值、事件音量、事件音高和 Bus 音量；后续重点是 active voice 持续重算。
- State：当前已支持全局模式切换、Event / Bus 属性覆盖和 State child effects；后续重点是过渡时间与插值。
- Switch：当前已支持 emitter 级分支选择、RTPC 映射阈值、事件变体选片和 Switch child effects；后续重点是更复杂的容器层级。
- 当前包已经正式切到 `SchemaVersion = 3` 单一路径；如果项目内仍维护自研 runtime，请优先同步 `AudioObjects + Events[AudioId]` 解析链，而不是继续依赖旧 schema 兼容。
- 对当前 0.07.0 包而言，这一节不再只是路线图，而是说明“已落地能力之外还剩什么没有做完”。

补充说明：若 Unity 端本阶段仍采用原生 `AudioSource.pitch` 执行音高变化，则“音高变化是否保时长”不计入第一期最小验收失败项，但需在联调记录中明确标注。

15. 本期未要求实现的内容

- 样本级 Trim 和 Loop 点精确执行。
- Unity AudioMixer 深度集成。
- Addressables / AssetBundle 正式生产化接入。
- 更复杂的优先级、Duck、Side Chain、Profiler 和可视化调试工具。

16. 建议交接方式

把本文件、`开发文档.md`、`unity_validation/README.md` 和本次实际导出目录一起交给 Unity 程序同学。Unity 端先按本文件完成最小 SDK，再用空项目验证样例做联调回归。

建议按以下顺序交接：

1. 先交本文件和 `开发文档.md`，让 Unity 程序对边界和字段语义达成一致。
2. 再交 `unity_validation/Assets/AudioForgeRuntime` 与 `unity_validation/README.md`，在空项目里验证最小运行时链路。
3. 最后交 `reports/internal_release_smoke/release_signoff.md` 与 `reports/internal_release_smoke/checks/full_chain_report.md`，作为当前工具端基线已验证的客观记录。