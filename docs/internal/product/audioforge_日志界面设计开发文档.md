# AudioForge 日志界面设计开发文档

当前文档同步日期：2026-05-18

## 1. 文档目标

这份文档只解决一件事：

- 在不新起第二套导航体系的前提下，把 AudioForge 当前分散在日志文本框、结果中心、诊断概览和弹窗提示里的反馈能力，收口成一套可继续开发的日志界面方案。

它同时覆盖两层内容：

- 设计层：用户在什么位置看日志、怎么从日志定位对象、日志和诊断页如何分工。
- 开发层：数据模型、控制器接入点、视图改造点、回归测试口径。

## 2. 现有资料与约束来源

当前方案不是从零开始，而是建立在以下既有资料之上：

- `docs/operations/AudioForge日志与诊断暴露清单.md`
- `docs/internal/product/audioforge_桌面工具产品化路线图.md`
- `docs/releases/v0.06.0-github-release.md`
- `docs/internal/research/audioforge_主流音频中间件评估与优化报告.md`
- `docs/internal/archive/audioforge_商业化改造清单.md`

从这些资料可以提炼出 4 条冻结约束：

1. 日志、校验、构建、响度必须始终可回看，但不能长期抢占主编辑区。
2. 结果中心和结果坞是唯一允许继续增强的反馈入口，不新增独立“日志窗口”或平行工作区。
3. 用户不打开原始日志，也应该理解刚刚发生了什么；原始日志只负责深查，不负责承载全部产品反馈。
4. 日志界面增强不能改变 Unity SDK 契约，也不能把桌面工具内部状态写回导出结果。

## 3. 当前实现快照

### 3.1 视图结构

当前结果中心已经存在 5 个结果页：

- 日志
- 校验报告
- 构建报告
- 响度扫描
- 诊断概览

其中日志页仍以单个 `QPlainTextEdit` 为核心承载；诊断页负责汇总最近日志、校验、构建、响度和 Bus 状态。

### 3.2 关键代码现状

- `audioforge/app/views/main_window.py`
  - `append_log()` 当前直接把文本追加到 `log_output`，并只保留一条 `_latest_log_message`。
  - 日志结果页由 `_build_log_results_page()` 构建，本质上仍是“说明卡 + 原始文本框”。
  - 诊断页由 `_build_diagnostic_results_page()` 构建，已经具备 section 列表和 detail 输出区。
- `audioforge/app/controllers/main_controller.py`
  - `_handle_log_appended()` 会把最新日志同步进诊断快照的 `log` section。
  - `_publish_diagnostic_snapshot()` 已经形成控制器统一收口机制。
- `audioforge/app/models/diagnostic_dto.py`
  - 已提供 `DiagnosticSection` 和 `DiagnosticSnapshot`，但还没有日志条目级 DTO。

### 3.3 当前问题

当前日志界面的主要问题不是“没有日志”，而是“日志只有文本，没有产品化结构”：

1. 日志页只有原始文本，缺少按级别、子系统、对象、相关动作的筛选能力。
2. 弹窗通知、日志文本、诊断摘要三套反馈并存，用户心智分裂。
3. 诊断页只拿到“最近一条日志摘要”，没有条目级上下文和跳转能力。
4. `append_log()` 目前只有 message、level、context，缺少稳定 DTO、查询状态和持久化桥接。
5. 日志文件路径虽然在规范里要求暴露，但当前日志页没有把“当前会话日志位置”和“最近 fault 日志”做成显式入口。

## 4. 目标状态

目标不是把 AudioForge 做成完整 profiler，而是让日志界面达到“产品化反馈 + 深查入口”双重能力。

### 4.1 用户侧目标

- 设计师优先目标：能在 10 秒内判断最近发生了什么，不需要先理解原始日志格式。
- 维护优先目标：出现失败时能快速看到发生了什么、影响哪个对象、关联哪次操作，并能直接导出日志快照给研发或 QA 定位。
- 联调预留目标：日志条目模型天然支持外部来源字段，后续 Unity 联调和通信日志不需要新起第二套界面。
- 需要深查时，能从结果中心进入原始日志、结构化详情和关联对象。

### 4.2 研发侧目标

- 日志条目具备稳定字段，不再只是拼接文本。
- 控制器可以在不依赖弹窗的情况下，统一写日志、摘要和跳转目标。
- AB 实验日志需要带 task / variant / baseline / action 上下文，不能再和普通运行日志混成一条无结构文本流。
- 测试能稳定断言日志摘要、过滤结果、导出内容和导航目标，而不是只比较纯文本片段。

### 4.3 非目标

- 不新增独立诊断应用、独立窗口或新的主导航入口。
- 不在本轮引入运行时 IPC、socket 或 Unity 调试桥。
- 不把所有错误提示都改成静默提示；破坏性确认和文件选择仍保留现有交互。

## 5. 信息架构建议

### 5.1 总体分工

- 结果坞：只显示最近动作摘要、失败摘要和快捷入口。
- 日志页：负责条目级回看、筛选、搜索、定位对象、打开文件日志。
- 诊断概览页：负责跨日志 / 校验 / 构建 / 响度 / Bus 的统一摘要，不复制日志页全部内容。

### 5.2 日志页推荐结构

日志页建议从“单文本框”升级为“三段式”：

1. 顶部状态条
   - 当前会话日志路径
   - 最近 fault 日志路径
   - 最近关键失败摘要
   - 清空筛选 / 打开日志目录 / 复制关联 ID
2. 中部条目列表
   - 时间
   - 级别
   - 子系统
   - 来源（desktop / unity / runtime bridge）
   - 摘要
   - 关联对象标识
   - AB 实验任务 / 方案摘要
3. 右侧详情区
   - 完整 message
   - 结构化 context
   - target_type / target_id
   - correlation_id
   - experiment_context
   - 建议动作

### 5.3 与诊断页的关系

诊断页继续存在，但职责应收紧为“跨域摘要卡 + section 导航”：

- 日志 section 只显示“最近关键日志摘要 + 风险等级 + 跳转入口”。
- 实验 section 单独显示最近一次 AB 实验关键动作摘要，不和 build / validation 抢同一个 summary 位。
- 日志条目明细统一回到日志页。
- 诊断页不再承担原始日志浏览职责。

### 5.4 与弹窗通知的关系

推荐把通知分成两类：

- 阻断类：仍走 `QMessageBox`，例如 destructive confirm、必须即时决策的失败。
- 非阻断类：统一写入日志流并刷新结果坞摘要；如需要再配轻提示，而不是只弹窗不落条目。

## 6. 数据模型建议

建议新增独立日志 DTO，而不是继续复用纯文本：

```python
@dataclass(slots=True)
class LogEntry:
    timestamp: str
    level: str
    subsystem: str
   source: str
    message: str
    summary: str
    session_id: str
    correlation_id: str
   operation_id: str
   parent_operation_id: str
    project_name: str
    project_path: str
    target_type: str = ""
    target_id: str = ""
    context: dict[str, object] = field(default_factory=dict)
   experiment_context: ExperimentLogContext | None = None
```

字段来源直接对齐 `AudioForge日志与诊断暴露清单.md`：

- 必选：`timestamp`、`level`、`subsystem`、`message`、`correlation_id`
- 推荐：`project_name`、`project_path`、`failure_stage`、`elapsed_ms`、`source`
- UI 专用：`summary`、`target_type`、`target_id`
- AB 实验专用：`experiment_context.task_name`、`variant_name`、`baseline_variant_name`、`action`
- Unity 预留：`source`、`operation_id`、`parent_operation_id` 用于后续把 Unity 编辑器日志、运行时桥接日志并入同一列表而不改 UI 架构。

建议同时补一个内存态 store：

```python
class LogStore:
    def append(entry: LogEntry) -> None: ...
    def latest(level: str | None = None) -> LogEntry | None: ...
    def query(filters: LogQuery) -> list[LogEntry]: ...
```

这样可以解决当前只保留 `_latest_log_message` 的问题。

## 7. 代码改造建议

### 7.1 视图层

改造文件：`audioforge/app/views/main_window.py`

目标：

- `append_log()` 改为接收结构化条目或能安全构造条目。
- 日志页从 `QPlainTextEdit` 升级为“列表 + 详情 + 筛选”。
- 保留原始文本输出区作为 secondary surface，而不是 primary surface。

建议新增：

- `log_filter_level_combo`
- `log_filter_subsystem_combo`
- `log_filter_keyword_edit`
- `log_entry_list`
- `log_entry_detail_output`
- `open_session_log_button`
- `open_fault_log_button`

### 7.2 控制器层

改造文件：

- `audioforge/app/controllers/main_controller.py`
- `audioforge/app/controllers/build_export_controller.py`
- `audioforge/app/controllers/preview_playback_controller.py`
- `audioforge/app/controllers/experiment_integration_controller.py`

目标：

- 所有关键操作不再只传入 message，而是带上 `subsystem`、目标对象、相关上下文。
- `_handle_log_appended()` 从“只更新最近摘要”升级为“消费结构化条目并更新 store + 诊断摘要 + 实验摘要”。
- 非阻断通知统一同时写入日志流。
- AB 实验控制器在 save / switch / sync / compare / export 上必须补齐 experiment_context。
- 试听、构建链路至少要补齐 subsystem、target、关键导出字段，确保设计师和维护同学看到的是同一批结构化结果。

### 7.3 模型 / 服务层

建议新增：

- `audioforge/app/models/log_entry_dto.py`
- `audioforge/app/services/log_store.py`

职责分工：

- DTO 负责字段稳定。
- Store 负责查询、筛选、最近摘要和列表容量控制。
- `runtime_logging` 继续负责文件日志，不和 UI store 混成一层。

### 7.4 文件日志桥接

当前文件日志不应直接变成 UI 主数据源，但应提供桥接信息：

- 当前会话文件路径
- latest.log 路径
- latest.fault.log 路径
- 最近 fault 条目的摘要和时间
- 当前筛选结果可直接导出为 JSON / 文本快照，作为问题单附件或联调记录

这层桥接推荐通过只读 metadata 完成，不在 UI 里实时 tail 整个日志文件。

## 8. 交互细节建议

### 8.1 默认状态

- 没有日志时，日志页显示空状态卡，不显示大面积空文本框。
- 空状态文案要区分“刚启动尚无日志”和“已清空筛选导致无结果”。

### 8.2 失败状态

- 最近失败条目固定浮在日志页顶栏。
- 若条目带 `target_type` / `target_id`，详情区显示“定位对象”按钮。
- 若条目带 `correlation_id`，提供复制按钮，方便去文件日志或报告里对齐。

### 8.3 与结果坞的联动

- 结果坞只显示最近 1 到 3 条关键反馈。
- 点击结果坞摘要直接切到日志页并带筛选条件。

### 8.4 与诊断页的联动

- 诊断页中的“日志” section 双击后，直接跳到日志页并选中对应条目。
- 诊断页只显示摘要，不复制日志列表。

## 9. 分阶段开发计划

### P0：日志条目结构化

- 新增 `LogEntry` DTO 和 `LogStore`
- `append_log()` 接入结构化字段
- 控制器关键路径补 `subsystem` 和 `target`

验收：

- 日志页仍可显示原有内容
- 诊断页摘要不回退
- 原始文件日志链路不受影响

### P1：日志页 UI 升级

- 增加筛选条、列表区、详情区
- 会话日志路径和 fault 日志路径显式展示
- 支持从条目定位对象
- 支持导出当前筛选日志快照

验收：

- 不新增独立窗口
- 结果中心现有 5 页结构不被打散
- 日志页能完成“筛选 + 查看 + 定位”闭环

### P2：通知收口

- 非阻断通知统一入日志
- 结果坞摘要和日志页共享同一数据源
- 诊断页改为消费 store 生成摘要
- 新增 experiment diagnostic section，承接 AB 实验主动作摘要

验收：

- 用户不打开原始日志，也能理解最近发生了什么
- 失败时能快速看到对象、原因和建议动作

### P3：测试和文档补齐

- 更新日志与诊断暴露清单
- 补日志页布局和交互回归
- 补 store 查询单测
- 补导出链路测试、AB 实验日志上下文测试、结果中心筛选测试

## 10. 测试流程

本轮日志系统测试按 4 层执行，不允许只做 GUI 点击截图式验收：

1. 模型层
   - `LogEntry` / `ExperimentLogContext` 字段归一化
   - `LogStore` 查询、筛选、容量上限、最近失败提取
2. 视图层
   - 日志页存在状态栏、筛选区、列表区、详情区、原始文本区
   - 改变筛选条件后，列表和详情能稳定刷新
   - 导出 JSON / 文本快照内容正确
3. 控制器集成层
   - 构建、试听、AB 实验关键动作都会写入结构化日志
   - `MainController` 会把实验日志同步到 diagnostic experiment section
4. 回归入口
   - 跑聚焦 pytest 切片验证日志系统
   - 再跑已有 MainController 关键布局 / 流程回归，确认没有破坏旧日志文本断言面

## 11. 回归测试建议

建议至少补以下测试：

1. `tests/unit/test_main_controller_layout.py` 或拆分后的日志页专用布局测试
   - 日志页存在筛选区、列表区、详情区
2. `tests/unit/test_main_controller_full_flow.py`
   - 构建失败、校验失败、试听失败会同步刷新日志摘要和定位入口
3. 新增 `tests/unit/test_log_store.py`
   - 查询、筛选、容量控制、最近失败提取
4. 新增通知收口测试
   - 非阻断通知进入日志流；阻断通知仍走弹窗

## 12. AB 实验适配评估与升级结论

基于当前实现评估，原始日志设计可以复用，但如果不升级，会直接卡在 AB 实验场景：

- 现有 `append_log()` 只保留文本，无法稳定表达 task / variant / baseline / action。
- AB 实验文档已经明确要求“所有实验主动作完成后都写入日志，并刷新实验面板摘要”。
- 结果中心未来还要承接实验过滤器和实验时间线，如果现在不把 source / experiment_context / operation_id 补进去，后续只能推翻重做。

因此结论不是“另做一套实验日志系统”，而是：

1. 在统一日志链路里增加 experiment_context。
2. 在诊断页增加 experiment section。
3. 在日志页增加实验筛选和导出能力。
4. 用同一 DTO 为后续 Unity 联调来源预留字段。

## 13. 风险与规避

### 11.1 风险：把日志页做成第二个诊断页

规避：

- 日志页只做条目级浏览。
- 诊断页只做跨域摘要。

### 11.2 风险：继续把产品反馈全塞进纯文本

规避：

- 任何新增关键反馈都先定义字段，再决定如何渲染。

### 11.3 风险：通知和日志再次分叉

规避：

- 非阻断通知必须有日志落点。
- 诊断页和结果坞都只消费统一日志源。

## 14. 结论

日志界面的下一轮重点，不是继续堆更多文本，而是把当前已经存在的日志、诊断摘要、结果坞和通知机制收成一套统一反馈系统。

最小可落地路径是：

1. 先补结构化日志 DTO 和 store。
2. 再把日志页升级为状态栏 + 筛选 + 列表 + 详情 + 导出。
3. 同步把构建、试听、AB 实验三条主链路改成写结构化日志。
4. 最后让诊断页、结果坞和未来 Unity 联调入口消费同一条数据链。 

这样可以在不改主导航、不改 Unity 契约的前提下，把日志界面从“文本回看区”升级成真正可开发、可验证、可定位问题的产品级反馈入口。