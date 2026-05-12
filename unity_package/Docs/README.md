# AudioForge Unity SDK Docs

当前文档同步日期：2026-05-12

这个目录是交给 Unity 开发同学时的包内文档入口。目标是让接手人不翻整个仓库，也能按固定顺序完成导入、初始化、联调和二次开发。

## 包内建议阅读顺序

1. `QuickStart.md`
2. `一期对比变化总览.md`
3. `../../README.md`
4. `Canonical/UnitySDK对接规范.md`
5. `Canonical/Unity场景联调清单.md`
6. `../Examples/README.md`
7. `../Verification/full_chain_report.md`

## 生成后的交付包结构

- `package.json`：UPM 包清单，包名固定为 `com.audioforge.runtime`。
- `Runtime/`：SDK 运行时代码与运行时侧资源。
- `Editor/`：Inspector、自检和编辑器辅助工具。
- `Documentation~/Docs/`：包内说明入口与 canonical 文档副本。
- `Documentation~/Examples/`：带注释示范代码，按需手工拷入目标项目。
- `Documentation~/Verification/`：当前机器验证报告与签收摘要。

## 交接建议

1. 先用 `QuickStart.md` 跑通最小播放链路。
2. 再按 `Canonical/UnitySDK对接规范.md` 接入业务事件、总线和资源加载策略。
3. 最后根据 `Examples/` 里的示范代码，把参考脚本替换成项目自己的 AudioService、资源加载器和触发层。

补充说明：0.07.0 这轮发布建议把 `一期对比变化总览.md` 当成包内第一份差异化入口。它会直接告诉你哪些变化真的影响 Unity 理解，哪些仍然只停留在编辑器侧。