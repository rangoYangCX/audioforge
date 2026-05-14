# AudioForge Unity Integration Package

这个目录是 Unity 侧运行时资源的独立维护包，也是仓库内的唯一源码真源。

当前文档同步日期：2026-05-14

## 目录定位

- `unity_package/Assets/AudioForgeRuntime`：Unity 运行时脚本、Editor 工具和稳定 `.meta` 文件。
- `unity_package/Docs`：包内文档入口、速查说明和交付视角的阅读顺序。
- `unity_package/Examples`：带注释的示范代码文件，供 Unity 程序按需复制和改造。
- `unity_validation/Assets/AudioForgeRuntime`：用于空项目验证的镜像副本，不再作为手工维护入口。

当前对外打包形态已切到 Unity Package Manager 风格：执行 `python tools/package_unity_integration_package.py` 后，`dist/AudioForgeUnityPackage-<version>/` 根目录会生成 `package.json`、`Runtime/`、`Editor/` 和 `Documentation~/`，而不是直接把 `Assets/AudioForgeRuntime` 原样暴露为交付根目录。

## 维护规则

1. 所有 Unity 侧运行时代码只在 `unity_package/Assets/AudioForgeRuntime` 修改。
2. 修改后执行 `python tools/sync_unity_integration_package.py`，把包内容同步到 `unity_validation` 验证工程。
3. 交付给 Unity 程序时，优先直接交这个包目录，而不是从验证工程里手动挑文件。
4. 执行 `python tools/run_full_chain_check.py` 时，会同时检查独立包和验证镜像是否一致。
5. 如果要输出可直接交付的压缩包，执行 `python tools/package_unity_integration_package.py`，会生成版本化目录包和 zip，并自动把 canonical 文档副本与验证报告装入包内。
6. 如果要做一轮完整的 Unity 包交付签收，执行 `python tools/run_unity_package_release.py --skip-pytest`，会依次完成同步、全链路检查、打包，并输出签收报告。

## SDK 对接包内容

执行 `python tools/package_unity_integration_package.py` 后，生成的包根目录会包含：

- `package.json`：UPM 包清单，包名固定为 `com.audioforge.runtime`。
- `Runtime/`：从 `unity_package/Assets/AudioForgeRuntime/Scripts` 导出的运行时代码与运行时侧资源。
- `Editor/`：从 `unity_package/Assets/AudioForgeRuntime/Editor` 导出的编辑器工具。
- `Documentation~/Docs/`：包内对接入口与 canonical 文档副本。
- `Documentation~/Examples/`：带注释的示范代码文件，不会自动进入 Unity 工程，需要按需手工复制。
- `Documentation~/Verification/`：最近一次机器验证报告与内部签收摘要。
- `README.md`：包根总说明。

## 和第一期相比，这包现在多了什么

- 包内文档新增 `Docs/一期对比变化总览.md`，Unity 同学拿到包后可以先用一页文档看清楚“一期到当前”的真实差异。
- 对接规范已经把 `PlayMode = OneShot`、有效 Clip 集合和 editor-only 边界写清楚，不需要再从编辑器实现里反推 Unity 端应该怎么理解。
- 包内验证材料会随重新打包一起刷新，交接时可以同时给目录包、zip 和签收摘要，而不是只给一份运行时代码目录。
- 当前包内 runtime 已正式进入“Event 动作层 + AudioObject 声音层”契约：Unity runtime 直接消费顶层 `AudioObjects` 与 `Events[AudioId]`，不再依赖事件内嵌 `Audio` 或扁平镜像字段。

## 2026-05-14 版本说明

- 0.09.0 这轮发布的重点是 Schema 3 与 Audio Object 主模型冻结：运行时代码目录仍维持同一套 SDK，但契约已明确要求 `SchemaVersion = 3` 走顶层 `AudioObjects + Events[AudioId]`。
- 当前参考运行时代码仍位于 `unity_package/Assets/AudioForgeRuntime`，并已直接消费 `AudioObjects` 与 `AudioId` 引用，不再依赖嵌套 `Audio` 或扁平字段回退。
- 如果你只看代码目录，容易误以为这次只是数据层重命名；真正需要同步给 Unity 的，是“Event 只负责触发行为，声音层全部归 AudioObject”的运行时语义。

## 打包产物

执行 `python tools/package_unity_integration_package.py` 后，会在 `dist/` 下生成：

- `AudioForgeUnityPackage-0.09.0/`
- `AudioForgeUnityPackage-0.09.0.zip`

执行 `python tools/run_unity_package_release.py --skip-pytest` 后，还会在 `reports/unity_package_release/` 下生成：

- `unity_package_release_signoff.json`
- `unity_package_release_signoff.md`

## 集成方式

1. 将 `dist/AudioForgeUnityPackage-<version>/` 目录整体放到目标 Unity 项目的 `Packages/` 下，或通过本地路径方式引入该包。
2. 将工具导出的 `AudioData.json`、`AudioManifest.json` 和 `Assets/**` 放到 `Assets/StreamingAssets/AudioForge/`。
3. 先阅读包内 `Documentation~/Docs/QuickStart.md`，再按 `Documentation~/Docs/Canonical/UnitySDK对接规范.md` 或 `unity_validation/README.md` 完成初始化和空项目验证。

## Inspector 搜索

当前 `AudioForgeBootstrap` 和 `AudioForgeEventPlayer` 的 Inspector 已内置 `Event Id` 关联搜索区：

1. 保留原始字符串输入，兼容手填。
2. 会优先按 `StreamingAssets/AudioForge/AudioData.json` 中的事件列表做搜索，找不到时再回退到导入后的 `AudioEventID` 枚举项。
3. 可从筛选结果里一键应用到当前组件，也可以双击快捷候选直接选中。
4. 菜单 `AudioForge/Tools/Refresh AudioEventID From StreamingAssets` 可直接从当前导入的 `AudioData.json` 刷新 `AudioEventID.cs`。

如果搜索区没有枚举项，通常说明 Unity 工程里还没有导入最新的 `AudioEventID.cs`。

## Unity AudioMixer 配置

`AudioForgeRuntime` 现在已经支持 Unity AudioMixer 接入：

1. 可在组件 Inspector 中开启 `启用 Unity AudioMixer 集成`。
2. Inspector 顶部会优先显示导出项目、运行时格式、事件数、总线数和运行时状态等常用信息。
3. `常用总线信息与微调` 区会直接列出从 `AudioData.json` 识别出的 AudioForge 总线，显示父总线、导出基线、当前映射状态和附加倍率。
4. Unity 侧的 `主总线附加倍率` 与各总线 `附加倍率` 都表示在 AudioForge 导出结果之上的额外微调；`1` 表示未改动，不会覆盖导出基线。
5. 可为指定总线绑定独立的 `AudioMixerGroup`；未单独绑定时会回退到默认输出组。
6. 进入 Play 模式后，`运行中快速微调` 区会显示实时滑杆，便于联调时快速试听。
7. `跨场景常驻`、预热声源数、最大声源数、主总线名称和保时长变调开关等低频配置，已收纳到折叠区，避免干扰常用操作。

## 事件音量微调

现在 Unity 侧已经补充两层事件音量微调能力：

1. `AudioForgeRuntime` Inspector 中的 `事件微调`：项目级偏移，按 `EventId` 对整个工程生效。
2. `AudioForgeEventPlayer` 和 `AudioForgeBootstrap` Inspector 中的 `当前组件偏移`：只影响当前组件触发的该事件。

这两层都以 dB 表达：

- `0 dB` 表示不改动 AudioForge 导出事件基线。
- 负值表示压低当前事件。
- 正值表示单独抬高当前事件。

推荐用法：

1. 项目里全局都要改的事件，放到 `AudioForgeRuntime` 的项目级偏移里。
2. 只在某个场景物体上想单独修一下的事件，放到 `AudioForgeEventPlayer` 或 `AudioForgeBootstrap` 的组件级偏移里。
