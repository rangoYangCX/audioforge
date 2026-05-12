from __future__ import annotations

from pathlib import Path

from audioforge.app.utils.constants import APP_VERSION
from tools.package_unity_upm_sdk import build_upm_runtime_sdk


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    dist_root = workspace / "dist"
    release_root = dist_root / f"AudioForgeUnityPackage-{APP_VERSION}"
    archive_path = dist_root / f"AudioForgeUnityPackage-{APP_VERSION}.zip"
    build_upm_runtime_sdk(workspace, release_root, archive_path)

    print(f"Packaged Unity integration directory created at: {release_root}")
    print(f"Packaged Unity integration zip created at: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
