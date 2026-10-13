from __future__ import annotations

from collections.abc import Callable
from datetime import date
import re
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError, Locator, Page, Response

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.core.exceptions import EhrmError, QueryResultTimeoutError, WebsiteStructureChangedError
from ehrm.core.settings import BrowserInteractionPacingSettings
from ehrm.modules.medical_enrollment.models import MedicalPreSubmitItem, MedicalStage
from ehrm.modules.medical_termination.page import is_medical_portal_url


_PORTAL_HOST = "wb.njybjyybz.org.cn"
_LOADING = ".el-loading-mask"
_FEEDBACK = (
    ".el-message-box__message",
    ".el-message.el-message--error .el-message__content",
    ".el-message.el-message--warning .el-message__content",
    ".el-alert--error .el-alert__content",
    ".el-alert--warning .el-alert__content",
    ".el-form-item__error",
)


class MedicalPreSubmitBlockedError(EhrmError):
    """A portal business rule blocked filling; never interpret it as submitted."""

    def __init__(self, message: str, *, outcome: str = "业务阻断") -> None:
        super().__init__(message)
        self.outcome = outcome


def identity_demographics(identity: str) -> tuple[date, str]:
    """Use the ID-encoded birth date and sex only for the collection form."""
    if len(identity) == 18:
        birth = f"{identity[6:10]}-{identity[10:12]}-{identity[12:14]}"
        sex_digit = identity[16]
    elif len(identity) == 15:
        birth = f"19{identity[6:8]}-{identity[8:10]}-{identity[10:12]}"
        sex_digit = identity[14]
    else:
        raise WebsiteStructureChangedError("身份证号长度无法推导出生日期和性别，未提交医保建档")
    try:
        return date.fromisoformat(birth), "男" if int(sex_digit) % 2 else "女"
    except ValueError as exc:
        raise WebsiteStructureChangedError("身份证号无法推导有效出生日期和性别，未提交医保建档") from exc


class MedicalPreSubmitPage:
    """The recorded collection/enrollment paths, with no save or submit action."""

    def __init__(
        self,
        page: Page,
        stage: MedicalStage,
        *,
        timeout_ms: int = 30_000,
        pacing: BrowserInteractionPacingSettings | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        if not is_medical_portal_url(page.url):
            raise WebsiteStructureChangedError("当前页面不是南京医保单位大厅")
        self.page = page
        self.stage = stage
        self.timeout_ms = timeout_ms
        self.progress_callback = progress_callback
        self.pacer = (
            BrowserInteractionPacer(pacing, page.wait_for_timeout)
            if pacing is not None else None
        )

    def fill_item(self, item: MedicalPreSubmitItem) -> None:
        item = item.normalized(self.stage)
        self.open()
        if self.stage is MedicalStage.COLLECTION:
            self._fill_collection(item)
        else:
            self._fill_enrollment(item)
        self._raise_feedback()
        self._progress("医保：已填写录制可确认的字段，正在核对下一步操作")

    def open(self) -> None:
        if self.stage is MedicalStage.COLLECTION:
            self._progress("医保：正在进入人员基础信息采集")
            self._perform(self.page.get_by_text("单位人员档案管理", exact=True).first.click)
            self._progress("医保：档案管理菜单已展开，正在打开采集表单")
            self._perform(
                self.page.get_by_role("link", name="人员基础信息采集", exact=True).click
            )
            self._progress("医保：采集页面已打开，等待证件号码输入框")
            self._collection_identity().wait_for(state="visible", timeout=self.timeout_ms)
            self._progress("医保：基础信息采集表单已就绪")
        else:
            if self._enrollment_form_is_active():
                self._progress("医保：人员参保登记已打开，复用当前页面")
                return
            self._progress("医保：正在进入人员参保登记")
            link = self.page.get_by_role("link", name="人员参保登记", exact=True)
            if not self._visible_nodes(link):
                self._perform(self.page.get_by_text("单位参停保办理", exact=True).first.click)
            try:
                link.first.wait_for(state="visible", timeout=self.timeout_ms)
            except PlaywrightError as exc:
                raise WebsiteStructureChangedError(
                    "医保人员参保登记菜单未出现，未继续办理"
                ) from exc
            visible_links = self._visible_nodes(link)
            if len(visible_links) != 1:
                raise WebsiteStructureChangedError("医保人员参保登记菜单不能唯一定位")
            self._perform(visible_links[0].click)
            self._enrollment_identity()
            self._enrollment_button("员工个人信息查询", "查询")

    def _enrollment_form_is_active(self) -> bool:
        # The medical hall keeps a completed enrollment tab open. Clicking its
        # parent menu again toggles the submenu closed, hiding the link.
        form = self.page.locator('form[name="f_form"]')
        identity = form.locator(
            'label[for="certno"] + .el-form-item__content input.el-input__inner'
        )
        card = form.locator(".el-card").filter(has_text="员工个人信息查询")
        return (
            form.count() == 1
            and identity.count() == 1
            and identity.is_visible()
            and card.count() == 1
            and card.is_visible()
        )

    def _fill_collection(self, item: MedicalPreSubmitItem) -> None:
        identity = self._collection_identity()
        self._progress("医保：正在填写证件号码")
        self._fill_verified(identity, item.identity_number, "身份证号")
        # The recording pressed Enter after the document number. It may
        # populate read-only demographic fields, but does not save a person.
        self._perform(lambda: identity.press("Enter"))
        self._progress("医保：证件号码已填写，等待页面校验")
        self._wait_until_not_loading()
        self._raise_feedback()
        birth_date, gender = identity_demographics(item.identity_number)
        birth_field = self._collection_input("brdy", "出生日期")
        if not birth_field.input_value().strip():
            self._set_date(birth_field, birth_date, "出生日期")
        elif birth_field.input_value().strip() != birth_date.isoformat():
            raise WebsiteStructureChangedError("医保建档出生日期与身份证号不一致，未点击确认")
        gender_field = self._collection_input("gend", "性别")
        if not gender_field.input_value().strip():
            self._select_option("性别", gender, field=gender_field)
        elif gender_field.input_value().strip() != gender:
            raise WebsiteStructureChangedError("医保建档性别与身份证号不一致，未点击确认")
        self._progress("医保：正在填写人员基本信息")
        self._fill_verified(self._collection_input("psnName", "姓名"), item.name, "姓名")
        if item.mobile:
            mobile = self._collection_input("mob", "联系电话")
            self._fill_verified(mobile, item.mobile, "联系电话")
            self._perform(lambda: mobile.press("Tab"))
            self.page.wait_for_timeout(250)
        if item.nation:
            self._select_option(
                "民族", item.nation, field=self._collection_input("naty", "民族")
            )
        if item.document_start_date:
            self._set_date(
                self._collection_input("zjyxqqsrq", "证件有效期(起始日期)"),
                item.document_start_date, "证件有效期起始日期",
            )
        if item.document_end_date:
            self._set_date(
                self._collection_input("zjyxqjzrq", "证件有效期(截止日期)"),
                item.document_end_date, "证件有效期截止日期",
            )

    def _fill_enrollment(self, item: MedicalPreSubmitItem) -> None:
        identity = self._enrollment_identity()
        self._fill_verified(identity, item.identity_number, "身份证号")
        responses: list[Response] = []

        def on_response(response: Response) -> None:
            try:
                request = response.request
                if (
                    request.resource_type in {"xhr", "fetch"}
                    and urlsplit(response.url).hostname == _PORTAL_HOST
                    and urlsplit(response.url).path.endswith(
                        "/api/dwctbbl/rycbdj/queryYg"
                    )
                ):
                    responses.append(response)
            except (AttributeError, PlaywrightError, ValueError):
                return

        self.page.on("response", on_response)
        try:
            self._progress("医保：正在查询人员并等待加载结束")
            query = self._enrollment_button("员工个人信息查询", "查询")
            self._perform(query.click)
            self._wait_for_query(responses, item.identity_number)
        finally:
            self.page.remove_listener("response", on_response)
        self._raise_feedback()
        self._progress("医保：人员查询完成，正在填写参保字段")
        assert item.enrollment_date is not None
        self._set_date(
            self._enrollment_input("ddwsj", "到单位时间"),
            item.enrollment_date,
            "参保日期",
        )
        mobile = self._enrollment_input("mob", "手机号")
        self._fill_verified(mobile, item.mobile, "联系电话")
        self._perform(lambda: mobile.press("Tab"))
        self.page.wait_for_timeout(250)

    def _wait_for_query(self, responses: list[Response], identity_number: str) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        clear_since: float | None = None
        while time.monotonic() < deadline:
            self._raise_feedback()
            if not responses or self._any_visible(_LOADING):
                clear_since = None
            else:
                clear_since = clear_since or time.monotonic()
                if time.monotonic() - clear_since >= 0.3:
                    break
            self.page.wait_for_timeout(100)
        else:
            raise QueryResultTimeoutError(
                "医保参保人员查询加载超时",
                details="未取得人员查询接口响应，或加载遮罩尚未结束",
            )
        self._raise_feedback()
        for response in responses:
            if response.status >= 400:
                raise MedicalPreSubmitBlockedError(
                    f"医保人员查询接口返回 HTTP {response.status}"
                )
            try:
                payload = response.json()
            except (PlaywrightError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            data = payload.get("data")
            failed = (
                payload.get("success") is False
                or payload.get("ok") is False
                or payload.get("type") == "error"
                or (isinstance(data, dict) and data.get("success") is False)
            )
            if not failed and (
                payload.get("ok") is True
                or payload.get("success") is True
                or payload.get("code") in (None, 0, "0", 200, "200")
            ):
                continue
            message = str(
                payload.get("message") or payload.get("msg") or payload.get("errmsg")
                or (data.get("message") if isinstance(data, dict) else None)
                or "医保人员查询接口返回错误"
            )
            if "请先给该人员建档" in message:
                raise MedicalPreSubmitBlockedError(message, outcome="需先建档")
            if "已经参保" in message or "重复参保" in message:
                raise MedicalPreSubmitBlockedError(message, outcome="已参保")
            raise MedicalPreSubmitBlockedError(message)
        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            self._raise_feedback()
            portal_identity = self._enrollment_input(
                "zjhm", "证件号码", require_enabled=False
            ).input_value().strip().upper()
            portal_name = self._enrollment_input(
                "psnName", "姓名", require_enabled=False
            ).input_value().strip()
            if portal_identity == identity_number.upper() and portal_name:
                return
            self.page.wait_for_timeout(100)
        raise WebsiteStructureChangedError(
            "人员查询已结束，但参保表单未显示当前身份证号及姓名；未继续填写或提交"
        )

    def _wait_until_not_loading(self) -> None:
        deadline = time.monotonic() + self.timeout_ms / 1000
        while self._any_visible(_LOADING):
            self._raise_feedback()
            if time.monotonic() >= deadline:
                raise QueryResultTimeoutError("基础信息采集页面加载超时")
            self.page.wait_for_timeout(100)
        # Allow a validation message triggered by Enter to render.
        self.page.wait_for_timeout(300)

    def _collection_identity(self) -> Locator:
        return self._collection_input("certno", "证件号码")

    def _collection_input(self, field_id: str, expected_label: str) -> Locator:
        # In the captured form, label[for] identifies the field, but the input
        # has no id. Do not use get_by_label() or a textbox position here.
        form = self.page.locator('form[name="f_form"]')
        label = form.locator(f'label[for="{field_id}"]')
        try:
            label.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"基础信息采集字段“{expected_label}”标签未出现（for={field_id}）"
            ) from exc
        actual_label = re.sub(r"\s*[:：]\s*$", "", label.inner_text().strip())
        if label.count() != 1 or actual_label != expected_label:
            raise WebsiteStructureChangedError(
                f"基础信息采集字段“{expected_label}”标签已变化（实际：{actual_label}）"
            )
        field = form.locator(
            f'label[for="{field_id}"] + .el-form-item__content input.el-input__inner'
        )
        try:
            field.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"基础信息采集字段“{expected_label}”输入框未出现（for={field_id}）"
            ) from exc
        if field.count() != 1 or not field.is_enabled():
            raise WebsiteStructureChangedError(
                f"基础信息采集字段“{expected_label}”输入框不可唯一定位或不可填写"
            )
        return field

    def _enrollment_identity(self) -> Locator:
        return self._enrollment_input("certno", "身份证号码(输入后点击查询)")

    def _enrollment_input(
        self, field_id: str, expected_label: str, *, require_enabled: bool = True
    ) -> Locator:
        # The portal's label[for] is not linked to an input id. Locate its
        # adjacent content, not a global textbox position or placeholder.
        form = self.page.locator('form[name="f_form"]')
        label = form.locator(f'label[for="{field_id}"]')
        try:
            label.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"医保参保字段“{expected_label}”标签未出现（for={field_id}）"
            ) from exc
        actual_label = re.sub(r"\s*[:：]\s*$", "", label.inner_text().strip())
        if label.count() != 1 or actual_label != expected_label:
            raise WebsiteStructureChangedError(
                f"医保参保字段“{expected_label}”标签已变化（实际：{actual_label}）"
            )
        field = form.locator(
            f'label[for="{field_id}"] + .el-form-item__content input.el-input__inner'
        )
        try:
            field.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"医保参保字段“{expected_label}”输入框未出现（for={field_id}）"
            ) from exc
        if field.count() != 1 or (require_enabled and not field.is_enabled()):
            raise WebsiteStructureChangedError(
                f"医保参保字段“{expected_label}”输入框不可唯一定位或不可填写"
            )
        return field

    def _enrollment_button(self, card_title: str, button_text: str) -> Locator:
        form = self.page.locator('form[name="f_form"]')
        card = form.locator(".el-card").filter(has_text=card_title)
        button = card.get_by_role("button", name=button_text, exact=True)
        try:
            button.first.wait_for(state="visible", timeout=self.timeout_ms)
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError(
                f"医保参保“{card_title}”区的“{button_text}”按钮未出现"
            ) from exc
        if card.count() != 1 or button.count() != 1 or not button.is_enabled():
            raise WebsiteStructureChangedError(
                f"医保参保“{card_title}”区的“{button_text}”按钮不可唯一定位或不可用"
            )
        return button

    def _field_input(self, *labels: str) -> Locator:
        matched: list[Locator] = []
        for label in labels:
            pattern = re.compile(rf"^\s*{re.escape(label)}\s*[:：]?\s*$")
            items = self.page.locator(".el-form-item").filter(
                has=self.page.locator(".el-form-item__label", has_text=pattern)
            )
            for item in self._visible_nodes(items):
                inputs = self._visible_nodes(item.locator("input"))
                matched.extend(inputs)
        if len(matched) != 1:
            raise WebsiteStructureChangedError(
                f"无法唯一定位医保字段“{'/'.join(labels)}”（可见输入框 {len(matched)} 个）"
            )
        return matched[0]

    def _assert_context(self, field: Locator, expected: str) -> None:
        context = field.locator("xpath=ancestor::*[contains(@class, 'el-form-item')][1]")
        try:
            label = context.locator(".el-form-item__label").first.inner_text()
        except PlaywrightError as exc:
            raise WebsiteStructureChangedError("医保表单字段标签无法读取") from exc
        if expected not in label:
            raise WebsiteStructureChangedError(
                f"医保录制的输入框顺序已变化：期望“{expected}”，实际“{label.strip()}”"
            )

    def _fill_verified(self, field: Locator, value: str, label: str) -> None:
        field.wait_for(state="visible", timeout=self.timeout_ms)
        self._perform(lambda: field.fill(value))
        if field.input_value().strip().upper() != value.upper():
            raise WebsiteStructureChangedError(f"医保{label}未正确写入")

    def _select_option(self, label: str, value: str, *, field: Locator | None = None) -> None:
        if field is None:
            field = self._field_input(label)
        self._perform(field.click)
        options = self.page.get_by_role("listitem").filter(
            has_text=re.compile(rf"^\s*{re.escape(value)}\s*$")
        )
        options.first.wait_for(state="visible", timeout=self.timeout_ms)
        visible = self._visible_nodes(options)
        if len(visible) != 1:
            raise WebsiteStructureChangedError(f"医保{label}选项未能唯一定位：{value}")
        self._perform(visible[0].click)
        if field.input_value().strip() != value:
            raise WebsiteStructureChangedError(f"医保{label}选择后值不一致")

    def _set_date(self, field: Locator, target: date, label: str) -> None:
        value = target.isoformat()
        field.wait_for(state="visible", timeout=self.timeout_ms)
        if field.get_attribute("readonly") is None:
            self._perform(lambda: field.fill(value))
            self._perform(lambda: field.press("Tab"))
        else:
            self._perform(field.click)
            panel = self.page.locator(".el-picker-panel:visible").last
            panel.wait_for(state="visible", timeout=self.timeout_ms)
            for _ in range(120):
                header = panel.locator(".el-date-picker__header").inner_text()
                year = re.search(r"(\d{4})\s*年", header)
                month = re.search(r"(\d{1,2})\s*月", header)
                if not year or not month:
                    raise WebsiteStructureChangedError(f"医保{label}日期选择器结构已变化")
                displayed = (int(year[1]), int(month[1]))
                if displayed == (target.year, target.month):
                    break
                direction = (
                    ".el-icon-arrow-left" if displayed > (target.year, target.month)
                    else ".el-icon-arrow-right"
                )
                self._perform(panel.locator(f".el-date-picker__header {direction}").click)
            else:
                raise WebsiteStructureChangedError(f"医保{label}超出日期选择器可安全定位范围")
            day = panel.locator(
                ".el-date-table td.available:not(.prev-month):not(.next-month)"
            ).filter(has_text=re.compile(rf"^\s*{target.day}\s*$"))
            if day.count() != 1:
                raise WebsiteStructureChangedError(f"医保{label}日期未能唯一定位")
            self._perform(day.click)
        if field.input_value().strip() != value:
            raise WebsiteStructureChangedError(f"医保{label}未正确写入，期望 {value}")

    def _raise_feedback(self) -> None:
        for selector in _FEEDBACK:
            for node in self._visible_nodes(self.page.locator(selector)):
                message = " ".join(node.inner_text().split())
                if not message:
                    continue
                if "请先给该人员建档" in message:
                    raise MedicalPreSubmitBlockedError(message, outcome="需先建档")
                if "已经建档" in message:
                    raise MedicalPreSubmitBlockedError(message, outcome="已建档")
                if "已经参保" in message or "重复参保" in message:
                    raise MedicalPreSubmitBlockedError(message, outcome="已参保")
                raise MedicalPreSubmitBlockedError(message)

    def _any_visible(self, selector: str) -> bool:
        return bool(self._visible_nodes(self.page.locator(selector)))

    @staticmethod
    def _visible_nodes(nodes: Locator) -> list[Locator]:
        visible: list[Locator] = []
        for index in range(nodes.count()):
            node = nodes.nth(index)
            try:
                if node.is_visible():
                    visible.append(node)
            except PlaywrightError:
                continue
        return visible

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)

    def _perform(self, action: Callable[[], None]) -> None:
        if self.pacer is None:
            action()
        else:
            self.pacer.perform(action)
