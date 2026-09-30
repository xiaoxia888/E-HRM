from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QThread, Signal

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.nocobase.application_query_service import NocoBaseApplicationQueryService


class NocoBaseConnectionWorker(QThread):
    """Verify API-key read access off the UI thread, without saving credentials."""

    status_changed = Signal(str)
    succeeded = Signal()
    failed = Signal(str, str)

    def __init__(self, settings: AppSettings, logger: logging.Logger, api_key: str = "") -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._api_key = api_key
        self._cancel_requested = Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    def run(self) -> None:
        try:
            if self._cancel_requested.is_set():
                return
            self.status_changed.emit("正在使用 API 密钥测试 NocoBase 查询权限…")
            NocoBaseApplicationQueryService(self._settings, self._logger).test_connection(api_key=self._api_key)
            if not self._cancel_requested.is_set():
                self.succeeded.emit()
        except EhrmError as exc:
            summary = display_message(exc.code, exc.message)
            self.failed.emit(summary, exc.details or "")
        except Exception as exc:
            # 不记录未知异常的请求栈，以免第三方请求信息包含密钥。
            self._logger.error("NocoBase 连接测试发生错误：%s", type(exc).__name__)
            self.failed.emit("NocoBase 连接测试失败", str(exc).replace(self._api_key, "[已隐藏]") if self._api_key else str(exc))
        finally:
            self._api_key = ""
