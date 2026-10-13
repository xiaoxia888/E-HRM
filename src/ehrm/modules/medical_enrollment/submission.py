"""Single-click medical collection and enrollment with conservative outcome checks."""
from __future__ import annotations

from collections.abc import Callable
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, Locator, Response

from ehrm.core.exceptions import EhrmError, WebsiteStructureChangedError
from ehrm.modules.medical_enrollment.models import MedicalPreSubmitItem, MedicalStage
from ehrm.modules.medical_enrollment.page import MedicalPreSubmitPage, identity_demographics


_HOST = "wb.njybjyybz.org.cn"
_COLLECTION_PATH = "/api/ryda/saveRydainfo"
_ENROLLMENT_PATH = "/api/dwctbbl/rycbdj/saveInfo"
_RESULT_PATH = "/api/dwctbbl/rycbdj/queryBl"


class MedicalEnrollmentSubmissionUncertainError(EhrmError):
    """A save/submit click happened, but a definitive result was not observed."""


def classify_collection_response(payload: dict) -> str:
    """Return saved/existing; everything else needs human confirmation."""
    message = str(payload.get("message") or payload.get("msg") or "")
    if payload.get("code") in (0, "0") and payload.get("type") == "success" and "成功" in message:
        return "saved"
    if payload.get("code") not in (0, "0") and "已经建档" in message:
        return "existing"
    raise MedicalEnrollmentSubmissionUncertainError(
        f"基础信息采集返回未确认结果：{message or '无明确提示'}；请先到医保平台核对，勿重复提交"
    )


def confirm_enrollment_response(payload: dict) -> str:
    message = str(payload.get("message") or payload.get("msg") or "")
    if (payload.get("code") in (0, "0") and payload.get("type") == "success"
            and ("办理成功" in message or "参保成功" in message)):
        return message
    raise MedicalEnrollmentSubmissionUncertainError(
        f"医保参保返回未确认结果：{message or '无明确提示'}；请先到医保平台核对，勿重复提交"
    )


class MedicalEnrollmentSubmissionPage(MedicalPreSubmitPage):
    """The real submit methods are intentionally separate from the fill-only E2E page."""

    def submit_collection(
        self, item: MedicalPreSubmitItem, *, before_submit: Callable[[], None],
    ) -> str:
        if self.stage is not MedicalStage.COLLECTION:
            raise ValueError("当前不是基础信息采集页面")
        item = item.normalized(MedicalStage.COLLECTION)
        form = self.page.locator('form[name="f_form"]')
        if form.count() != 1 or not form.is_visible():
            raise WebsiteStructureChangedError("医保基础信息采集表单未就绪，未点击确认")
        birth_date, gender = identity_demographics(item.identity_number)
        for field, expected, label in (
            (self._collection_identity(), item.identity_number, "身份证号"),
            (self._collection_input("psnName", "姓名"), item.name, "姓名"),
            (self._collection_input("brdy", "出生日期"), birth_date.isoformat(), "出生日期"),
            (self._collection_input("gend", "性别"), gender, "性别"),
            (self._collection_input("mob", "联系电话"), item.mobile, "联系电话"),
            (self._collection_input("naty", "民族"), item.nation, "民族"),
        ):
            if not expected or field.input_value().strip().upper() != expected.upper():
                raise WebsiteStructureChangedError(f"医保基础信息采集{label}缺失或与申请不一致，未点击确认")
        self._raise_feedback()
        button = self._unique_button(form.get_by_role("button", name="确认", exact=True), "基础信息采集确认")
        payload = self._click_and_wait_response(button, _COLLECTION_PATH, before_submit)
        outcome = classify_collection_response(payload)
        if outcome == "existing":
            self.dismiss_archive_notice("已经建档")
        return outcome

    def dismiss_archive_notice(self, message: str) -> None:
        notices = self.page.locator(".el-message-box").filter(has_text=message)
        dialogs = []
        for _ in range(10):
            dialogs = self._visible_nodes(notices)
            if dialogs:
                break
            self.page.wait_for_timeout(100)
        if not dialogs:
            return
        if len(dialogs) != 1:
            raise WebsiteStructureChangedError("医保建档提示弹窗不唯一，已停止后续操作")
        button = self._unique_button(
            dialogs[0].get_by_role("button", name="确定", exact=True), "医保提示确认"
        )
        self._perform(button.click)

    def submit_enrollment(
        self, item: MedicalPreSubmitItem, *, before_submit: Callable[[], None],
    ) -> str:
        if self.stage is not MedicalStage.ENROLLMENT:
            raise ValueError("当前不是人员参保登记页面")
        item = item.normalized(MedicalStage.ENROLLMENT)
        identity = self._enrollment_identity()
        if identity.input_value().strip().upper() != item.identity_number:
            raise WebsiteStructureChangedError("医保参保身份证号与申请不一致，未点击提交")
        displayed_identity = self._enrollment_input(
            "zjhm", "证件号码", require_enabled=False
        ).input_value().strip().upper()
        if displayed_identity != item.identity_number:
            raise WebsiteStructureChangedError("医保查询返回的证件号码与申请不一致，未点击参保提交")
        if item.name:
            portal_name = self._enrollment_input(
                "psnName", "姓名", require_enabled=False
            ).input_value().strip()
            if portal_name != item.name:
                raise WebsiteStructureChangedError("医保查询返回的姓名与 NocoBase 申请不一致，未点击参保提交")
        enrollment_date = self._enrollment_input("ddwsj", "到单位时间")
        if enrollment_date.input_value().strip() != item.enrollment_date.isoformat():
            raise WebsiteStructureChangedError("医保参保日期与申请不一致，未点击提交")
        mobile = self._enrollment_input("mob", "手机号")
        if mobile.input_value().strip() != item.mobile:
            raise WebsiteStructureChangedError("医保参保手机号与申请不一致，未点击提交")
        self._raise_feedback()
        button = self._enrollment_button("单位员工参保信息", "提交")
        payload = self._click_and_wait_response(button, _ENROLLMENT_PATH, before_submit)
        message = confirm_enrollment_response(payload)
        if not self._has_result_row(item.identity_number):
            cards = self._visible_nodes(self.page.locator("div.el-card").filter(has_text="查询办理结果"))
            if len(cards) != 1:
                raise MedicalEnrollmentSubmissionUncertainError(
                    "医保参保接口提示成功，但办理结果查询区未能唯一定位；请核对，勿重复提交"
                )
            query = self._unique_button(
                cards[0].get_by_role("button", name="查询", exact=True), "办理结果查询"
            )
            result_payload = self._click_and_wait_response(query, _RESULT_PATH)
            if result_payload.get("code") not in (0, "0") or result_payload.get("type") != "success":
                raise MedicalEnrollmentSubmissionUncertainError(
                    "办理结果查询未返回明确成功状态；请核对参保结果，勿重复提交"
                )
        self._wait_for_result_row(item.identity_number)
        return f"医保平台提示：{message}；办理结果列表已显示本人的办理成功记录"

    def _click_and_wait_response(
        self, button: Locator, endpoint: str, before_submit: Callable[[], None] | None = None,
    ) -> dict:
        responses: list[Response] = []

        def on_response(response: Response) -> None:
            try:
                if (response.request.method == "POST" and urlsplit(response.url).hostname == _HOST
                        and urlsplit(response.url).path.endswith(endpoint)):
                    responses.append(response)
            except (AttributeError, PlaywrightError, ValueError):
                return

        self.page.on("response", on_response)
        try:
            if before_submit is not None:
                before_submit()
            self._perform(button.click)
            deadline = time.monotonic() + self.timeout_ms / 1000
            while not responses and time.monotonic() < deadline:
                self.page.wait_for_timeout(100)
            if len(responses) != 1 or responses[0].status != 200:
                raise MedicalEnrollmentSubmissionUncertainError(
                    "点击后未取得唯一且正常的医保提交接口响应；请先到医保平台核对，勿重复提交"
                )
            payload = responses[0].json()
            if not isinstance(payload, dict):
                raise ValueError("提交接口响应不是对象")
            return payload
        except MedicalEnrollmentSubmissionUncertainError:
            raise
        except (PlaywrightError, ValueError) as exc:
            raise MedicalEnrollmentSubmissionUncertainError(
                "医保提交后页面或接口响应异常；请先到医保平台核对，勿重复提交"
            ) from exc
        finally:
            self.page.remove_listener("response", on_response)

    def _wait_for_result_row(self, identity: str) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            if self._has_result_row(identity):
                return
            self.page.wait_for_timeout(100)
        raise MedicalEnrollmentSubmissionUncertainError(
            "参保接口提示成功，但未在办理结果列表找到本人的成功记录；请核对，勿重复提交"
        )

    def _has_result_row(self, identity: str) -> bool:
        for row in self._visible_nodes(self.page.locator("tr")):
            text = re.sub(r"\s+", "", row.inner_text())
            if identity in text and ("办理成功" in text or "参保成功" in text):
                return True
        return False

    @staticmethod
    def _unique_button(buttons: Locator, label: str) -> Locator:
        visible = MedicalPreSubmitPage._visible_nodes(buttons)
        if len(visible) != 1 or visible[0].is_disabled():
            raise WebsiteStructureChangedError(f"{label}按钮未能唯一定位或不可用，未继续执行")
        return visible[0]
