import os
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.utils.runtime_logging import configure_runtime_logging


logger = logging.getLogger(__name__)


def configure_platform_runtime() -> None:
    if sys.platform != "darwin":
        return
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)


def main() -> int:
    configure_platform_runtime()
    log_config = configure_runtime_logging()
    logger.info(
        "Application startup session_log=%s latest_log=%s fault_log=%s",
        log_config.session_log,
        log_config.latest_log,
        log_config.fault_log,
    )
    controller = MainController()
    controller.show()
    return controller.run()


if __name__ == "__main__":
    raise SystemExit(main())