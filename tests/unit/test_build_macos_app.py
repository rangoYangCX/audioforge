from __future__ import annotations

from pathlib import Path

from tools.build_macos_app import build_pyinstaller_command


def test_build_macos_app_collects_audio_runtime_dependencies(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dist_root = workspace / "dist"
    pyinstaller_root = workspace / "build" / "pyinstaller-macos"
    icon_dir = workspace / "audioforge" / "app" / "assets" / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    (icon_dir / "app.icns").write_bytes(b"icns")

    command = build_pyinstaller_command(workspace, dist_root, pyinstaller_root)

    assert "--collect-all" in command
    assert "pygame" in command
    assert "numpy" in command
    assert "scipy" in command
    assert "soundfile" in command
    assert "--icon" in command