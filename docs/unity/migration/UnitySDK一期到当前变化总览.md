# AudioForge Unity SDK 一期到当前变化总览

当前文档同步日期：2026-05-14

这份文档只回答一个问题：如果你已经按第一期心智开始对接 Unity SDK，那么当前版本相对一期到底改了什么，哪些需要你关注，哪些仍然不需要动 Unity 代码。

## 一眼结论

- 当前相对第一期，运行时层已经从 `SchemaVersion = 1` 升到 `SchemaVersion = 3`，不再只有 `PlayMode = OneShot` 这一处变化。
- 当前导出会额外写出顶层 `AudioObjects`、项目级 `GameParameters / StateGroups / SwitchGroups`，以及 Audio/总线级 Game Sync 绑定；如果项目使用仓库自带 runtime，重点是同步最新包；如果项目维护自研 runtime，则必须补齐 v3 解析与 emitter context。
- 对象浏览器三分页、事件树 bindings 弹窗、`Enabled` / `Active` 切换、拖拽追加反馈和智能总线分配设置，仍然主要是桌面工具编辑体验升级，不要求把这些 editor-only 状态原样写进 SDK。

## 和第一期对比，当前新增了什么

| 类别 | 第一期 | 当前版本 | Unity 侧要不要改 |
| --- | --- | --- | --- |
| 播放模式 | `Random / Sequence / Combo` | 明确补齐 `OneShot` | 要理解 `OneShot` 语义 |
| 导出版本 | `SchemaVersion = 1` | `SchemaVersion = 3`，主结构为 `AudioObjects + Events[AudioId]` | 若自研 runtime，需要补齐 v3 解析 |
| 项目级控制量 | 无 | `GameParameters`、`StateGroups`、`SwitchGroups` | 若自研 runtime，需要支持 |
| 事件/总线调制 | 无 | `RtpcBindings`、`StateOverrides`、`SwitchVariants` | 若自研 runtime，需要支持 |
| emitter 作用域 | 无 | `RegisterEmitter`、局部 RTPC、局部 Switch | 若项目要用 per-object 语义，需要支持 |
| Clip 消费方式 | Unity 侧按导出 `Clips` 播放 | 仍按导出 `Clips` 播放，但这些 `Clips` 已是工具端过滤后的有效集合 | 不需要新字段，只要继续消费导出结果 |
| 对象浏览 | 主要按一期工程树心智 | 升级为总线树 / 源音频树 / 事件树三分页 | 不需要 |
| 绑定编辑 | 一期没有当前这套弹窗工作流 | 事件树展开后通过 bindings 弹窗编辑绑定 | 不需要 |
| 绑定状态 | Unity 不感知 `Enabled / Active` 原始编辑态 | 这些状态仍只存在于编辑器与 `.afproj` | 不需要 |
| 默认总线策略 | 主要依赖固定默认值 | 新增按命名智能分配总线工程设置 | 不需要 |
| 自动建事件 | 拖入后主要按原模板建事件 | 单源音频自动建事件时默认 `OneShot` | 只要理解导出出来的 `PlayMode` 即可 |

## 现在必须确认的 Unity 侧理解

1. `PlayMode = OneShot` 表示一次触发只从当前有效 Clip 集合里取一个 Clip 播放。
2. 当前最新导出可能是 `SchemaVersion = 3`，其中会包含顶层 `AudioObjects`、项目级 Game Sync 定义和 Audio/总线级绑定；旧版只按 `Events + BusConfigs` 解析的自研 runtime 会漏能力。
3. Unity 侧不需要读取 `Enabled`、`Active`、bindings 弹窗状态或对象浏览器分页信息；这些都不会以 editor-only 原始状态进入当前导出 Schema。
4. 如果你看到导出的 `Clips` 数量变少，不一定是导出器丢数据，也可能是工具端已经按当前有效集合过滤过结果，或者当前事件正通过 `DefaultClipIds / SwitchVariants` 表达候选集。
5. 当前参考运行时代码已经能消费新版导出物；这次对使用官方包的同学主要是同步包和文档，对维护自研 runtime 的同学则是一次实质性的契约升级。

## 建议的对接动作

1. 先读 `docs/unity/UnitySDK对接规范.md` 里关于 `SchemaVersion = 3`、`AudioObjects + Events[AudioId]`、GameSync 字段和 editor-only 边界的最新说明。
2. 再拿最新打包目录 `dist/AudioForgeUnityPackage-0.09.1/` 或 zip 里的文档副本走一遍 Quick Start。
3. 如果项目里自己写过 runtime 解析层，先确认是否仍把顶层契约硬编码成只有 `BusConfigs` 与 `Events`。
4. 如果项目里自己写过 `PlayMode` 或 emitter 触发逻辑，确认没有遗漏 `OneShot`、`RegisterEmitter`、`SetSwitch`、`SetGameParameter` 这类新增路径。