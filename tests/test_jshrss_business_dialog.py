from unittest.mock import Mock

from pathlib import Path
from html import escape

import pytest
from playwright.sync_api import sync_playwright

from ehrm.browser.smart_wait import SmartWait
from ehrm.core.exceptions import WebsiteStructureChangedError
from ehrm.core.settings import load_settings
from ehrm.modules.jshrss_business_dialog import (
    BusinessDialog,
    BusinessDialogKind,
    classify_business_dialog,
    close_business_dialog,
    inspect_business_dialog,
    topmost_business_dialog,
)
from ehrm.modules.jshrss_hall import JshrssHallNavigator


@pytest.fixture(scope="module")
def local_page():
    """只加载本地 HTML；没有登录、网络请求或业务提交。"""
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).exists():
            pytest.skip("本地 DOM 回归测试需要已安装的 Playwright Chromium")
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        yield page
        browser.close()


@pytest.mark.parametrize("wrapper", [
    '<div>{content}</div>',
    '<div class="modal" aria-hidden="true">{content}</div>',
    '<div class="modal fade" role="dialog">{content}</div>',
    '<div class="modal in" style="opacity:0">{content}</div>',
    '<div class="ng-cloak"><div class="modal in">{content}</div></div>',
    '<div class="ant-modal" role="dialog">{content}</div>',
])
def test_unopened_notice_template_is_not_a_business_dialog(local_page, wrapper):
    # 模拟 CSS/Angular 尚未完成初始化：模板节点有尺寸，但并非已打开的弹窗。
    content = ('<div class="modal-content"><div class="modal-header">'
               '不符合办理条件，暂不受理本业务</div><div class="modal-body">'
               '经办人不能为空 移动电话格式错误 确认打印告知书</div></div>')
    local_page.set_content(wrapper.format(content=content))
    assert local_page.locator(".modal-content").is_visible()
    assert topmost_business_dialog(local_page) is None


def test_active_error_is_not_hidden_by_later_notice_template(local_page):
    local_page.set_content('''
        <div class="modal in" role="dialog">
          <div class="modal-content"><div class="modal-title">无法办理</div>
            <div class="modal-body">核心处理异常，详情请查看日志</div>
            <button>关闭</button></div>
        </div>
        <div class="modal-content"><div class="modal-title">不符合办理条件</div>
          <div class="modal-body">经办人不能为空</div></div>
    ''')
    dialog = topmost_business_dialog(local_page)
    assert dialog is not None
    assert dialog.kind is BusinessDialogKind.ERROR
    assert dialog.message == "核心处理异常，详情请查看日志"
    assert dialog.action is not None


def test_active_ineligible_notice_without_close_button_is_still_error(local_page):
    local_page.set_content('''
        <div class="modal in" role="dialog"><div class="modal-content">
          <div class="modal-title">不符合办理条件，暂不受理本业务</div>
          <div class="modal-body">请登记联系电话并打印告知书</div>
          <button class="btn-success">确认打印告知书</button>
        </div></div>
    ''')
    dialog = topmost_business_dialog(local_page)
    assert dialog is not None
    assert dialog.kind is BusinessDialogKind.ERROR
    assert dialog.action is None  # 不得自动点击打印告知书来绕过业务错误。


def test_active_antd_information_dialog_is_supported(local_page):
    local_page.set_content('''
        <div class="ant-modal" role="dialog"><div class="ant-modal-content">
          <div class="ant-modal-title">消息提示</div>
          <div class="ant-modal-body">当前时间办理人员停保</div>
          <button>确定</button>
        </div></div>
    ''')
    dialog = topmost_business_dialog(local_page)
    assert dialog is not None
    assert dialog.kind is BusinessDialogKind.INFORMATION
    assert dialog.action is not None


def _set_business_frame(local_page, html):
    inner = '<iframe id="busiIframe" srcdoc="' + escape(html, quote=True) + '"></iframe>'
    local_page.set_content('<iframe name="layui-layer-iframe1" srcdoc="'
                           + escape(inner, quote=True) + '"></iframe>')


@pytest.mark.parametrize("pending", ["hidden_form", "loading"])
def test_business_frame_waits_for_visible_form_and_loading_to_finish(
    local_page, tmp_path, pending,
):
    hidden = 'style="display:none"' if pending == "hidden_form" else ""
    _set_business_frame(local_page, f'''
      <sipub-person-quick-search {hidden}><input></sipub-person-quick-search>
      <div class="loading-mask">正在加载</div>
      <div class="modal-content"><div class="modal-title">不符合办理条件</div>
        <div class="modal-body">经办人不能为空 移动电话格式错误</div></div>
      <script>setTimeout(() => {{
        document.querySelector('sipub-person-quick-search').style.display = 'block';
        document.querySelector('.loading-mask').remove();
        document.documentElement.dataset.ready = 'yes';
      }}, 350);</script>
    ''')
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    progress = []
    navigator = JshrssHallNavigator(local_page, settings, operation_name="退保",
                                   progress_callback=progress.append)
    frame = navigator.wait_for_business_frame("sipub-person-quick-search",
                                              description="退保业务窗口")
    assert frame.locator("input").is_visible()
    assert frame.locator(".loading-mask").count() == 0
    assert frame.locator("html").get_attribute("data-ready") == "yes"
    assert not any("检测到业务弹窗" in message for message in progress)
    assert "人员录入表单已就绪" in progress[-1]


def test_real_error_blocks_entry_even_when_person_form_exists(local_page, tmp_path):
    _set_business_frame(local_page, '''
      <sipub-person-quick-search><input></sipub-person-quick-search>
      <div class="modal in" role="dialog"><div class="modal-content">
        <div class="modal-title">不符合办理条件</div>
        <div class="modal-body">暂不受理本业务，请登记联系电话并打印告知书</div>
        <button class="btn-success" onclick="window.printClicked = true">确认打印告知书</button>
      </div></div>
    ''')
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    navigator = JshrssHallNavigator(local_page, settings, operation_name="退保")
    with pytest.raises(WebsiteStructureChangedError, match="不符合办理条件"):
        navigator.wait_for_business_frame("sipub-person-quick-search",
                                         description="退保业务窗口")
    assert all(frame.evaluate("window.printClicked !== true")
               for frame in local_page.frames)


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
