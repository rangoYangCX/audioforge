# AudioForge GameSync 全局与个体作用域升级书

当前文档同步日期：2026-05-15

## 1. 文档目的

本文档用于把 AudioForge 当前 GameSync 的“全局 / 个体”边界彻底收口，并给出一套可直接执行的升级方案。它覆盖四类内容：

- 语义冻结：RTPC、State、Switch 各自属于哪一层作用域
- Authoring / Preview 升级：试听面板如何可视化“当前生效来源”
- Runtime API 升级：如何用明确命名拆开 global 与 emitter 上下文
- 测试与迁移：如何在不打穿 Schema 3 主契约的前提下完成收口

本文档默认以当前仓库主线为基线：

- SchemaVersion = 3
- 顶层数据结构为 AudioObjects + Events[AudioId]
- 工具端已具备 GameSync 编辑入口与试听 GameSync 控件
- Runtime 已具备 global parameter、state、switch 与 emitter context 基础能力

## 2. 当前问题

当前实现已经基本具备 phase3 主链，但“全局 / 个体”仍存在认知和交互层的混淆，主要表现为：

1. 试听面板把 RTPC 的 scope 选择、参数值输入、State / Switch 选择放在一块紧凑条带里，但没有告诉用户“当前到底吃的是 global 值、emitter 值，还是 default 值”。
2. Switch 的显式选择与“按 Game Parameter 映射”共存，但界面上没有明确说明：Switch 的结果是个体的，而驱动它的参数值可能来自 emitter，也可能回退到 global。
3. Runtime API 虽然已经有 `SetGlobalGameParameter`、`SetGameParameter`、`SetState`、`SetSwitch`，但 authoring、preview、runtime 三边还没有统一成一套“世界上下文 vs 个体上下文”的表述。
4. 现有自动化测试更偏向功能通路验证，对“当前生效来源”和“Emitter 覆盖 Global”的行为覆盖还不够系统。

因此本轮升级不应继续把问题解释为“某个下拉框没生效”，而是要把作用域模型、界面表达和 API 命名统一起来。

## 3. 最终语义冻结

### 3.1 两层上下文模型

AudioForge 后续统一采用两层上下文：

- 全局上下文：项目 / 会话 / 世界级控制量
- 个体上下文：某个 emitter / game object / 某次播放实例的局部控制量

### 3.2 RTPC

RTPC 是唯一允许同时存在 Global 与 Emitter 两种作用域的控制量。

冻结规则：

- 绑定 scope = Global：只读取 global game parameter；无值则回 default
- 绑定 scope = Emitter：先读取 emitter game parameter；无值则回退 global；再无值则回 default
- RTPC 本身不承担全局离散模式切换，不直接替代 State
- RTPC 可以参与 Switch 映射，但其映射结果仍应落到个体上下文

### 3.3 State

State 固定为全局离散模式，不引入 emitter state。

冻结规则：

- State Group 在任一时刻只有一个全局当前值
- Event / Bus 的 state override 只消费全局 state
- Preview UI 不为 State 提供 Global / Emitter scope 切换
- Runtime 只保留 `SetState(group, state)` / `GetState(group)` 这一层接口

### 3.4 Switch

Switch 固定为个体上下文的离散分支，不引入 global switch。

冻结规则：

- 显式 Switch 值绑定到 emitter / game object，而不是全局唯一值
- Event SwitchVariant 选片只读取当前 emitter 上下文中的 switch 值
- 未提供 emitter switch 时回 default switch
- Preview 中如果用户直接选择某个 switch，本质是在设置“当前试听对象的临时 emitter switch”

### 3.5 Switch 映射 Game Parameter

Switch Group 开启 `UseGameParameter` 后，仍然生成个体 switch 结果；只是用于映射的参数值可以回退到 global。

冻结规则：

- 映射结果属于 emitter scope
- 取值顺序：Emitter parameter -> Global parameter -> Parameter default
- 不把这条规则解释成“Switch 也支持 Global scope”
- UI 必须明确显示这是“个体结果，参数回退来源可能是 global”

## 4. Authoring 与试听面板升级方案

## 4.1 目标

试听面板的升级目标不是增加更多控件，而是让用户在一次试听前就能回答三个问题：

- 我当前改的是世界级值还是试听对象局部值
- 当前真正参与求值的是 emitter、global 还是 default
- 当前 Switch 是手动指定的，还是由参数映射推导出来的

## 4.2 RTPC 面板改造

当前 RTPC 区保留“参数名 + scope + slider + spin”的紧凑结构，但新增“生效来源读数层”。

建议改造为三段：

1. 参数选择层
- 参数名
- 绑定 scope 标签或可编辑 scope 选择

2. 值输入层
- Slider
- 数值输入框
- 最小/最大值标识

3. 生效来源层
- 当前生效来源：Emitter / Global / Default
- 当前求值链：`Emitter(6.0) -> Global(4.0) -> Default(0.0)` 中被命中的项高亮
- 如果当前 binding scope = Global，则显示“当前绑定仅读取 Global”

界面行为：

- 当用户切换到 Emitter scope 且本地没有 emitter 值时，面板明确显示“当前回退到 Global”
- 当用户切换到 Global scope 时，面板明确显示“Emitter 值不会参与本次绑定求值”
- 当当前事件没有任何 RTPC binding 使用该参数时，面板仍可编辑试听值，但显示“当前事件未消费此参数”

## 4.3 State 面板改造

State 面板不引入 scope 控件，只强调“全局模式”。

建议结构：

- Group
- Active State
- 来源标签：Global State
- 当前命中的覆盖摘要：命中的 Event override / Bus override 数量

界面行为：

- 任何 State 变更都应在试听中直接重触发当前 event audition
- State 行上显示“作用域：全局”，避免再让用户把它误判成对象级开关

## 4.4 Switch 面板改造

Switch 面板拆成“显式选择模式”和“参数映射模式”两种可读状态。

建议结构：

- Group
- 当前结果 Switch
- 结果来源标签：Manual Emitter Switch / Parameter-Mapped Switch / Default Switch
- 若为参数映射模式，展示：
  - 映射参数名
  - 参数实际来源：Emitter / Global / Default
  - 当前阈值区间

界面行为：

- 如果用户手动选择 switch，则明确显示“当前试听对象的手动 switch 覆盖映射结果”
- 如果 group 开启了参数映射且未手动覆盖，则显示“当前结果由参数映射得到”
- 如果既没有手动值也没有有效参数，则显示“当前回退 Default Switch”

## 4.5 建议新增的 Preview 数据结构

Preview UI 层建议新增一层“诊断快照”而不是直接从控件反推原因。

建议结构：

```text
PreviewGameSyncResolution
  - parameter_resolutions[]
    - name
    - binding_scope
    - resolved_source   # emitter/global/default
    - emitter_value
    - global_value
    - default_value
    - resolved_value
  - state_resolutions[]
    - group_name
    - resolved_state
    - source            # global/default
    - matched_overrides
  - switch_resolutions[]
    - group_name
    - resolution_mode   # manual/mapped/default
    - parameter_name
    - parameter_source  # emitter/global/default/none
    - resolved_switch
    - matched_threshold
```

这层结构只用于工具端诊断和日志，不进入运行时导出契约。

## 5. Runtime API 升级方案

## 5.1 总目标

Runtime API 必须显式区分“世界上下文”和“个体上下文”，避免再出现一个万能接口把 RTPC、State、Switch 都塞进去。

原则：

- State 只属于 world
- Switch 只属于 emitter
- RTPC 同时支持 world 与 emitter
- API 命名体现上下文，不让调用者猜 scope

## 5.2 推荐 API 命名

### 全局上下文

- `void SetGlobalGameParameter(string name, float value)`
- `float GetGlobalGameParameter(string name)`
- `void ResetGlobalGameParameter(string name)`
- `void SetState(string groupName, string stateName)`
- `string GetState(string groupName)`
- `void ResetState(string groupName)`

### 个体上下文

- `void SetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name, float value)`
- `float GetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name)`
- `void ResetEmitterGameParameter(AudioForgeEmitterHandle emitter, string name)`
- `void SetSwitch(AudioForgeEmitterHandle emitter, string groupName, string switchName)`
- `string GetSwitch(AudioForgeEmitterHandle emitter, string groupName)`
- `void ResetSwitch(AudioForgeEmitterHandle emitter, string groupName)`

### 播放 API

- `Coroutine PlayEvent(string eventId)`
- `Coroutine PlayEvent(string eventId, AudioForgeEmitterHandle emitter)`
- `Coroutine PlayEvent(string eventId, AudioForgeEmitterHandle emitter, AudioSource overrideSource, float localEventVolumeDbOffset)`

若无 emitter 句柄：

- 允许播放，但只使用 world 上下文 + default switch
- 不把这种路径包装成“global switch 播放”
- 日志层建议明确记录“no emitter context”

## 5.3 兼容命名策略

当前已有 `SetGameParameter(string name, float value, AudioForgeEmitterHandle emitter)`。

建议升级策略：

- 保留旧接口一段兼容期
- 旧接口内部转发到 `SetEmitterGameParameter(...)`
- 文档、示例、validation 用例统一切到新命名
- 下一大版本移除旧接口或把旧接口标成 obsolete

这样能避免 authoring / runtime / 文档三边继续混用“SetGameParameter 到底是不是 emitter”的模糊表达。

## 6. Runtime 求值顺序升级

后续统一采用以下顺序：

1. 读取 Event 基础配置
2. 读取全局 State 并应用 State overrides / child effects
3. 读取 emitter switch，上屏决定 SwitchVariant / 分支选片
4. 读取 RTPC，按 binding scope 解算连续属性
5. 进入 OneShot / Random / Sequence / Combo 播放模式
6. 输出最终 resolved mix / pitch / mute / selected clips

补充规则：

- 显式 emitter switch 优先于参数映射 switch
- 参数映射 switch 的参数来源顺序为 Emitter -> Global -> Default
- Event / Bus 的 RTPC binding scope = Emitter 时，参数来源顺序为 Emitter -> Global -> Default
- Event / Bus 的 RTPC binding scope = Global 时，参数来源顺序为 Global -> Default

## 7. 工具端控制器与服务层升级项

## 7.1 MainController

建议增加以下职责：

- 从 preview service 取得 resolution snapshot，而不是只拿最终的 `PreviewGameSyncContext`
- 在试听重触发时，同时刷新 preview 面板上的“当前生效来源”标签
- 在日志输出中加入简短诊断，例如：
  - `RTPC PlayerSpeed 命中 Emitter=6.0`
  - `Switch FootstepSurface 由 Global PlayerSpeed=10.0 映射到 Stone`
  - `State CombatState 命中 Global=Combat`

## 7.2 PreviewService

建议新增三类查询方法：

- `resolve_parameter_source(...)`
- `resolve_switch_resolution(...)`
- `build_preview_resolution_snapshot(...)`

其中：

- 现有求值主链继续负责返回最终播放结果
- 新增 snapshot 只负责给工具端解释“为什么是这个结果”
- snapshot 不参与导出，不进入 Unity runtime payload

## 7.3 MainWindow

建议把当前 preview bar 升级为“可解释的紧凑条”，不是简单堆更多控件。

需要新增的可视元素：

- RTPC 当前来源 chip
- State 作用域 chip（固定 Global）
- Switch 结果来源 chip
- Switch 映射参数来源 chip
- 一行摘要标签，用于显示“当前命中链路”

## 8. 数据与导出边界

本轮升级不修改以下边界：

- 不新增 editor-only 字段到导出结果
- 不把 preview resolution snapshot 写进 `.afproj` 或运行时 payload
- 不在 Schema 3 中新增“global switch”或“emitter state”字段
- 不把布局状态、调试状态、当前选择器状态写进导出契约

换句话说：

- 导出契约继续保持当前语义
- 工具侧增加的是“解释层”和“命名清晰度”
- runtime 增加的是“上下文边界清晰度”，不是重新发明第三套 GameSync 模型

## 9. 自动化验证升级

## 9.1 PreviewService 单测

至少补齐以下场景：

1. `Emitter parameter` 覆盖 `Global parameter`
2. `Emitter missing` 时 RTPC 回退到 `Global`
3. `Global missing` 时 RTPC 回退到 `Default`
4. 参数映射 Switch 在 `Emitter` 有值时命中 emitter 值
5. 参数映射 Switch 在 `Emitter` 无值时回退到 global 值
6. 参数映射 Switch 在两者都无值时回 default switch
7. 手动 emitter switch 覆盖参数映射 switch
8. State 始终只读取 global state

## 9.2 MainController / UI 单测

至少补齐以下场景：

1. 修改 preview scope 后，当前 audition session 会重触发
2. RTPC 面板可显示当前生效来源为 Emitter / Global / Default
3. State 面板固定显示 Global 作用域
4. Switch 面板可显示 Manual / Mapped / Default 三种结果来源
5. 当 mapping 走 global 回退时，UI 摘要文案正确

## 9.3 Unity validation

至少补齐以下场景：

1. `SetGlobalGameParameter` 可影响无 emitter 局部覆盖的事件
2. `SetEmitterGameParameter` 可覆盖 global 并影响同一参数的 emitter 级 RTPC
3. `SetState` 可统一改变多个 event / bus 的全局覆盖结果
4. `SetSwitch(emitter)` 可让两个不同 emitter 命中不同分支
5. 参数映射 switch 在 emitter 未设置局部参数时可回退 global 参数

## 10. 分阶段实施建议

### Phase A：语义与命名收口

目标：先把文档、API 命名和求值规则统一。

输出：

- 本升级书
- Runtime API 命名清单
- Preview 求值顺序说明
- 兼容命名策略

### Phase B：Preview 可解释性升级

目标：让试听面板能直接显示当前结果为什么成立。

输出：

- Preview resolution snapshot
- RTPC / State / Switch 来源 chip
- 简洁日志文案
- UI 单测覆盖

### Phase C：Runtime API 收口

目标：彻底切清 world 与 emitter 上下文。

输出：

- `SetEmitterGameParameter` / `GetEmitterGameParameter`
- 旧接口兼容转发
- Unity validation 与示例更新

### Phase D：联调与验收

目标：确保 authoring、preview、runtime 三边口径一致。

输出：

- 端到端试玩验证
- 文档同步
- SDK 对接说明补充

## 11. 验收标准

本轮升级完成的标志不是“界面上多了几个标识”，而是以下 6 条同时成立：

1. 团队成员能够一句话说明 RTPC / State / Switch 的作用域归属。
2. Preview 面板能够直接告诉用户当前命中的是 Emitter、Global 还是 Default。
3. Runtime API 命名不再让调用方猜测 scope。
4. Switch 的参数映射结果仍是个体的，但参数来源可清晰回退到 global。
5. 自动化测试能覆盖覆盖链、回退链和手动覆盖链。
6. 不新增任何 editor-only 字段进入导出契约。

## 12. 建议的对外口径

后续团队内外统一使用以下表述：

- RTPC：双作用域连续参数
- State：全局离散模式
- Switch：个体离散分支
- Switch 参数映射：个体结果，参数来源可回退 global

避免继续使用以下模糊说法：

- “Global 模式的 Switch”
- “State 的局部值”
- “一个统一 GameSync 参数区”

## 13. 配套阅读

- docs/internal/architecture/audioforge_第三期RTPC-State-Switch路线图.md
- docs/unity/architecture/UnityRuntime三期GameSync设计.md
- docs/internal/archive/audioforge_wwise兼容工作台映射.md
