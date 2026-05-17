# AudioForge 开发完成定义与文档同步基线

当前文档同步日期：2026-05-17

## 1. 目的

这份文档只解决一件事：

- 每次开发做到哪一步可以停
- 每次收口时，文档升级必须如何进入固定步骤

如果没有这层定义，工程一大就会重复出现两类问题：

- 代码改完了，但边界其实还没闭合
- 功能已经变了，文档和验证口径却还停在旧版本，最后团队靠记忆协作

## 2. 当前阶段允许停止的边界

当前仓库的合理停点，不是“功能写完”，而是下面 4 条同时成立：

1. 当前需求已经做到本轮明确边界，不继续顺手扩需求。
2. 对应层级的验证已经通过，至少包括 targeted pytest；跨模块主链路改动还要补 harness 或 full-chain。
3. 受影响文档已经同步，或者已经明确记录“本次无文档影响”。
4. 最终交付说明里能明确回答 3 个问题：改了什么、如何验证、文档同步到哪。

只要有任意一条不成立，就不算真正收口。

## 3. 每次开发固定步骤

以后默认按下面顺序执行，不再靠临时判断：

1. 先定义本轮边界。
2. 只做到这轮边界，不顺手扩大范围。
3. 先跑最窄验证：targeted pytest 或最贴近改动的检查。
4. 如果改动跨模块主链路，再跑 harness smoke 或 full-chain。
5. 同步更新受影响文档。
6. 交付时显式写清楚：代码变化、验证结果、文档变化。

这 6 步里，第 5 步不是可选项。

## 4. 文档同步不是“最后想起来再补”

文档升级必须按改动类型进入同一轮开发，而不是拖到下一轮：

- 改了主流程、验证入口、发布入口：更新 README、发布手册、相关架构文档。
- 改了跨模块基线或 smoke 规则：更新 harness 文档、准入规则和索引。
- 改了对外版本、交付目录或 SDK 口径：更新 CHANGELOG、release note 和对应说明文档。
- 改了某一模块的边界或默认行为：更新该模块的主说明文档或开发文档入口。

如果本次没有文档变化，也要在交付说明中明确写“本次无文档影响”。

## 5. 文档同步矩阵

### 5.1 一般功能迭代

- 最少检查：`README.md`
- 若影响仓库阅读入口：`docs/README.md`
- 若影响架构或边界：`开发文档.md` 或对应架构文档

### 5.2 Harness / 基线 / 验证链变更

- `docs/internal/architecture/audioforge_Harness环境与迭代基线.md`
- `docs/internal/architecture/audioforge_Harness准入规则与场景矩阵.md`
- `docs/README.md`
- 如影响正式入口，还要更新 `README.md` 和 `docs/operations/internal_release_execution_plan.md`

### 5.3 版本与发布链变更

- `CHANGELOG.md`
- `docs/releases/v<APP_VERSION>-github-release.md`
- `docs/operations/internal_release_execution_plan.md`
- 如影响包内 canonical 文档，还要检查 Unity package 打包链

## 6. 验证层级要求

### 6.1 最低要求

- 改动必须至少跑一条与当前改动直接相关的可执行验证。
- 优先使用仓库固定入口：`tools/run_test_suite.py fast/gui/integration/release/smoke`，避免长期继续堆手工 pytest 组合命令。

### 6.2 跨模块改动

- 除 targeted pytest 外，还要补 harness smoke。
- 如果改动集中在 `MainController` 的实验 / 预览 / 构建切面，优先补跑 `tools/run_test_suite.py main-controller` 或 `tools/run_main_controller_stability_batches.py`，不要默认只用大范围 `-k` 组合命令。

### 6.3 发布链或签收链改动

- 除 targeted pytest 外，还要真实跑对应入口：
  - `tools/run_full_chain_check.py`
  - `tools/run_internal_release_validation.py`
  - `tools/run_unity_package_release.py`
- `tools/run_full_chain_check.py` 默认只带 smoke pytest 目标；只有明确需要完整 Python 回归时，才额外加 `--pytest-all`。

## 7. 防遗忘规则

以后每次收口，必须显式检查下面 3 项：

1. 这次边界是否已经闭合。
2. 这次验证是否已经到匹配层级。
3. 这次文档是否已经同步，或者已经明确说明无需同步。

这三项缺任何一项，都不允许把本轮任务称为“完成”。

## 8. 当前仓库内的落地方式

这套要求已经通过两种方式落地：

- 文档层：本文件、harness 基线文档、发布执行手册、README 索引
- 测试层：关键文档基线会进入测试，至少保证当前版本 release note 和固定流程文档不会缺失

## 9. 结论

以后 AudioForge 的默认收口标准应该是：

- 先到边界
- 再过验证
- 再同步文档

顺序不能反过来，也不能少掉最后一步。