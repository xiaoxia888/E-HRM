from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date, datetime
import json
from pathlib import Path

from ehrm.core.error_catalog import display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import (
    application_runtime_root,
    resolve_runtime_path,
)
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings, select_ai_model
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.task_service import ErpTaskQueryService


ERP_SOCIAL_TRANSACTION_TYPES = ("社保咨询", "单位社保权益单")


class _ClassificationArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if parsed.code:
            if parsed.start_date or parsed.end_date:
                self.error("--code 不能与日期范围同时使用")
        elif not parsed.start_date or not parsed.end_date:
            self.error("请提供 --code，或同时提供 --start-date 和 --end-date")
        if parsed.start_date:
            try:
                start = date.fromisoformat(parsed.start_date)
                end = date.fromisoformat(parsed.end_date)
            except ValueError:
                self.error("日期必须使用 YYYY-MM-DD 格式")
            if start > end:
                self.error("开始日期不能晚于结束日期")
        return parsed


def _parser() -> argparse.ArgumentParser:
    parser = _ClassificationArgumentParser(
        prog="run_erp_business_classification",
        description="查询 ERP 社保申请并使用大模型判断业务类型；不执行参保、停保或权益单打印",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument("--code", "--application-code", default="", help="ERP 申请编号")
    parser.add_argument("--start-date", default="", help="申请开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="申请结束日期 YYYY-MM-DD，包含当天")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-tasks", type=int, default=0, help="最多分析条数；0 表示全部")
    parser.add_argument("--model-profile", default="", help="可选模型配置 ID")
    parser.add_argument(
        "--reasoning-mode",
        choices=[mode.value for mode in ReasoningMode],
        help="可选模型推理模式",
    )
    parser.add_argument("--output", type=Path, help="可选 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_tasks < 0:
        print("任务执行失败：--max-tasks 不能小于 0")
        return 2
    try:
        runtime_root = application_runtime_root(args.config)
        settings = load_settings(args.config, data_root=runtime_root)
        if args.model_profile:
            settings = select_ai_model(
                settings,
                args.model_profile,
                reasoning_mode=args.reasoning_mode,
            )
        mode = args.reasoning_mode or settings.ai.default_reasoning_mode
        if mode not in settings.ai.reasoning_modes:
            raise ValueError(f"当前模型不支持推理模式：{mode}")
        logger = configure_logging(runtime_root / "logs")
        query_service = ErpTaskQueryService(settings, logger, progress_callback=print)
        records = []
        seen_ids: set[str] = set()
        for transaction_type in ERP_SOCIAL_TRANSACTION_TYPES:
            result = query_service.query_tasks(
                transaction_type,
                application_code=args.code,
                start_date=args.start_date,
                end_date=args.end_date,
                page_size=args.page_size,
            )
            for record in result.records:
                identity = record.id or record.code
                if identity in seen_ids:
                    continue
                seen_ids.add(identity)
                records.append(record)
        if args.max_tasks:
            records = records[: args.max_tasks]

        report_records: list[dict[str, object]] = []
        classified = unclear = failed = 0
        classifier = None
        if records:
            classifier = OllamaTaskExtractionClient(settings.ai, logger)
            classifier.ensure_available()
        for index, record in enumerate(records, start=1):
            print(f"正在判断 {index}/{len(records)}：{record.code}")
            item: dict[str, object] = {
                "erp_record_id": record.id,
                "application_code": record.code,
                "application_date": record.initiated_date,
                "erp_transaction_type": record.transaction_type,
                "title": record.title,
                "description": record.description,
            }
            try:
                assert classifier is not None
                decision = classifier.classify(record, mode)
                item.update(asdict(decision))
                if decision.classified:
                    classified += 1
                else:
                    unclear += 1
                print(
                    f"  → {decision.business_type}"
                    + (f"（依据：{decision.evidence}）" if decision.evidence else "")
                )
            except EhrmError as exc:
                failed += 1
                item.update({"business_type": None, "classified": False, "error": exc.message})
                print(f"  → 失败：{display_message(exc.code, exc.message)}")
            report_records.append(item)

        report = {
            "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "query": {
                "application_code": args.code,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "transaction_types": list(ERP_SOCIAL_TRANSACTION_TYPES),
            },
            "summary": {
                "total": len(records),
                "classified": classified,
                "unclear": unclear,
                "failed": failed,
            },
            "records": report_records,
        }
        print(
            f"分析结束：共 {len(records)} 条，明确分类 {classified} 条，"
            f"保留原始类型 {unclear} 条，失败 {failed} 条"
        )
        if args.output is not None:
            output_path = resolve_runtime_path(args.output, runtime_root)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"JSON 已保存：{output_path}")
        return 3 if failed else 0
    except EhrmError as exc:
        print(display_message(exc.code, exc.message))
        if exc.details:
            print(exc.details)
        return 2
    except (OSError, ValueError) as exc:
        print(f"任务执行失败：{exc}")
        return 2
    except KeyboardInterrupt:
        print("\n用户已取消 ERP 业务分类")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
