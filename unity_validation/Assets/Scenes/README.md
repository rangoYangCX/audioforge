# Validation Scenes

当前文档同步日期：2026-05-08

这个目录用于放 Unity 空项目验证场景。

推荐保留一个最小场景，例如 `Validation.unity`，只验证这些内容：

1. `AudioForgeRuntime` 能完成初始化。
2. `AudioData.json` 和导出音频能从 `StreamingAssets/AudioForge` 被读取。
3. `AudioForgeBootstrap` 能触发样例事件。
4. `AudioForgeRuntimeDebugPanel` 能显示事件、总线和活动声部状态。
