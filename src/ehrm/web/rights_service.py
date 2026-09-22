from __future__ import annotations

from datetime import datetime
from dataclasses import replace
import json
import logging
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from ehrm.core.auth_repository import SystemAccount, SystemType
from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.modules.erp.batch_service import ErpBatchUploadService
from ehrm.modules.erp.extraction_service import ErpTaskExtractionService
from ehrm.modules.erp.models import ErpCredentials
from ehrm.modules.nocobase.models import NocoBaseRightsApplicationDetail
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_service import ExcelRightsStatementService
from ehrm.modules.rights_statement.excel_models import (
    EmployeeRecord,
    ExcelRunResult,
    ExcelTaskRequest,
    ExportMode,
)
from ehrm.web.settings_service import WebSettingsService
from ehrm.web.tasks import TaskContext, TaskCoordinator, TaskKind, TaskSnapshot
from ehrm.workbench import DesktopWorkbench


_IMPORT_ID = re.compile(r"^[0-9a-f]{32}$")


class ArtifactRegistry:
    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}
        self._lock = RLock()

    def register(self, path: Path) -> dict[str, str]:
        resolved = path.expanduser().resolve()
        token = uuid4().hex
        with self._lock:
            self._paths[token] = resolved
        return {
            "name": resolved.name,
            "url": f"/api/v1/artifacts/{token}",
        }

    def resolve(self, token: str) -> Path | None:
        with self._lock:
            path = self._paths.get(token)
        return path if path is not None and path.is_file() else None


class RightsWebService:
    MAX_UPLOAD_BYTES = 20 * 1024 * 1024

    def __init__(
        self,
        settings_service: WebSettingsService,
        coordinator: TaskCoordinator,
        logger: logging.Logger,
        artifacts: ArtifactRegistry,
    ) -> None:
        self.settings_service = settings_service
        self.coordinator = coordinator
        self.logger = logger
        self.artifacts = artifacts
        self.loader = RightsStatementExcelLoader()
        self.template = RightsStatementTemplateService()
        self.import_root = settings_service.runtime_root / "uploads" / "rights"

    def import_excel(self, filename: str, content: bytes) -> dict[str, object]:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            raise ValueError("只支持 .xlsx 或 .xlsm 权益单人员文件")
        if not content:
            raise ValueError("上传的 Excel 文件为空")
        if len(content) > self.MAX_UPLOAD_BYTES:
            raise ValueError("上传文件不能超过 20 MB")
        import_id = uuid4().hex
        self.import_root.mkdir(parents=True, exist_ok=True)
        path = self.import_root / f"{import_id}{suffix}"
        path.write_bytes(content)
        try:
            records = self.loader.load(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        preferences = self.settings_service.preferences()
        mode = ExportMode(preferences.export_mode)
        planning_records = records
        groups = self.loader.plan(planning_records, mode, preferences.batch_size)
        preview_records = [
            {
                **self._preview_record(record),
                "print_group": record.print_group_label or "默认组",
                "print_group_id": record.print_group_id,
                "status": "success",
                "issue_count": 0,
            }
            for record in records
        ]
        print_groups = self._erp_print_groups(
            planning_records,
            preview_records,
            [],
        )
        erp_upload_available = bool(records) and all(
            bool(record.task_number.strip()) for record in records
        )
        return {
            "import_id": import_id,
            "filename": Path(filename).name,
            "source": "excel",
            "record_count": len(records),
            "unique_person_count": len(
                {record.identity_number for record in records}
            ),
            "group_count": len(print_groups),
            "estimated_pdf_count": len(groups),
            "erp_upload_available": erp_upload_available,
            "executable": True,
            "records": preview_records,
            "issues": [],
            "applications": [],
            "print_groups": print_groups,
        }

    def submit_import(
        self,
        *,
        import_id: str,
        account_id: int,
        mode: ExportMode,
        batch_size: int,
        upload_to_erp: bool,
    ) -> TaskSnapshot:
        source = self._import_path(import_id)
        is_erp_source = (self.import_root / f"{import_id}.json").is_file()
        records = self.loader.load(source)
        erp_upload_available = is_erp_source or (
            bool(records)
            and all(bool(record.task_number.strip()) for record in records)
        )
        if upload_to_erp and not erp_upload_available:
            raise ValueError(
                "Excel 中存在未填写 ERP申请编号的打印组，无法自动上传 ERP。"
                "请补全编号后重新导入，或关闭自动上传。"
            )
        groups = self.loader.plan(records, mode, batch_size)
        account = self.settings_service.account(account_id, SystemType.JSHRSS)
        request = self._request(
            groups=groups,
            mode=mode,
            source=source,
            label=source.stem,
            upload_to_erp=upload_to_erp,
        )
        return self._submit(account, request, title="获取社保权益单")

    def submit_erp_extraction(
        self,
        *,
        account_id: int,
        transaction_type: str,
        statuses: tuple[int, ...],
        application_code: str,
        start_date: str,
        end_date: str,
        page_size: int,
        reasoning_mode: str,
    ) -> TaskSnapshot:
        account = self.settings_service.account(account_id, SystemType.ERP)
        label = account.display_name or self._mask_account(account.account)
        return self.coordinator.submit(
            title="获取并解析 ERP 申请信息",
            operation="erp.rights.extract",
            kind=TaskKind.ERP_BROWSER,
            resource_key=str(account.id),
            resource_label=label,
            runner=lambda context: self._run_erp_extraction(
                context,
                account,
                transaction_type=transaction_type.strip(),
                statuses=statuses,
                application_code=application_code.strip(),
                start_date=start_date.strip(),
                end_date=end_date.strip(),
                page_size=page_size,
                reasoning_mode=reasoning_mode.strip(),
            ),
        )

    def _run_erp_extraction(
        self,
        context: TaskContext,
        account: SystemAccount,
        *,
        transaction_type: str,
        statuses: tuple[int, ...],
        application_code: str,
        start_date: str,
        end_date: str,
        page_size: int,
        reasoning_mode: str,
    ) -> dict[str, object]:
        settings = self.settings_service.runtime_settings(erp_account=account)

        def item_progress(current: int, total: int, task_number: str) -> None:
            suffix = f"：{task_number}" if task_number else ""
            context.report(
                f"正在解析 ERP 申请 {current}/{total}{suffix}",
                current=current,
                total=max(total, 1),
            )

        context.report("正在登录 ERP 并查询申请记录", current=0, total=1)
        result = ErpTaskExtractionService(
            settings,
            self.logger,
            progress_callback=lambda message: context.report(message),
            item_progress_callback=item_progress,
            cancel_check=lambda: context.cancelled,
        ).run(
            transaction_type,
            statuses=statuses,
            application_code=application_code,
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            reasoning_mode=reasoning_mode or settings.ai.default_reasoning_mode,
            credentials=ErpCredentials(account.account, account.password),
        )
        context.raise_if_cancelled()
        query = result.get("query")
        query = query if isinstance(query, dict) else {}
        summary = result.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        selected_count = int(
            query.get("selected_count") or summary.get("tasks_total") or 0
        )
        if selected_count == 0:
            status_labels = query.get("status_labels")
            status_text = (
                "、".join(str(item) for item in status_labels if str(item).strip())
                if isinstance(status_labels, list)
                else ""
            )
            filters = [f"事务类型：{transaction_type}"]
            if application_code:
                filters.append(f"申请编号：{application_code}")
            filters.append(f"申请状态：{status_text or '全部状态'}")
            raise ValueError(
                "未查询到符合条件的 ERP 申请。请检查申请编号、事务类型和申请状态。"
                f"当前查询条件：{'；'.join(filters)}"
            )
        preview = self._erp_preview(result)
        return {
            "preview": preview,
            "summary": result.get("summary", {}),
            "model": result.get("model", {}),
            "query": result.get("query", {}),
        }

    def _erp_preview(
        self,
        result: dict[str, object],
        *,
        import_id: str | None = None,
    ) -> dict[str, object]:
        request_items = result.get("rights_statement_requests")
        requests = request_items if isinstance(request_items, list) else []
        records: list[EmployeeRecord] = []
        for sequence, item in enumerate(requests, start=2):
            if not isinstance(item, dict):
                continue
            identity_match = item.get("identity_match")
            identity_match = identity_match if isinstance(identity_match, dict) else {}
            records.append(
                EmployeeRecord(
                    row_number=sequence,
                    unit=str(identity_match.get("company") or "").strip(),
                    department=str(identity_match.get("department") or "").strip(),
                    name=str(item.get("name") or "").strip(),
                    identity_number=str(
                        item.get("social_security_number") or ""
                    ).strip(),
                    insurance_type=str(item.get("insurance_type") or "").strip(),
                    start_month=str(item.get("start_month") or "").strip(),
                    end_month=str(item.get("end_month") or "").strip(),
                    task_number=str(item.get("task_number") or "").strip(),
                    print_group_id=str(item.get("group_id") or "").strip(),
                    print_group_label=(
                        str(item.get("group_label") or "").strip()
                        or (
                            f"组{int(item.get('group_sequence') or 0)}"
                            if int(item.get("group_sequence") or 0)
                            else "默认组"
                        )
                    ),
                    print_group_sequence=int(item.get("group_sequence") or 0),
                    source_print_mode=str(
                        item.get("source_print_mode") or ""
                    ).strip(),
                    resolved_print_mode=str(
                        item.get("resolved_print_mode") or ""
                    ).strip(),
                )
            )

        issues = self._erp_issues(result)
        issues_by_row: dict[int, list[dict[str, object]]] = {}
        for issue in issues:
            issues_by_row.setdefault(int(issue.get("row_number") or 0), []).append(issue)
        preview_records = []
        for record in records:
            row_issues = issues_by_row.get(record.row_number, [])
            blocking = any(
                item.get("level") in {"error", "pending"} for item in row_issues
            )
            warning = any(item.get("level") == "warning" for item in row_issues)
            preview_records.append(
                {
                    **self._preview_record(record),
                    "print_group": (
                        record.print_group_label or "默认组"
                    ),
                    "print_group_id": record.print_group_id,
                    "status": "error" if blocking else "warning" if warning else "success",
                    "issue_count": len(row_issues),
                }
            )

        print_groups = self._erp_print_groups(records, preview_records, issues)
        unique_people = {
            (
                record.identity_number.strip()
                or f"{record.task_number.strip()}:{record.name.strip()}"
            )
            for record in records
            if record.identity_number.strip() or record.name.strip()
        }

        import_id = import_id or uuid4().hex
        self.import_root.mkdir(parents=True, exist_ok=True)
        self._write_erp_state(import_id, result)
        source = self.import_root / f"{import_id}.xlsx"
        self.template.write_records(source, records, include_print_groups=True)
        preferences = self.settings_service.preferences()
        estimated_pdf_count = len(print_groups)
        executable = bool(records) and not any(
            item.get("level") in {"error", "pending"} for item in issues
        )
        if executable:
            try:
                planning_records = records
                validated = self.loader.validate_records(planning_records)
                estimated_pdf_count = len(
                    self.loader.plan(
                        validated,
                        ExportMode(preferences.export_mode),
                        preferences.batch_size,
                    )
                )
            except Exception as exc:
                executable = False
                issues.append(
                    {
                        "issue_id": f"EXCEL_VALIDATION_ERROR:0:{len(issues) + 1}",
                        "level": "error",
                        "level_label": "错误",
                        "task_number": "-",
                        "person_name": "-",
                        "code": ErrorCode.EXCEL_VALIDATION_ERROR.value,
                        "message": display_message(ErrorCode.EXCEL_VALIDATION_ERROR),
                        "details": str(exc),
                        "row_number": 0,
                        "group_id": "",
                    }
                )
        tasks = result.get("tasks")
        applications = []
        if isinstance(tasks, list):
            for item in tasks:
                if not isinstance(item, dict):
                    continue
                task_number = str(item.get("task_number") or "").strip()
                applications.append(
                    {
                        "sequence": int(item.get("sequence") or 0),
                        "task_number": task_number,
                        "title": str(item.get("title") or "").strip(),
                        "description": str(item.get("description") or "").strip(),
                        "status_label": str(item.get("status_label") or "").strip(),
                        "originator": str(item.get("originator") or "").strip(),
                        "department": str(item.get("department") or "").strip(),
                        "parse_status": item.get("parse_status") or {},
                        "issue_count": sum(
                            issue.get("task_number") == task_number for issue in issues
                        ),
                    }
                )
        return {
            "import_id": import_id,
            "filename": "ERP申请解析数据.xlsx",
            "source": "erp",
            "record_count": len(records),
            "unique_person_count": len(unique_people),
            "group_count": len(print_groups),
            "estimated_pdf_count": estimated_pdf_count,
            "erp_upload_available": True,
            "executable": executable,
            "records": preview_records,
            "issues": issues,
            "applications": applications,
            "print_groups": print_groups,
        }

    def erp_record_detail(
        self,
        import_id: str,
        row_number: int,
    ) -> dict[str, object]:
        result = self._read_erp_state(import_id)
        item = self._erp_request_row(result, row_number)
        match = item.get("identity_match")
        match = match if isinstance(match, dict) else {}
        return {
            "row_number": row_number,
            "task_number": str(item.get("task_number") or "").strip(),
            "print_group": self._erp_group_label(item),
            "unit": str(match.get("company") or "").strip(),
            "department": str(match.get("department") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "identity_number": str(
                item.get("social_security_number") or ""
            ).strip(),
            "insurance_type": str(item.get("insurance_type") or "").strip(),
            "start_month": str(item.get("start_month") or "").strip(),
            "end_month": str(item.get("end_month") or "").strip(),
        }

    def update_erp_record(
        self,
        import_id: str,
        row_number: int,
        values: dict[str, object],
    ) -> dict[str, object]:
        result = self._read_erp_state(import_id)
        item = self._erp_request_row(result, row_number)
        task_number = str(item.get("task_number") or "").strip()
        normalized = self._normalize_manual_record(
            values,
            row_number=row_number,
            task_number=task_number,
            item=item,
        )
        self._apply_manual_record(result, item, normalized)
        self._move_erp_record_to_group(
            result,
            item,
            str(values.get("print_group") or "").strip(),
        )
        return self._erp_preview(result, import_id=import_id)

    def add_erp_record(
        self,
        import_id: str,
        values: dict[str, object],
    ) -> dict[str, object]:
        result = self._read_erp_state(import_id)
        task_number = str(values.get("task_number") or "").strip()
        tasks = result.get("tasks")
        task_items = tasks if isinstance(tasks, list) else []
        task = next(
            (
                entry
                for entry in task_items
                if isinstance(entry, dict)
                and str(entry.get("task_number") or "").strip() == task_number
            ),
            None,
        )
        if task is None:
            raise ValueError("未找到需要补录人员的 ERP 申请")
        requests = result.get("rights_statement_requests")
        if not isinstance(requests, list):
            requests = []
            result["rights_statement_requests"] = requests
        group_sequence = 1 + max(
            (
                int(entry.get("group_sequence") or 0)
                for entry in requests
                if isinstance(entry, dict)
                and str(entry.get("task_number") or "").strip() == task_number
            ),
            default=0,
        )
        item: dict[str, object] = {
            "task_number": task_number,
            "erp_record_id": str(task.get("record_id") or task.get("id") or ""),
            "application_date": str(task.get("initiated_date") or ""),
            "group_id": f"{task_number}-MANUAL-{uuid4().hex[:8]}",
            "group_label": str(values.get("print_group") or "").strip()
            or f"组{group_sequence}",
            "group_sequence": group_sequence,
            "group_people_count": 1,
            "source_print_mode": "individual",
            "resolved_print_mode": "individual",
            "person_sequence": 1,
            "review_reasons": [],
            "warnings": [],
        }
        normalized = self._normalize_manual_record(
            values,
            row_number=len(requests) + 2,
            task_number=task_number,
            item=item,
        )
        requests.append(item)
        self._apply_manual_record(result, item, normalized)
        self._refresh_erp_group_metadata(result)
        task["parse_status"] = {
            "code": ErrorCode.SUCCESS.value,
            "message": "已人工补录申请人员",
        }
        return self._erp_preview(result, import_id=import_id)

    def select_erp_candidate(
        self,
        import_id: str,
        row_number: int,
        candidate_id: str,
    ) -> dict[str, object]:
        result = self._read_erp_state(import_id)
        item = self._erp_request_row(result, row_number)
        match = item.get("identity_match")
        match = match if isinstance(match, dict) else {}
        candidates = match.get("candidates")
        candidate_items = candidates if isinstance(candidates, list) else []
        selected = next(
            (
                candidate
                for index, candidate in enumerate(candidate_items, start=1)
                if isinstance(candidate, dict)
                and self._candidate_id(candidate, index) == candidate_id.strip()
            ),
            None,
        )
        if selected is None:
            raise ValueError("候选人员不存在或已经失效，请重新获取申请信息")
        values = {
            "unit": selected.get("company") or "",
            "department": selected.get("department") or "",
            "name": selected.get("name") or item.get("name") or "",
            "identity_number": selected.get("identity_number") or "",
            # Candidate selection confirms identity only. Placeholder conditions
            # keep identity validation independent from unresolved group dates.
            "insurance_type": "养老",
            "start_month": "2000-01",
            "end_month": "2000-01",
        }
        normalized = self._normalize_manual_record(
            values,
            row_number=row_number,
            task_number=str(item.get("task_number") or "").strip(),
            item=item,
        )
        item["name"] = normalized.name
        item["social_security_number"] = normalized.identity_number
        item["manual_identity_confirmed"] = True
        item["identity_match"] = {
            "code": ErrorCode.SUCCESS.value,
            "message": "已人工选择 ERP 候选人员",
            "details": "已根据人工选择确定人员身份信息",
            "source": "manual_candidate_selection",
            "employee_code": str(selected.get("employee_code") or ""),
            "department": normalized.department,
            "company": normalized.unit,
        }
        return self._erp_preview(result, import_id=import_id)

    def _normalize_manual_record(
        self,
        values: dict[str, object],
        *,
        row_number: int,
        task_number: str,
        item: dict[str, object],
    ) -> EmployeeRecord:
        return self.loader.normalize_record(
            EmployeeRecord(
                row_number=row_number,
                task_number=task_number,
                unit=str(values.get("unit") or "").strip(),
                department=str(values.get("department") or "").strip(),
                name=str(values.get("name") or "").strip(),
                identity_number=str(
                    values.get("identity_number") or ""
                ).strip(),
                insurance_type=str(
                    values.get("insurance_type") or ""
                ).strip(),
                start_month=str(values.get("start_month") or "").strip(),
                end_month=str(values.get("end_month") or "").strip(),
                print_group_id=str(item.get("group_id") or "").strip(),
                print_group_sequence=int(item.get("group_sequence") or 0),
                source_print_mode=str(
                    item.get("source_print_mode") or ""
                ).strip(),
                resolved_print_mode=str(
                    item.get("resolved_print_mode") or ""
                ).strip(),
            )
        )

    @staticmethod
    def _apply_manual_record(
        result: dict[str, object],
        item: dict[str, object],
        record: EmployeeRecord,
    ) -> None:
        item.update(
            {
                "name": record.name,
                "social_security_number": record.identity_number,
                "insurance_type": record.insurance_type,
                "start_month": record.start_month,
                "end_month": record.end_month,
                "needs_review": False,
                "review_reasons": [],
                "manual_review_confirmed": True,
                "identity_match": {
                    "code": ErrorCode.SUCCESS.value,
                    "message": "已人工补充人员信息",
                    "details": "人员资料已经人工填写并通过格式校验",
                    "source": "manual_entry",
                    "department": record.department,
                    "company": record.unit,
                },
            }
        )

    @staticmethod
    def _erp_group_label(item: dict[str, object]) -> str:
        label = str(item.get("group_label") or "").strip()
        if label:
            return label
        sequence = int(item.get("group_sequence") or 0)
        return f"组{sequence}" if sequence else "默认组"

    def _move_erp_record_to_group(
        self,
        result: dict[str, object],
        item: dict[str, object],
        requested_label: str,
    ) -> None:
        if not requested_label.strip():
            self._refresh_erp_group_metadata(result)
            return
        label = requested_label.strip()
        if len(label) > 80 or any(character in label for character in "\r\n\t"):
            raise ValueError("打印组名称不能超过 80 个字符且不能包含换行或制表符")
        if label == self._erp_group_label(item):
            self._refresh_erp_group_metadata(result)
            return
        requests = result.get("rights_statement_requests")
        request_items = requests if isinstance(requests, list) else []
        task_number = str(item.get("task_number") or "").strip()
        target = next(
            (
                entry
                for entry in request_items
                if isinstance(entry, dict)
                and entry is not item
                and str(entry.get("task_number") or "").strip() == task_number
                and self._erp_group_label(entry) == label
            ),
            None,
        )
        if target is None:
            sequence = 1 + max(
                (
                    int(entry.get("group_sequence") or 0)
                    for entry in request_items
                    if isinstance(entry, dict)
                    and str(entry.get("task_number") or "").strip() == task_number
                ),
                default=0,
            )
            item["group_id"] = f"{task_number}-MANUAL-{uuid4().hex[:8]}"
            item["group_sequence"] = sequence
            item["group_label"] = label
        else:
            item["group_id"] = str(target.get("group_id") or "").strip()
            item["group_sequence"] = int(target.get("group_sequence") or 0)
            item["group_label"] = self._erp_group_label(target)
            item["source_print_mode"] = target.get("source_print_mode")
            item["resolved_print_mode"] = target.get("resolved_print_mode")
        self._refresh_erp_group_metadata(result)

    @staticmethod
    def _refresh_erp_group_metadata(result: dict[str, object]) -> None:
        requests = result.get("rights_statement_requests")
        request_items = requests if isinstance(requests, list) else []
        counts: dict[tuple[str, str], int] = {}
        for entry in request_items:
            if not isinstance(entry, dict):
                continue
            key = (
                str(entry.get("task_number") or "").strip(),
                str(entry.get("group_id") or "").strip(),
            )
            counts[key] = counts.get(key, 0) + 1
        for entry in request_items:
            if not isinstance(entry, dict):
                continue
            key = (
                str(entry.get("task_number") or "").strip(),
                str(entry.get("group_id") or "").strip(),
            )
            entry["group_people_count"] = counts.get(key, 1)

    def resolve_erp_print_group(
        self,
        import_id: str,
        task_number: str,
        group_id: str,
        mode: str,
    ) -> dict[str, object]:
        normalized_task = task_number.strip()
        normalized_group = group_id.strip()
        normalized_mode = mode.strip()
        if not normalized_group:
            raise ValueError("打印组编号不能为空")
        if normalized_mode not in {"batch", "individual"}:
            raise ValueError("打印方式无效")
        result = self._read_erp_state(import_id)
        requests = result.get("rights_statement_requests")
        request_items = requests if isinstance(requests, list) else []
        matched_items = [
            item
            for item in request_items
            if isinstance(item, dict)
            and str(item.get("task_number") or "").strip() == normalized_task
            and str(item.get("group_id") or "").strip() == normalized_group
        ]
        if not matched_items:
            raise ValueError("打印组不存在或已经失效，请重新获取申请信息")
        stored_mode = "combined" if normalized_mode == "batch" else "individual"
        if stored_mode == "individual" and len(matched_items) > 1:
            next_sequence = max(
                (
                    int(item.get("group_sequence") or 0)
                    for item in request_items
                    if isinstance(item, dict)
                    and str(item.get("task_number") or "").strip()
                    == normalized_task
                ),
                default=0,
            )
            first_sequence = int(
                matched_items[0].get("group_sequence") or next_sequence + 1
            )
            for index, item in enumerate(matched_items):
                if index == 0:
                    sequence = first_sequence
                else:
                    next_sequence += 1
                    sequence = next_sequence
                    item["group_id"] = f"{normalized_task}-G{sequence:02d}"
                item["group_sequence"] = sequence
                item["group_label"] = f"组{sequence}"
                item["person_sequence"] = 1
                item["resolved_print_mode"] = stored_mode
        else:
            for item in matched_items:
                item["resolved_print_mode"] = stored_mode
        self._refresh_erp_group_metadata(result)
        return self._erp_preview(result, import_id=import_id)

    def resolve_erp_print_group_conditions(
        self,
        import_id: str,
        *,
        task_number: str,
        group_id: str,
        insurance_type: str,
        start_month: str,
        end_month: str,
        overwrite: bool,
    ) -> dict[str, object]:
        normalized_task = task_number.strip()
        normalized_group = group_id.strip()
        if not normalized_group:
            raise ValueError("打印组编号不能为空")
        conditions = self.loader.normalize_record(
            EmployeeRecord(
                row_number=0,
                task_number=normalized_task,
                unit="条件校验",
                department="条件校验",
                name="条件校验",
                identity_number="320101199001011234",
                insurance_type=insurance_type,
                start_month=start_month,
                end_month=end_month,
                print_group_id=normalized_group,
            )
        )
        result = self._read_erp_state(import_id)
        requests = result.get("rights_statement_requests")
        request_items = requests if isinstance(requests, list) else []
        matched: list[dict[str, object]] = []
        for item in request_items:
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("task_number") or "").strip() == normalized_task
                and str(item.get("group_id") or "").strip() == normalized_group
            ):
                matched.append(item)
        if not matched:
            raise ValueError("打印组不存在或已经失效，请重新获取申请信息")
        replacements = {
            "insurance_type": conditions.insurance_type,
            "start_month": conditions.start_month,
            "end_month": conditions.end_month,
        }
        for item in matched:
            for field, value in replacements.items():
                if overwrite or not str(item.get(field) or "").strip():
                    item[field] = value
            item["needs_review"] = False
            item["review_reasons"] = []
            item["manual_review_confirmed"] = True
        return self._erp_preview(result, import_id=import_id)

    def _erp_request_row(
        self,
        result: dict[str, object],
        row_number: int,
    ) -> dict[str, object]:
        requests = result.get("rights_statement_requests")
        request_items = requests if isinstance(requests, list) else []
        index = row_number - 2
        if index < 0 or index >= len(request_items):
            raise ValueError("需要处理的人员记录不存在或已经失效")
        item = request_items[index]
        if not isinstance(item, dict):
            raise ValueError("需要处理的人员记录格式无效")
        return item

    def _write_erp_state(
        self,
        import_id: str,
        result: dict[str, object],
    ) -> None:
        self._validate_import_id(import_id)
        state = self.import_root / f"{import_id}.json"
        state.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _read_erp_state(self, import_id: str) -> dict[str, object]:
        self._validate_import_id(import_id)
        state = self.import_root / f"{import_id}.json"
        if not state.is_file():
            raise ValueError("当前 ERP 解析数据已失效，请重新获取申请信息")
        try:
            payload = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("当前 ERP 解析数据损坏，请重新获取申请信息") from exc
        if not isinstance(payload, dict):
            raise ValueError("当前 ERP 解析数据格式无效")
        return payload

    @staticmethod
    def _validate_import_id(import_id: str) -> None:
        if not _IMPORT_ID.fullmatch(import_id):
            raise ValueError("权益单导入记录编号无效")

    @staticmethod
    def _candidate_id(candidate: dict[str, object], index: int) -> str:
        return str(
            candidate.get("id")
            or candidate.get("employee_code")
            or index
        ).strip()

    @staticmethod
    def _erp_print_groups(
        records: list[EmployeeRecord],
        preview_records: list[dict[str, object]],
        issues: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for record, preview in zip(records, preview_records, strict=True):
            group_id = record.print_group_id or f"row:{record.row_number}"
            key = (record.task_number, group_id)
            group = grouped.get(key)
            if group is None:
                mode = record.resolved_print_mode or record.source_print_mode
                group = {
                    "group_id": group_id,
                    "group_sequence": record.print_group_sequence,
                    "group_label": (
                        record.print_group_label
                        or (
                            f"打印组 {record.print_group_sequence}"
                            if record.print_group_sequence
                            else "默认组"
                        )
                    ),
                    "task_number": record.task_number,
                    "insurance_type": record.insurance_type,
                    "start_month": record.start_month,
                    "end_month": record.end_month,
                    "print_mode": mode,
                    "print_mode_label": {
                        "combined": "合并打印",
                        "batch": "合并打印",
                        "individual": "单独打印",
                    }.get(mode, "待确认"),
                    "people": [],
                    "people_count": 0,
                    "issue_count": 0,
                    "status": "success",
                }
                grouped[key] = group
            people = group["people"]
            assert isinstance(people, list)
            people.append(
                {
                    "row_number": record.row_number,
                    "name": record.name,
                    "identity_number": preview["identity_number"],
                    "unit": record.unit,
                    "department": record.department,
                }
            )
            group["people_count"] = len(people)

        for group in grouped.values():
            group_id = str(group["group_id"])
            task_number = str(group["task_number"])
            group_issues = [
                issue
                for issue in issues
                if str(issue.get("task_number") or "") == task_number
                and (
                    str(issue.get("group_id") or "") == group_id
                    or not str(issue.get("group_id") or "")
                )
            ]
            group["issue_count"] = len(group_issues)
            if any(item.get("level") in {"error", "pending"} for item in group_issues):
                group["status"] = "error"
            elif any(item.get("level") == "warning" for item in group_issues):
                group["status"] = "warning"
        return list(grouped.values())

    @staticmethod
    def _erp_issues(result: dict[str, object]) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []

        def add(
            level: str,
            task_number: str,
            person_name: str,
            code: str,
            message: str,
            details: str,
            row_number: int = 0,
            group_id: str = "",
            candidates: list[dict[str, str]] | None = None,
        ) -> None:
            issue: dict[str, object] = {
                "issue_id": f"{code}:{task_number}:{row_number}:{len(issues) + 1}",
                "level": level,
                "level_label": {
                    "error": "错误",
                    "warning": "待复核",
                    "pending": "待处理",
                    "info": "提示",
                }.get(level, "提示"),
                "task_number": task_number or "-",
                "person_name": person_name or "-",
                "code": code,
                "message": message,
                "details": details or message,
                "row_number": row_number,
                "group_id": group_id,
            }
            if candidates:
                issue["candidates"] = candidates
            issues.append(issue)

        raw_requests = result.get("rights_statement_requests")
        requests = raw_requests if isinstance(raw_requests, list) else []
        tasks_with_people = {
            str(item.get("task_number") or "").strip()
            for item in requests
            if isinstance(item, dict)
        }
        raw_tasks = result.get("tasks")
        tasks = raw_tasks if isinstance(raw_tasks, list) else []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_number = str(task.get("task_number") or "").strip()
            parse_status = task.get("parse_status")
            if isinstance(parse_status, dict):
                code = str(parse_status.get("code") or "").strip()
                if code and code != ErrorCode.SUCCESS.value:
                    add(
                        "error",
                        task_number,
                        "",
                        code,
                        str(parse_status.get("message") or "申请解析失败"),
                        str(parse_status.get("details") or "申请解析失败"),
                    )
                    continue
            if task_number not in tasks_with_people:
                add(
                    "error",
                    task_number,
                    "",
                    ErrorCode.AI_NO_PERSON_EXTRACTED.value,
                    display_message(ErrorCode.AI_NO_PERSON_EXTRACTED),
                    "申请标题和问题描述中未识别到可处理人员",
                )

        grouped_requests: dict[
            tuple[str, str], list[tuple[int, dict[str, object]]]
        ] = {}
        for row_number, item in enumerate(requests, start=2):
            if not isinstance(item, dict):
                continue
            task_number = str(item.get("task_number") or "").strip()
            group_id = str(item.get("group_id") or "").strip()
            group_key = group_id or f"row:{row_number}"
            grouped_requests.setdefault((task_number, group_key), []).append(
                (row_number, item)
            )

        condition_fields = (
            ("insurance_type", "险种"),
            ("start_month", "开始月份"),
            ("end_month", "结束月份"),
        )
        for (task_number, _), members in grouped_requests.items():
            first_row, first_item = members[0]
            group_id = str(first_item.get("group_id") or "").strip()
            group_sequence = int(first_item.get("group_sequence") or 0)
            group_label = (
                f"打印组 {group_sequence}" if group_sequence else "默认打印组"
            )
            missing_fields: list[str] = []
            conflicts: list[str] = []
            for field, label in condition_fields:
                values = {
                    str(item.get(field) or "").strip()
                    for _, item in members
                    if str(item.get(field) or "").strip()
                }
                if any(not str(item.get(field) or "").strip() for _, item in members):
                    missing_fields.append(label)
                if len(values) > 1:
                    conflicts.append(f"{label}存在多个值：{'、'.join(sorted(values))}")
            if conflicts:
                add(
                    "error",
                    task_number,
                    group_label,
                    ErrorCode.PRINT_GROUP_CONDITION_CONFLICT.value,
                    display_message(ErrorCode.PRINT_GROUP_CONDITION_CONFLICT),
                    "；".join(conflicts)
                    + (f"；同时缺少{'、'.join(missing_fields)}" if missing_fields else "")
                    + "。请确认后将整组条件统一为同一值。",
                    first_row,
                    group_id,
                )
            elif missing_fields:
                missing_row = next(
                    row
                    for row, item in members
                    if any(
                        not str(item.get(field) or "").strip()
                        for field, _ in condition_fields
                    )
                )
                add(
                    "error",
                    task_number,
                    group_label,
                    ErrorCode.PRINT_GROUP_CONDITION_MISSING.value,
                    display_message(ErrorCode.PRINT_GROUP_CONDITION_MISSING),
                    f"该组缺少{'、'.join(missing_fields)}。本次补充只填写空缺人员，"
                    "不会覆盖组内已有值；若补充值与已有值不同，系统会继续报告打印组条件不一致。",
                    missing_row,
                    group_id,
                )

        review_issue_groups: set[tuple[str, str, str]] = set()
        unresolved_print_groups: set[tuple[str, str]] = set()
        for row_number, item in enumerate(requests, start=2):
            if not isinstance(item, dict):
                continue
            task_number = str(item.get("task_number") or "").strip()
            person_name = str(item.get("name") or "").strip()
            group_id = str(item.get("group_id") or "").strip()
            group_sequence = int(item.get("group_sequence") or 0)
            group_label = f"打印组 {group_sequence}" if group_sequence else "默认打印组"
            group_key = (task_number, group_id or f"row:{row_number}")
            resolved_print_mode = str(
                item.get("resolved_print_mode") or ""
            ).strip()
            group_people_count = int(item.get("group_people_count") or 0)
            if (
                group_people_count > 1
                and not resolved_print_mode
                and group_key not in unresolved_print_groups
            ):
                unresolved_print_groups.add(group_key)
                add(
                    "pending",
                    task_number,
                    group_label,
                    ErrorCode.AI_PRINT_MODE_REQUIRED.value,
                    "打印组划分需要人工确认",
                    "原文未明确多人是否属于同一打印组；当前按一个打印组展示，请人工确认。",
                    row_number,
                    group_id,
                )
            reasons = item.get("review_reasons")
            if isinstance(reasons, list):
                details = "；".join(dict.fromkeys(str(value).strip() for value in reasons if str(value).strip()))
                review_key = (group_key[0], group_key[1], details)
                if details and review_key not in review_issue_groups:
                    review_issue_groups.add(review_key)
                    add(
                        "warning",
                        task_number,
                        group_label if group_id else person_name,
                        ErrorCode.AI_REVIEW_REQUIRED.value,
                        display_message(ErrorCode.AI_REVIEW_REQUIRED),
                        details,
                        row_number,
                        group_id,
                    )
            warnings = item.get("warnings")
            if isinstance(warnings, list):
                details = "；".join(dict.fromkeys(str(value).strip() for value in warnings if str(value).strip()))
                if details:
                    add(
                        "info",
                        task_number,
                        person_name,
                        ErrorCode.AI_EXTRACTION_WARNING.value,
                        display_message(ErrorCode.AI_EXTRACTION_WARNING),
                        details,
                        row_number,
                        group_id,
                    )
            if not str(item.get("social_security_number") or "").strip():
                match = item.get("identity_match")
                match = match if isinstance(match, dict) else {}
                raw_candidates = match.get("candidates")
                candidate_items = (
                    raw_candidates if isinstance(raw_candidates, list) else []
                )
                public_candidates = []
                for candidate_index, candidate in enumerate(
                    candidate_items,
                    start=1,
                ):
                    if not isinstance(candidate, dict):
                        continue
                    identity = str(
                        candidate.get("identity_number") or ""
                    ).strip()
                    masked_identity = (
                        f"{identity[:4]}**********{identity[-4:]}"
                        if len(identity) >= 8
                        else "未维护"
                    )
                    public_candidates.append(
                        {
                            "candidate_id": RightsWebService._candidate_id(
                                candidate,
                                candidate_index,
                            ),
                            "employee_code": str(
                                candidate.get("employee_code") or ""
                            ).strip(),
                            "name": str(candidate.get("name") or person_name).strip(),
                            "masked_identity": masked_identity,
                            "department": str(
                                candidate.get("department") or ""
                            ).strip(),
                            "company": str(
                                candidate.get("company") or ""
                            ).strip(),
                            "status": str(
                                candidate.get("status")
                                or candidate.get("is_quit")
                                or ""
                            ).strip(),
                        }
                    )
                add(
                    "pending",
                    task_number,
                    person_name,
                    str(match.get("code") or ErrorCode.IDENTITY_MATCH_PENDING.value),
                    str(match.get("message") or display_message(ErrorCode.IDENTITY_MATCH_PENDING)),
                    str(match.get("details") or "人员身份证号尚未匹配"),
                    row_number,
                    group_id,
                    public_candidates,
                )
        return issues

    def submit_nocobase_application(
        self,
        detail: NocoBaseRightsApplicationDetail,
        *,
        account_id: int,
        upload_to_erp: bool,
    ) -> TaskSnapshot:
        if not detail.related_persons:
            raise ValueError("当前申请没有申请人员，无法打印权益单")
        records = self._nocobase_records(detail)
        preferences = self.settings_service.preferences()
        groups = self.loader.plan(records, ExportMode.BATCH, preferences.batch_size)
        task_root = self.settings_service.runtime_root / "tasks"
        source = task_root / (
            f"NocoBase权益申请_{detail.code}_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
        )
        self.template.write_records(source, records, include_print_groups=False)
        account = self.settings_service.account(account_id, SystemType.JSHRSS)
        request = self._request(
            groups=groups,
            mode=ExportMode.BATCH,
            source=source,
            label=detail.code,
            upload_to_erp=upload_to_erp,
        )
        return self._submit(
            account,
            request,
            title=f"打印权益申请 {detail.code}",
        )

    def _submit(
        self,
        account: SystemAccount,
        request: ExcelTaskRequest,
        *,
        title: str,
    ) -> TaskSnapshot:
        label = account.display_name or self._mask_account(account.account)
        return self.coordinator.submit(
            title=title,
            operation="rights_statement.acquire",
            kind=TaskKind.JSHRSS_BROWSER,
            resource_key=str(account.id),
            resource_label=label,
            runner=lambda context: self._run(context, account, request),
        )

    def _run(
        self,
        context: TaskContext,
        account: SystemAccount,
        request: ExcelTaskRequest,
    ) -> dict[str, object]:
        total = max(1, len(request.groups))
        progress_current = 0

        def progress(message: str) -> None:
            nonlocal progress_current
            matched = re.search(r"批次\s+(\d+)/(\d+)", message)
            if matched:
                progress_current = int(matched.group(1)) - 1
            context.report(message, current=progress_current, total=total)

        settings = self.settings_service.runtime_settings(
            rights_account=account,
        )
        context.report("正在准备智慧人社登录状态", current=0, total=total)
        with DesktopWorkbench(
            settings,
            self.logger,
            progress_callback=progress,
            cancel_check=lambda: context.cancelled,
        ) as workbench:
            result = workbench.run(request)
        context.report("正在整理结果文件", current=total, total=total)
        payload = self._result_payload(result)
        if request.upload_to_erp:
            erp_account = self.settings_service.repository.get_default_account(
                SystemType.ERP
            )
            if erp_account is None or not erp_account.account or not erp_account.password:
                payload["erp_warning"] = (
                    "已完成权益单下载，但未找到完整的 ERP 账号，"
                    "未启动自动上传"
                )
            else:
                erp_task = self.coordinator.submit(
                    title="上传权益单至 ERP",
                    operation="erp.rights.upload",
                    kind=TaskKind.ERP_WRITE,
                    resource_key=str(erp_account.id),
                    resource_label=erp_account.display_name or self._mask_account(erp_account.account),
                    runner=lambda erp_context: self._run_erp(
                        erp_context,
                        settings,
                        request,
                        result,
                    ),
                )
                payload["erp_task_id"] = erp_task.task_id
                payload["erp_message"] = (
                    "权益单已下载，ERP 上传已按账号单独排队"
                )
        return payload

    def _run_erp(
        self,
        context: TaskContext,
        settings,
        request: ExcelTaskRequest,
        result: ExcelRunResult,
    ) -> dict[str, object]:
        def progress(message: str) -> None:
            matched = re.search(r"ERP\s+(\d+)/(\d+)", message)
            current = int(matched.group(1)) if matched else 0
            total = int(matched.group(2)) if matched else 1
            context.report(message, current=current, total=total)

        items = ErpBatchUploadService(
            settings,
            self.logger,
            progress_callback=progress,
            cancel_check=lambda: context.cancelled,
        ).execute(request, result)
        refreshed = ExcelRightsStatementService(
            settings,
            self.logger,
        ).refresh_artifacts(
            result,
            request.source_excel,
            request.output_dir,
            items,
        )
        return self._result_payload(refreshed)

    def _result_payload(self, result: ExcelRunResult) -> dict[str, object]:
        paths: list[Path] = [result.manifest_path]
        if result.result_workbook_path is not None:
            paths.append(result.result_workbook_path)
        paths.extend(
            item.file_path
            for item in result.items
            if item.file_path is not None
        )
        unique_paths = list(dict.fromkeys(path.resolve() for path in paths if path.is_file()))
        archive_path = self._create_download_archive(result)
        return {
            "mode": result.mode.value,
            "total": result.total,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "erp_uploaded": result.erp_uploaded,
            "erp_failed": result.erp_failed,
            "artifacts": [self.artifacts.register(path) for path in unique_paths],
            "archive": (
                self.artifacts.register(archive_path)
                if archive_path is not None
                else None
            ),
            "items": [
                {
                    "row_number": item.row_number,
                    "success": item.success,
                    "code": item.code,
                    "message": item.message,
                    "file_name": item.file_path.name if item.file_path else None,
                    "erp_success": item.erp_success,
                    "erp_code": item.erp_code,
                    "erp_message": item.erp_message,
                    "erp_attachment_id": item.erp_attachment_id,
                }
                for item in result.items
            ],
        }

    def _create_download_archive(self, result: ExcelRunResult) -> Path | None:
        """Packages the user-facing PDF and Excel results into one download."""
        downloadable: list[Path] = []
        if (
            result.result_workbook_path is not None
            and result.result_workbook_path.is_file()
        ):
            downloadable.append(result.result_workbook_path.resolve())
        downloadable.extend(
            item.file_path.resolve()
            for item in result.items
            if item.file_path is not None and item.file_path.is_file()
        )
        downloadable = list(dict.fromkeys(downloadable))
        if not downloadable:
            return None

        output_dir = result.manifest_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        archive_path = output_dir / f"{output_dir.name}_完整结果.zip"
        temporary_path = archive_path.with_suffix(".zip.tmp")
        used_names: set[str] = set()
        try:
            with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:
                for path in downloadable:
                    archive.write(path, arcname=self._unique_archive_name(path.name, used_names))
            temporary_path.replace(archive_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return archive_path

    @staticmethod
    def _unique_archive_name(filename: str, used_names: set[str]) -> str:
        candidate = filename
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        counter = 2
        while candidate in used_names:
            candidate = f"{stem}_{counter}{suffix}"
            counter += 1
        used_names.add(candidate)
        return candidate

    def _request(
        self,
        *,
        groups: list,
        mode: ExportMode,
        source: Path,
        label: str,
        upload_to_erp: bool,
    ) -> ExcelTaskRequest:
        preferences = self.settings_service.preferences()
        output_root = (
            Path(preferences.output_path).expanduser()
            if preferences.output_path.strip()
            else self.settings_service.runtime_root / "output" / "rights"
        )
        output_dir = output_root / f"{label}_权益单_{datetime.now():%Y%m%d_%H%M%S}"
        return ExcelTaskRequest(
            groups=tuple(groups),
            mode=mode,
            output_dir=output_dir,
            source_excel=source,
            upload_to_erp=upload_to_erp,
        )

    def _import_path(self, import_id: str) -> Path:
        if not _IMPORT_ID.fullmatch(import_id):
            raise ValueError("权益单导入记录编号无效")
        matches = [
            path
            for suffix in (".xlsx", ".xlsm")
            if (path := self.import_root / f"{import_id}{suffix}").is_file()
        ]
        if len(matches) != 1 or not matches[0].is_file():
            raise ValueError("导入的 Excel 已失效，请重新上传")
        return matches[0]

    def _nocobase_records(
        self,
        detail: NocoBaseRightsApplicationDetail,
    ) -> list[EmployeeRecord]:
        sequences: dict[str, int] = {}
        records: list[EmployeeRecord] = []
        for index, person in enumerate(detail.related_persons, start=2):
            logical_group = (
                f"group:{person.print_group}"
                if person.print_group
                else f"person:{person.person_id}"
            )
            sequences.setdefault(logical_group, len(sequences) + 1)
            print_mode = "combined" if person.print_group else "individual"
            records.append(
                EmployeeRecord(
                    row_number=index,
                    unit=person.company,
                    department=person.department,
                    name=person.name,
                    identity_number=person.identity_number,
                    insurance_type=self._insurance_label(person.insurance_type),
                    start_month=self._month(person.start_month),
                    end_month=self._month(person.end_month),
                    task_number=detail.code,
                    print_group_id=f"{detail.application_id}:{logical_group}",
                    print_group_label=person.print_group or "单独打印",
                    print_group_sequence=sequences[logical_group],
                    source_print_mode=print_mode,
                    resolved_print_mode=print_mode,
                )
            )
        return self.loader.validate_records(records)

    @staticmethod
    def _preview_record(record: EmployeeRecord) -> dict[str, object]:
        identity = record.identity_number
        masked = f"{identity[:4]}**********{identity[-4:]}" if len(identity) >= 8 else "****"
        return {
            "row_number": record.row_number,
            "task_number": record.task_number,
            "print_group": record.print_group_label,
            "unit": record.unit,
            "department": record.department,
            "name": record.name,
            "identity_number": masked,
            "insurance_type": record.insurance_type,
            "start_month": record.start_month,
            "end_month": record.end_month,
        }

    @staticmethod
    def _insurance_label(value: str) -> str:
        normalized = value.strip().lower()
        return {
            "elderly_care": "养老",
            "pension": "养老",
            "work_injury": "工伤",
            "industrial_injury": "工伤",
            "unemployment": "失业",
        }.get(normalized, value.strip())

    @staticmethod
    def _month(value) -> str:
        if value is None:
            return ""
        localized = value.astimezone() if value.tzinfo is not None else value
        return localized.strftime("%Y%m")

    @staticmethod
    def _mask_account(value: str) -> str:
        return value[:2] + "*" * max(4, len(value) - 4) + value[-2:]
