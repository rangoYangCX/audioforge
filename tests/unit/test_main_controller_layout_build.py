from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.services.recovery_service import RecoveryService
from tests.unit.main_controller_test_support import wait_for_build_completion


def test_build_project_handles_export_failure(monkeypatch) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    criticals: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda parent, title, message: criticals.append((title, message)),
    )

    controller = MainController()

    class BoomExporter:
        def plan_export(self, project, export_root, request=None):
            return controller.exporter.plan_export(project, export_root, request)

        def export(self, *args, **kwargs):
            raise RuntimeError("export boom")

    class PassingValidator:
        def validate(self, project):
            return []

    monkeypatch.setattr(controller, "_create_build_validator", lambda: PassingValidator())
    monkeypatch.setattr(controller, "_create_build_exporter", lambda: BoomExporter())

    controller.build_project()
    wait_for_build_completion(controller)

    assert criticals
    assert criticals[0][0] == "构建失败"
    assert "export boom" in criticals[0][1]
    assert controller.window._report_tab_index == 2
    assert "构建失败" in controller.window.build_report_output.toPlainText()
    assert "export boom" in controller.window.log_output.toPlainText()

    controller.is_dirty = False
    controller.window.close()


def test_build_project_resolves_relative_export_root_from_project_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RecoveryService, "has_snapshot", lambda self: False)

    controller = MainController()
    controller.project.file_path = str(tmp_path / "portable.afproj")
    controller.project.settings.export_root = "./Export"
    captured: dict[str, Path] = {}

    def capture_start(project, export_root, build_request) -> None:
        captured["export_root"] = export_root

    monkeypatch.setattr(controller, "_start_build_worker", capture_start)

    controller.build_project()

    assert captured["export_root"] == (tmp_path / "Export").resolve(strict=False)

    controller.is_dirty = False
    controller.window.close()