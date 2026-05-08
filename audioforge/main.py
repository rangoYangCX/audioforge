import logging

from audioforge.app.controllers.main_controller import MainController
from audioforge.app.utils.runtime_logging import configure_runtime_logging


logger = logging.getLogger(__name__)


def main() -> int:
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