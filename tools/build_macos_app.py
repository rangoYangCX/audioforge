from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION


def build_pyinstaller_spec(workspace: Path, spec_path: Path) -> None:
    icon_source = workspace / "audioforge" / "app" / "assets" / "icons" / "app.icns"

    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_all

datas = [('{workspace / 'audioforge' / 'app' / 'assets'}', 'audioforge/app/assets')]
binaries = []
hiddenimports = ['sitecustomize', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets']
binaries += collect_dynamic_libs('pygame')
binaries += collect_dynamic_libs('numpy')
binaries += collect_dynamic_libs('scipy')
binaries += collect_dynamic_libs('soundfile')
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['{workspace / 'audioforge' / 'main.py'}'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AudioForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AudioForge',
)
"""

    spec_path.write_text(spec_content, encoding="utf-8")


def build_pyinstaller_command(pyinstaller_python: str, dist_root: Path, pyinstaller_root: Path, spec_path: Path) -> list[str]:
    return [
        pyinstaller_python,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(pyinstaller_root),
        str(spec_path),
    ]


def build_app_bundle(workspace: Path, dist_root: Path, release_root: Path) -> Path:
    source_dir = dist_root / "AudioForge"
    app_bundle = release_root / "AudioForge.app"
    contents_dir = app_bundle / "Contents"
    macos_dir = contents_dir / "MacOS"
    frameworks_dir = contents_dir / "Frameworks"
    resources_dir = contents_dir / "Resources"

    if app_bundle.exists():
        shutil.rmtree(app_bundle)

    macos_dir.mkdir(parents=True, exist_ok=True)
    frameworks_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_dir / "AudioForge", macos_dir / "AudioForge")
    shutil.copytree(source_dir / "_internal", frameworks_dir, dirs_exist_ok=True, symlinks=False)

    icon_source = workspace / "audioforge" / "app" / "assets" / "icons" / "app.icns"
    if icon_source.exists():
        shutil.copy2(icon_source, resources_dir / "AudioForge.icns")

    info_plist = {
        "CFBundleName": "AudioForge",
        "CFBundleDisplayName": "AudioForge",
        "CFBundleIdentifier": "com.audioforge.app",
        "CFBundleExecutable": "AudioForge",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "LSMinimumSystemVersion": "11.0",
    }
    if icon_source.exists():
        info_plist["CFBundleIconFile"] = "AudioForge"

    with (contents_dir / "Info.plist").open("wb") as plist_file:
        plistlib.dump(info_plist, plist_file)

    return app_bundle


def main() -> int:
    if sys.platform != "darwin":
        print("macOS package build must be run on a macOS host.", file=sys.stderr)
        return 1

    workspace = Path(__file__).resolve().parents[1]
    dist_root = workspace / "dist"
    build_root = workspace / "build"
    release_root = dist_root / f"AudioForge-{APP_VERSION}-macos"
    pyinstaller_root = build_root / "pyinstaller-macos"
    spec_path = pyinstaller_root / "AudioForge.spec"

    preferred_python = Path.home() / ".pyenv" / "versions" / "3.14.5" / "bin" / "python3.14"
    pyinstaller_python = str(preferred_python if preferred_python.exists() else Path(sys.executable))

    for path in (release_root, pyinstaller_root, dist_root / "AudioForge.app"):
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    pyinstaller_root.mkdir(parents=True, exist_ok=True)
    build_pyinstaller_spec(workspace, spec_path)
    command = build_pyinstaller_command(pyinstaller_python, dist_root, pyinstaller_root, spec_path)

    completed = subprocess.run(command, cwd=workspace)
    if completed.returncode != 0:
        return completed.returncode

    built_app = build_app_bundle(workspace, dist_root, release_root)
    if not built_app.exists():
        print(f"Expected app bundle was not produced: {built_app}", file=sys.stderr)
        return 1

    archive_path = dist_root / f"AudioForge-{APP_VERSION}-macos.zip"
    if archive_path.exists():
        archive_path.unlink()
    shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=dist_root, base_dir=release_root.name)

    print(f"Packaged macOS build created at: {release_root}")
    print(f"Packaged macOS zip created at: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())