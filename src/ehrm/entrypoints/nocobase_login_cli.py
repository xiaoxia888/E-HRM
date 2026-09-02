from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from ehrm.browser.access_token import AccessTokenManager
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.nocobase import (
    NocoBaseAuthClient,
    NocoBaseCredentials,
    NocoBaseSystemTokenStore,
    build_nocobase_token_account_key,
)
from ehrm.modules.nocobase.exceptions import NocoBaseAuthenticationError
from ehrm.modules.nocobase.jwt_token import decode_jwt_claims


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测试 NocoBase 登录接口并校验返回的 JWT，不启动浏览器。"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="系统配置文件",
    )
    parser.add_argument("--account", help="登录账号；默认读取配置指定的环境变量")
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="忽略本地未过期 Token，强制调用登录接口",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        account = (
            args.account
            or os.getenv(settings.nocobase.account_env, "")
        ).strip()
        if not account:
            account = input("NocoBase 账号：").strip()
        token_manager = AccessTokenManager(
            build_nocobase_token_account_key(
                settings.nocobase.base_url,
                account,
            ),
            NocoBaseSystemTokenStore(),
        )
        if args.force_login:
            token_manager.invalidate()
        else:
            persisted = token_manager.get_token()
            if persisted:
                try:
                    claims = decode_jwt_claims(persisted)
                except NocoBaseAuthenticationError:
                    token_manager.invalidate()
                else:
                    if not claims.is_expired():
                        print("NocoBase 本地 Token 有效，无需重新登录")
                        print(f"用户 ID：{claims.user_id}")
                        print(
                            "Token 到期时间："
                            f"{claims.expires_at_datetime.astimezone()}"
                        )
                        return 0
                    token_manager.invalidate()

        password = os.getenv(settings.nocobase.password_env, "")
        if not password:
            password = input("NocoBase 密码（输入内容可见）：")
        credentials = NocoBaseCredentials(account=account, password=password)
        with sync_playwright() as playwright:
            request = playwright.request.new_context()
            try:
                result = NocoBaseAuthClient(
                    settings.nocobase,
                    request,
                    logging.getLogger("ehrm.nocobase-login-test"),
                ).sign_in(credentials)
                token_manager.save_token(result.token)
            finally:
                request.dispose()
    except Exception as exc:
        message = getattr(exc, "message", str(exc))
        details = getattr(exc, "details", None)
        print(f"NocoBase 登录测试失败：{message}")
        if details:
            print(f"详细信息：{details}")
        return 1

    print("NocoBase 登录测试成功")
    print(f"用户：{result.user.nickname or result.user.username}")
    print(f"用户 ID：{result.user.user_id}")
    print(f"Token 到期时间：{result.claims.expires_at_datetime.astimezone()}")
    print("Authorization Token：已获取（内容不输出）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
