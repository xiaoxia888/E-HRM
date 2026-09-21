from pathlib import Path
from unittest.mock import Mock, patch

from ehrm.browser.smart_wait import WaitResult
from ehrm.core.settings import load_settings
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
