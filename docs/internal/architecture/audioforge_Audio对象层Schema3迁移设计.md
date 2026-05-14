AudioForge Audio 对象层 Schema 3 迁移设计

当前文档同步日期：2026-05-14

1. 目标

本轮迁移把当前“事件内嵌 Audio 子对象”的结构，升级为“项目级 Audio Object + Event 引用 AudioId”的正式模型。

迁移目标如下：

- 事件只保留触发行为和播放控制，不再直接承载声音内容。
- Audio Object 成为项目级一等对象，负责承载播放模式、源音频集合、GameSync 绑定和声音属性。
- 编辑器对象浏览从“源音频 -> 事件绑定”升级为“源音频 -> Audio Object -> Event 引用”。
- 导出契约升级为 SchemaVersion 3，运行时直接消费 AudioObjects 和 Events[AudioId]，不再读取嵌套 Audio 或扁平镜像字段。
- 本轮不考虑旧工程和旧运行时兼容；所有 editor、export、runtime、validation 都按新契约迁移。

2. 新对象模型

2.1 Event

Event 只保留动作层字段：

- Id
- DisplayName
- MaxInstances
- CooldownSeconds
- StealPolicy
- Notes
- AudioId

Event 不再持久化以下字段：

- Bus
- PlayMode
- AvoidImmediateRepeat
- VolumeDb / VolumeRandDb
- PitchCents / PitchRandCents
- ComboPitchStepCents / ComboResetSeconds / ComboMaxStep
- LoadPolicy
- Clips
- RtpcBindings
- StateOverrides
- SwitchVariants

2.2 Audio Object

Audio Object 作为项目级对象持久化，字段如下：

- Id
- DisplayName
- Bus
- PlayMode
- AvoidImmediateRepeat
- VolumeDb
- VolumeRandMinDb
- VolumeRandMaxDb
- PitchCents
- PitchRandMinCents
- PitchRandMaxCents
- ComboPitchStepCents
- ComboResetSeconds
- ComboMaxStep
- LoadPolicy
- Clips
- RtpcBindings
- StateOverrides
- SwitchVariants

2.3 当前关系约束

本轮迁移先固化以下关系：

- 一个 Event 必须引用一个 Audio Object。
- 一个 Audio Object 可以被多个 Event 引用。
- 源音频永远挂在 Audio Object 下，不直接挂在 Event 下。

3. 编辑器迁移范围

3.1 对象浏览器

对象浏览器调整为四个核心对象面：

- 总线树
- 源音频树
- Audio 树
- 事件树

迁移后的浏览规则：

- 源音频树显示源文件及其被哪些 Audio Object 引用。
- Audio 树显示 Audio Object，本体负责源音频拖拽、多选追加、播放模式切换、GameSync 绑定和属性编辑。
- 事件树显示 Event 和它引用的 Audio Object 摘要，但事件本身不再承载源音频绑定编辑。
- Event 展开不再弹“当前事件的 Audio 绑定”，而是跳到或打开对应 Audio Object 编辑界面。

3.2 属性编辑器

属性编辑拆成两层：

- Event 属性页：只编辑事件 ID、显示名、Cooldown、MaxInstances、StealPolicy、Notes、Audio 引用。
- Audio 属性页：编辑播放模式、Bus、音量、音高、LoadPolicy、AvoidImmediateRepeat、Clips、RTPC、State、Switch。

3.3 源音频交互

迁移后的合法操作：

- 从源音频树多选拖到 Audio Object。
- 在 Audio 编辑器内追加、替换、删除源音频。
- 在 Event 上只能切换引用哪个 Audio，不允许直接往 Event 拖源音频。

3.4 外部拖拽导入矩阵

本轮把“外部文件夹 / 外部音频文件”拖拽行为统一收口为三条入口：

- 拖到事件树：保持现有行为，直接创建 Event + Audio Object + 初始源音频绑定。目录结构会映射为事件目录层级。
- 拖到 Audio 树空白区或根级区域：先创建 Audio Object，再询问是否同时创建同名 Event。选择“是”时，导入结果与事件树导入共享同一套命名和目录映射规则；选择“否”时，只创建 Audio Object，并注册对应源音频资产。
- 拖到已有 Audio Object：不再询问是否创建 Event。若目标 Audio 已存在源音频，则询问“替换”还是“追加”；无论选择哪种模式，都只改动目标 Audio Object 的源音频集合。
- 拖到源音频树：只注册到 asset_registry，不创建 Event，不创建 Audio Object。该资源初始显示为“未引用资源”，供后续拖到 Audio Object 时复用。

3.5 未引用资源语义

为支持内置资源库工作流，源音频树的条目状态改为按 Audio Object 语义定义：

- 只要 source_path 已进入 asset_registry，就允许出现在源音频树中。
- 当某个 source_path 尚未被任何 Audio Object 的 Clips 引用时，条目标记为“未引用资源”。
- 当某个 source_path 被一个或多个 Audio Object 引用时，引用统计显示“引用 Audio 数”，而不是“引用 Event 数”。
- Event 只作为 Audio Object 的上层引用信息展示；source browser 的 event_ids 来自“引用该 Audio Object 的 Event 集合”，而不是直接对 source_path 建立事件级绑定。

4. Schema 3 导出契约

4.1 顶层结构

AudioData.json 顶层结构调整为：

- SchemaVersion
- ProjectName
- RuntimeAudioFormat
- Buses / BusConfigs
- GameParameters
- StateGroups
- SwitchGroups
- AudioObjects
- Events

4.2 Events

Events 只输出动作层字段：

- EventId
- MaxInstances
- CooldownSeconds
- StealPolicy
- AudioId

4.3 AudioObjects

AudioObjects 输出所有声音层字段：

- AudioId
- DisplayName
- Bus
- PlayMode
- AvoidImmediateRepeat
- VolumeDb
- VolumeRandDb
- PitchCents
- PitchRandCents
- LoadPolicy
- ComboPitchStepCents
- ComboResetSeconds
- ComboMaxStep
- DefaultClipIds
- Clips
- RtpcBindings
- StateOverrides
- SwitchVariants

5. Runtime 迁移范围

5.1 JSON 适配

JsonAdapter 必须：

- 先读 AudioObjects，建立 AudioId -> AudioObjectConfig 索引。
- 再读 Events，通过 AudioId 绑定到对应 Audio Object。
- AudioId 缺失或找不到时直接视为契约错误，不做旧字段回退。

5.2 运行时求值

运行时求值链改为：

- Event 决定是否允许触发。
- Audio Object 决定播放模式、候选 Clip、GameSync 调制和最终混音属性。
- 活动声部记录 EventId 和 AudioId，便于后续做 Audio 级调试和复用分析。

5.3 调试与日志

调试记录至少新增：

- AudioId
- AudioDisplayName

6. Python editor 迁移顺序

第一批：核心数据层

- audio_project.py
- project_serializer.py
- exporter.py
- preview_service.py
- validator.py

第二批：编辑器工作流

- main_controller.py
- main_window.py
- source_tree.py
- event_tree.py
- 新增 audio_tree.py 或等价 Audio 浏览器部件

第三批：工具链与验证

- run_full_chain_check.py
- smoke / sample project builder
- 全量单元测试和 UI 回归

7. 非目标

本轮不做以下扩展：

- 一次触发多个 Audio Object。
- Audio Object 层级嵌套容器。
- Event 内混合多个 Audio 引用策略。
- 旧 `.afproj` 自动迁移器。

8. 迁移完成判定

迁移完成后，以下条件必须同时成立：

- `.afproj` 中 Event 不再内嵌 Audio 内容，只保留 AudioId。
- 导出 AudioData.json 中 Event 不再嵌套 Audio，也不再保留扁平镜像字段。
- Runtime 只从 AudioObjects + Events[AudioId] 解析声音层配置。
- Editor 中源音频绑定入口只挂在 Audio Object，不再挂在 Event。
- Source browser 的引用统计从“引用事件数”改为“引用 Audio 数”。