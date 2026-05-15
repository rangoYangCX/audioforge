# AudioForge Unity SDK Quick Start

当前文档同步日期：2026-05-14

这份文档只回答一件事：拿到包以后，Unity 程序最快怎么在 10 分钟内听到第一声。

如果你是从第一期 SDK 直接接到这份包，建议先用 2 分钟读完 `一期对比变化总览.md`，再继续下面的最短接入步骤。

如果你想先看超短版，再回到这里，请先读 `研发接入速查.md`。

## 第一步：导入运行时代码

1. 打开生成后的 `AudioForgeUnityPackage-<version>/`。
2. 将整个包目录放进 Unity 项目的 `Packages/` 下，或在 `Packages/manifest.json` 中以本地路径方式引用当前目录。
3. 等 Unity 完成包解析与脚本编译，确认 Console 没有红色编译错误。

## 第二步：放入工具导出物

把 AudioForge 工具导出的这些文件复制到 Unity 项目：

- `AudioData.json` -> `Assets/StreamingAssets/AudioForge/AudioData.json`
- `AudioManifest.json` -> `Assets/StreamingAssets/AudioForge/AudioManifest.json`
- `Assets/**` -> `Assets/StreamingAssets/AudioForge/Assets/**`

如果当前导出是 `SchemaVersion = 3`，`AudioData.json` 里还会包含顶层 `AudioObjects`、`Events[AudioId]`、`GameParameters`、`StateGroups`、`SwitchGroups`，以及 Audio/总线级 GameSync 区块；这些字段已经由包内 runtime 负责解析，不需要额外复制其他配置文件。

## 第三步：搭最小验证场景

1. 在场景里新建一个空物体，命名为 `AudioForgeBootstrap`。
2. 给它挂上 `AudioForgeBootstrap` 组件。
3. 如果你想直接观察运行时状态，再额外挂上 `AudioForgeRuntimeDebugPanel`。
4. 在 `AudioForgeBootstrap` Inspector 中把 `Event Id` 设为一个导出里真实存在的事件，例如 `sfx_level_check_02`。
5. 保持 `Auto Play On Start = true`，进入 Play 模式确认是否能出声。

如果你要顺手验证 GameSync：

1. 再创建一个挂有 `AudioForgeEventPlayer` 的对象。
2. 保持 `UseEmitterContext = true`。
3. 进入 Play 模式后，通过脚本或 Inspector 调用 `SetState`、`SetSwitch`、`SetGameParameter` 相关路径，确认调试面板里能看到事件结果变化。

## 第四步：看懂下一步该改哪层

- 如果只是要先跑通：继续使用 `AudioForgeBootstrap` 和 `AudioForgeEventPlayer`。
- 如果要接项目自己的业务代码：看 `../Examples/AudioForgeRuntimeLocatorExample.cs`。
- 如果要替换默认 `StreamingAssets` 加载方案：先看 `../Examples/AudioForgeResourcesProviderExample.cs`，再看 `../Examples/AudioForgeRuntimeInstallerExample.cs`。
- 如果要核对字段语义和运行时边界：读 `Canonical/UnitySDK对接规范.md`。

## 最低验收标准

满足以下 4 条，就说明 SDK 已经在 Unity 项目里落到最小可用状态：

1. `AudioForgeRuntime` 能完成初始化。
2. `AudioData.json` 能被读到，事件列表不为空。
3. 至少一个真实事件可以被触发播放。
4. `AudioForgeRuntimeDebugPanel` 或日志里能看到事件触发记录。

补充说明：当前包除了 `PlayMode = OneShot` 外，还已经补齐 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]`、GameSync API、emitter context、child effects smoke，以及 Event 顶层只保留播放控制、声音属性统一归 `AudioObject` 的契约；如果项目里不是直接使用包内 runtime，而是自行维护运行时，请优先同步这些变化。