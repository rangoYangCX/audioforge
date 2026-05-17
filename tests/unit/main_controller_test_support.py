from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication

from audioforge.app.controllers.main_controller import MainController


def wait_for_build_completion(controller: MainController, timeout_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        thread = getattr(controller, "_build_thread", None)
        if thread is None or not thread.isRunning():
            QApplication.processEvents()
            return
    raise AssertionError("Timed out waiting for background build to finish.")