from __future__ import annotations

import argparse
import logging
from pathlib import Path

from playwright.sync_api import sync_playwright

from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.runtime import application_runtime_root
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.nocobase import (
    NocoBaseAuthClient,
    NocoBaseCredentials,
    create_nocobase_token_manager,
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
    parser.add_argument(
        "--account",
        help="选择系统设置中已保存的登录账号；默认使用默认账号",
    )
    parser.add_argument(
        "--force-login",
        action="store_true",
        help="忽略本地未过期 Token，强制调用登录接口",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(
            args.config,
            data_root=application_runtime_root(args.config),
        )
        repository = AuthenticationRepository(settings.auth_database_path)
        default_account = repository.get_default_account(SystemType.NOCOBASE)
        saved_account = (
            repository.get_account(SystemType.NOCOBASE, args.account)
            if args.account
            else default_account
        )
        if saved_account is None:
            raise ValueError(
                "NocoBase 账号未配置，请先在“系统设置 → 账户与连接”中保存账号"
            )
        account = saved_account.account
        password = saved_account.password
        if not password:
            raise ValueError(
                "所选 NocoBase 账号缺少密码，请先在系统设置中补充"
            )
        token_manager = create_nocobase_token_manager(
            settings.auth_database_path,
            account,
            password=password,
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

        credentials = NocoBaseCredentials(account=account, password=password)
        with sync_playwright() as playwright:
            request = playwright.request.new_context()
            try:
                result = NocoBaseAuthClient(
                    settings.nocobase,
                    request,
                    logging.getLogger("ehrm.nocobase-login-test"),
                ).sign_in(credentials)
                repository.save_account(
                    SystemType.NOCOBASE,
                    account,
                    password,
                    display_name=result.user.nickname or result.user.username,
                    profile={
                        "id": result.user.user_id,
                        "username": result.user.username,
                        "nickname": result.user.nickname,
                        "erp_userId": result.user.erp_user_id,
                    },
                )
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
