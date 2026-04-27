# AudioForge Unity Integration Package

这个目录是 Unity 侧运行时资源的独立维护包，也是仓库内的唯一源码真源。

## 目录定位

- `unity_package/Assets/AudioForgeRuntime`：Unity 运行时脚本、Editor 工具和稳定 `.meta` 文件。
- `unity_validation/Assets/AudioForgeRuntime`：用于空项目验证的镜像副本，不再作为手工维护入口。

## 维护规则

1. 所有 Unity 侧运行时代码只在 `unity_package/Assets/AudioForgeRuntime` 修改。
2. 修改后执行 `python tools/sync_unity_integration_package.py`，把包内容同步到 `unity_validation` 验证工程。
3. 交付给 Unity 程序时，优先直接交这个包目录，而不是从验证工程里手动挑文件。
4. 执行 `python tools/run_full_chain_check.py` 时，会同时检查独立包和验证镜像是否一致。
5. 如果要输出可直接交付的压缩包，执行 `python tools/package_unity_integration_package.py`，会生成版本化目录包和 zip。
6. 如果要做一轮完整的 Unity 包交付签收，执行 `python tools/run_unity_package_release.py --skip-pytest`，会依次完成同步、全链路检查、打包，并输出签收报告。

## 打包产物

执行 `python tools/package_unity_integration_package.py` 后，会在 `dist/` 下生成：

- `AudioForgeUnityPackage-0.02/`
- `AudioForgeUnityPackage-0.02.zip`

执行 `python tools/run_unity_package_release.py --skip-pytest` 后，还会在 `reports/unity_package_release/` 下生成：

- `unity_package_release_signoff.json`
- `unity_package_release_signoff.md`

## 集成方式

1. 将 `unity_package/Assets/AudioForgeRuntime` 整体复制到目标 Unity 项目的 `Assets` 目录。
2. 将工具导出的 `AudioData.json`、`AudioManifest.json` 和 `Assets/**` 放到 `Assets/StreamingAssets/AudioForge/`。
3. 按 `docs/UnitySDK对接规范.md` 或 `unity_validation/README.md` 完成初始化和空项目验证。

## Inspector 搜索

当前 `AudioForgeBootstrap` 和 `AudioForgeEventPlayer` 的 Inspector 已内置 `Event Id` 关联搜索区：

1. 保留原始字符串输入，兼容手填。
2. 会优先按 `StreamingAssets/AudioForge/AudioData.json` 中的事件列表做搜索，找不到时再回退到导入后的 `AudioEventID` 枚举项。
3. 可从筛选结果里一键应用到当前组件，也可以双击快捷候选直接选中。
4. 菜单 `AudioForge/Tools/Refresh AudioEventID From StreamingAssets` 可直接从当前导入的 `AudioData.json` 刷新 `AudioEventID.cs`。

如果搜索区没有枚举项，通常说明 Unity 工程里还没有导入最新的 `AudioEventID.cs`。

## Unity AudioMixer 配置

`AudioForgeRuntime` 现在已经支持 Unity AudioMixer 接入：

1. 可在组件 Inspector 中开启 `Integrate With Unity Audio Mixer`。
2. 可配置默认输出 `AudioMixerGroup`。
3. 可配置 `Unity Master Volume` 和每个总线的附加音量倍率。
4. 可为指定总线绑定独立的 `AudioMixerGroup`。
5. 进入 Play 模式后，`AudioForgeRuntime` 的 Inspector 配置栏会出现实时音量滑杆，可直接调主音量和各总线音量。
