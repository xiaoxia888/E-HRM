"""Observed, single-attempt termination submission (never direct API replay).

The contracts come from the recorded submit flow. In particular, dimissionApply
uses ``ok`` rather than a generic appcode, and complete=false can accompany a
successful view. Network acceptance AND the current success DOM are required.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from playwright.sync_api import Dialog, Error as PlaywrightError, Frame, Locator, Page, Response

from ehrm.browser.smart_wait import SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.core.settings import AppSettings
from ehrm.modules.employment_termination.models import EmploymentTerminationItem
from ehrm.modules.jshrss_business_dialog import (
    BusinessDialogKind,
    close_business_dialog,
    topmost_business_dialog,
)

if TYPE_CHECKING:
    from ehrm.modules.employment_termination.page import EmploymentTerminationPage


class TerminationSubmissionError(EhrmError):
    """A non-retryable submission outcome; unknown must be checked manually."""

    code = "TERMINATION_SUBMISSION_FAILED"

    def __init__(self, message: str, *, outcome: str = "failed") -> None:
        super().__init__(message)
        self.outcome = outcome
        self.code = (
            "TERMINATION_RESULT_UNKNOWN" if outcome == "unknown"
            else "TERMINATION_SUBMISSION_FAILED"
        )


@dataclass(frozen=True, slots=True)
class TerminationSubmissionReceipt:
    application_id: str


class TerminationSubmissionMonitor:
    """Only observes POST responses during this one person's submit attempt."""

    def __init__(self, page: Page, settings: AppSettings, item: EmploymentTerminationItem) -> None:
        self.page = page
        self.contract = settings.employment_termination
        self.item = item.normalized()
        self.host = urlsplit(settings.site.login_url).netloc.casefold()
        self.responses: dict[str, list[Response]] = {path: [] for path in (
            self.contract.submit_save_path,
            self.contract.submit_apply_path,
            self.contract.submit_complete_path,
        )}
        # Keep the callback identity so cleanup does not remove unrelated listeners.
        self._listener = self.capture
        self.page.on("response", self._listener)

    def close(self) -> None:
        self.page.remove_listener("response", self._listener)

    def capture(self, response: Response) -> None:
        url = urlsplit(response.url)
        if (url.netloc.casefold() == self.host
                and url.path in self.responses
                and response.request.method.upper() == "POST"
                and response.request.resource_type in {"xhr", "fetch"}):
            self.responses[url.path].append(response)

    def _json(self, response: Response) -> dict:
        try:
            data = response.json()
        except (ValueError, PlaywrightError) as exc:
            raise TerminationSubmissionError(
                "提交接口响应无法解析，结果待确认；请勿重复提交", outcome="unknown"
            ) from exc
        if not isinstance(data, dict):
            raise TerminationSubmissionError("提交接口响应结构不正确，结果待确认", outcome="unknown")
        return data

    def _payload(self, response: Response) -> dict:
        try:
            payload = json.loads(response.request.post_data or "{}")
            if not isinstance(payload, dict):
                raise ValueError("not an object")
        except (ValueError, PlaywrightError) as exc:
            raise TerminationSubmissionError("无法核对提交人员，结果待确认", outcome="unknown") from exc
        if (str(payload.get("idNumber", "")).upper() != self.item.identity_number
                or str(payload.get("changeReason", "")) != str(self.item.termination_reason)):
            raise TerminationSubmissionError("提交请求的人员或退工原因与当前行不一致，结果待确认", outcome="unknown")
        return payload

    def receipt(self, *, success_visible: bool) -> TerminationSubmissionReceipt | None:
        for responses in self.responses.values():
            if len(responses) > 1:
                raise TerminationSubmissionError("检测到重复提交响应，结果待确认；请勿重复提交", outcome="unknown")
            if responses and not 200 <= responses[0].status < 300:
                # A non-2xx response can still follow a committed operation.
                raise TerminationSubmissionError(
                    f"提交接口 HTTP={responses[0].status}，结果待确认；请勿重复提交", outcome="unknown"
                )
        saved = self.responses[self.contract.submit_save_path]
        if saved:
            self._payload(saved[0])
            # The observed successful save has an empty body. A non-empty
            # response is a different contract, not success merely due to 200.
            if saved[0].text().strip():
                saved_data = self._json(saved[0])
                message = saved_data.get("message") or saved_data.get("errmsg") or "未识别的保存响应"
                raise TerminationSubmissionError(
                    f"人员数据保存返回提示：{message}；结果待确认", outcome="unknown"
                )
        applied = self.responses[self.contract.submit_apply_path]
        if not applied:
            return None
        payload = self._payload(applied[0])
        data = self._json(applied[0])
        if data.get("ok") is False:
            raise TerminationSubmissionError(str(data.get("errmsg") or "退保接口明确拒绝办理"))
        if data.get("ok") is not True:
            raise TerminationSubmissionError("退保接口未返回明确成功状态，结果待确认", outcome="unknown")
        # The recorded placeholder is harmless; a different error message is
        # conflicting evidence even when ok=true and must never be ignored.
        if str(data.get("errmsg") or "").strip() not in {"", "未提供错误信息"}:
            raise TerminationSubmissionError(
                "退保接口成功标志与错误说明矛盾：" + str(data["errmsg"]), outcome="unknown"
            )
        if str(data.get("certificateNumber", "")).upper() != self.item.identity_number:
            raise TerminationSubmissionError("返回人员证件号码与当前行不一致，结果待确认", outcome="unknown")
        application_id = str(payload.get("applyId") or "")
        if not application_id or not data.get("partyId"):
            raise TerminationSubmissionError("退保成功响应缺少申请或人员标识，结果待确认", outcome="unknown")
        if saved and str(self._payload(saved[0]).get("applyId") or "") != application_id:
            raise TerminationSubmissionError("人员保存和退保提交不属于同一申请，结果待确认", outcome="unknown")
        completed = self.responses[self.contract.submit_complete_path]
        if not completed:
            return None
        completion = self._json(completed[0])
        if str(completion.get("appcode")) != "0":
            raise TerminationSubmissionError(
                f"退保接口已接受，但办件收尾异常：{completion.get('msg') or '未明确成功'}；请勿重复提交",
                outcome="unknown",
            )
        container = completion.get("map")
        business = container.get("data") if isinstance(container, dict) else None
        if not isinstance(business, dict) or str(business.get("busiId") or "") != application_id:
            raise TerminationSubmissionError("办件收尾响应与当前申请不匹配，结果待确认", outcome="unknown")
        if business.get("message"):
            raise TerminationSubmissionError(f"办件返回未确认的提示：{business['message']}", outcome="unknown")
        # Do NOT interpret complete=false as failure: it appears in the success HAR.
        if not saved or not success_visible:
            return None
        return TerminationSubmissionReceipt(application_id)


class TerminationSubmitter:
    """Uses the existing browser pacing/waiter and the current nested frames."""

    def __init__(self, automation: EmploymentTerminationPage, frame: Frame, item: EmploymentTerminationItem) -> None:
        self.automation = automation
        self.page = automation.page
        self.frame = frame
        self.item = item
        self.outer = frame.parent_frame
        if self.outer is None:
            raise TerminationSubmissionError("退保外层业务窗口不存在，未执行提交")
        self.scopes = (frame, self.outer, self.page)
        self.contract = automation.contract
        self.notices_closed = 0
        self.feedback_changed = False
        self.native_feedback: list[str] = []

    def success_visible(self) -> bool:
        # Inspect DOM, not screenshots. Both success markers must share a scope.
        for scope in (self.outer, self.frame):
            try:
                if (scope.get_by_role("heading", name=self.contract.submit_success_heading, exact=True).is_visible()
                        and scope.get_by_text(self.contract.submit_success_text, exact=True).is_visible()):
                    return True
            except PlaywrightError:
                # The outer shell may replace/remove #busiIframe while rendering
                # the success page. Keep waiting on the captured outer frame.
                continue
        return False

    def _native_dialog(self, dialog: Dialog) -> None:
        self.native_feedback.append(dialog.message)
        # Never accept an unrecognised native confirmation or duplicate submission.
        dialog.dismiss()

    def feedback(self, *, confirmation: bool = False) -> Locator | None:
        self.feedback_changed = False
        if self.native_feedback:
            raise TerminationSubmissionError(
                "提交阶段出现浏览器原生提示：" + self.native_feedback[-1], outcome="unknown"
            )
        dialogs = [dialog for scope in self.scopes if (dialog := topmost_business_dialog(scope)) is not None]
        # Errors across all layers take precedence over confirmation/success.
        for dialog in dialogs:
            if dialog.kind in {BusinessDialogKind.ERROR, BusinessDialogKind.EMPLOYEE_NOT_FOUND}:
                raise TerminationSubmissionError(dialog.display_text, outcome="unknown" if not confirmation else "failed")
        for dialog in dialogs:
            compact = "".join(dialog.message.split())
            declaration = "".join(self.contract.submit_declaration_text.split())
            if declaration in compact:
                if not confirmation:
                    raise TerminationSubmissionError("提交确认弹窗仍然存在，结果待确认", outcome="unknown")
                yes = dialog.locator.get_by_role("button", name="是", exact=True)
                no = dialog.locator.get_by_role("button", name="否", exact=True)
                if yes.count() == 1 and no.count() == 1 and yes.is_visible() and no.is_visible():
                    return yes
                raise TerminationSubmissionError("真实性声明的确认按钮结构发生变化，未继续提交")
            # Do not close arbitrary '消息提示': it might be validation or a question.
            if any(token in compact for token in ("当前时间办理人员停保", "发送税务缴费截止时间")):
                self.notices_closed += 1
                if self.notices_closed > 16:
                    raise TerminationSubmissionError("提示弹窗重复出现，停止提交以避免误操作", outcome="unknown")
                close_business_dialog(dialog, pacer=self.automation.pacer, waiter=self.automation.waiter,
                                      timeout_ms=self.automation.settings.browser.action_timeout_ms,
                                      description="关闭提交阶段的办理月份提示")
                # Re-scan newly exposed dialogs before ever accepting success.
                self.feedback_changed = True
                return None
            if (dialog.locator.get_by_role("heading", name=self.contract.submit_success_heading, exact=True).is_visible()
                    and dialog.locator.get_by_text(self.contract.submit_success_text, exact=True).is_visible()):
                continue
            raise TerminationSubmissionError("提交阶段出现未识别的弹窗：" + dialog.display_text, outcome="unknown")
        return None

    def run(self) -> TerminationSubmissionReceipt:
        # A stale success page must never be reused for a new person.
        if self.success_visible():
            raise TerminationSubmissionError("当前业务窗口仍是上一条成功页，未执行提交")
        self.feedback()
        search = self.frame.locator(self.contract.person_search).get_by_role("textbox").first
        if search.input_value().strip().upper() != self.item.identity_number:
            raise TerminationSubmissionError("当前表单身份证号与待提交人员不一致，未执行提交")
        button = self.outer.get_by_role("button", name=self.contract.submit_button_text, exact=True)
        button.wait_for(state="visible", timeout=self.automation.settings.browser.action_timeout_ms)
        monitor = TerminationSubmissionMonitor(self.page, self.automation.settings, self.item)
        listener = self._native_dialog
        self.page.on("dialog", listener)
        clicked = False
        try:
            # Both mutating clicks are single-attempt, with listeners registered first.
            clicked = True
            self.automation.pacer.perform(lambda: button.click(timeout=self.automation.settings.browser.action_timeout_ms))
            yes = self.automation.waiter.first(
                [WaitCondition("退保真实性声明", lambda: self.feedback(confirmation=True))],
                timeout_ms=self.automation.settings.browser.action_timeout_ms,
                description="等待退保提交确认弹窗",
            ).value
            self.automation.pacer.perform(lambda: yes.click(timeout=self.automation.settings.browser.action_timeout_ms))
            self.automation._progress("退保：已确认提交，正在核对接口响应和成功页面")

            def completed() -> TerminationSubmissionReceipt | None:
                self.feedback()
                if self.feedback_changed:
                    return None
                receipt = monitor.receipt(success_visible=self.success_visible())
                # Reading response bodies may dispatch browser events too.
                self.feedback()
                return None if self.feedback_changed else receipt

            return self.automation.waiter.first(
                [WaitCondition("本次人员接口和页面共同确认成功", completed,
                               stable_for_ms=self.contract.stable_delay_ms)],
                timeout_ms=self.contract.response_timeout_ms,
                description="等待退保提交结果",
            ).value
        except (PlaywrightError, SmartWaitTimeoutError, TaskCancelledError) as exc:
            raise TerminationSubmissionError(
                "提交过程中等待中断，结果待确认；请人工查询办件，勿重复提交" if clicked else "未执行提交",
                outcome="unknown" if clicked else "failed",
            ) from exc
        finally:
            monitor.close()
            self.page.remove_listener("dialog", listener)
