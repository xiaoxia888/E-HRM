"""Checks SQL Server runtime prerequisites before building Windows packages."""

from __future__ import annotations

import argparse
from pathlib import Path

import pyodbc

from ehrm.core.settings import load_settings
from ehrm.modules.erp.person_database import (
    _connect,
    validate_odbc_driver_available,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.toml"),
    )
    parser.add_argument(
        "--check-database",
        action="store_true",
        help="also open and close one ERP/NCC SQL Server connection",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    settings = load_settings(args.config)
    validate_odbc_driver_available(
        settings.erp_database.driver,
        registered_drivers=pyodbc.drivers(),
    )
    if args.check_database:
        connection = _connect(settings.erp_database)
        connection.close()
    print(f"pyodbc 版本：{pyodbc.version}")
    print(f"SQL Server ODBC 驱动：{settings.erp_database.driver}")
    if args.check_database:
        print("ERP/NCC 人员数据库连接验证通过")
    else:
        print("SQL Server 打包运行依赖验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
