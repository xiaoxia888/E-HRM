from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ehrm.browser.smart_wait import WaitResult
from ehrm.core.exceptions import JshrssBusinessError
from ehrm.core.settings import load_settings
from ehrm.modules.jshrss_business_dialog import (
    BusinessDialog,
    BusinessDialogKind,
)
from ehrm.modules.jshrss_hall import JshrssHallNavigator


def test_shared_hall_navigation_guards_nanjing_and_searches_menu(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = Mock(url="https://rs.jshrss.jiangsu.gov.cn/index/")
    page.wait_for_timeout = lambda _milliseconds: None
    middle = page.frame_locator.return_value
    search = middle.get_by_role.return_value
    target_menu = Mock()
    navigator = JshrssHallNavigator(
        page,
        settings,
        operation_name="参保",
    )
    navigator.pacer.perform = Mock(side_effect=lambda action: action())
    navigator._first_visible = Mock(return_value=None)
    navigator._last_visible = Mock(return_value=target_menu)
    navigator.waiter.first = Mock(
        side_effect=[
            WaitResult("目标业务菜单", target_menu, 0),
            WaitResult("目标业务菜单", target_menu, 0),
        ]
    )

    with patch(
        "ehrm.modules.jshrss_hall.EmploymentTerminationPage"
    ) as region_guard:
        navigator.open_menu(
            "用人单位用工参保登记",
            category_text="社会保险登记",
        )

    region_guard.return_value.ensure_nanjing.assert_called_once_with()
    search.wait_for.assert_called_once_with(
        state="visible",
        timeout=settings.browser.action_timeout_ms,
    )
    search.fill.assert_called_once_with("用人单位用工参保登记")
    search.press.assert_called_once_with("Enter")
    target_menu.click.assert_called_once_with()


def test_business_frame_closes_multiple_information_dialogs_before_ready(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = Mock()
    page.wait_for_timeout = lambda _milliseconds: None
    navigator = JshrssHallNavigator(page, settings, operation_name="退保")
    first = BusinessDialog(
        Mock(), Mock(), "消息提示", "第一条提示", BusinessDialogKind.INFORMATION
    )
    second = BusinessDialog(
        Mock(), Mock(), "消息提示", "第二条提示", BusinessDialogKind.INFORMATION
    )
    business_frame = Mock()
    description = "用人单位退工停保登记业务窗口"
    navigator.waiter.first = Mock(
        side_effect=[
            WaitResult("智慧人社业务弹窗", first, 0),
            WaitResult("智慧人社业务弹窗", second, 0),
            WaitResult(description, business_frame, 0),
        ]
    )

    with patch("ehrm.modules.jshrss_hall.close_business_dialog") as close_dialog:
        result = navigator.wait_for_business_frame(
            "sipub-person-quick-search",
            description=description,
        )

    assert result is business_frame
    assert [call.args[0] for call in close_dialog.call_args_list] == [first, second]


def test_business_frame_closes_and_returns_recorded_outer_error(
    tmp_path: Path,
) -> None:
    settings = load_settings(Path("config/settings.toml"), data_root=tmp_path)
    page = Mock()
    page.wait_for_timeout = lambda _milliseconds: None
    navigator = JshrssHallNavigator(page, settings, operation_name="退保")
    error = BusinessDialog(
        Mock(),
        Mock(),
        "无法办理",
        "核心处理异常，详情请查看日志",
        BusinessDialogKind.ERROR,
    )
    navigator.waiter.first = Mock(
        return_value=WaitResult("智慧人社业务弹窗", error, 0)
    )

    with (
        patch("ehrm.modules.jshrss_hall.close_business_dialog") as close_dialog,
        pytest.raises(
            JshrssBusinessError,
            match="无法办理：核心处理异常，详情请查看日志",
        ),
    ):
        navigator.wait_for_business_frame(
            "sipub-person-quick-search",
            description="用人单位退工停保登记业务窗口",
        )

    close_dialog.assert_called_once()
