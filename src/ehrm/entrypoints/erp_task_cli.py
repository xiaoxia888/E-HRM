from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import (
    application_runtime_root,
    configure_application_identity,
    resolve_runtime_path,
)
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings
from ehrm.modules.erp.task_service import ErpTaskQueryService
from ehrm.modules.erp.models import ErpTaskStatus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_erp_task_query",
        description="按事务类型分页查询 ERP 人力资源事务申请",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SETTINGS_PATH,
        help="配置文件路径",
    )
    parser.add_argument(
        "--transaction-type",
        required=True,
        help="事务类型，按 ERP 实际值精确查询，例如：社保咨询",
    )
    parser.add_argument(
        "--status",
        type=int,
        choices=[status.value for status in ErpTaskStatus],
        help=(
            "可选申请状态：0新增、15待送审、20审批中、"
            "35生效、40终止、50批准"
        ),
    )
    parser.add_argument(
        "--application-code",
        "--code",
        default="",
        help="可选：申请编号精确匹配，例如 RLSQ20260818-0004",
    )
    parser.add_argument(
        "--start-date",
        default="",
        help="可选：申请开始日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        default="",
        help="可选：申请结束日期，格式 YYYY-MM-DD，包含当天",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="每页记录数，范围 1–500，默认 50",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="可选：将完整查询结果保存为 JSON 文件",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        application = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        configure_application_identity(application)
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        logger = configure_logging(runtime_root / "logs")
        result = ErpTaskQueryService(
            settings,
            logger,
            progress_callback=print,
        ).query_tasks(
            args.transaction_type,
            status=args.status,
            application_code=args.application_code,
            start_date=args.start_date,
            end_date=args.end_date,
            page_size=args.page_size,
        )

        status_filter = (
            ErpTaskStatus.display(result.status.value)
            if result.status is not None
            else "全部"
        )
        print(
            f"\n查询结果：事务类型={result.transaction_type}，"
            f"状态={status_filter}，"
            f"编号={result.application_code or '全部'}，"
            f"申请日期={result.start_date or '不限'} 至 "
            f"{result.end_date or '不限'}，"
            f"共 {len(result.records)} 条，读取 {result.pages_fetched} 页"
        )
        for index, record in enumerate(result.records, start=1):
            description = record.description.replace("\n", " ")
            if len(description) > 100:
                description = f"{description[:100]}…"
            print(
                f"{index}. {record.code or '无编号'} | "
                f"{record.initiated_date or '无发起日期'} | "
                f"{record.title or '无标题'}"
            )
            print(
                f"   发起人：{record.originator or '-'} | "
                f"部门：{record.department or '-'} | "
                f"状态：{ErpTaskStatus.display(record.status)}"
            )
            print(f"   描述：{description or '-'}")

        if args.output is not None:
            output_path = resolve_runtime_path(args.output, runtime_root)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "queried_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "transaction_type": result.transaction_type,
                "status": result.status.value if result.status is not None else None,
                "status_label": result.status.label if result.status is not None else "",
                "application_code": result.application_code,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "total_count": result.total_count,
                "pages_fetched": result.pages_fetched,
                "records": [asdict(record) for record in result.records],
            }
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\nJSON 已保存：{output_path}")
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
        print("\n用户已取消 ERP 任务查询")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
