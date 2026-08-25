from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_data_root, configure_application_identity
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings, select_ai_model
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService
from ehrm.modules.erp.models import ErpTaskStatus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_erp_task_extraction",
        description="按条件分页查询 ERP 任务并顺序调用大模型解析权益单人员",
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
        help="事务类型，例如：社保咨询",
    )
    parser.add_argument(
        "--status",
        type=int,
        choices=[status.value for status in ErpTaskStatus],
        help="可选状态：0新增、15待送审、20审批中、35生效、40终止、50批准",
    )
    parser.add_argument(
        "--application-code",
        "--code",
        default="",
        help="可选：申请编号精确匹配",
    )
    parser.add_argument("--start-date", default="", help="可选开始日期 YYYY-MM-DD")
    parser.add_argument(
        "--end-date",
        default="",
        help="可选结束日期 YYYY-MM-DD，包含当天",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=50,
        help="ERP 每页记录数，范围 1–500，默认 50",
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=0,
        help="最多解析多少条；0 表示解析查询到的全部任务",
    )
    parser.add_argument(
        "--model-profile",
        default="",
        help="可选模型配置 ID，例如 qwen3_5_9b；默认读取配置",
    )
    parser.add_argument(
        "--reasoning-mode",
        choices=[mode.value for mode in ReasoningMode],
        help="推理模式：依所选模型支持 off/on 或 off/low/medium/max",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出 JSON 路径；不填写时保存到 output 目录",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        application = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        configure_application_identity(application)
        runtime_root = application_data_root()
        settings = load_settings(args.config, data_root=runtime_root)
        if args.model_profile:
            settings = select_ai_model(
                settings,
                args.model_profile,
                reasoning_mode=args.reasoning_mode,
            )
        logger = configure_logging(runtime_root / "logs")
        payload = ErpTaskExtractionService(
            settings,
            logger,
            progress_callback=print,
        ).run(
            args.transaction_type,
            status=args.status,
            application_code=args.application_code,
            start_date=args.start_date,
            end_date=args.end_date,
            page_size=args.page_size,
            max_tasks=args.max_tasks,
            reasoning_mode=args.reasoning_mode,
        )
        output_path = _output_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary = payload["summary"]
        assert isinstance(summary, dict)
        print(
            "\n解析完成："
            f"任务成功 {summary['tasks_succeeded']}，"
            f"失败 {summary['tasks_failed']}，"
            f"拆分打印组 {summary['print_groups_extracted']}，"
            f"人员记录 {summary['people_extracted']}，"
            f"需人工复核 {summary['tasks_needing_review']}"
        )
        print(f"JSON 已保存：{output_path}")
        return 0 if summary["tasks_failed"] == 0 else 3
    except EhrmError as exc:
        message = display_message(exc.code, exc.message)
        print(message)
        if exc.message != message:
            print(exc.message)
        if exc.details:
            print(exc.details)
        return 2
    except (OSError, ValueError) as exc:
        print(f"任务执行失败：{exc}")
        return 2
    except KeyboardInterrupt:
        print("\n用户已取消 ERP 大模型解析")
        return 130


def _output_path(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    filename = f"erp_task_extraction_{datetime.now():%Y%m%d_%H%M%S}.json"
    return (Path("output") / filename).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
