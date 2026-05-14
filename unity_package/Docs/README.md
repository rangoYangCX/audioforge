# AudioForge Unity SDK Docs

当前文档同步日期：2026-05-14

这个目录是交给 Unity 开发同学时的包内文档入口。目标是让接手人不翻整个仓库，也能按固定顺序完成导入、初始化、联调和二次开发。

## 包内建议阅读顺序

1. `QuickStart.md`
2. `一期对比变化总览.md`
3. `../../README.md`
4. `Canonical/UnitySDK输出规范.md`
5. `Canonical/UnitySDK对接规范.md`
6. `Canonical/Unity场景联调清单.md`
7. `../Examples/README.md`
8. `../Verification/full_chain_report.md`

当前包内 runtime 已支持 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]`、GameParameters / StateGroups / SwitchGroups、Audio/总线级 GameSync 绑定、emitter context 与 child effects smoke；当前正式把 Event 固定为动作层、把 AudioObject 固定为声音层。若项目内有自研 runtime，建议优先阅读 `Canonical/UnitySDK对接规范.md` 对齐当前契约。

从 0.09.1 起，包根目录结构也已固定到 `Canonical/UnitySDK输出规范.md` 中定义的 `com.audioforge.runtime` UPM 骨架；如果拿到包后发现不是 `package.json + Runtime/ + Editor/ + Documentation~/` 这一套结构，应视为交付异常。

## 生成后的交付包结构

- `package.json`：UPM 包清单，包名固定为 `com.audioforge.runtime`。
- `Runtime/`：SDK 运行时代码与运行时侧资源。
- `Editor/`：Inspector、自检和编辑器辅助工具。
- `Documentation~/Docs/`：包内说明入口与 canonical 文档副本。
- `Documentation~/Examples/`：带注释示范代码，按需手工拷入目标项目。
- `Documentation~/Verification/`：当前机器验证报告与签收摘要。

## 交接建议

1. 先用 `QuickStart.md` 跑通最小播放链路。
2. 再按 `Canonical/UnitySDK输出规范.md` 和 `Canonical/UnitySDK对接规范.md` 接入业务事件、总线和资源加载策略。
3. 最后根据 `Examples/` 里的示范代码，把参考脚本替换成项目自己的 AudioService、资源加载器和触发层。

补充说明：当前这轮包内文档仍建议把 `一期对比变化总览.md` 当成第一份差异化入口，但请注意它已不再只覆盖 `OneShot`，而是会明确标出 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]`、GameSync，以及 Event / AudioObject 拆层契约变化。