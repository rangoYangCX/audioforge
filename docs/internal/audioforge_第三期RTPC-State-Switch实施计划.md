# AudioForge 第三期 RTPC / State / Switch 实施计划

当前文档同步日期：2026-05-13

## 目标

这份计划定义 AudioForge phase3 的正式目标：把 Wwise 中最关键的 Game Sync 语义，即 RTPC、State、Switch，系统地接入 AudioForge 工程模型、导出契约和 Unity runtime。

phase3 的目标不是只补一个编辑器面板，也不是在现有事件字段上继续叠加零散参数，而是补上一层项目级控制模型，使 AudioForge 首次具备更接近 Wwise 的运行时控制表达能力。

## 当前状态更新

2026-05-13 当前主线已完成以下落地：

1. 工程模型、导出器与 `.afproj` 序列化已支持项目级 Game Parameter、State Group、Switch Group，以及事件/总线级 RTPC、State、Switch 绑定。
2. `SchemaVersion = 2` 已进入当前导出链路，Unity runtime / validation 已同步支持 v2 初始化与 v1 兼容。
3. 工具端已落地 GameSync 工作区、State/Switch 子项效果编辑、RTPC 图形曲线编辑器和试听中心 GameSync 控件。
4. Unity runtime 已具备 emitter context、State/Switch/RTPC API、Switch Variant 选片、child effects 应用与 smoke 验证。

因此本文档后续更多用于解释阶段拆分、边界和剩余工作，而不是说明“是否开始做 phase3”。

## 结论先行

- RTPC：按连续 Game Parameter 处理，用于实时驱动属性。
- State：按全局离散模式处理，用于切换 Event / Bus 属性覆盖。
- Switch：按 emitter / game object 生效的离散分支选择处理，用于切换事件内部的变体或容器分支。

这三者不能合并为同一类“事件参数”。如果在数据模型或 runtime API 上把三者混成一个概念，后续行为会持续偏离 Wwise 心智。

## 本期范围

### 要做的事

1. 在工程模型中引入项目级 Game Sync 定义。
2. 设计并实现 Schema v2 草案。
3. 设计并逐步实现 Unity runtime 的 Game Sync 控制层。
4. 让 Event / Bus 能表达与 RTPC / State / Switch 相关的绑定与覆盖规则。
5. 补齐验证样例、测试面和文档说明。

### 本期不做的事

1. 不在 phase3 第一轮同时完成全部 authoring UI 的商业化润色。
2. 不把 profiler、远程回传、Capture 协议和运行时可视化联调桥绑进同一阶段。
3. 不借 phase3 机会夹带 `Enabled` / `Active`、布局状态或其他 editor-only 字段进入运行时契约。
4. 不在没有 emitter 作用域的前提下强行实现 per-object Switch 或 RTPC。

## 当前基线

phase2 已完成以下交付：

- 对象浏览器三分页。
- Source Binding 弹窗与 `Enabled` / `Active` 编辑闭环。
- `PlayMode = OneShot`。
- Unity UPM SDK 输出。
- 当前 Unity runtime 继续兼容 `SchemaVersion = 1` 的 `AudioData.json`。

当前主线额外已具备：

- `SchemaVersion = 2`
- `GameParameters` / `StateGroups` / `SwitchGroups`
- Event `RtpcBindings` / `StateOverrides` / `SwitchVariants` / `DefaultClipIds`
- Bus `RtpcBindings` / `StateOverrides`
- emitter / game object 作用域与 Game Sync 求值层

当前仍待继续增强：

- active voice 持续调制
- State 过渡插值
- 更复杂的 Switch Container 层级
- 更完整的场景侧实播自动化签收

## 设计原则

### 1. 先定 runtime 语义，再做 authoring UI

phase3 第一优先级是导出契约和 Unity runtime 设计，不是先做工具端交互。没有稳定的语义边界，UI 只会反向固化错误模型。

### 2. 先补 emitter 作用域，再做 per-object Switch / RTPC

Switch 与局部 RTPC 的语义都依赖 emitter / game object。如果 runtime 没有这层上下文，只能错误地退化成全局值。

### 3. State 与 Switch 明确分工

State 负责“全局模式”，Switch 负责“对象分支”。State 不承担事件分支选片，Switch 不承担全局模式广播。

### 4. 不破坏 phase2 已交付边界

phase3 的 schema 升级必须通过显式 `SchemaVersion` 和兼容实现来承接，而不是悄悄篡改 v1 字段含义。

## 工作拆分

### P3-A 工程模型与导出契约

目标：在 AudioForge 工程模型与 `AudioData.json` 中新增 Game Sync 层。

计划落地：

- 新增 `GameParameterModel`、`StateGroupModel`、`StateModel`、`SwitchGroupModel`、`SwitchValueModel`。
- 在 `EventModel` 上新增：RTPC 绑定、State 覆盖、Switch 分支定义。
- 在 `BusConfig` 上新增：RTPC 绑定与 State 覆盖。
- `RuntimeExporter` 输出 `SchemaVersion = 2` 的结构化 payload。

建议验收：

- v1 工程与 v2 工程能在导出阶段明确区分。
- 不改动现有 `Clips`、`BusConfigs` 和事件基础字段的语义。
- schema 草案可用 Markdown 和样例 JSON 直接审阅。

### P3-B Unity runtime 控制层

目标：给 Unity runtime 增加 Game Sync 存储、API 和求值流程。

计划落地：

- 新增全局 RTPC 表。
- 新增全局 State Group 当前值表。
- 新增 emitter / game object 上下文，用于保存局部 RTPC 与 Switch。
- `PlayEvent` 在选片前执行 Game Sync 求值。
- Active voice 结构升级，为后续持续调制预留空间。

建议验收：

- 能通过 API 改变全局 State 与全局 RTPC。
- 能针对 emitter 设置 Switch 并命中不同事件分支。
- v1 payload 仍可初始化并按旧行为播放。

### P3-C Tool authoring UI

目标：在工具端新增 Game Sync authoring 能力。

计划落地：

- Project Explorer 增加 Game Sync 入口。
- 属性编辑器增加 RTPC / State / Switch 绑定区。
- Event 设计页支持编辑 Switch 分支与 State 覆盖。
- Bus 混音台支持编辑 State 覆盖与 RTPC 绑定。

建议验收：

- 项目级对象可创建、重命名、删除并保存进 `.afproj`。
- 事件与总线能在 UI 中正确显示绑定摘要。
- 未配置的 Game Sync 不影响现有 phase2 编辑流。

### P3-D 测试、验证与交付

目标：为 phase3 建立独立验证闭环。

计划落地：

- exporter 单测覆盖 schema v2 输出。
- runtime 单测覆盖 RTPC、State、Switch 求值。
- Unity 空项目验证增加 Game Sync 场景。
- 文档同步到 README、开发文档、Unity SDK 对接文档。

建议验收：

- phase3 的新语义都有最少一条自动化验证用例。
- 空项目能验证 State 覆盖、RTPC 调制、Switch 变体切换。
- 新旧 schema 的初始化路径都可回归。

## 文件级影响面

预计会触达的核心模块：

- `audioforge/app/models/audio_project.py`
- `audioforge/app/services/exporter.py`
- `audioforge/app/controllers/main_controller.py`
- `audioforge/app/views/main_window.py`
- `unity_package/Assets/AudioForgeRuntime/Scripts/AudioForgeModels.cs`
- `unity_package/Assets/AudioForgeRuntime/Scripts/AudioForgeJsonAdapter.cs`
- `unity_package/Assets/AudioForgeRuntime/Scripts/AudioForgeRuntime.cs`
- `unity_validation/Assets/AudioForgeRuntime/Scripts/*`

## 关键风险

### 风险 1：把 RTPC、State、Switch 混成统一参数表

后果：runtime API 失真，UI 也会持续偏离 Wwise 语义。

控制：保持三类对象与三类控制 API 分离。

### 风险 2：没有 emitter 作用域却先做 Switch

后果：Switch 被迫退化成全局分支，无法支持典型脚步材质、武器状态等对象级切换。

控制：在 runtime 设计阶段先补 `AudioEmitterContext`。

### 风险 3：在 v1 契约上偷偷加字段

后果：旧项目和旧 SDK 的兼容边界被打穿。

控制：phase3 明确使用 Schema v2，并保留旧 schema 初始化路径。

## 里程碑建议

1. M1：完成 schema v2 草案与 runtime API 草案。
2. M2：完成工程模型、导出器与 v2 payload 生成。
3. M3：完成 runtime 初始化、SetState / SetSwitch / SetGameParameter 基础接口。
4. M4：完成首轮 authoring UI 与空项目验证。
5. M5：完成文档、测试、迁移与交付收口。

## 验收口径

phase3 达标的最小标准不是“界面已经像 Wwise”，而是以下 5 条：

1. 能明确表达项目级 RTPC、State Group、Switch Group。
2. 能稳定导出 Schema v2，并与 v1 明确区分。
3. Unity runtime 能按正确作用域消费三类控制量。
4. Event / Bus 的绑定语义与 Wwise 心智一致，不互相越权。
5. 文档、测试和验证样例都能解释这套新契约如何使用。