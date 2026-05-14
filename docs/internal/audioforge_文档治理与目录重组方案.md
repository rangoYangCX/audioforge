# AudioForge 文档治理与目录重组方案

当前文档同步日期：2026-05-14

## 1. 结论先行

当前仓库的问题不是单纯“文档太多”，而是三类问题叠在一起：

- 入口过多：README、开发文档、使用说明、WSG 概述、速查文档都在承担“第一次该看什么”的职责。
- 生命周期混放：现状文档、历史实施计划、研究报告、发布记录同时平铺在同一层级，用户无法快速区分“当前真相”和“历史背景”。
- 受众边界重复：音频设计、Unity 研发、工具研发三类受众各自有主文档，但又被多份速查和概述文档重复覆盖。

因此这轮治理建议不要先按“文件名好不好看”处理，而是按两个维度收口：

- 受众：外部使用者、Unity 对接者、内部研发。
- 生命周期：canonical 主文档、专题参考、阶段设计、历史归档。

## 2. 治理原则

### 2.1 每个主题只保留一个 canonical 主文档

- 工具整体边界：开发文档。
- 工具使用方式：使用说明。
- Unity 对接：UnitySDK 对接规范。
- SDK 输出形态：UnitySDK 输出规范。
- 版本变化：CHANGELOG。

其他文档只能承担三类角色之一：

- 主文档的速查版。
- 主文档的专题补充。
- 历史设计或阶段记录。

### 2.2 速查文档只能服务高频场景，不能再承担完整说明

速查文档应该控制在“一屏到两屏能看完”的密度，只负责提醒用户最短路径、最常见坑和跳转入口，不再维护完整背景和完整边界说明。

### 2.3 完成态计划文档退出主目录

只要文档明确写了“已完成”“已落地第一轮”“后续主要作为记录保留”，它就不应该继续与当前主文档并列，应该移入 archive 或 history。

### 2.4 研究文档和规范文档分目录

研究、评估、蓝图、实施计划不应该与交付规范、接入文档、联调清单放在同一层。

## 3. 文件级判断

### 3.1 建议保留为 canonical 主文档

| 文件 | 处理建议 | 原因 |
| --- | --- | --- |
| `开发文档.md` | 保留，继续作为工具总体规范 | 当前仍是产品边界、架构、契约与交付总规范，虽然偏长，但主题明确。 |
| `docs/guides/AudioForge使用说明.md` | 保留，继续作为统一使用入口 | 面向多角色的“怎么用”说明最完整，适合做 repo 级用户入口。 |
| `docs/unity/UnitySDK对接规范.md` | 保留，继续作为 Unity 唯一主对接文档 | 文档内部已明确声明自己是 Unity 主文档，边界清楚。 |
| `docs/unity/UnitySDK输出规范.md` | 保留，继续作为 SDK 输出规范 | 这是独立主题，不能并入使用说明或 Unity 接入文档。 |
| `docs/operations/AudioForge日志与诊断暴露清单.md` | 保留为专题参考 | 这是诊断暴露规范，不是入口文档，但主题独立。 |
| `docs/operations/AudioForge容量评估与优化方案.md` | 保留为专题参考 | 这是容量专题，不应被合并进主文档。 |
| `CHANGELOG.md` | 保留 | 版本历史主锚点明确，不建议拆散到 docs 内。 |

### 3.2 建议升级但不删除

| 文件 | 处理建议 | 原因 |
| --- | --- | --- |
| `README.md` | 升级为总索引，不再承载大段现状描述 | 现在 README 已经部分重复使用说明和开发文档，应收口成仓库入口与导航页。 |
| `docs/operations/internal_release_execution_plan.md` | 升级为“当前发布执行手册”或移到 operations | 内容仍有价值，但验证基线停在 87 项，已明显过期。若继续保留，必须按 0.09.1 刷新。 |
| `docs/unity/architecture/UnityRuntime三期GameSync设计.md` | 保留并归入 runtime/architecture | 这是当前仍有价值的 runtime 设计文档，但目录应更语义化。 |
| `docs/internal/architecture/audioforge_Audio对象层Schema3迁移设计.md` | 保留并归入 architecture/decisions | 虽然是迁移设计，但 Schema 3 是现行主模型，这份设计仍有长期参考价值。 |
| `docs/internal/architecture/audioforge_第三期RTPC-State-Switch路线图.md` | 升级为“阶段总结 + 剩余路线”后再保留 | 当前大部分目标已落地，继续以“实施计划”命名会误导读者。 |

### 3.3 建议合并或降级为索引/速查

| 文件 | 处理建议 | 原因 |
| --- | --- | --- |
| `docs/AudioForge研发接入速查.md` | 合并进 `docs/AudioForge使用说明.md` 的研发入口章节，原文件降级为单页跳转索引或删除 | 其内容与 `docs/UnitySDK对接规范.md`、包内 `unity_package/Docs/研发接入速查.md` 重叠很高。 |
| `docs/AudioForge音频设计速查.md` | 合并进 `docs/AudioForge使用说明.md` 的音频设计入口章节，原文件降级为单页清单 | 适合作为速查，但不应再维护一套几乎平行的工作流说明。 |
| `docs/UnitySDK一期到当前变化总览.md` | 移入 migration/ 或并入 `docs/UnitySDK对接规范.md` 的迁移章节 | 这是非常明确的“迁移说明”，不应该继续和主规范并列成一级入口。 |
| `docs/Unity场景联调清单.md` | 保留，但降级为 Unity 对接文档的配套清单 | 它不是主文档，应该成为 Unity 对接规范下的验证附录或 validation 子目录文件。 |

### 3.4 建议归档，不再作为当前文档入口

| 文件 | 处理建议 | 原因 |
| --- | --- | --- |
| `docs/WSG_audiotest.md` | 归档，内容并入 README 或使用说明概述段 | 当前验证基线仍写 87 项，且主题与 README/使用说明高度重叠，已不是当前真相。 |
| `docs/internal/audioforge_第一期重构实施计划.md` | 归档 | 文档开头已明确“2026-04-30 已完成”。 |
| `docs/internal/audioforge_逐页面改造蓝图.md` | 归档 | 文档开头已明确第一轮页面化改造已落地，剩余内容更像历史蓝图。 |

### 3.5 建议整合后保留在 internal

| 文件 | 处理建议 | 原因 |
| --- | --- | --- |
| `docs/internal/audioforge_商业化改造清单.md` | 与 `audioforge_wwise兼容工作台映射.md` 整合为单一“桌面工具产品化路线图” | 两者都在描述桌面工具后续产品化方向，一个讲差距，一个讲映射，长期分开维护成本高。 |
| `docs/internal/audioforge_wwise兼容工作台映射.md` | 与 `audioforge_商业化改造清单.md` 整合 | 这是更具体的设计映射，适合成为产品化路线图中的一章。 |
| `docs/internal/audioforge_主流音频中间件评估与优化报告.md` | 保留到 research/ | 这是独立研究文档，不应与实施计划并列。 |

### 3.6 当前不建议直接删除的文件

以下文件虽然重叠或过时，但现阶段不建议直接物理删除，应先完成引用迁移：

- `README.md`
- `docs/AudioForge研发接入速查.md`
- `docs/AudioForge音频设计速查.md`
- `docs/UnitySDK一期到当前变化总览.md`
- `docs/Unity场景联调清单.md`
- `docs/WSG_audiotest.md`

原因是这些文件很可能已经被 README、包内文档、发布说明或外部交接流程引用。正确顺序应该是：先改入口和引用，再迁移或删除旧文件。

## 4. 建议的新目录结构

建议把 `docs/` 调整为“按主题 + 生命周期”混合分层：

```text
docs/
  README.md                       # 文档总索引
  guides/
    AudioForge使用说明.md
    AudioForge音频设计速查.md     # 若保留，则明确为 quick reference
    AudioForge研发接入速查.md     # 若保留，则明确为 quick reference
  unity/
    UnitySDK对接规范.md
    UnitySDK输出规范.md
    validation/
      Unity场景联调清单.md
    migration/
      UnitySDK一期到当前变化总览.md
    architecture/
      UnityRuntime三期GameSync设计.md
  operations/
    AudioForge日志与诊断暴露清单.md
    AudioForge容量评估与优化方案.md
    internal_release_execution_plan.md
  internal/
    architecture/
      audioforge_Audio对象层Schema3迁移设计.md
      audioforge_第三期RTPC-State-Switch路线图.md
    product/
      audioforge_桌面工具产品化路线图.md
    research/
      audioforge_主流音频中间件评估与优化报告.md
    archive/
      audioforge_第一期重构实施计划.md
      audioforge_逐页面改造蓝图.md
      WSG_audiotest.md
  releases/
    v0.05-github-release.md
    ...
```

说明：

- `guides/` 放用户面向的持续使用文档。
- `unity/` 放 SDK、接入、迁移、联调相关内容。
- `operations/` 放诊断、容量、发布执行等运行与交付文档。
- `internal/` 再按 architecture、product、research、archive 分层。
- `releases/` 保持版本历史独立，不和主题文档混放。

## 5. 推荐的合并方案

### 5.1 第一组合并：使用入口收口

目标：减少 repo 顶层入口文档数量。

建议动作：

- `README.md` 改成总索引，只保留项目定位、快速入口、运行命令、验证命令、文档地图。
- `docs/AudioForge使用说明.md` 继续承接完整使用流程。
- `docs/AudioForge音频设计速查.md` 和 `docs/AudioForge研发接入速查.md` 如果保留，应各自压到一页内，并在开头明确“这是速查，不是主说明”。

预期效果：

- 用户第一次进入时，只需要在 README 和使用说明之间做一次选择。

### 5.2 第二组合并：Unity 文档收口

目标：让 Unity 相关文档形成单一簇，而不是散在 docs 根目录。

建议动作：

- 保留 `UnitySDK对接规范.md` 为主文档。
- `Unity场景联调清单.md` 移到 validation 子目录。
- `UnitySDK一期到当前变化总览.md` 移到 migration 子目录。
- `UnityRuntime三期GameSync设计.md` 移到 architecture 子目录。

预期效果：

- Unity 接手人只要进入 `docs/unity/` 就能理解主文档、迁移、验证、架构四类信息。

### 5.3 第三组合并：内部产品化文档收口

目标：避免产品化方向文档互相重复。

建议动作：

- 合并 `audioforge_商业化改造清单.md`。
- 合并 `audioforge_wwise兼容工作台映射.md`。
- 将合并结果命名为 `audioforge_桌面工具产品化路线图.md`。
- `audioforge_逐页面改造蓝图.md` 只保留到 archive。

预期效果：

- 内部只维护一份桌面工具方向文档，不再在“差距清单”“设计映射”“页面蓝图”之间来回同步。

## 6. 删除与归档判断

### 6.1 删除候选

达到以下条件后，可以考虑直接删除：

- 文件内容已经被新的主文档完整吸收。
- 所有仓库内引用已改完。
- 包内文档或发布文档不再依赖旧路径。

当前最接近删除条件的文件：

- `docs/WSG_audiotest.md`
- `docs/AudioForge研发接入速查.md`（前提是使用说明和 Unity 对接规范已收口）
- `docs/AudioForge音频设计速查.md`（前提是使用说明已有足够紧凑的角色入口）

### 6.2 更推荐归档而不是删除的文件

- `docs/internal/audioforge_第一期重构实施计划.md`
- `docs/internal/audioforge_逐页面改造蓝图.md`
- `docs/internal/audioforge_第三期RTPC-State-Switch实施计划.md`（在改名为路线图前保留历史版本）

原因：这些文件属于设计和实施历史，对后续回顾决策脉络仍有价值。

## 7. 建议的执行顺序

### 第一步：先建索引，不先搬文件

- 新建 `docs/README.md` 作为文档地图。
- 把 README 的文档入口改成指向新的文档地图。

### 第二步：收口入口文档

- 压缩 README。
- 收口 `AudioForge使用说明.md`。
- 决定两份速查文档是保留为单页卡片，还是完全并入使用说明。

### 第三步：重排 Unity 文档目录

- 建 `docs/unity/` 子结构。
- 移动对接、迁移、验证、架构类文档。
- 修正 README、包内文档和发布说明引用。

### 第四步：整理 internal 生命周期

- 建 `architecture/`、`product/`、`research/`、`archive/`。
- 把已完成计划移入 archive。
- 合并产品化方向文档。

### 第五步：最后再删旧文件

- 确认没有残余引用。
- 再删除已被完全替代的旧文件。

## 8. 最终建议

如果只做一轮最小治理，我建议优先做下面 5 件事：

1. 把 `README.md` 收口成真正的导航页。
2. 新建 `docs/README.md` 作为文档总索引。
3. 归档 `docs/WSG_audiotest.md`、`docs/internal/audioforge_第一期重构实施计划.md`、`docs/internal/audioforge_逐页面改造蓝图.md`。
4. 把 Unity 相关文档集中到单一目录簇。
5. 合并 `audioforge_商业化改造清单.md` 与 `audioforge_wwise兼容工作台映射.md`。

这样能先解决 80% 的混乱来源，同时不需要一口气重写所有文档内容。