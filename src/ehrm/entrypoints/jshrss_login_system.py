from __future__ import annotations

from ehrm.core.auth_repository import AuthenticationRepository, SystemAccount, SystemType


LOGIN_SYSTEMS = {
    "江苏智慧人社账号": "direct",
    "江苏政务服务平台账号": "government_sso",
}
DEFAULT_LOGIN_SYSTEM = "江苏智慧人社账号"


def select_login_account(
    repository: AuthenticationRepository,
    system_name: str,
) -> SystemAccount:
    expected_method = LOGIN_SYSTEMS.get(system_name)
    if expected_method is None:
        raise ValueError(f"不支持的智慧人社登录系统：{system_name}")
    account = next(
        (
            item
            for item in repository.list_accounts(SystemType.JSHRSS)
            if str(item.profile.get("login_method") or "direct")
            == expected_method
        ),
        None,
    )
    if account is None:
        raise ValueError(
            f"系统设置中尚未配置“{system_name}”，请先保存该系统账号"
        )
    if not account.password or (
        expected_method == "direct" and not account.secondary_account
    ):
        raise ValueError(
            f"“{system_name}”登录信息不完整，请先在系统设置中补充账号信息"
        )
    return account


def login_method_label(login_method: str) -> str:
    if login_method == "government_sso":
        return "江苏政务服务平台"
    return "智慧人社直登"

