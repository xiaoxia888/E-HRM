from __future__ import annotations

import logging

from playwright.sync_api import Page

from ehrm.browser.download import DownloadManager
from ehrm.browser.session import authenticated_browser
from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exception_handler import ExceptionManager
from ehrm.core.result import ExecutionResult
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.models import RightsStatementQuery
from ehrm.modules.rights_statement.excel_models import EmployeeRecord, WorkGroup
from ehrm.modules.rights_statement.page import RightsStatementPage


class RightsStatementService:
    def __init__(self, settings: AppSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.exceptions = ExceptionManager(
            logger,
            settings.browser.user_data_dir.parent / "screenshots",
        )

    def execute(
        self,
        request: RightsStatementQuery,
        *,
        username: str | None = None,
        password: str | None = None,
        mobile: str | None = None,
    ) -> ExecutionResult:
        request.validate()
        page: Page | None = None
        try:
            with authenticated_browser(
                self.settings,
                username=username,
                password=password,
                mobile=mobile,
            ) as browser:
                page = browser.page
                statement_page = RightsStatementPage(
                    page, self.settings, DownloadManager()
                )
                statement_page.open()
                record = EmployeeRecord(
                    row_number=1,
                    unit="",
                    department="",
                    name=request.employee_name,
                    identity_number="",
                    insurance_type=request.insurance_type,
                    start_month=request.start_month,
                    end_month=request.end_month,
                    task_number="单次下载",
                )
                group = WorkGroup(sequence=1, records=(record,))
                statement_page.prepare_group(group)
                statement_page.query_and_add(record)
                downloaded = statement_page.download_selected(
                    request.output_dir,
                    request.fallback_filename,
                    [record],
                )
                self.logger.info("权益单下载成功 file=%s", downloaded)
                return ExecutionResult(
                    success=True,
                    code=str(ErrorCode.SUCCESS),
                    message=display_message(ErrorCode.SUCCESS),
                    file_path=downloaded,
                )
        except Exception as exc:
            return self.exceptions.handle(exc, page)
