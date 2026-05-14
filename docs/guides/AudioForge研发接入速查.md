# AudioForge 研发接入速查

> 这是面向 Unity / 客户端研发的快速入口，不替代完整规范。完整字段语义、边界和接入步骤统一以 `docs/unity/UnitySDK对接规范.md` 为准。

当前文档同步日期：2026-05-14

适用对象：Unity 客户端、音频运行时研发、TA、负责 SDK 接入和联调的同学。

## 1. 接入只看这 6 句话

1. Unity 只消费导出产物，不读取 `.afproj`。
2. 当前正式契约是 `SchemaVersion = 3`，核心结构是 `AudioObjects + Events[AudioId]`。
3. Event 是动作层，Audio Object 是声音层，不要再按旧结构把声音规则全挂在事件上理解。
4. 业务代码只通过 Event Id 触发，不要另写一套随机、序列、连击规则。
5. 资源加载策略可以替换，但建议通过资源提供器接口注入，不要改播放主干。
6. 出问题先查导出目录、初始化、事件存在性、资源路径和 Bus 状态。

## 2. 最小接入步骤

### 2.1 放包

- 使用 `dist/AudioForgeUnityPackage-<version>/` 或 zip。
- 以本地 UPM 包方式放进 Unity 项目 `Packages/`，或按团队规范接入。

### 2.2 放导出物

目标结构建议为：

```text
Assets/
  StreamingAssets/
    AudioForge/
      AudioData.json
      AudioManifest.json
      Assets/
        ...导出音频...
```

### 2.3 跑第一声

- 初始化 `AudioForgeRuntime`。
- 触发一个已知 Event Id。
- 确认调试面板或日志里能看到触发记录。

## 3. 研发真正要关心的字段

### 3.1 必看顶层

- `SchemaVersion`
- `AudioObjects`
- `Events`
- `GameParameters`
- `StateGroups`
- `SwitchGroups`
- `BusConfigs`

### 3.2 Event 重点

- `AudioId`
- `MaxInstances`
- `CooldownSeconds`
- `StealPolicy`

### 3.3 Audio Object 重点

- Bus
- PlayMode
- Clips
- DefaultClipIds
- RTPC / State / Switch 绑定
- 声音层属性与子项效果

## 4. 运行时最小职责

- 读 `AudioData.json` 并建索引。
- 通过 Event Id 找到 Event 和 Audio Object。
- 管理实例数、冷却、Sequence 游标、Combo 状态。
- 管理 Bus 音量和静音。
- 提供资源加载能力。
- 提供日志与调试观测。

## 5. 最小验收标准

1. `AudioForgeRuntime` 初始化成功。
2. `AudioData.json` 可读且事件索引非空。
3. 至少一个真实 Event Id 可播放。
4. Random / Sequence / Combo 至少各能验证一条样例。
5. 资源缺失、事件缺失和契约错误能在日志里被明确定位。

## 6. 最常见的接入错误

1. 只同步了 `AudioData.json`，没同步导出音频目录。
2. 仍按旧 schema 读取事件内嵌 Audio。
3. 用旧 SDK 包联调新导出。
4. 业务侧自己又写了一套播放规则。
5. 调试时只看有没有出声，不看事件记录和资源解析路径。

## 7. 推荐联调顺序

1. OneShot 或 Random 的基础事件。
2. Sequence。
3. Combo。
4. Cooldown / MaxInstances / StealPolicy。
5. RTPC。
6. State。
7. Switch。
8. Bus 音量、静音和路由。

## 8. 出问题先查什么

- 初始化是否完成。
- `AudioData.json` 是否被读到。
- Event Id 是否存在。
- `AudioId` 是否能解析到目标 Audio Object。
- 资源文件是否存在且路径正确。
- Bus 是否静音或被父 Bus 衰减。
- 当前是否命中了冷却、实例上限或 GameSync 分支条件。

## 9. 进一步阅读

- 完整说明：`docs/guides/AudioForge使用说明.md`
- Unity 主对接文档：`docs/unity/UnitySDK对接规范.md`
- Unity 包说明：`unity_package/README.md`
- Unity 空项目验证：`unity_validation/README.md`