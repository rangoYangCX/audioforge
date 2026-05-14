# AudioForge 发布执行手册

当前文档同步日期：2026-05-14

## 目标

这份文档用于回答两个问题：

1. 当前仓库用于内部发布或交接时，最小验证闭环是什么。
2. 发布前必须执行哪些命令，产出哪些签收材料。

## 当前发布基线

- 当前桌面工具版本：`0.09.1`
- 当前主契约：`SchemaVersion = 3`
- 当前完整 Python 测试基线：`pytest` 112 项通过
- 当前真实 WAV 烟雾验证：PASS
- 当前全链路检查：4/4 通过
- 当前 phase3 聚焦回归：25 项通过

## 必跑命令

```powershell
python -m pytest
python tools/run_internal_release_validation.py --source-dir "E:\sfx\116 Casual UI\Casual UI\Casual UI DS"
python tools/run_full_chain_check.py --export-dir reports/internal_release_smoke/export --report-dir reports/internal_release_smoke/checks
```

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
5. 若本次包含 Unity SDK 或桌面发版，确认打包脚本能找到当前文档新路径。

## 当前结论

- 当前仓库已经具备“工具端可导出、契约可检查、SDK 可打包、报告可签收”的内部发布基线。
- 运行时与工具端的当前正式口径统一为 `SchemaVersion = 3` 与 `AudioObjects + Events[AudioId]`。
- 后续只要发布基线、报告路径或打包目录结构发生变化，必须同步更新本文档。