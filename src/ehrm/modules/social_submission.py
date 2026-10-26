"""Observe one manual-equivalent HRSS collection/enrollment submission.

Contracts are from the 2026-10-16 recording. No direct API replay or automatic
retry: requests identify the current person, and success needs the current DOM.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError, Frame, Request, Response

from ehrm.browser.smart_wait import SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.modules.employment_enrollment.models import EmploymentEnrollmentItem
from ehrm.modules.jshrss_business_dialog import topmost_business_dialog
from ehrm.modules.person_information_collection.models import PersonInformationItem

COLLECTION_PATH = "/api/ehrss-si-enterprise-app/api/applys/employee/registerBaseApply/submitEmpRegisterBaseApplyRest"
ENROLLMENT_PATH = "/api/ehrss-si-enterprise-app/api/applys/employee/registerWorkApply/submitEmpPersonRegistration"
SAVE_PATH = "/api/ehrss-si-enterprise-app/api/changeAndLookController/submitSave"
COMPLETE_PATH = "/api/ggfw-affair-base-center/affair/case/commbusiness/complete"
_EXISTING = re.compile(r"证件号为\s*(\d{15}|\d{17}[\dXx])\s*的人员信息已采集[,，]\s*人员编号为\s*(\d+)")
_LOADING = ".loading-mask:visible, .el-loading-mask:visible, .ant-spin-spinning:visible, .block-ui-active:visible, .blockUI.blockOverlay:visible, .cg-busy:visible, [aria-busy=true]:visible"


class SocialSubmissionError(EhrmError):
    code = "SOCIAL_SUBMISSION_FAILED"

    def __init__(self, message: str, *, outcome: str = "unknown") -> None:
        super().__init__(message)
        self.outcome = outcome


@dataclass(frozen=True, slots=True)
class SocialSubmissionReceipt:
    outcome: str
    message: str
    application_id: str = ""


class SocialSubmissionMonitor:
    def __init__(self, page, settings, item, *, operation: str):
        self.page, self.item, self.operation = page, item.normalized(), operation
        self.host = urlsplit(settings.site.login_url).netloc.casefold()
        self.apply_path = COLLECTION_PATH if operation == "information_collection" else ENROLLMENT_PATH
        self.responses: dict[str, list[Response]] = {path: [] for path in (self.apply_path, SAVE_PATH, COMPLETE_PATH)}
        self._captured_requests: set[int] = set()
        self._listener = self._request_finished
        self._empty_save_listener = self._empty_save_response
        self.page.on("requestfinished", self._listener)
        self.page.on("response", self._empty_save_listener)

    def close(self):
        self.page.remove_listener("requestfinished", self._listener)
        self.page.remove_listener("response", self._empty_save_listener)

    def _empty_save_response(self, response: Response):
        # A verified zero-length save has no body to wait for. Some Chromium
        # versions omit requestfinished/body data for this empty response.
        if urlsplit(response.url).path == SAVE_PATH and response.headers.get('content-length') == '0':
            self.capture(response)

    def _request_finished(self, request: Request):
        if urlsplit(request.url).path not in self.responses:
            return
        response = request.response()
        if response is not None:
            self.capture(response)

    def capture(self, response):
        url = urlsplit(response.url)
        if (url.netloc.casefold() == self.host and url.path in self.responses
                and response.request.method == "POST" and response.request.resource_type in {"xhr", "fetch"}):
            key = id(response.request)
            if key in self._captured_requests:
                return
            self._captured_requests.add(key)
            self.responses[url.path].append(response)

    @staticmethod
    def _json(response):
        try:
            data = response.json()
        except (ValueError, PlaywrightError) as exc:
            raise SocialSubmissionError("提交响应无法解析，结果待确认，请勿重复提交") from exc
        if not isinstance(data, dict):
            raise SocialSubmissionError("提交响应结构未识别，结果待确认，请勿重复提交")
        return data

    def _payload(self, response):
        try:
            payload = json.loads(response.request.post_data or "{}")
        except (ValueError, PlaywrightError) as exc:
            raise SocialSubmissionError("无法核对提交人员，结果待确认") from exc
        if not isinstance(payload, dict):
            raise SocialSubmissionError("提交请求结构未识别，结果待确认")
        person = payload.get("personBasicInfoDTO") if self.operation == "information_collection" else payload
        if not isinstance(person, dict):
            raise SocialSubmissionError("采集请求缺少人员资料，结果待确认")
        identity = person.get("certificateNumber") if self.operation == "information_collection" else person.get("idNumber")
        if str(identity or "").upper() != self.item.identity_number:
            raise SocialSubmissionError("提交请求人员与当前人员不一致，结果待确认")
        if self.operation == "information_collection":
            if str(person.get("name") or "").strip() != self.item.name or str(person.get("mobile") or "") != self.item.mobile:
                raise SocialSubmissionError("采集请求的姓名或手机号与当前人员不一致，结果待确认")
        else:
            item = self.item
            expected = {"contractAddReasons": item.contract_add_reason.value, "contractAddType": item.contract_type.value,
                        "positionType": item.position_type.value}
            if item.management is not None:
                expected["management"] = item.management
            if item.contract_add_reason.value == "1":
                expected["insuredIdentity"] = item.insured_identity.value
                try:
                    from decimal import Decimal
                    if Decimal(str(person.get("wages"))) != item.monthly_wage:
                        raise ValueError("wage mismatch")
                except (ValueError, ArithmeticError) as exc:
                    raise SocialSubmissionError("参保提交工资与当前人员不一致，结果待确认") from exc
            if any(str(person.get(key) or "") != value for key, value in expected.items()):
                raise SocialSubmissionError("参保提交的合同、岗位或参保身份与当前人员不一致，结果待确认")
            for key, expected_date in (("contractBDate", item.contract_start_date), ("contractEDate", item.contract_end_date)):
                if expected_date is None:
                    continue
                try:
                    actual = datetime.fromtimestamp(float(person[key]) / 1000, ZoneInfo("Asia/Shanghai")).date()
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    raise SocialSubmissionError("无法核对参保提交合同日期，结果待确认") from exc
                if actual != expected_date:
                    raise SocialSubmissionError("参保提交合同日期与当前人员不一致，结果待确认")
        if not person.get("applyId"):
            raise SocialSubmissionError("提交请求缺少申请标识，结果待确认")
        return person

    def receipt(self, *, success_visible: bool) -> SocialSubmissionReceipt | None:
        applied = self.responses[self.apply_path]
        if len(applied) > 1 or len(self.responses[COMPLETE_PATH]) > 1:
            raise SocialSubmissionError("检测到重复业务提交或收尾响应，结果待确认，请勿重复提交")
        if not applied:
            return None
        response = applied[0]
        person = self._payload(response)
        data = self._json(response)
        message = str(data.get("message") or data.get("errmsg") or data.get("msg") or "").strip()
        existing = _EXISTING.fullmatch(message)
        if self.operation == "information_collection" and response.status == 400 and str(data.get("code")) == "1111" and existing:
            if existing.group(1).upper() != self.item.identity_number:
                raise SocialSubmissionError("平台已采集提示对应其他人员，结果待确认")
            return SocialSubmissionReceipt("existing", message, str(person["applyId"]))
        if data.get("ok") is False:
            raise SocialSubmissionError(message or "平台明确拒绝本次办理", outcome="failed")
        if not 200 <= response.status < 300:
            raise SocialSubmissionError(f"平台返回 HTTP {response.status}：{message or '未提供业务说明'}；结果待确认，请勿重复提交")
        if data.get("ok") is not True:
            raise SocialSubmissionError(message or "平台未返回明确成功状态，结果待确认")
        # The successful enrollment sample has appcode=-1 and this placeholder.
        if message not in {"", "未提供错误信息"}:
            raise SocialSubmissionError(f"平台成功标志与提示矛盾：{message}；结果待确认")
        if self.operation == "enrollment":
            for response_key, request_key in (("personUniqueId", "personUniqueId"), ("personUniqId", "personId")):
                if not data.get(response_key) or str(data[response_key]) != str(person.get(request_key) or ""):
                    raise SocialSubmissionError("参保响应人员标识与当前提交不一致，结果待确认")
        saves = self.responses[SAVE_PATH]
        for saved in saves:
            saved_person = self._payload(saved)
            if (str(saved_person["applyId"]) != str(person["applyId"]) or not 200 <= saved.status < 300):
                raise SocialSubmissionError("保存响应与当前申请不一致或保存异常，结果待确认")
            if getattr(saved, 'headers', {}).get('content-length') != '0' and saved.text().strip():
                raise SocialSubmissionError("人员保存返回未识别的提示，结果待确认")
        completed = self.responses[COMPLETE_PATH]
        if not saves or not completed:
            return None
        complete = self._json(completed[0])
        container = complete.get("map")
        business = container.get("data") if isinstance(container, dict) else None
        if (not 200 <= completed[0].status < 300 or str(complete.get("appcode")) != "0"
                or not isinstance(business, dict) or str(business.get("busiId") or "") != str(person["applyId"])):
            raise SocialSubmissionError("业务提交已接受，但办件收尾与当前申请不匹配或异常，结果待确认")
        if business.get("message"):
            raise SocialSubmissionError(f"办件收尾提示：{business['message']}；结果待确认")
        if not success_visible:
            return None
        return SocialSubmissionReceipt("submitted", "平台接口与页面共同确认：业务办理成功，提交成功", str(person["applyId"]))


class SocialSubmitter:
    def __init__(self, automation, frame: Frame, item: PersonInformationItem | EmploymentEnrollmentItem, *, operation: str,
                 timeout_ms: int = 120_000):
        self.automation, self.frame, self.item = automation, frame, item.normalized()
        self.page, self.outer = automation.page, frame.parent_frame
        self.operation, self.timeout_ms = operation, timeout_ms
        self.native_messages: list[str] = []
        if self.outer is None:
            raise SocialSubmissionError("当前业务窗口不存在，未执行提交", outcome="failed")

    def success_visible(self):
        for scope in (self.outer, self.frame):
            try:
                if (scope.get_by_role("heading", name="业务办理成功", exact=True).is_visible()
                        and scope.get_by_text("提交成功", exact=True).is_visible()):
                    return True
            except PlaywrightError:
                continue
        return False

    def _idle(self):
        for scope in (self.page, self.outer, self.frame):
            try:
                if scope.locator(_LOADING).count():
                    return False
            except PlaywrightError:
                if scope is not self.frame or not self.success_visible():
                    return False
        return True

    def _feedback(self):
        if self.native_messages:
            return "浏览器提示：" + self.native_messages[-1]
        for scope in (self.frame, self.outer, self.page):
            dialog = topmost_business_dialog(scope)
            if dialog is not None:
                if (dialog.locator.get_by_role("heading", name="业务办理成功", exact=True).is_visible()
                        and dialog.locator.get_by_text("提交成功", exact=True).is_visible()):
                    continue
                return dialog.display_text
        return None

    def run(self, *, before_submit: Callable[[], None]) -> SocialSubmissionReceipt:
        if self.success_visible():
            raise SocialSubmissionError("仍是上一人的成功页，未执行提交", outcome="failed")
        if feedback := self._feedback():
            raise SocialSubmissionError(feedback, outcome="failed")
        identity = (self.frame.locator("#idNumber") if self.operation == "information_collection"
                    else self.frame.locator("sipub-person-quick-search").get_by_role("textbox").first)
        if identity.input_value().strip().upper() != self.item.identity_number:
            raise SocialSubmissionError("当前表单身份证号与待提交人员不一致，未提交", outcome="failed")
        button = self.outer.get_by_role("button", name="确认提交", exact=True)
        button.wait_for(state="visible", timeout=self.automation.settings.browser.action_timeout_ms)
        monitor = SocialSubmissionMonitor(self.page, self.automation.settings, self.item, operation=self.operation)

        def native_dialog(dialog):
            self.native_messages.append(dialog.message)
            dialog.dismiss()

        self.page.on("dialog", native_dialog)
        clicked = False
        try:
            self.automation.pacer.wait_before_action()
            before_submit()
            clicked = True
            button.click(timeout=self.automation.settings.browser.action_timeout_ms)
            self.automation._progress("已点击确认提交，正在等待平台响应、加载结束和办理结果")

            def completed():
                receipt = monitor.receipt(success_visible=self.success_visible() and self._idle())
                # Already-collected is an explicit business rejection, even in
                # an '错误提示' dialog. Preserve its full text for the frontend.
                if receipt and receipt.outcome == "existing":
                    return receipt
                if feedback := self._feedback():
                    existing = _EXISTING.search(feedback) if self.operation == 'information_collection' else None
                    if existing and existing.group(1).upper() == self.item.identity_number:
                        # The dialog can render just before requestfinished is
                        # dispatched. Wait for its matching business response.
                        return None
                    raise SocialSubmissionError(feedback)
                return receipt

            return self.automation.waiter.first(
                [WaitCondition("当前人员的接口与最终页面结果", completed, stable_for_ms=500)],
                timeout_ms=self.timeout_ms, description="等待社保业务提交结果",
            ).value
        except (PlaywrightError, SmartWaitTimeoutError, TaskCancelledError) as exc:
            raise SocialSubmissionError(
                "提交后等待中断或超时，结果待确认，请人工核对，勿重复提交" if clicked else "未执行提交",
                outcome="unknown" if clicked else "failed",
            ) from exc
        finally:
            monitor.close()
            self.page.remove_listener("dialog", native_dialog)
