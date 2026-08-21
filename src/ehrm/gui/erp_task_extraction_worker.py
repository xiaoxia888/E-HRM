from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Event

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService


@dataclass(frozen=True, slots=True)
class ErpTaskExtractionRequest:
    transaction_type: str
    statuses: tuple[int, ...] = ()
    application_code: str = ""
    start_date: str = ""
    end_date: str = ""
    page_size: int = 50
    reasoning_mode: str = "medium"


class ErpTaskExtractionWorker(QThread):
    """Queries ERP and calls Ollama without blocking the QML event loop."""

    status_changed = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        request: ErpTaskExtractionRequest,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._request = request
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            result = ErpTaskExtractionService(
                self._settings,
                self._logger,
                progress_callback=self.status_changed.emit,
                item_progress_callback=self.progress_changed.emit,
                cancel_check=self._cancel_requested.is_set,
            ).run(
                self._request.transaction_type,
                statuses=self._request.statuses,
                application_code=self._request.application_code,
                start_date=self._request.start_date,
                end_date=self._request.end_date,
                page_size=self._request.page_size,
                reasoning_mode=self._request.reasoning_mode,
            )
            self.completed.emit(result)
        except TaskCancelledError:
            self.cancelled.emit()
        except EhrmError as exc:
            self._logger.exception("ERP 申请信息获取失败 code=%s", exc.code)
            summary = display_message(exc.code, exc.message)
            details = exc.message if exc.message != summary else (exc.details or "")
            self.failed.emit(summary, details)
        except Exception as exc:
            self._logger.exception("ERP 申请信息获取发生未知错误")
            self.failed.emit("获取申请信息失败", str(exc))
