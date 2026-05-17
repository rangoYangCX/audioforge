# AudioForge Harness 准入规则与场景矩阵

当前文档同步日期：2026-05-17

## 1. 目的

这份文档解决两个问题：

- 以后什么东西应该进 harness
- 以后什么东西不要硬塞进 harness

如果没有这层边界，harness 很快会从“迭代基线”膨胀成“第二套低可维护测试框架”。

## 2. 准入标准

只有同时满足下面 3 条，才建议进入 harness：

1. 至少涉及两个模块联动。
2. 出问题会直接影响真实用户主流程。
3. 单元测试全部通过时，仍然有可能漏掉这类问题。

任何一条不满足，都优先留在普通 pytest、GUI 测试或人工验收，不进 harness。

## 3. 不建议进入 harness 的内容

下面这些默认不要放进 harness：

- 纯 serializer 字段映射细节
- 单个 controller 的边界分支
- MainWindow / Widget 布局和控件显示细节
- QMessageBox 文案、按钮顺序、状态条文字等 UI 细节
- 纯参数校验、空值分支、异常字符串比对
- 依赖大量 mock 才能跑通的内部逻辑

这些内容如果进 harness，只会让场景越来越慢、失败越来越难定位、重构越来越痛。

## 4. 当前建议纳入 harness 的链路

### 4.1 已经纳入

- `project_roundtrip`
  目标：portable afproj 样本、资源回读、基础序列化闭环。
- `export_contract`
  目标：完整导出、运行时契约、导出产物可用性。
- `build_export_cycle`
  目标：完整导出后再做增量导出，验证 rebuilt / reused 资产计划。
- `recovery_cycle`
  目标：autosave snapshot / history snapshot 基本保存与恢复。
- `recovery_reopen_cycle`
  目标：从恢复快照回到工程文件，验证“恢复后还能继续迭代”。
- `experiment_cycle`
  目标：实验工作区、任务、方案、激活链路。
- `experiment_delta_export`
  目标：方案修改、差异预览、增量导出链路。

### 4.2 为什么这些应该进

这些场景都满足：

- 至少跨了样本、序列化、业务控制器、导出或恢复中的两层以上
- 一旦断裂，用户会直接遇到“不能切方案”“不能导出”“恢复后打不开”“资源路径坏掉”这种问题
- 只看局部单测，无法稳定发现整条链是否真的通了

## 5. 场景矩阵

| 场景 | 主要覆盖模块 | 主要风险 | 是否未来必跑 |
| --- | --- | --- | --- |
| `project_roundtrip` | ProjectSerializer / fixtures | portable bundle 失效、资源路径坏 | 是 |
| `export_contract` | RuntimeExporter / Validator | 导出契约断裂、产物缺失 | 是 |
| `build_export_cycle` | RuntimeExporter / 增量计划 | 增量构建误重建或误复用 | 是 |
| `recovery_cycle` | RecoveryService | autosave/history 快照失效 | 是 |
| `recovery_reopen_cycle` | RecoveryService / ProjectSerializer | 恢复后无法继续保存/重开 | 是 |
| `experiment_cycle` | ExperimentController / WorkspaceSerializer | 任务/方案/激活主链断裂 | 是 |
| `experiment_delta_export` | ExperimentController / ExperimentExporter | 方案导出链断裂、预览与导出不一致 | 是 |

## 6. 新功能接入规则

以后要加新 harness 场景，按这个顺序判断：

1. 这是跨模块真实主链路吗？
2. 失败后用户会卡在关键动作上吗？
3. 现有 targeted pytest 无法覆盖整条链吗？
4. 能复用现有 sample project / sample workspace 吗？
5. 能在几秒级完成，而不是变成慢测试吗？

只有前 4 条都满足，且第 5 条可接受，才加入。

## 7. 文档与代码同步要求

以后每次新增 harness 场景，必须同步更新：

- `audioforge/harness/scenarios.py`
- `tests/unit/test_harness_environment.py`
- `docs/internal/architecture/audioforge_Harness环境与迭代基线.md`
- 本文档
- `README.md` 或 `docs/README.md` 中的入口索引（如果入口有变化）

这不是形式要求，而是为了避免“代码加了，后来没人知道为什么要跑、什么时候该跑、失败说明什么”。

## 8. 未来维护原则

- harness 只做主链路和契约基线，不替代单元测试。
- pytest 负责细粒度正确性；harness 负责跨模块烟测。
- GUI 测试负责交互壳层，不把控件细节塞进 harness。
- 如果一个场景已经很难解释，那通常说明它不该继续留在 harness。

## 9. 结论

未来开发的默认基准应该是：

- 小改动先跑 targeted pytest
- 涉及主链路的改动再跑 harness smoke
- 只有同时通过，才算本地回归达标

这样 harness 才会长期保持稳定、清晰、可扩，而不是重新长成一个难维护的大泥球。