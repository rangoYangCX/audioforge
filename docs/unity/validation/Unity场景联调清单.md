# Unity 场景联调清单

这份清单用于把 AudioForge 集成从“空工程验证通过”推进到“目标 Unity 场景可签收”。建议按顺序执行，并把结果记录到项目自己的联调单中。

## 1. 环境准备

- Unity 版本与目标项目生产版本一致。
- 已导入 `AudioForgeRuntime` 目录或最新独立包产物。
- `StreamingAssets/AudioForge/AudioData.json`、音频资源目录、`AudioEventID.cs` 都来自同一批导出。
- 如果启用了 Unity AudioMixer，确认 `AudioMixer` 资源和输出组已在工程中提交。

## 2. 启动路径检查

- 场景内存在一个唯一的 `AudioForgeRuntime` 实例。
- 如果使用自启动，`AudioForgeBootstrap` 所在物体会在首个场景加载时初始化运行时。
- 切场景后不会重复创建运行时，也不会丢失运行时引用。
- 运行时控制台没有 `AudioData.json` 读取失败、事件找不到或资源缺失日志。

## 3. 数据契约检查

- `AudioData.json` 中的事件数量与 `AudioEventID.cs` 枚举数量一致。
- Inspector 里的 Event Id 搜索结果与导出事件列表一致。
- 使用 `AudioForge/Tools/Refresh AudioEventID From StreamingAssets` 后，枚举刷新结果无脏差异。
- 任意一个新增事件在工具端导出后，可在 Unity 侧搜索、选择并播放。

## 4. 核心播放链路检查

- BGM、SFX、UI 三类事件都能在目标场景内正常触发。
- 同一事件的随机片段、权重和冷却在运行时符合预期。
- 循环事件可启动、停止、切场景续存或按预期销毁。
- 不存在明显爆音、重复叠播或事件漏触发。

## 5. AudioMixer 联调检查

- `integrateWithUnityAudioMixer` 打开后，默认输出组和各 Bus 绑定均生效。
- Play 模式下 `AudioForgeRuntime` Inspector 的 Master / Bus 音量滑杆可实时生效。
- UI 调整音量后，目标 `AudioMixer` 参数与听感一致。
- 当某个 Bus 没有配置绑定时，事件仍可退回默认输出组播放。

## 6. 场景行为检查

- 场景首帧触发音效不会因为运行时尚未初始化而丢失。
- 高频 UI 点击、连续战斗事件、场景切换等压力路径下没有明显卡顿。
- 暂停、恢复、切后台、回前台后音频状态符合项目预期。
- 如果目标项目自己管理全局音频单例，确认不会与 `AudioForgeRuntime` 职责冲突。

## 7. 资源与包体检查

- 导出音频格式、采样率和包体大小满足目标平台要求。
- 不再使用的旧导出资源已从工程中清理，避免同名脏文件残留。
- Addressables、AssetBundle 或自定义分包方案下，`StreamingAssets/AudioForge` 的装载路径仍有效。
- 真机包或开发包里实际包含本次导出的音频资源。

## 8. 回归建议

- 每次修改事件表、Bus 配置或 AudioMixer 绑定后，至少回归一次主菜单、战斗内和结算页。
- 每次更新 Unity 包后，重新执行一次 `tools/run_full_chain_check.py` 和一轮目标场景联调。
- 发版前固定保留一份对应版本的 Windows 工具包和 Unity 包产物，确保导出来源可追溯。
