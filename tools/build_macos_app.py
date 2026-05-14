from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


def build_pyinstaller_command(workspace: Path, dist_root: Path, pyinstaller_root: Path) -> list[str]:
    icon_source = workspace / "audioforge" / "app" / "assets" / "icons" / "app.icns"
    add_data = f"{workspace / 'audioforge' / 'app' / 'assets'}:audioforge/app/assets"
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
        str(pyinstaller_root),
        "--specpath",
        str(pyinstaller_root),
        "--osx-bundle-identifier",
        "com.audioforge.app",
        "--add-data",
        add_data,
        "--collect-all",
        "pygame",
        "--collect-all",
        "numpy",
        "--collect-all",
        "scipy",
        "--collect-all",
        "soundfile",
        str(workspace / "audioforge" / "main.py"),
    ]

    if icon_source.exists():
        command[10:10] = ["--icon", str(icon_source)]
    return command


def main() -> int:
    if sys.platform != "darwin":
        print("macOS package build must be run on a macOS host.", file=sys.stderr)
        return 1

    workspace = Path(__file__).resolve().parents[1]
    dist_root = workspace / "dist"
    build_root = workspace / "build"
    release_root = dist_root / f"AudioForge-{APP_VERSION}-macos"
    pyinstaller_root = build_root / "pyinstaller-macos"

    for path in (release_root, pyinstaller_root, dist_root / "AudioForge.app"):
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    command = build_pyinstaller_command(workspace, dist_root, pyinstaller_root)

    completed = subprocess.run(command, cwd=workspace)
    if completed.returncode != 0:
        return completed.returncode

    built_app = dist_root / "AudioForge.app"
    if not built_app.exists():
        print(f"Expected app bundle was not produced: {built_app}", file=sys.stderr)
        return 1

    release_root.mkdir(parents=True, exist_ok=True)
    built_app.rename(release_root / "AudioForge.app")

    archive_path = dist_root / f"AudioForge-{APP_VERSION}-macos.zip"
    if archive_path.exists():
        archive_path.unlink()
    shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=dist_root, base_dir=release_root.name)

    print(f"Packaged macOS build created at: {release_root}")
    print(f"Packaged macOS zip created at: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())