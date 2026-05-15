from __future__ import annotations

from pathlib import Path

from tools.build_macos_app import build_pyinstaller_command, build_pyinstaller_spec


def test_build_macos_app_collects_audio_runtime_dependencies(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    dist_root = workspace / "dist"
    pyinstaller_root = workspace / "build" / "pyinstaller-macos"
    pyinstaller_root.mkdir(parents=True, exist_ok=True)
    spec_path = pyinstaller_root / "AudioForge.spec"
    icon_dir = workspace / "audioforge" / "app" / "assets" / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    (icon_dir / "app.icns").write_bytes(b"icns")

    build_pyinstaller_spec(workspace, spec_path)
    command = build_pyinstaller_command("python3.14", dist_root, pyinstaller_root, spec_path)
    spec_text = spec_path.read_text(encoding="utf-8")

    assert "collect_dynamic_libs('pygame')" in spec_text
    assert "collect_dynamic_libs('numpy')" in spec_text
    assert "collect_dynamic_libs('scipy')" in spec_text
    assert "collect_dynamic_libs('soundfile')" in spec_text
    assert str(spec_path) == command[-1]