from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from pathlib import Path

from ehrm.application import EhrmApplication, RIGHTS_STATEMENT_DOWNLOAD
from ehrm.core.auth_repository import AuthenticationRepository, SystemType
from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import ConfigurationError, EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.rights_statement.models import RightsStatementQuery
from ehrm.web.settings_service import WebSettingsService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ehrm", description="E-HRM 自动化工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="查询并下载单位权益单")
    download.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
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
    record.add_argument(
        "--har", type=Path,
        help="录制完整网络请求与响应；关闭录制窗口后保存 HAR",
    )
    return parser


def _record(url: str, profile: Path, output: Path, har: Path | None = None) -> int:
    if har is not None and output.resolve() == har.resolve():
        print("录制脚本与 HAR 不能使用同一个文件路径")
        return 2
    profile.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if har is not None:
        har.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "playwright",
        "codegen",
        "--target=python",
        f"--user-data-dir={profile.resolve()}",
        f"--output={output.resolve()}",
    ]
    if har is not None:
        command.append(f"--save-har={har.resolve()}")
    command.append(url)
    print("录制窗口已启动。请完成需要分析的流程，结束后正常关闭录制窗口。")
    print("关闭录制窗口后，生成代码将保存到：", output.resolve())
    if har is not None:
        print("完整网络请求与响应将保存到：", har.resolve())
        print("HAR 可能含账号、令牌和人员信息；请勿直接分享原文件。")
    return subprocess.run(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config_path = getattr(args, "config", DEFAULT_SETTINGS_PATH)
    runtime_root = application_runtime_root(config_path)
    if args.command == "record":
        profile = resolve_runtime_path(args.profile, runtime_root)
        output = resolve_runtime_path(args.output, runtime_root)
        har = resolve_runtime_path(args.har, runtime_root) if args.har else None
        return _record(args.url, profile, output, har)

    try:
        settings = load_settings(args.config, data_root=runtime_root)
        saved_account = AuthenticationRepository(
            settings.auth_database_path
        ).get_default_account(SystemType.JSHRSS)
        settings = WebSettingsService(settings, runtime_root).runtime_settings(
            rights_account=saved_account,
        )
        credentials = settings.rights_credentials
        username = credentials.credit_code
        mobile = credentials.mobile
        password = credentials.password
        if args.ask_password:
            username = username or input("统一信用代码：").strip()
            mobile = mobile or input("移动号码：").strip()
            password = getpass.getpass("登录密码：")
        elif saved_account is None:
            raise ConfigurationError(
                "智慧人社账号未配置",
                details="请先在“系统设置 → 账户与连接”中保存智慧人社账号。",
            )

        request = RightsStatementQuery(
            start_month=args.start_month,
            end_month=args.end_month,
            insurance_type=args.insurance,
            employee_name=args.name,
            output_dir=resolve_runtime_path(args.output_dir, runtime_root),
        )
        result = EhrmApplication(
            settings,
            configure_logging(runtime_root / "logs"),
        ).run(
            RIGHTS_STATEMENT_DOWNLOAD,
            request,
            username=username,
            password=password,
            mobile=mobile,
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
