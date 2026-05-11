# AudioForge 内部上线执行表

当前文档同步日期：2026-05-11

## 目标

- 目标标准：支撑当前商业休闲游戏项目内部上线，形成可重复验证的导出与运行时交付链路。
- 本轮范围：先完成 P0 交付基线，包含执行表、pytest 基线恢复、真实 WAV 集成导出验证、全链路检查报告。

## 执行表

| 阶段 | 目标 | 交付物 | 验收标准 | 当前状态 |
| --- | --- | --- | --- | --- |
| P0 | 建立交付基线 | 执行表、pytest 基线、集成验证脚本 | `pytest` 通过；可用真实 WAV 目录生成导出；`tools/run_full_chain_check.py` 通过 | 已完成 |
| P1 | 收口导出稳定性 | 导出 bundle 回归用例、报告归档 | `AudioData.json`、`AudioManifest.json`、`AudioEventID.cs`、`BuildReport.json` 内容一致且可重复生成 | 已完成 |
| P2 | 收口运行时契约 | Unity 参考运行时契约复核、包体完整性检查 | 运行时字段与导出字段一一对应，Unity 验证包元文件齐全 | 已完成 |
| P3 | 收口项目韧性 | 自动恢复、异常恢复、用户操作保护 | 项目损坏与导出中断具备可恢复路径 | 已完成 |
| P4 | 内部上线签收 | 发布候选包、验证报告、风险清单 | 形成一份可归档的上线验收报告 | 已完成 |

## 本轮落地项

1. 恢复 `tests/`，覆盖序列化、校验器、导出器、预览总线混音器。
2. 新增真实素材集成脚本，从外部 WAV 目录自动生成烟雾测试项目并导出。
3. 复用 `tools/run_full_chain_check.py` 生成 JSON/Markdown 报告，作为本轮验收输出。
4. 补充自动恢复快照、未保存工程保护和发布签收摘要，完成内部上线收口。

## 本轮验收命令

```powershell
python -m pytest
python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"
python tools/run_full_chain_check.py --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks
```

## 当前结论

- P0 已完成，仓库现已具备最基本的交付闭环：可测、可导出、可生成检查报告。
- 本轮已补齐 P1-P4 的最小交付实现：重复导出回归、运行时契约增强检查、自动恢复、签收摘要归档。
- 当前桌面端编辑器的第一轮产品化 UI 重构也已并入主分支，但不改变导出契约与验收命令。

## 最新验证快照

- 最近一次完整 `pytest` 基线：87 项通过。
- 最近一次真实素材烟雾验证：PASS，使用 12 个 WAV 样本，校验警告 0。
- 最近一次全链路检查：4/4 通过，覆盖 `pytest`、导出 bundle、运行时契约、Unity 集成包完整性。
- 2026-05-11 冒烟复跑已刷新 `reports/internal_release_smoke/release_signoff.md` 与 `reports/internal_release_smoke/checks/full_chain_report.md`，桌面程序主入口启动烟雾无即时异常。
- 报告路径：`reports/internal_release_smoke/checks/full_chain_report.md`