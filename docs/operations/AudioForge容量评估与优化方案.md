# AudioForge 容量评估与优化方案

当前文档同步日期：2026-05-14

当前适用版本：AudioForge 0.09.1

## 1. 文档定位

这份文档用于回答两个问题：

1. 当前 AudioForge 大致支持什么量级的导出。
2. 如果要继续往更大规模推进，后续应该优先做哪些优化。

本文档的重点不是给出一个绝对上限数字，而是给出基于当前实现、当前架构和本地基准的容量判断区间。

## 2. 结论摘要

### 2.1 当前结论

- 当前实现没有看到针对事件数、Audio Object 数或资源数的硬编码导出上限。
- 导出链路已经实测通过低五位量级，也就是 `10000` 个事件 / `10000` 个运行时资源这一档。
- 如果是 `wav -> wav` 且无 `trim / fade` 的直拷贝快路径，当前导出吞吐接近线性增长。
- 如果大量资源需要裁剪、淡入淡出或转码，吞吐会明显下降，当前应按更保守的规模估计。
- 从“能导出多少”看，当前实现已具备几千到一万级导出能力。
- 从“日常作者体验还能否顺手”看，当前更建议把常态工作规模控制在低千到几千这一档。

### 2.2 推荐口径

- 舒适规模：`1000 - 3000` 个独立运行时资源。
- 可管理规模：`3000 - 8000` 个独立运行时资源。
- 已验证可导出规模：`10000` 个独立运行时资源。
- 不建议直接宣传的规模：`10000+` 作为常态编辑规模。

原因很简单：当前先到瓶颈的更可能是编辑器的整树刷新、全量校验和大列表交互，而不是导出器本身。

## 3. 评估口径说明

这份评估默认讨论的是“运行时导出规模”，也就是：

- Event 数量。
- Audio Object 数量。
- 最终导出的独立资源数量。

需要注意三件事：

1. Event 数和独立资源数不是同一个概念。
2. 如果多个 Event 复用同一个 Audio Object 或同一批源资源，事件数可以比资源数更高。
3. 如果每个 Event 都对应唯一资源，那么 Event 数、Audio Object 数和导出资源数会大致同阶增长。

## 4. 当前实现依据

### 4.1 没看到导出数量硬上限

当前导出器的核心数据结构 `ExportPlan` 会记录：

- `TotalEventCount`
- `TotalAssetCount`
- `RebuiltAssetKeys`
- `ReusedAssetKeys`

它们都按集合和列表处理，没有看到“事件数最多多少”或“资源数最多多少”的硬编码限制。[audioforge/app/services/exporter.py](audioforge/app/services/exporter.py#L28) [audioforge/app/services/exporter.py](audioforge/app/services/exporter.py#L74)

### 4.2 当前导出链路是线性批处理模型

当前 `RuntimeExporter` 的路径大致是：

1. 收集当前工程的 asset entries。
2. 计算本次导出计划。
3. 写临时导出目录。
4. 按资产逐个 materialize。
5. 原子提交到正式导出目录。

相关核心实现位于：[audioforge/app/services/exporter.py](audioforge/app/services/exporter.py#L354) [audioforge/app/services/exporter.py](audioforge/app/services/exporter.py#L619) [audioforge/app/services/exporter.py](audioforge/app/services/exporter.py#L671)

这条链路的特征是：

- 没有硬上限。
- 当前是单进程、单条资源处理主链。
- 资源数增长时，耗时大致线性增长。

### 4.3 当前有快路径和慢路径两种吞吐形态

当源格式和目标格式相同，且资源没有 `trim / fade` 时，导出器会直接 copy，不做重编码。[audioforge/app/services/audio_processor.py](audioforge/app/services/audio_processor.py#L20) [audioforge/app/services/audio_processor.py](audioforge/app/services/audio_processor.py#L27) [audioforge/app/services/audio_processor.py](audioforge/app/services/audio_processor.py#L51)

当资源带 `trim / fade`，或者目标格式需要重新写出时，当前会走读入、裁剪、应用淡入淡出、再写回的慢路径。[audioforge/app/services/audio_processor.py](audioforge/app/services/audio_processor.py#L31) [audioforge/app/services/audio_processor.py](audioforge/app/services/audio_processor.py#L44)

这意味着容量评估必须至少拆成：

- 快路径容量。
- 处理路径容量。

### 4.4 当前编辑器树控件不是虚拟化结构

事件树、Audio 树、源音频树的刷新当前都是 `clear()` 后整树 `rebuild()`，不是大数据量下的虚拟化或分页模型。[audioforge/app/widgets/event_tree.py](audioforge/app/widgets/event_tree.py#L73) [audioforge/app/widgets/audio_tree.py](audioforge/app/widgets/audio_tree.py#L61) [audioforge/app/widgets/source_tree.py](audioforge/app/widgets/source_tree.py#L109)

这会直接影响：

- 打开大工程后的首屏刷新。
- 搜索过滤。
- 选择同步。
- 批量编辑后的回刷。

所以“能导出一万资源”并不自动等于“还能流畅编辑一万资源”。

## 5. 本次本地基准

### 5.1 测试环境说明

本次评估使用现有模型和导出器，在仓库本地临时构造 synthetic project，再直接跑 `RuntimeExporter.export()`。

这不是完整 UI 交互压测，而是导出链路压测。

### 5.2 测试结果

#### 快路径：`wav -> wav` 且无 `trim / fade`

- `1000` 事件 / `1000` 资源：约 `1.77s`
- `5000` 事件 / `5000` 资源：约 `8.78s`
- `10000` 事件 / `10000` 资源：约 `18.11s`

对应 JSON 规模大致为：

- `1000`：`AudioData.json` 约 `1.0 MB`，`AudioManifest.json` 约 `0.66 MB`
- `5000`：`AudioData.json` 约 `5.0 MB`，`AudioManifest.json` 约 `3.32 MB`
- `10000`：`AudioData.json` 约 `10.17 MB`，`AudioManifest.json` 约 `6.71 MB`

#### 慢路径：带 `trim + fade` 处理

- `1000` 事件 / `1000` 资源：约 `4.23s`

这说明在当前机器上，处理型资源相较快路径至少慢约 `2x`，真实项目如果资源时长更长、格式更重，差距还会继续扩大。

### 5.3 基准结论

- 当前导出器已经证明 `10000` 量级可以导出。
- 当前快路径吞吐近似线性。
- 当前慢路径在 `1000` 量级仍可接受，但继续放大时需要更谨慎。

## 6. 当前容量判断

### 6.1 推荐支持规模

如果以“项目真实日常使用”作为标准，而不是只看导出是否能跑通，我建议对外采用以下口径：

#### A. 舒适规模

- `1000 - 3000` 个独立运行时资源。

这个区间内：

- 导出压力可控。
- JSON 体量可控。
- 事件树 / 资源树 / Audio 树仍有较大概率保持可用。
- 全量校验和差异预览也更容易维持在可接受时间内。

#### B. 可管理规模

- `3000 - 8000` 个独立运行时资源。

这个区间内：

- 导出本身仍然可行。
- 更依赖增量构建和资源复用。
- 对工程组织和命名纪律要求更高。
- UI 刷新、搜索和批量操作更容易成为先到瓶颈的部分。

#### C. 已验证极限导出规模

- `10000` 个独立运行时资源。

注意这里的含义是“当前导出器已经证明能跑通”，不是“推荐把一万资源当作当前产品的常态编辑规模”。

### 6.2 保守结论

如果你需要一个给项目经理、发行或外部合作方更稳妥的说法，可以直接写成：

“当前 AudioForge 建议面向低千到几千音效规模项目使用；导出链路已验证到一万级资源，但大规模工程下的编辑体验优化仍在后续路线中。”

## 7. 当前瓶颈拆解

### 7.1 导出器瓶颈

当前导出器的主要瓶颈是：

- 资产处理是逐条执行。
- 慢路径需要真实读写音频内容。
- 当前会把 asset entries、runtime payload、manifest payload 都整体构造在内存中。

这意味着规模继续扩大时，最先上升的是：

- 导出耗时。
- 峰值内存。
- 大量小文件写入的 IO 成本。

### 7.2 UI 瓶颈

当前 UI 更可能成为真实使用中的先到瓶颈：

- 三棵树控件整树 rebuild。
- 搜索和筛选是当前数据结构上的遍历式处理。
- 批量修改后的回刷成本随对象数增长。

### 7.3 校验与差异预览瓶颈

当前校验、构建计划预览、manifest 对比也会随着事件和资源数量增长而线性放大。

### 7.4 运行时交付体积瓶颈

当 `AudioData.json` 和 `AudioManifest.json` 继续扩大时：

- Unity 侧首轮读取成本会上升。
- 包内审阅和版本对比成本会上升。
- 大型项目中更需要按模块分层，而不是一直堆单体大表。

## 8. 后续优化方案设计

下面这部分按优先级和实施收益来排。

### 8.1 P0：建立正式容量基线

目标：先把“当前到底能撑多少”变成可重复验证的事实，而不是临时结论。

建议做法：

1. 新增正式的容量基准脚本，例如 `tools/run_capacity_benchmark.py`。
2. 固定几组标准用例：
   - `1k` 快路径
   - `5k` 快路径
   - `10k` 快路径
   - `1k` 处理路径
   - `5k` 处理路径
3. 输出统一 JSON 报告：
   - 总事件数
   - 总资源数
   - 导出耗时
   - 产物大小
   - 峰值内存
4. 把它接进内部发布检查，而不是只靠人工临时跑。

预期收益：

- 能把容量口径固定下来。
- 后续优化可以量化比较前后收益。

### 8.2 P1：导出链路性能优化

目标：先优化真正影响大工程交付时间的部分。

建议拆成四项：

#### 方案 A：并行化资源物化

- 对直拷贝资源做并行 copy。
- 对需要处理的资源使用受控 worker 池。
- 维持主线程只负责计划、日志聚合和提交。

注意点：

- 日志要带 `correlation_id` 和 `asset_key`。
- 保证失败时仍能安全中止和清理临时目录。

#### 方案 B：哈希与指纹缓存

- 当前已经有 `BuildFingerprint`，但文件 hash 仍会在计划阶段重复计算。
- 可引入持久化缓存，例如基于 `source_path + size + mtime` 的哈希缓存。

收益：

- 大工程反复增量构建时明显减少准备阶段时间。

#### 方案 C：manifest / runtime payload 分段生成

- 当前 payload 偏整批内存构造。
- 后续可考虑分段生成 JSON 或至少延后部分中间对象构造。

收益：

- 降低峰值内存。

#### 方案 D：资源分组与 profile 化构建

- 为项目提供构建 profile，例如 UI / Battle / BGM。
- 让大工程更容易按模块交付，而不是永远操作全量单体工程。

### 8.3 P1：作者体验优化

目标：让 UI 侧不要先于导出器崩在大工程上。

建议做法：

#### 方案 A：树控件增量刷新

- 从“整树 rebuild”升级为局部增量刷新。
- 对单对象修改、批量编辑、导入追加走局部 patch，而不是全部清空重建。

#### 方案 B：大列表虚拟化 / 延迟加载

- 事件树、Audio 树、源音频树改成模型驱动且支持分页或虚拟化。
- 折叠节点不提前构造全部子项。

#### 方案 C：索引化搜索

- 当前搜索和过滤可进一步用缓存索引，而不是每次全量文本遍历。

#### 方案 D：大工程保护阈值

- 当事件数、资源数超过阈值时，主动提示使用增量构建、分组视图或局部工作区。

### 8.4 P2：架构级扩展能力

目标：为一万级以上长期维护的工程做准备。

建议做法：

#### 方案 A：模块化工程

- 支持把一个大工程拆为多个子工程或逻辑包。
- 最终可导出到同一运行时目录或多 bundle 结构。

#### 方案 B：共享资源池

- 让跨模块可复用资源走统一资源池，而不是在多个工程里重复复制。

#### 方案 C：更细的运行时装载单元

- 运行时不必永远读取一个超大单体数据文件。
- 可以逐步演进为基础索引 + 分包数据。

### 8.5 P2：运行时交付优化

目标：避免编辑器能导出，但 Unity 侧初始化和排查开始吃力。

建议做法：

- 增加分模块 manifest。
- 增加资源分组加载策略。
- 为大工程输出更强的调试摘要和索引报告。
- 在 Unity runtime 侧加入更明确的加载耗时和解析耗时记录。

## 9. 推荐实施顺序

如果只按投入产出比排序，我建议是：

1. 正式容量 benchmark 脚本。
2. 导出链路并行化与 hash 缓存。
3. 树控件增量刷新。
4. 大工程保护阈值和 profile 化构建。
5. 模块化工程与分包运行时。

