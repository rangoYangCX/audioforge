# AudioForge Changelog

本文档用于记录对外版本变更。版本号与 `audioforge/app/utils/constants.py` 中的 `APP_VERSION`、Unity 包产物目录名以及主文档中的版本说明保持一致。

当前采用的版本管理原则：

- 工具版本、Unity 包版本、主文档版本说明必须同步更新。
- 每个版本至少记录：新增能力、行为变化、修复项、验证结果。
- Git 提交负责记录实现细节；本文件负责回答“这一版具体给用户带来了什么变化”。

当前已补录的版本范围：0.03 - 0.09.0，并使用 `Unreleased` 记录尚未单独发版的维护更新。

## [Unreleased]

- 暂无未发布变更。

## [0.09.0] - 2026-05-14

### Added

- 项目级 `AudioObject` 正式进入主模型，Audio 树、Audio 引用关系和 Audio 级导入路径成为编辑器一等工作流。
- 导出契约正式升级为 `SchemaVersion = 3`，新增顶层 `AudioObjects`，并把事件与声音层关系固化为 `Events[AudioId]`。
- Unity runtime、JSON 适配器与全链路检查已接入 `AudioObjects + Events[AudioId]` 解析链，并新增针对缺失 `AudioId`、缺失 `AudioObject` 的契约错误校验。
- Bus 混音台工作区新增三分页结构，并把“当前 Bus”再细拆成“路由 / 电平与导出”二级页签，缓解总线编辑页拥挤问题。

### Changed

- Event 不再承载 Bus、PlayMode、Clips、GameSync 绑定或其他声音属性，只保留触发行为和 `AudioId` 引用。
- Source browser 的引用统计与未引用资源语义已切换到 Audio Object 口径，导入矩阵同步收口为事件树 / Audio 树 / 源音频树三条规则。
- Unity SDK 对接文档、README、开发文档、包内说明与 release note 已统一刷新到 0.09.0 和 Schema 3 口径。
- 版本锚点已统一刷新到 0.09.0，包括 `APP_VERSION`、`pyproject.toml`、README、CHANGELOG、开发文档、Unity 对接文档、包内说明和 release note。

### Fixed

- 修复在 `SFX` 下新建子 Bus 后继续切换浏览时误弹“父 Bus 非法”的状态串扰问题。
- 修复 Bus 混音台在单页堆叠下过于拥挤、布局快照无法准确反映当前总线编辑面的可用性问题。

### Validation

- `pytest tests/unit/test_main_controller_layout.py tests/unit/test_event_tree_widget.py tests/unit/test_exporter.py tests/unit/test_full_chain_check.py tests/unit/test_project_serializer.py`：112 项通过。
- Python / Qt 侧相关文件编辑器诊断：无错误。

## [0.08.0] - 2026-05-13

### Added

- phase3 主链已落地：工程模型、`.afproj` 序列化、Schema v2 导出、PreviewService 和 Unity runtime 现已统一支持 RTPC / State / Switch。
- 新增项目级 `GameParameters`、`StateGroups`、`SwitchGroups`，以及事件/总线级 `RtpcBindings`、`StateOverrides`、事件级 `SwitchVariants` 与 `DefaultClipIds`。
- 新增 GameSync 工作区、事件/总线绑定编辑器、State / Switch 子项 child effects 编辑、RTPC 图形曲线编辑器，以及试听中心内嵌 GameSync 控件与 transport 风格 RTPC 调参条。
- Unity runtime 新增 emitter context、`SetGlobalGameParameter` / `SetGameParameter` / `SetState` / `SetSwitch` API、Switch Variant 选片、Bus GameSync 求值与 child effects smoke。
- 事件 payload 新增嵌套 `Audio` 对象，并把 `Bus`、`PlayMode`、`AvoidImmediateRepeat`、音量/音高、Combo、Clips 与 GameSync 绑定正式收拢到音频层。

### Changed

- `SchemaVersion` 从 1 升级到 2，并保留 v1 payload 兼容初始化路径。
- StateGroup / SwitchGroup 在保留 names list 的同时新增 `state_effects` / `switch_effects`，兼容旧工程并让子项效果能贯穿 authoring、preview、exporter 与 Unity runtime。
- Unity SDK 对接文档、README、开发文档和包内 Quick Start 已同步改为当前 v2 契约口径，不再把 phase3 描述为“仅规划中”。
- 事件设计页视觉结构改为“事件元数据 / 播放控制 / Audio 属性 / Audio 调制”，并把 `AvoidImmediateRepeat` 从播放控制移到 Audio 层展示。
- `tools/run_full_chain_check.py` 现强校验 `SchemaVersion = 2` 事件必须带嵌套 `Audio`，且扁平镜像字段必须与 `Audio` 保持一致。
- 版本锚点已统一刷新到 0.08.0，包括 `APP_VERSION`、`pyproject.toml`、README、CHANGELOG、开发文档、Unity 对接文档、包内说明和 release note。

### Fixed

- 修复 GameSync 页面在新建参数、State 或 Switch 等操作后回跳概览页的问题，导航状态现在会保留 `gamesync_workspace_tab`。
- 修复试听中心 RTPC 参数条对负数范围支持不完整的问题，当前已按参数定义范围驱动 spin 与 slider。
- 修复“声音属性已经下沉到模型层，但事件设计页与发布态契约检查仍按旧事件层认知展示”的交付错位问题。

### Validation

- `pytest tests/unit/test_project_serializer.py tests/unit/test_exporter.py tests/unit/test_preview_service.py tests/unit/test_main_controller_layout.py -k "gamesync or preview_current_event_uses_preview_gamesync_context or preview_gamesync_change_retriggers_current_event_audition or preview_gamesync_parameter_editor_supports_negative_ranges or rtpc_curve_editor_uses_parameter_and_target_ranges"`：25 项通过。
- `pytest tests/unit/test_main_controller_layout.py -k "navigation_state_restores_gamesync_workspace_tab"`：1 项通过。
- Unity package 与 unity_validation 关键 C# 文件编辑器诊断：无错误。
- `pytest tests/unit/test_full_chain_check.py tests/unit/test_main_controller_layout.py -k "full_chain or preview_current_event_uses_preview_gamesync_context or preview_gamesync_change_retriggers_current_event_audition or selecting_folder_does_not_reset_active_property_tab or switching_from_contents_to_property_editor_keeps_clip_edit_stable"`：8 项通过。

## [0.07.0] - 2026-05-12

### Added

- 左侧对象浏览器升级为总线树、源音频树、事件树三分页，并补齐源音频引用浏览、缺失状态提示与从源音频定位事件的工作流。
- 事件树新增 Source Binding 弹窗工作流，追加绑定、替换绑定、拖拽追加反馈以及 `Enabled` / `Active` 切换统一收口到弹窗内完成。
- `PlayMode` 正式补齐 `OneShot`，单源音频自动建事件时默认落为 `OneShot`；试听、校验与导出统一按有效 Clip 集合工作。
- 工程设置新增“根据事件命名智能分配总线”开关，并纳入 `.afproj` 序列化。
- 新增“一期到当前变化总览”文档，同时补进仓库主文档入口和 Unity SDK 包内入口，方便 Unity 同学快速判断哪些变化需要关注。

### Changed

- Unity SDK 对接文档已明确 `PlayMode = OneShot` 的契约说明，并强调对象浏览器三分页、绑定弹窗、`Enabled` / `Active` 原始编辑态等仍是 editor-only，不进入当前运行时 Schema。
- 包内文档阅读顺序已调整为先读一期对比总览，再读 Quick Start、README 和 canonical 规范，减少 Unity 对接时的信息跳转成本。
- 版本锚点已统一刷新到 0.07.0，包括 `APP_VERSION`、打包产物目录名、README、CHANGELOG、开发文档、Unity 对接文档和 release note。

### Fixed

- 修复初始化阶段创建默认工程时访问 `self.project.settings` 过早，导致智能总线分配逻辑触发 `AttributeError` 的问题。
- 修复 OneShot 与多源绑定场景下试听、导出和校验对有效 Clip 集合的消费不一致问题。

### Validation

- `pytest`：112 项通过。
- OneShot 导出、预览和校验相关回归测试已补齐，覆盖有效绑定过滤与工程设置 round-trip。

## [0.06.2] - 2026-05-11

### Changed

- 最近试听侧栏卡片进一步收口为更明确的 transport card，标题、状态、控制按钮和响度摘要分层展示，不再像表单块一样占用右侧注意力。
- 最近试听按钮继续放大并增强状态反馈，播放中、暂停、可试听和可重播都能直接通过状态徽标和圆形图标按钮识别。
- README、开发文档、Unity 对接文档、包内文档和 GitHub release 说明已同步到 0.06.2，版本锚点与打包产物名保持一致。

### Fixed

- 修复最近试听卡片与响度监视器复用同一组摘要标签，导致侧栏卡片内部指标会被后续视图挂载挪走的问题。
- 修复最近试听跨工作区常驻后，状态感知弱、卡片内部层级不清晰的问题。

### Validation

- PySide 离屏 recent preview 回归断言通过：侧栏宽度、按钮尺寸、状态徽标、暂停/继续信号切换和卡片内指标挂载均符合预期。
- `audioforge/app/views/main_window.py` 与 `tests/unit/test_main_controller_layout.py` 静态错误检查通过。

## [0.06.1] - 2026-05-11

### Changed

- 欢迎页进一步收敛为任务型首页，保留新建工程、打开工程以及直达事件设计、资源整理、Bus 混音台和结果中心的快捷入口。
- 底部结果坞改为默认紧凑、按需展开；展开后再显示诊断、日志、校验、构建和响度详情，完整回看仍统一进入结果中心。
- 工作区 overview card、note card 和状态条继续去重，重复说明和重复状态不再并排占用主工作流空间。
- README、开发文档、Unity 对接文档、空项目验证说明和内部上线执行表已按最新 smoke 结果刷新。

### Fixed

- 修复 `focus_panel("log")` 与 `restore_default_layout()` 在结果坞展开态上的配合不稳定问题。
- 修复欢迎页和工作区信息收口后，底部结果坞仍可能因默认展开而长期挤占主编辑空间的问题。

### Validation

- `pytest`：76 项通过。
- `python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"`：PASS。
- `python tools/run_full_chain_check.py --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks`：4/4 通过。
- `python audioforge/main.py`：主入口启动烟雾通过，无即时异常。

## [0.06.0] - 2026-05-11

### Added

- 结果中心新增“诊断概览”页，统一展示最近日志、校验、构建、响度和 Bus 上下文，不再平行新增第二套诊断模块。
- `MainController` 新增结构化 `DiagnosticSnapshot` / `DiagnosticSection` 收口，诊断 section 与 build metadata 会直接回流到主窗口。
- 构建交付页新增构建画像列表与详情，当前构建范围、资源差异和交付目标会直接显示在页面内。

### Changed

- 工具端构建执行改为后台线程，长批量导出时界面保持可响应；构建进行中会阻止重复发起、关闭窗口和切换工程。
- 启动入口新增运行期诊断日志、Python / 线程异常钩子和 Qt 消息落盘；构建链路新增逐资源开始 / 完成 / 失败日志，默认输出到 `%LOCALAPPDATA%/AudioForge/logs/`。
- 对“源格式与目标格式相同且无 Trim / Fade 处理”的音频资源改为直接复制，不再执行无意义重编码；Unity 运行时契约不变。
- 本地工作台布局进一步收敛为“左侧工程树 + 中央工作台 + 底部结果坞”，固定右侧检视器移除后，相关分栏都可手动拖拽缩放。
- 顶部“命令面板”已进一步收敛为导航与隐藏动作面板，并新增 `Ctrl+Shift+P` 快捷入口；顶栏和工作区中已经显式可见的执行按钮不再在这里重复暴露。
- 顶部全局搜索保留工程树过滤同步，但执行搜索时已升级为跨对象跳转，可直接命中工程对象、总线、校验问题、构建结果和响度结果。
- 底部结果坞新增结构化摘要卡，日志、校验、构建和响度状态会同步汇总到常驻入口层，减少在结果中心与主工作区之间来回切换。
- Bus 混音台新增路由图，可直接查看当前 Bus 到主 Bus 的父 Bus 链路、子 Bus 和有效输出百分比，并从图上跳转到相邻 Bus。
- 资源工作区新增批量编辑反馈卡，最近一次批量权重、批量属性、批量重命名、排序和拖拽重排都会在当前事件上下文中保留摘要。

### Fixed

- 修复大批量构建在 UI 线程同步导出时容易卡死甚至崩溃的问题。
- 修复部分 OGG 资源在“同格式、无额外处理”路径下重复编码时可能卡住导出的问题。
- 修复工作区在 `events` / `build` / `validation` / `results` 间切换时 `main_splitter` 被当前页 `sizeHint` 重新分配，导致中央编辑区被挤窄、内页签布局错乱的问题。

### Validation

- `pytest tests/unit/test_main_controller_full_flow.py::test_build_project_returns_before_background_export_finishes tests/unit/test_main_controller_full_flow.py::test_full_authoring_flow_from_wav_import_to_export tests/unit/test_main_controller_full_flow.py::test_invalid_combo_and_instance_limits_block_build_consistently tests/unit/test_main_controller_layout.py::test_build_project_handles_export_failure`：4/4 通过。
- `pytest tests/unit/test_exporter.py::test_audio_processor_copies_same_format_without_reencoding tests/unit/test_exporter.py::test_runtime_exporter_writes_bundle_and_assets tests/unit/test_exporter.py::test_runtime_exporter_is_stable_across_repeated_exports tests/unit/test_exporter.py::test_runtime_exporter_incremental_rebuilds_only_changed_assets`：4/4 通过。
- `pytest tests/unit/test_main_controller_layout.py`：41/41 通过。
- 问题文件 `game_bgm.ogg` 的同格式导出隔离探针已通过，不再卡在 OGG 写出阶段。
- PySide 离屏烟雾验证已通过：命令面板会保留导航与隐藏动作条目，且不再重复暴露新建工程、保存工程、构建导出等显式按钮动作。
- PySide 离屏烟雾验证已通过：全局搜索候选可命中事件、总线和构建结果，且能触发对应跳转动作。
- PySide 离屏烟雾验证已通过：结果坞摘要卡会同步最近日志、校验计数、构建亮点和响度结论。
- PySide 离屏烟雾验证已通过：Bus 路由图会生成“父 Bus 链路 + 子 Bus”两层结构，资源页最近批量反馈会在同一事件内保留并回写概览提示。

## [0.05] - 2026-04-30

### Added

- 构建交付页新增“全量构建 / 增量构建 / 选中构建”三种范围。
- 构建页新增构建计划摘要，能直接显示请求范围、实际执行范围、重建资源数、复用资源数和移除资源数。
- `AudioManifest.json` 新增 `BuildFingerprint` 字段，用于资源内容级构建指纹。
- `BuildReport.json` 新增 `BuildPlan` 结构，记录 `RequestedScope`、`EffectiveScope`、`SelectionLabel`、`RebuiltAssetKeys`、`ReusedAssetKeys`、`RemovedAssetKeys`、`OutOfScopeDirtyAssetKeys` 等信息。
- 新增导出器回归测试，覆盖“仅重建脏资源”和“选中构建自动升级为增量构建”两类关键行为。

### Changed

- 导出链路改为“元数据全量刷新 + 音频资源按计划增量重建或复用”。
- 选中构建不再尝试导出残缺子包；若发现选区外仍有脏资源，会自动升级为增量构建，保持完整包一致性。
- Unity 包发版脚本默认改用 `reports/internal_release_smoke/export` 作为正式样例导出目录，避免被根目录 `Export/` 的本地临时状态污染。
- 主文档、README、Unity 对接文档和 Unity 包说明统一同步到 0.05。

### Fixed

- 修复底部日志面板在内容页/编辑页切换后被 Qt 可见态误隐藏的问题。
- 修复构建状态摘要容易被普通工作区刷新覆盖的问题，构建进行中和构建完成态现在会稳定保留。

### Validation

- `pytest`：65 项通过。
- `python tools/run_full_chain_check.py --skip-pytest --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks`：4/4 通过。
- `python tools/run_unity_package_release.py --skip-pytest`：PASS。

## [0.04] - 2026-04-30

### Added

- 片段波形编辑台、波形缩放、播放头、聚焦选区与局部试听。
- `FadeInMs`、`FadeOutMs` 编辑能力和导出链路。
- 片段裁剪、淡入淡出在导出阶段直接烘焙进运行时音频文件。
- Unity 参考运行时显式读取 Fade 元数据，并在调试记录中展示 Trim / Fade / Loop 信息。

### Changed

- 音频编辑体验从纯文字表单升级为波形驱动的片段精修工作流。
- 构建结果、响度结果和编辑器试听链路进一步收口，便于与 Unity 联调。

## [0.03] - 2026-04-30

### Added

- Unity 场景级联调清单。
- Unity 运行时交付内容补充 Event Id 搜索增强。
- 支持从 `AudioData.json` 刷新 `AudioEventID.cs` 的菜单工具。
- Unity AudioMixer 音量联调能力。

### Changed

- 桌面端与 Unity 侧交付链路收口到独立 Unity 包发版流程。
