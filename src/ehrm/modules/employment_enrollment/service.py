from __future__ import annotations

from collections.abc import Callable, Sequence
import logging

from playwright.sync_api import Page

from ehrm.core.error_catalog import ErrorCode
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_enrollment.models import (
    EmploymentEnrollmentItem,
    EmploymentEnrollmentPreparation,
    EmploymentEnrollmentResult,
    EmploymentEnrollmentRowError,
    normalize_enrollment_items,
)
from ehrm.modules.employment_enrollment.page import EmploymentEnrollmentPage


class EmploymentEnrollmentService:
    """Object-array enrollment service; it never clicks the final submit."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        result_callback: Callable[[EmploymentEnrollmentResult], None] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.result_callback = result_callback

    def prepare_with_page(
        self,
        page: Page,
        items: Sequence[EmploymentEnrollmentItem],
    ) -> EmploymentEnrollmentPreparation:
        normalized = normalize_enrollment_items(items)
        results: list[EmploymentEnrollmentResult] = []
        for index, item in enumerate(normalized):
            item_page = page if index == 0 else page.context.new_page()
            automation = EmploymentEnrollmentPage(
                item_page,
                self.settings,
                progress_callback=self.progress_callback,
                cancel_check=self.cancel_check,
            )
            try:
                frame = automation.open()
                automation.fill_item(frame, item)
            except EmploymentEnrollmentRowError as exc:
                result = EmploymentEnrollmentResult(
                    item=item,
                    success=False,
                    code=exc.reason_code,
                    message=exc.message,
                )
                self._publish(result)
                results.append(result)
                self.logger.info(
                    "参保第 %s 行存在业务问题 code=%s message=%s",
                    item.source_index,
                    exc.reason_code,
                    exc.message,
                )
                continue
            result = EmploymentEnrollmentResult(
                item=item,
                success=True,
                code=str(ErrorCode.SUCCESS),
            )
            self._publish(result)
            results.append(result)
            self.logger.info(
                "参保信息已录入 row=%s identity=***%s submitted=false",
                item.source_index,
                item.identity_number[-4:],
            )
        return EmploymentEnrollmentPreparation(
            items=normalized,
            results=tuple(results),
            submitted=False,
        )

    def _publish(self, result: EmploymentEnrollmentResult) -> None:
        if self.result_callback is not None:
            self.result_callback(result)
