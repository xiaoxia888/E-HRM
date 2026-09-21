from __future__ import annotations

from collections.abc import Callable
import logging

from playwright.sync_api import Error as PlaywrightError, Frame, Locator, Page

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.browser.smart_wait import SmartWait, SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import (
    EmployeeNotFoundError,
    TaskCancelledError,
    WebsiteStructureChangedError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.jshrss_hall import JshrssHallNavigator, validate_nanjing_contract
from ehrm.modules.person_information_collection.models import PersonInformationItem
from ehrm.modules.person_information_collection.models import (
    PersonInformationRowError,
    address_level_for_household,
)


_LOGGER = logging.getLogger("ehrm")
_MENU = "人员基础信息采集"
_PICKER = ".girder-select-address-container"
_LOADING = ".loading-mask:visible, .ant-spin-spinning:visible, .el-loading-mask:visible"


class PersonInformationPage:
    """Nanjing collection form; the final business submit is deliberately absent."""

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
        self.cancel_check = cancel_check
        cancelled_error = lambda: TaskCancelledError("人员基础信息采集已停止")
        self.pacer = BrowserInteractionPacer(
            settings.browser.pacing,
            page.wait_for_timeout,
            cancel_check=cancel_check,
            cancelled_error=cancelled_error,
        )
        self.waiter = SmartWait(
            page.wait_for_timeout,
            poll_interval_ms=100,
            cancel_check=cancel_check,
            cancelled_error=cancelled_error,
        )
        self.navigator = JshrssHallNavigator(
            page,
            settings,
            operation_name="采集",
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    def open(self) -> Frame:
        validate_nanjing_contract(self.settings)
        self._open_menu()
        frame = self._wait_for_business_frame()
        self._wait_for_form_ready(frame, details=False)
        return frame

    def fill_item(self, frame: Frame, item: PersonInformationItem) -> None:
        item = item.normalized()
        try:
            identity = frame.locator("#idNumber")
            name = frame.locator("#name")
            mobile = frame.locator('#ng-view input[name="mobile"]')
            nation = frame.locator("#nation")
            household = frame.locator("#householdType")
            self._wait_for_form_ready(frame, details=False)
            self._fill_and_verify(identity, item.identity_number, "身份证号")
            self.pacer.perform(lambda: identity.press("Enter"))
            # The recording does not establish a lookup API for this field.
            # Readiness comes from the form/overlay, not a guessed XHR.
            self._wait_for_idle(frame)
            self._wait_for_form_ready(frame, details=True)
            self._fill_and_verify(name, item.name, "姓名")
            self._fill_and_verify(mobile, item.mobile, "手机号")
            self._select_option(
                nation,
                item.nation,
                field_name="民族",
                reason_code="NATION_NOT_FOUND",
            )
            household_label = self._select_household(household, item.household_type)
            self._wait_for_idle(frame)
            self._raise_on_feedback(frame)
            address_depth = self._validate_address_depth(
                household_label,
                item.address,
            )
            if address_depth:
                self._select_address(frame, item.address)
            self._wait_for_idle(frame)
            self._raise_on_feedback(frame)
            self._verify_fields(frame, item, address_depth=address_depth)
        except (
            EmployeeNotFoundError,
            PersonInformationRowError,
            TaskCancelledError,
            WebsiteStructureChangedError,
        ):
            raise
        except (PlaywrightError, ValueError) as exc:
            raise WebsiteStructureChangedError(
                "人员基础信息采集表单录入失败", details=str(exc)
            ) from exc
        source = f"第 {item.source_index} 行" if item.source_index else "当前人员"
        self._progress(f"采集：{source}信息已录入，未点击提交")

    def _open_menu(self) -> None:
        self.navigator.open_menu(_MENU)

    def _wait_for_business_frame(self) -> Frame:
        return self.navigator.wait_for_business_frame(
            "#idNumber",
            description="人员基础信息采集业务窗口",
        )

    def _wait_for_form_ready(self, frame: Frame, *, details: bool = False) -> None:
        def ready() -> bool | None:
            if self._feedback_visible(frame):
                self._raise_on_feedback(frame)
                return None
            if self._loading_visible(frame):
                return None
            selectors = ("#idNumber",)
            if details:
                selectors += (
                    "#name",
                    '#ng-view input[name="mobile"]',
                    "#nation",
                    "#householdType",
                )
            if all(self._enabled_visible(frame.locator(selector)) for selector in selectors):
                return True
            return None

        try:
            self.waiter.first(
                [WaitCondition("采集表单可操作且无遮罩", ready, stable_for_ms=500)],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待采集表单就绪",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "人员基础信息采集表单没有加载完成", details=str(exc)
            ) from exc

    def _wait_for_idle(self, frame: Frame) -> None:
        try:
            self.waiter.first(
                [WaitCondition("页面加载遮罩消失", lambda: None if self._loading_visible(frame) else True, stable_for_ms=500)],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待采集页面加载完成",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "采集页面加载遮罩长时间未消失", details=str(exc)
            ) from exc

    def _fill_and_verify(self, locator: Locator, value: str, label: str) -> None:
        locator.wait_for(state="visible", timeout=self.settings.browser.action_timeout_ms)
        self.pacer.perform(lambda: locator.fill(value))
        if locator.input_value().strip() != value:
            raise WebsiteStructureChangedError(f"{label}填写后未在页面中生效")

    def _select_household(self, select: Locator, requested: str) -> str:
        return self._select_option(
            select,
            requested,
            field_name="户籍性质",
            reason_code="HOUSEHOLD_TYPE_NOT_FOUND",
        )

    def _select_option(
        self,
        select: Locator,
        requested: str,
        *,
        field_name: str,
        reason_code: str,
    ) -> str:
        normalized = requested.strip().removeprefix("string:")
        options = select.locator("option")
        for index in range(options.count()):
            option = options.nth(index)
            value = (option.get_attribute("value") or "").strip()
            label = option.inner_text().strip()
            if normalized not in {value.removeprefix("string:"), label}:
                continue
            self.pacer.perform(lambda: select.select_option(value=value))
            if select.input_value() != value:
                raise WebsiteStructureChangedError(
                    f"{field_name}选择后未在页面中生效"
                )
            return label
        raise PersonInformationRowError(
            f"智慧人社页面中没有{field_name}：{requested}",
            reason_code=reason_code,
        )

    @staticmethod
    def _validate_address_depth(
        household_label: str,
        address: tuple[str, ...],
    ) -> int:
        expected = address_level_for_household(household_label)
        actual = len(address)
        if expected == 0 and actual:
            raise PersonInformationRowError(
                f"户籍性质“{household_label}”无需填写户籍地行政区",
                reason_code="ADDRESS_NOT_REQUIRED",
            )
        if expected and actual != expected:
            region = "本省" if expected == 5 else "外省"
            raise PersonInformationRowError(
                f"户籍性质“{household_label}”属于{region}，户籍地行政区应填写 {expected} 级，实际为 {actual} 级",
                reason_code="ADDRESS_LEVEL_MISMATCH",
            )
        return expected

    def _select_address(self, frame: Frame, address: tuple[str, ...]) -> None:
        # This is the recorded address textbox. Verify opening the actual
        # address picker before selecting anything so a changed form fails safe.
        address_input = frame.get_by_role("textbox").nth(5)
        self.pacer.perform(address_input.click)
        picker = frame.locator(_PICKER)
        picker.wait_for(state="visible", timeout=self.settings.browser.action_timeout_ms)
        selected: list[str] = []
        for level, part in enumerate(address):
            option = self._wait_for_address_option(
                picker,
                part,
                level=level,
                selected=tuple(selected),
            )
            self.pacer.perform(option.click)
            selected.append(part)
            has_next = self._wait_for_address_step(frame, picker, level)
            more_input = level + 1 < len(address)
            if more_input and not has_next:
                remaining = " / ".join(address[level + 1 :])
                raise PersonInformationRowError(
                    f"智慧人社户籍区划在“{' / '.join(selected)}”处已无下一级，无法继续选择：{remaining}",
                    reason_code="ADDRESS_LEVEL_ENDED",
                )
            if not more_input and has_next:
                raise PersonInformationRowError(
                    f"智慧人社户籍区划在“{' / '.join(selected)}”后仍有下一级，导入地址不完整",
                    reason_code="ADDRESS_LEVEL_INCOMPLETE",
                )
        self._confirm_address(picker, address_input, address)

    def _wait_for_address_option(
        self,
        picker: Locator,
        part: str,
        *,
        level: int,
        selected: tuple[str, ...],
    ) -> Locator:
        def visible_option() -> Locator | None:
            if not self._visible(picker):
                return None
            columns = self._visible_address_columns(picker)
            if len(columns) <= level:
                return None
            return self._last_visible(columns[level].get_by_text(part, exact=True))

        try:
            return self.waiter.first(
                [WaitCondition(f"户籍地址选项 {part}", visible_option, transient_exceptions=(PlaywrightError,))],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description=f"等待户籍地址选项 {part}",
            ).value
        except SmartWaitTimeoutError as exc:
            parent = " / ".join(selected) or "根节点"
            raise PersonInformationRowError(
                f"智慧人社户籍区划第 {level + 1} 级（{parent}）没有找到“{part}”",
                reason_code="ADDRESS_NOT_FOUND",
                details=str(exc),
            ) from exc

    def _wait_for_address_step(
        self,
        frame: Frame,
        picker: Locator,
        level: int,
    ) -> bool:
        component = self._address_component(picker)
        confirm = component.locator("button.address-submit")

        def next_level() -> bool | None:
            self._raise_on_feedback(frame)
            return True if len(self._visible_address_columns(picker)) > level + 1 else None

        def leaf_ready() -> bool | None:
            self._raise_on_feedback(frame)
            try:
                if confirm.count() == 1 and confirm.is_visible() and confirm.is_enabled():
                    return False
            except PlaywrightError:
                pass
            return None

        try:
            result = self.waiter.first(
                [
                    WaitCondition("户籍区划出现下一级", next_level, stable_for_ms=100),
                    WaitCondition("户籍区划当前节点为末级", leaf_ready, stable_for_ms=400),
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="判断户籍区划是否存在下一级",
            )
            return bool(result.value)
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "选择户籍区划后，页面没有给出下一级或末级状态",
                details=str(exc),
            ) from exc

    def _confirm_address(
        self,
        picker: Locator,
        address_input: Locator,
        address: tuple[str, ...],
    ) -> None:
        # The site's girder/ui/selectState/stateCodeView.html template places
        # the picker and button.address-submit under .girder-select-address.
        # A global dialog/button (or business submit) is never eligible.
        component = self._address_component(picker)
        confirms = component.locator("button.address-submit")
        visible_confirms = [
            confirms.nth(index)
            for index in range(confirms.count())
            if self._visible(confirms.nth(index))
        ]
        if not self._visible(picker) or len(visible_confirms) != 1:
            raise WebsiteStructureChangedError("无法在户籍地址控件内唯一定位确定按钮")
        self.pacer.perform(visible_confirms[0].click)

        def address_written_back() -> bool | None:
            try:
                value = address_input.input_value().strip()
            except PlaywrightError:
                return None
            return True if value and all(part in value for part in address) else None

        try:
            self.waiter.first(
                [
                    WaitCondition(
                        "户籍地址已写回表单",
                        address_written_back,
                        stable_for_ms=300,
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待户籍地址确认",
            )
        except SmartWaitTimeoutError as exc:
            raise PersonInformationRowError(
                "点击户籍地址确定后，地址没有写回当前人员表单",
                reason_code="ADDRESS_CONFIRM_FAILED",
                details=str(exc),
            ) from exc

    def _verify_fields(
        self,
        frame: Frame,
        item: PersonInformationItem,
        *,
        address_depth: int,
    ) -> None:
        expected = {
            "#idNumber": item.identity_number,
            "#name": item.name,
            '#ng-view input[name="mobile"]': item.mobile,
        }
        for selector, value in expected.items():
            if frame.locator(selector).input_value().strip() != value:
                raise WebsiteStructureChangedError(f"采集表单回读不一致：{selector}")
        self._verify_selected_option(frame.locator("#nation"), item.nation, "民族")
        household = frame.locator("#householdType").input_value().strip().removeprefix("string:")
        requested = item.household_type.strip().removeprefix("string:")
        if household != requested:
            options = frame.locator("#householdType option:checked")
            if not (options.count() == 1 and options.first.inner_text().strip() == requested):
                raise WebsiteStructureChangedError("户籍性质确认后没有在页面中生效")
        if address_depth:
            address_input = frame.get_by_role("textbox").nth(5)
            selected_address = address_input.input_value()
            if not all(part in selected_address for part in item.address):
                raise WebsiteStructureChangedError(
                    "户籍地址路径确认后没有在输入框中完整生效"
                )

    @staticmethod
    def _verify_selected_option(select: Locator, requested: str, label: str) -> None:
        normalized = requested.strip().removeprefix("string:")
        actual = select.input_value().strip().removeprefix("string:")
        checked = select.locator("option:checked")
        checked_label = (
            checked.first.inner_text().strip() if checked.count() > 0 else ""
        )
        if normalized not in {actual, checked_label}:
            raise WebsiteStructureChangedError(f"{label}确认后没有在页面中生效")

    def _raise_on_feedback(self, frame: Frame) -> None:
        messages = frame.locator(".modal-content")
        for index in range(messages.count() - 1, -1, -1):
            dialog = messages.nth(index)
            if not self._visible(dialog):
                continue
            body = dialog.locator(".modal-body")
            if self._visible(body):
                text = " ".join(body.inner_text().split())
            else:
                text = " ".join(dialog.inner_text().split())
            self._close_feedback_dialog(dialog)
            if any(
                token in text
                for token in ("未找到", "不存在", "未查询到", "无此人员")
            ):
                raise EmployeeNotFoundError(f"人员查询未找到：{text}")
            raise PersonInformationRowError(
                f"智慧人社页面提示：{text}",
                reason_code="BUSINESS_MESSAGE",
            )

    def _close_feedback_dialog(self, dialog: Locator) -> None:
        buttons = dialog.locator(
            'button[data-ng-click="modalOptions.ok();"], button.btn-success'
        )
        button = self._last_visible(buttons)
        if button is None:
            return
        try:
            handle = dialog.element_handle()
            self.pacer.perform(button.click)
            if handle is None:
                return

            def dialog_closed() -> bool | None:
                try:
                    return True if not handle.is_visible() else None
                except PlaywrightError:
                    return True

            self.waiter.first(
                [
                    WaitCondition(
                        "问题提示弹窗已关闭",
                        dialog_closed,
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="关闭问题提示弹窗",
            )
        except (PlaywrightError, SmartWaitTimeoutError) as exc:
            _LOGGER.warning("采集：读取到问题提示，但关闭弹窗失败：%s", exc)

    @classmethod
    def _visible_address_columns(cls, picker: Locator) -> list[Locator]:
        columns = picker.locator(":scope > ul > li")
        return [
            columns.nth(index)
            for index in range(columns.count())
            if cls._visible(columns.nth(index))
        ]

    @staticmethod
    def _address_component(picker: Locator) -> Locator:
        return picker.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' girder-select-address ')][1]"
        )

    def _loading_visible(self, frame: Frame) -> bool:
        masks = frame.locator(_LOADING)
        return any(self._visible(masks.nth(i)) for i in range(masks.count()))

    def _feedback_visible(self, frame: Frame) -> bool:
        dialogs = frame.locator(".modal-content")
        return any(self._visible(dialogs.nth(i)) for i in range(dialogs.count()))

    def _progress(self, message: str) -> None:
        _LOGGER.info(message)
        if self.progress_callback is not None:
            self.progress_callback(message)

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
                option = locators.nth(index)
                if cls._visible(option):
                    return option
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
