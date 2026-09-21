from __future__ import annotations

from collections.abc import Callable, Sequence
import logging

from playwright.sync_api import Page

from ehrm.core.exceptions import EmployeeNotFoundError
from ehrm.core.error_catalog import ErrorCode
from ehrm.core.settings import AppSettings
from ehrm.modules.person_information_collection.models import (
    PersonInformationItem,
    PersonInformationPreparation,
    PersonInformationResult,
    PersonInformationRowError,
    normalize_items,
)
from ehrm.modules.person_information_collection.page import PersonInformationPage


class PersonInformationService:
    """Only populates collection forms; never invokes the business submit action."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        result_callback: Callable[[PersonInformationResult], None] | None = None,
    ) -> None:
        self.settings = settings
        self.logger = logger
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.result_callback = result_callback

    def prepare_with_page(
        self, page: Page, items: Sequence[PersonInformationItem]
    ) -> PersonInformationPreparation:
        normalized = normalize_items(items)
        results: list[PersonInformationResult] = []
        for index, item in enumerate(normalized):
            # An unsubmitted form can hold only one person. Keep one browser tab
            # per item so later rows never overwrite earlier inputs.
            item_page = page if index == 0 else page.context.new_page()
            automation = PersonInformationPage(
                item_page,
                self.settings,
                progress_callback=self.progress_callback,
                cancel_check=self.cancel_check,
            )
            try:
                frame = automation.open()
                automation.fill_item(frame, item)
            except EmployeeNotFoundError as exc:
                row = PersonInformationResult(
                    item,
                    False,
                    str(ErrorCode.EMPLOYEE_NOT_FOUND),
                    str(exc),
                )
                results.append(row)
                if self.result_callback is not None:
                    self.result_callback(row)
                self.logger.info("采集第 %s 行人员查询无结果：%s", item.source_index, exc)
                continue
            except PersonInformationRowError as exc:
                row = PersonInformationResult(
                    item,
                    False,
                    exc.reason_code,
                    exc.message,
                )
                results.append(row)
                if self.result_callback is not None:
                    self.result_callback(row)
                self.logger.info(
                    "采集第 %s 行数据存在问题 code=%s message=%s",
                    item.source_index,
                    exc.reason_code,
                    exc.message,
                )
                continue
            row = PersonInformationResult(item, True, str(ErrorCode.SUCCESS))
            results.append(row)
            if self.result_callback is not None:
                self.result_callback(row)
            self.logger.info(
                "人员基础信息已录入 row=%s identity=%s submitted=false",
                item.source_index,
                f"***{item.identity_number[-4:]}",
            )
        return PersonInformationPreparation(
            items=normalized,
            results=tuple(results),
            city_code="320100",
            city_name="南京",
            submitted=False,
        )
