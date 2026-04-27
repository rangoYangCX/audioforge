# AudioForge Validation Sample

这个目录代表 Unity 空项目验证工程里的示例骨架层，不承载运行时代码真源。

## 作用

- 放置验证场景的说明和占位资源。
- 约定最小测试对象如何搭建。
- 和 `Assets/AudioForgeRuntime` 分离，避免把示例内容和 SDK 运行时代码混在一起维护。

## 推荐骨架

- `Assets/AudioForgeRuntime`：从 `unity_package` 同步来的运行时代码镜像。
- `Assets/AudioForgeValidationSample`：示例场景、说明、测试对象约定。
- `Assets/Scenes`：验证场景入口。
- `Assets/StreamingAssets/AudioForge`：放工具导出的 JSON 和音频资源。

## 最小验证对象

1. 新建一个空物体，命名为 `AudioForgeBootstrap`。
2. 挂上 `AudioForgeBootstrap` 组件。
3. 如果需要观察状态，再挂上 `AudioForgeRuntimeDebugPanel`。
4. 事件 ID 默认可使用 `sfx_level_check_02`。
