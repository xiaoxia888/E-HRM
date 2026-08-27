from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_runtime_root, configure_application_identity
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.erp.client import ErpApplicationClient, ErpAttachmentClient
from ehrm.modules.erp.credentials import resolve_erp_credentials
from ehrm.modules.erp.session import ErpSession


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_erp_upload",
        description="ERP 自动登录、申请查询和附件上传联调工具",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="只验证 ERP 自动登录")

    query = commands.add_parser("query", help="查询申请编号并输出业务记录 ID")
    query.add_argument("application_code", help="例如 RLSQ20260819-0001")

    upload = commands.add_parser(
        "upload",
        help="查询申请并上传一个 PDF、Word 或 Excel 附件",
    )
    upload.add_argument("application_code", help="例如 RLSQ20260819-0001")
    upload.add_argument(
        "file",
        type=Path,
        help="待上传附件（pdf/doc/docx/xls/xlsx/xlsm）",
    )

    delete = commands.add_parser("delete", help="按申请编号和完整文件名删除附件")
    delete.add_argument("application_code", help="例如 RLSQ20260819-0001")
    delete.add_argument("filename", help="完整文件名，例如 单位权益单.pdf")
    delete.add_argument(
        "--yes",
        action="store_true",
        help="跳过交互确认；自动化调用时使用",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        application = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        configure_application_identity(application)
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        credentials = resolve_erp_credentials(settings)
        logger = configure_logging(runtime_root / "logs")
        with ErpSession(settings, logger) as session:
            print("正在检查 ERP 登录状态……")
            session.ensure_authenticated(credentials)
            print("ERP 登录状态有效")
            if args.command == "login":
                return 0

            application = ErpApplicationClient(
                settings.erp,
                session.page,
                session.request,
                logger,
            ).find_by_code(args.application_code)
            print(f"查询成功：{application.code} -> {application.id}")
            if args.command == "query":
                return 0

            attachment_client = ErpAttachmentClient(
                settings.erp,
                session.page,
                session.request,
                logger,
            )
            if args.command == "delete":
                target = attachment_client.find_by_filename(
                    application,
                    args.filename,
                )
                full_name = f"{target.name}{target.extension}"
                print(
                    f"待删除：申请 {application.code}，附件 {full_name}，"
                    f"{target.size} 字节"
                )
                if not args.yes:
                    answer = input("确认删除？该操作不可恢复 [y/N]：").strip().lower()
                    if answer not in {"y", "yes"}:
                        print("已取消删除")
                        return 1
                deleted = attachment_client.delete(application, target)
                print(f"删除成功：{deleted.name}{deleted.extension}")
                return 0

            attachment, chunks = attachment_client.upload(application, args.file)
            print(
                f"上传成功：{attachment.name}{attachment.extension}，"
                f"{attachment.size} 字节，{chunks} 个分片"
            )
            return 0
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2
    except KeyboardInterrupt:
        print("\n用户已取消 ERP 联调任务")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
