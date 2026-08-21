from __future__ import annotations

import logging
from typing import Callable, Iterable

from ehrm.core.settings import AppSettings
from ehrm.modules.erp.client import ErpTaskClient
from ehrm.modules.erp.credentials import resolve_erp_credentials
from ehrm.modules.erp.models import (
    ErpCredentials,
    ErpTaskQueryResult,
    ErpTaskStatus,
)
from ehrm.modules.erp.session import ErpSession


class ErpTaskQueryService:
    """Application service for querying ERP tasks outside the desktop UI."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check

    def query_by_transaction_type(
        self,
        transaction_type: str,
        *,
        page_size: int = 50,
        credentials: ErpCredentials | None = None,
    ) -> ErpTaskQueryResult:
        resolved_credentials = credentials or resolve_erp_credentials(self._settings)
        with ErpSession(
            self._settings,
            self._logger,
            self._progress,
        ) as session:
            session.ensure_authenticated(resolved_credentials)
            self._progress(f"ERP：正在查询事务类型“{transaction_type.strip()}”")
            result = ErpTaskClient(
                self._settings.erp,
                session.page,
                session.request,
                self._logger,
            ).query_by_transaction_type(
                transaction_type,
                page_size=page_size,
            )
            self._progress(
                f"ERP：查询完成，共获取 {len(result.records)} 条任务，"
                f"{result.pages_fetched} 页"
            )
        return result

    def query_tasks(
        self,
        transaction_type: str,
        *,
        status: int | ErpTaskStatus | None = None,
        statuses: Iterable[int | ErpTaskStatus] | None = None,
        application_code: str = "",
        start_date: str = "",
        end_date: str = "",
        page_size: int = 50,
        credentials: ErpCredentials | None = None,
    ) -> ErpTaskQueryResult:
        resolved_credentials = credentials or resolve_erp_credentials(self._settings)
        with ErpSession(
            self._settings,
            self._logger,
            self._progress,
            self._cancel_check,
        ) as session:
            session.ensure_authenticated(resolved_credentials)
            self._progress("ERP：正在按组合条件查询任务")
            result = ErpTaskClient(
                self._settings.erp,
                session.page,
                session.request,
                self._logger,
                self._cancel_check,
            ).query_tasks(
                transaction_type,
                status=status,
                statuses=statuses,
                application_code=application_code,
                start_date=start_date,
                end_date=end_date,
                page_size=page_size,
            )
            self._progress(
                f"ERP：查询完成，共获取 {len(result.records)} 条任务，"
                f"{result.pages_fetched} 页"
            )
            return result

    def _progress(self, text: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(text)
