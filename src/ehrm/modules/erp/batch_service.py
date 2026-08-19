from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
from typing import Callable

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.erp.client import ErpApplicationClient, ErpAttachmentClient
from ehrm.modules.erp.credentials import resolve_erp_credentials
from ehrm.modules.erp.session import ErpSession
from ehrm.modules.rights_statement.excel_models import (
    ExcelRunResult,
    ExcelTaskRequest,
    ItemResult,
)


class ErpBatchUploadService:
    """Uploads each generated PDF once and maps the outcome to its Excel rows."""

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
        request: ExcelTaskRequest,
        result: ExcelRunResult,
    ) -> list[ItemResult]:
        records_by_row = {
            record.row_number: record
            for group in request.groups
            for record in group.records
        }
        items_by_row = {item.row_number: item for item in result.items}
        targets: dict[tuple[str, Path], list[int]] = {}
        for item in result.items:
            record = records_by_row.get(item.row_number)
            if not item.success or item.file_path is None or record is None:
                continue
            key = (record.task_number, item.file_path.expanduser().resolve())
            targets.setdefault(key, []).append(item.row_number)

        if not targets:
            return list(result.items)

        try:
            credentials = resolve_erp_credentials(self._settings)
            with ErpSession(
                self._settings,
                self._logger,
                self._progress,
                self._cancel_check,
            ) as session:
                self._progress("正在检查 ERP 登录状态")
                session.ensure_authenticated(credentials)
                applications = ErpApplicationClient(
                    self._settings.erp,
                    session.page,
                    session.request,
                    self._logger,
                )
                attachments = ErpAttachmentClient(
                    self._settings.erp,
                    session.page,
                    session.request,
                    self._logger,
                )
                total = len(targets)
                for index, ((task_number, file_path), rows) in enumerate(
                    targets.items(), start=1
                ):
                    if self._is_cancelled():
                        self._mark_remaining_cancelled(
                            items_by_row,
                            list(targets.items())[index - 1 :],
                        )
                        break
                    self._progress(
                        f"正在上传 ERP {index}/{total}：{task_number}"
                    )
                    try:
                        application = applications.find_by_code(task_number)
                        attachment, _ = attachments.upload(application, file_path)
                        self._replace_rows(
                            items_by_row,
                            rows,
                            erp_success=True,
                            erp_code=str(ErrorCode.SUCCESS),
                            erp_message=display_message(ErrorCode.SUCCESS),
                            erp_attachment_id=attachment.id,
                        )
                        self._logger.info(
                            "ERP 批量上传成功 task_number=%s file=%s rows=%s attachment_id=%s",
                            task_number,
                            file_path,
                            rows,
                            attachment.id,
                        )
                    except Exception as exc:
                        code, message = self._failure_values(exc)
                        self._replace_rows(
                            items_by_row,
                            rows,
                            erp_success=False,
                            erp_code=code,
                            erp_message=message,
                        )
                        self._logger.exception(
                            "ERP 批量上传失败 task_number=%s file=%s rows=%s code=%s",
                            task_number,
                            file_path,
                            rows,
                            code,
                        )
        except Exception as exc:
            code, message = self._failure_values(exc)
            for rows in targets.values():
                pending = [
                    row
                    for row in rows
                    if items_by_row[row].erp_success is None
                ]
                self._replace_rows(
                    items_by_row,
                    pending,
                    erp_success=False,
                    erp_code=code,
                    erp_message=message,
                )
            self._logger.exception("ERP 批量上传阶段初始化失败 code=%s", code)

        return [items_by_row[item.row_number] for item in result.items]

    def _mark_remaining_cancelled(
        self,
        items_by_row: dict[int, ItemResult],
        targets: list[tuple[tuple[str, Path], list[int]]],
    ) -> None:
        for _, rows in targets:
            self._replace_rows(
                items_by_row,
                rows,
                erp_success=False,
                erp_code=str(ErrorCode.TASK_CANCELLED),
                erp_message=display_message(ErrorCode.TASK_CANCELLED),
            )

    @staticmethod
    def _replace_rows(
        items_by_row: dict[int, ItemResult],
        rows: list[int],
        **changes: object,
    ) -> None:
        for row in rows:
            item = items_by_row.get(row)
            if item is not None:
                items_by_row[row] = replace(item, **changes)

    @staticmethod
    def _failure_values(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, EhrmError):
            return str(exc.code), exc.message
        return str(ErrorCode.UNEXPECTED_ERROR), str(exc)

    def _progress(self, text: str) -> None:
        print(text)
        if self._progress_callback is not None:
            self._progress_callback(text)

    def _is_cancelled(self) -> bool:
        return self._cancel_check is not None and self._cancel_check()
