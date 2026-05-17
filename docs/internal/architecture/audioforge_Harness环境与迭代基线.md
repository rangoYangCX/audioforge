# AudioForge Harness 环境与迭代基线

当前文档同步日期：2026-05-17

## 1. 目标

Harness 环境的目标不是替代 `pytest`，而是补一层仓库内统一、可复用、可落盘的迭代基线：

- 统一生成可迁移的样本工程 `.afproj`
- 统一生成带默认任务/方案的实验工作区 `.afws`
- 统一执行一组低成本 smoke 场景
- 统一输出 JSON / Markdown 报告，方便后续接 CI 或做迭代签收

这样以后改序列化、实验工作区、导出、自动恢复或主流程时，不需要再临时拼样本或手工找命令。

当前仓库已经把 `pytest` 侧入口固定成 `tools/run_test_suite.py` 分层命令；Harness 负责补跨模块 smoke，不负责替代这层分层回归。

## 2. 当前落地结构

- 代码入口：`audioforge/harness/`
- 命令入口：`python tools/run_harness.py ...`
- 打包脚本入口：`audioforge-harness ...`
- 产物默认目录：`reports/harness/`

## 3. 当前内置能力

### 3.1 样本与工作区生成

- `audioforge.harness.fixtures.write_wav_fixture()`
- `audioforge.harness.fixtures.build_sample_project()`
- `audioforge.harness.fixtures.save_sample_project()`
- `audioforge.harness.fixtures.create_workspace_from_base_project()`
- `audioforge.harness.fixtures.create_sample_workspace()`

当前样本默认覆盖：

- `UiClick`
- `UIHover`
- `BGMMenuLoop`

并保证样本工程保存后是 portable bundle，可直接用于实验工作区和导出 smoke。

### 3.2 内置 smoke 场景

- `project_roundtrip`：序列化保存/读取和工程内资源路径回读
- `export_contract`：完整导出、运行时契约和导出产物校验
- `build_export_cycle`：完整导出后再跑一次增量导出，验证 rebuilt / reused 资产计划
- `recovery_cycle`：autosave snapshot / history snapshot 保存与恢复
- `recovery_reopen_cycle`：从 history snapshot 恢复后再次保存并重开工程
- `experiment_cycle`：实验工作区、任务/方案、方案激活主链路
- `experiment_delta_export`：实验方案修改、差异预览和增量导出主链路

建议把这些场景看成三层：

- 样本与序列化基线：`project_roundtrip`
- 构建/恢复基线：`export_contract`、`build_export_cycle`、`recovery_cycle`、`recovery_reopen_cycle`
- 实验联动基线：`experiment_cycle`、`experiment_delta_export`

## 4. 使用方式

### 4.1 初始化本地 sandbox

```bash
python tools/run_harness.py init-sandbox --target reports/harness/sandbox
```

输出内容：

- `reports/harness/sandbox/project/*.afproj`
- `reports/harness/sandbox/workspace/*.afws`
- `reports/harness/sandbox/harness_manifest.json`

### 4.2 执行 smoke 场景

```bash
python tools/run_harness.py run-smoke --target reports/harness/smoke
```

先查看内置场景：

```bash
python tools/run_harness.py list-scenarios
```

只跑指定场景：

```bash
python tools/run_harness.py run-smoke --target reports/harness/smoke --scenario project_roundtrip --scenario experiment_cycle
```

输出内容：

- `harness_report.json`
- `harness_report.md`

## 5. 推荐接入方式

### 开发本地迭代

- 改完单个模块逻辑后，先跑对应 targeted pytest 或 `tools/run_test_suite.py fast/gui/integration/release`
- 改动涉及序列化、导出、恢复、实验工作区、跨模块协作时，再跑 harness smoke
- `MainController` 的实验 / 预览 / 构建切面优先走 `tools/run_test_suite.py main-controller`
- 只有 harness 和对应层级的分层 pytest 都通过，才算完成本地基线验证

### 后续 CI

建议后面在 CI 中加两层：

1. `python tools/run_test_suite.py smoke`
2. `python tools/run_full_chain_check.py --export-dir ... --report-dir ...`

如果需要发布前的完整 Python 扫描，再在第二层显式加 `--pytest-all`。这样可以把“分层 pytest”与“工程级样本 smoke + 导出契约 + Unity 包检查”分开统计。

## 6. 未来开发的基准流程

推荐以后所有功能开发都按这条线走：

1. 先判断需求是否属于 harness 准入范围。
2. 不属于：补 targeted pytest 或 GUI 回归，不进 harness。
3. 属于：优先复用 `audioforge.harness.fixtures` 增加 smoke 场景。
4. 落地后同时更新 harness 文档、索引和命令示例。
5. 发布级入口统一走 `tools/run_full_chain_check.py`、`tools/run_internal_release_validation.py`、`tools/run_unity_package_release.py`，不要再手工拼命令。
6. 本轮如果改动了边界、流程或验证入口，必须同步更新开发完成定义文档：`audioforge_开发完成定义与文档同步基线.md`。

准入规则和场景矩阵见：`audioforge_Harness准入规则与场景矩阵.md`。

## 7. 后续扩展原则

后面如果继续扩 harness，遵守这几条：

- 新场景优先复用 `audioforge.harness.fixtures`，不要各自再造样本
- 新 smoke 场景优先放到 `audioforge.harness.scenarios`
- 只把跨模块、能代表真实迭代风险的流程加进 harness
- 不把 UI 细节断言塞进 harness；UI 细节仍然留给专门的 GUI 测试

## 8. 当前定位

这一层的定位是：

- 比手工点击稳
- 比全量 pytest 快
- 比散落在 tools/ 和 tests/ 里的临时脚本更统一

它是以后做迭代、回归、重构和签收时的公共底座。