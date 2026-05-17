# AudioForge 项目稳定性报告

当前文档同步日期：2026-05-17

## 1. 结论

- 总体结论：**稳定，可继续迭代**。
- 当前最强稳定性信号来自两类验证：
  - 文档 / 发布链 / harness 环境基线测试通过。
  - harness smoke 7 个跨模块主链路场景全部通过。
- 用户实际导出的真实产物已通过一轮 full-chain 快速校验，包含 `main_controller` 固定批次检查。
- `main_controller` 的实验 / 预览 / 构建回归现已拆成固定批次与独立测试文件，默认不再依赖单条大范围组合命令。

换句话说，当前仓库不是“零风险”，但已经达到继续开发和继续收口的可接受稳定性水平。

## 2. 本轮验证范围

### 2.1 已通过验证

1. 文档 / 发布链 / harness 环境基线

```bash
QT_QPA_PLATFORM=offscreen /Users/rango/Documents/audio/.venv/bin/python -m pytest tests/unit/test_documentation_baseline.py tests/unit/test_full_chain_check.py tests/unit/test_harness_environment.py -q
```

- 结果：**11 passed in 5.54s**
- 说明：当前固定文档基线、全链路入口和 harness 环境未发现回归。

2. harness smoke

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_harness.py run-smoke --target reports/harness/stability_report_smoke
```

- 结果：**PASS**
- 报告路径：`reports/harness/stability_report_smoke/harness_report.json`
- Markdown 报告：`reports/harness/stability_report_smoke/harness_report.md`
- 通过场景：
  - `project_roundtrip`
  - `export_contract`
  - `build_export_cycle`
  - `recovery_cycle`
  - `recovery_reopen_cycle`
  - `experiment_cycle`
  - `experiment_delta_export`

3. `main_controller` 固定批次回归入口

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_main_controller_stability_batches.py --report-json reports/main_controller_stability_batches.json --report-markdown reports/main_controller_stability_batches.md
```

- 结果：**PASS**
- 报告路径：`reports/main_controller_stability_batches.json`
- Markdown 报告：`reports/main_controller_stability_batches.md`
- 当前观测耗时：
  - `experiment_guards`: 3.27s
  - `layout_experiment`: 8.90s
  - `layout_preview_gamesync`: 33.23s
  - `layout_preview_transport`: 31.23s
  - `layout_preview_recent`: 30.79s
  - `layout_build`: 9.45s
  - `full_flow_build`: 66.80s

4. 基于用户真实导出产物的 full-chain 快速校验

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_full_chain_check.py --main-controller-batches --skip-pytest --skip-harness --export-dir /Users/rango/Documents/audio/Export --report-dir reports/full_chain_with_main_controller_batches_user_export
```

- 结果：**PASS**
- 校验对象：`/Users/rango/Documents/audio/Export`
- 报告路径：`reports/full_chain_with_main_controller_batches_user_export/full_chain_report.json`
- Markdown 报告：`reports/full_chain_with_main_controller_batches_user_export/full_chain_report.md`
- 覆盖检查：
  - `main_controller_batches`
  - `export_bundle`
  - `runtime_contract`
  - `unity_integration_package`

### 2.2 已收口的测试流程调整

1. `main_controller` 回归入口已从大范围组合命令切到固定批次与分层入口。

当前默认入口：

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_test_suite.py main-controller
```

- 作用：统一调度 experiment / preview / build 拆分后的固定批次，避免长时组合命令的定位和收敛成本。

## 3. 稳定性分项判断

### 3.1 序列化与工程可迁移性：稳定

- `project_roundtrip` 通过，说明 `.afproj` 样本工程的保存、回读和资源路径闭环当前可用。
- `build_export_cycle` 通过，说明完整导出与增量导出的 rebuilt / reused 资产计划当前一致。
- `export_contract` 通过，说明运行时契约文件和导出产物集合当前完整。
- 基于用户真实导出产物的 full-chain 快速校验通过，说明当前实际导出目录也满足 `export_bundle` 与 `runtime_contract` 检查。

### 3.2 恢复链：稳定

- `recovery_cycle` 与 `recovery_reopen_cycle` 均通过。
- 说明 autosave / history snapshot 当前不仅能保存和恢复，而且恢复后的工程还能继续保存并重开。

### 3.3 实验工作区链：稳定

- `experiment_cycle` 与 `experiment_delta_export` 均通过。
- 说明实验工作区、任务/方案、方案激活、差异预览、增量导出主链路当前可用。

### 3.4 文档与发布入口：稳定

- `test_documentation_baseline.py`、`test_full_chain_check.py`、`test_harness_environment.py` 通过。
- 说明当前文档基线、full-chain 入口和 harness 入口没有明显漂移。

## 4. 当前观察项

### 4.1 `main_controller` 仍需坚持固定批次回归

- 风险不在于当前入口不可用，而在于一旦重新回到大范围组合命令，回归反馈会再次变慢、定位成本会再次升高。
- 当前仓库已新增并固定批次入口，后续统一改用：

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_main_controller_stability_batches.py
```

- 当前默认批次为：
  - `experiment_guards`
  - `layout_experiment`
  - `layout_preview_gamesync`
  - `layout_preview_transport`
  - `layout_preview_recent`
  - `layout_build`
  - `full_flow_build`

### 4.2 `MainController` 仍是结构性风险中心

- 现有耦合审查结论仍成立，见 `docs/internal/coupling_audit_report.md`。
- 当前 P0-P2 已完成，但 P3 仍待规划，尤其是：
  - `MainController` 进一步职责拆分
  - 事件路由 / 信号编排进一步解耦

这不是“当前功能不可用”的风险，而是“后续迭代容易再次出现高耦合回归”的风险。

## 5. 稳定性等级

建议将当前仓库状态标记为：

- **开发迭代：可继续**
- **跨模块改动：必须继续保持 targeted pytest + harness smoke 双层验证**
- **发布前：仍需按既有入口再跑一次正式签收链，不应直接拿本报告替代 release sign-off**

## 6. 建议下一步

1. 如果下一轮继续改 `main_controller`、实验联动、导出、恢复链，默认继续先跑 targeted pytest，再跑 harness smoke。
2. `main_controller` 回归优先使用 `tools/run_main_controller_stability_batches.py`，不要再默认使用大范围 `-k 'experiment or preview or build'` 组合命令。
3. 如果要进入正式发布或内部签收，额外执行：
   - `tools/run_full_chain_check.py`
   - `tools/run_internal_release_validation.py`
   - `tools/run_unity_package_release.py`

4. 如果希望在 full-chain 报告里一并带上 `main_controller` 固定批次结果，使用：

```bash
/Users/rango/Documents/audio/.venv/bin/python tools/run_full_chain_check.py --main-controller-batches
```

5. 如果导出产物不在仓库默认 `audioforge/Export` 下，而是在工作区其他目录，运行 full-chain 时显式传入 `--export-dir`。

## 7. 结论摘要

当前 AudioForge 的项目稳定性可以概括为：

- 主链路稳定。
- 文档和验证入口稳定。
- 高耦合区域仍存在结构性观察项，但当前没有证据表明它已经导致新的主链路故障。

因此，本轮结论不是“完全收官”，而是“当前版本具备继续安全迭代的稳定基线”。