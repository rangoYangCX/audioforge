# AudioForge Unity SDK Quick Start

当前文档同步日期：2026-05-11

这份文档只回答一件事：拿到包以后，Unity 程序最快怎么在 10 分钟内听到第一声。

## 第一步：导入运行时代码

1. 打开生成后的 `AudioForgeUnityPackage-<version>/`。
2. 把 `Assets/AudioForgeRuntime/` 整体复制到你的 Unity 项目 `Assets/` 目录。
3. 等 Unity 完成脚本编译，确认 Console 没有红色编译错误。

## 第二步：放入工具导出物

把 AudioForge 工具导出的这些文件复制到 Unity 项目：

- `AudioData.json` -> `Assets/StreamingAssets/AudioForge/AudioData.json`
- `AudioManifest.json` -> `Assets/StreamingAssets/AudioForge/AudioManifest.json`
- `Assets/**` -> `Assets/StreamingAssets/AudioForge/Assets/**`

## 第三步：搭最小验证场景

1. 在场景里新建一个空物体，命名为 `AudioForgeBootstrap`。
2. 给它挂上 `AudioForgeBootstrap` 组件。
3. 如果你想直接观察运行时状态，再额外挂上 `AudioForgeRuntimeDebugPanel`。
4. 在 `AudioForgeBootstrap` Inspector 中把 `Event Id` 设为一个导出里真实存在的事件，例如 `sfx_level_check_02`。
5. 保持 `Auto Play On Start = true`，进入 Play 模式确认是否能出声。

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

补充说明：0.06.2 这轮发布不会改变这里的接入步骤；如果你重新拿工具生成了一批导出物，主要变化是桌面工具最近试听卡片、transport 可视化和交付文档更加完整。