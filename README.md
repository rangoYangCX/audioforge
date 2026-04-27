# AudioForge

AudioForge 是一个面向 Unity 休闲游戏项目的数据驱动音频工具。当前仓库已进入第一期可交付状态，覆盖工具端编辑、校验、导出、本地试听、Unity 参考运行时与对接文档，并保留测试与验证脚本作为交付基线的一部分。

## 当前状态

- 适用目标：UI / SFX / BGM 为主、事件驱动为主、接受轻量 SDK 的手游休闲项目。
- 工具端现状：已具备工程树、属性编辑器、内容编辑器、问题中心、响度监视器、总线编辑、自动恢复、高频快捷操作，以及事件树多选、批量改总线、批量重命名、批量删除与搜索定位。
- 运行时现状：仓库附带 Unity 参考运行时与空项目验证材料，适合联调与二次生产化落地。
- 当前验证基线：`pytest` 59 项通过；真实 WAV 烟雾工程 PASS；全链路检查 4/4 通过。

## 第一期交付范围

- PySide6 桌面工具主程序
- 面向休闲游戏常见 BGM / SFX / UI 工作流的工程浏览、属性编辑、内容编辑与响度监视器界面
- `.afproj` 工程保存与读取
- `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs` 与运行时音频资源导出
- 事件试听、响度分析、源文件与事件后双读数显示
- Unity 空项目验证运行时示例
- Unity 端对接开发文档

## 当前目录说明

- `audioforge/`：工具主程序源码
- `tests/`：单元测试与交互回归测试
- `tools/`：验证脚本、样板工程脚本和全链路检查脚本
- `Export/`：当前导出样例
- `reports/`：内部发布验证产物与检查报告
- `docs/UnitySDK对接规范.md`：Unity 端主对接文档，后续优先维护
- `docs/AudioForge概述.md`：脱敏概述文档，适合非技术传播或对外介绍
- `docs/internal/internal_release_execution_plan.md`：内部上线执行表与验证命令
- `unity_validation/`：Unity 空项目验证运行时与说明
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

- `pytest`：59 项全部通过
- `tools/run_internal_release_validation.py`：PASS
- `tools/run_full_chain_check.py`：4/4 通过

## 推荐阅读顺序

1. `docs/UnitySDK对接规范.md`
2. `unity_validation/README.md`
3. `开发文档.md`
4. `docs/AudioForge概述.md`
5. `docs/internal/internal_release_execution_plan.md`

## 说明

- 当前仓库目标是让音频和 Unity 程序可以围绕稳定导出契约协作开发，并保留最小可重复验证链路。
- Unity 侧只消费导出结果，不依赖 Python 工具内部实现，不读取 `.afproj`。
- Unity 参考运行时定位为开发参考实现，不等于最终生产版 SDK；正式项目接入前仍建议做一次目标工程联调。