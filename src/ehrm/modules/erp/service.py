from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from ehrm.core.settings import AppSettings
from ehrm.modules.erp.client import ErpApplicationClient, ErpAttachmentClient
from ehrm.modules.erp.credentials import resolve_erp_credentials
from ehrm.modules.erp.models import ErpCredentials, ErpUploadResult
from ehrm.modules.erp.session import ErpSession


class ErpUploadService:
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

    def execute(
        self,
        application_code: str,
        file_path: Path,
        *,
        credentials: ErpCredentials | None = None,
    ) -> ErpUploadResult:
        resolved_credentials = credentials or resolve_erp_credentials(self._settings)
        with ErpSession(
            self._settings,
            self._logger,
            self._progress,
            self._cancel_check,
        ) as session:
            session.ensure_authenticated(resolved_credentials)
            self._progress(f"ERP：正在查询任务编号 {application_code}")
            application = ErpApplicationClient(
                self._settings.erp,
                session.page,
                session.request,
                self._logger,
            ).find_by_code(application_code)
            self._progress(f"ERP：正在上传 {file_path.name}")
            attachment, chunks = ErpAttachmentClient(
                self._settings.erp,
                session.page,
                session.request,
                self._logger,
            ).upload(application, file_path)
            result = ErpUploadResult(
                application=application,
                attachment=attachment,
                source_file=file_path.expanduser().resolve(),
                chunks=chunks,
            )
            self._progress("ERP：附件上传并校验成功")
            return result

    def _progress(self, text: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(text)
