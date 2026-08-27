from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import (
    AuthenticationFailedError,
    EmployeeNotFoundError,
    MultipleEmployeeMatchedError,
    TaskCancelledError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.api_models import (
    InsuranceCode,
    PersonQueryRequest,
    PersonQueryResult,
    PersonRecord,
    RightsBillPrintRequest,
)
from ehrm.modules.rights_statement.excel_models import (
    EmployeeRecord,
    ExcelRunResult,
    ExportMode,
    ItemResult,
    WorkGroup,
)
from ehrm.modules.rights_statement.excel_service import ExcelRightsStatementService


QueryPeople = Callable[[PersonQueryRequest], PersonQueryResult]
DownloadRightsBill = Callable[[RightsBillPrintRequest, Path, str], Path]


class ApiExcelRightsStatementService(ExcelRightsStatementService):
    """Executes the existing Excel print plan through the rights APIs."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(settings, logger, progress_callback, cancel_check)

    def execute_with_api(
        self,
        groups: list[WorkGroup],
        mode: ExportMode,
        output_dir: Path,
        source_excel: Path | None,
        *,
        query_people: QueryPeople,
        download_rights_bill: DownloadRightsBill,
    ) -> ExcelRunResult:
        """Queries bac001 values and downloads each planned PDF via API."""
        output_dir.mkdir(parents=True, exist_ok=True)
        items: list[ItemResult] = []
        for index, group in enumerate(groups):
            if self._is_cancelled():
                self._progress("任务已停止，正在生成结果文件")
                items.extend(
                    self._cancelled_results(
                        record
                        for remaining in groups[index:]
                        for record in remaining.records
                    )
                )
                break
            batch_label = f"{index + 1}/{len(groups)}"
            self._progress(f"正在处理批次 {batch_label}（API）")
            self.logger.info(
                "开始通过 API 处理分组 sequence=%s rows=%s",
                group.sequence,
                [record.row_number for record in group.records],
            )
            items.extend(
                self._execute_api_group(
                    group,
                    group.mode or mode,
                    output_dir,
                    query_people,
                    download_rights_bill,
                )
            )
        return self._finalize(output_dir, mode, items, source_excel)

    def _execute_api_group(
        self,
        group: WorkGroup,
        mode: ExportMode,
        output_dir: Path,
        query_people: QueryPeople,
        download_rights_bill: DownloadRightsBill,
    ) -> list[ItemResult]:
        failures: list[ItemResult] = []
        selected: list[tuple[EmployeeRecord, PersonRecord]] = []

        for record_index, record in enumerate(group.records):
            try:
                self._raise_if_cancelled()
                result = query_people(self._query_request(record))
                selected.append((record, self._resolve_person(record, result)))
            except AuthenticationFailedError:
                # Authentication is shared by the whole batch. Retrying it for
                # every remaining row could repeatedly trigger a CAPTCHA.
                raise
            except TaskCancelledError:
                pending = [item[0] for item in selected]
                pending.extend(group.records[record_index:])
                return failures + self._cancelled_results(pending)
            except Exception as exc:
                code, message = self._failure_values(exc, None)
                failures.append(
                    ItemResult(record.row_number, False, code, message)
                )
                self.logger.error(
                    "API 人员查询失败 row=%s code=%s",
                    record.row_number,
                    code,
                )

        if not selected:
            return failures

        first = group.first
        target_dir, filename = self._download_target(
            group,
            mode,
            len(selected),
            output_dir,
        )
        try:
            self._raise_if_cancelled()
            downloaded = download_rights_bill(
                RightsBillPrintRequest(
                    start_month=self._api_month(first.start_month),
                    end_month=self._api_month(first.end_month),
                    insurance=InsuranceCode.from_display_name(
                        first.insurance_type
                    ),
                    person_ids=tuple(person.person_id for _, person in selected),
                ),
                target_dir,
                filename,
            )
        except AuthenticationFailedError:
            raise
        except TaskCancelledError:
            return failures + self._cancelled_results(
                record for record, _ in selected
            )
        except Exception as exc:
            code, message = self._failure_values(exc, None)
            return failures + [
                ItemResult(record.row_number, False, code, message)
                for record, _ in selected
            ]

        return failures + [
            ItemResult(
                record.row_number,
                True,
                str(ErrorCode.SUCCESS),
                display_message(ErrorCode.SUCCESS),
                downloaded,
            )
            for record, _ in selected
        ]

    @classmethod
    def _query_request(cls, record: EmployeeRecord) -> PersonQueryRequest:
        return PersonQueryRequest(
            identity_number=record.identity_number,
            name="" if record.identity_number.strip() else record.name,
            start_month=cls._api_month(record.start_month),
            end_month=cls._api_month(record.end_month),
        )

    @staticmethod
    def _resolve_person(
        expected: EmployeeRecord,
        result: PersonQueryResult,
    ) -> PersonRecord:
        identity = expected.identity_number.strip().upper()
        name = expected.name.strip()
        if identity:
            matches = [
                person
                for person in result.records
                if person.identity_number.strip().upper() == identity
            ]
        else:
            matches = [
                person
                for person in result.records
                if person.name.strip() == name
            ]
        label = name or identity
        if not matches:
            reason = result.page.error_info or f"未查询到人员：{label}"
            raise EmployeeNotFoundError(reason)
        if len(matches) > 1:
            raise MultipleEmployeeMatchedError(
                f"人员查询结果不唯一：{label}，共 {len(matches)} 条"
            )
        return matches[0]

    @staticmethod
    def _api_month(value: str) -> str:
        return value.strip().replace("-", "")
