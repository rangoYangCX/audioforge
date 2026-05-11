from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.services.recovery_service import RecoveryService


def test_save_recovery_snapshot_clears_stale_snapshot_after_failure(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    cleanup_calls: list[str] = []

    def fail_save_snapshot(_project) -> None:
        raise OSError("disk full")

    def record_clear_snapshot() -> None:
        cleanup_calls.append("clear")

    monkeypatch.setattr(controller.recovery_service, "save_snapshot", fail_save_snapshot)
    monkeypatch.setattr(controller.recovery_service, "clear_snapshot", record_clear_snapshot)

    controller._save_recovery_snapshot()

    assert cleanup_calls == ["clear"]
    assert "自动恢复快照保存失败：OSError: disk full" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()