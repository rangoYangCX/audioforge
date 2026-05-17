# AudioForge 发布执行手册

当前文档同步日期：2026-05-17

## 目标

这份文档用于回答两个问题：

1. 当前仓库用于内部发布或交接时，最小验证闭环是什么。
2. 发布前必须执行哪些命令，产出哪些签收材料。

## 当前发布基线

- 当前桌面工具版本：`0.09.2`
- 当前主契约：`SchemaVersion = 3`
- 当前完整 Python 测试基线：仓库已切到 `tools/run_test_suite.py` 分层入口，发布前如需全量 Python 扫描再显式使用 `--pytest-all`
- 当前 harness smoke：PASS
- 当前真实 WAV 烟雾验证：PASS
- 当前全链路检查：5/5 通过
- 当前 phase3 聚焦回归：25 项通过

## 必跑命令

```powershell
python tools/run_test_suite.py smoke
python tools/run_test_suite.py main-controller
python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"
python tools/run_full_chain_check.py --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks
```

说明：`run_full_chain_check.py` 现在默认包含 smoke pytest 与 harness smoke；除非明确排查脚本自身问题，否则不要加 `--skip-harness`。如果这次发布需要完整 Python 回归，再额外执行：

```powershell
python tools/run_full_chain_check.py --pytest-all --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks
```

如果已经有一份真实导出产物，不需要重新从 WAV 构建 smoke 工程，可以直接生成签收报告：

```powershell
python tools/run_internal_release_validation.py --existing-export-dir D:\builds\AudioForge\Export --skip-pytest
```

该模式会直接对现有导出目录运行 full-chain 与 harness 检查，并生成同结构的 `release_signoff.md/json`。

如需执行 Unity SDK 交付链路，还应补跑：

```powershell
python tools/run_unity_package_release.py --skip-pytest
```

如需验证桌面版交付目录，还应补跑：

```powershell
python tools/build_windows_exe.py
```

## 最小签收材料

- `reports/internal_release_smoke/checks/full_chain_report.md`
- `reports/internal_release_smoke/checks/full_chain_report.json`
- `reports/internal_release_smoke/checks/harness_smoke/harness_report.md`
- `reports/internal_release_smoke/checks/harness_smoke/harness_report.json`
- `reports/internal_release_smoke/release_signoff.md`
- `reports/internal_release_smoke/release_signoff.json`

如本次包含 Unity SDK 发版，还应补：

- `reports/unity_package_release/unity_package_release_signoff.md`
- `reports/unity_package_release/unity_package_release_signoff.json`

## 发布前检查清单

1. `APP_VERSION`、`pyproject.toml`、`CHANGELOG.md`、主说明文档与 release note 已同步。
2. `AudioData.json` 主契约、Unity runtime 和全链路检查口径一致。
3. 包内 canonical 文档可从当前 `docs/` 目录正确复制。
4. `reports/` 下已有最新 smoke 与 full chain 结果。
5. `reports/internal_release_smoke/checks/harness_smoke/` 下已有最新 harness 报告。
6. 若本次包含 Unity SDK 或桌面发版，确认打包脚本能找到当前文档新路径。
7. 若本次修改了开发流程、验证入口或架构边界，确认 `docs/internal/architecture/audioforge_开发完成定义与文档同步基线.md` 已同步。

## 当前结论

- 当前仓库已经具备“工具端可导出、契约可检查、SDK 可打包、报告可签收”的内部发布基线。
- 当前 full-chain 主入口已经把 harness smoke 纳入默认流程，发布和签收不再依赖手工补跑。
- 当前 full-chain 主入口默认只跑 smoke pytest，避免每次发布都被整仓 Python 测试时长拖住；完整 Python 回归改为显式 opt-in。
- 运行时与工具端的当前正式口径统一为 `SchemaVersion = 3` 与 `AudioObjects + Events[AudioId]`。
- 后续只要发布基线、报告路径或打包目录结构发生变化，必须同步更新本文档。

## 开发收口补充要求

- 每次开发默认流程不再只看“代码 + 测试”，还要显式检查文档同步。
- 当前唯一冻结口径见 `docs/internal/architecture/audioforge_开发完成定义与文档同步基线.md`。