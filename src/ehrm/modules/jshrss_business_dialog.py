from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from playwright.sync_api import Error as PlaywrightError, Locator

from ehrm.browser.interaction_pacer import BrowserInteractionPacer
from ehrm.browser.smart_wait import SmartWait, SmartWaitTimeoutError, WaitCondition
from ehrm.core.exceptions import WebsiteStructureChangedError


_DIALOG_SELECTORS = (".modal-content", ".ant-modal-content", '[role="dialog"]')
_TITLE_SELECTORS = (
    ".modal-title",
    ".modal-header",
    ".ant-modal-title",
)
_BODY_SELECTORS = (".modal-body", ".ant-modal-body")
_ACTION_NAME = re.compile(r"^\s*(?:确\s*定|关\s*闭)\s*$")
_ACTION_SELECTORS = (
    'button[data-ng-click="modalOptions.ok();"]',
    "button.btn-success",
    "button.ant-btn-primary",
)
_ERROR_TOKENS = (
    "无法办理",
    "不能办理",
    "核心处理异常",
    "处理异常",
    "系统异常",
    "操作失败",
    "业务失败",
)
_NOT_FOUND_TOKENS = ("未找到", "不存在", "无此人员", "未查询到")
_INFO_TOKENS = ("当前时间办理人员停保", "发送税务缴费截止时间")


class BusinessDialogKind(StrEnum):
    INFORMATION = "information"
    EMPLOYEE_NOT_FOUND = "employee_not_found"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class BusinessDialog:
    locator: Locator
    action: Locator | None
    title: str
    message: str
    kind: BusinessDialogKind

    @property
    def display_text(self) -> str:
        if self.title and self.message and self.title not in self.message:
            return f"{self.title}：{self.message}"
        return self.message or self.title or "智慧人社返回了未识别的业务提示"


def classify_business_dialog(title: str, message: str) -> BusinessDialogKind:
    compact_title = _compact(title)
    compact_message = _compact(message)
    combined = compact_title + compact_message
    if any(token in combined for token in _NOT_FOUND_TOKENS):
        return BusinessDialogKind.EMPLOYEE_NOT_FOUND
    if any(token in combined for token in _ERROR_TOKENS):
        return BusinessDialogKind.ERROR
    if any(token in combined for token in _INFO_TOKENS):
        return BusinessDialogKind.INFORMATION
    if compact_title in {"消息提示", "温馨提示", "提示"}:
        return BusinessDialogKind.INFORMATION
    return BusinessDialogKind.UNKNOWN


def topmost_business_dialog(scope: object) -> BusinessDialog | None:
    for selector in _DIALOG_SELECTORS:
        try:
            dialogs = scope.locator(selector)
            for index in range(dialogs.count() - 1, -1, -1):
                dialog = dialogs.nth(index)
                if not _visible(dialog):
                    continue
                return inspect_business_dialog(dialog)
        except (AttributeError, PlaywrightError):
            continue
    return None


def inspect_business_dialog(dialog: Locator) -> BusinessDialog:
    title = _first_visible_text(dialog, _TITLE_SELECTORS)
    message = _first_visible_text(dialog, _BODY_SELECTORS)
    if not message:
        message = _safe_text(dialog)
        if title and message.startswith(title):
            message = message[len(title) :].strip(" ：:")
    action = _dialog_action(dialog)
    return BusinessDialog(
        locator=dialog,
        action=action,
        title=title,
        message=message,
        kind=classify_business_dialog(title, message),
    )


def close_business_dialog(
    dialog: BusinessDialog,
    *,
    pacer: BrowserInteractionPacer,
    waiter: SmartWait,
    timeout_ms: int,
    description: str,
) -> None:
    if dialog.action is None:
        raise WebsiteStructureChangedError(
            f"{dialog.display_text}；弹窗中没有可操作的确定或关闭按钮"
        )
    try:
        dialog_handle = dialog.locator.element_handle(timeout=500)
        action_handle = dialog.action.element_handle(timeout=500)
    except PlaywrightError as exc:
        raise WebsiteStructureChangedError(
            f"无法读取业务弹窗：{dialog.display_text}", details=str(exc)
        ) from exc

    def closed() -> bool | None:
        if dialog_handle is None:
            return True
        try:
            return True if not dialog_handle.is_visible() else None
        except PlaywrightError:
            return True

    strategies = ("playwright", "dom")
    errors: list[str] = []
    for strategy in strategies:
        if closed() is not None:
            return
        try:
            if strategy == "dom" and action_handle is not None:
                pacer.perform(
                    lambda: action_handle.evaluate(
                        "element => { element.focus(); element.click(); }"
                    )
                )
            else:
                pacer.perform(
                    lambda: (
                        action_handle.click(timeout=min(timeout_ms, 5_000))
                        if action_handle is not None
                        else dialog.action.click(timeout=min(timeout_ms, 5_000))
                    )
                )
        except PlaywrightError as exc:
            errors.append(f"{strategy}: {exc}")
            continue
        try:
            waiter.first(
                [WaitCondition("当前业务弹窗已关闭", closed)],
                timeout_ms=min(timeout_ms, 2_000),
                description=description,
            )
            return
        except SmartWaitTimeoutError:
            continue
    raise WebsiteStructureChangedError(
        f"{dialog.display_text}；点击后弹窗没有关闭",
        details="；".join(errors) or description,
    )


def _dialog_action(dialog: Locator) -> Locator | None:
    try:
        buttons = dialog.get_by_role("button", name=_ACTION_NAME)
        action = _last_visible(buttons)
        if action is not None:
            return action
    except PlaywrightError:
        pass
    for selector in _ACTION_SELECTORS:
        try:
            action = _last_visible(dialog.locator(selector))
            if action is not None:
                return action
        except PlaywrightError:
            continue
    return None


def _first_visible_text(dialog: Locator, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            candidates = dialog.locator(selector)
            for index in range(candidates.count()):
                candidate = candidates.nth(index)
                if _visible(candidate):
                    text = _safe_text(candidate)
                    if text:
                        return text
        except PlaywrightError:
            continue
    return ""


def _safe_text(locator: Locator) -> str:
    try:
        return " ".join(locator.inner_text(timeout=500).split())
    except PlaywrightError:
        return ""


def _last_visible(locators: Locator) -> Locator | None:
    for index in range(locators.count() - 1, -1, -1):
        candidate = locators.nth(index)
        if _visible(candidate):
            return candidate
    return None


def _visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible()
    except PlaywrightError:
        return False


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "")
