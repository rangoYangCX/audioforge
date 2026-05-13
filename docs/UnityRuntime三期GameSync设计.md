# AudioForge Unity Runtime 三期 Game Sync 设计

当前文档同步日期：2026-05-13

## 文档定位

本文档定义 phase3 中 Unity runtime 对 RTPC、State、Switch 的目标设计。它不是当前 0.07.0 SDK 的实现说明，而是下一轮 schema 与 runtime 演进的技术基线。

当前 phase2 SDK 仍然只支持 `SchemaVersion = 1`。本文档描述的是 `SchemaVersion = 2` 的目标模型。

## 1. 当前缺口

当前 runtime 已具备：

- 事件索引
- Bus 初始化与音量静音控制
- 播放模式（OneShot / Random / Sequence / Combo）
- 冷却、实例上限与基础调试记录

当前 runtime 缺少：

- 项目级 Game Parameter 定义
- State Group / Switch Group 定义
- emitter / game object 作用域
- Game Sync 求值顺序
- 持续调制中的 active voice 重算机制

因此 phase3 的设计重点不是“多加几个字段”，而是补上一层运行时控制面。

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

`SwitchGroups`

- `Name`
- `DefaultSwitch`
- `Switches`
- `UseGameParameter`
- `MappedGameParameter`
- `Thresholds`

### 3.3 Event 扩展建议

事件对象建议新增三类区块：

- `RtpcBindings`
- `StateOverrides`
- `SwitchVariants`

其中：

- `RtpcBindings` 用于连续属性驱动。
- `StateOverrides` 用于在特定 State 下覆盖事件属性。
- `SwitchVariants` 用于在特定 Switch 值下挑选不同变体分支。

### 3.4 Bus 扩展建议

Bus 对象建议新增：

- `RtpcBindings`
- `StateOverrides`

phase3 第一轮不建议把 Switch 直接挂到 Bus 上，避免把对象级分支选择扩散到全局混音层。

## 4. Runtime API 草案

### 4.1 初始化与上下文

- `Initialize()`
- `bool HasGameParameter(string name)`
- `bool HasStateGroup(string groupName)`
- `bool HasSwitchGroup(string groupName)`
- `AudioForgeEmitterHandle RegisterEmitter(GameObject gameObject)`
- `void UnregisterEmitter(AudioForgeEmitterHandle emitter)`

### 4.2 RTPC API

- `void SetGlobalGameParameter(string name, float value)`
- `void SetGameParameter(string name, float value, AudioForgeEmitterHandle emitter)`
- `float GetGlobalGameParameter(string name)`
- `float GetGameParameter(string name, AudioForgeEmitterHandle emitter)`

### 4.3 State API

- `void SetState(string groupName, string stateName)`
- `string GetState(string groupName)`

### 4.4 Switch API

- `void SetSwitch(string groupName, string switchName, AudioForgeEmitterHandle emitter)`
- `string GetSwitch(string groupName, AudioForgeEmitterHandle emitter)`

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

### 8.2 v2 初始化

当读取到 `SchemaVersion = 2` 时：

- 解析新增顶层字段。
- 初始化全局默认 RTPC / State。
- 为 Switch 准备 emitter 作用域存储。
- 缺失必要字段时明确报错并拒绝进入 Ready 状态。

## 9. 验证建议

最少需要覆盖以下场景：

1. 设置全局 State 后，同一事件音量或总线状态发生变化。
2. 为两个 emitter 设置不同 Switch，同一事件命中不同分支。
3. 设置局部 RTPC 后，同一事件在不同 emitter 上产生不同音量或音高。
4. 在未注册 emitter 的场景下，Switch 使用默认值或明确拒绝。
5. v1 payload 与 v2 payload 都能被 runtime 正确区分并初始化。

## 10. 结论

phase3 runtime 的核心工作不是给当前 `PlayEvent` 再塞几个可选参数，而是建立一个完整的 Game Sync 控制层。只有先把 Schema、API、emitter 作用域和求值顺序设计清楚，后续工具端 authoring UI 和 Unity 项目接入才不会反复返工。