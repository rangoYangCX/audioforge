from __future__ import annotations

import shutil
from pathlib import Path


REQUIRED_ROOTS = (
    "Assets/AudioForgeRuntime",
    "Assets/AudioForgeRuntime.meta",
)


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    package_root = workspace / "unity_package"
    validation_root = workspace / "unity_validation"
    validation_assets_root = validation_root / "Assets"

    missing = [relative for relative in REQUIRED_ROOTS if not (package_root / relative).exists()]
    if missing:
        missing_text = ", ".join(missing)
        raise FileNotFoundError(f"Unity package source is incomplete: {missing_text}")

    validation_assets_root.mkdir(parents=True, exist_ok=True)

    target_runtime_dir = validation_assets_root / "AudioForgeRuntime"
    if target_runtime_dir.exists():
        shutil.rmtree(target_runtime_dir)
    target_runtime_meta = validation_assets_root / "AudioForgeRuntime.meta"
    if target_runtime_meta.exists():
        target_runtime_meta.unlink()

    shutil.copytree(package_root / "Assets/AudioForgeRuntime", target_runtime_dir)
    shutil.copy2(package_root / "Assets/AudioForgeRuntime.meta", target_runtime_meta)

    print(f"Synced Unity integration package to validation mirror: {target_runtime_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
