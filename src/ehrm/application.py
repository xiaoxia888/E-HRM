from __future__ import annotations

import logging

from ehrm.core.exceptions import ConfigurationError
from ehrm.core.result import ExecutionResult
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.models import RightsStatementQuery
from ehrm.modules.rights_statement.excel_models import ExcelTaskRequest
from ehrm.modules.rights_statement.excel_service import ExcelRightsStatementService
from ehrm.modules.rights_statement.service import RightsStatementService


RIGHTS_STATEMENT_DOWNLOAD = "unit_rights_statement.download"
RIGHTS_STATEMENT_EXCEL_EXPORT = "unit_rights_statement.excel_export"


class EhrmApplication:
    """Stable application entrypoint shared by CLI and future API/UI adapters."""

    def __init__(self, settings: AppSettings, logger: logging.Logger) -> None:
        self._rights_statement = RightsStatementService(settings, logger)
        self._excel_rights_statement = ExcelRightsStatementService(settings, logger)

    def run(
        self,
        task_name: str,
        payload: object,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> object:
        if task_name == RIGHTS_STATEMENT_DOWNLOAD:
            if not isinstance(payload, RightsStatementQuery):
                raise ConfigurationError("单位权益单任务参数类型错误")
            return self._rights_statement.execute(
                payload, username=username, password=password
            )
        if task_name == RIGHTS_STATEMENT_EXCEL_EXPORT:
            if not isinstance(payload, ExcelTaskRequest):
                raise ConfigurationError("Excel 权益单任务参数类型错误")
            return self._excel_rights_statement.execute(
                list(payload.groups),
                payload.mode,
                payload.output_dir,
                payload.source_excel,
            )
        raise ConfigurationError(f"未知任务：{task_name}")
