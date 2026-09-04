from __future__ import annotations

from collections.abc import Callable
import logging
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from playwright.sync_api import (
    Error as PlaywrightError,
    Frame,
    Locator,
    Page,
    Response,
)

from ehrm.browser.smart_wait import SmartWait, SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import (
    EmployeeNotFoundError,
    QueryResultTimeoutError,
    TaskCancelledError,
    WebsiteStructureChangedError,
)
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_termination.models import (
    EmploymentTerminationItem,
    EmploymentTerminationReason,
)


_LOGGER = logging.getLogger("ehrm")


class _ResponseMonitor:
    """Collects action responses from the main page and every nested iframe."""

    def __init__(
        self,
        page: Page,
        expected_host: str,
        expected_path: str,
        waiter: SmartWait,
    ) -> None:
        self.page = page
        self.expected_host = expected_host.casefold()
        self.expected_path = expected_path
        self.waiter = waiter
        self.responses: list[Response] = []
        page.on("response", self._capture)

    def _capture(self, response: Response) -> None:
        try:
            request = response.request
            if request.resource_type not in {"xhr", "fetch"}:
                return
            if urlsplit(response.url).netloc.casefold() != self.expected_host:
                return
            self.responses.append(response)
        except (AttributeError, ValueError):
            return

    def mark(self) -> int:
        return len(self.responses)

    def wait_for_action_response(
        self,
        marker: int,
        *,
        preferred_value: str,
        timeout_ms: int,
    ) -> Response:
        def matching_response() -> Response | None:
            for response in self.responses[marker:]:
                if urlsplit(response.url).path != self.expected_path:
                    continue
                if self._request_contains(response, preferred_value):
                    return response
            return None

        try:
            return self.waiter.first(
                [WaitCondition("当前人员查询接口响应", matching_response)],
                timeout_ms=timeout_ms,
                description="等待人员查询接口",
            ).value
        except SmartWaitTimeoutError as exc:
            raise QueryResultTimeoutError(
                "人员查询接口没有在规定时间内返回",
                details=(
                    f"期望路径={self.expected_path}；"
                    "请求必须包含当前身份证号；"
                    f"{exc}"
                ),
            ) from exc

    @staticmethod
    def _request_contains(response: Response, value: str) -> bool:
        try:
            request = response.request
            source = f"{request.url}\n{request.post_data or ''}"
            return value.casefold() in source.casefold()
        except (AttributeError, PlaywrightError):
            return False


class EmploymentTerminationPage:
    """Prepares the Nanjing termination form without submitting it."""

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
        self.contract = settings.employment_termination
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self.waiter = SmartWait(
            page.wait_for_timeout,
            poll_interval_ms=100,
            cancel_check=cancel_check,
            cancelled_error=lambda: TaskCancelledError(
                "用户在退保数据录入阶段停止任务"
            ),
        )
        expected_host = urlsplit(settings.site.login_url).netloc
        self.responses = _ResponseMonitor(
            page,
            expected_host,
            self.contract.person_query_path,
            self.waiter,
        )

    def open(self) -> Frame:
        self._raise_if_cancelled()
        home_url = urljoin(self.settings.site.login_url, self.contract.home_path)
        self._progress("退保：正在进入智慧人社大厅")
        self.page.goto(home_url, wait_until="domcontentloaded")
        # The hall may open a mandatory region chooser on first entry. Its
        # backdrop is a modal layer, not a loading state, so handle it before
        # waiting for ordinary loading indicators.
        self._ensure_nanjing()
        self._wait_for_loading_to_finish()
        self._progress("退保：南京地区校验通过，正在打开退工停保登记")
        try:
            middle = self.page.frame_locator(self.contract.middle_frame)
            menu = middle.get_by_text(self.contract.menu_text, exact=True)
            menu.wait_for(
                state="visible",
                timeout=self.settings.browser.action_timeout_ms,
            )
            menu.click()
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                "无法打开用人单位退工停保登记",
                details=str(exc),
            ) from exc
        frame = self._wait_for_business_frame()
        self._dismiss_entry_notice(frame)
        return frame

    def fill_item(self, frame: Frame, item: EmploymentTerminationItem) -> None:
        self._raise_if_cancelled()
        search = frame.locator(self.contract.person_search).get_by_role("textbox").first
        form = frame.locator(self.contract.person_form)
        query_button = form.get_by_role("button").first
        try:
            search.wait_for(
                state="visible",
                timeout=self.settings.browser.action_timeout_ms,
            )
            search.fill(item.identity_number)
            if search.input_value().strip().upper() != item.identity_number:
                raise WebsiteStructureChangedError("身份证号没有正确写入人员查询框")

            marker = self.responses.mark()
            query_button.click()
            response = self.responses.wait_for_action_response(
                marker,
                preferred_value=item.identity_number,
                timeout_ms=self.contract.response_timeout_ms,
            )
            self._validate_response(response, item=item)
            self._wait_for_loading_to_finish()
            self._wait_for_person_form_ready(frame)
            self._select_reason(frame, item.termination_reason)
            self._wait_for_loading_to_finish()
        except (
            EmployeeNotFoundError,
            QueryResultTimeoutError,
            TaskCancelledError,
            WebsiteStructureChangedError,
        ):
            raise
        except (PlaywrightError, ValueError) as exc:
            raise WebsiteStructureChangedError(
                "无法完成人员查询或退工原因录入",
                details=str(exc),
            ) from exc

        source = f"第 {item.source_index} 行" if item.source_index > 0 else "当前人员"
        self._progress(f"退保：{source}身份证号和退工原因已录入")

    def _ensure_nanjing(self) -> None:
        option_selector = self.contract.region_option_template.replace(
            "{city_code}", self.contract.city_code
        ).replace("{city_name}", self.contract.city_name)
        options = self.page.locator(option_selector)
        switch = self.page.locator(self.contract.region_switch).first

        def selected_state() -> dict[str, str] | None:
            state = self._read_region_state()
            return state if self._region_matches(state) else None

        def visible_option() -> Locator | None:
            return self._first_visible(options)

        def actionable_switch() -> Locator | None:
            return switch if self._actionable(switch) else None

        try:
            state = self.waiter.first(
                [
                    WaitCondition("南京地区已生效", selected_state),
                    WaitCondition(
                        "地区弹窗中的南京选项",
                        visible_option,
                        transient_exceptions=(PlaywrightError,),
                    ),
                    WaitCondition(
                        "可操作的地区切换入口",
                        actionable_switch,
                        transient_exceptions=(PlaywrightError,),
                    ),
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="识别智慧人社办事地区状态",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                f"无法识别或切换到{self.contract.city_name}地区",
                details=str(exc),
            ) from exc

        if state.condition == "南京地区已生效":
            current = state.value
            _LOGGER.info(
                "退保地区校验通过 areaCode=%s cityname=%s",
                current.get("areaCode"),
                current.get("cityname"),
            )
            return
        if state.condition == "可操作的地区切换入口":
            try:
                state.value.click()
            except PlaywrightError as exc:
                raise WebsiteStructureChangedError(
                    "无法打开办事地区选择窗口",
                    details=str(exc),
                ) from exc
            try:
                option = self.waiter.first(
                    [
                        WaitCondition(
                            "地区弹窗中的南京选项",
                            visible_option,
                            transient_exceptions=(PlaywrightError,),
                        )
                    ],
                    timeout_ms=self.settings.browser.action_timeout_ms,
                    description="等待办事地区选择窗口",
                ).value
            except SmartWaitTimeoutError as exc:
                raise WebsiteStructureChangedError(
                    f"办事地区窗口中没有找到{self.contract.city_name}",
                    details=str(exc),
                ) from exc
        else:
            option = state.value

        self._progress(
            f"退保：检测到办事地区选择窗口，正在选择{self.contract.city_name}"
        )
        try:
            option.click()
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"无法在办事地区选择窗口中选择{self.contract.city_name}",
                details=str(exc),
            ) from exc
        self._wait_for_nanjing_state()

    def _wait_for_nanjing_state(self) -> None:
        def selected_state() -> dict[str, str] | None:
            state = self._read_region_state()
            return state if self._region_matches(state) else None

        try:
            result = self.waiter.first(
                [WaitCondition("南京地区已生效", selected_state)],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description=f"确认{self.contract.city_name}地区状态",
            )
        except SmartWaitTimeoutError as exc:
            actual = self._read_region_state()
            raise WebsiteStructureChangedError(
                f"选择地区后未确认到{self.contract.city_name}",
                details=(
                    f"期望 areaCode={self.contract.city_code}、"
                    f"cityname={self.contract.city_name}，实际={actual}；{exc}"
                ),
            ) from exc
        state = result.value
        _LOGGER.info(
            "退保地区已切换 areaCode=%s cityname=%s",
            state.get("areaCode"),
            state.get("cityname"),
        )

    def _read_region_state(self) -> dict[str, str]:
        try:
            value = self.page.evaluate(
                """() => {
                    const raw = localStorage.getItem('vuex');
                    if (!raw) return {};
                    try {
                        const value = JSON.parse(raw);
                        const home = value && value.home;
                        return home && typeof home === 'object' ? home : {};
                    } catch (_) {
                        return {};
                    }
                }"""
            )
        except PlaywrightError:
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            "areaCode": str(value.get("areaCode") or "").strip(),
            "cityname": str(value.get("cityname") or "").strip(),
        }

    def _region_matches(self, state: dict[str, str]) -> bool:
        return (
            state.get("areaCode") == self.contract.city_code
            and state.get("cityname") == self.contract.city_name
        )

    def _wait_for_business_frame(self) -> Frame:
        def recorded_frame_chain() -> Frame | None:
            """Resolve the exact two-level iframe chain emitted by codegen.

            layui appends a changing number to the outer iframe name, and can
            leave an older layer attached to the page.  Work backwards through
            the visible layer elements so the newest visible business window
            wins.
            """
            outer_iframes = self.page.locator(self.contract.outer_business_frame)
            for outer_index in range(outer_iframes.count() - 1, -1, -1):
                outer_iframe = outer_iframes.nth(outer_index)
                if not self._visible(outer_iframe):
                    continue
                outer_frame = self._content_frame(outer_iframe)
                if outer_frame is None:
                    continue
                business_iframes = outer_frame.locator(self.contract.business_frame)
                for business_index in range(
                    business_iframes.count() - 1, -1, -1
                ):
                    business_iframe = business_iframes.nth(business_index)
                    if not self._visible(business_iframe):
                        continue
                    business_frame = self._content_frame(business_iframe)
                    if business_frame is not None:
                        return business_frame
            return None

        def available_frame() -> Frame | None:
            try:
                return recorded_frame_chain()
            except PlaywrightError:
                return None

        try:
            return self.waiter.first(
                [WaitCondition("退工停保业务 iframe", available_frame)],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待退工停保业务页面",
            ).value
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "退工停保业务 iframe 没有加载完成",
                details=(
                    "期望层级=当前可见的 layui-layer iframe > #busiIframe；"
                    f"{exc}"
                ),
            ) from exc

    def _dismiss_entry_notice(self, frame: Frame) -> None:
        search = frame.locator(self.contract.person_search).get_by_role("textbox").first
        confirm = frame.get_by_role("button", name="确定", exact=True)
        notice_confirmed = False
        entry_confirmed = False
        deadline = (
            time.monotonic() + self.settings.browser.action_timeout_ms / 1000
        )

        def ready_search() -> Locator | None:
            return search if self._actionable(search) else None

        def visible_notice_dialog() -> Locator | None:
            # Use the actual Angular UI Bootstrap DOM supplied by the site.
            # Its inferred dialog role is not consistently available while
            # Angular is attaching the modal to the document.
            dialogs = frame.locator(self.contract.entry_notice_dialog).filter(
                has_text=self.contract.entry_notice_text
            )
            return self._first_visible(dialogs)

        def actionable_notice_button() -> Locator | None:
            if notice_confirmed:
                return None
            dialog = visible_notice_dialog()
            if dialog is None:
                return None
            return self._last_visible(
                dialog.locator(self.contract.entry_notice_confirm)
            )

        def actionable_confirm() -> Locator | None:
            if entry_confirmed:
                return None
            try:
                for index in range(confirm.count()):
                    candidate = confirm.nth(index)
                    if self._actionable(candidate):
                        return candidate
            except PlaywrightError:
                return None
            return None

        while True:
            remaining_ms = round((deadline - time.monotonic()) * 1000)
            if remaining_ms < 1:
                raise WebsiteStructureChangedError(
                    "退工停保页面已打开，但人员查询框没有加载完成",
                    details="入口提示处理完成前已达到操作超时上限",
                )
            try:
                state = self.waiter.first(
                    [
                        WaitCondition(
                            "停保时间提示确定按钮",
                            actionable_notice_button,
                        ),
                        WaitCondition("业务入口确认", actionable_confirm),
                        # Check both recorded confirmations before the search
                        # field. Controls underneath an iframe modal can exist
                        # in the DOM before the modal has actually disappeared.
                        WaitCondition(
                            "人员查询框稳定可操作",
                            ready_search,
                            stable_for_ms=self.contract.stable_delay_ms,
                        ),
                    ],
                    timeout_ms=remaining_ms,
                    description="等待退工停保查询表单",
                )
            except SmartWaitTimeoutError as exc:
                raise WebsiteStructureChangedError(
                    "退工停保页面已打开，但人员查询框没有加载完成",
                    details=str(exc),
                ) from exc

            if state.condition == "人员查询框稳定可操作":
                return
            if state.condition == "停保时间提示确定按钮":
                self._progress("退保：检测到停保时间提示，正在确认")
                click_started_at = time.monotonic()
                try:
                    # The locator is already constrained to the visible modal,
                    # its exact text and Angular OK handler.  A forced click
                    # avoids Playwright waiting on the page's long-lived modal
                    # animation/overlay while retaining a narrow, safe target.
                    state.value.click(force=True, timeout=remaining_ms)
                except PlaywrightError as exc:
                    raise WebsiteStructureChangedError(
                        "无法关闭停保时间提示",
                        details=str(exc),
                    ) from exc
                notice_confirmed = True
                remaining_ms = round((deadline - time.monotonic()) * 1000)
                try:
                    self.waiter.first(
                        [
                            WaitCondition(
                                "停保时间提示已关闭",
                                lambda: (
                                    True
                                    if visible_notice_dialog() is None
                                    else None
                                ),
                                transient_exceptions=(PlaywrightError,),
                            )
                        ],
                        timeout_ms=max(1, remaining_ms),
                        description="确认停保时间提示关闭状态",
                    )
                except SmartWaitTimeoutError as exc:
                    raise WebsiteStructureChangedError(
                        "点击确定后停保时间提示仍未关闭",
                        details=str(exc),
                    ) from exc
                _LOGGER.info(
                    "退保：停保时间提示已确认 click_elapsed=%.3fs",
                    time.monotonic() - click_started_at,
                )
                continue

            # This exact entry confirmation is only considered while the
            # person-search field is not actionable. The final submission is
            # therefore never reached or clicked by this preparation flow.
            self._progress("退保：检测到业务入口确认，正在进入人员查询表单")
            click_started_at = time.monotonic()
            try:
                state.value.click(timeout=remaining_ms)
            except PlaywrightError as exc:
                raise WebsiteStructureChangedError(
                    "无法确认进入退工停保查询表单",
                    details=str(exc),
                ) from exc
            entry_confirmed = True
            _LOGGER.info(
                "退保：业务入口确认已完成 click_elapsed=%.3fs",
                time.monotonic() - click_started_at,
            )

    def _select_reason(
        self,
        frame: Frame,
        requested: EmploymentTerminationReason | str,
    ) -> None:
        reason = EmploymentTerminationReason.parse(requested)
        requested_key = reason.value
        comboboxes = frame.locator(self.contract.reason_combobox)
        visible_boxes = [
            comboboxes.nth(index)
            for index in range(comboboxes.count())
            if self._visible(comboboxes.nth(index))
        ]
        for combobox in visible_boxes:
            options = combobox.locator("option")
            for option_index in range(options.count()):
                option = options.nth(option_index)
                value = str(option.get_attribute("value") or "").strip()
                label = re.sub(r"\s+", "", option.inner_text())
                if requested_key not in {
                    _normalized_reason(value),
                    _normalized_reason(label),
                }:
                    continue
                combobox.select_option(value=value)
                actual = str(combobox.input_value() or "").strip()
                if _normalized_reason(actual) != _normalized_reason(value):
                    raise WebsiteStructureChangedError(
                        "退工原因选择后没有在页面中生效"
                    )
                _LOGGER.info(
                    "退工原因已选择 code=%s label=%s",
                    _normalized_reason(value),
                    label,
                )
                return

        # Defensive support for a future custom combobox implementation.
        for combobox in visible_boxes:
            try:
                combobox.click()
                option = frame.get_by_role("option", name=requested, exact=True).last
                if self._visible(option):
                    option.click()
                    return
            except PlaywrightError:
                continue
        available = self._available_reasons(visible_boxes)
        raise WebsiteStructureChangedError(
            f"页面中没有找到退工原因：{reason.display_name}({reason.value})",
            details=(
                "可用选项：" + "、".join(available)
                if available
                else "页面中没有可读取的退工原因选项"
            ),
        )

    def _wait_for_person_form_ready(self, frame: Frame) -> None:
        comboboxes = frame.locator(self.contract.reason_combobox)

        def ready_combobox() -> Locator | None:
            for index in range(comboboxes.count()):
                candidate = comboboxes.nth(index)
                if not self._visible(candidate):
                    continue
                if candidate.locator("option").count() > 0:
                    return candidate
            return None

        try:
            self.waiter.first(
                [
                    WaitCondition(
                        "退工原因选项已渲染",
                        ready_combobox,
                        transient_exceptions=(PlaywrightError,),
                    )
                ],
                timeout_ms=self.settings.browser.action_timeout_ms,
                description="等待人员查询结果写入退保表单",
            )
        except SmartWaitTimeoutError as exc:
            raise WebsiteStructureChangedError(
                "人员查询接口成功，但退工表单没有完成渲染",
                details=str(exc),
            ) from exc

    @staticmethod
    def _available_reasons(comboboxes: list[Locator]) -> list[str]:
        values: list[str] = []
        for combobox in comboboxes:
            options = combobox.locator("option")
            for index in range(options.count()):
                option = options.nth(index)
                code = _normalized_reason(option.get_attribute("value") or "")
                label = re.sub(r"\s+", "", option.inner_text())
                if not code and not label:
                    continue
                display = f"{label}({code})" if label and code else label or code
                if display not in values:
                    values.append(display)
        return values

    def _validate_response(
        self,
        response: Response,
        *,
        item: EmploymentTerminationItem | None = None,
    ) -> None:
        path = urlunsplit((*urlsplit(response.url)[:3], "", ""))
        _LOGGER.info(
            "退保人员查询接口响应 method=%s status=%s url=%s",
            response.request.method,
            response.status,
            path,
        )
        payload: object | None = None
        try:
            payload = response.json()
        except (PlaywrightError, ValueError):
            pass

        message = _response_message(payload)
        if response.status == 400:
            source = (
                f"第 {item.source_index} 行"
                if item is not None and item.source_index > 0
                else "当前人员"
            )
            reason = message or "未查询到符合条件的参保人员"
            _LOGGER.info(
                "退保人员查询无结果 status=%s message=%s",
                response.status,
                reason,
            )
            raise EmployeeNotFoundError(
                f"{source}未查询到可办理退保的人员：{reason}",
                details=path,
            )
        if response.status >= 400:
            raise WebsiteStructureChangedError(
                (
                    f"人员查询接口返回 HTTP {response.status}：{message}"
                    if message
                    else f"人员查询接口返回 HTTP {response.status}"
                ),
                details=path,
            )
        if payload is None:
            return
        message = _response_error_message(payload)
        if message:
            if _is_employee_not_found_message(message):
                source = (
                    f"第 {item.source_index} 行"
                    if item is not None and item.source_index > 0
                    else "当前人员"
                )
                raise EmployeeNotFoundError(
                    f"{source}未查询到可办理退保的人员：{message}",
                    details=path,
                )
            raise WebsiteStructureChangedError(
                f"人员查询接口返回失败：{message}",
                details=path,
            )

    def _wait_for_loading_to_finish(self) -> None:
        selector = self.contract.loading_indicator
        if not selector:
            return

        def loading_cleared() -> bool | None:
            for frame in self.page.frames:
                try:
                    masks = frame.locator(selector)
                    if any(
                        self._visible(masks.nth(index))
                        for index in range(masks.count())
                    ):
                        return None
                except PlaywrightError:
                    continue
            return True

        try:
            self.waiter.first(
                [
                    WaitCondition(
                        "所有加载动画已消失",
                        loading_cleared,
                        stable_for_ms=self.contract.stable_delay_ms,
                    )
                ],
                timeout_ms=self.contract.loading_timeout_ms,
                description="等待退工停保页面加载完成",
            )
        except SmartWaitTimeoutError as exc:
            raise QueryResultTimeoutError(
                "等待退工停保页面加载遮罩消失超时",
                details=str(exc),
            ) from exc

    def _raise_if_cancelled(self) -> None:
        if self.cancel_check is not None and self.cancel_check():
            raise TaskCancelledError("用户在退保数据录入阶段停止任务")

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
    def _first_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count()):
                candidate = locators.nth(index)
                if cls._visible(candidate):
                    return candidate
        except PlaywrightError:
            return None
        return None

    def _last_actionable(self, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count() - 1, -1, -1):
                candidate = locators.nth(index)
                if self._actionable(candidate):
                    return candidate
        except PlaywrightError:
            return None
        return None

    @classmethod
    def _last_visible(cls, locators: Locator) -> Locator | None:
        try:
            for index in range(locators.count() - 1, -1, -1):
                candidate = locators.nth(index)
                if cls._visible(candidate):
                    return candidate
        except PlaywrightError:
            return None
        return None

    @staticmethod
    def _content_frame(iframe: Locator) -> Frame | None:
        try:
            handle = iframe.element_handle()
            return handle.content_frame() if handle is not None else None
        except PlaywrightError:
            return None

    @classmethod
    def _actionable(cls, locator: Locator) -> bool:
        if not cls._visible(locator):
            return False
        try:
            return bool(
                locator.evaluate(
                    """element => {
                        if (element.disabled) return false;
                        const rect = element.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) return false;
                        const x = rect.left + rect.width / 2;
                        const y = rect.top + rect.height / 2;
                        const hit = document.elementFromPoint(x, y);
                        return hit === element || element.contains(hit);
                    }"""
                )
            )
        except PlaywrightError:
            return False


def _normalized_reason(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value)).casefold()
    return normalized.removeprefix("string:")


def _response_error_message(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("message") or first.get("msg") or first).strip()
        return str(first).strip()
    message = str(payload.get("msg") or payload.get("message") or "").strip()
    appcode = payload.get("appcode")
    if appcode is not None and str(appcode).strip() not in {"", "0"}:
        return message or f"appcode={appcode}"
    if payload.get("success") is False:
        return message or "success=false"
    return ""


def _response_message(payload: object) -> str:
    """Extracts a human-readable message without deciding success or failure."""
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(
                first.get("message")
                or first.get("msg")
                or first.get("errorMessage")
                or first
            ).strip()
        return str(first).strip()
    return str(
        payload.get("msg")
        or payload.get("message")
        or payload.get("errorMessage")
        or payload.get("errMessage")
        or payload.get("error")
        or ""
    ).strip()


def _is_employee_not_found_message(message: str) -> bool:
    normalized = re.sub(r"\s+", "", message).casefold()
    return any(
        marker in normalized
        for marker in (
            "未查询",
            "未找到",
            "不存在",
            "查无",
            "无此人",
            "没有人员",
            "nodata",
            "notfound",
        )
    )
