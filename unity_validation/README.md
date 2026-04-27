# Unity Empty Project Validation

> 本文档只负责说明 Unity 空项目验证步骤。
> SDK 对接边界、运行时契约、字段语义、接入建议与验收标准，统一以 `docs/UnitySDK对接规范.md` 为准；后续不在本文档中维护并行版本的详细对接说明。

## 当前验证状态

- 当前仓库内最近一次基线验证结果：`pytest` 59 项通过。
- 真实 WAV 烟雾工程验证结果：PASS。
- 最近一次全链路检查结果：4/4 通过，覆盖 `pytest`、导出 bundle、运行时契约、Unity 验证包完整性。

这些结果说明当前仓库已经具备“工具端可导出、契约可检查、验证包可交接”的最低交付基线，但不代表已经完成正式项目内的最终联调。

当前仓库没有检测到本机可用的 Unity 或 Unity Hub 命令行入口，因此无法在此环境里自动创建真实 Unity 空项目。

已经准备好的内容位于本目录。你只需要在 Unity Hub 里手动新建一个空项目，再把 `Assets/AudioForgeRuntime` 目录整体复制进去，就可以开始验证。

当前 `AudioForgeRuntime` 里已经附带一套保时长变调参考实现，默认由 `AudioForgeRuntime` 组件上的 `Use Reference Time Preserving Pitch` 开关控制，开启后会优先使用参考代码生成保时长音高版本的 `AudioClip` 再播放。

## 参考脚本结构

复制进去后的 `Assets/AudioForgeRuntime` 主要包含这些脚本：

1. `AudioForgeRuntime.cs`：运行时主入口，负责初始化、事件播放、总线控制、声部管理和保时长变调参考链路。
2. `AudioForgeStreamingAssetsProvider.cs`：默认资源提供器，负责从 `StreamingAssets/AudioForge/Assets` 加载导出音频。
3. `IAudioForgeResourceProvider.cs`：资源提供器抽象接口，生产项目可替换成 Addressables 或 AssetBundle 版本。
4. `AudioForgeTimePreservingPitchProcessor.cs`：保时长变调参考实现，用于把工具端的参考听感接到 Unity 运行时。
5. `AudioForgeEventPlayer.cs`：把 Start、Enable、按键等输入转换为一次事件触发。
6. `AudioForgeBootstrap.cs`：空项目一键引导组件，方便快速搭建验证场景。
7. `AudioForgeRuntimeDebugPanel.cs`：轻量调试面板，方便直接观察事件、总线和活动声部状态。
8. `Editor/AudioForgeValidationRunner.cs`：一键跑当前场景验证并输出报告。
9. `Editor/AudioForgeMissingScriptCleaner.cs`：清理场景里残留的 Missing Script。

## 目标

这套验证流程要确认四件事：

1. AudioForge 导出的 `AudioData.json` 能被 Unity 读取。
2. 导出的 OGG 资源能从 `StreamingAssets` 正常加载。
3. 最小 Runtime 能按事件名触发播放。
4. Random、Sequence、Combo、Cooldown、MaxInstances 这些行为至少在空项目里能走通基础链路。

建议在开始 Unity 联调前，先完成仓库内这两条本地验证命令：

1. `python -m pytest`
2. `python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"`

## 准备导出物

先在 AudioForge 里准备一个测试工程，建议至少包含：

1. 一个 `Random` 事件，例如 `sfx_level_check_02`。
2. 一个 `Sequence` 事件，例如 `UI_Click_Step`。
3. 一个 `Combo` 事件，例如 `BTL_Combo_Hit`。
4. 至少一个设置了 `TrimStartMs` 和 `TrimEndMs` 的 Clip。
5. 项目设置里使用：
	`Source Format = wav`
	`Runtime Format = ogg`

然后执行 Build，确认导出目录里至少有这些文件：

1. `AudioData.json`
2. `AudioManifest.json`
3. `AudioEventID.cs`
4. `Assets/` 目录，里面是导出的 `.ogg` 音频

## 第一步：创建 Unity 空项目

1. 打开 Unity Hub。
2. 点击右上角 `New project`。
3. 模板选择 `3D Core` 或 `Empty` 都可以。
4. 项目名称建议填写 `AudioForgeValidation`。
5. 选一个空目录作为项目位置。
6. 点击 `Create project`。

## 第二步：导入 Runtime 脚本

1. 打开这个仓库下的 `unity_validation/Assets/AudioForgeRuntime`。
2. 将整个 `AudioForgeRuntime` 文件夹复制到 Unity 项目的 `Assets` 目录里。
3. 回到 Unity，等待脚本自动刷新和编译。
4. 编译完成后，Project 面板里应能看到：
	`Assets/AudioForgeRuntime/Scripts/...`

## 第三步：放入导出数据和音频

1. 在 Unity 项目的 `Assets` 下新建 `StreamingAssets` 文件夹。如果已经有就跳过。
2. 在 `StreamingAssets` 下新建 `AudioForge` 文件夹。
3. 将 AudioForge 导出的 `AudioData.json` 复制到：
	`Assets/StreamingAssets/AudioForge/AudioData.json`
4. 将导出的整个 `Assets` 音频目录复制到：
	`Assets/StreamingAssets/AudioForge/Assets`

完成后目录结构应类似：

```text
Assets/
  AudioForgeRuntime/
	 Scripts/
  StreamingAssets/
	 AudioForge/
		AudioData.json
		Assets/
		  ui/
			 click_01.ogg
		  battle/
			 hit_01.ogg
```

## 第四步：搭一个最小测试场景

1. 在 Hierarchy 里新建一个空物体。
2. 把它命名为 `AudioForgeBootstrap`。
3. 给这个物体挂上 `AudioForgeBootstrap` 组件。
4. 如果你想直接观察运行时状态，再额外挂上 `AudioForgeRuntimeDebugPanel` 组件。
4. 在 Inspector 中设置：
	`Event Id = sfx_level_check_02`
	`Auto Play On Start = true`
	`Trigger Key = Space`
5. 保存当前场景，例如保存为 `Assets/Scenes/Validation.unity`。

## 第五步：运行首次验证

1. 点击 Play 进入运行模式。
2. 如果 `Auto Play On Start` 开启，游戏启动后会尝试自动播放 `sfx_level_check_02`。
3. 如果没有自动播放，按一次空格键，Runtime 会再次尝试触发当前事件。
4. 打开 Console，看是否有以下情况：
	没有报错：表示 JSON 路径、音频路径和脚本编译都正常。
	有 `AudioData.json not found`：说明 `StreamingAssets/AudioForge` 目录放错了。
	有 `file not found` 或 `request error`：说明导出的音频目录结构或扩展名不匹配。

## 第六步：验证不同行为

### 验证 Random

1. 把 `Event Id` 改成一个配置了多个 Clip 的 Random 事件。
2. 连续多次按空格。
3. 观察是否会命中不同 Clip。
4. 如果打开了 `AvoidImmediateRepeat`，重点观察是否避免连续命中同一条。

### 验证 Sequence

1. 把 `Event Id` 改成一个 `Sequence` 事件。
2. 连续多次按空格。
3. 观察播放是否按固定顺序轮转，而不是随机切换。

### 验证 Combo

1. 把 `Event Id` 改成一个 `Combo` 事件。
2. 快速连续按空格。
3. 观察音高是否随着连续触发逐步升高。
4. 在 `Use Reference Time Preserving Pitch` 开启时，额外观察片段时长是否基本保持不变，而不只是音高升高。
5. 停顿超过 `ComboResetSeconds` 之后再次触发，观察是否回到基础步数。

### 观察运行时状态

1. 如果场景里挂了 `AudioForgeRuntimeDebugPanel`，运行后可直接看到已注册事件数、总线数、保时长变调开关状态、当前运行时音频格式、当前资源提供器类型，以及处理后 Clip 缓存数量。
2. 面板里还会显示最近事件触发记录：包含 `EventId`、触发结果、命中 `ClipId`、总音高 cents、Combo 步数、是否走保时长路径、缓存是否命中，以及被拒绝时的原因。
3. 面板里会显示最近总线状态变化记录：包含总线名、操作类型、音量值和静音状态。
4. 每个事件当前活动声部数量和每个总线的当前状态仍会持续显示。
5. 默认按反引号键可开关面板显示。
6. 这个面板的目标是帮助开发联调，不是最终游戏内调试 UI。

### 验证基础音高与随机音高

1. 选择一个设置了 `PitchCents` 或 `PitchRandCents` 的事件。
2. 在 `Use Reference Time Preserving Pitch` 开启时运行并反复触发。
3. 观察音高变化是否生效，同时片段时长是否仍接近原始长度。
4. 若关闭该开关，再次验证时应回退为 Unity 原生 `AudioSource.pitch` 行为，此时音高变化会同时影响播放速度和片段时长。

### 验证 Cooldown

1. 把当前事件的 `CooldownSeconds` 设成明显值，例如 `0.5`。
2. 运行后快速反复按空格。
3. 观察是否有一部分触发被吞掉，只在冷却到期后真正播放。

### 验证 Max Instances

1. 给某个事件设置较长音频，并将 `MaxInstances` 设为 `1`。
2. 运行后快速连续按空格。
3. 如果 `StealPolicy = RejectNew`，预期新的播放请求被拒绝。
4. 如果 `StealPolicy = StopOldest`，预期旧实例被打断，新实例顶上来。

## 第七步：定位问题时怎么查

1. 先看 `AudioData.json` 里的 `RuntimeAudioFormat`，确认是不是 `ogg`。
2. 再看 `StreamingAssets/AudioForge/Assets` 下的真实扩展名是不是 `.ogg`。
3. 再看 `AssetKey` 和文件路径是否一致。
4. 如果脚本已编译但没声音，优先检查：
	音频是否真的导出了
	事件名是否和 JSON 里的键完全一致
	AudioSource 是否被创建
	Console 是否有加载失败日志

## Missing Script 修复

如果 Console 里出现：

`The referenced script (Unknown) on this Behaviour is missing!`

这通常不是当前脚本又写坏了，而是 Unity 场景里保留了旧的脚本 GUID 引用。常见触发方式包括：

1. 你删除过 `Assets/AudioForgeRuntime` 后又重新复制。
2. 复制时没有连同 `.meta` 文件一起带过去。
3. 场景里原本挂着旧版本的 `AudioForgeBootstrap`、`AudioForgeRuntime` 或其他测试组件。

现在仓库里的 `AudioForgeRuntime` 已经带上稳定 `.meta` 文件，并且额外提供了一个编辑器清理工具：

1. `AudioForge/Cleanup/Remove Missing Scripts In Selection`
2. `AudioForge/Cleanup/Remove Missing Scripts In Active Scene`
3. `AudioForge/Validation/Run Active Scene Validation`

推荐处理步骤：

1. 先把整个 `unity_validation/Assets/AudioForgeRuntime` 连同 `.meta` 文件重新复制到 Unity 项目中。
2. 等 Unity 编译完成，确认 Console 没有红色 C# 编译错误。
3. 如果只是个别对象坏了：选中这些对象，执行 `AudioForge > Cleanup > Remove Missing Scripts In Selection`。
4. 如果整个测试场景都受影响：直接执行 `AudioForge > Cleanup > Remove Missing Scripts In Active Scene`。
5. 清理完成后，再把需要的组件重新挂回去：
	`AudioForgeRuntime`
	`AudioForgeEventPlayer`
	`AudioForgeBootstrap`

如果你只是想最快恢复验证环境，最稳的办法仍然是：

1. 新建一个空物体。
2. 重新挂 `AudioForgeBootstrap`。
3. 把旧的带 Missing Script 的测试物体直接删掉。

## Unity 一键验证与报告

现在可以直接在 Unity 菜单中执行：

1. `AudioForge > Validation > Run Active Scene Validation`

它会对当前打开场景执行以下检查：

1. `StreamingAssets/AudioForge/AudioData.json` 是否存在且可解析。
2. `StreamingAssets/AudioForge/Assets` 下的运行时音频文件是否齐全。
3. 当前场景里是否仍然存在 Missing Script。
4. `AudioForgeBootstrap` 与 `AudioForgeEventPlayer` 配置的 `EventId` 是否能在当前 `AudioData.json` 中找到。
5. `AudioForgeRuntime` 是否能在编辑器环境里完成初始化，并成功注册导出的 Events 与 Buses。

执行完成后，会在 Unity 项目根目录生成：

1. `AudioForgeReports/unity_validation_report_时间戳.json`
2. `AudioForgeReports/unity_validation_report_时间戳.md`

适合的使用时机：

1. 你刚替换了导出数据和运行时脚本之后。
2. 你怀疑场景里还有旧组件残留时。
3. 你准备把当前 Unity 验证项目交给别人复现时。

## 当前 Runtime 的边界

当前这套 Unity Runtime 是“空项目验证版”，目标是验证契约和基础行为，不是最终生产版音频系统。它当前适合验证：

1. JSON 契约读取
2. OGG 文件加载
3. 事件查找
4. Random / Sequence / Combo / Cooldown / MaxInstances 的基础行为
5. 基础 Bus 管理、事件入口封装，以及更稳定的 AudioSource 池化回收

它当前还没有做的内容包括：

1. Unity AudioMixer 对接
2. Loop 点真实样本级处理
3. Trim 的运行时再次裁剪
4. Addressables / AssetBundle 对接
5. 更完整的 3D 空间音频和语音优先级系统

当前还需要由实际项目再补一轮确认的内容：

1. 目标项目内的资源加载策略
2. 与业务场景切换、内存约束、包体管理相关的实际表现
3. 是否保留参考保时长变调路径，或替换为生产版方案

补充说明：当前仓库里的保时长变调实现定位为“参考实现”，重点是给 Unity 程序提供挂接点、缓存方式和算法入口，不等同于最终生产质量的 DSP 方案。

## 生产化接入建议

现在推荐把组件分成两层使用：

1. `AudioForgeRuntime`
	负责加载 `AudioData.json`、维护 Bus 状态、缓存 AudioClip、管理 AudioSource 池。
2. `AudioForgeEventPlayer`
	负责作为场景里的事件触发入口，给按钮、交互物体、测试器挂这个组件更合适。
3. `AudioForgeBootstrap`
	保留为最小示例入口，适合空场景快速验证链路，不建议继续把业务逻辑都写在这个组件里。

当前 `AudioForgeRuntime` 已暴露这些可直接从脚本调用的方法：

1. `Play(string eventId)`
2. `Play(string eventId, AudioSource overrideSource)`
3. `SetBusVolume(string busName, float linearVolume)`
4. `SetBusMuted(string busName, bool isMuted)`
5. `StopBus(string busName)`
6. `StopEvent(string eventId)`
7. `StopAllManagedVoices()`

如果你的目标是“先验证这套中间件链路是否能在 Unity 空项目里成立”，这套材料已经足够。

如果你的目标是“准备进入正式项目接入”，建议在完成本 README 的空项目验证后，再补一份项目内联调记录，至少记录：

1. 接入项目名称与 Unity 版本
2. 当前资源提供方式
3. 当前保时长变调策略
4. 已通过的事件行为抽查项
5. 暂未实现或暂不接入的边界