from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ehrm.core.runtime import application_runtime_root
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.nocobase.application_query_service import NocoBaseApplicationQueryService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用系统设置中保存的 API 密钥测试 NocoBase 查询权限，不登录、不启动浏览器。"
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH, help="系统配置文件")
    parser.add_argument("--account-id", type=int, help="选择已保存的 NocoBase 连接；默认使用默认连接")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = load_settings(args.config, data_root=application_runtime_root(args.config))
        NocoBaseApplicationQueryService(
            settings, logging.getLogger("ehrm.nocobase-connection-test")
        ).test_connection(account_id=args.account_id)
    except Exception as exc:
        print(f"NocoBase 连接测试失败：{getattr(exc, 'message', str(exc))}")
        if getattr(exc, "details", None):
            print(f"详细信息：{exc.details}")
        return 1
    print("NocoBase API 密钥连接测试成功，权益申请查询权限正常")
    print("测试仅查询一条申请，不保存或刷新登录 Token")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
