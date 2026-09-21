from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
import logging
import re
import time

from playwright.sync_api import Error as PlaywrightError, Frame, Locator, Page

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.browser.smart_wait import SmartWait, SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import TaskCancelledError, WebsiteStructureChangedError
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_enrollment.models import (
    ContractAddReason,
    ContractType,
    EmploymentEnrollmentItem,
    EmploymentEnrollmentRowError,
)
from ehrm.modules.jshrss_hall import JshrssHallNavigator


_LOGGER = logging.getLogger("ehrm")
_MENU = "用人单位用工参保登记"
_CATEGORY = "社会保险登记"
_SEARCH = "sipub-person-quick-search"
_LOADING = ".loading-mask:visible, .ant-spin-spinning:visible, .el-loading-mask:visible"
_INLINE_ERROR = re.compile(
    r"在本单位已存在参保信息|不能办理参保|未找到.*人员|不存在.*人员|无此人员"
)


class EmploymentEnrollmentPage:
    """Fills the Nanjing enrollment form and deliberately never submits it."""

    def __init__(
        self,
        page: Page,
        settings: AppSettings,
        *,
        progress_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.page = page
        self.settings = settings
        self.progress_callback = progress_callback
        cancelled = lambda: TaskCancelledError("参保数据录入已停止")
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
        self.navigator = JshrssHallNavigator(
            page,
            settings,
            operation_name="参保",
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def open(self) -> Frame:
        self.navigator.open_menu(_MENU, category_text=_CATEGORY)
        frame = self.navigator.wait_for_business_frame(
            _SEARCH,
            description="用人单位用工参保登记业务窗口",
        )
        self._dismiss_entry_notice(frame)
        return frame

    def fill_item(self, frame: Frame, item: EmploymentEnrollmentItem) -> None:
        item = item.normalized()
        search = frame.locator(_SEARCH).get_by_role("textbox").first
        try:
            search.wait_for(
                state="visible",
                timeout=self.settings.browser.action_timeout_ms,
            )
            self.pacer.perform(lambda: search.fill(item.identity_number))
            if search.input_value().strip().upper() != item.identity_number:
                raise WebsiteStructureChangedError("身份证号没有正确写入参保人员查询框")
            baseline = self._form_signature(frame)
            self.pacer.perform(lambda: search.press("Enter"))
            self._wait_for_query_result(frame, baseline=baseline)

            self._select_code(
                frame.locator("#contractAddReasons"),
                item.contract_add_reason.value,
                "合同增加原因",
            )
            self._select_code(
                frame.locator("#contractAddType"),
                item.contract_type.value,
                "合同类别",
            )
            self._fill_date(frame, "劳动合同开始日期", item.contract_start_date)
            if item.contract_type is not ContractType.OPEN_ENDED:
                assert item.contract_end_date is not None
                self._fill_date(frame, "劳动合同终止日期", item.contract_end_date)
            self._select_code(
                frame.locator("#positionType"),
                item.position_type.value,
                "岗位工种",
            )
            if item.contract_add_reason is ContractAddReason.NEW:
                self._select_code(
                    frame.locator("#insuredIdentity"),
                    item.insured_identity.value,
                    "参保身份",
                )
                assert isinstance(item.monthly_wage, Decimal)
                self._fill_value(
                    frame.locator("#wages"),
                    _decimal_text(item.monthly_wage),
                    "月缴费工资",
                )
            self._raise_on_feedback(frame)
            self._verify_form(frame, item)
        except (
            EmploymentEnrollmentRowError,
            TaskCancelledError,
            WebsiteStructureChangedError,
        ):
            raise
        except (PlaywrightError, ValueError) as exc:
            raise WebsiteStructureChangedError(
                "无法完成人员参保表单录入", details=str(exc)
            ) from exc

        source = f"第 {item.source_index} 行" if item.source_index else "当前人员"
        self._progress(f"{source}参保信息已录入，未点击确认提交")

    def _dismiss_entry_notice(self, frame: Frame) -> None:
        search = frame.locator(_SEARCH).get_by_role("textbox").first

        def ready() -> bool | None:
            if self._topmost_dialog(frame) is not None:
                return None
            return True if self._enabled_visible(search) else None

        deadline = time.monotonic() + self.settings.browser.action_timeout_ms / 1000
        while True:
            remaining_ms = round((deadline - time.monotonic()) * 1000)
            if remaining_ms < 1:
                raise WebsiteStructureChangedError(
                    "参保页面已打开，但入口提示未在操作时限内处理完成"
                )
            try:
                state = self.waiter.first(
                    [
                        WaitCondition("参保入口提示", lambda: self._topmost_dialog(frame)),
                        WaitCondition("参保人员查询框", ready, stable_for_ms=300),
                    ],
                    timeout_ms=remaining_ms,
                    description="等待参保人员查询表单",
                )
            except SmartWaitTimeoutError as exc:
                raise WebsiteStructureChangedError(
                    "参保页面已打开，但人员查询框没有加载完成", details=str(exc)
                ) from exc
            if state.condition == "参保人员查询框":
                return
            dialog = state.value
            self._progress("检测到业务入口提示，正在确认")
            self._close_dialog(dialog)

    def _wait_for_query_result(self, frame: Frame, *, baseline: str) -> None:
        reason = frame.locator("#contractAddReasons")

        def feedback() -> str | None:
            return self._feedback_text(frame)

        def form_ready() -> bool | None:
            if self._loading_visible(frame) or self._feedback_text(frame):
                return None
            if self._form_signature(frame) == baseline:
                return None
            if not self._enabled_visible(reason):
                return None
            try:
                return True if reason.locator("option").count() >= 2 else None
            except PlaywrightError:
                return None

        try:
            state = self.waiter.first(
                [
                    WaitCondition("参保业务错误", feedback, stable_for_ms=200),
                    WaitCondition("参保表单已加载", form_ready, stable_for_ms=700),
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待参保人员查询结果",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "查询人员后参保表单没有完成加载", details=str(exc)
            ) from exc
        if state.condition == "参保业务错误":
            message = str(state.value)
            self._close_topmost_dialog(frame)
            code = (
                "EMPLOYEE_NOT_FOUND"
                if any(token in message for token in ("未找到", "不存在", "无此人员"))
                else "BUSINESS_MESSAGE"
            )
            raise EmploymentEnrollmentRowError(message, reason_code=code)

    @staticmethod
    def _form_signature(frame: Frame) -> str:
        try:
            return " ".join(str(frame.locator("body").inner_text()).split())
        except PlaywrightError:
            return ""

    def _select_code(self, select: Locator, code: str, label: str) -> None:
        select.wait_for(
            state="visible",
            timeout=self.settings.browser.action_timeout_ms,
        )
        options = select.locator("option")
        matched_value: str | None = None
        for index in range(options.count()):
            value = str(options.nth(index).get_attribute("value") or "").strip()
            if value.removeprefix("string:") == code:
                matched_value = value
                break
        if matched_value is None:
            raise WebsiteStructureChangedError(f"页面中没有找到{label}编码：{code}")
        self.pacer.perform(lambda: select.select_option(value=matched_value))
        actual = select.input_value().strip().removeprefix("string:")
        if actual != code:
            raise WebsiteStructureChangedError(f"{label}选择后没有在页面中生效")

    def _fill_date(self, frame: Frame, label: str, value: date) -> None:
        field = self._labeled_input(frame, label)
        expected = value.isoformat()
        field.wait_for(
            state="visible",
            timeout=self.settings.browser.action_timeout_ms,
        )
        if not field.is_enabled():
            raise WebsiteStructureChangedError(f"{label}当前不可用")

        # The Jiangsu HRSS form uses an AngularJS uib-datepicker input with a
        # readonly attribute. Playwright's fill() correctly refuses to edit it.
        # Use the native value setter and the same DOM events that Angular's
        # ngModel input directive observes, then require the value to remain
        # stable before moving to the next field.
        def set_date() -> None:
            field.evaluate(
                """
                (element, nextValue) => {
                    const setter = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype,
                        'value'
                    ).set;
                    element.focus();
                    setter.call(element, nextValue);
                    element.dispatchEvent(new Event('input', { bubbles: true }));
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    element.blur();
                }
                """,
                expected,
            )

        self.pacer.perform(set_date)
        try:
            self.waiter.first(
                [
                    WaitCondition(
                        f"{label}已写入",
                        lambda: True
                        if field.input_value().strip() == expected
                        else None,
                        stable_for_ms=300,
                        transient_exceptions=(PlaywrightError,),
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description=f"等待{label}写入",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                f"{label}填写后没有在页面中生效", details=str(exc)
            ) from exc

    def _fill_value(self, field: Locator, value: str, label: str) -> None:
        field.wait_for(
            state="visible",
            timeout=self.settings.browser.action_timeout_ms,
        )
        self.pacer.perform(lambda: field.fill(value))
        self.pacer.perform(lambda: field.press("Tab"))
        if field.input_value().strip() != value:
            raise WebsiteStructureChangedError(f"{label}填写后没有在页面中生效")

    def _labeled_input(self, frame: Frame, label_text: str) -> Locator:
        labels = frame.locator("label").filter(has_text=label_text)
        for index in range(labels.count()):
            label = labels.nth(index)
            if not self._visible(label):
                continue
            field_id = str(label.get_attribute("for") or "").strip()
            if field_id:
                linked = frame.locator(f"#{field_id}")
                if self._visible(linked):
                    return linked
            candidates = label.locator(
                "xpath=following-sibling::*[1]//input | following-sibling::input[1]"
            )
            visible = self._first_visible(candidates)
            if visible is not None:
                return visible
            following = label.locator("xpath=following::input[1]")
            if self._visible(following):
                return following
        raise WebsiteStructureChangedError(f"无法定位字段：{label_text}")

    def _verify_form(self, frame: Frame, item: EmploymentEnrollmentItem) -> None:
        expected_selects = {
            "#contractAddReasons": item.contract_add_reason.value,
            "#contractAddType": item.contract_type.value,
            "#positionType": item.position_type.value,
        }
        if item.contract_add_reason is ContractAddReason.NEW:
            expected_selects["#insuredIdentity"] = item.insured_identity.value
        for selector, expected in expected_selects.items():
            actual = frame.locator(selector).input_value().strip().removeprefix("string:")
            if actual != expected:
                raise WebsiteStructureChangedError(f"参保表单回读不一致：{selector}")
        start_date = self._labeled_input(frame, "劳动合同开始日期").input_value().strip()
        if start_date != item.contract_start_date.isoformat():
            raise WebsiteStructureChangedError("劳动合同开始日期回读不一致")
        if item.contract_type is not ContractType.OPEN_ENDED:
            assert item.contract_end_date is not None
            end_date = self._labeled_input(frame, "劳动合同终止日期").input_value().strip()
            if end_date != item.contract_end_date.isoformat():
                raise WebsiteStructureChangedError("劳动合同终止日期回读不一致")
        if item.contract_add_reason is ContractAddReason.NEW:
            assert item.monthly_wage is not None
            if frame.locator("#wages").input_value().strip() != _decimal_text(item.monthly_wage):
                raise WebsiteStructureChangedError("月缴费工资回读不一致")

    def _feedback_text(self, frame: Frame) -> str | None:
        dialog = self._topmost_dialog(frame)
        if dialog is not None:
            body = dialog.locator(".modal-body")
            text = body.inner_text() if self._visible(body) else dialog.inner_text()
            normalized = " ".join(text.split())
            return normalized or None
        try:
            matches = frame.get_by_text(_INLINE_ERROR)
            for index in range(matches.count() - 1, -1, -1):
                match = matches.nth(index)
                if self._visible(match):
                    text = " ".join(match.inner_text().split())
                    if text:
                        return text
        except PlaywrightError:
            pass
        return None

    def _raise_on_feedback(self, frame: Frame) -> None:
        message = self._feedback_text(frame)
        if message is None:
            return
        self._close_topmost_dialog(frame)
        raise EmploymentEnrollmentRowError(
            message,
            reason_code="BUSINESS_MESSAGE",
        )

    def _close_topmost_dialog(self, frame: Frame) -> None:
        dialog = self._topmost_dialog(frame)
        if dialog is not None:
            self._close_dialog(dialog)

    def _close_dialog(self, dialog: Locator) -> None:
        buttons = dialog.get_by_role("button", name="确定", exact=True)
        button = self._last_visible(buttons)
        if button is None:
            raise WebsiteStructureChangedError("业务提示中没有可操作的确定按钮")
        handle = dialog.element_handle()
        self.pacer.perform(button.click)
        if handle is None:
            return
        try:
            self.waiter.first(
                [
                    WaitCondition(
                        "当前业务提示已关闭",
                        lambda: True if not _handle_visible(handle) else None,
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="关闭参保业务提示",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "参保业务提示点击确定后没有关闭", details=str(exc)
            ) from exc

    def _topmost_dialog(self, frame: Frame) -> Locator | None:
        dialogs = frame.locator(".modal-content")
        return self._last_visible(dialogs)

    def _loading_visible(self, frame: Frame) -> bool:
        masks = frame.locator(_LOADING)
        return any(self._visible(masks.nth(index)) for index in range(masks.count()))

    def _progress(self, detail: str) -> None:
        _LOGGER.info("参保：%s", detail)
        if self.progress_callback is not None:
            self.progress_callback(f"参保：{detail}")

    @staticmethod
    def _visible(locator: Locator) -> bool:
        try:
            return locator.count() > 0 and locator.is_visible()
        except PlaywrightError:
            return False

    @classmethod
    def _enabled_visible(cls, locator: Locator) -> bool:
        try:
            return cls._visible(locator) and locator.is_enabled()
        except PlaywrightError:
            return False

    @classmethod
    def _first_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count()):
                locator = locators.nth(index)
                if cls._visible(locator):
                    return locator
        except PlaywrightError:
            pass
        return None

    @classmethod
    def _last_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count() - 1, -1, -1):
                locator = locators.nth(index)
                if cls._visible(locator):
                    return locator
        except PlaywrightError:
            pass
        return None


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _handle_visible(handle: object) -> bool:
    try:
        return bool(handle.is_visible())
    except PlaywrightError:
        return False
