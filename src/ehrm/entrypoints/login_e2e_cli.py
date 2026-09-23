from __future__ import annotations

import argparse
import getpass
import os
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import Error as PlaywrightError

from ehrm.browser.access_token import (
    AccessTokenManager,
    MemoryAccessTokenStore,
    create_rights_access_token_manager,
)
from ehrm.browser.login import LoginService
from ehrm.browser.manager import BrowserManager
from ehrm.browser.captcha_policy import is_allowed_host_url
from ehrm.core.exceptions import EhrmError
from ehrm.core.auth_repository import AuthenticationRepository, SystemAccount, SystemType
from ehrm.core.settings import AppSettings, DEFAULT_SETTINGS_PATH, load_settings
from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.web.settings_service import WebSettingsService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ehrm-login-e2e",
        description="按配置的浏览器模式运行一次完整登录端到端验证。",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument(
        "--account-id",
        type=int,
        help="使用系统设置中已保存的智慧人社账号 ID（推荐）",
    )
    parser.add_argument(
        "--list-accounts",
        action="store_true",
        help="列出可测试的智慧人社账号，不启动浏览器",
    )
    parser.add_argument(
        "--reuse-profile",
        action="store_true",
        help="复用配置中的浏览器资料；默认使用全新临时资料以确保完整登录流程",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="凭据缺失时直接失败，适用于 CI",
    )
    parser.add_argument(
        "--ignore-https-errors",
        action="store_true",
        help="仅用于自签名证书的测试环境",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="只检查配置，不启动浏览器",
    )
    parser.add_argument(
        "--close-on-finish",
        action="store_true",
        help="测试结束后自动关闭浏览器；默认保留浏览器供人工检查",
    )
    parser.add_argument(
        "--diagnostic",
        type=Path,
        default=Path("output/login-e2e-failure.png"),
        help="登录失败时保存页面截图的位置",
    )
    return parser


def _credential(
    *,
    configured: str,
    environment_name: str,
    prompt: str,
    secret: bool,
    no_prompt: bool,
) -> str:
    value = configured or os.getenv(environment_name, "")
    if value:
        return value
    if no_prompt:
        raise ValueError(f"缺少环境变量 {environment_name}")
    entered = getpass.getpass(prompt) if secret else input(prompt)
    value = entered.strip()
    if not value:
        raise ValueError(f"{prompt.rstrip('：')}不能为空")
    return value


@contextmanager
def _isolated_settings(
    settings: AppSettings, *, reuse_profile: bool
) -> Iterator[AppSettings]:
    if reuse_profile:
        yield settings
        return
    with TemporaryDirectory(prefix="ehrm-login-e2e-") as temporary:
        root = Path(temporary)
        browser = replace(
            settings.browser,
            silent_session_check=False,
            user_data_dir=root / "browser-profile",
            storage_state_path=root / "storage-state.json",
        )
        yield replace(settings, browser=browser)


def _save_diagnostic(page, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)
        print(f"失败截图：{path.resolve()}")
    except (OSError, PlaywrightError) as exc:
        print(f"失败截图保存失败：{exc}")


def _hold_browser_open(*, close_on_finish: bool) -> None:
    if close_on_finish:
        return
    try:
        input("浏览器将保持打开，检查完成后按 Enter 关闭浏览器并退出……")
    except EOFError:
        print("标准输入不可用，无法等待人工确认。")


def _failure_text(exc: BaseException) -> str:
    failure = str(exc)
    details = getattr(exc, "details", None)
    if details and details != failure:
        failure += f"；{details}"
    return failure


def _print_targets(settings: AppSettings) -> None:
    browser_name = settings.browser.channel or settings.browser.engine
    print(
        f"浏览器：{browser_name}（engine={settings.browser.engine}, "
        f"channel={settings.browser.channel or '内置'}, "
        f"mode={'无头' if settings.browser.headless else '可见'}）"
    )
    login_method = settings.rights_credentials.login_method
    login_url = (
        settings.government_login.login_url
        if login_method == "government_sso"
        else settings.site.login_url
    )
    print(
        "登录方式："
        + ("江苏政务服务平台" if login_method == "government_sso" else "智慧人社直登")
    )
    print(f"登录地址：{login_url}")
    target_url = (
        settings.government_login.target_url
        if login_method == "government_sso"
        else settings.site.rights_statement_url
    )
    print(f"登录成功判定页：{target_url}")
    pacing = settings.browser.pacing
    if pacing.enabled:
        print(
            "DOM 操作随机等待："
            f"{pacing.min_delay_ms}–{pacing.max_delay_ms} 毫秒"
        )
    else:
        print("DOM 操作随机等待：已关闭")


def _mask(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 4:
        return "*" * len(normalized)
    return f"{normalized[:2]}****{normalized[-2:]}"


def _list_accounts(repository: AuthenticationRepository) -> None:
    accounts = repository.list_accounts(SystemType.JSHRSS)
    if not accounts:
        print("尚未保存智慧人社账号，请先在系统设置中维护。")
        return
    print("可测试的智慧人社账号：")
    for account in accounts:
        method = str(account.profile.get("login_method") or "direct")
        method_label = "江苏政务服务平台" if method == "government_sso" else "智慧人社直登"
        default = "，默认" if account.is_default else ""
        print(
            f"  ID={account.id}  {account.display_name or '未命名账号'}  "
            f"{_mask(account.account)}  {method_label}{default}"
        )


def _selected_account(
    repository: AuthenticationRepository,
    account_id: int | None,
) -> SystemAccount | None:
    if account_id is None:
        return None
    account = repository.get_account_by_id(account_id)
    if account is None or account.system_type is not SystemType.JSHRSS:
        raise ValueError(f"智慧人社账号 ID={account_id} 不存在")
    return account


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        diagnostic_path = resolve_runtime_path(args.diagnostic, runtime_root)
    except EhrmError as exc:
        print(f"配置加载失败：{exc}")
        return 2

    repository = AuthenticationRepository(settings.auth_database_path)
    if args.list_accounts:
        _list_accounts(repository)
        return 0

    try:
        selected_account = _selected_account(repository, args.account_id)
    except ValueError as exc:
        print(f"账号选择失败：{exc}")
        return 2
    settings = WebSettingsService(settings, runtime_root).runtime_settings(
        rights_account=selected_account,
    )

    if args.check_config:
        print("登录 E2E 配置检查通过")
        _print_targets(settings)
        print(f"验证码自动化：{'启用' if settings.captcha.enabled else '停用'}")
        print("允许主机：" + "、".join(settings.captcha.allowed_hosts))
        return 0

    _print_targets(settings)

    credentials = settings.rights_credentials
    try:
        credit_code = _credential(
            configured=credentials.credit_code,
            environment_name=credentials.credit_code_env,
            prompt=(
                "政务服务平台登录名："
                if credentials.login_method == "government_sso"
                else "统一信用代码："
            ),
            secret=False,
            no_prompt=args.no_prompt,
        )
        mobile = credentials.mobile
        if credentials.login_method != "government_sso":
            mobile = _credential(
                configured=credentials.mobile,
                environment_name=credentials.mobile_env,
                prompt="证件号码/移动电话：",
                secret=False,
                no_prompt=args.no_prompt,
            )
        password = _credential(
            configured=credentials.password,
            environment_name=credentials.password_env,
            prompt="登录密码：",
            secret=True,
            no_prompt=args.no_prompt,
        )
    except ValueError as exc:
        print(f"凭据准备失败：{exc}")
        return 2

    try:
        with _isolated_settings(
            settings, reuse_profile=args.reuse_profile
        ) as runtime_settings:
            if credentials.account_id is not None:
                access_tokens = create_rights_access_token_manager(
                    runtime_settings.auth_database_path,
                    credit_code,
                    mobile,
                    password=password,
                    account_id=credentials.account_id,
                )
            elif credentials.login_method == "government_sso":
                access_tokens = AccessTokenManager(
                    "government-sso-e2e",
                    MemoryAccessTokenStore(),
                )
            else:
                access_tokens = create_rights_access_token_manager(
                    runtime_settings.auth_database_path,
                    credit_code,
                    mobile,
                    password=password,
                )
            authentication_url = (
                runtime_settings.government_login.login_url
                if credentials.login_method == "government_sso"
                else runtime_settings.site.login_url
            )
            with BrowserManager(
                runtime_settings.browser,
                ignore_https_errors=args.ignore_https_errors,
                stealth_enabled=(
                    runtime_settings.captcha.stealth_enabled
                    and is_allowed_host_url(
                        authentication_url,
                        runtime_settings.captcha.allowed_hosts,
                    )
                ),
            ) as browser:
                page = browser.page
                service = LoginService(
                    page,
                    runtime_settings,
                    access_token_manager=access_tokens,
                )
                try:
                    service.ensure_authenticated(
                        username=credit_code,
                        mobile=mobile,
                        password=password,
                    )
                except (EhrmError, PlaywrightError) as exc:
                    try:
                        diagnostic_page = browser.page
                    except (RuntimeError, PlaywrightError):
                        diagnostic_page = service.page
                    _save_diagnostic(diagnostic_page, diagnostic_path)
                    print(f"完整登录 E2E 验证失败：{_failure_text(exc)}")
                    _hold_browser_open(close_on_finish=args.close_on_finish)
                    return 1
                if credentials.login_method == "government_sso":
                    authenticated = service.is_government_view_ready()
                else:
                    authenticated = service.is_authenticated()
                    if not authenticated:
                        if access_tokens.get_token() is not None:
                            print("已获取 Access-Token，正在确认最终业务页面……")
                        try:
                            authenticated = service.check_authenticated()
                        except (EhrmError, PlaywrightError):
                            authenticated = False
                if not authenticated:
                    try:
                        page = browser.page
                    except (RuntimeError, PlaywrightError):
                        page = service.page
                    _save_diagnostic(page, diagnostic_path)
                    print("登录流程已取得响应，但未能进入最终判定页面")
                    _hold_browser_open(close_on_finish=args.close_on_finish)
                    return 1
                if access_tokens.get_token() is None:
                    _save_diagnostic(service.page, diagnostic_path)
                    print("已进入业务页面，但未获取到智慧人社 Access-Token")
                    _hold_browser_open(close_on_finish=args.close_on_finish)
                    return 1
                print("完整登录 E2E 验证通过")
                print(f"最终页面：{service.page.url}")
                _hold_browser_open(close_on_finish=args.close_on_finish)
                return 0
    except (EhrmError, OSError, PlaywrightError) as exc:
        print(f"完整登录 E2E 验证失败：{_failure_text(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
