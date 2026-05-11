# AudioForge Changelog

本文档用于记录对外版本变更。版本号与 `audioforge/app/utils/constants.py` 中的 `APP_VERSION`、Unity 包产物目录名以及主文档中的版本说明保持一致。

当前采用的版本管理原则：

- 工具版本、Unity 包版本、主文档版本说明必须同步更新。
- 每个版本至少记录：新增能力、行为变化、修复项、验证结果。
- Git 提交负责记录实现细节；本文件负责回答“这一版具体给用户带来了什么变化”。

当前已补录的版本范围：0.03 - 0.06.2，并使用 `Unreleased` 记录尚未单独发版的维护更新。

## [Unreleased]

- 批量导入音频为事件现已支持直接拖入多级文件夹；会按磁盘目录层级在事件树下自动创建对应文件夹，并在各层内继续生成同名事件。
- 修复最近试听卡片在自然播完后仍停留在“播放中”的状态问题；recent preview transport 会按当前事件与 Bus 状态重新刷新响度/音量指标，并放宽右侧 preview 区宽度限制，恢复边界拖拽与完整文本显示。
- 主窗口、分离工程浏览器、设置窗以及各工作区命名 splitter 的布局与大小现在统一写入窗口偏好；重开工程后会恢复工作区、页签和关键分栏状态，不影响既有 Unity 导出契约。
- 验证基线已刷新为 `pytest` 87 项通过。

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
