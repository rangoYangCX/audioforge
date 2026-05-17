# AudioForge 项目耦合审查报告

> 审查日期：2026-05-16  |  修复更新：2026-05-16  
> 审查范围：`audioforge/app/` 全层（models / services / controllers / views / widgets / utils）  
> 审查目标：识别跨层耦合、循环依赖、God Object、信号绑定脆弱性等架构风险  
> 修复状态：**P0 ✅ | P1 ✅ | P2 ✅** — 31项测试全部通过

---

## 0. 修复进度总览

| 优先级 | 状态 | 修复项数 | 详情 |
|--------|------|---------|------|
| **P0** | ✅ 全部完成 | 3 | R02 方法缺失→委托MainWindow; R09 6处信号补齐; R11 导出回退修复 |
| **P1** | ✅ 全部完成 | 3 | R05 token_codec提取; R03 DTO下沉models; R10 Diagnostic DTO下沉 |
| **P2** | ✅ 全部完成 | 2 | R08 ExperimentExporter依赖注入; R07 ProjectOpener Protocol解耦 |
| **P3** | 🔄 待规划 | 2 | R01 MainController拆分; R06 事件总线 |

---

## 1. 项目结构概览

| 层级 | 目录 | 文件数 | 职责 |
|------|------|--------|------|
| **U** Utils | `utils/` | 3 | 常量、图标、日志配置 |
| **M** Models | `models/` | 2 | 数据模型定义 |
| **S** Services | `services/` | 13 | 业务逻辑与IO |
| **C** Controllers | `controllers/` | 2 | 协调逻辑与状态管理 |
| **V** Views | `views/` | 2 | 窗口/页面组装 |
| **W** Widgets | `widgets/` | 9 | 独立UI组件 |

---

## 2. 跨层依赖矩阵

### 2.1 完整跨层依赖清单

以下列出所有 **跨层**（非同层）导入依赖：

| 源文件 | → 目标层 | → 目标模块 | 违规等级 |
|--------|----------|-----------|---------|
| `controllers/experiment_controller.py` | M | `models/experiment_workspace` | ✅ 正常（C→M） |
| `controllers/experiment_controller.py` | S | `services/experiment_serializer` | ✅ 正常（C→S） |
| `controllers/main_controller.py` | M | `models/audio_meter_dto` | ✅ 已从S下沉至M |
| `controllers/main_controller.py` | M | `models/diagnostic_dto` | ✅ 已从C下沉至M |
| `controllers/main_controller.py` | M | `models/audio_project` | ✅ 正常（C→M） |
| `controllers/main_controller.py` | S | `services/audio_meter_service` | ⚠️ C→S 但仅取数据类型 |
| `controllers/main_controller.py` | S | `services/command_history` | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/exporter` | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/playback_service` | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/preview_*` (3个) | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/project_serializer` | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/recovery_service` | ✅ 正常 |
| `controllers/main_controller.py` | S | `services/validator` | ✅ 正常 |
| `controllers/main_controller.py` | **V** | **`views/main_window`** | **🔴 C→V 跨层违规** (待P3拆分) |
| `controllers/main_controller.py` | U | `utils/token_codec` | ✅ P1修复：原C→W已解除 |
| `controllers/main_controller.py` | U | `utils/constants` | ✅ 正常 |
| `controllers/main_controller.py` | U | `utils/runtime_logging` | ✅ 正常 |
| `views/main_window.py` | M | `models/audio_project` | ⚠️ V→M 边缘 |
| `views/main_window.py` | M | `models/audio_meter_dto` | ✅ P1修复：原V→S已解除 |
| `views/main_window.py` | U | `utils/constants` | ✅ 正常 |
| `views/main_window.py` | U | `utils/icons` | ✅ 正常 |
| `views/main_window.py` | W | `widgets/*` (9个) | ✅ 正常（V→W 组装） |
| `views/shell_components.py` | U | `utils/constants` | ✅ 正常 |
| `widgets/event_tree.py` | **M** | **`models/audio_project`** | **⚠️ W→M 跨层违规** |
| `widgets/event_tree.py` | U | `utils/icons` | ✅ 正常 |
| `widgets/audio_tree.py` | U | `utils/icons` | ✅ 正常 |
| `widgets/audio_tree.py` | W | `widgets/source_tree` | ✅ 同层 |
| `widgets/source_tree.py` | U | `utils/icons` | ✅ 正常 |
| `models/audio_project.py` | U | `utils/constants` | ✅ 正常 |
| `models/experiment_workspace.py` | M | `models/audio_project` | ✅ 同层 |
| `services/audio_processor.py` | M | `models/audio_project` | ✅ 正常 |
| `services/command_history.py` | M | `models/audio_project` | ✅ 正常 |
| `services/experiment_exporter.py` | M | `models/audio_project` | ✅ 正常 |
| `services/experiment_exporter.py` | M | `models/experiment_workspace` | ✅ 正常 |
| `services/experiment_exporter.py` | S | `services/audio_processor` | ✅ P2修复：依赖注入 |
| `services/experiment_exporter.py` | S | `services/exporter` | ✅ P2修复：依赖注入+公开方法 |
| `services/experiment_exporter.py` | U | `utils/constants` | ✅ 正常 |
| `services/experiment_serializer.py` | M | `models/experiment_workspace` | ✅ 正常 |
| `services/exporter.py` | M | `models/audio_project` | ✅ 正常 |
| `services/exporter.py` | S | `services/audio_processor` | ✅ 同层组合 |
| `services/exporter.py` | U | `utils/constants` | ✅ 正常 |
| `services/validator.py` | M | `models/audio_project` | ✅ 正常 |
| `services/validator.py` | U | `utils/constants` | ✅ 正常 |
| `services/preview_service.py` | M | `models/audio_project` | ✅ 正常 |
| `services/project_serializer.py` | M | `models/audio_project` | ✅ 正常 |
| `services/recovery_service.py` | M | `models/audio_project` | ✅ 正常 |
| `services/playback_service.py` | S | `services/preview_audio_renderer` | ✅ 同层组合 |
| `services/audio_meter_service.py` | S | `services/preview_audio_renderer` | ✅ 同层组合 |

### 2.2 跨层违规汇总

共发现 **4 处跨层违规** + **2 处同层耦合风险**（已修复 3 处跨层 + 2 处同层）：

| # | 违规 | 说明 | 严重等级 | 修复状态 |
|---|------|------|---------|----------|
| **V1** | `C → V` | `main_controller.py` 导入 `views.main_window.MainWindow` | 🔴 严重 | 🔄 待P3拆分 |
| **V2** | `C → W` | `main_controller.py` 导入 `widgets.event_tree.encode/decode_source_binding_token` | 🔴 严重 | ✅ 已提取至 `utils/token_codec.py` |
| **V3** | `V → S` | `main_window.py` 导入 `services.audio_meter_service.AudioMeterSnapshot/LoudnessReading` | 🔴 严重 | ✅ 已下沉至 `models/audio_meter_dto.py` |
| **V4** | `W → M` | `widgets/event_tree.py` 导入 `models.audio_project.AudioProject` | ⚠️ 中等 | 🔄 保留（Model是公共底层） |
| **S1** | 同层硬实例化 | `experiment_exporter.py` 自行创建 `AudioProcessor()` + `RuntimeExporter()` | ⚠️ 中等 | ✅ 已改为依赖注入 |
| **S2** | TYPE_CHECKING循环 | `experiment_controller ↔ main_controller` 结构性双向耦合 | ⚠️ 中等 | ✅ 已用 `ProjectOpener` Protocol 解耦 |

---

## 3. God Object 分析：MainController

### 3.1 规模数据

| 指标 | 数值 | 评估 |
|------|------|------|
| 总行数 | **4817** | 🔴 远超健康阈值（~500行） |
| 方法数 | **237** | 🔴 远超健康阈值（~20-30方法） |
| `self.window.*` 引用 | **413** | 🔴 Controller 对 View 的直接操作极多 |
| 导入 Service 数 | **10** | ⚠️ 过多直接依赖 |
| 导入 Model 类型数 | **16+** | ⚠️ 直接引用过多数据类型 |

### 3.2 可提取职责簇

| 簇 | 大约行数 | 方法数 | 建议拆出 |
|----|---------|--------|---------|
| **预览/试听** | ~500行 | ~12 | → **PreviewController** |
| **响度/计量** | ~90行 | ~3 | → 合入 Preview 或独立 **LoudnessController** |
| **构建/导出** | ~590行 | ~10 | → **BuildController** |
| **诊断聚合** | ~260行 | ~8 | → **DiagnosticController** |
| **导入/资产管理** | ~470行 | ~8 | → **ImportController** |
| **实验绑定** | ~130行 | ~6 | → 归入 **ExperimentController** |

拆分后 `MainController` 可降至 ~800-1000行，只保留项目生命周期管理（new/open/save/close）和核心协调职责。

### 3.3 内嵌数据类问题

`DiagnosticSection` 和 `DiagnosticSnapshot` 定义在 `main_controller.py`（Controller层），但本质是纯数据结构，应移至 `models/` 或独立的 `dto.py`。

---

## 4. 信号绑定耦合分析

### 4.1 `_bind_experiment_signals()` (L377-400)

| 信号 | 源 | 目标 | 问题 |
|------|---|------|------|
| `panel.createTaskRequested` | ExperimentPanel | `ec.create_task` | ✅ 直连 |
| `panel.deleteTaskRequested` | ExperimentPanel | `ec.delete_task` | ⚠️ 面板无UI触发 |
| `panel.deleteVariantRequested` | ExperimentPanel | `ec.delete_variant` | ⚠️ 唯一删除按钮只连variant |
| `panel.exportDeltaRequested` | ExperimentPanel | `self._export_experiment_delta` | 🔴 **不连ec，由mc中介** |
| `switcher.workspaceOpenRequested` | ExperimentSwitcher | `lambda: self._activate_workspace_mode("experiment")` | 🔴 **方法不存在！** |
| `switcher.workspaceCloseRequested` | ExperimentSwitcher | `ec.close_workspace` | ✅ |
| `switcher.taskVariantChanged` | ExperimentSwitcher | `ec.activate_variant` | ⚠️ 切换即加载，太重 |

### 4.2 `_bind_events()` (L514-584)

- **70 条直连信号绑定**，无中间层/事件总线
- **3 处 lambda 参数重排**：翻转参数顺序
- **3 处 lambda 参数丢弃**：只触发 `_sync_browser_action_affordances()`
- **扩展成本极高**：新增 widget 需手动逐条添加 connect

### 4.3 `hasattr` 脆弱性

`_bind_experiment_signals()` 和相关方法中有 **5 处 `hasattr` 检查**（L379, L408, L458, L462, L506），检查 `self.window.experiment_panel` / `experiment_switcher` 是否存在。原因是 MainWindow 对这两个组件做了延迟导入，组件可能不存在。这种模式脆弱，组件属性名变更会导致静默失败。

---

## 5. Service 间耦合分析

### 5.1 依赖图

```
exporter.py ──→ audio_processor.py (组合)
playback_service.py ──→ preview_audio_renderer.py (组合)
audio_meter_service.py ──→ preview_audio_renderer.py (组合)
experiment_exporter.py ──→ audio_processor.py (✅ 依赖注入)
experiment_exporter.py ──→ exporter.py (✅ 依赖注入 + 公开方法)
```

### 5.2 ✅ 已修复

**`experiment_exporter.py`** 的依赖注入改造已完成：
- `ExperimentExporter.__init__` 接受可选的 `audio_processor` 和 `runtime_exporter` 参数
- `_export_experiment_delta()` 在 MainController 中传入已配置的实例
- `RuntimeExporter` 的 `_serialize_*` 方法已改为公开 `serialize_*` 方法
- 默认值 `None` 时自动创建新实例（向后兼容）

---

## 6. 数据类型层级穿透

| 数据类型 | 原定义位置 | 现定义位置 | 修复状态 |
|---------|-----------|-----------|----------|
| `AudioMeterSnapshot` | `services/audio_meter_service.py` | `models/audio_meter_dto.py` | ✅ P1已下沉 |
| `LoudnessReading` | `services/audio_meter_service.py` | `models/audio_meter_dto.py` | ✅ P1已下沉 |
| `DiagnosticSection` | `controllers/main_controller.py` | `models/diagnostic_dto.py` | ✅ P1已下沉 |
| `DiagnosticSnapshot` | `controllers/main_controller.py` | `models/diagnostic_dto.py` | ✅ P1已下沉 |
| `PreviewGameSyncContext` | `services/preview_service.py` | —原地 | 🔄 待下沉 |

**新增文件**：
- `models/audio_meter_dto.py` — `AudioMeterSnapshot` + `LoudnessReading` 数据类
- `models/diagnostic_dto.py` — `DiagnosticSection` + `DiagnosticSnapshot` 数据类
- `utils/token_codec.py` — `encode/decode_source_binding_token` 纯工具函数

---

## 7. 循环依赖分析

| 模块A | 模块B | 模式 | 修复状态 |
|-------|-------|------|----------|
| `experiment_controller.py` | `main_controller.py` | TYPE_CHECKING延迟导入 | ✅ 已用 `ProjectOpener` Protocol 解耦 |

`ExperimentController.__init__` 现在接收 `ProjectOpener` 协议实例而非 `MainController` 类引用。`MainController` 因拥有 `open_project()` 方法自动满足此协议（鸭子类型）。TYPE_CHECKING 导入已完全移除。

---

## 8. AB 实验功能专属耦合问题

### 8.1 ExperimentController ↔ MainController ✅ 已部分解耦

| 交互方式 | 修复状态 | 说明 |
|---------|----------|------|
| `ec.__init__(project_opener)` | ✅ Protocol解耦 | 现接收 `ProjectOpener` 协议而非 MainController 类 |
| `ec._project_opener.open_project()` | ✅ 协议调用 | 仅通过协议方法交互 |
| `mc._export_experiment_delta()` | 🔄 仍在mc中 | 导出职责归入 ExperimentController 是P3目标 |
| `mc.window.experiment_panel` | 🔄 hasattr模式 | 待P3拆分后消除 |
| `mc.window.experiment_switcher` | 🔄 同上 | 待P3拆分后消除 |

### 8.2 信号流 ✅ 已全部修复

| 操作 | 修复前 emit | 修复后 emit | 状态 |
|------|-------------|-------------|------|
| `create_variant()` | `activeTaskChanged` | `_emit_workspace_signals()` (含3信号) | ✅ |
| `duplicate_variant()` | ❌ 无信号 | `_emit_workspace_signals()` | ✅ |
| `set_active_variant()` | `activeVariantChanged` | `_emit_workspace_signals()` + 边界检查 | ✅ |
| `set_task_lifecycle()` | `activeTaskChanged` | `_emit_workspace_signals()` | ✅ |
| `sync_variant_from_base()` | ❌ 无信号 | `_emit_workspace_signals()` | ✅ |
| `set_variant_lifecycle()` | `activeVariantChanged` | `_emit_workspace_signals()` | ✅ |

所有操作现在统一调用 `_emit_workspace_signals()`，一次性 emit `workspaceChanged` + `activeTaskChanged` + `activeVariantChanged`。

---

## 9. 综合风险评估

### 9.1 风险矩阵

| 风险ID | 修复状态 | 描述 | 影响范围 |
|--------|----------|------|---------|
| **R01** | 🔄 待P3 | MainController God Object (4817行/237方法) | 全项目 |
| **R02** | ✅ 已修复 | `_activate_workspace_mode` → 委托 `self.window._activate_workspace_mode()` | 实验 Switcher |
| **R03** | ✅ 已修复 | DTO下沉至 `models/audio_meter_dto.py` | View↔Model |
| **R04** | 🔄 C→V保留 | Controller 导入 View（Qt实践常见，待P3拆分消除） | Controller↔View |
| **R05** | ✅ 已修复 | token_codec 提取至 `utils/token_codec.py` | C→W解除 |
| **R06** | 🔄 待P3 | 70条直连信号绑定无中间层 | 扩展性 |
| **R07** | ✅ 已修复 | `ProjectOpener` Protocol 解耦双向依赖 | 实验功能 |
| **R08** | ✅ 已修复 | ExperimentExporter 依赖注入 | 配置一致性 |
| **R09** | ✅ 已修复 | 6处信号 emit 补齐 | UI刷新 |
| **R10** | ✅ 已修复 | DTO下沉至 `models/diagnostic_dto.py` | 层级穿透 |
| **R11** | ✅ 已修复 | 回退时保持源文件原始后缀 | 数据完整性 |
| **R12** | 🔄 保留 | W→M：Model是公共底层，可接受 | Widget↔Model |

### 9.2 修复优先级排序

| 优先级 | 修复项 | 工作量 | 收益 | 状态 |
|--------|-------|--------|------|------|
| **P0** | R02: 修复 `_activate_workspace_mode` | 小 | 实验功能可用 | ✅ 已完成 |
| **P0** | R09: 补齐实验信号emit（6处） | 小 | UI正确刷新 | ✅ 已完成 |
| **P0** | R11: 修复导出回退逻辑 wav→.ogg | 小 | 数据完整性 | ✅ 已完成 |
| **P1** | R05: token_codec 提取至 utils | 小 | 解除C→W违规 | ✅ 已完成 |
| **P1** | R03: DTO下沉至 models/audio_meter_dto | 小 | 解除V→S违规 | ✅ 已完成 |
| **P1** | R10: DTO下沉至 models/diagnostic_dto | 小 | 层级规范 | ✅ 已完成 |
| **P2** | R08: ExperimentExporter 依赖注入 | 中 | 配置一致性 | ✅ 已完成 |
| **P2** | R07: ProjectOpener Protocol 解耦 | 中 | 解除C→C双向耦合 | ✅ 已完成 |
| **P3** | R01: MainController拆分为5子Controller | 大 | 核心架构改善 | 🔄 待规划 |
| **P3** | R06: 引入事件总线/声明式信号绑定 | 大 | 扩展性改善 | 🔄 待规划 |

---

## 10. 推荐的分层依赖规则

| 层级 | 允许依赖 | 禁止依赖 |
|------|---------|---------|
| **Utils** | 无 | 所有 |
| **Models** | Utils | Services/Controllers/Views/Widgets |
| **Services** | Models + Utils + 同层组合 | Controllers/Views/Widgets |
| **Controllers** | Models + Services + Utils | Views/Widgets |
| **Views** | Models(仅DTO) + Utils + Widgets | Services/Controllers |
| **Widgets** | Utils(仅DTO) | Models(业务)/Services/Controllers |

---

## 11. 修复记录

### ✅ P0 已完成（2026-05-16）

1. **R02** `_activate_workspace_mode` → `lambda: self.window._activate_workspace_mode("experiment")` 委托 MainWindow
2. **R09** 6处信号 emit 补齐 → 所有操作统一调用 `_emit_workspace_signals()`
   - `create_variant` / `duplicate_variant` / `set_active_variant` / `set_task_lifecycle` / `sync_variant_from_base` / `set_variant_lifecycle`
3. **R11** 导出回退修复 → 保持源文件原始后缀，同步更新 ExportPath
4. 补充：`set_active_variant()` 增加 `task_index` 边界检查

### ✅ P1 已完成（2026-05-16）

1. **R05** `encode/decode_source_binding_token` → 移至 `utils/token_codec.py`
   - `main_controller.py` 和 `event_tree.py` 改从 utils 导入
2. **R03** `AudioMeterSnapshot` / `LoudnessReading` → 移至 `models/audio_meter_dto.py`
   - `audio_meter_service.py` 和 `main_window.py` 改从 models 导入
3. **R10** `DiagnosticSection` / `DiagnosticSnapshot` → 移至 `models/diagnostic_dto.py`
   - `main_controller.py` 改从 models 导入

### ✅ P2 已完成（2026-05-16）

1. **R08** `ExperimentExporter` 依赖注入改造
   - 构造函数接受可选 `audio_processor` 和 `runtime_exporter` 参数
   - `_export_experiment_delta()` 传入 `self.exporter` 实例
   - `RuntimeExporter` 的 `_serialize_*` 私有方法改为公开 `serialize_*`
2. **R07** `ProjectOpener` Protocol 解耦
   - 定义 `@runtime_checkable class ProjectOpener(Protocol)` 在 `experiment_controller.py`
   - `ExperimentController.__init__` 接收 `ProjectOpener` 而非 `MainController`
   - 完全移除 TYPE_CHECKING 循环导入

### 🔄 P3 待规划

1. **R01** MainController 拆分为 PreviewController / BuildController / ImportController / DiagnosticController
2. **R06** 引入声明式信号注册机制

---

## 12. 测试验证

- **测试套件**: 31项测试全部通过 ✅
- **新增文件**: `utils/token_codec.py` / `models/audio_meter_dto.py` / `models/diagnostic_dto.py`
- **修改文件**: `experiment_controller.py` / `experiment_exporter.py` / `exporter.py` / `main_controller.py` / `main_window.py` / `event_tree.py` / `audio_meter_service.py`

---

*报告更新于 2026-05-16。P0-P2 全部完成并验证，P3待规划。如需继续P3重构，请确认。*

