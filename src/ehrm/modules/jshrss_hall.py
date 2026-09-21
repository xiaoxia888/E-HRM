from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError, Frame, Locator, Page

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.browser.smart_wait import SmartWait, SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import (
    ConfigurationError,
    TaskCancelledError,
    WebsiteStructureChangedError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_termination.page import EmploymentTerminationPage


def validate_nanjing_contract(settings: AppSettings) -> None:
    region = settings.employment_termination
    if (region.city_code, region.city_name) != ("320100", "南京"):
        raise ConfigurationError("该业务只能在南京办理：地区配置必须为 320100/南京")


class JshrssHallNavigator:
    """Shared Jiangsu HRSS hall entry, Nanjing guard and menu search."""

    def __init__(
        self,
        page: Page,
        settings: AppSettings,
        *,
        operation_name: str,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.operation_name = operation_name
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        cancelled = lambda: TaskCancelledError(f"{operation_name}任务已停止")
        self.pacer = BrowserInteractionPacer(
            settings.browser.pacing,
            page.wait_for_timeout,
            cancel_check=cancel_check,
            cancelled_error=cancelled,
        )
        self.waiter = SmartWait(
            page.wait_for_timeout,
            poll_interval_ms=100,
            cancel_check=cancel_check,
            cancelled_error=cancelled,
        )

    def open_menu(self, menu_text: str, *, category_text: str | None = None) -> None:
        validate_nanjing_contract(self.settings)
        contract = self.settings.employment_termination
        self._progress("正在进入智慧人社大厅")
        self.page.goto(
            urljoin(self.settings.site.login_url, contract.home_path),
            wait_until="domcontentloaded",
        )
        EmploymentTerminationPage(
            self.page,
            self.settings,
            progress_callback=self._region_progress,
            cancel_check=self.cancel_check,
        ).ensure_nanjing()
        self._progress(f"南京地区校验通过，正在打开{menu_text}")

        try:
            unit_affairs = self._first_visible(
                self.page.get_by_text("单位办事", exact=True)
            )
            if unit_affairs is not None:
                self.pacer.perform(unit_affairs.click)
            middle = self.page.frame_locator(contract.middle_frame)
            search = middle.get_by_role("textbox", name="请输入您要搜索的内容")
            search.wait_for(
                state="visible",
                timeout=self.settings.browser.action_timeout_ms,
            )
            self.pacer.perform(lambda: search.fill(menu_text))
            self.pacer.perform(lambda: search.press("Enter"))
            if category_text:
                categories = middle.get_by_text(category_text, exact=True)
                menus = middle.get_by_text(menu_text, exact=True)
                state = self.waiter.first(
                    [
                        WaitCondition(
                            "业务分类",
                            lambda: self._first_visible(categories),
                            transient_exceptions=(PlaywrightError,),
                        ),
                        WaitCondition(
                            "目标业务菜单",
                            lambda: self._last_visible(menus),
                            transient_exceptions=(PlaywrightError,),
                        ),
                    ],
                    timeout_ms=self.settings.browser.action_timeout_ms,
                    description=f"等待{menu_text}搜索结果",
                )
                if state.condition == "业务分类":
                    category = state.value
                    self.pacer.perform(category.click)
            menu = middle.get_by_text(menu_text, exact=True)
            visible_menu = self.waiter.first(
                [
                    WaitCondition(
                        "目标业务菜单",
                        lambda: self._last_visible(menu),
                        transient_exceptions=(PlaywrightError,),
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description=f"等待{menu_text}菜单",
            ).value
            self.pacer.perform(visible_menu.click)
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                f"智慧人社搜索结果中没有找到{menu_text}", details=str(exc)
            ) from exc
        except WebsiteStructureChangedError:
            raise
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"无法从智慧人社大厅打开{menu_text}", details=str(exc)
            ) from exc

    def wait_for_business_frame(
        self,
        required_selector: str,
        *,
        description: str,
    ) -> Frame:
        contract = self.settings.employment_termination

        def ready_frame() -> Frame | None:
            outer_iframes = self.page.locator(contract.outer_business_frame)
            for outer_index in range(outer_iframes.count() - 1, -1, -1):
                outer = outer_iframes.nth(outer_index)
                if not self._visible(outer):
                    continue
                outer_frame = self._content_frame(outer)
                if outer_frame is None:
                    continue
                inner_iframes = outer_frame.locator(contract.business_frame)
                for inner_index in range(inner_iframes.count() - 1, -1, -1):
                    inner = inner_iframes.nth(inner_index)
                    if not self._visible(inner):
                        continue
                    business = self._content_frame(inner)
                    if (
                        business is not None
                        and business.locator(required_selector).count() > 0
                    ):
                        return business
            return None

        try:
            return self.waiter.first(
                [
                    WaitCondition(
                        description,
                        ready_frame,
                        transient_exceptions=(PlaywrightError,),
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description=f"等待{description}",
            ).value
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                f"{description}未加载", details=str(exc)
            ) from exc

    def _region_progress(self, message: str) -> None:
        detail = message.split("：", 1)[-1]
        self._progress(detail)

    def _progress(self, detail: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(f"{self.operation_name}：{detail}")

    @staticmethod
    def _visible(locator: Locator) -> bool:
        try:
            return locator.count() > 0 and locator.is_visible()
        except PlaywrightError:
            return False

    @classmethod
    def _first_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count()):
                candidate = locators.nth(index)
                if cls._visible(candidate):
                    return candidate
        except PlaywrightError:
            pass
        return None

    @classmethod
    def _last_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count() - 1, -1, -1):
                candidate = locators.nth(index)
                if cls._visible(candidate):
                    return candidate
        except PlaywrightError:
            pass
        return None

    @staticmethod
    def _content_frame(iframe: Locator) -> Frame | None:
        try:
            element = iframe.element_handle()
            return element.content_frame() if element is not None else None
        except PlaywrightError:
            return None
