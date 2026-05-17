from __future__ import annotations

import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_GUI_FILE_PREFIXES = ("test_main_controller",)
_GUI_FILES = {"test_experiment_gui_behavior.py"}
_INTEGRATION_FILES = {
    "test_experiment_e2e.py",
    "test_experiment_full_flow.py",
    "test_main_controller_full_flow.py",
}
_RELEASE_FILES = {
    "test_documentation_baseline.py",
    "test_full_chain_check.py",
    "test_harness_environment.py",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        file_name = Path(str(item.fspath)).name
        has_category = False
        if file_name.startswith(_GUI_FILE_PREFIXES) or file_name in _GUI_FILES:
            item.add_marker(pytest.mark.gui)
            item.add_marker(pytest.mark.slow)
            has_category = True
        if file_name in _INTEGRATION_FILES:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)
            has_category = True
        if file_name in _RELEASE_FILES:
            item.add_marker(pytest.mark.release)
            item.add_marker(pytest.mark.slow)
            has_category = True
        if not has_category:
            item.add_marker(pytest.mark.fast)