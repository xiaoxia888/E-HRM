from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, Locator, Page, Response

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.core.exceptions import (
    EhrmError,
    EmployeeNotFoundError,
    QueryResultTimeoutError,
    WebsiteStructureChangedError,
)
from ehrm.core.settings import BrowserInteractionPacingSettings
from ehrm.modules.medical_termination.models import MedicalTerminationItem


_PORTAL_HOST = "wb.njybjyybz.org.cn"
_PORTAL_PATH = "/hsa-local-nj/web/hallUnit/"
_MENU_PATH = "/hsa-pss-cw-local-nj/pss/web/roles/selectCwMenu"
MEDICAL_LOGIN_URL = "https://www.jszwfw.gov.cn/jsjis/front/login.do?uuid=Q5mxXFYhCnUh"
_LOADING = ".el-loading-mask"
_REASON_SELECT = ".el-form-item.is-required .el-select"
_PAYMENT_SELECT = (
    ".el-col.el-col-24 > .el-form-item > "
    ".el-form-item__content > .el-select"
)
_FEEDBACK = (
    ".el-message-box__message",
    ".el-message.el-message--error .el-message__content",
    ".el-alert--error .el-alert__content",
    ".el-form-item__error",
)
_SUCCESS = ".el-message.el-message--success .el-message__content"
_SUCCESS_TEXT = re.compile(r"^提交成功[!！。]?$")


class MedicalSubmissionUncertainError(EhrmError):
    """The submit boundary was crossed; the person must be checked manually."""

    code = "MEDICAL_TERMINATION_RESULT_UNKNOWN"


def is_medical_portal_url(url: str) -> bool:
    """Never use a saved accessToken URL as a navigation template."""
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and (parts.hostname or "").casefold() == _PORTAL_HOST
        and parts.path.startswith(_PORTAL_PATH)
    )


def find_medical_portal_page(pages: Sequence[Page]) -> Page | None:
    for page in reversed(pages):
        try:
            if not page.is_closed() and is_medical_portal_url(page.url):
                return page
        except PlaywrightError:
            continue
    return None


def is_medical_portal_ready(page: Page) -> bool:
    """A portal URL alone may be a stale shell with an expired session."""
    if not is_medical_portal_url(page.url):
        return False
    try:
        return page.get_by_text("单位参停保办理", exact=True).first.is_visible()
    except PlaywrightError:
        return False


def verify_existing_medical_session(page: Page, *, timeout_ms: int = 10_000) -> bool:
    """Reload an open portal and require a successful authenticated menu response."""
    if not is_medical_portal_url(page.url):
        return False

    def is_menu_response(response: Response) -> bool:
        parts = urlsplit(response.url)
        return (
            parts.scheme == "https"
            and (parts.hostname or "").casefold() == _PORTAL_HOST
            and parts.path == _MENU_PATH
            and response.request.method.upper() == "POST"
        )

    try:
        with page.expect_response(is_menu_response, timeout=timeout_ms) as pending:
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        response = pending.value
        if response.status != 200:
            return False
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "0":
            return False
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("success") is not True:
            return False
        page.get_by_text("单位参停保办理", exact=True).first.wait_for(
            state="visible", timeout=timeout_ms
        )
        return is_medical_portal_ready(page)
    except (PlaywrightError, ValueError, TypeError):
        return False


class MedicalTerminationPage:
    """Recorded medical form flow; submit is a single, non-retryable UI click."""

    def __init__(
        self,
        page: Page,
        *,
        timeout_ms: int = 30_000,
        pacing: BrowserInteractionPacingSettings | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if not is_medical_portal_url(page.url):
            raise WebsiteStructureChangedError("当前页面不是南京医保单位大厅")
        self.page = page
        self.timeout_ms = timeout_ms
        self.progress_callback = progress_callback
        self.pacer = (
            BrowserInteractionPacer(pacing, page.wait_for_timeout)
            if pacing is not None else None
        )

    def open(self) -> None:
        if self._query_visible():
            return
        self._progress("医保停保：正在进入单位参停保办理")
        self._perform(self.page.get_by_text("单位参停保办理", exact=True).first.click)
        self._perform(
            self.page.get_by_role("link", name="退工停保登记", exact=True).click
        )
        self.page.get_by_role("button", name="查询").first.wait_for(
            state="visible", timeout=self.timeout_ms
        )
        if not self._query_visible():
            raise WebsiteStructureChangedError("医保退工停保登记查询框未加载完成")

    def prepare_next(self) -> None:
        """Return to a verified, empty form before processing another person."""
        self._progress("医保停保：正在刷新业务页面，准备办理下一人")
        if not verify_existing_medical_session(self.page, timeout_ms=self.timeout_ms):
            raise WebsiteStructureChangedError("医保页面刷新后会话未通过验证，未继续办理下一人")
        self.open()
        identity = self.page.get_by_role("textbox").first
        if identity.input_value().strip():
            raise WebsiteStructureChangedError("医保页面刷新后仍保留上一人证件号码，未继续办理下一人")

    def fill_item(self, item: MedicalTerminationItem) -> None:
        item = item.normalized()
        self.open()
        identity = self.page.get_by_role("textbox").first
        self._perform(lambda: identity.fill(item.identity_number))
        if identity.input_value().strip().upper() != item.identity_number:
            raise WebsiteStructureChangedError("身份证号未正确写入医保人员查询框")

        query_responses: list[Response] = []

        def on_response(response: Response) -> None:
            try:
                request = response.request
                if (
                    request.resource_type in {"xhr", "fetch"}
                    and urlsplit(response.url).hostname == _PORTAL_HOST
                    and item.identity_number in (
                        (request.post_data or "") + request.url
                    )
                ):
                    query_responses.append(response)
            except (AttributeError, PlaywrightError, ValueError):
                return

        self.page.on("response", on_response)
        try:
            self._progress("医保停保：正在查询人员并等待加载结束")
            self._perform(self.page.get_by_role("button", name="查询").first.click)
            self._wait_for_query(item, query_responses)
        finally:
            self.page.remove_listener("response", on_response)

        self._set_date(item.termination_date)
        self._select_option(_REASON_SELECT, item.reason, "停保原因")
        self._select_option(
            _PAYMENT_SELECT,
            "是" if item.pay_current_month else "否",
            "停保当月缴费",
        )
        self._raise_feedback(item)
        self._progress("医保停保：表单已填写，未点击任何提交按钮")

    def submit_item(
        self,
        item: MedicalTerminationItem,
        *,
        before_submit: Callable[[], None] | None = None,
    ) -> str:
        """Submit once and accept only a fresh, explicit success toast.

        The recording's HAR stopped at the portal landing page, so no business
        response contract is available. A timeout or error after clicking is
        therefore *unknown*, never safe to retry automatically.
        """
        item = item.normalized()
        if not self._form_visible():
            raise WebsiteStructureChangedError("医保停保表单未就绪，未点击提交")
        self._raise_feedback(item)
        identity_field = self.page.get_by_role("textbox").first
        if identity_field.input_value().strip().upper() != item.identity_number:
            raise WebsiteStructureChangedError("医保页面证件号码与本次人员不一致，未点击提交")
        date_field = self.page.get_by_role("textbox", name="选择日期").first
        if date_field.input_value().strip() != item.termination_date.isoformat():
            raise WebsiteStructureChangedError("医保停保日期与申请数据不一致，未点击提交")
        for selector, expected, label in (
            (_REASON_SELECT, item.reason, "停保原因"),
            (_PAYMENT_SELECT, "是" if item.pay_current_month else "否", "停保当月缴费"),
        ):
            controls = self.page.locator(selector)
            visible = [controls.nth(index) for index in range(controls.count())
                       if self._visible(controls.nth(index))]
            if len(visible) != 1 or visible[0].locator("input").first.input_value().strip() != expected:
                raise WebsiteStructureChangedError(f"医保{label}与申请数据不一致，未点击提交")
        buttons = self.page.get_by_role("button", name="提交", exact=True)
        visible_buttons = [buttons.nth(index) for index in range(buttons.count())
                           if self._visible(buttons.nth(index))]
        if len(visible_buttons) != 1 or visible_buttons[0].is_disabled():
            raise WebsiteStructureChangedError("医保停保提交按钮未能唯一定位或不可用，未点击提交")
        success = self.page.locator(_SUCCESS)
        try:
            success.first.wait_for(state="hidden", timeout=5_000)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError("页面存在上次提交的成功提示，未点击新提交") from exc

        if before_submit is not None:
            before_submit()
        self._progress("医保停保：正在点击提交；此后结果不明时不会自动重试")
        try:
            visible_buttons[0].click()
            deadline = time.monotonic() + self.timeout_ms / 1000
            while time.monotonic() < deadline:
                errors = self._visible_messages(_FEEDBACK)
                if errors:
                    raise MedicalSubmissionUncertainError(
                        f"医保平台提交后提示：{'；'.join(errors)}；结果待人工核对，请勿重复提交"
                    )
                messages = self._visible_messages((_SUCCESS,))
                if any(_SUCCESS_TEXT.fullmatch(message) for message in messages):
                    self._progress("医保停保：平台显示“提交成功”；最终办结请以医保平台查询为准")
                    return "医保平台显示“提交成功”；最终办理结果请在医保平台查询"
                self.page.wait_for_timeout(100)
        except MedicalSubmissionUncertainError:
            raise
        except PlaywrightError as exc:
            raise MedicalSubmissionUncertainError(
                "医保提交后页面操作异常，结果待人工核对，请勿重复提交"
            ) from exc
        raise MedicalSubmissionUncertainError(
            "医保提交后未观察到明确的“提交成功”提示，结果待人工核对，请勿重复提交"
        )

    def _visible_messages(self, selectors: tuple[str, ...]) -> list[str]:
        messages = []
        for selector in selectors:
            nodes = self.page.locator(selector)
            for index in range(nodes.count()):
                node = nodes.nth(index)
                if self._visible(node):
                    message = " ".join(node.inner_text().split())
                    if message:
                        messages.append(message)
        return messages

    def _wait_for_query(
        self,
        item: MedicalTerminationItem,
        responses: list[Response],
    ) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        saw_loading = False
        clear_since: float | None = None
        while time.monotonic() < deadline:
            self._raise_feedback(item)
            loading = self._any_visible(_LOADING)
            if loading:
                saw_loading = True
                clear_since = None
            elif saw_loading:
                clear_since = clear_since or time.monotonic()
                if time.monotonic() - clear_since >= 0.3:
                    break
            elif responses and self._form_visible():
                # The overlay may have completed between polling intervals.
                # Still require a stable mask-free window before filling.
                clear_since = clear_since or time.monotonic()
                if time.monotonic() - clear_since >= 0.3:
                    break
            self.page.wait_for_timeout(100)
        else:
            raise QueryResultTimeoutError(
                "医保人员查询后页面加载超时",
                details="未观察到加载遮罩结束或当前身份证号对应的查询响应",
            )

        self._raise_feedback(item)
        for response in responses:
            if response.status >= 400:
                raise WebsiteStructureChangedError(
                    f"医保人员查询接口返回 HTTP {response.status}"
                )
        if not self._form_visible():
            raise WebsiteStructureChangedError("医保人员查询结束，但停保表单未就绪")
        self._progress("医保停保：人员查询加载完成，开始填写停保信息")

    def _set_date(self, target: date) -> None:
        field = self.page.get_by_role("textbox", name="选择日期").first
        field.wait_for(state="visible", timeout=self.timeout_ms)
        value = target.isoformat()
        if field.get_attribute("readonly") is None:
            self._perform(lambda: field.fill(value))
            self._perform(lambda: field.press("Tab"))
        else:
            self._perform(field.click)
            panel = self.page.locator(".el-picker-panel:visible").last
            panel.wait_for(state="visible", timeout=self.timeout_ms)
            header = panel.locator(".el-date-picker__header").inner_text()
            year = re.search(r"(\d{4})\s*年", header)
            month = re.search(r"(\d{1,2})\s*月", header)
            if not year or not month or (int(year[1]), int(month[1])) != (
                target.year, target.month
            ):
                raise WebsiteStructureChangedError(
                    "医保停保日期选择器未显示目标年月；已停止，避免选择错误日期"
                )
            day = panel.locator(
                ".el-date-table td.available:not(.prev-month):not(.next-month)"
            ).filter(has_text=re.compile(rf"^\s*{target.day}\s*$"))
            if day.count() != 1:
                raise WebsiteStructureChangedError("医保停保日期未能唯一定位")
            self._perform(day.click)
        if field.input_value().strip() != value:
            raise WebsiteStructureChangedError(
                f"医保停保日期未正确写入，期望 {value}"
            )

    def _select_option(self, selector: str, label: str, field_name: str) -> None:
        controls = self.page.locator(selector)
        visible = [controls.nth(index) for index in range(controls.count())
                   if self._visible(controls.nth(index))]
        if len(visible) != 1:
            raise WebsiteStructureChangedError(
                f"无法唯一定位医保{field_name}下拉框（可见数量 {len(visible)}）"
            )
        control = visible[0]
        self._perform(control.click)
        # Element UI mounts the popper asynchronously and may retain other
        # hidden dropdowns in the DOM. The recording used the visible list
        # item, not a snapshot of all .el-select-dropdown__item nodes.
        options = self.page.get_by_role("listitem").filter(
            has_text=re.compile(rf"^\s*{re.escape(label)}\s*$")
        )
        try:
            options.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"医保{field_name}下拉框未出现“{label}”选项"
            ) from exc
        if options.count() != 1:
            raise WebsiteStructureChangedError(
                f"医保{field_name}选项未能唯一定位：{label}"
                f"（可见匹配数量 {options.count()}）"
            )
        self._perform(options.first.click)
        actual = control.locator("input").first.input_value().strip()
        if not actual or label not in actual:
            raise WebsiteStructureChangedError(f"医保{field_name}选择后值不一致")

    def _raise_feedback(self, item: MedicalTerminationItem) -> None:
        for selector in _FEEDBACK:
            nodes = self.page.locator(selector)
            for index in range(nodes.count()):
                node = nodes.nth(index)
                if not self._visible(node):
                    continue
                message = " ".join(node.inner_text().split())
                if not message:
                    continue
                if "不是本单位人员" in message or "未查询到" in message:
                    raise EmployeeNotFoundError(
                        f"第 {item.source_index} 行医保人员不可办理停保：{message}"
                    )
                raise WebsiteStructureChangedError(f"医保停保页面提示错误：{message}")

    def _form_visible(self) -> bool:
        return (
            self._any_visible('input[placeholder="选择日期"]')
            and self._any_visible(_REASON_SELECT)
        )

    def _query_visible(self) -> bool:
        try:
            return self.page.get_by_role("button", name="查询").first.is_visible()
        except PlaywrightError:
            return False

    def _any_visible(self, selector: str) -> bool:
        nodes = self.page.locator(selector)
        return any(self._visible(nodes.nth(index)) for index in range(nodes.count()))

    @staticmethod
    def _visible(node: Locator) -> bool:
        try:
            return node.is_visible()
        except PlaywrightError:
            return False

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    def _perform(self, action: Callable[[], None]) -> None:
        if self.pacer is None:
            action()
        else:
            self.pacer.perform(action)
