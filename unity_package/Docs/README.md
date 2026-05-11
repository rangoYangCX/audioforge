# AudioForge Unity SDK Docs

当前文档同步日期：2026-05-11

这个目录是交给 Unity 开发同学时的包内文档入口。目标是让接手人不翻整个仓库，也能按固定顺序完成导入、初始化、联调和二次开发。

## 包内建议阅读顺序

1. `QuickStart.md`
2. `../README.md`
3. `Canonical/UnitySDK对接规范.md`
4. `Canonical/Unity场景联调清单.md`
5. `../Examples/README.md`
6. `../Verification/full_chain_report.md`

## 生成后的交付包结构

- `Assets/AudioForgeRuntime/`：SDK 运行时代码和 Editor 工具。
- `Docs/`：包内说明入口与 canonical 文档副本。
- `Examples/`：带注释示范代码，按需手工拷入目标项目。
- `Verification/`：当前机器验证报告与签收摘要。

## 交接建议

1. 先用 `QuickStart.md` 跑通最小播放链路。
2. 再按 `Canonical/UnitySDK对接规范.md` 接入业务事件、总线和资源加载策略。
3. 最后根据 `Examples/` 里的示范代码，把参考脚本替换成项目自己的 AudioService、资源加载器和触发层。

补充说明：0.06.0 这轮发布主要更新桌面工具诊断、工作台布局和交付文档，不改变本目录内的 Unity SDK 代码结构。