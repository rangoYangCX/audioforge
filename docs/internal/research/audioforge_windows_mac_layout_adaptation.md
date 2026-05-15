# AudioForge Windows / mac 布局与分辨率适配专项

## 背景

当前桌面端已经具备顶层窗口自适应能力，但 `mac` 上“片段编辑台”在中小分辨率下仍会出现编辑区被挤压的问题，尤其是音频波形编辑区域高度和宽度同时收缩后，操作按钮、时间参数和波形面板会堆叠得过于紧凑。

这说明现有适配主要解决了“窗口能否放进屏幕”，还没有系统解决“工作区内部在不同平台、不同可用宽高下如何重排”。

## 现状结论

### 1. 顶层窗口已有基础自适应，但范围有限

- `audioforge/app/views/main_window.py` 中的 `_adaptive_top_level_sizes(...)` 会按照屏幕 `availableGeometry()` 缩小窗口默认尺寸与最小尺寸。
- `audioforge/main.py` 在 `darwin` 下开启了 `QT_AUTO_SCREEN_SCALE_FACTOR=1` 和 `PassThrough` 的高 DPI rounding policy。
- 这套逻辑能避免窗口整体超出屏幕，但不会改变工作区内部控件的排布方式。

### 2. 当前问题主要出在片段编辑台内部布局不是响应式

相关实现集中在：

- `audioforge/app/views/main_window.py`
- `audioforge/app/widgets/clip_waveform_editor.py`

核心问题链路如下：

1. `ContentTopSplitter` 默认按 `[700, 360]` 分配“片段列表 / 片段编辑台”宽度。
2. 右侧 `clip_detail_group` 没有显式的“可用宽度断点”策略，窄屏下会继续被压缩。
3. 波形区下方是一整行高频操作按钮，按钮数量多、文案长，窄列时会显著抬高行高。
4. `ClipWaveformEditor` 虽然设置了 `Expanding`，但其父容器没有在窄宽度下做结构切换，最终表现为波形区被上方按钮和下方参数表单夹扁。

### 3. 现有 UI scale 不是这类问题的根解

- `main_window.py` 已有 `set_ui_scale(...)` 和 `_apply_wwise_style()`。
- 当前缩放主要影响 padding、字号、圆角和部分控件的最小尺寸。
- 这能缓和视觉密度，但不能替代“断点式重排”。
- 如果单纯在 `mac` 上降低 UI scale，只会把问题转成“字更小、仍然拥挤”。

## 根因判断

`mac` 上音频编辑窗口拥挤，不是单一平台 bug，而是以下三个因素叠加：

### A. 默认 splitter 比例偏向桌面宽屏

- `self._default_content_top_splitter_sizes = [700, 360]`
- 这组默认值在较宽窗口上可用，但对 13/14 寸 MacBook 常见可用宽度不够稳妥。
- 当左侧浏览器和顶部/底部容器也占据空间时，右侧详情列 360 的基准宽度会过早触发拥挤。

### B. 片段编辑台缺少窄屏模式

当前 `clip_detail_group` 内部是单列纵向堆叠：

- 头部摘要卡
- 波形编辑卡
- 元数据卡
- 底部动作行

这在宽度充足时成立，但在宽度不足时，没有任何一层会改成更紧凑的结构。

### C. 波形区操作条对窄宽度不友好

当前波形卡里一口气塞入：

- 播放头说明
- 起点/终点/循环相关动作
- 缩放动作

虽然这些按钮已标记 `role="clipCompactButton"`，但仍然是同一行横向布局，导致窄宽度时优先挤压波形编辑器本体。

## 专项目标

本专项建议目标不是“为 mac 单独写一套布局”，而是建立一套统一的桌面布局适配策略：

### 目标 1

同一份 UI 代码同时适配 Windows 和 mac，不引入大规模平台分叉。

### 目标 2

布局以“可用宽高”和“内容密度”为驱动，而不是以操作系统名为驱动。

### 目标 3

保证片段编辑台在以下场景下仍可用：

- 1280 x 800 级别可用区域
- 1440 x 900 级别可用区域
- 1080p Windows 常规缩放
- mac Retina + PassThrough rounding

## 推荐方案

## 一层：保留现有顶层自适应

现有 `_adaptive_top_level_sizes(...)` 应继续保留，它解决的是：

- 窗口初始大小
- 恢复几何时不越界
- 小屏幕下最小尺寸收缩

这一层无需推翻。

## 二层：为关键工作区补“响应式断点”

建议新增工作区级布局模式判断，例如：

- `wide`
- `medium`
- `compact`

判定维度优先使用容器实际可用宽度，其次再参考高度。例如针对片段编辑台容器：

- `>= 1180`: wide
- `900 - 1179`: medium
- `< 900`: compact

注意这里的判断对象应该是工作区内容容器，而不是整窗宽度。

## 三层：片段编辑台改为可切换结构

这是本专项的重点。

### wide

保持当前形态：

- 左侧片段列表
- 右侧片段编辑台
- 波形操作条单行展示

### medium

调整为更稳妥的比例：

- `ContentTopSplitter` 不再固定 `[700, 360]`
- 改成按比例分配，并为右侧详情列设置安全下限
- 例如右侧详情列目标宽度至少保持在 420 到 460 之间

### compact

片段编辑台内部切成紧凑模式：

1. 波形操作按钮改成两行或流式布局，不能继续强占单行。
2. 元数据卡与底部动作行允许折叠或下沉到独立页签。
3. 保证 `ClipWaveformEditor` 始终优先拿到一块稳定高度。
4. 必要时将“片段列表 / 片段编辑台”改成上下布局，或在 compact 下提供“列表 / 编辑”二级切换。

其中第 1 点优先级最高，因为它最直接影响当前 `mac` 拥挤现象。

## 四层：对 splitter 采用“比例 + 下限”而不是纯静态默认值

当前 `main_window.py` 中多处 splitter 默认值仍是写死数组。

建议对核心 splitter 统一改成：

- 默认比例
- 左右最小可用宽度
- 在布局 flush 时按当前可用宽度重新归一

以 `ContentTopSplitter` 为例，目标不是永远记住 `[700, 360]`，而是：

- 宽窗口下接近这个比例
- 窄窗口下保障右列不低于编辑器最低可用宽度
- 再窄时触发 compact 模式而不是硬压缩

## 五层：把平台差异收敛到“阈值微调”，不要分叉布局树

Windows / mac 的差异主要来自：

- 字体度量
- 控件默认内边距
- Retina / DPI rounding

建议只允许下面这种平台差异：

- mac 的 compact 阈值略高于 Windows
- mac 的按钮行更早进入两行模式

不建议出现：

- `if sys.platform == "darwin":` 走一套页面
- Windows 和 mac 分别维护两棵布局树

## 建议落地顺序

### 第一阶段：止血

目标：先解决 `mac` 上音频编辑区挤在一起。

建议改动：

1. 为 `clip_detail_group` 引入最低舒适宽度概念。
2. 为波形操作区增加 compact 模式，两行展示按钮。
3. 调整 `ContentTopSplitter` 的默认分配逻辑，让右列在中等窗口宽度下拿到更多空间。

这是最小可交付改造，收益最高。

### 第二阶段：抽象通用响应式策略

目标：把资源工作区、事件工作区、Bus 工作区统一纳入同一套断点体系。

建议能力：

1. 统一的 workspace density / layout mode 计算。
2. 核心页面根据 mode 重排按钮行、表单列数和 splitter 比例。
3. 状态持久化继续保存用户手动拖拽后的结果，但在低于某个宽度阈值时优先服从 compact 布局。

### 第三阶段：补全测试矩阵

新增布局测试不应只验证 splitter 状态持久化，还要验证“窄屏下是否切对模式”。

建议新增：

1. 小分辨率下 `ContentTopSplitter` 不会把右侧编辑列压到不可用。
2. compact 模式下波形操作区改为两行或紧凑容器。
3. `set_ui_scale(...)` 后布局模式仍然稳定，不会因为样式刷新回退。
4. Windows / mac 平台标志下阈值如有差异，测试要覆盖两边。

## 可验证假设

本专项当前最值得先验证的假设是：

> 只要让片段编辑台在窄宽度下切到 compact 布局，并保障右列最低舒适宽度，`mac` 上音频编辑窗口“挤在一起”的主观问题会明显缓解。

最低成本验证方式：

1. 在 `clip_waveform_action_row` 所在区域做一次窄屏双行重排。
2. 将测试窗口限制到 1280 x 800 或等效可用宽度。
3. 观察波形编辑器和时间参数区是否仍保持清晰可操作。

如果这一步无明显改善，再继续评估是否需要在 compact 下把“列表 / 编辑”改为上下结构或页签切换。

## 关联代码位置

- `audioforge/app/views/main_window.py`
  - `CurrentPageStack.sizeHint()` / `minimumSizeHint()`
  - `_adaptive_top_level_sizes(...)`
  - `ContentTopSplitter` 初始化
  - `clip_detail_group` / `clip_timing_card` / `clip_waveform_action_row`
  - `set_ui_scale(...)` / `_apply_wwise_style()`
- `audioforge/app/widgets/clip_waveform_editor.py`
  - `ClipWaveformEditor.sizeHint()`
  - `ClipWaveformEditor.minimumSizeHint()`
- `tests/unit/test_main_controller_layout.py`
  - 现有 splitter 持久化与顶层分辨率回归测试

## 建议结论

这次专项应定义为：

“建立 AudioForge 桌面工作区的跨平台响应式布局策略，并以片段编辑台为第一批治理对象。”

短期先修 `mac` 上最明显的片段编辑拥挤问题；中期把这套策略扩展到其他工作区，最终形成统一的 Windows / mac 分辨率适配基线。