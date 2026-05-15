# AudioForge Unity Runtime 三期 Game Sync 设计

当前文档同步日期：2026-05-14

## 文档定位

本文档记录 phase3 中 Unity runtime 对 RTPC、State、Switch 的已落地实现与继续演进边界。它当前以 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]` 的实现为准，也是后续继续向 Wwise 靠拢时的技术基线。

当前仓库主线当前以 `SchemaVersion = 3` 为主，运行时主数据结构已经切到顶层 `AudioObjects` 与 `Events[AudioId]`。

## 1. 当前落地面与剩余缺口

当前 runtime 已具备：

- 事件索引
- Bus 初始化与音量静音控制
- 播放模式（OneShot / Random / Sequence / Combo）
- 冷却、实例上限与基础调试记录
- 项目级 Game Parameter、State Group、Switch Group 定义解析
- emitter / game object 作用域与 emitter handle 注册
- `SetGlobalGameParameter` / `SetEmitterGameParameter` / `SetState` / `SetSwitch` API
- Event / Bus 的 RTPC、StateOverride 求值与 Event SwitchVariant 选片
- State / Switch child effects 应用与 validation smoke

当前 runtime 仍未完成：

- 已播放 active voice 的持续 RTPC 重算机制
- State 过渡时间与插值
- 更复杂的 Switch Container / 多层容器嵌套
- 更完整的场景侧实播签收流程自动化

因此 phase3 当前已经完成的重点不是“多加几个字段”，而是补上了一层可工作的运行时控制面；后续迭代主要围绕持续调制和更复杂容器能力展开。

## 2. 语义定义

### 2.1 RTPC

RTPC 在 AudioForge phase3 中定义为连续 Game Parameter。

语义约束：

- 可以有默认值、最小值、最大值。
- 可以是全局值，也可以是 emitter 级局部值。
- 主要用于驱动连续属性，如事件音量、事件音高、Bus 音量。
- 第一阶段不直接承担离散分支选择；若需要离散分支，应通过“RTPC 映射到 Switch”的规则显式实现。

### 2.2 State

State 在 AudioForge phase3 中定义为全局离散模式。

语义约束：

- State 必须属于某个 State Group。
- 同一 State Group 在任一时刻只有一个当前值。
- 作用范围为全局，不按 emitter 区分。
- 主要用于 Event / Bus 的属性覆盖，如音量、音高、静音、路由偏好。

### 2.3 Switch

Switch 在 AudioForge phase3 中定义为按 emitter / game object 生效的离散分支选择。

语义约束：

- Switch 必须属于某个 Switch Group。
- 当前值与 emitter / game object 绑定，而不是全局唯一。
- 主要用于事件内的变体分支切换，例如脚步材质、武器形态、角色形态。
- Switch 可以由游戏代码直接设置，也可以通过 RTPC 映射规则间接驱动。

## 3. Schema v2 草案

### 3.1 顶层结构

```json
{
  "SchemaVersion": 2,
  "ProjectName": "DemoProject",
  "RuntimeAudioFormat": "ogg",
  "BusConfigs": [],
  "GameParameters": [],
  "StateGroups": [],
  "SwitchGroups": [],
  "Events": {}
}
```

### 3.2 建议新增对象

`GameParameters`

- `Name`
- `DefaultValue`
- `MinValue`
- `MaxValue`
- `Description`

`StateGroups`

- `Name`
- `DefaultState`
- `States`
- `StateEffects`

`SwitchGroups`

- `Name`
- `DefaultSwitch`
- `Switches`
- `UseGameParameter`
- `MappedGameParameter`
- `Thresholds`
- `SwitchEffects`

### 3.3 Event 扩展建议

事件对象建议新增三类区块：

- `RtpcBindings`
- `StateOverrides`
- `SwitchVariants`
- `DefaultClipIds`

其中：

- `RtpcBindings` 用于连续属性驱动。
- `StateOverrides` 用于在特定 State 下覆盖事件属性。
- `SwitchVariants` 用于在特定 Switch 值下挑选不同变体分支。

### 3.4 Bus 扩展建议

Bus 对象建议新增：

- `RtpcBindings`
- `StateOverrides`

phase3 第一轮不建议把 Switch 直接挂到 Bus 上，避免把对象级分支选择扩散到全局混音层。

## 4. Runtime API 现状

### 4.1 初始化与上下文

- `Initialize()`
- `bool HasGameParameter(string name)`
- `bool HasStateGroup(string groupName)`
- `bool HasSwitchGroup(string groupName)`
- `AudioForgeEmitterHandle RegisterEmitter(GameObject gameObject)`
- `void UnregisterEmitter(AudioForgeEmitterHandle emitter)`

### 4.2 RTPC API

- `void SetGlobalGameParameter(string name, float value)`
- `void ResetGlobalGameParameter(string name)`
- `void SetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name, float value)`
- `float GetGlobalGameParameter(string name)`
- `float GetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name)`
- `void ResetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name)`

兼容期内，旧的 `SetGameParameter(string name, float value, AudioForgeEmitterHandle emitter)` / `GetGameParameter(string name, AudioForgeEmitterHandle emitter)` 仍作为 emitter 语义别名保留。

### 4.3 State API

- `void SetState(string groupName, string stateName)`
- `string GetState(string groupName)`
- `void ResetState(string groupName)`

### 4.4 Switch API

- `void SetSwitch(AudioForgeEmitterHandle emitter, string groupName, string switchName)`
- `string GetSwitch(AudioForgeEmitterHandle emitter, string groupName)`
- `void ResetSwitch(AudioForgeEmitterHandle emitter, string groupName)`

兼容期内，旧顺序的 `SetSwitch(string groupName, string switchName, AudioForgeEmitterHandle emitter)` / `GetSwitch(string groupName, AudioForgeEmitterHandle emitter)` 仍保留转发，以便旧项目平滑迁移。

### 4.5 播放 API

- `Coroutine PlayEvent(string eventId)`
- `Coroutine PlayEvent(string eventId, AudioSource overrideSource)`
- `Coroutine PlayEvent(string eventId, AudioForgeEmitterHandle emitter)`
- `Coroutine PlayEvent(string eventId, AudioForgeEmitterHandle emitter, AudioSource overrideSource, float localEventVolumeDbOffset)`

核心变化：播放 API 必须允许调用方传入 emitter 上下文，否则 per-object Switch 与 RTPC 无法正确求值。

## 5. Runtime 数据结构建议

### 5.1 静态配置

- `AudioForgeGameParameterConfig`
- `AudioForgeStateGroupConfig`
- `AudioForgeSwitchGroupConfig`
- `AudioForgeRtpcBindingConfig`
- `AudioForgeStateOverrideConfig`
- `AudioForgeSwitchVariantConfig`

### 5.2 运行时状态

- `_globalGameParameters`
- `_globalStates`
- `_emitters`
- `_events`
- `_buses`

### 5.3 Emitter 上下文

建议新增：

```text
AudioForgeEmitterContext
  - EmitterId
  - BoundGameObject
  - LocalGameParameters
  - LocalSwitches
  - ActiveVoices
```

这层结构是 phase3 的关键，没有它就无法区分“某个敌人脚下是 Gravel，另一个敌人脚下是 Concrete”。

### 5.4 ActiveVoice 扩展建议

当前 `AudioForgeActiveVoice` 仅包含 `Source`、`BusName`、`BaseVolume` 等信息。phase3 建议扩展为：

- `EventId`
- `EmitterId`
- `SelectedVariantId`
- `BasePitchCents`
- `CurrentResolvedVolume`
- `CurrentResolvedPitch`
- `AppliedStateSnapshot`
- `AppliedRtpcSnapshot`

如果后续要支持 RTPC 对正在播放声部的持续调制，这些字段是必要前提。

## 6. 求值顺序建议

事件触发时建议固定采用以下顺序：

1. 读取事件基础配置。
2. 应用全局 State 覆盖。
3. 读取 emitter 上下文中的 Switch 值，选择事件分支。
4. 读取全局与局部 RTPC，计算连续属性修正。
5. 进入现有 OneShot / Random / Sequence / Combo 逻辑。
6. 生成最终播放参数并创建 voice。

这样做的原因：

- State 决定全局模式。
- Switch 决定播放哪个分支。
- RTPC 决定分支内部的连续属性。

## 7. 第一阶段能力边界

phase3 第一阶段建议只实现：

- RTPC -> Event Volume
- RTPC -> Event Pitch
- RTPC -> Bus Volume
- State -> Event/Bus 属性覆盖
- Switch -> Event 级分支选片

暂不强求：

- RTPC 持续重算已播放 voice
- State 过渡时间与插值
- Switch Container 的复杂层级嵌套
- RTPC 到任意自定义属性的全开放映射

## 8. 兼容策略

### 8.1 v1 初始化

当读取到 `SchemaVersion = 1` 时：

- 不创建 Game Sync 表。
- State / Switch / RTPC API 可返回默认空状态。
- 继续按 phase2 的旧逻辑播放。

### 8.2 v3 初始化

当读取到 `SchemaVersion = 3` 时：

- 解析顶层 `AudioObjects`、`Events`、Game Sync 与总线字段。
- 为 `Event.AudioId -> AudioObject` 建立主真源映射。
- 初始化全局默认 RTPC / State。
- 为 Switch 准备 emitter 作用域存储。
- 缺失必要字段时明确报错并拒绝进入 Ready 状态。

## 9. 验证建议

最少需要覆盖以下场景：

1. 设置全局 State 后，同一事件音量或总线状态发生变化。
2. 为两个 emitter 设置不同 Switch，同一事件命中不同分支。
3. 设置局部 RTPC 后，同一事件在不同 emitter 上产生不同音量或音高。
4. 在未注册 emitter 的场景下，Switch 使用默认值或明确拒绝。
5. v3 payload 中 `Event.AudioId` 与目标 `AudioObject.Id` 能被正确关联并初始化。

## 10. 结论

phase3 runtime 的核心工作已经不是给当前 `PlayEvent` 再塞几个可选参数，而是把完整的 Game Sync 控制层和 `AudioObjects + Events[AudioId]` 数据主链落成了可运行基线。当前后续工作的重点不再是“是否做 Schema v2”，而是继续补齐持续调制、复杂容器和更强的场景侧验证。