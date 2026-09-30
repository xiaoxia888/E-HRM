from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.logging import configure_logging
from ehrm.core.runtime import application_runtime_root, resolve_runtime_path
from ehrm.core.settings import DEFAULT_SETTINGS_PATH, load_settings, select_ai_model
from ehrm.modules.ai.business_classification import BusinessIntent
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.business_people_service import ErpBusinessPeopleService
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService
from ehrm.modules.erp.models import ErpTaskRecord
from ehrm.modules.erp.task_service import ErpTaskQueryService


ERP_SOCIAL_TRANSACTION_TYPES = ("社保咨询", "单位社保权益单")
_BUSINESS_INTENTS = {
    "用工参保登记": BusinessIntent.EMPLOYMENT_ENROLLMENT,
    "退工停保登记": BusinessIntent.EMPLOYMENT_TERMINATION,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_erp_social_analysis",
        description="按 ERP 申请编号查询、判断社保业务类型并解析人员；不执行参保、停保或打印",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument("--code", "--application-code", required=True, help="ERP 申请编号")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--model-profile", default="", help="可选模型配置 ID")
    parser.add_argument(
        "--reasoning-mode",
        choices=[mode.value for mode in ReasoningMode],
        help="可选模型推理模式",
    )
    parser.add_argument("--output", type=Path, help="可选 JSON 输出路径")
    return parser


def _find_task(
    query_service: ErpTaskQueryService,
    code: str,
    page_size: int,
) -> ErpTaskRecord:
    matches: dict[str, ErpTaskRecord] = {}
    for transaction_type in ERP_SOCIAL_TRANSACTION_TYPES:
        result = query_service.query_tasks(
            transaction_type,
            application_code=code,
            page_size=page_size,
        )
        for record in result.records:
            if record.code.strip() == code:
                matches.setdefault(record.id or record.code, record)
    if not matches:
        raise ValueError(f"未找到申请编号为 {code} 的 ERP 社保任务")
    if len(matches) > 1:
        raise ValueError(f"申请编号 {code} 对应多条 ERP 任务，请人工核对")
    return next(iter(matches.values()))


def _rights_people(payload: dict[str, object], code: str) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise ValueError("权益单解析未返回唯一的申请任务")
    task = tasks[0]
    if not isinstance(task, dict) or task.get("task_number") != code:
        raise ValueError("权益单解析结果与所选申请编号不一致")
    parse_status = task.get("parse_status")
    if not isinstance(parse_status, dict) or parse_status.get("code") != ErrorCode.SUCCESS.value:
        message = parse_status.get("message") if isinstance(parse_status, dict) else ""
        raise ValueError(f"权益单解析失败：{message or '未返回成功状态'}")
    requests = payload.get("rights_statement_requests")
    if not isinstance(requests, list):
        raise ValueError("权益单解析未返回人员列表")
    people: list[dict[str, object]] = []
    issues: list[dict[str, str]] = []
    for item in requests:
        if not isinstance(item, dict) or item.get("task_number") != code:
            raise ValueError("权益单人员结果与所选申请编号不一致")
        name = str(item.get("name") or "").strip()
        identity_match = item.get("identity_match")
        match = identity_match if isinstance(identity_match, dict) else {}
        match_code = str(match.get("code") or "")
        ambiguous = match_code == ErrorCode.ERP_PERSON_AMBIGUOUS.value
        people.append({
            "name": name,
            "identity_number": (
                "" if ambiguous else str(item.get("social_security_number") or "")
            ),
            "company": "" if ambiguous else str(match.get("company") or ""),
            "department": "" if ambiguous else str(match.get("department") or ""),
            "employee_code": "" if ambiguous else str(match.get("employee_code") or ""),
            "match_status": (
                "ambiguous" if ambiguous else (
                    "matched" if match_code == ErrorCode.SUCCESS.value else "needs_review"
                )
            ),
            "print_group": str(item.get("group_label") or ""),
        })
        if match_code and match_code != ErrorCode.SUCCESS.value:
            issues.append({
                "code": match_code,
                "person_name": name,
                "message": str(match.get("message") or match.get("details") or "请人工核对"),
            })
        for reason in item.get("review_reasons") or []:
            issues.append({
                "code": ErrorCode.AI_REVIEW_REQUIRED.value,
                "person_name": name,
                "message": str(reason),
            })
    extraction = task.get("extraction")
    if isinstance(extraction, dict) and extraction.get("needs_review"):
        reasons = extraction.get("review_reasons") or ["权益单解析结果需要人工复核"]
        for reason in reasons:
            if not any(issue["message"] == str(reason) for issue in issues):
                issues.append({
                    "code": ErrorCode.AI_REVIEW_REQUIRED.value,
                    "person_name": "",
                    "message": str(reason),
                })
    return people, issues


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    code = args.code.strip()
    if not code or not 1 <= args.page_size <= 500:
        print("任务执行失败：申请编号不能为空，且 --page-size 必须在 1–500 之间")
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
        record = _find_task(
            ErpTaskQueryService(settings, logger, progress_callback=print),
            code,
            args.page_size,
        )
        ai_client = OllamaTaskExtractionClient(settings.ai, logger)
        ai_client.ensure_available()
        decision = ai_client.classify(record, mode)
        people: list[dict[str, object]] = []
        issues: list[dict[str, str]] = []
        if decision.classified and decision.business_type in _BUSINESS_INTENTS:
            result = ErpBusinessPeopleService(
                settings, logger, ai_client=ai_client
            ).extract(record, _BUSINESS_INTENTS[decision.business_type], mode)
            result_payload = result.as_dict()
            people = list(result_payload["people"])
            issues = list(result_payload["issues"])
        elif decision.classified and decision.business_type == "单位社保权益单":
            rights_payload = ErpTaskExtractionService(
                settings, logger, progress_callback=print
            ).run(
                record.transaction_type,
                application_code=code,
                reasoning_mode=mode,
            )
            people, issues = _rights_people(rights_payload, code)
        else:
            issues.append({
                "code": "BUSINESS_TYPE_UNCLEAR",
                "person_name": "",
                "message": decision.reason or "无法根据申请原文明确判断业务类型",
            })
        report = {
            "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "application": {
                "erp_record_id": record.id,
                "code": record.code,
                "application_date": record.initiated_date,
                "erp_transaction_type": record.transaction_type,
                "title": record.title,
                "description": record.description,
            },
            "classification": asdict(decision),
            "people": people,
            "issues": issues,
            "needs_review": bool(issues),
        }
        print(f"业务类型：{decision.business_type}")
        print(f"人员：{len(people)} 人；需处理问题：{len(issues)} 项")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.output is not None:
            output_path = resolve_runtime_path(args.output, runtime_root)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"JSON 已保存：{output_path}")
        return 0
    except EhrmError as exc:
        print(display_message(exc.code, exc.message))
        if exc.details:
            print(exc.details)
        return 2
    except (OSError, ValueError) as exc:
        print(f"任务执行失败：{exc}")
        return 2
    except KeyboardInterrupt:
        print("\n用户已取消 ERP 社保申请分析")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
