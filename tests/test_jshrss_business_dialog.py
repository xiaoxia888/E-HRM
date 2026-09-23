from unittest.mock import Mock

from ehrm.browser.smart_wait import SmartWait
from ehrm.modules.jshrss_business_dialog import (
    BusinessDialog,
    BusinessDialogKind,
    classify_business_dialog,
    close_business_dialog,
    inspect_business_dialog,
)


def test_recorded_time_notice_is_information() -> None:
    assert classify_business_dialog(
        "消息提示",
        "当前时间办理人员停保，发送税务缴费截止时间为2026年09月",
    ) is BusinessDialogKind.INFORMATION


def test_recorded_core_processing_failure_is_error() -> None:
    assert classify_business_dialog(
        "无法办理",
        "核心处理异常，详情请查看日志",
    ) is BusinessDialogKind.ERROR


def test_dialog_inspection_supports_close_button_with_spacing() -> None:
    dialog = Mock()
    title = Mock()
    title.count.return_value = 1
    title.nth.return_value = title
    title.is_visible.return_value = True
    title.inner_text.return_value = "无法办理"
    body = Mock()
    body.count.return_value = 1
    body.nth.return_value = body
    body.is_visible.return_value = True
    body.inner_text.return_value = "核心处理异常，详情请查看日志"
    empty = Mock()
    empty.count.return_value = 0
    dialog.locator.side_effect = lambda selector: {
        ".modal-title": title,
        ".modal-body": body,
    }.get(selector, empty)
    button = Mock()
    button.count.return_value = 1
    button.is_visible.return_value = True
    buttons = Mock()
    buttons.count.return_value = 1
    buttons.nth.return_value = button
    dialog.get_by_role.return_value = buttons

    result = inspect_business_dialog(dialog)

    assert result.kind is BusinessDialogKind.ERROR
    assert result.display_text == "无法办理：核心处理异常，详情请查看日志"
    assert result.action is button
    action_pattern = dialog.get_by_role.call_args.kwargs["name"]
    assert action_pattern.fullmatch("关闭")
    assert action_pattern.fullmatch("关 闭")


def test_close_is_bound_to_the_original_dialog_button_node() -> None:
    visible = {"value": True}
    dialog_locator = Mock()
    dialog_handle = Mock()
    dialog_handle.is_visible.side_effect = lambda: visible["value"]
    dialog_locator.element_handle.return_value = dialog_handle
    action_locator = Mock()
    action_handle = Mock()
    action_handle.click.side_effect = lambda **_kwargs: visible.update(value=False)
    action_locator.element_handle.return_value = action_handle
    dialog = BusinessDialog(
        dialog_locator,
        action_locator,
        "消息提示",
        "当前时间办理人员停保",
        BusinessDialogKind.INFORMATION,
    )
    pacer = Mock()
    pacer.perform.side_effect = lambda action: action()

    close_business_dialog(
        dialog,
        pacer=pacer,
        waiter=SmartWait(lambda _milliseconds: None),
        timeout_ms=5_000,
        description="关闭测试弹窗",
    )

    action_handle.click.assert_called_once_with(timeout=5_000)
    action_locator.click.assert_not_called()
