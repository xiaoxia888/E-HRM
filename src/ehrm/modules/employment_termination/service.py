from __future__ import annotations

from collections.abc import Callable, Sequence
import logging

from playwright.sync_api import Page

from ehrm.core.settings import AppSettings
from ehrm.modules.employment_termination.models import (
    EmploymentTerminationItem,
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
        for item in normalized:
            automation.fill_item(frame, item)
        contract = self.settings.employment_termination
        self.logger.info(
            "退保数据录入完成 count=%s city=%s(%s) submitted=false",
            len(normalized),
            contract.city_name,
            contract.city_code,
        )
        if self.progress_callback is not None:
            self.progress_callback(
                f"退保：已录入 {len(normalized)} 条数据；未点击确定提交"
            )
        return EmploymentTerminationPreparation(
            items=normalized,
            city_code=contract.city_code,
            city_name=contract.city_name,
            submitted=False,
        )
