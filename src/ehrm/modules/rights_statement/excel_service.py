from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from playwright.sync_api import Page

from ehrm.browser.download import DownloadManager
from ehrm.browser.session import authenticated_browser
from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.core.exception_handler import ExceptionManager
from ehrm.core.settings import AppSettings
from ehrm.modules.rights_statement.excel_models import (
    ExcelRunResult,
    ExportMode,
    ItemResult,
    WorkGroup,
)
from ehrm.modules.rights_statement.page import RightsStatementPage
from ehrm.modules.rights_statement.result_workbook import ResultWorkbookWriter


_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class ExcelRightsStatementService:
    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.exceptions = ExceptionManager(
            logger,
            settings.browser.user_data_dir.parent / "screenshots",
        )

    def execute(
        self,
        groups: list[WorkGroup],
        mode: ExportMode,
        output_dir: Path,
        source_excel: Path | None = None,
    ) -> ExcelRunResult:
        page: Page | None = None
        try:
            with authenticated_browser(self.settings) as browser:
                page = browser.page
                return self.execute_with_page(
                    page,
                    groups,
                    mode,
                    output_dir,
                    source_excel,
                )
        except Exception as exc:
            failure = self.exceptions.handle(exc, page)
            items = [
                ItemResult(
                    row_number=record.row_number,
                    success=False,
                    code=failure.code,
                    message=failure.message,
                )
                for group in groups
                for record in group.records
            ]
            return self._finalize(output_dir, mode, items, source_excel)

    def execute_with_page(
        self,
        page: Page,
        groups: list[WorkGroup],
        mode: ExportMode,
        output_dir: Path,
        source_excel: Path | None = None,
    ) -> ExcelRunResult:
        """Executes a task on an existing tab without closing its login session."""
        output_dir.mkdir(parents=True, exist_ok=True)
        items: list[ItemResult] = []
        try:
            statement = RightsStatementPage(
                page,
                self.settings,
                DownloadManager(),
                self.cancel_check,
            )
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
                self._progress(f"正在准备批次 {batch_label}")
                self.logger.info(
                    "开始处理分组 sequence=%s rows=%s",
                    group.sequence,
                    [record.row_number for record in group.records],
                )
                items.extend(
                    self._execute_group(
                        statement,
                        group,
                        group.mode or mode,
                        output_dir,
                        batch_label,
                    )
                )
                if self._is_cancelled():
                    self._progress("任务已停止，正在生成结果文件")
                    items.extend(
                        self._cancelled_results(
                            record
                            for remaining in groups[index + 1 :]
                            for record in remaining.records
                        )
                    )
                    break
        except Exception as exc:
            failure = self.exceptions.handle(exc, page)
            completed_rows = {item.row_number for item in items}
            for group in groups:
                for record in group.records:
                    if record.row_number not in completed_rows:
                        items.append(
                            ItemResult(
                                row_number=record.row_number,
                                success=False,
                                code=failure.code,
                                message=failure.message,
                            )
                        )

        return self._finalize(output_dir, mode, items, source_excel)

    def cancelled_result(
        self,
        groups: list[WorkGroup],
        mode: ExportMode,
        output_dir: Path,
        source_excel: Path | None,
    ) -> ExcelRunResult:
        """Creates the normal result artifacts when stopped before page work."""
        items = self._cancelled_results(
            record for group in groups for record in group.records
        )
        return self._finalize(output_dir, mode, items, source_excel)

    def _finalize(
        self,
        output_dir: Path,
        mode: ExportMode,
        items: list[ItemResult],
        source_excel: Path | None,
    ) -> ExcelRunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        items.sort(key=lambda item: item.row_number)
        result_workbook: Path | None = None
        if source_excel is not None:
            try:
                result_workbook = ResultWorkbookWriter().write(
                    source_excel,
                    output_dir,
                    items,
                )
            except Exception:
                self.logger.exception("生成带失败原因的结果 Excel 失败")
        manifest = self._write_manifest(
            output_dir,
            mode,
            items,
            result_workbook,
        )
        succeeded = sum(item.success for item in items)
        return ExcelRunResult(
            mode=mode,
            total=len(items),
            succeeded=succeeded,
            failed=len(items) - succeeded,
            manifest_path=manifest,
            result_workbook_path=result_workbook,
            items=tuple(items),
            erp_uploaded=sum(item.erp_success is True for item in items),
            erp_failed=sum(item.erp_success is False for item in items),
        )

    def refresh_artifacts(
        self,
        result: ExcelRunResult,
        source_excel: Path,
        output_dir: Path,
        items: list[ItemResult],
    ) -> ExcelRunResult:
        """Rewrites result artifacts after the optional ERP upload stage."""
        ordered = sorted(items, key=lambda item: item.row_number)
        result_workbook = result.result_workbook_path
        if result_workbook is not None:
            try:
                ResultWorkbookWriter().write(
                    source_excel,
                    output_dir,
                    ordered,
                    destination=result_workbook,
                )
            except Exception:
                self.logger.exception("回写 ERP 上传结果到 Excel 失败")
        manifest = self._write_manifest(
            output_dir,
            result.mode,
            ordered,
            result_workbook,
            destination=result.manifest_path,
        )
        succeeded = sum(item.success for item in ordered)
        return ExcelRunResult(
            mode=result.mode,
            total=len(ordered),
            succeeded=succeeded,
            failed=len(ordered) - succeeded,
            manifest_path=manifest,
            result_workbook_path=result_workbook,
            items=tuple(ordered),
            erp_uploaded=sum(item.erp_success is True for item in ordered),
            erp_failed=sum(item.erp_success is False for item in ordered),
        )

    def _execute_group(
        self,
        page: RightsStatementPage,
        group: WorkGroup,
        mode: ExportMode,
        output_dir: Path,
        batch_label: str,
    ) -> list[ItemResult]:
        failures: list[ItemResult] = []
        selected = []
        try:
            self._raise_if_cancelled()
            page.open()
            # Clear historical right-side rows before a new group. Nothing is
            # cleared after download, so task completion is not delayed.
            page.recover_group_state()
            page.prepare_group(group)
            self._progress(f"正在处理批次 {batch_label}")
        except TaskCancelledError:
            return self._cancelled_results(group.records)
        except Exception as exc:
            code, message = self._failure_values(exc, page.page)
            return [
                ItemResult(record.row_number, False, code, message)
                for record in group.records
            ]

        for record_index, record in enumerate(group.records):
            try:
                self._raise_if_cancelled()
                page.query_and_add(record)
                selected.append(record)
            except TaskCancelledError:
                pending = selected + list(group.records[record_index:])
                return failures + self._cancelled_results(pending)
            except Exception as exc:
                code, message = self._failure_values(exc, page.page)
                failures.append(
                    ItemResult(record.row_number, False, code, message)
                )
                self.logger.error(
                    "人员加入失败 row=%s code=%s", record.row_number, code
                )

        if not selected:
            return failures

        target_dir, filename = self._download_target(
            group,
            mode,
            len(selected),
            output_dir,
        )

        try:
            self._raise_if_cancelled()
            downloaded = page.download_selected(target_dir, filename, selected)
            successes = [
                ItemResult(
                    record.row_number,
                    True,
                    str(ErrorCode.SUCCESS),
                    display_message(ErrorCode.SUCCESS),
                    downloaded,
                )
                for record in selected
            ]
            return failures + successes
        except TaskCancelledError:
            return failures + self._cancelled_results(selected)
        except Exception as exc:
            code, message = self._failure_values(exc, page.page)
            return failures + [
                ItemResult(record.row_number, False, code, message)
                for record in selected
            ]

    def _failure_values(
        self,
        exc: Exception,
        page: Page | None,
    ) -> tuple[str, str]:
        result = self.exceptions.handle(exc, page)
        if not isinstance(exc, EhrmError):
            return result.code, result.message
        messages = [result.message]
        if exc.message and exc.message not in messages:
            messages.append(exc.message)
        if exc.details and exc.details not in messages:
            messages.append(exc.details)
        return result.code, "\n".join(messages)

    @classmethod
    def _download_target(
        cls,
        group: WorkGroup,
        mode: ExportMode,
        person_count: int,
        output_dir: Path,
    ) -> tuple[Path, str]:
        """Builds the same deterministic target for every print backend."""
        first = group.first
        pdf_root = output_dir / "PDF"
        group_suffix = (
            f"_组{first.print_group_sequence:02d}"
            if first.print_group_sequence
            else ""
        )
        if mode is ExportMode.INDIVIDUAL:
            target_dir = (
                pdf_root / cls._safe(first.unit) / cls._safe(first.department)
            )
            filename = (
                f"{cls._safe(first.task_number)}{group_suffix}_"
                f"{cls._safe(first.name)}_"
                f"{cls._safe(first.insurance_type)}_"
                f"{first.start_month.replace('-', '')}-"
                f"{first.end_month.replace('-', '')}_权益单.pdf"
            )
        else:
            target_dir = pdf_root / cls._safe(first.unit) / "批量"
            filename = (
                f"{cls._safe(first.task_number)}_"
                f"{cls._safe(first.insurance_type)}_"
                f"{first.start_month.replace('-', '')}-"
                f"{first.end_month.replace('-', '')}_"
                f"批次{group.sequence}_{person_count}人.pdf"
            )
        return target_dir, filename

    def _progress(self, message: str) -> None:
        print(message)
        if self.progress_callback is not None:
            self.progress_callback(message)

    def _is_cancelled(self) -> bool:
        return self.cancel_check is not None and self.cancel_check()

    def _raise_if_cancelled(self) -> None:
        if self._is_cancelled():
            raise TaskCancelledError("用户提前停止任务")

    @staticmethod
    def _cancelled_results(records) -> list[ItemResult]:
        return [
            ItemResult(
                record.row_number,
                False,
                str(ErrorCode.TASK_CANCELLED),
                display_message(ErrorCode.TASK_CANCELLED),
            )
            for record in records
        ]

    @staticmethod
    def _safe(value: str) -> str:
        return _UNSAFE_FILENAME.sub("_", value).strip(". ") or "未命名"

    @staticmethod
    def _write_manifest(
        output_dir: Path,
        mode: ExportMode,
        items: list[ItemResult],
        result_workbook: Path | None,
        destination: Path | None = None,
    ) -> Path:
        run_dir = output_dir / "_runs"
        run_dir.mkdir(parents=True, exist_ok=True)
        path = destination or run_dir / f"result_{datetime.now():%Y%m%d_%H%M%S}.json"
        payload = {
            "mode": mode.value,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "result_workbook_path": (
                str(result_workbook) if result_workbook else None
            ),
            "items": [
                {
                    "row_number": item.row_number,
                    "success": item.success,
                    "code": item.code,
                    "message": display_message(item.code, item.message),
                    "file_path": str(item.file_path) if item.file_path else None,
                    "erp_success": item.erp_success,
                    "erp_code": item.erp_code,
                    "erp_message": (
                        display_message(item.erp_code, item.erp_message)
                        if item.erp_code
                        else item.erp_message
                    ),
                    "erp_attachment_id": item.erp_attachment_id,
                }
                for item in items
            ],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
