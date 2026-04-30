# AudioForge

AudioForge 是一个面向 Unity 休闲游戏项目的数据驱动音频工具。当前仓库已进入第一期可交付状态，覆盖工具端编辑、校验、导出、本地试听、Unity 参考运行时与对接文档，并保留测试与验证脚本作为交付基线的一部分。

当前桌面工具版本：0.05

当前文档同步日期：2026-04-30

## 当前状态

- 适用目标：UI / SFX / BGM 为主、事件驱动为主、接受轻量 SDK 的手游休闲项目。
- 工具端现状：已具备 AppShell 主壳层、顶部应用栏、左侧任务导航、欢迎页、六大主工作区、结果中心、问题中心、响度监视器、总线编辑、自动恢复和高频快捷操作，以及事件树多选、批量改总线、批量重命名、批量删除、搜索定位、全量/增量/选中构建和构建计划预览。
- 运行时现状：仓库附带独立维护的 Unity 集成包与空项目验证材料，支持 Event Id 搜索、从 `AudioData.json` 刷新 `AudioEventID.cs`，以及 Unity AudioMixer 对接。
- 当前验证基线：`pytest` 65 项通过；真实 WAV 烟雾工程 PASS；全链路检查 4/4 通过。

## 第一期交付范围

- PySide6 桌面工具主程序
- 面向休闲游戏常见 BGM / SFX / UI 工作流的工程浏览、属性编辑、内容编辑与响度监视器界面
- `.afproj` 工程保存与读取
- `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 与运行时音频资源导出
- 事件试听、响度分析、源文件与事件后双读数显示
- Unity 空项目验证运行时示例
- Unity 端对接开发文档
- Unity 场景级联调清单与发布说明

## 0.05 更新摘要

- 构建交付页新增全量构建、增量构建和选中构建三种范围，并提供构建计划预览与即时状态反馈。
- 导出器现可复用上次导出的未变化音频资源，仅重建脏资源；`AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 仍保持全量刷新。
- `AudioManifest.json` 新增 `BuildFingerprint`，`BuildReport.json` 新增 `BuildPlan`，便于 CI、联调和大工程下的差异审计。

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
- `unity_package/`：Unity 集成包真源，供程序侧接入与单独维护
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
```

最近一次仓库内执行结果：

- `pytest`：65 项全部通过
- `tools/run_internal_release_validation.py`：PASS
- `tools/run_full_chain_check.py`：4/4 通过
- `reports/internal_release_smoke/checks/full_chain_report.md`：当前全链路机器报告

## 推荐阅读顺序

1. `docs/UnitySDK对接规范.md`
2. `CHANGELOG.md`
3. `docs/Unity场景联调清单.md`
4. `unity_package/README.md`
5. `unity_validation/README.md`
6. `开发文档.md`
7. `docs/WSG_audiotest.md`
8. `docs/internal/internal_release_execution_plan.md`

## 说明

- 当前仓库目标是让音频和 Unity 程序可以围绕稳定导出契约协作开发，并保留最小可重复验证链路。
- Unity 侧只消费导出结果，不依赖 Python 工具内部实现，不读取 `.afproj`。
- Unity 参考运行时定位为开发参考实现，不等于最终生产版 SDK；正式项目接入前仍建议做一次目标工程联调。