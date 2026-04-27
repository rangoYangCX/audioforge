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
    shutil.make_archive(str(release_root), "zip", root_dir=dist_root, base_dir=release_root.name)

    print(f"Packaged Unity integration directory created at: {release_root}")
    print(f"Packaged Unity integration zip created at: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
