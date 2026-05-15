# AudioForge 文档总索引

当前文档同步日期：2026-05-14

## 1. 第一次进入仓库先看什么

如果你是第一次接手这个仓库，按这个顺序读：

1. `../README.md`
2. `guides/AudioForge使用说明.md`
3. `../开发文档.md`
4. `../CHANGELOG.md`

## 2. 按角色阅读

### 音频设计

- 主说明：`guides/AudioForge使用说明.md`
- 快速检查：`guides/AudioForge音频设计速查.md`
- 诊断与日志：`operations/AudioForge日志与诊断暴露清单.md`

### Unity / 客户端研发

- 主对接文档：`unity/UnitySDK对接规范.md`
- 迁移差异：`unity/migration/UnitySDK一期到当前变化总览.md`
- 场景联调：`unity/validation/Unity场景联调清单.md`
- 输出规范：`unity/UnitySDK输出规范.md`
- 快速接入：`guides/AudioForge研发接入速查.md`

### 工具研发 / TA / 内部维护

- 总体边界：`../开发文档.md`
- 发布执行：`operations/internal_release_execution_plan.md`
- Schema 3 设计：`internal/architecture/audioforge_Audio对象层Schema3迁移设计.md`
- GameSync 路线：`internal/architecture/audioforge_第三期RTPC-State-Switch路线图.md`
- 桌面工具产品化：`internal/product/audioforge_桌面工具产品化路线图.md`
- 结果坞专项：`internal/product/audioforge_底部结果坞极简重构专项开发说明.md`
- 中间件评估：`internal/research/audioforge_主流音频中间件评估与优化报告.md`

## 3. 按主题阅读

### 使用与接入

- `guides/AudioForge使用说明.md`
- `unity/UnitySDK对接规范.md`
- `unity/UnitySDK输出规范.md`

### 验证与运维

- `operations/AudioForge日志与诊断暴露清单.md`
- `operations/AudioForge容量评估与优化方案.md`
- `operations/internal_release_execution_plan.md`

### 架构与设计

- `internal/architecture/audioforge_Audio对象层Schema3迁移设计.md`
- `internal/architecture/audioforge_第三期RTPC-State-Switch路线图.md`
- `internal/product/audioforge_底部结果坞极简重构专项开发说明.md`
- `unity/architecture/UnityRuntime三期GameSync设计.md`

### 历史与归档

- `../CHANGELOG.md`
- `releases/`
- `internal/archive/`

## 4. 目录说明

- `guides/`：持续维护的用户说明与速查。
- `unity/`：Unity SDK 对接、迁移、验证与运行时架构文档。
- `operations/`：诊断、容量、发布执行等交付与运维文档。
- `internal/architecture/`：当前仍有效的内部架构与路线文档。
- `internal/product/`：桌面工具产品化方向文档。
- `internal/research/`：对标评估与研究文档。
- `internal/archive/`：已完成阶段计划与历史背景文档。
- `releases/`：GitHub release 文案归档。