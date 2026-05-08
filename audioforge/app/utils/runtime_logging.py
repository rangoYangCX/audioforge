from __future__ import annotations

import faulthandler
import logging
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO

try:
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler
except Exception:  # pragma: no cover - optional during non-Qt execution
    QtMsgType = None
    qInstallMessageHandler = None


@dataclass(frozen=True, slots=True)
class RuntimeLogConfig:
    log_dir: Path
    session_log: Path
    latest_log: Path
    fault_log: Path


_LOG_CONFIG: RuntimeLogConfig | None = None
_FAULT_STREAM: TextIO | None = None
_LOCK = threading.Lock()
_PREVIOUS_QT_HANDLER = None
_QT_HANDLER = None
_PREVIOUS_SYS_EXCEPTHOOK = sys.excepthook
_PREVIOUS_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)
_PREVIOUS_UNRAISABLEHOOK = getattr(sys, "unraisablehook", None)


def configure_runtime_logging() -> RuntimeLogConfig:
    global _FAULT_STREAM, _LOG_CONFIG
    with _LOCK:
        if _LOG_CONFIG is not None:
            return _LOG_CONFIG

        log_dir = _resolve_log_dir()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_log = log_dir / f"audioforge-{timestamp}.log"
        latest_log = log_dir / "latest.log"
        fault_log = log_dir / "latest.fault.log"

        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        app_logger = logging.getLogger("audioforge")
        app_logger.setLevel(logging.INFO)
        app_logger.handlers.clear()
        app_logger.propagate = False

        for log_path, mode in ((session_log, "a"), (latest_log, "w")):
            handler = logging.FileHandler(log_path, mode=mode, encoding="utf-8")
            handler.setFormatter(formatter)
            app_logger.addHandler(handler)

        _FAULT_STREAM = fault_log.open("w", encoding="utf-8")
        faulthandler.enable(_FAULT_STREAM, all_threads=True)
        _install_exception_hooks()
        _install_qt_message_handler()

        _LOG_CONFIG = RuntimeLogConfig(
            log_dir=log_dir,
            session_log=session_log,
            latest_log=latest_log,
            fault_log=fault_log,
        )
        logging.getLogger(__name__).info(
            "Runtime logging initialized pid=%s session_log=%s latest_log=%s fault_log=%s",
            os.getpid(),
            session_log,
            latest_log,
            fault_log,
        )
        return _LOG_CONFIG


def get_runtime_log_config() -> RuntimeLogConfig | None:
    return _LOG_CONFIG


def _resolve_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates = [
        Path(local_app_data) / "AudioForge" / "logs" if local_app_data else None,
        Path.cwd() / ".audioforge" / "logs",
        Path(tempfile.gettempdir()) / "AudioForge" / "logs",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise OSError("Unable to create a writable AudioForge log directory.")


def _install_exception_hooks() -> None:
    def _log_unhandled_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            if _PREVIOUS_SYS_EXCEPTHOOK is not None:
                _PREVIOUS_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("audioforge.crash").critical(
            "Unhandled exception reached sys.excepthook",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        if _PREVIOUS_SYS_EXCEPTHOOK is not None:
            _PREVIOUS_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    sys.excepthook = _log_unhandled_exception

    if _PREVIOUS_THREADING_EXCEPTHOOK is not None:

        def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
            if issubclass(args.exc_type, KeyboardInterrupt):
                _PREVIOUS_THREADING_EXCEPTHOOK(args)
                return
            thread_name = args.thread.name if args.thread is not None else "<unknown>"
            logging.getLogger("audioforge.crash").critical(
                "Unhandled exception reached threading.excepthook thread=%s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            _PREVIOUS_THREADING_EXCEPTHOOK(args)

        threading.excepthook = _log_thread_exception

    if _PREVIOUS_UNRAISABLEHOOK is not None:

        def _log_unraisable(unraisable: object) -> None:
            exc_type = getattr(unraisable, "exc_type", None)
            exc_value = getattr(unraisable, "exc_value", None)
            exc_traceback = getattr(unraisable, "exc_traceback", None)
            target = getattr(unraisable, "object", None)
            logging.getLogger("audioforge.crash").error(
                "Unraisable exception target=%r",
                target,
                exc_info=(exc_type, exc_value, exc_traceback),
            )
            _PREVIOUS_UNRAISABLEHOOK(unraisable)

        sys.unraisablehook = _log_unraisable


def _install_qt_message_handler() -> None:
    global _PREVIOUS_QT_HANDLER, _QT_HANDLER
    if qInstallMessageHandler is None:
        return
    if _QT_HANDLER is not None:
        return

    def _handle_qt_message(mode, context, message) -> None:
        logger = logging.getLogger("audioforge.qt")
        level = _map_qt_message_level(mode)
        location = ""
        if context is not None and getattr(context, "file", None):
            location = f" file={context.file}:{getattr(context, 'line', 0)}"
        category = getattr(context, "category", "") if context is not None else ""
        category_text = f" category={category}" if category else ""
        logger.log(level, "Qt message:%s%s %s", location, category_text, message)
        if _PREVIOUS_QT_HANDLER is not None:
            _PREVIOUS_QT_HANDLER(mode, context, message)

    _QT_HANDLER = _handle_qt_message
    _PREVIOUS_QT_HANDLER = qInstallMessageHandler(_QT_HANDLER)


def _map_qt_message_level(mode) -> int:
    if QtMsgType is None:
        return logging.INFO
    if mode == QtMsgType.QtDebugMsg:
        return logging.DEBUG
    if mode == QtMsgType.QtInfoMsg:
        return logging.INFO
    if mode == QtMsgType.QtWarningMsg:
        return logging.WARNING
    if mode == QtMsgType.QtCriticalMsg:
        return logging.ERROR
    if mode == QtMsgType.QtFatalMsg:
        return logging.CRITICAL
    return logging.INFO