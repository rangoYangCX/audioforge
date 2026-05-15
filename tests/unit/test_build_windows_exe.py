from __future__ import annotations

from pathlib import Path

import tools.build_windows_exe as build_windows_exe


def test_build_windows_exe_embeds_unity_sdk_into_release_directory(monkeypatch) -> None:
    calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(
        build_windows_exe,
        "build_upm_runtime_sdk",
        lambda workspace, release_root, archive_path=None: calls.append((workspace, release_root)),
    )

    workspace = Path("C:/AudioForgeWorkspace")
    release_root = workspace / "dist" / "AudioForge-0.09.2-windows"

    build_windows_exe._embed_unity_sdk(workspace, release_root)

    assert calls == [(workspace, release_root / "SDK" / "com.audioforge.runtime")]