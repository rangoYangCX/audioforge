# AudioForge

AudioForge 是一个面向 Unity 休闲游戏项目的数据驱动音频工具。当前仓库在保留 phase2 编辑器交付基线的同时，已经把 phase3 的 Wwise 风格 RTPC、State、Switch 主链推进到 Schema 3：项目级 Audio Object 主模型、Events 引用 AudioId、AudioObjects 导出、Unity runtime 消费链和验证链路都已打通。

当前桌面工具版本：0.09.2

当前文档同步日期：2026-05-15

## 使用入口

- 文档总索引：`docs/README.md`
- 统一使用说明：`docs/guides/AudioForge使用说明.md`
- Unity 端对接主文档：`docs/unity/UnitySDK对接规范.md`
- SDK 输出规范：`docs/unity/UnitySDK输出规范.md`
- 工具总体设计与边界：`开发文档.md`

## 当前状态

- 适用目标：UI / SFX / BGM 为主、事件驱动为主、接受轻量 SDK 的手游休闲项目。
- 阶段状态：phase2 的对象浏览器三分页、绑定弹窗、OneShot 与 UPM SDK 交付仍然保留；phase3 当前已冻结到项目级 Audio Object 主模型、Schema v3 导出、Audio 树编辑流和 Unity runtime 的 AudioId 消费链。
- 工具端现状：已具备 AppShell 主壳层、顶部应用栏、左侧任务导航、欢迎页、六大主工作区、结果中心、问题中心、响度监视器、总线编辑、自动恢复和高频快捷操作，以及事件树多选、批量改总线、批量重命名、批量删除、搜索定位、全量/增量/选中构建和构建计划预览；当前还新增了 GameSync 工作区、State/Switch 子项效果编辑、RTPC 图形曲线编辑器和 transport 风格试听 RTPC 调参条。
- 运行时现状：仓库附带独立维护的 Unity 集成包与空项目验证材料，当前已支持 SchemaVersion 3、AudioObjects、Events[AudioId]、GameParameters/StateGroups/SwitchGroups、Audio/Bus 级 GameSync 绑定、emitter context、全局 State、全局/局部 Game Parameter 与 child effects smoke；最新 SDK 口径已明确拆开 `SetGlobalGameParameter` 与 `SetEmitterGameParameter`，并把 Switch 调用统一到 emitter 语义。
- 当前验证基线：`pytest tests/unit` 159 项通过，`python tools/run_unity_package_release.py --skip-pytest` PASS，`python tools/build_windows_exe.py` PASS；Windows 发布目录已再次确认包含 `SDK/com.audioforge.runtime/`，Unity 包签收材料已刷新到 `reports/unity_package_release/`。

## 第一期交付范围

- PySide6 桌面工具主程序
- 面向休闲游戏常见 BGM / SFX / UI 工作流的工程浏览、属性编辑、内容编辑与响度监视器界面
- `.afproj` 工程保存与读取
- `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 与运行时音频资源导出
- 事件试听、响度分析、源文件与事件后双读数显示
- Unity 空项目验证运行时示例
- Unity 端对接开发文档
- Unity 场景级联调清单与发布说明

## 0.09.2 更新摘要

- 底部区域重构为完整试听中心，移除了波形编辑、Bus 视图和结果卡片等非核心入口；日志/校验/构建/响度详情统一收口到结果中心，底部保留全局轻状态提醒。
- 试听 GameSync 条现可直接显示当前命中的作用域来源：RTPC 会区分 `Emitter / Global / Default`，State 固定标记 `Global`，Switch 会区分 `Manual / Mapped / Default` 并显示映射参数回退来源。
- Unity runtime 与 validation runtime 现正式提供 `SetEmitterGameParameter` / `GetEmitterGameParameter` / `ResetEmitterGameParameter` 等世界/个体上下文 API，旧 `SetGameParameter` 保留兼容转发；EventPlayer 和 validation runner 示例已统一切到新口径。
- 资源工作区片段编辑台现支持 `wide / medium / compact` 响应式布局，并修复重排时误销毁 Qt 控件的问题。
- 工程保存已升级为可迁移模式：源音频收纳进同名工程目录、ExportRoot 锚定到工程文件位置、mac 打包补齐运行库收集与高 DPI 兜底。

## 三期已落地摘要

- RTPC 已按连续 Game Parameter 落地，支持默认值、最小值、最大值、Global/Emitter 作用域、事件与总线绑定，以及曲线编辑器真实轴范围。
- State 已按全局离散模式落地，支持项目级 State Group、事件/总线 State Override，以及每个 State 子项独立的音量、音高、静音和备注效果。
- Switch 已按 emitter 级离散分支落地，支持项目级 Switch Group、RTPC 映射阈值、事件 Switch Variant 选片，以及每个 Switch 子项独立效果。
- 试听条现可直接解释当前命中链路：RTPC 会显示 `Emitter / Global / Default` 来源，State 固定标记 `Global`，Switch 会显示 `Manual / Mapped / Default` 结果来源和参数回退来源。
- Unity runtime 已支持 emitter handle、SetState、SetSwitch、SetGlobalGameParameter、SetEmitterGameParameter、Schema v3 初始化、Bus GameSync 求值和 validation smoke；旧 `SetGameParameter` 保留兼容转发，详细设计与当前边界见 `docs/unity/architecture/UnityRuntime三期GameSync设计.md`。

## 一期到当前的对接差异入口

- Unity 侧请先读 `docs/unity/migration/UnitySDK一期到当前变化总览.md`，快速判断本次交付相对一期到底新增了什么、哪些内容仍然不需要改 SDK 代码。
- SDK 包内对应入口为 `unity_package/Docs/一期对比变化总览.md`，拿到打包目录后无需再翻整个仓库找差异。

## 本地编辑器功能总览

下面这部分描述的是 AudioForge 本地编辑器当前已经能做的事情，重点覆盖工具端内容生产、校验、构建和本地联调，不包含 Unity 运行时代码本身。

### 1. 工程与工作区组织

- 提供欢迎页和六个主工作区：事件设计、资源整理、Bus 混音台、校验修复、构建交付、结果中心。
- 支持创建、打开、保存 `.afproj` 工程，并维护工程脏状态提示。
- 保存工程时会自动把当前引用到的源音频收纳到同名工程目录 `ProjectName/Sources/`，便于整包迁移、归档和交接。
- 支持自动恢复快照，异常退出后可从本地恢复最近一次工程状态。
- 支持主窗口、分离工程浏览器、设置窗以及各工作区命名 splitter 的布局与大小偏好恢复，并保留常用页签与工作区状态，减少频繁切页后的布局漂移。
- 顶部对象头会持续显示当前对象、当前工作区、报告页签、Bus 视图状态和片段选择数。
- 顶部命令面板已收敛为导航与隐藏动作入口，可通过 `Ctrl+Shift+P` 快速切换工作区、结果页，并执行另存工程、恢复布局等非显式入口动作。
- 顶部全局搜索已支持跨对象跳转，可从一个入口直接搜索工程对象、总线、校验问题、构建结果和响度结果。
- 底部结果坞已支持结构化摘要，可常驻回看最近日志、校验计数、构建亮点和响度结论，不必先切进结果中心。

### 2. 工程树与批量编辑

- 支持用 Folder / Event 两类节点组织工程结构，Folder 仅用于编辑期管理，Event 进入运行时导出。
- 支持新建、重命名、删除、复制、粘贴和拖拽调整层级。
- 支持工程树搜索过滤和事件快速定位；执行顶部全局搜索时可进一步跨对象跳转。
- 支持事件树多选，以及批量改总线、批量重命名、批量删除等高频整理动作。
- 支持右键菜单和快捷键操作，包括 `F2` 重命名、`Delete` 删除、`Ctrl+C` 复制对象标识、`Enter` 快速聚焦编辑。
- 对非法命名、脏状态和局部刷新后的选中状态都有即时反馈和保留。

### 3. 事件参数编辑

- 可编辑事件基础属性：`Event ID`、显示名、所属总线和备注。
- 支持三类核心播放模式：`Random`、`Sequence`、`Combo`。
- 支持常见触发约束：避免连续重复、冷却时间、实例上限、抢占策略。
- 支持基础音量、随机音量、基础音高、随机音高等常见调制参数。
- 支持 `Combo` 连击相关参数，包括步进音高、重置时间和最大步数。
- 默认面向休闲项目高频场景，优先覆盖 UI、SFX、BGM 的常见事件参数编辑工作流。

### 4. 资源整理与片段编排

- 支持从本地批量导入音频资源，当前主流程覆盖 `wav` / `ogg`。
- 可为一个事件组织多个候选片段，并维护每个片段的源路径、导出路径、资源键和权重。
- 支持片段权重编辑、导出路径预览和源文件存在性检查。
- 资源工作区现会保留最近一次批量权重、批量属性、批量重命名、排序或拖拽重排反馈，方便在片段页直接回看成组修改结果。
- 片段编排页已支持波形编辑，可直接调整 `TrimStartMs`、`TrimEndMs`、`FadeInMs`、`FadeOutMs`。
- 支持循环区间标注、滚轮缩放、双击聚焦选区，以及通过游标把当前时间快速写入起点、终点或循环区。
- 支持围绕当前播放头的局部试听，以及片段表右键菜单、定位源文件、复制资源键等高频操作。

### 5. 总线、混音与响度观察

- 提供独立的 Bus 混音台工作区，不再把 Bus 编辑混在普通属性页里。
- 支持主 Bus 和工程 Bus 树管理，包括父子层级、基础音量和静音状态。
- Bus 混音台已新增路由图，可同时回看当前 Bus、父 Bus 链路、子 Bus 和有效输出百分比。
- 支持 Bus 视图状态显示和传输控制侧 Bus 控制，方便在编辑期单独观察混音结构。
- 提供响度监视器和结果中心，可统一回看响度结果、构建输出和日志。
- 当前工具端已支持源文件与事件后结果的双读数观察，便于对比处理前后的听感与结果差异。

### 6. 校验与问题修复

- 提供独立的问题中心，采用“列表 + 详情”结构查看错误、警告和信息项。
- 支持从校验结果直接跳转回对象，修复后保持当前选中项和滚动位置。
- 支持即时校验和构建前全量校验两套入口，避免只靠最终导出时才发现问题。
- 当前校验覆盖事件 ID、重复命名、资源存在性、权重、总线合法性、随机范围、Combo 参数、资源冲突等常见问题。
- `Error` 会阻断构建，`Warning` 会保留风险提示但不阻断主流程。

### 7. 构建、导出与交付预览

- 支持三种构建范围：全量构建、增量构建、选中构建。
- 支持构建计划预览，可直接看到请求范围、实际执行范围、重建资源数、复用资源数和移除资源数。
- 支持导出差异预览和构建计划摘要，便于在交付前先审查这次会改动什么。
- 导出结果包含 `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs`、`BuildReport.json` 和运行时音频资源目录。
- 导出器已支持复用未变化资源，仅重建脏资源，并在 `AudioManifest.json` 中写出 `BuildFingerprint`，在 `BuildReport.json` 中写出 `BuildPlan`。
- 构建过程已切到后台线程执行，构建中会阻止重复发起、关闭窗口和切换工程，避免长任务把界面卡死。
- 对同格式且无 `Trim` / `Fade` 处理的资源，导出阶段会直接复制，减少不必要的重编码风险。

### 8. 本地试听、日志与诊断

- 本地试听会尽量对齐运行时事件逻辑，覆盖 `Random`、`Sequence`、`Combo`、冷却和实例限制等常见行为。
- 当前工具端的音高相关参数已统一按保时长变调提供参考听感，便于音频设计阶段先做主观判断。
- mac 端当前已补 Qt 缩放和 `pygame.mixer` 初始化兜底，但仍建议在真机上至少回归一次界面比例、播放/暂停/恢复和多素材 sample rate 切换。
- 结果中心和底部日志面板可统一回看构建日志、校验反馈、响度结果和交付状态。
- 工具启动时会自动安装运行期诊断日志，默认输出到 `%LOCALAPPDATA%/AudioForge/logs/`。
- 构建阶段会记录逐资源的开始、完成和失败日志，便于在大批量导出时快速定位具体卡在哪个资源。
- 当前日志体系已覆盖工程加载、校验、构建和运行期异常定位，适合问题复现后的第一轮自查。

## 当前目录说明

- `audioforge/`：工具主程序源码
- `tests/`：单元测试与交互回归测试
- `tools/`：验证脚本、样板工程脚本和全链路检查脚本
- `tools/package_unity_integration_package.py`：输出 Unity 独立包目录和 zip
- `tools/run_unity_package_release.py`：统一执行 Unity 包同步、检查、打包与签收报告输出
- `Export/`：默认导出目录名与本地导出落位
- `reports/`：内部发布验证产物与检查报告
- `CHANGELOG.md`：版本变更总表，记录每个版本具体新增、变化、修复与验证结果
- `docs/README.md`：文档总索引，按角色和主题选择阅读路径
- `docs/unity/UnitySDK对接规范.md`：Unity 端主对接文档，后续优先维护
- `docs/unity/validation/Unity场景联调清单.md`：目标 Unity 项目接入时的场景级联调与签收清单
- `docs/operations/internal_release_execution_plan.md`：内部发布执行与验证命令
- `unity_package/`：Unity 集成包真源，包含运行时代码、包内说明和示范代码
- `unity_package/Docs/`：SDK 包内文档入口与速查说明
- `unity_package/Examples/`：带注释的 Unity 接入示范代码，可按需手工拷入目标项目
- `unity_validation/`：Unity 空项目验证工程与说明，运行时目录由独立包同步而来
- `开发文档.md`：工具总体设计、边界和交付说明

## 运行方式

```bash
python -m audioforge.main
```

## 验证方式

```bash
python -m pytest
python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"
python tools/run_full_chain_check.py --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks
```

最近一次仓库内执行结果：

- `pytest`：112 项全部通过
- `tools/run_internal_release_validation.py`：PASS
- `tools/run_full_chain_check.py`：4/4 通过
- `reports/internal_release_smoke/checks/full_chain_report.md`：当前全链路机器报告
- `reports/internal_release_smoke/release_signoff.md`：当前烟雾工程签收摘要

## 推荐阅读顺序

1. `docs/README.md`
2. `docs/guides/AudioForge使用说明.md`
3. `CHANGELOG.md`
4. `开发文档.md`
5. `docs/unity/UnitySDK对接规范.md`
6. `docs/unity/architecture/UnityRuntime三期GameSync设计.md`
7. `docs/internal/architecture/audioforge_第三期RTPC-State-Switch路线图.md`
8. `unity_package/README.md`
9. `unity_validation/README.md`
10. `docs/operations/internal_release_execution_plan.md`

## 说明

- 当前仓库目标是让音频和 Unity 程序可以围绕稳定导出契约协作开发，并保留最小可重复验证链路。
- Unity 侧只消费导出结果，不依赖 Python 工具内部实现，不读取 `.afproj`。
- Unity 参考运行时定位为开发参考实现，不等于最终生产版 SDK；正式项目接入前仍建议做一次目标工程联调。