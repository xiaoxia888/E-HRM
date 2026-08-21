from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_data_root, configure_application_identity
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.erp.person_service import ErpPersonLookupService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_erp_person_query",
        description="按姓名查询 ERP 人员库并读取身份证信息",
    )
    parser.add_argument("name", help="人员姓名，使用精确匹配")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="配置文件路径",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选 JSON 输出路径；文件中包含完整身份证号，请妥善保管",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        application = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        configure_application_identity(application)
        runtime_root = application_data_root()
        settings = load_settings(args.config, data_root=runtime_root)
        logger = configure_logging(runtime_root / "logs")
        records = ErpPersonLookupService(
            settings,
            logger,
            progress_callback=print,
        ).lookup_names([args.name]).get(args.name.strip(), ())
        print(f"查询完成：{args.name.strip()}，精确匹配 {len(records)} 人")
        for index, record in enumerate(records, start=1):
            print(
                f"{index}. {record.employee_code or '-'} | {record.name} | "
                f"{record.department or '-'} | 身份证 {_mask(record.identity_number)}"
            )
        if args.output is not None:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(
                    [
                        {
                            "id": record.id,
                            "employee_code": record.employee_code,
                            "name": record.name,
                            "identity_number": record.identity_number,
                            "department": record.department,
                            "company": record.company,
                            "status": record.status,
                            "is_quit": record.is_quit,
                        }
                        for record in records
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"完整结果已保存：{output}")
        return 0 if records else 3
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2
    except KeyboardInterrupt:
        print("\n用户已取消 ERP 人员查询")
        return 130


def _mask(identity: str) -> str:
    if len(identity) <= 10:
        return identity or "-"
    return identity[:6] + "*" * (len(identity) - 10) + identity[-4:]


if __name__ == "__main__":
    raise SystemExit(main())
