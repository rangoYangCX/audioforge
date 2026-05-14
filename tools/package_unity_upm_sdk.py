from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


PACKAGE_NAME = "com.audioforge.runtime"
PACKAGE_DISPLAY_NAME = "AudioForge Runtime"
PACKAGE_DESCRIPTION = "AudioForge Unity runtime integration - event-driven audio playback, AudioMixer support, and editor tooling."
UNITY_VERSION = "2022.3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the AudioForge Unity SDK in Unity Package Manager format.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--archive-path", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace.resolve()
    output_dir = (args.output_dir or (workspace / "dist" / f"AudioForgeUnityPackage-{APP_VERSION}")).resolve()
    archive_path = (args.archive_path or (workspace / "dist" / f"AudioForgeUnityPackage-{APP_VERSION}.zip")).resolve()
    build_upm_runtime_sdk(workspace, output_dir, archive_path)
    print(f"Packaged Unity UPM directory created at: {output_dir}")
    print(f"Packaged Unity UPM zip created at: {archive_path}")
    return 0


def build_upm_runtime_sdk(workspace: Path, release_root: Path, archive_path: Path | None = None) -> None:
    runtime_source_root = workspace / "unity_package" / "Assets" / "AudioForgeRuntime"
    docs_source_root = workspace / "unity_package" / "Docs"
    examples_source_root = workspace / "unity_package" / "Examples"

    if not runtime_source_root.exists():
        raise FileNotFoundError(f"Unity runtime source not found: {runtime_source_root}")
    if not docs_source_root.exists():
        raise FileNotFoundError(f"Unity docs source not found: {docs_source_root}")

    if release_root.exists():
        shutil.rmtree(release_root)
    release_root.mkdir(parents=True, exist_ok=True)

    runtime_root = release_root / "Runtime"
    editor_root = release_root / "Editor"
    docs_root = release_root / "Documentation~" / "Docs"
    examples_root = release_root / "Documentation~" / "Examples"
    verification_root = release_root / "Documentation~" / "Verification"

    copy_tree_contents(runtime_source_root / "Scripts", runtime_root)
    copy_tree_contents(runtime_source_root / "Editor", editor_root)
    shutil.copytree(docs_source_root, docs_root)
    if examples_source_root.exists():
        shutil.copytree(examples_source_root, examples_root)
    else:
        examples_root.mkdir(parents=True, exist_ok=True)
    verification_root.mkdir(parents=True, exist_ok=True)

    write_package_manifest(release_root / "package.json")
    write_package_readme(release_root / "README.md")
    write_asmdefs(runtime_root, editor_root)
    add_release_docs(workspace, docs_root)
    add_release_reports(workspace, verification_root)
    ensure_runtime_and_editor_meta(release_root)

    if archive_path is not None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            archive_path.unlink()
        shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=release_root.parent, base_dir=release_root.name)


def copy_tree_contents(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.exists():
        raise FileNotFoundError(f"Required source directory not found: {source_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    for child in source_dir.iterdir():
        destination = target_dir / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def write_package_manifest(target_path: Path) -> None:
    payload = {
        "name": PACKAGE_NAME,
        "version": to_upm_version(APP_VERSION),
        "displayName": PACKAGE_DISPLAY_NAME,
        "description": PACKAGE_DESCRIPTION,
        "unity": UNITY_VERSION,
    }
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_package_readme(target_path: Path) -> None:
    content = f"""# AudioForge Runtime UPM Package

这个目录按 Unity Package Manager 的本地包规范生成，可直接作为 `{PACKAGE_NAME}` 交给 Unity 项目接入。

当前文档同步日期：{datetime.now().strftime('%Y-%m-%d')}
当前桌面工具版本：AudioForge {APP_VERSION}
当前 UPM 包版本：{to_upm_version(APP_VERSION)}

## 目录定位

- `Runtime/`：运行时脚本与运行时侧资源。
- `Editor/`：Inspector、自检和编辑器辅助工具。
- `Documentation~/Docs/`：包内对接文档入口与 canonical 文档副本。
- `Documentation~/Examples/`：示例代码与参考实现片段。
- `Documentation~/Verification/`：最近一次验证报告与签收摘要。

## 接入方式

1. 将整个包目录放到 Unity 项目的 `Packages/` 下，或通过 `Packages/manifest.json` 的本地路径方式引用。
2. 将工具导出的 `AudioData.json`、`AudioManifest.json` 和导出音频资源放到 `Assets/StreamingAssets/AudioForge/`。
3. 先阅读 `Documentation~/Docs/QuickStart.md`，再按 `Documentation~/Docs/Canonical/UnitySDK输出规范.md` 和 `Documentation~/Docs/Canonical/UnitySDK对接规范.md` 接入业务事件与总线。

## 一期到当前的差异入口

- 先看 `Documentation~/Docs/一期对比变化总览.md`，快速确认相对一期真正需要 Unity 侧关注的变化。
- 当前最重要的运行时语义新增点是 `PlayMode = OneShot`；对象浏览器三分页、bindings 弹窗、`Enabled / Active` 编辑态与智能总线分配设置仍是 editor-only。
"""
    target_path.write_text(content, encoding="utf-8")


def write_asmdefs(runtime_root: Path, editor_root: Path) -> None:
    runtime_payload = {
        "name": PACKAGE_NAME,
        "rootNamespace": "",
        "references": [],
        "includePlatforms": [],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": False,
        "precompiledReferences": [],
        "autoReferenced": True,
        "defineConstraints": [],
        "versionDefines": [],
        "noEngineReferences": False,
    }
    editor_payload = {
        "name": f"{PACKAGE_NAME}.editor",
        "rootNamespace": "",
        "references": [PACKAGE_NAME],
        "includePlatforms": ["Editor"],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": False,
        "precompiledReferences": [],
        "autoReferenced": True,
        "defineConstraints": [],
        "versionDefines": [],
        "noEngineReferences": False,
    }
    (runtime_root / f"{PACKAGE_NAME}.asmdef").write_text(json.dumps(runtime_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (editor_root / f"{PACKAGE_NAME}.editor.asmdef").write_text(json.dumps(editor_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_release_docs(workspace: Path, docs_root: Path) -> None:
    canonical_root = docs_root / "Canonical"
    docs_targets = {
        workspace / "CHANGELOG.md": canonical_root / "CHANGELOG.md",
        workspace / "docs" / "UnitySDK对接规范.md": canonical_root / "UnitySDK对接规范.md",
        workspace / "docs" / "UnitySDK输出规范.md": canonical_root / "UnitySDK输出规范.md",
        workspace / "docs" / "UnitySDK一期到当前变化总览.md": canonical_root / "UnitySDK一期到当前变化总览.md",
        workspace / "docs" / "Unity场景联调清单.md": canonical_root / "Unity场景联调清单.md",
        workspace / "docs" / "releases" / f"v{APP_VERSION}-github-release.md": canonical_root / "GitHubRelease.md",
        workspace / "unity_validation" / "README.md": canonical_root / "UnityValidationREADME.md",
    }
    for source_path, target_path in docs_targets.items():
        copy_release_file(source_path, target_path)


def add_release_reports(workspace: Path, verification_root: Path) -> None:
    report_targets = {
        workspace / "reports" / "internal_release_smoke" / "release_signoff.md": verification_root / "release_signoff.md",
        workspace / "reports" / "internal_release_smoke" / "release_signoff.json": verification_root / "release_signoff.json",
        workspace / "reports" / "internal_release_smoke" / "checks" / "full_chain_report.md": verification_root / "full_chain_report.md",
        workspace / "reports" / "internal_release_smoke" / "checks" / "full_chain_report.json": verification_root / "full_chain_report.json",
        workspace / "reports" / "unity_package_release" / "unity_package_release_signoff.md": verification_root / "unity_package_release_signoff.md",
        workspace / "reports" / "unity_package_release" / "unity_package_release_signoff.json": verification_root / "unity_package_release_signoff.json",
    }
    for source_path, target_path in report_targets.items():
        if source_path.exists():
            copy_release_file(source_path, target_path)


def copy_release_file(source_path: Path, target_path: Path) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Required release file not found: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def ensure_runtime_and_editor_meta(release_root: Path) -> None:
    ensure_folder_meta(release_root / "Runtime")
    ensure_folder_meta(release_root / "Editor")
    ensure_file_meta(release_root / "package.json", importer="package")
    ensure_file_meta(release_root / "README.md", importer="text")
    ensure_file_meta(release_root / "Runtime" / f"{PACKAGE_NAME}.asmdef", importer="asmdef")
    ensure_file_meta(release_root / "Editor" / f"{PACKAGE_NAME}.editor.asmdef", importer="asmdef")

    for folder in sorted((release_root / "Runtime").rglob("*")):
        if folder.is_dir():
            ensure_folder_meta(folder)
    for folder in sorted((release_root / "Editor").rglob("*")):
        if folder.is_dir():
            ensure_folder_meta(folder)

    for source_file in sorted((release_root / "Runtime").rglob("*.cs")):
        ensure_file_meta(source_file, importer="mono")
    for source_file in sorted((release_root / "Editor").rglob("*.cs")):
        ensure_file_meta(source_file, importer="mono")


def ensure_folder_meta(folder_path: Path) -> None:
    meta_path = folder_path.parent / f"{folder_path.name}.meta"
    if meta_path.exists():
        return
    guid = deterministic_guid(f"folder:{normalize_path(folder_path)}")
    meta_path.write_text(
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "folderAsset: yes\n"
        "DefaultImporter:\n"
        "  externalObjects: {}\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n",
        encoding="utf-8",
    )


def ensure_file_meta(file_path: Path, importer: str) -> None:
    meta_path = file_path.parent / f"{file_path.name}.meta"
    if meta_path.exists():
        return
    guid = deterministic_guid(f"file:{normalize_path(file_path)}")
    if importer == "package":
        content = (
            "fileFormatVersion: 2\n"
            f"guid: {guid}\n"
            "PackageManifestImporter:\n"
            "  externalObjects: {}\n"
            "  userData: \n"
            "  assetBundleName: \n"
            "  assetBundleVariant: \n"
        )
    elif importer == "asmdef":
        content = (
            "fileFormatVersion: 2\n"
            f"guid: {guid}\n"
            "AssemblyDefinitionImporter:\n"
            "  externalObjects: {}\n"
            "  userData: \n"
            "  assetBundleName: \n"
            "  assetBundleVariant: \n"
        )
    elif importer == "mono":
        content = (
            "fileFormatVersion: 2\n"
            f"guid: {guid}\n"
            "MonoImporter:\n"
            "  externalObjects: {}\n"
            "  serializedVersion: 2\n"
            "  defaultReferences: []\n"
            "  executionOrder: 0\n"
            "  icon: {instanceID: 0}\n"
            "  userData: \n"
            "  assetBundleName: \n"
            "  assetBundleVariant: \n"
        )
    else:
        content = (
            "fileFormatVersion: 2\n"
            f"guid: {guid}\n"
            "TextScriptImporter:\n"
            "  externalObjects: {}\n"
            "  userData: \n"
            "  assetBundleName: \n"
            "  assetBundleVariant: \n"
        )
    meta_path.write_text(content, encoding="utf-8")


def deterministic_guid(key: str) -> str:
    return hashlib.md5(f"audioforge-upm::{key}".encode("utf-8")).hexdigest()


def normalize_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def to_upm_version(version: str) -> str:
    parts: list[str] = []
    for raw_part in version.split("."):
        part = raw_part.strip()
        parts.append(str(int(part)) if part.isdigit() else (part or "0"))
    return ".".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())