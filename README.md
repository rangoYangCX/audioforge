# AudioForge

AudioForge 是一个面向 Unity 休闲游戏项目的数据驱动音频工具。当前仓库已完成 phase2 编辑器交付，并在此基础上启动 phase3 规划：围绕 Wwise 的 RTPC、State、Switch 语义，补齐项目级 Game Sync 模型、导出契约升级和 Unity runtime 控制层设计。

当前桌面工具版本：0.07.0

当前文档同步日期：2026-05-13

## 当前状态

- 适用目标：UI / SFX / BGM 为主、事件驱动为主、接受轻量 SDK 的手游休闲项目。
- 阶段状态：phase2 已完成对象浏览器三分页、绑定弹窗、OneShot 语义补齐与 UPM SDK 交付；phase3 已进入详细设计阶段，目标是引入 Wwise 风格的 RTPC / State / Switch 控制层。
- 工具端现状：已具备 AppShell 主壳层、顶部应用栏、左侧任务导航、欢迎页、六大主工作区、结果中心、问题中心、响度监视器、总线编辑、自动恢复和高频快捷操作，以及事件树多选、批量改总线、批量重命名、批量删除、搜索定位、全量/增量/选中构建和构建计划预览；最近一轮维护更新已将大批量构建切到后台执行，并补上运行期诊断日志。
- 运行时现状：仓库附带独立维护的 Unity 集成包与空项目验证材料，支持 Event Id 搜索、从 `AudioData.json` 刷新 `AudioEventID.cs`，以及 Unity AudioMixer 对接；当前运行时契约仍停留在 Events + BusConfigs，尚未纳入 RTPC / State / Switch。
- 当前验证基线：最近一次完整基线为 `pytest` 112 项通过、真实 WAV 烟雾工程 PASS、全链路检查 4/4 通过；主窗口工作台聚焦回归已覆盖欢迎页直达入口、结果坞紧凑/展开、最近试听修复、对象浏览器三分页、绑定弹窗、OneShot 语义以及窗口偏好持久化回环。

## 第一期交付范围

- PySide6 桌面工具主程序
- 面向休闲游戏常见 BGM / SFX / UI 工作流的工程浏览、属性编辑、内容编辑与响度监视器界面
- `.afproj` 工程保存与读取
- `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 与运行时音频资源导出
- 事件试听、响度分析、源文件与事件后双读数显示
- Unity 空项目验证运行时示例
- Unity 端对接开发文档
- Unity 场景级联调清单与发布说明

## 0.07.0 更新摘要

- 左侧对象浏览器升级为“总线树 / 源音频树 / 事件树”三分页，并把源音频浏览、引用状态和事件定位收口到统一入口。
- 事件树不再把 Source Binding 永久堆在树节点里；当前版本改为只显示 Event，展开时通过绑定弹窗完成追加、替换、Active / Enabled 切换和拖拽追加反馈。
- `PlayMode` 已补齐 `OneShot`，单源音频拖入事件树自动建事件时会默认落成 `OneShot`；导出与试听统一按有效 Clip 集合工作。
- 工程设置新增“根据事件命名智能分配总线”开关，行为会随 `.afproj` 保存，团队协作时默认策略可复现。
- Unity 端仍不需要读取 editor-only 字段，但需要以最新版文档为准理解 `PlayMode = OneShot` 和“只消费有效 Clip 集合”的边界；如需同步这些说明、验证材料和最新签收结果，应重新生成 `dist/AudioForgeUnityPackage-0.07.0/`。

## 三期方向摘要

- phase3 的核心不是继续补编辑器视觉，而是把 Wwise 的 Game Sync 语义正式落到 AudioForge：RTPC 作为连续 Game Parameter，State 作为全局离散模式，Switch 作为按 emitter / game object 生效的离散分支选择。
- 这会成为当前仓库第一次明确升级 Unity 运行时契约的阶段，计划引入 Schema v2，而不是继续把新语义挤进现有 `Events` 和 `BusConfigs`。
- phase3 的最小实现优先级固定为：项目级数据模型和导出器、Unity runtime 控制层、验证与文档，再到工具端 authoring UI。
- 详细计划见 `docs/internal/audioforge_第三期RTPC-State-Switch实施计划.md`，运行时设计见 `docs/UnityRuntime三期GameSync设计.md`。

## 一期到当前的对接差异入口

- Unity 侧请先读 `docs/UnitySDK一期到当前变化总览.md`，快速判断本次交付相对一期到底新增了什么、哪些内容仍然不需要改 SDK 代码。
- SDK 包内对应入口为 `unity_package/Docs/一期对比变化总览.md`，拿到打包目录后无需再翻整个仓库找差异。

## 本地编辑器功能总览

下面这部分描述的是 AudioForge 本地编辑器当前已经能做的事情，重点覆盖工具端内容生产、校验、构建和本地联调，不包含 Unity 运行时代码本身。

### 1. 工程与工作区组织

- 提供欢迎页和六个主工作区：事件设计、资源整理、Bus 混音台、校验修复、构建交付、结果中心。
- 支持创建、打开、保存 `.afproj` 工程，并维护工程脏状态提示。
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
- `docs/UnitySDK对接规范.md`：Unity 端主对接文档，后续优先维护
- `docs/Unity场景联调清单.md`：目标 Unity 项目接入时的场景级联调与签收清单
- `docs/WSG_audiotest.md`：当前方案概述文档，适合先建立工具端/运行时协作边界理解
- `docs/internal/internal_release_execution_plan.md`：内部上线执行表与验证命令
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

- `pytest`：87 项全部通过
- `tools/run_internal_release_validation.py`：PASS
- `tools/run_full_chain_check.py`：4/4 通过
- `reports/internal_release_smoke/checks/full_chain_report.md`：当前全链路机器报告
- `reports/internal_release_smoke/release_signoff.md`：当前烟雾工程签收摘要

## 推荐阅读顺序

1. `docs/UnitySDK对接规范.md`
2. `CHANGELOG.md`
3. `开发文档.md`
4. `docs/UnityRuntime三期GameSync设计.md`
5. `docs/internal/audioforge_第三期RTPC-State-Switch实施计划.md`
6. `docs/Unity场景联调清单.md`
7. `unity_package/README.md`
8. `unity_validation/README.md`
9. `docs/WSG_audiotest.md`
10. `docs/internal/internal_release_execution_plan.md`

## 说明

- 当前仓库目标是让音频和 Unity 程序可以围绕稳定导出契约协作开发，并保留最小可重复验证链路。
- Unity 侧只消费导出结果，不依赖 Python 工具内部实现，不读取 `.afproj`。
- Unity 参考运行时定位为开发参考实现，不等于最终生产版 SDK；正式项目接入前仍建议做一次目标工程联调。