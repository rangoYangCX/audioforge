# AudioForge Unity SDK 输出规范

当前文档同步日期：2026-05-14

本文档定义 AudioForge 后续对 Unity 侧交付的 SDK 输出规范。当前规范以本地 UPM 参考目录 `com.audioforge.runtime` 的骨架为准，目标是让任何一次重新打包都能产出同一套可直接被 Unity Package Manager 接入的目录结构。

## 1. 目标形态

未来所有对 Unity 的 SDK 交付，都必须满足以下 UPM 根目录结构：

```text
com.audioforge.runtime/
	package.json
	README.md
	Runtime/
	Editor/
	Documentation~/
		Docs/
		Examples/
		Verification/
```

说明：

- `package.json`、`README.md`、`Runtime/`、`Editor/` 和 `Documentation~/` 是强制项。
- `Documentation~/Docs/` 承载包内入口文档与 canonical 文档副本。
- `Documentation~/Examples/` 承载示例脚本与参考实现片段。
- `Documentation~/Verification/` 承载最近一次机器验证报告与签收摘要。

## 2. package.json 规范

`package.json` 必须至少包含以下字段：

```json
{
  "name": "com.audioforge.runtime",
  "version": "0.9.1",
  "displayName": "AudioForge Runtime",
  "description": "AudioForge Unity runtime integration - event-driven audio playback, AudioMixer support, and editor tooling.",
  "unity": "2022.3"
}
```

约束如下：

- `name` 固定为 `com.audioforge.runtime`。
- `version` 必须是合法 semver，并由桌面工具版本转换得出。
- 桌面工具版本 `0.09.1` 在 UPM manifest 中写作 `0.9.1`。
- `displayName`、`description`、`unity` 由打包脚本统一生成，不允许手工在发布目录内临时改写。

## 3. README 规范

包根 `README.md` 必须明确以下信息：

- 当前文档同步日期。
- 当前桌面工具版本。
- 当前 UPM 包版本。
- `Runtime/`、`Editor/`、`Documentation~/Docs/`、`Documentation~/Examples/`、`Documentation~/Verification/` 的职责。
- 最短接入路径：把整个包目录放到 Unity 项目的 `Packages/` 下，或通过 `Packages/manifest.json` 以本地路径方式引用。

## 4. Documentation~ 规范

`Documentation~/Docs/` 里至少应包含：

- `README.md`
- `QuickStart.md`
- `一期对比变化总览.md`
- `Canonical/CHANGELOG.md`
- `Canonical/UnitySDK对接规范.md`
- `Canonical/UnitySDK输出规范.md`
- `Canonical/Unity场景联调清单.md`
- `Canonical/GitHubRelease.md`
- `Canonical/UnityValidationREADME.md`

`Documentation~/Examples/` 和 `Documentation~/Verification/` 允许按发布内容增删文件，但目录本身必须存在。

## 5. 代码与元文件规范

- `Runtime/` 从 `unity_package/Assets/AudioForgeRuntime/Scripts` 导出。
- `Editor/` 从 `unity_package/Assets/AudioForgeRuntime/Editor` 导出。
- `Runtime/` 与 `Editor/` 下的 `.cs`、`.asmdef`、文件夹和包根关键文件必须自动补齐 Unity `.meta` 文件。
- `.meta` 文件应使用稳定、可重复生成的 GUID，避免每次打包都产生无意义 diff。

## 6. 版本与命名规范

- 仓库版本锚点统一使用桌面工具版本，如 `0.09.1`。
- UPM 包内部使用 `to_upm_version(APP_VERSION)` 转成 `0.9.1`。
- Unity 独立 SDK 交付目录继续使用 `dist/AudioForgeUnityPackage-<桌面版本>/` 和同名 zip 归档。
- Windows 桌面发布目录必须额外内嵌 `SDK/com.audioforge.runtime/`，用于直接交给 Unity 程序同学做本地包接入。

## 7. 打包入口规范

- `python tools/package_unity_upm_sdk.py`：输出单独的 UPM SDK 根目录。
- `python tools/package_unity_integration_package.py`：输出版本化 Unity SDK 目录包与 zip。
- `python tools/run_unity_package_release.py --skip-pytest`：执行同步、全链路检查、打包和签收摘要输出。
- `python tools/build_windows_exe.py`：输出桌面程序，并把当前版本 SDK 嵌入 `dist/AudioForge-<version>-windows/SDK/com.audioforge.runtime/`。

## 8. 维护要求

- 只要 SDK 输出结构、版本映射、包内文档入口或嵌入式发布目录发生变化，本文档必须同步更新。
- 对 Unity 程序的交付说明、包内说明和 release note 必须与本文档保持一致，不允许出现“仓库文档是 UPM、实际输出还是旧 Assets 根目录”的口径漂移。