# AudioForge 使用说明

当前文档同步日期：2026-05-14

当前适用版本：AudioForge 0.09.1

## 0. 速查入口

- 文档总索引：`docs/README.md`
- 音频设计速查：`docs/guides/AudioForge音频设计速查.md`
- 研发接入速查：`docs/guides/AudioForge研发接入速查.md`
- 日志与诊断暴露清单：`docs/operations/AudioForge日志与诊断暴露清单.md`
- 容量评估与优化方案：`docs/operations/AudioForge容量评估与优化方案.md`

## 1. 文档定位

这是一份面向三类同学的统一使用说明：

- 音频设计：关注工程创建、事件设计、试听、校验、构建与交付。
- Unity / 客户端研发：关注导出产物、运行时接入、联调方式与问题定位。
- 工具链 / TA / 技术研发：关注工程模型、构建链路、脚本命令、验证基线与协作边界。

如果你第一次接触 AudioForge，建议先读本文档，再按需要继续阅读：

1. `docs/unity/UnitySDK对接规范.md`
2. `开发文档.md`
3. `CHANGELOG.md`
4. `unity_package/README.md`
5. `unity_validation/README.md`

本文档的目标不是替代这些技术文档，而是把“怎么用”这件事讲完整，帮助音频和研发围绕同一套导出契约协作。

## 2. AudioForge 是什么

AudioForge 是一个面向 Unity 项目的数据驱动音频工作台。它的核心思路是：

- 音频设计同学在工具里维护事件、声音对象、总线和 GameSync。
- 工具负责校验、构建、导出和本地试听。
- Unity 运行时只消费导出结果，不读取 `.afproj`，也不依赖 Python 工具源码。

当前主线已经冻结到 Schema 3，核心模型是“Event 负责触发行为，Audio Object 负责声音层配置”。这意味着：

- Event 不再承载全部声音细节，而是通过 `AudioId` 引用一个 Audio Object。
- Audio Object 负责 Bus、PlayMode、Clips、GameSync 绑定和大部分声音参数。
- Unity 运行时当前正式消费的是 `AudioObjects + Events[AudioId]`。

## 3. 你会接触到哪些核心对象

### 3.1 工程文件

- `.afproj`：AudioForge 工程文件，只给工具端使用。
- 同名工程目录：与 `.afproj` 配套的工程资源目录，当前主要承载 `Sources/` 下的已收纳源音频。
- `AudioData.json`：运行时主数据，Unity 端唯一真源。
- `AudioManifest.json`：导出清单和资源审计信息。
- `BuildReport.json`：本次构建范围、复用情况、差异信息。
- `AudioEventID.cs`：可选的事件常量文件。

### 3.2 编辑期核心概念

- Event：运行时触发入口，负责动作层语义，例如 `MaxInstances`、`CooldownSeconds`、`StealPolicy`、`AudioId`。
- Audio Object：声音层主对象，负责 Clip、PlayMode、Bus、GameSync、音量音高等配置。
- Source Asset：源音频资源库里的原始文件，不直接等于 Event。
- Bus：混音层级，用于组织输出、音量、静音和路由。
- RTPC / State / Switch：当前 phase3 的 GameSync 能力，分别对应连续参数、全局离散状态和 emitter 级离散分支。

### 3.3 三棵主要浏览树

- Bus 树：管理总线层级和输出关系。
- Audio 树 / 事件相关对象面：管理声音对象和其绑定关系。
- 源音频树：管理导入后的源文件和引用状态。

使用上要记住一条：源音频只是素材，真正参与运行时的是 Event 和 Audio Object。



## 4. 10 分钟快速上手

如果你只想先跑通一次最小闭环，按这个顺序做：

1. 新建或打开一个 `.afproj` 工程。
2. 第一次保存工程，确认 `.afproj` 旁边已生成同名工程目录；后续迁移工程时，必须把这两者一起移动。
3. 设置导出目录，默认可以先用仓库根目录下的 `Export/`。
4. 在事件树或 Audio 树中导入一批 `wav` / `ogg`。
5. 创建一个 Event，并确认它关联了正确的 `AudioId`。
6. 为该 Audio Object 选择 Bus、PlayMode 和至少一个有效 Clip。
7. 点击试听，确认有声音并观察响度监视器。
8. 执行校验，先把 `Error` 清零。
9. 执行构建，确认导出目录生成 `AudioData.json`、`AudioManifest.json`、`BuildReport.json`、`AudioEventID.cs` 和 `Assets/`。
10. 把导出目录交给 Unity，同步最小接入说明。

如果这 9 步都通了，说明工具端最小主链已经跑通。

## 5. 音频设计同学的日常工作流

### 5.1 创建或打开工程

- 新建工程时，先确定工程名、默认导出目录、运行时格式和默认 Bus 策略。
- 如果是已有项目，优先打开最新 `.afproj`，不要手工修改导出的 `AudioData.json` 反向作为唯一工作底稿。
- 异常退出后若工具提示自动恢复，先确认恢复内容是否正确，再继续编辑。
- 当前保存工程会自动把引用到的源音频收纳到同名工程目录；如果你准备换机器或归档工程，直接整体移动 `.afproj` 和同名目录即可。

### 5.2 组织对象结构

推荐的组织方式：

- 事件树按业务域拆分，例如 UI、Battle、BGM、Ambience。
- Audio Object 按实际可复用声音语义组织，而不是单纯按文件名堆放。
- Bus 保持较稳定的混音层级，例如 Master、BGM、SFX、UI、Voice。

实践上建议做到两件事：

- Event Id 稳定且可读，不要频繁重命名已接入代码的事件。
- Audio Object 和源音频资产可以随着设计调整，但 Event Id 应尽量保持对研发稳定。

### 5.3 导入源音频

当前导入主流程支持 `wav` 和 `ogg`。导入时要注意：

- 拖到事件树：通常会创建 Event 和相关 Audio 关联。
- 拖到 Audio 树：可只建 Audio，也可连同同名 Event 一起创建。
- 拖到源音频树：只入资源库，不创建引用对象。

建议先把素材整理进源音频树，再决定哪些素材需要进入 Audio Object 和 Event 层。

### 5.4 配置 Event 和 Audio Object

Event 侧重点：

- `Event ID`
- `AudioId`
- `MaxInstances`
- `CooldownSeconds`
- `StealPolicy`
- 备注和协作说明

Audio Object 侧重点：

- Bus
- PlayMode
- Clip 集合
- 音量 / 随机音量
- 音高 / 随机音高
- GameSync 绑定
- 子项效果和声音层备注

如果你发现“这个参数更像声音层规则，而不是触发规则”，优先把它理解为 Audio Object 配置，而不是继续堆在 Event 上。

### 5.5 选择播放模式

当前主要播放模式包括：

- OneShot：单次触发，通常只允许一个有效主绑定。
- Random：多 Clip 随机命中，可配合权重和避免连续重复。
- Sequence：按顺序轮转，适合有明确播序的反馈音。
- Combo：连续触发时按步进演进，适合连击或叠加反馈。

选择时的经验规则：

- UI 点击音通常先从 Random 或 OneShot 开始。
- 明确轮播反馈用 Sequence。
- 连续打击、叠层反馈用 Combo。
- 不要为了“看起来高级”滥用 Combo，先确认业务真的需要时间连续语义。

### 5.6 编辑 Clip

Clip 层当前常见可编辑内容包括：

- 权重
- 资源键
- 导出路径
- `TrimStartMs`
- `TrimEndMs`
- `FadeInMs`
- `FadeOutMs`
- 循环区间与相关元数据

几点建议：

- 先确定素材是否真的需要裁剪，再动 `Trim`。
- 需要平顺起收音时再使用 `FadeIn` / `FadeOut`，避免所有素材都机械加淡入淡出。
- 导出前重点检查资源键和导出路径是否稳定，避免下游资源加载映射混乱。

### 5.7 配置 Bus

Bus 主要用于混音组织，而不是替代事件分组。推荐做法：

- Bus 结构保持少而稳，不要按每个小事件建一个 Bus。
- 父子 Bus 用来表达真正的混音层级。
- 经常切换观察时利用当前 Bus、路由和有效输出视图，不要只盯最终音量值。

遇到总线相关问题时，先看三件事：

- 当前 Bus 是否静音。
- 父 Bus 链上是否有人静音或衰减过大。
- 事件是否被路由到了预期 Bus。

### 5.8 配置 GameSync

当前 phase3 已支持：

- RTPC：连续参数，例如速度、强度、距离。
- State：全局离散模式，例如战斗中、暂停中、胜利态。
- Switch：emitter 级离散选择，例如脚步材质、武器类型。

建议的使用边界：

- 会连续变化的量用 RTPC。
- 对全局生效的离散上下文用 State。
- 依赖对象局部上下文的分支选择用 Switch。

如果一个需求既不是连续值，也不是明确的离散模式，就先不要硬塞进 GameSync，先确认是否只是普通事件拆分更清晰。

### 5.9 本地试听与响度观察

试听时建议关注三层：

- 是否命中预期 Clip。
- 事件行为是否符合 Random / Sequence / Combo 预期。
- 处理后响度是否在可接受范围内。

当前工具端试听具备以下特点：

- 会尽量对齐运行时事件语义。
- 当前音高相关参数按保时长变调提供参考听感。
- 响度监视器支持源文件与事件后结果双读数。

因此试听的目标是“尽量接近运行时语义”，而不是把工具端当作最终游戏内混音结果的唯一标准。

### 5.10 校验与修复

日常建议遵循这个顺序：

1. 先在对象编辑时即时修明显问题。
2. 再执行全量校验。
3. 先清 `Error`，再判断 `Warning` 是否需要本轮处理。

常见校验问题包括：

- Event Id 非法或重复。
- 源文件缺失。
- Clip 集合为空或无有效绑定。
- 权重异常。
- Combo 参数越界。
- Bus 不存在或路由不合法。
- 峰值或增益可能导致失真。

### 5.11 构建与导出

当前支持三种构建范围：

- 全量构建
- 增量构建
- 选中构建

推荐使用方式：

- 日常局部调整优先用增量构建。
- 交付前至少跑一次全量构建。
- 选中构建只适合明确知道影响面的局部迭代，不适合临近发版时做全局签收。

构建成功后，重点确认这些产物：

- `AudioData.json`
- `AudioManifest.json`
- `BuildReport.json`
- `AudioEventID.cs`
- `Assets/`

交付前最好额外看一次 `BuildReport.json`，确认本次是按预期范围重建，而不是被脏资源自动放大范围。

