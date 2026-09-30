from __future__ import annotations

from collections.abc import Callable, Sequence
import logging

from playwright.sync_api import Error as PlaywrightError, Page

from ehrm.browser.smart_wait import SmartWaitTimeoutError
from ehrm.core.error_catalog import ErrorCode
from ehrm.core.exceptions import EmployeeNotFoundError, EhrmError
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_termination.models import (
    EmploymentTerminationItem,
    EmploymentTerminationItemResult,
    EmploymentTerminationPreparation,
    normalize_termination_items,
)
from ehrm.modules.employment_termination.page import EmploymentTerminationPage


class EmploymentTerminationService:
    """Application service whose public input is an object array, not Excel."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check

    def submit_with_page(
        self, page: Page, items: Sequence[EmploymentTerminationItem],
        *,
        before_submit_callback: Callable[[EmploymentTerminationItem], None] | None = None,
        result_callback: Callable[[EmploymentTerminationItemResult], None] | None = None,
    ) -> EmploymentTerminationPreparation:
        """Explicit, per-person submission. Never retries an uncertain mutation.

        A failed/unknown submit stops this batch and exports all remaining rows
        as not processed. Confirmed successes remain recorded even if closing
        their window fails, preventing accidental re-submission on recovery.
        """
        normalized = normalize_termination_items(tuple(items))
        automation = EmploymentTerminationPage(
            page, self.settings, progress_callback=self.progress_callback,
            cancel_check=self.cancel_check,
        )
        class RecordedResults(list):
            # Record immediately: a later cancellation/window-close failure
            # must not erase a confirmed person's durable submission result.
            def append(self, result):
                if result_callback:
                    result_callback(result)
                super().append(result)

            def extend(self, rows):
                for result in rows:
                    self.append(result)

        results: list[EmploymentTerminationItemResult] = RecordedResults()
        frame = None
        for index, item in enumerate(normalized):
            attempting_submit = False
            try:
                if frame is None:
                    frame = automation.open()
                automation.fill_item(frame, item)
                if before_submit_callback:
                    before_submit_callback(item)
                attempting_submit = True
                automation.submit_item(frame, item)
            except EmployeeNotFoundError as exc:
                if attempting_submit:
                    results.append(EmploymentTerminationItemResult(
                        item, False, "TERMINATION_RESULT_UNKNOWN", str(exc), "unknown",
                    ))
                    self._append_unprocessed(results, normalized[index + 1:])
                    break
                automation.dismiss_query_feedback(frame)
                results.append(EmploymentTerminationItemResult(
                    item, False, str(exc.code), exc.message, "failed",
                ))
                self.logger.info("退保第 %s 条未查询到人员，跳过且未提交", index + 1)
                if self.progress_callback:
                    self.progress_callback(f"退保：第 {index + 1} 条未查询到人员，跳过且未提交")
                continue
            except (EhrmError, PlaywrightError, SmartWaitTimeoutError, ValueError) as exc:
                outcome = getattr(exc, "outcome", "unknown" if attempting_submit else "failed")
                results.append(EmploymentTerminationItemResult(
                    item, False, str(getattr(exc, "code", "TERMINATION_RESULT_UNKNOWN")),
                    str(exc), outcome,
                ))
                self.logger.warning("退保第 %s 条停止处理 outcome=%s reason=%s", index + 1, outcome, exc)
                if self.progress_callback:
                    self.progress_callback(f"退保：第 {index + 1} 条{'结果待确认' if outcome == 'unknown' else '处理失败'}：{exc}；停止后续处理")
                self._append_unprocessed(results, normalized[index + 1:])
                break
            results.append(EmploymentTerminationItemResult(
                item, True, str(ErrorCode.SUCCESS), "接口和成功页面均已确认提交成功", "submitted",
            ))
            if self.progress_callback:
                self.progress_callback(f"退保：第 {index + 1}/{len(normalized)} 条提交成功")
            if index == len(normalized) - 1:
                # Leave the final success view visible for the CLI diagnostic
                # screenshot and --keep-browser-open inspection.
                break
            try:
                automation.close_submitted_form(frame)
            except (EhrmError, PlaywrightError, SmartWaitTimeoutError, ValueError) as exc:
                results[-1] = EmploymentTerminationItemResult(
                    item, True, str(ErrorCode.SUCCESS),
                    f"已确认提交成功，但关闭窗口失败：{exc}；已停止后续处理", "submitted",
                )
                self.logger.warning("退保已提交，但关闭窗口失败；停止后续处理：%s", exc)
                if self.progress_callback:
                    self.progress_callback(results[-1].message)
                self._append_unprocessed(results, normalized[index + 1:])
                break
            frame = None
        contract = self.settings.employment_termination
        verified_count = sum(result.status == "submitted" for result in results)
        self.logger.info("退保提交结束 total=%s verified=%s unknown=%s", len(results), verified_count,
                         sum(result.status == "unknown" for result in results))
        return EmploymentTerminationPreparation(
            normalized, tuple(results), contract.city_code, contract.city_name,
            submitted=verified_count > 0,
        )

    @staticmethod
    def _append_unprocessed(
        results: list[EmploymentTerminationItemResult],
        items: Sequence[EmploymentTerminationItem],
    ) -> None:
        results.extend(EmploymentTerminationItemResult(
            item, False, "TERMINATION_NOT_PROCESSED", "前一条处理中断，本条未执行提交", "not_processed",
        ) for item in items)

    def prepare_with_page(
        self,
        page: Page,
        items: Sequence[EmploymentTerminationItem],
    ) -> EmploymentTerminationPreparation:
        normalized = normalize_termination_items(tuple(items))
        automation = EmploymentTerminationPage(
            page,
            self.settings,
            progress_callback=self.progress_callback,
            cancel_check=self.cancel_check,
        )
        frame = automation.open()
        results: list[EmploymentTerminationItemResult] = []
        for item in normalized:
            try:
                automation.fill_item(frame, item)
            except EmployeeNotFoundError as exc:
                # This is a row-level data result, not a system failure. Clear
                # the site's error modal before moving to the next person.
                automation.dismiss_query_feedback(frame)
                results.append(
                    EmploymentTerminationItemResult(
                        item=item,
                        success=False,
                        code=str(exc.code),
                        message=exc.message,
                    )
                )
                source = (
                    f"第 {item.source_index} 行"
                    if item.source_index > 0
                    else item.identity_number
                )
                message = f"退保：{source}未查询到可办理人员，继续处理下一条"
                self.logger.info(
                    "%s identity=%s reason=%s",
                    message,
                    item.identity_number,
                    exc.message,
                )
                if self.progress_callback is not None:
                    self.progress_callback(message)
                continue
            results.append(
                EmploymentTerminationItemResult(
                    item=item,
                    success=True,
                    code=str(ErrorCode.SUCCESS),
                )
            )
        contract = self.settings.employment_termination
        self.logger.info(
            "退保数据录入完成 total=%s succeeded=%s failed=%s "
            "city=%s(%s) submitted=false",
            len(results),
            sum(result.success for result in results),
            sum(not result.success for result in results),
            contract.city_name,
            contract.city_code,
        )
        if self.progress_callback is not None:
            self.progress_callback(
                "退保：处理完成，"
                f"成功 {sum(result.success for result in results)} 条，"
                f"未查询到 {sum(not result.success for result in results)} 条；"
                "未点击确定提交"
            )
        return EmploymentTerminationPreparation(
            items=normalized,
            results=tuple(results),
            city_code=contract.city_code,
            city_name=contract.city_name,
            submitted=False,
        )
