# AudioForge Changelog

本文档用于记录对外版本变更。版本号与 `audioforge/app/utils/constants.py` 中的 `APP_VERSION`、Unity 包产物目录名以及主文档中的版本说明保持一致。

当前采用的版本管理原则：

- 工具版本、Unity 包版本、主文档版本说明必须同步更新。
- 每个版本至少记录：新增能力、行为变化、修复项、验证结果。
- Git 提交负责记录实现细节；本文件负责回答“这一版具体给用户带来了什么变化”。

当前已补录的版本范围：0.03 - 0.05。

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
