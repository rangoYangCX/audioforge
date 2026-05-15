from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION
from tools.package_unity_upm_sdk import build_upm_runtime_sdk


def _promote_built_directory(built_dir: Path, release_root: Path) -> None:
    if not built_dir.exists():
        raise FileNotFoundError(f"Built directory does not exist: {built_dir}")

    for attempt in range(3):
        try:
            built_dir.replace(release_root)
            return
        except PermissionError:
            if attempt == 2:
                break
            time.sleep(0.5 * (attempt + 1))

    shutil.copytree(built_dir, release_root)
    shutil.rmtree(built_dir, ignore_errors=True)


def _embed_unity_sdk(workspace: Path, release_root: Path) -> None:
    sdk_root = release_root / "SDK" / "com.audioforge.runtime"
    build_upm_runtime_sdk(workspace, sdk_root)


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    dist_root = workspace / "dist"
    build_root = workspace / "build"
    release_root = dist_root / f"AudioForge-{APP_VERSION}-windows"

    for path in (release_root, build_root / "pyinstaller"):
        if path.exists():
            shutil.rmtree(path)

    icon_source = workspace / "audioforge" / "app" / "assets" / "icons" / "app.ico"
    add_data = f"{workspace / 'audioforge' / 'app' / 'assets'};audioforge/app/assets"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "AudioForge",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(build_root / "pyinstaller"),
        "--specpath",
        str(build_root / "pyinstaller"),
        "--add-data",
        add_data,
        str(workspace / "audioforge" / "main.py"),
    ]

    if icon_source.exists():
        command[10:10] = ["--icon", str(icon_source)]

    completed = subprocess.run(command, cwd=workspace)
    if completed.returncode != 0:
        return completed.returncode

    built_dir = dist_root / "AudioForge"
    if release_root.exists():
        shutil.rmtree(release_root)
    _promote_built_directory(built_dir, release_root)
    _embed_unity_sdk(workspace, release_root)
    archive_path = dist_root / f"AudioForge-{APP_VERSION}-windows.zip"
    if archive_path.exists():
        archive_path.unlink()
    shutil.make_archive(str(release_root), "zip", root_dir=dist_root, base_dir=release_root.name)
    print(f"Packaged build created at: {release_root}")
    print(f"Packaged zip created at: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())