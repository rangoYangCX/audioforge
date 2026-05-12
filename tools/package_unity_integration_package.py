from __future__ import annotations

import shutil
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    dist_root = workspace / "dist"
    package_source_root = workspace / "unity_package"
    release_root = dist_root / f"AudioForgeUnityPackage-{APP_VERSION}"
    archive_path = dist_root / f"AudioForgeUnityPackage-{APP_VERSION}.zip"

    if not package_source_root.exists():
        raise FileNotFoundError(f"Unity package source not found: {package_source_root}")

    if release_root.exists():
        shutil.rmtree(release_root)
    if archive_path.exists():
        archive_path.unlink()

    shutil.copytree(package_source_root, release_root)
    add_release_docs(workspace, release_root)
    add_release_reports(workspace, release_root)
    shutil.make_archive(str(release_root), "zip", root_dir=dist_root, base_dir=release_root.name)

    print(f"Packaged Unity integration directory created at: {release_root}")
    print(f"Packaged Unity integration zip created at: {archive_path}")
    return 0


def add_release_docs(workspace: Path, release_root: Path) -> None:
    docs_targets = {
        workspace / "CHANGELOG.md": release_root / "Docs" / "Canonical" / "CHANGELOG.md",
        workspace / "docs" / "UnitySDK对接规范.md": release_root / "Docs" / "Canonical" / "UnitySDK对接规范.md",
        workspace / "docs" / "UnitySDK一期到当前变化总览.md": release_root / "Docs" / "Canonical" / "UnitySDK一期到当前变化总览.md",
        workspace / "docs" / "Unity场景联调清单.md": release_root / "Docs" / "Canonical" / "Unity场景联调清单.md",
        workspace / "docs" / "releases" / f"v{APP_VERSION}-github-release.md": release_root / "Docs" / "Canonical" / "GitHubRelease.md",
        workspace / "unity_validation" / "README.md": release_root / "Docs" / "Canonical" / "UnityValidationREADME.md",
    }
    for source_path, target_path in docs_targets.items():
        copy_release_file(source_path, target_path)


def add_release_reports(workspace: Path, release_root: Path) -> None:
    report_targets = {
        workspace / "reports" / "internal_release_smoke" / "release_signoff.md": release_root / "Verification" / "release_signoff.md",
        workspace / "reports" / "internal_release_smoke" / "checks" / "full_chain_report.md": release_root / "Verification" / "full_chain_report.md",
        workspace / "reports" / "internal_release_smoke" / "checks" / "full_chain_report.json": release_root / "Verification" / "full_chain_report.json",
    }
    for source_path, target_path in report_targets.items():
        copy_release_file(source_path, target_path)


def copy_release_file(source_path: Path, target_path: Path) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Required release file not found: {source_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


if __name__ == "__main__":
    raise SystemExit(main())
