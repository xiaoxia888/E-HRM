from __future__ import annotations

from collections.abc import Callable, Sequence
import logging

from playwright.sync_api import Page

from ehrm.core.error_catalog import ErrorCode
from ehrm.core.exceptions import EmployeeNotFoundError
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
