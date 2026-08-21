from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.models import ErpCredentials
from ehrm.modules.erp.session import ErpSession


class ErpConnectionWorker(QThread):
    status_changed = Signal(str)
    succeeded = Signal()
    failed = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        credentials: ErpCredentials,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._credentials = credentials
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            with ErpSession(
                self._settings,
                self._logger,
                self.status_changed.emit,
                self._cancel_requested.is_set,
            ) as session:
                # Connection tests are credential tests, so they must never
                # succeed solely because a previous browser session is valid.
                session.ensure_authenticated(self._credentials, force_login=True)
            self.succeeded.emit()
        except EhrmError as exc:
            summary = display_message(exc.code, exc.message)
            details = exc.message if exc.message != summary else (exc.details or "")
            self.failed.emit(summary, details)
        except Exception as exc:
            self._logger.exception("ERP 连接测试发生未知错误")
            self.failed.emit("ERP 连接测试失败", str(exc))
