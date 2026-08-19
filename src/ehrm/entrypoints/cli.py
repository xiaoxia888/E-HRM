from __future__ import annotations

import argparse
import getpass
import os
import subprocess
from pathlib import Path

from ehrm.application import EhrmApplication, RIGHTS_STATEMENT_DOWNLOAD
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.settings import load_settings
from ehrm.modules.rights_statement.models import RightsStatementQuery


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ehrm", description="E-HRM 自动化工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="查询并下载单位权益单")
    download.add_argument("--config", type=Path, default=Path("config/settings.toml"))
    download.add_argument("--start-month", required=True, help="格式 YYYY-MM")
    download.add_argument("--end-month", required=True, help="格式 YYYY-MM")
    download.add_argument("--insurance", required=True, help="险种显示名称")
    download.add_argument("--name", required=True, help="员工姓名")
    download.add_argument("--output-dir", type=Path, required=True)
    download.add_argument(
        "--ask-password", action="store_true", help="从终端安全读取密码"
    )

    record = subparsers.add_parser("record", help="录制真实页面操作流程")
    record.add_argument("--url", required=True)
    record.add_argument(
        "--profile", type=Path, default=Path("data/codegen-profile")
    )
    record.add_argument(
        "--output", type=Path, default=Path("artifacts/recorded_flow.py")
    )
    return parser


def _record(url: str, profile: Path, output: Path) -> int:
    profile.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "playwright",
        "codegen",
        "--target=python",
        f"--user-data-dir={profile.resolve()}",
        f"--output={output.resolve()}",
        url,
    ]
    print("录制窗口已启动。请完成登录、验证码、查询、生成和下载全流程。")
    print("关闭录制窗口后，生成代码将保存到：", output.resolve())
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "record":
        return _record(args.url, args.profile, args.output)

    try:
        settings = load_settings(args.config)
        username = os.getenv("EHRM_USERNAME")
        password = os.getenv("EHRM_PASSWORD")
        if args.ask_password:
            username = username or input("登录账号：").strip()
            password = getpass.getpass("登录密码：")

        request = RightsStatementQuery(
            start_month=args.start_month,
            end_month=args.end_month,
            insurance_type=args.insurance,
            employee_name=args.name,
            output_dir=args.output_dir.expanduser().resolve(),
        )
        result = EhrmApplication(settings, configure_logging()).run(
            RIGHTS_STATEMENT_DOWNLOAD,
            request,
            username=username,
            password=password,
        )
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2

    print(f"[{result.code}] {result.message}")
    if result.file_path:
        print(result.file_path)
    if result.diagnostic_path:
        print("诊断截图：", result.diagnostic_path)
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
