from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase.application_query_service import NocoBaseApplicationQueryService


class NocoBaseApplicationDetailWorker(QThread):
    """Query NocoBase using the shared API-key service off the QML thread."""

    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        application_id: int,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._application_id = application_id

    def run(self) -> None:
        try:
            result = NocoBaseApplicationQueryService(self._settings, self._logger).get_application(self._application_id)
            self.succeeded.emit(result)
        except EhrmError as exc:
            self.failed.emit(display_message(exc.code, exc.message), exc.details or "")
        except Exception as exc:
            self._logger.error("NocoBase 查询发生错误：%s", type(exc).__name__)
            self.failed.emit("权益申请详情查询失败", str(exc))
