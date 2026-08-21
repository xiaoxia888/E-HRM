from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Callable, Iterable

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError, TaskCancelledError
from ehrm.core.settings import AppSettings
from ehrm.modules.ai.client import OllamaTaskExtractionClient
from ehrm.modules.ai.models import ReasoningMode
from ehrm.modules.erp.models import (
    ErpCredentials,
    ErpPersonRecord,
    ErpTaskRecord,
    ErpTaskStatus,
)
from ehrm.modules.erp.person_service import ErpPersonLookupService
from ehrm.modules.erp.task_service import ErpTaskQueryService


_IDENTITY_PATTERN = re.compile(r"^(?:\d{15}|\d{17}[0-9X])$")


class ErpTaskExtractionService:
    """Queries ERP tasks, then extracts rights-statement inputs sequentially."""

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        progress_callback: Callable[[str], None] | None = None,
        item_progress_callback: Callable[[int, int, str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._progress_callback = progress_callback
        self._item_progress_callback = item_progress_callback
        self._cancel_check = cancel_check

    def run(
        self,
        transaction_type: str,
        *,
        status: int | ErpTaskStatus | None = None,
        statuses: Iterable[int | ErpTaskStatus] | None = None,
        application_code: str = "",
        start_date: str = "",
        end_date: str = "",
        page_size: int = 50,
        max_tasks: int = 0,
        reasoning_mode: str | ReasoningMode | None = None,
        credentials: ErpCredentials | None = None,
    ) -> dict[str, object]:
        if max_tasks < 0:
            raise ValueError("max_tasks 不能小于 0")
        mode = ReasoningMode.parse(
            reasoning_mode or self._settings.ai.default_reasoning_mode
        )
        if mode.value not in self._settings.ai.reasoning_modes:
            supported = "、".join(self._settings.ai.reasoning_modes)
            raise ValueError(
                f"模型 {self._settings.ai.display_name} 不支持推理模式 "
                f"{mode.value}；可用模式：{supported}"
            )
        query_result = ErpTaskQueryService(
            self._settings,
            self._logger,
            progress_callback=self._progress,
            cancel_check=self._cancel_check,
        ).query_tasks(
            transaction_type,
            status=status,
            statuses=statuses,
            application_code=application_code,
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            credentials=credentials,
        )
        records = query_result.records[:max_tasks] if max_tasks else query_result.records

        task_results: list[dict[str, object]] = []
        rights_requests: list[dict[str, object]] = []
        succeeded = 0
        failed = 0
        review_tasks = 0
        total = len(records)
        processed = 0
        stopped = self._is_cancelled()

        client: OllamaTaskExtractionClient | None = None
        if total and not stopped:
            client = OllamaTaskExtractionClient(self._settings.ai, self._logger)
            self._progress(
                f"AI：正在检查模型 {self._settings.ai.model}，"
                f"推理模式={mode.label}"
            )
            client.ensure_available()
        self._item_progress(0, total, "")

        for sequence, record in enumerate(records, start=1):
            if self._is_cancelled():
                stopped = True
                break
            self._progress(
                f"AI：正在顺序解析 {sequence}/{total}："
                f"{record.code or '无任务编号'}"
            )
            self._item_progress(processed, total, record.code)
            task_payload = self._task_payload(sequence, record)
            try:
                if client is None:
                    raise RuntimeError("大模型客户端未初始化")
                response = client.extract(record, mode)
                extraction = response.extraction
                task_payload.update(
                    {
                        "parse_status": {
                            "code": ErrorCode.SUCCESS.value,
                            "message": display_message(ErrorCode.SUCCESS),
                        },
                        "extraction": extraction.as_dict(),
                        "model_metrics": response.metrics.as_dict(),
                    }
                )
                succeeded += 1
                if extraction.needs_review:
                    review_tasks += 1
                assigned_identities: set[str] = set()
                for person_index, person in enumerate(extraction.people, start=1):
                    source_identity = self._identity_from_application_text(
                        record,
                        person.name,
                        person.social_security_number,
                    )
                    if source_identity in assigned_identities:
                        self._logger.warning(
                            "忽略申请内重复分配的身份证 code=%s name=%s",
                            record.code,
                            person.name,
                        )
                        source_identity = None
                    elif source_identity:
                        assigned_identities.add(source_identity)
                    rights_requests.append(
                        {
                            "task_number": record.code,
                            "erp_record_id": record.id,
                            "application_date": record.initiated_date,
                            "person_sequence": person_index,
                            "name": person.name,
                            "social_security_number": source_identity,
                            "start_month": person.start_month,
                            "end_month": person.end_month,
                            "time_expression": person.time_expression,
                            "evidence": person.evidence,
                            "date_basis": person.date_basis,
                            "confidence": person.confidence,
                            "needs_review": extraction.needs_review,
                            "review_reasons": list(extraction.review_reasons),
                            "warnings": list(extraction.warnings),
                        }
                    )
            except EhrmError as exc:
                failed += 1
                self._logger.error(
                    "大模型任务解析失败 code=%s error_code=%s internal=%s details=%s",
                    record.code,
                    exc.code,
                    exc.message,
                    exc.details or "",
                )
                task_payload.update(
                    {
                        "parse_status": {
                            "code": exc.code.value,
                            "message": display_message(exc.code, exc.message),
                            "details": exc.details or exc.message,
                        },
                        "extraction": None,
                        "model_metrics": None,
                    }
                )
            task_results.append(task_payload)
            processed += 1
            self._item_progress(processed, total, record.code)

        if rights_requests and not stopped:
            stopped = self._enrich_identities(
                rights_requests,
                credentials=credentials,
            )

        identities_matched = sum(
            bool(str(item.get("social_security_number") or "").strip())
            for item in rights_requests
        )

        return {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "query": {
                "transaction_type": query_result.transaction_type,
                "status": (
                    query_result.status.value
                    if query_result.status is not None
                    else None
                ),
                "status_label": (
                    query_result.status.label
                    if query_result.status is not None
                    else ""
                ),
                "statuses": [item.value for item in query_result.statuses],
                "status_labels": [item.label for item in query_result.statuses],
                "application_code": query_result.application_code,
                "start_date": query_result.start_date,
                "end_date": query_result.end_date,
                "page_size": page_size,
                "total_count": query_result.total_count,
                "pages_fetched": query_result.pages_fetched,
                "selected_count": total,
            },
            "model": {
                "provider": "ollama",
                "profile_id": self._settings.ai.profile_id.value,
                "display_name": self._settings.ai.display_name,
                "base_url": self._settings.ai.base_url,
                "name": self._settings.ai.model,
                "reasoning_mode": mode.value,
                "reasoning_label": mode.label,
                "ollama_think": mode.ollama_think,
                "prompt_file": self._settings.ai.prompt_path.name,
            },
            "summary": {
                "tasks_total": total,
                "tasks_succeeded": succeeded,
                "tasks_failed": failed,
                "tasks_needing_review": review_tasks,
                "people_extracted": len(rights_requests),
                "identities_matched": identities_matched,
                "identities_pending": len(rights_requests) - identities_matched,
                "tasks_processed": processed,
                "tasks_unprocessed": total - processed,
                "stopped": stopped,
            },
            "tasks": task_results,
            "rights_statement_requests": rights_requests,
        }

    def _enrich_identities(
        self,
        requests: list[dict[str, object]],
        *,
        credentials: ErpCredentials | None,
    ) -> bool:
        identity_requests: list[dict[str, object]] = []
        missing_requests: list[dict[str, object]] = []
        for item in requests:
            identity = str(
                item.get("social_security_number") or ""
            ).strip().upper()
            if _IDENTITY_PATTERN.fullmatch(identity):
                item["social_security_number"] = identity
                identity_requests.append(item)
            else:
                item["social_security_number"] = None
                missing_requests.append(item)

        identities = [
            str(item.get("social_security_number") or "").strip()
            for item in identity_requests
        ]
        names = [
            str(item.get("name") or "").strip()
            for item in missing_requests
        ]
        try:
            matches_by_identity, matches_by_name = ErpPersonLookupService(
                self._settings,
                self._logger,
                progress_callback=self._progress,
                cancel_check=self._cancel_check,
            ).lookup_people(
                identity_numbers=identities,
                names=names,
                credentials=credentials,
            )
        except TaskCancelledError:
            return True
        except EhrmError as exc:
            self._logger.error(
                "ERP 人员身份证匹配失败 code=%s internal=%s details=%s",
                exc.code,
                exc.message,
                exc.details or "",
            )
            for item in requests:
                item["identity_match"] = {
                    "code": exc.code.value,
                    "message": display_message(exc.code, exc.message),
                    "details": exc.details or exc.message,
                }
            return False

        for item in identity_requests:
            identity = str(item.get("social_security_number") or "").strip()
            matches = matches_by_identity.get(identity, ())
            self._apply_identity_lookup_result(
                item,
                matches,
                queried_by_identity=True,
            )

        for item in missing_requests:
            name = str(item.get("name") or "").strip()
            matches = matches_by_name.get(name, ())
            self._apply_identity_lookup_result(
                item,
                matches,
                queried_by_identity=False,
            )
        return False

    @staticmethod
    def _candidate_payload(match: ErpPersonRecord) -> dict[str, str]:
        return {
            "employee_code": match.employee_code,
            "department": match.department,
            "company": match.company,
            "is_quit": match.is_quit,
        }

    def _apply_identity_lookup_result(
        self,
        item: dict[str, object],
        matches: tuple[ErpPersonRecord, ...],
        *,
        queried_by_identity: bool,
    ) -> None:
        name = str(item.get("name") or "").strip()
        if not matches:
            condition = (
                "申请原文中的身份证号"
                if queried_by_identity
                else f"姓名“{name}”"
            )
            item["identity_match"] = {
                "code": ErrorCode.ERP_PERSON_NOT_FOUND.value,
                "message": display_message(ErrorCode.ERP_PERSON_NOT_FOUND),
                "details": f"ERP 人员库未找到{condition}对应的人员",
                "source": (
                    "application_text" if queried_by_identity else "name_lookup"
                ),
                "department": "",
                "company": "",
            }
            return
        if len(matches) > 1:
            item["identity_match"] = {
                "code": ErrorCode.ERP_PERSON_AMBIGUOUS.value,
                "message": display_message(ErrorCode.ERP_PERSON_AMBIGUOUS),
                "details": f"查询到 {len(matches)} 名匹配人员，请人工核对",
                "source": (
                    "application_text" if queried_by_identity else "name_lookup"
                ),
                "department": "",
                "company": "",
                "candidates": [
                    self._candidate_payload(match) for match in matches
                ],
            }
            return

        match = matches[0]
        matched_identity = match.identity_number.strip().upper()
        matched_name = match.name.strip()
        if queried_by_identity and name and matched_name != name:
            item["social_security_number"] = None
            item["identity_match"] = {
                "code": ErrorCode.ERP_PERSON_IDENTITY_NAME_MISMATCH.value,
                "message": display_message(
                    ErrorCode.ERP_PERSON_IDENTITY_NAME_MISMATCH
                ),
                "details": (
                    f"解析姓名“{name}”使用身份证查询后匹配到“{matched_name}”，"
                    "已拒绝使用该身份证及人员组织信息"
                ),
                "source": "application_identity",
                "department": "",
                "company": "",
            }
            return
        if not queried_by_identity and not _IDENTITY_PATTERN.fullmatch(
            matched_identity
        ):
            item["identity_match"] = {
                "code": ErrorCode.ERP_PERSON_IDENTITY_INVALID.value,
                "message": display_message(ErrorCode.ERP_PERSON_IDENTITY_INVALID),
                "details": (
                    f"ERP 人员“{name}”的身份证号为空或不是 15/18 位格式"
                ),
                "employee_code": match.employee_code,
                "department": "",
                "company": "",
            }
            return

        if not queried_by_identity:
            item["social_security_number"] = matched_identity
        item["identity_match"] = {
            "code": ErrorCode.SUCCESS.value,
            "message": display_message(ErrorCode.SUCCESS),
            "details": (
                "已使用申请原文身份证精确匹配 ERP 人员信息"
                if queried_by_identity
                else "已使用姓名匹配 ERP 人员信息"
            ),
            "source": (
                "application_identity" if queried_by_identity
                else "erp_person_database"
            ),
            "employee_code": match.employee_code,
            "department": match.department,
            "company": match.company,
        }

    def _identity_from_application_text(
        self,
        record: ErpTaskRecord,
        name: str,
        model_identity: str | None,
    ) -> str | None:
        """Returns only an identity that is verifiably present in the application."""

        source_text = f"{record.title}\n{record.description}"
        normalized_model_identity = str(model_identity or "").strip().upper()
        escaped_name = re.escape(name.strip())
        if escaped_name:
            after_name = re.search(
                rf"{escaped_name}[ \t]*[（(]?[ \t]*"
                rf"(?P<identity>\d{{17}}[0-9Xx]|\d{{15}})[ \t]*[）)]?",
                source_text,
            )
            if after_name:
                return after_name.group("identity").upper()
            before_name = re.search(
                rf"(?m)^[ \t]*[（(]?"
                rf"(?P<identity>\d{{17}}[0-9Xx]|\d{{15}})[ \t]*[）)]?"
                rf"[ \t]+{escaped_name}[ \t]*$",
                source_text,
            )
            if before_name:
                return before_name.group("identity").upper()

        if normalized_model_identity:
            self._logger.warning(
                "忽略未在申请原文中找到或无法关联人员的模型身份证 code=%s name=%s",
                record.code,
                name,
            )
        return None

    @staticmethod
    def _task_payload(
        sequence: int,
        record: ErpTaskRecord,
    ) -> dict[str, object]:
        return {
            "sequence": sequence,
            "erp_record_id": record.id,
            "task_number": record.code,
            "application_date": record.initiated_date,
            "title": record.title,
            "description": record.description,
            "transaction_type": record.transaction_type,
            "status": record.status,
            "status_label": ErpTaskStatus.display(record.status),
            "originator": record.originator,
            "department": record.department,
        }

    def _progress(self, text: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(text)

    def _item_progress(self, current: int, total: int, task_number: str) -> None:
        if self._item_progress_callback is not None:
            self._item_progress_callback(current, total, task_number)

    def _is_cancelled(self) -> bool:
        return self._cancel_check is not None and self._cancel_check()
