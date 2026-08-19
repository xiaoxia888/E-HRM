from __future__ import annotations

import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.models import ErpUploadResult
from ehrm.modules.erp.service import ErpUploadService


class ManualErpUploadWorker(QThread):
    """Runs one manually selected ERP attachment upload off the GUI thread."""

    status_changed = Signal(str)
    completed = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        task_number: str,
        file_path: Path,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._task_number = task_number
        self._file_path = file_path
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            result = ErpUploadService(
                self._settings,
                self._logger,
                self.status_changed.emit,
                self._cancel_requested.is_set,
            ).execute(self._task_number, self._file_path)
            if not isinstance(result, ErpUploadResult):
                raise RuntimeError("ERP 上传返回了错误的结果类型")
            self.completed.emit(result)
        except EhrmError as exc:
            self._logger.exception(
                "手工 ERP 上传失败 task_number=%s file=%s code=%s",
                self._task_number,
                self._file_path,
                exc.code,
            )
            summary = display_message(exc.code, exc.message)
            details = exc.message if exc.message != summary else (exc.details or "")
            self.failed.emit(summary, details)
        except Exception as exc:
            self._logger.exception(
                "手工 ERP 上传发生未知错误 task_number=%s file=%s",
                self._task_number,
                self._file_path,
            )
            self.failed.emit("ERP 上传失败", str(exc))
