# Application Controller Refactor Plan

## 目标

这次重构把主控继续往应用层控制器拆，而不是继续把流程塞回 MainController。

第一阶段已经落地两条主链路：

- ProjectLifecycle：工程打开、保存、最近工程、窗口偏好改由应用层控制器和仓储边界承接。
- RecoveryAutosave：自动恢复快照、自动保存历史、自动保存偏好改由应用层控制器和 SnapshotRepository / SettingsStore 承接。

同时补出了明确边界类型：

- ProjectRepository
- ExperimentWorkspaceRepository
- SnapshotRepository
- SettingsStore
- PlaybackGateway

## 分阶段方案

### 阶段 1

范围：ProjectLifecycle、RecoveryAutosave、应用层 Result 协议。

代码产物：

- audioforge/app/application/contracts.py
- audioforge/app/application/ports.py
- audioforge/app/application/project_lifecycle_controller.py
- audioforge/app/application/recovery_autosave_controller.py
- audioforge/app/adapters/workbench_adapters.py

测试要求：

- 纯应用层单测覆盖成功、失败、取消三类结果。
- 现有 MainController 回归至少覆盖打开/保存、自动保存偏好、恢复快照链路。

### 阶段 2

范围：ExperimentIntegrationController 全面改为 Result / Command 请求驱动，去掉控制器中的 QMessageBox 和 QFileDialog。

代码目标：

- ExperimentWorkspaceRepository 全量接管 ExperimentWorkspaceSerializer。
- ExperimentIntegrationController 只返回 workflow result、notification、confirmation request、file request。
- MainWindow 成为唯一 GUI 对话框执行器。

测试要求：

- 应用编排测试改用 fake repository / fake dialog executor。
- GUI smoke 只验证请求被视图正确渲染，不再断言控制器内部弹窗分支。

### 阶段 3

范围：PreviewPlayback、BuildExport。

代码目标：

- PreviewPlaybackController 统一事件试听、片段试听、传输控制、Bus 停止。
- BuildExportController 统一构建计划、后台构建、结果汇总、失败报告。
- PlaybackGateway 和导出相关 adapter 成为主入口，MainController 仅保留状态同步和视图接线。

测试要求：

- PreviewPlayback 纯应用层测试覆盖播放命中、无选中、暂停恢复、最近试听重播。
- BuildExport 应用层测试覆盖计划预览、构建中拒绝、校验拦截、后台成功、后台失败。

### 阶段 4

范围：MainWindow 大页面 Presenter / ViewModel。

优先区域：

- 对象头
- 实验面板
- 自动保存页

代码目标：

- 每个区域只有 render(state) 和用户事件信号。
- 状态拼装放入 Presenter，不在 MainWindow 中直接拼 QLabel/QPushButton 条件。

测试要求：

- Presenter 测试断言 ViewState。
- GUI smoke 只断言 render 后关键控件可见性、文本和启用态。

## 测试分层基线

建议把测试固定成四层，并逐步迁移目录：

1. 领域单测：模型、规则、纯算法，不依赖 Qt、不落盘。
2. 适配层测试：serializer、repository、settings store、snapshot repository。
3. 应用编排测试：application controller + fake repository / fake gateway。
4. GUI smoke / E2E：MainWindow 接线和少量端到端主链路。

本轮新增的纯应用层测试：

- tests/unit/test_project_lifecycle_controller.py
- tests/unit/test_recovery_autosave_controller.py

## Fixture 资产策略

当前 harness 适合动态生成 smoke 资产，但还需要补稳定黄金样本。

建议并行维护两类 fixture：

- golden fixtures：版本化、可 diff、可 review 的固定 afproj / afws / delta 资产。
- builder fixtures：继续保留 harness 生成器，负责参数化场景和烟测环境。

建议优先沉淀四类黄金样本：

- portable afproj 样本
- 带 Sources 的工程 bundle
- experiment workspace 样本
- experiment delta 样本