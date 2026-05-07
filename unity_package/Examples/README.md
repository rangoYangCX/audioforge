# AudioForge Unity SDK Examples

当前文档同步日期：2026-05-07

这个目录里的文件是“参考示范代码”，不是自动导入 Unity 的运行时真源。

## 使用原则

1. 先看注释，确认你要解决的是“触发层”、 “运行时定位”还是“资源加载层”。
2. 再把需要的文件手工复制到目标 Unity 项目的 `Assets/` 目录。
3. 最后按项目命名规范改名，并收进自己的业务层或基础设施层。

## 文件说明

- `AudioForgeRuntimeLocatorExample.cs`：示范如何安全取得 `AudioForgeRuntime`，并在首次播放前确保初始化完成。
- `AudioForgeGameplaySfxExample.cs`：示范如何把常见 UI / 玩法动作映射为事件触发和总线控制。
- `AudioForgeResourcesProviderExample.cs`：示范如何实现一个自定义 `IAudioForgeResourceProvider`。
- `AudioForgeRuntimeInstallerExample.cs`：示范如何在 `Initialize()` 之前把自定义资源提供器注入 `AudioForgeRuntime`。

## 推荐阅读顺序

1. `AudioForgeRuntimeLocatorExample.cs`
2. `AudioForgeGameplaySfxExample.cs`
3. `AudioForgeResourcesProviderExample.cs`
4. `AudioForgeRuntimeInstallerExample.cs`