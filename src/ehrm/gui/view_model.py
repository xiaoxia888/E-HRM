from __future__ import annotations

import logging
import re
import shutil
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ehrm import __version__
from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.preferences import UserPreferences, UserPreferencesStore
from ehrm.core.settings import AppSettings, select_ai_model
from ehrm.modules.ai.models import ReasoningMode
from ehrm.gui.erp_connection_worker import ErpConnectionWorker
from ehrm.gui.erp_task_extraction_worker import (
    ErpTaskExtractionRequest,
    ErpTaskExtractionWorker,
)
from ehrm.gui.erp_upload_worker import ManualErpUploadWorker
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.gui.worker import AutomationWorker
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.erp.file_validation import (
    ErpUploadFileValidator,
    ValidatedUploadFile,
)
from ehrm.modules.erp.credential_store import (
    ErpCredentialStore,
    RightsCredentialStore,
)
from ehrm.modules.erp.models import ErpCredentials, ErpUploadResult
from ehrm.modules.rights_statement.excel_models import (
    EmployeeRecord,
    ExcelRunResult,
    ExcelTaskRequest,
    ExportMode,
    WorkGroup,
)


class DesktopViewModel(QObject):
    """QML-facing state and commands; business services remain UI-agnostic."""

    recordsChanged = Signal()
    planChanged = Signal()
    fileChanged = Signal()
    modeChanged = Signal()
    batchSizeChanged = Signal()
    outputPathChanged = Signal()
    uploadToErpChanged = Signal()
    runningChanged = Signal()
    stoppingChanged = Signal()
    statusChanged = Signal()
    progressChanged = Signal()
    confirmationChanged = Signal()
    erpUploadFileChanged = Signal()
    erpUploadingChanged = Signal()
    erpUploadStatusChanged = Signal()
    preferencesChanged = Signal()
    erpAccountChanged = Signal()
    rightsAccountChanged = Signal()
    erpConnectionChanged = Signal()
    erpTaskExtractionChanged = Signal()
    pdfPreviewChanged = Signal()

    validationFailed = Signal(str, str)
    notification = Signal(str, str)
    confirmationReady = Signal()
    executionFinished = Signal(str, str, str)
    erpFileReady = Signal()
    manualErpUploadFinished = Signal(str, str, str)
    erpTaskExtractionStarted = Signal()
    erpTaskExtractionFinished = Signal(str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        start_worker: bool = True,
    ) -> None:
        super().__init__()
        self._preferences_store = UserPreferencesStore(
            settings.browser.user_data_dir.parent / "preferences.json"
        )
        self._preferences = self._preferences_store.load()
        self._credential_store = ErpCredentialStore()
        self._rights_credential_store = RightsCredentialStore()
        self._base_settings = settings
        self._settings = self._settings_with_preferences(settings)
        self._logger = logger
        self._loader = RightsStatementExcelLoader()
        self._template = RightsStatementTemplateService()
        self._records: list[EmployeeRecord] = []
        self._records_edited = False
        self._record_source = ""
        self._erp_task_result: dict[str, object] | None = None
        self._record_issues: list[dict[str, object]] = []
        self._groups: list[WorkGroup] = []
        self._source_excel: Path | None = None
        # Individual export is the safer default: importing a file must not
        # silently merge employees unless the operator chooses batch mode.
        self._mode = ExportMode(self._preferences.export_mode)
        self._batch_size = self._preferences.batch_size
        configured_output = Path(self._preferences.output_path).expanduser()
        self._output_path = (
            configured_output
            if self._preferences.output_path and configured_output.is_dir()
            else self._default_download_dir()
        )
        self._upload_to_erp = self._preferences.upload_to_erp
        self._running = False
        self._stopping = False
        self._status = "准备就绪"
        self._progress_current = 0
        self._progress_total = 1
        self._pending_output_dir: Path | None = None
        self._last_output_dir: Path | None = None
        self._last_pdf_files: list[Path] = []
        self._generated_source_excel: Path | None = None
        self._worker: AutomationWorker | None = None
        self._erp_upload_file: ValidatedUploadFile | None = None
        self._erp_uploading = False
        self._erp_upload_status = "请选择需要上传的文件"
        self._erp_upload_worker: ManualErpUploadWorker | None = None
        self._erp_connection_worker: ErpConnectionWorker | None = None
        self._erp_connection_status = "尚未测试连接"
        self._erp_connection_success = False
        self._erp_task_extraction_worker: ErpTaskExtractionWorker | None = None
        self._erp_task_extraction_running = False
        self._erp_task_extraction_stopping = False
        self._erp_task_extraction_status = "准备就绪"
        self._erp_task_extraction_current = 0
        self._erp_task_extraction_total = 0
        self._erp_task_extraction_task = ""
        self._erp_password_stored = bool(
            self._credential_store.load_password(self._preferences.erp_username)
        )
        self._rights_password_stored = bool(
            self._rights_credential_store.load_password(
                self._rights_account_key(
                    self._preferences.rights_credit_code,
                    self._preferences.rights_mobile,
                )
            )
        )
        self._worker_enabled = start_worker
        if start_worker:
            self._start_worker()

    def _start_worker(self) -> None:
        self._worker = AutomationWorker(self._settings, self._logger)
        self._worker.status_changed.connect(self._on_status)
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    @Property("QVariantList", notify=recordsChanged)
    def records(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record in self._records:
            row_issues = [
                item
                for item in self._record_issues
                if int(item.get("rowNumber") or 0) == record.row_number
            ]
            row_status = self._row_status(row_issues)
            rows.append({
                "status": "通过",
                "rowNumber": record.row_number,
                "rowStatus": row_status,
                "rowStatusLabel": {
                    "error": "错误",
                    "warning": "待复核",
                    "info": "提示",
                    "success": "正常",
                }[row_status],
                "rowIssueCount": len(row_issues),
                "rowIssueTooltip": self._row_issue_tooltip(row_issues),
                "unit": record.unit or "-",
                "department": record.department or "-",
                "name": record.name,
                "identity": record.identity_number or "待匹配",
                "insurance": record.insurance_type,
                "startMonth": record.start_month or (
                    "待确认" if self._record_source == "erp" else ""
                ),
                "endMonth": record.end_month or (
                    "待确认" if self._record_source == "erp" else ""
                ),
                "taskNumber": record.task_number,
                "printGroup": (
                    f"组{record.print_group_sequence}"
                    if record.print_group_sequence
                    else "-"
                ),
                "printGroupId": record.print_group_id,
            })
        return rows

    @Property(int, notify=planChanged)
    def peopleCount(self) -> int:
        return len(self._records)

    @Property(int, notify=planChanged)
    def conditionCount(self) -> int:
        if self._record_source == "erp":
            return len(
                {
                    (record.task_number, record.print_group_id)
                    for record in self._records
                    if record.print_group_id
                }
            )
        return len({record.group_key for record in self._records})

    @Property(bool, notify=fileChanged)
    def erpRecordSource(self) -> bool:
        return self._record_source == "erp"

    @Property(str, notify=fileChanged)
    def peopleMetricTitle(self) -> str:
        return "人员记录" if self._record_source == "erp" else "人员"

    @Property(int, notify=planChanged)
    def uniquePeopleCount(self) -> int:
        identities = {
            record.identity_number or f"name:{record.name}"
            for record in self._records
        }
        return len(identities)

    @Property("QVariantList", notify=planChanged)
    def printGroups(self) -> list[dict[str, object]]:
        grouped: dict[tuple[str, str], list[EmployeeRecord]] = {}
        for record in self._records:
            if not record.print_group_id:
                continue
            grouped.setdefault(
                (record.task_number, record.print_group_id), []
            ).append(record)
        summaries: list[dict[str, object]] = []
        for records in grouped.values():
            first = records[0]
            mode = first.resolved_print_mode
            pdf_count = (
                len(records)
                if mode == "individual"
                else (
                    (len(records) + self._batch_size - 1) // self._batch_size
                    if mode == "combined"
                    else 0
                )
            )
            summaries.append(
                {
                    "groupId": first.print_group_id,
                    "sequence": first.print_group_sequence,
                    "label": f"组{first.print_group_sequence}",
                    "taskNumber": first.task_number,
                    "peopleCount": len(records),
                    "insurance": first.insurance_type,
                    "startMonth": first.start_month or "待确认",
                    "endMonth": first.end_month or "待确认",
                    "sourceMode": first.source_print_mode,
                    "resolvedMode": mode,
                    "modeLabel": {
                        "combined": "合并打印",
                        "individual": "每人单独一份",
                    }.get(mode, "待选择"),
                    "modeRequired": not bool(mode),
                    "pdfCount": pdf_count,
                }
            )
        return summaries

    @Property(int, notify=planChanged)
    def expectedPdfCount(self) -> int:
        return len(self._groups)

    @Property(int, notify=planChanged)
    def batchExpectedPdfCount(self) -> int:
        if not self._records:
            return 0
        return len(
            self._loader.plan(self._records, ExportMode.BATCH, self._batch_size)
        )

    @Property(str, notify=fileChanged)
    def fileSummary(self) -> str:
        if self._record_source == "erp":
            return f"ERP 申请解析结果 · {len(self._records)} 条人员记录"
        if self._source_excel is None:
            return "尚未导入 Excel"
        return f"{self._source_excel.name} · {len(self._records)} 人"

    @Property(bool, notify=fileChanged)
    def imported(self) -> bool:
        return self._source_excel is not None and bool(self._records)

    @Property(bool, notify=fileChanged)
    def hasRecords(self) -> bool:
        return bool(self._records)

    @Property(str, notify=fileChanged)
    def recordStatusLabel(self) -> str:
        if self._record_source == "erp":
            issue_count = self._actionable_record_issue_count()
            return (
                f"· 解析完成，{issue_count} 项待处理"
                if issue_count
                else "· 解析完成"
            )
        return "· 校验通过"

    @Property(int, notify=recordsChanged)
    def recordIssueCount(self) -> int:
        return self._actionable_record_issue_count()

    @Property(int, notify=recordsChanged)
    def recordDetailCount(self) -> int:
        return len(self._record_issues)

    @Property("QVariantList", notify=recordsChanged)
    def recordIssues(self) -> list[dict[str, object]]:
        return list(self._record_issues)

    @Property(bool, notify=erpTaskExtractionChanged)
    def erpTaskExtractionRunning(self) -> bool:
        return self._erp_task_extraction_running

    @Property(bool, notify=erpTaskExtractionChanged)
    def erpTaskExtractionStopping(self) -> bool:
        return self._erp_task_extraction_stopping

    @Property(str, notify=erpTaskExtractionChanged)
    def erpTaskExtractionStatus(self) -> str:
        return self._erp_task_extraction_status

    @Property(int, notify=erpTaskExtractionChanged)
    def erpTaskExtractionProgressCurrent(self) -> int:
        return self._erp_task_extraction_current

    @Property(int, notify=erpTaskExtractionChanged)
    def erpTaskExtractionProgressTotal(self) -> int:
        return self._erp_task_extraction_total

    @Property(str, notify=erpTaskExtractionChanged)
    def erpTaskExtractionCurrentTask(self) -> str:
        return self._erp_task_extraction_task

    @Property(str, notify=modeChanged)
    def exportMode(self) -> str:
        return self._mode.value

    @Property(int, notify=batchSizeChanged)
    def batchSize(self) -> int:
        return self._batch_size

    @Property(str, notify=outputPathChanged)
    def outputPath(self) -> str:
        return str(self._output_path)

    @Property("QVariantList", notify=pdfPreviewChanged)
    def lastPdfFiles(self) -> list[dict[str, object]]:
        return [
            {
                "name": path.name,
                "path": str(path),
                "url": QUrl.fromLocalFile(str(path)),
                "directory": str(path.parent),
            }
            for path in self._last_pdf_files
        ]

    @Property(int, notify=pdfPreviewChanged)
    def lastPdfCount(self) -> int:
        return len(self._last_pdf_files)

    @Property(bool, notify=pdfPreviewChanged)
    def hasPreviewablePdfs(self) -> bool:
        return bool(self._last_pdf_files)

    @Property(bool, notify=uploadToErpChanged)
    def uploadToErp(self) -> bool:
        return self._upload_to_erp

    @Property(QUrl, constant=True)
    def downloadsFolderUrl(self) -> QUrl:
        return QUrl.fromLocalFile(str(self._default_download_dir()))

    @Property(QUrl, constant=True)
    def templateDefaultUrl(self) -> QUrl:
        return QUrl.fromLocalFile(
            str(self._default_download_dir() / "单位权益单导入模板.xlsx")
        )

    @Property(bool, notify=erpUploadFileChanged)
    def erpFileSelected(self) -> bool:
        return self._erp_upload_file is not None

    @Property(str, notify=erpUploadFileChanged)
    def erpFileName(self) -> str:
        return self._erp_upload_file.path.name if self._erp_upload_file else ""

    @Property(str, notify=erpUploadFileChanged)
    def erpFileDetails(self) -> str:
        if self._erp_upload_file is None:
            return ""
        return (
            f"{self._erp_upload_file.type_label} · "
            f"{self._format_file_size(self._erp_upload_file.size)}"
        )

    @Property(bool, notify=erpUploadingChanged)
    def erpUploading(self) -> bool:
        return self._erp_uploading

    @Property(str, notify=erpUploadStatusChanged)
    def erpUploadStatus(self) -> str:
        return self._erp_upload_status

    @Property(str, notify=erpAccountChanged)
    def erpUsername(self) -> str:
        return self._preferences.erp_username

    @Property(bool, notify=erpAccountChanged)
    def erpPasswordStored(self) -> bool:
        return self._erp_password_stored

    @Slot(str, result=str)
    def loadSavedErpPassword(self, username: str) -> str:
        """Returns the saved password only for the configured ERP account.

        QML calls this lazily when the operator focuses the password field, so
        the secret is not copied into the visual tree merely by opening the
        settings page.
        """
        normalized = username.strip()
        if not normalized or normalized != self._preferences.erp_username:
            return ""
        return self._credential_store.load_password(normalized) or ""

    @Property(str, notify=rightsAccountChanged)
    def rightsCreditCode(self) -> str:
        return self._preferences.rights_credit_code

    @Property(str, notify=rightsAccountChanged)
    def rightsMobile(self) -> str:
        return self._preferences.rights_mobile

    @Property(bool, notify=rightsAccountChanged)
    def rightsPasswordStored(self) -> bool:
        return self._rights_password_stored

    @Slot(str, str, result=str)
    def loadSavedRightsPassword(self, credit_code: str, mobile: str) -> str:
        normalized_credit = credit_code.strip()
        normalized_mobile = mobile.strip()
        if (
            normalized_credit != self._preferences.rights_credit_code
            or normalized_mobile != self._preferences.rights_mobile
        ):
            return ""
        key = self._rights_account_key(normalized_credit, normalized_mobile)
        return self._rights_credential_store.load_password(key) or ""

    @Property(bool, notify=erpConnectionChanged)
    def erpConnectionBusy(self) -> bool:
        return self._erp_connection_worker is not None

    @Property(str, notify=erpConnectionChanged)
    def erpConnectionStatus(self) -> str:
        return self._erp_connection_status

    @Property(bool, notify=erpConnectionChanged)
    def erpConnectionSuccess(self) -> bool:
        return self._erp_connection_success

    @Property(bool, notify=preferencesChanged)
    def openOutputFolderAfterRun(self) -> bool:
        return self._preferences.open_output_folder

    @Property(str, notify=preferencesChanged)
    def executionSpeed(self) -> str:
        return self._preferences.execution_speed

    @Property(str, notify=preferencesChanged)
    def aiReasoningMode(self) -> str:
        return self._settings.ai.default_reasoning_mode

    @Property(str, notify=preferencesChanged)
    def aiModelProfile(self) -> str:
        return self._settings.ai.profile_id.value

    @Property("QVariantList", notify=preferencesChanged)
    def aiModelOptions(self) -> list[dict[str, object]]:
        return [
            {
                "value": item.profile_id.value,
                "label": item.display_name,
                "ollamaName": item.model,
                "nativeContextLength": item.native_context_length,
                "numCtx": item.num_ctx,
                "numPredict": item.num_predict,
                "timeoutSeconds": item.request_timeout_seconds,
                "keepAlive": item.keep_alive,
            }
            for item in self._base_settings.ai_models
        ]

    @Property("QVariantMap", notify=preferencesChanged)
    def aiModelDetails(self) -> dict[str, object]:
        item = self._settings.ai
        return {
            "value": item.profile_id.value,
            "label": item.display_name,
            "ollamaName": item.model,
            "nativeContextLength": item.native_context_length,
            "numCtx": item.num_ctx,
            "numPredict": item.num_predict,
            "timeoutSeconds": item.request_timeout_seconds,
            "keepAlive": item.keep_alive,
            "sourceUrl": item.source_url,
        }

    @Property(str, notify=preferencesChanged)
    def aiModelRuntimeLabel(self) -> str:
        item = self._settings.ai
        reasoning_label = ReasoningMode.parse(
            item.default_reasoning_mode
        ).label
        return f"{item.display_name}（{item.model}）· {reasoning_label}"

    @Property("QVariantList", notify=preferencesChanged)
    def aiReasoningOptions(self) -> list[dict[str, str]]:
        return [
            {"value": value, "label": ReasoningMode.parse(value).label}
            for value in self._settings.ai.reasoning_modes
        ]

    @Property(int, notify=preferencesChanged)
    def noResultConfirmSeconds(self) -> int:
        return self._preferences.no_result_confirm_seconds

    @Property(int, notify=preferencesChanged)
    def previewDownloadDelayMs(self) -> int:
        return self._preferences.preview_download_delay_ms

    @Property(int, notify=preferencesChanged)
    def downloadTimeoutSeconds(self) -> int:
        return self._preferences.download_timeout_seconds

    @Property(str, constant=True)
    def logsPath(self) -> str:
        return str(self._settings.browser.user_data_dir.parent.parent / "logs")

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return __version__

    @Property(bool, notify=runningChanged)
    def running(self) -> bool:
        return self._running

    @Property(bool, notify=stoppingChanged)
    def stopping(self) -> bool:
        return self._stopping

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status

    @Property(int, notify=progressChanged)
    def progressCurrent(self) -> int:
        return self._progress_current

    @Property(int, notify=progressChanged)
    def progressTotal(self) -> int:
        return self._progress_total

    @Property(str, notify=planChanged)
    def planMessage(self) -> str:
        if self._record_source == "erp":
            issue_count = self._actionable_record_issue_count()
            if issue_count:
                return (
                    f"ERP 申请已解析，发现 {issue_count} 项待处理问题。"
                    "请查看问题明细后再继续。"
                )
            return (
                f"ERP 申请已拆分为 {self.conditionCount} 个打印组，"
                f"共 {len(self._records)} 条人员记录、"
                f"{self.uniquePeopleCount} 名实际人员。"
            )
        if not self._records:
            return "批量模式仅合并任务编号、险种及起止年月完全相同的人员。"
        if self._mode is ExportMode.INDIVIDUAL:
            return (
                f"当前选择每人单独一份，{len(self._records)} 人预计生成 "
                f"{len(self._groups)} 份 PDF。"
            )
        return (
            f"检测到 {self.conditionCount} 组查询条件；相同条件人员合并后预计生成 "
            f"{len(self._groups)} 份 PDF。"
        )

    @Property("QVariantList", notify=planChanged)
    def conditionSummaries(self) -> list[dict[str, object]]:
        if self._record_source == "erp":
            return self.printGroups
        counts = Counter(record.group_key for record in self._records)
        summaries: list[dict[str, object]] = []
        for (task_number, insurance, start, end), count in counts.items():
            pdf_count = (
                count
                if self._mode is ExportMode.INDIVIDUAL
                else (count + self._batch_size - 1) // self._batch_size
            )
            summaries.append(
                {
                    "taskNumber": task_number,
                    "insurance": insurance,
                    "startMonth": start,
                    "endMonth": end,
                    "peopleCount": count,
                    "pdfCount": pdf_count,
                }
            )
        return summaries

    @Slot(str, str)
    def setPrintGroupMode(self, group_id: str, value: str) -> None:
        normalized_group = group_id.strip()
        normalized_mode = value.strip()
        if normalized_mode not in {"combined", "individual"}:
            return
        if not normalized_group:
            return
        changed = False
        updated: list[EmployeeRecord] = []
        for record in self._records:
            if record.print_group_id == normalized_group:
                changed = changed or record.resolved_print_mode != normalized_mode
                updated.append(
                    replace(record, resolved_print_mode=normalized_mode)
                )
            else:
                updated.append(record)
        if not changed:
            return
        self._records = updated
        if self._erp_task_result is not None:
            requests = self._erp_task_result.get("rights_statement_requests")
            if isinstance(requests, list):
                for item in requests:
                    if (
                        isinstance(item, dict)
                        and str(item.get("group_id") or "") == normalized_group
                    ):
                        item["resolved_print_mode"] = normalized_mode
        self._record_issues = [
            issue
            for issue in self._record_issues
            if not (
                issue.get("code") == ErrorCode.AI_PRINT_MODE_REQUIRED.value
                and issue.get("groupId") == normalized_group
            )
        ]
        self.recordsChanged.emit()
        self._refresh_plan()

    @Slot(int, str, str, str, str, str, str, str, result=bool)
    def updateRecord(
        self,
        row_number: int,
        unit: str,
        department: str,
        name: str,
        identity: str,
        insurance: str,
        start_month: str,
        end_month: str,
    ) -> bool:
        target = next(
            (
                record
                for record in self._records
                if record.row_number == row_number
            ),
            None,
        )
        if target is None or self._running:
            return False
        candidate = replace(
            target,
            unit=unit,
            department=department,
            name=name,
            identity_number=identity,
            insurance_type=insurance,
            start_month=start_month,
            end_month=end_month,
        )
        try:
            candidate = self._loader.normalize_record(candidate)
            updated = [
                (
                    replace(
                        record,
                        insurance_type=candidate.insurance_type,
                        start_month=candidate.start_month,
                        end_month=candidate.end_month,
                    )
                    if target.print_group_id
                    and record.print_group_id == target.print_group_id
                    and record.task_number == target.task_number
                    else record
                )
                for record in self._records
            ]
            updated = [
                candidate if record.row_number == row_number else record
                for record in updated
            ]
            updated = self._loader.validate_records(updated)
        except (ValueError, EhrmError) as exc:
            details = getattr(exc, "details", None) or str(exc)
            self.validationFailed.emit("修改内容校验失败", details)
            return False

        self._records = updated
        self._records_edited = True
        self._sync_edited_records_to_erp_result(row_number, target.print_group_id)
        if self._erp_task_result is not None:
            self._record_issues = self._build_erp_record_issues(
                self._erp_task_result
            )
        self.recordsChanged.emit()
        self._refresh_plan()
        return True

    @Property(str, notify=confirmationChanged)
    def confirmationOutputPath(self) -> str:
        return str(self._pending_output_dir or "")

    @Property(str, notify=confirmationChanged)
    def lastOutputPath(self) -> str:
        return str(self._last_output_dir or "")

    @Slot(str)
    def setExportMode(self, value: str) -> None:
        try:
            mode = ExportMode(value)
        except ValueError:
            return
        if self._mode is mode:
            return
        self._mode = mode
        self._save_preferences(export_mode=mode.value)
        self.modeChanged.emit()
        self._refresh_plan()

    @Slot(int)
    def setBatchSize(self, value: int) -> None:
        normalized = max(1, min(100, value))
        if normalized == self._batch_size:
            return
        self._batch_size = normalized
        self._save_preferences(batch_size=normalized)
        self.batchSizeChanged.emit()
        self._refresh_plan()

    @Slot(bool)
    def setUploadToErp(self, value: bool) -> None:
        if self._upload_to_erp == value:
            return
        self._upload_to_erp = value
        self._save_preferences(upload_to_erp=value)
        self.uploadToErpChanged.emit()

    @Slot(QUrl)
    def importExcel(self, url: QUrl) -> None:
        path = self._url_path(url)
        if path is None:
            return
        try:
            records = self._loader.load(path)
        except EhrmError as exc:
            self._clear_import()
            generic = display_message(exc.code, exc.message)
            summary = exc.message.strip() or generic
            self.validationFailed.emit(summary, exc.details or "")
            return
        except Exception as exc:
            self._clear_import()
            self.validationFailed.emit("无法读取 Excel 文件", str(exc))
            return
        self._source_excel = path
        self._record_source = "excel"
        self._erp_task_result = None
        self._record_issues = []
        self._records = records
        self._records_edited = False
        self.fileChanged.emit()
        self.recordsChanged.emit()
        self._refresh_plan()

    @Slot(QUrl)
    def saveTemplate(self, url: QUrl) -> None:
        path = self._url_path(url)
        if path is None:
            return
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        try:
            self._template.write(path)
        except Exception as exc:
            self.notification.emit("模板生成失败", str(exc))
            return
        self.notification.emit("模板已生成", f"Excel 模板已保存至：\n{path}")

    @Slot(QUrl)
    def setOutputFolder(self, url: QUrl) -> None:
        path = self._url_path(url)
        if path is None:
            return
        self._output_path = path
        self._save_preferences(output_path=str(path))
        self.outputPathChanged.emit()

    @Slot(QUrl)
    def selectErpUploadFile(self, url: QUrl) -> None:
        if self._erp_uploading:
            return
        path = self._url_path(url)
        if path is None:
            return
        try:
            validated = ErpUploadFileValidator().validate(path)
        except EhrmError as exc:
            self.notification.emit(
                "文件校验失败",
                exc.message or display_message(exc.code),
            )
            return
        except Exception as exc:
            self.notification.emit("文件校验失败", str(exc))
            return
        self._erp_upload_file = validated
        self._set_erp_upload_status("文件校验通过，请填写任务编号")
        self.erpUploadFileChanged.emit()
        self.erpFileReady.emit()

    @Slot()
    def clearErpUploadFile(self) -> None:
        if self._erp_uploading:
            return
        self._erp_upload_file = None
        self._set_erp_upload_status("请选择需要上传的文件")
        self.erpUploadFileChanged.emit()

    @Slot(str)
    def uploadSelectedFileToErp(self, task_number: str) -> None:
        if self._erp_uploading:
            return
        if self._erp_upload_file is None:
            self.notification.emit("尚未选择文件", "请先选择需要上传的文件")
            return
        normalized = task_number.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", normalized):
            self.notification.emit(
                "任务编号格式错误",
                "任务编号只能包含字母、数字、下划线和短横线",
            )
            return
        worker = ManualErpUploadWorker(
            self._settings,
            self._logger,
            normalized,
            self._erp_upload_file.path,
        )
        worker.status_changed.connect(self._on_manual_erp_status)
        worker.completed.connect(self._on_manual_erp_completed)
        worker.failed.connect(self._on_manual_erp_failed)
        worker.finished.connect(self._on_manual_erp_worker_finished)
        self._erp_upload_worker = worker
        self._set_erp_uploading(True)
        self._set_erp_upload_status("正在启动 ERP 上传")
        worker.start()

    @Slot()
    def requestManualErpStop(self) -> None:
        if self._erp_upload_worker is None or not self._erp_uploading:
            return
        self._set_erp_upload_status("正在安全停止 ERP 上传…")
        self._erp_upload_worker.cancel()

    @Slot(str, str)
    def saveErpAccount(self, username: str, password: str) -> None:
        normalized = username.strip()
        if not normalized:
            self.notification.emit("账号不能为空", "请输入 ERP 用户名")
            return
        existing_password = (
            self._credential_store.load_password(normalized)
            if normalized == self._preferences.erp_username
            else None
        )
        if not password and not existing_password:
            self.notification.emit("密码不能为空", "请输入 ERP 密码")
            return
        try:
            if password:
                if (
                    self._preferences.erp_username
                    and self._preferences.erp_username != normalized
                ):
                    self._credential_store.delete_password(
                        self._preferences.erp_username
                    )
                self._credential_store.save_password(normalized, password)
            if not self._save_preferences(erp_username=normalized):
                return
        except (EhrmError, OSError) as exc:
            message = exc.message if isinstance(exc, EhrmError) else str(exc)
            self.notification.emit("ERP 账号保存失败", message)
            return
        self._erp_password_stored = True
        self._erp_connection_success = False
        self._erp_connection_status = "账号已保存，尚未测试连接"
        self.erpAccountChanged.emit()
        self.erpConnectionChanged.emit()
        self.notification.emit("保存成功", "ERP 账号已安全保存")

    @Slot(str, str, str)
    def saveRightsAccount(
        self,
        credit_code: str,
        mobile: str,
        password: str,
    ) -> None:
        normalized_credit = credit_code.strip()
        normalized_mobile = mobile.strip()
        if not normalized_credit:
            self.notification.emit(
                "账号不能为空",
                "请输入统一社会信用代码、单位编号或机构编号",
            )
            return
        if not normalized_mobile:
            self.notification.emit("证件信息不能为空", "请输入证件号码或移动电话")
            return

        new_key = self._rights_account_key(normalized_credit, normalized_mobile)
        old_key = self._rights_account_key(
            self._preferences.rights_credit_code,
            self._preferences.rights_mobile,
        )
        existing_password = (
            self._rights_credential_store.load_password(new_key)
            if new_key == old_key
            else None
        )
        if not password and not existing_password:
            self.notification.emit("密码不能为空", "请输入江苏智慧人社密码")
            return
        try:
            if password:
                if old_key and old_key != new_key:
                    self._rights_credential_store.delete_password(old_key)
                self._rights_credential_store.save_password(new_key, password)
                verified_password = self._rights_credential_store.load_password(
                    new_key
                )
                if verified_password != password:
                    raise OSError("密码写入系统凭据库后无法读取，请重新保存")
            if not self._save_preferences(
                rights_credit_code=normalized_credit,
                rights_mobile=normalized_mobile,
            ):
                return
        except (EhrmError, OSError) as exc:
            if isinstance(exc, EhrmError):
                message = exc.message
                if exc.details:
                    message += f"\n{exc.details}"
            else:
                message = str(exc)
            self.notification.emit("智慧人社账号保存失败", message)
            return

        self._rights_password_stored = True
        self._apply_automation_preferences()
        self.rightsAccountChanged.emit()
        self.notification.emit("保存成功", "江苏智慧人社账号已安全保存")

    @Slot(str, str)
    def testErpConnection(self, username: str, password: str) -> None:
        if self._erp_connection_worker is not None:
            return
        normalized = username.strip()
        resolved_password = password or self._credential_store.load_password(normalized)
        if not normalized or not resolved_password:
            self.notification.emit("账号信息不完整", "请填写 ERP 用户名和密码")
            return
        worker = ErpConnectionWorker(
            self._settings,
            self._logger,
            ErpCredentials(normalized, resolved_password),
        )
        worker.status_changed.connect(self._on_erp_connection_status)
        worker.succeeded.connect(self._on_erp_connection_succeeded)
        worker.failed.connect(self._on_erp_connection_failed)
        worker.finished.connect(self._on_erp_connection_finished)
        self._erp_connection_worker = worker
        self._erp_connection_success = False
        self._erp_connection_status = "正在测试 ERP 连接…"
        self.erpConnectionChanged.emit()
        worker.start()

    @Slot()
    def clearErpLoginState(self) -> None:
        if self._erp_uploading or self._erp_connection_worker is not None:
            self.notification.emit("当前无法清除", "请等待 ERP 操作结束后重试")
            return
        try:
            if self._settings.erp.user_data_dir.exists():
                shutil.rmtree(self._settings.erp.user_data_dir)
            self._settings.erp.user_data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notification.emit("清除失败", str(exc))
            return
        self._erp_connection_success = False
        self._erp_connection_status = "ERP 登录状态已清除"
        self.erpConnectionChanged.emit()
        self.notification.emit("清除成功", "下次 ERP 操作将重新登录")

    @Slot(str, str, str, str, str)
    def startErpTaskExtraction(
        self,
        application_code: str,
        status_values: str,
        transaction_type: str,
        start_date: str,
        end_date: str,
    ) -> None:
        if (
            self._erp_task_extraction_running
            or self._running
            or self._erp_uploading
            or self._erp_connection_worker is not None
        ):
            self.notification.emit("当前无法执行", "请先等待当前任务结束")
            return
        normalized_type = transaction_type.strip()
        if not normalized_type:
            self.notification.emit("查询条件不完整", "请选择事务类型")
            return
        try:
            statuses = tuple(
                int(value)
                for value in status_values.split(",")
                if value.strip()
            )
        except ValueError:
            self.notification.emit("查询条件错误", "申请状态格式不正确")
            return
        worker = ErpTaskExtractionWorker(
            self._settings,
            self._logger,
            ErpTaskExtractionRequest(
                transaction_type=normalized_type,
                statuses=statuses,
                application_code=application_code.strip(),
                start_date=start_date.strip(),
                end_date=end_date.strip(),
                reasoning_mode=self._settings.ai.default_reasoning_mode,
            ),
        )
        worker.status_changed.connect(self._on_erp_task_extraction_status)
        worker.progress_changed.connect(self._on_erp_task_extraction_progress)
        worker.completed.connect(self._on_erp_task_extraction_completed)
        worker.failed.connect(self._on_erp_task_extraction_failed)
        worker.cancelled.connect(self._on_erp_task_extraction_cancelled)
        worker.finished.connect(self._on_erp_task_extraction_worker_finished)
        self._erp_task_extraction_worker = worker
        self._erp_task_extraction_running = True
        self._erp_task_extraction_stopping = False
        self._erp_task_extraction_status = "正在启动 ERP 查询"
        self._erp_task_extraction_current = 0
        self._erp_task_extraction_total = 0
        self._erp_task_extraction_task = ""
        self.erpTaskExtractionChanged.emit()
        self.erpTaskExtractionStarted.emit()
        worker.start()

    @Slot()
    def requestErpTaskExtractionStop(self) -> None:
        worker = self._erp_task_extraction_worker
        if worker is None or not self._erp_task_extraction_running:
            return
        worker.cancel()
        self._erp_task_extraction_stopping = True
        self._erp_task_extraction_status = (
            "正在安全停止：当前模型请求完成后将保留结果并停止"
        )
        self.erpTaskExtractionChanged.emit()

    @Slot(bool)
    def setOpenOutputFolderAfterRun(self, value: bool) -> None:
        self._save_preferences(open_output_folder=value)
        self.preferencesChanged.emit()

    @Slot(str)
    def setExecutionSpeed(self, value: str) -> None:
        if value not in {"fast", "standard", "stable"}:
            return
        self._save_preferences(execution_speed=value)
        self._apply_automation_preferences()

    @Slot(str)
    def setAiReasoningMode(self, value: str) -> None:
        if value not in self._settings.ai.reasoning_modes:
            return
        if value == self._settings.ai.default_reasoning_mode:
            return
        if self._save_preferences(ai_reasoning_mode=value):
            self._settings = self._settings_with_preferences(self._base_settings)
            self.preferencesChanged.emit()

    @Slot(str)
    def setAiModelProfile(self, value: str) -> None:
        profile = next(
            (
                item
                for item in self._base_settings.ai_models
                if item.profile_id.value == value
            ),
            None,
        )
        if profile is None or profile.profile_id == self._settings.ai.profile_id:
            return
        current_mode = self._settings.ai.default_reasoning_mode
        selected_mode = (
            current_mode
            if current_mode in profile.reasoning_modes
            else profile.default_reasoning_mode
        )
        if self._save_preferences(
            ai_model_profile=profile.profile_id.value,
            ai_reasoning_mode=selected_mode,
        ):
            self._settings = self._settings_with_preferences(self._base_settings)
            self.preferencesChanged.emit()

    @Slot(int)
    def setNoResultConfirmSeconds(self, value: int) -> None:
        self._save_preferences(no_result_confirm_seconds=max(1, value))
        self._apply_automation_preferences()

    @Slot(int)
    def setPreviewDownloadDelayMs(self, value: int) -> None:
        self._save_preferences(preview_download_delay_ms=max(0, value))
        self._apply_automation_preferences()

    @Slot(int)
    def setDownloadTimeoutSeconds(self, value: int) -> None:
        self._save_preferences(download_timeout_seconds=max(1, value))
        self._apply_automation_preferences()

    @Slot()
    def openLogsFolder(self) -> None:
        path = Path(self.logsPath)
        path.mkdir(parents=True, exist_ok=True)
        self.openFolder(str(path))

    @Slot()
    def clearTemporaryFiles(self) -> None:
        targets = [
            self._settings.browser.user_data_dir.parent / "screenshots",
            self._settings.browser.user_data_dir.parent / "session-state.json",
        ]
        try:
            for target in targets:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.is_file():
                    target.unlink()
        except OSError as exc:
            self.notification.emit("清理失败", str(exc))
            return
        self.notification.emit("清理完成", "临时截图和会话快照已清理")

    @Slot()
    def prepareExecution(self) -> None:
        if not self._records:
            self.notification.emit(
                "尚无可执行数据",
                "请先导入 Excel 或获取并解析 ERP 申请信息",
            )
            return
        try:
            self._records = self._loader.validate_records(self._records)
            self._refresh_plan()
        except EhrmError as exc:
            self.validationFailed.emit(
                exc.message or "数据校验失败",
                exc.details or exc.message,
            )
            return
        issue_count = self._actionable_record_issue_count()
        if issue_count:
            details = "\n".join(
                f"{item.get('taskNumber', '-')} · "
                f"{item.get('personName', '-')}：{item.get('details', '')}"
                for item in self._record_issues
                if str(item.get("level") or "") != "info"
            )
            self.validationFailed.emit(
                f"当前有 {issue_count} 项待处理问题",
                details,
            )
            return
        if not self._groups:
            self.validationFailed.emit(
                "没有可执行的打印组",
                "请检查每个打印组的打印方式和查询条件",
            )
            return
        if self._record_source == "excel" and self._source_excel is None:
            self.notification.emit("源文件不可用", "请重新导入 Excel 文件")
            return
        self._pending_output_dir = self._output_path / (
            f"权益单下载_{datetime.now():%Y%m%d_%H%M%S}"
        )
        self.confirmationChanged.emit()
        self.confirmationReady.emit()

    @Slot()
    def executePrepared(self) -> None:
        if (
            self._pending_output_dir is None
            or not self._groups
            or self._running
        ):
            return
        source_excel = self._source_excel
        if self._record_source == "erp" or self._records_edited:
            try:
                source_excel = self._create_records_source_workbook()
            except Exception as exc:
                self._logger.exception("生成 ERP 解析结果源工作簿失败")
                self.notification.emit("执行准备失败", str(exc))
                return
        if source_excel is None:
            self.notification.emit("执行准备失败", "没有可用的任务源数据")
            return
        request = ExcelTaskRequest(
            groups=tuple(self._groups),
            mode=self._mode,
            output_dir=self._pending_output_dir,
            source_excel=source_excel,
            upload_to_erp=self._upload_to_erp,
        )
        if self._last_pdf_files:
            self._last_pdf_files = []
            self.pdfPreviewChanged.emit()
        self._last_output_dir = self._pending_output_dir
        self.confirmationChanged.emit()
        self._set_running(True)
        self._set_stopping(False)
        self._set_status("正在启动浏览器")
        self._progress_current = 0
        self._progress_total = max(1, len(self._groups))
        self.progressChanged.emit()
        if self._worker is None or not self._worker.submit(request):
            self._set_running(False)
            self._cleanup_generated_source_workbook()
            self.notification.emit("执行失败", "自动化工作线程已停止，请重新启动程序")

    @Slot()
    def requestStop(self) -> None:
        if not self._running or self._stopping or self._worker is None:
            return
        if not self._worker.cancel_current():
            return
        self._set_stopping(True)
        self._set_status("正在安全停止，已完成的文件将保留…")

    @Slot(str)
    def openFolder(self, path: str) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def openFileLocation(self, path: str) -> None:
        if not path:
            return
        target = Path(path).expanduser()
        directory = target.parent if target.suffix else target
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @Slot(result=bool)
    def preparePdfPreview(self) -> bool:
        available = [path for path in self._last_pdf_files if path.is_file()]
        if available != self._last_pdf_files:
            self._last_pdf_files = available
            self.pdfPreviewChanged.emit()
        if available:
            return True
        self.notification.emit(
            "无法预览 PDF",
            "本次生成的 PDF 已被移动或删除，请打开结果文件夹确认。",
        )
        return False

    def shutdown(self) -> None:
        """Stops the worker after Qt's UI event loop has finished.

        This deliberately is not a QML slot. PySide 6.10 on macOS can crash
        while converting a Python bool return value during a window-close
        meta-call, especially when QML teardown is already in progress.
        """
        if self._worker is not None:
            worker = self._worker
            if worker.isRunning():
                worker.shutdown()
                if not worker.wait(30_000):
                    self._logger.error("自动化工作线程未在 30 秒内停止")
                else:
                    self._worker = None
            else:
                self._worker = None
        if self._erp_upload_worker is not None:
            erp_worker = self._erp_upload_worker
            if erp_worker.isRunning():
                erp_worker.cancel()
                if not erp_worker.wait(30_000):
                    self._logger.error("ERP 上传线程未在 30 秒内停止")
                else:
                    self._erp_upload_worker = None
            else:
                self._erp_upload_worker = None
        if self._erp_connection_worker is not None:
            connection_worker = self._erp_connection_worker
            if connection_worker.isRunning():
                connection_worker.cancel()
                if not connection_worker.wait(30_000):
                    self._logger.error("ERP 连接测试线程未在 30 秒内停止")
                else:
                    self._erp_connection_worker = None
            else:
                self._erp_connection_worker = None
        if self._erp_task_extraction_worker is not None:
            extraction_worker = self._erp_task_extraction_worker
            if extraction_worker.isRunning():
                extraction_worker.cancel()
                if not extraction_worker.wait(30_000):
                    self._logger.error("ERP 申请解析线程未在 30 秒内停止")
                else:
                    self._erp_task_extraction_worker = None
            else:
                self._erp_task_extraction_worker = None
        self._cleanup_generated_source_workbook()

    def _refresh_plan(self) -> None:
        self._groups = (
            self._loader.plan(self._records, self._mode, self._batch_size)
            if self._records
            else []
        )
        self.planChanged.emit()

    def _create_records_source_workbook(self) -> Path:
        self._cleanup_generated_source_workbook()
        task_dir = self._settings.browser.user_data_dir.parent / "tasks"
        source = task_dir / (
            f"临时执行数据_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
        )
        self._generated_source_excel = self._template.write_records(
            source,
            self._records,
            include_print_groups=self._record_source == "erp",
        )
        return self._generated_source_excel

    def _sync_edited_records_to_erp_result(
        self,
        edited_row_number: int,
        edited_group_id: str,
    ) -> None:
        if self._erp_task_result is None:
            return
        raw_requests = self._erp_task_result.get("rights_statement_requests")
        if not isinstance(raw_requests, list):
            return
        records_by_row = {record.row_number: record for record in self._records}
        for raw_index, raw_item in enumerate(raw_requests, start=2):
            if not isinstance(raw_item, dict):
                continue
            record = records_by_row.get(raw_index)
            if record is None:
                continue
            same_group = bool(edited_group_id) and (
                record.print_group_id == edited_group_id
            )
            if same_group:
                raw_item["insurance_type"] = record.insurance_type
                raw_item["start_month"] = record.start_month
                raw_item["end_month"] = record.end_month
                raw_item["needs_review"] = False
                raw_item["review_reasons"] = []
            if raw_index != edited_row_number:
                continue
            raw_item["name"] = record.name
            raw_item["social_security_number"] = record.identity_number
            raw_item["insurance_type"] = record.insurance_type
            raw_item["start_month"] = record.start_month
            raw_item["end_month"] = record.end_month
            raw_item["needs_review"] = False
            raw_item["review_reasons"] = []
            raw_item["identity_match"] = {
                "code": ErrorCode.SUCCESS.value,
                "message": display_message(ErrorCode.SUCCESS),
                "details": "人员信息已在数据预览中人工确认",
                "source": "manual_edit",
                "company": record.unit,
                "department": record.department,
            }

    def _cleanup_generated_source_workbook(self) -> None:
        source = self._generated_source_excel
        self._generated_source_excel = None
        if source is None:
            return
        try:
            source.unlink(missing_ok=True)
        except OSError:
            self._logger.warning(
                "清理 ERP 临时源工作簿失败 path=%s",
                source,
                exc_info=True,
            )

    def _clear_import(self) -> None:
        self._cleanup_generated_source_workbook()
        self._records = []
        self._records_edited = False
        self._groups = []
        self._source_excel = None
        self._record_source = ""
        self._erp_task_result = None
        self._record_issues = []
        self.fileChanged.emit()
        self.recordsChanged.emit()
        self.planChanged.emit()

    @Slot(str)
    def _on_status(self, text: str) -> None:
        self._set_status(text)
        match = re.search(r"批次\s+(\d+)/(\d+)", text)
        if match:
            current, total = (int(value) for value in match.groups())
            self._progress_total = total
            self._progress_current = (
                current if text.startswith("正在处理") else max(0, current - 1)
            )
            self.progressChanged.emit()

    @Slot(object)
    def _on_completed(self, result: ExcelRunResult) -> None:
        self._set_running(False)
        self._set_stopping(False)
        unique_pdf_files: list[Path] = []
        seen_pdf_files: set[Path] = set()
        for item in result.items:
            if not item.success or item.file_path is None:
                continue
            path = item.file_path.expanduser().resolve()
            if path.suffix.lower() != ".pdf" or path in seen_pdf_files:
                continue
            seen_pdf_files.add(path)
            if path.is_file():
                unique_pdf_files.append(path)
        self._last_pdf_files = unique_pdf_files
        self.pdfPreviewChanged.emit()
        cancelled = sum(
            item.code == str(ErrorCode.TASK_CANCELLED) for item in result.items
        )
        if cancelled == 0:
            self._progress_current = self._progress_total
        self.progressChanged.emit()
        if cancelled:
            other_failures = result.failed - cancelled
            self._set_status(
                f"任务已停止：成功 {result.succeeded}，"
                f"未处理 {cancelled}，其他失败 {other_failures}"
            )
            title = "任务已停止"
            message = (
                f"已完成 {result.succeeded} 人，未处理 {cancelled} 人"
                + (f"，其他失败 {other_failures} 人" if other_failures else "")
            )
        else:
            self._set_status(f"执行完成：成功 {result.succeeded}，失败 {result.failed}")
            has_failure = result.failed > 0 or result.erp_failed > 0
            title = "执行完成" if not has_failure else "执行完成，部分项目失败"
            message = f"权益单成功 {result.succeeded} 人，失败 {result.failed} 人"
            if self._upload_to_erp:
                message += (
                    f"；ERP 上传成功 {result.erp_uploaded} 人，"
                    f"失败 {result.erp_failed} 人"
                )
        details = (
            f"结果 Excel：{result.result_workbook_path or '生成失败'}\n"
            f"结果清单：{result.manifest_path}"
        )
        self.executionFinished.emit(title, message, details)
        if self._preferences.open_output_folder and self._last_output_dir is not None:
            self.openFolder(str(self._last_output_dir))
        self._cleanup_generated_source_workbook()

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self._set_stopping(False)
        self._set_status("执行失败")
        self._cleanup_generated_source_workbook()
        self.notification.emit("执行失败", message)

    @Slot(str)
    def _on_manual_erp_status(self, text: str) -> None:
        self._set_erp_upload_status(text)

    @Slot(object)
    def _on_manual_erp_completed(self, result: ErpUploadResult) -> None:
        self._set_erp_uploading(False)
        self._set_erp_upload_status("ERP 上传成功")
        self.manualErpUploadFinished.emit(
            "上传成功",
            f"{result.source_file.name} 已上传至任务 {result.application.code}",
            (
                f"申请名称：{result.application.name or '未填写'}\n"
                f"附件大小：{self._format_file_size(result.attachment.size)}\n"
                f"上传分片：{result.chunks}"
            ),
        )

    @Slot(str, str)
    def _on_manual_erp_failed(self, summary: str, details: str) -> None:
        self._set_erp_uploading(False)
        self._set_erp_upload_status(summary)
        self.manualErpUploadFinished.emit(
            "上传失败",
            summary,
            details or "请核对任务编号、文件内容和 ERP 登录配置后重试。",
        )

    @Slot()
    def _on_manual_erp_worker_finished(self) -> None:
        self._erp_upload_worker = None

    @Slot(str)
    def _on_erp_connection_status(self, text: str) -> None:
        self._erp_connection_status = text.strip() or "正在测试 ERP 连接…"
        self.erpConnectionChanged.emit()

    @Slot()
    def _on_erp_connection_succeeded(self) -> None:
        self._erp_connection_success = True
        self._erp_connection_status = "ERP 连接正常"
        self.erpConnectionChanged.emit()

    @Slot(str, str)
    def _on_erp_connection_failed(self, summary: str, details: str) -> None:
        self._erp_connection_success = False
        self._erp_connection_status = summary or "ERP 连接失败"
        self.erpConnectionChanged.emit()
        self.notification.emit(
            "ERP 连接失败",
            details or summary or "请检查 ERP 账号、密码和网络连接",
        )

    @Slot()
    def _on_erp_connection_finished(self) -> None:
        self._erp_connection_worker = None
        self.erpConnectionChanged.emit()

    @Slot(str)
    def _on_erp_task_extraction_status(self, text: str) -> None:
        self._erp_task_extraction_status = text.strip() or "正在处理"
        self.erpTaskExtractionChanged.emit()

    @Slot(int, int, str)
    def _on_erp_task_extraction_progress(
        self,
        current: int,
        total: int,
        task_number: str,
    ) -> None:
        self._erp_task_extraction_current = max(0, current)
        self._erp_task_extraction_total = max(0, total)
        self._erp_task_extraction_task = task_number.strip()
        self.erpTaskExtractionChanged.emit()

    @Slot(object)
    def _on_erp_task_extraction_completed(self, result: object) -> None:
        if not isinstance(result, dict):
            self._on_erp_task_extraction_failed(
                "解析结果无效",
                "大模型解析服务未返回标准结果",
            )
            return
        self._erp_task_result = result
        request_items = result.get("rights_statement_requests")
        records: list[EmployeeRecord] = []
        if isinstance(request_items, list):
            for sequence, item in enumerate(request_items, start=2):
                if not isinstance(item, dict):
                    continue
                task_number = str(item.get("task_number") or "").strip()
                identity_match = item.get("identity_match")
                identity_match = (
                    identity_match if isinstance(identity_match, dict) else {}
                )
                records.append(
                    EmployeeRecord(
                        row_number=sequence,
                        unit=str(identity_match.get("company") or "").strip(),
                        department=str(
                            identity_match.get("department") or ""
                        ).strip(),
                        name=str(item.get("name") or "").strip(),
                        identity_number=str(
                            item.get("social_security_number") or ""
                        ).strip(),
                        insurance_type=str(
                            item.get("insurance_type") or "养老"
                        ).strip(),
                        start_month=str(item.get("start_month") or "").strip(),
                        end_month=str(item.get("end_month") or "").strip(),
                        task_number=task_number,
                        print_group_id=str(
                            item.get("group_id") or ""
                        ).strip(),
                        print_group_sequence=int(
                            item.get("group_sequence") or 0
                        ),
                        source_print_mode=str(
                            item.get("source_print_mode") or ""
                        ).strip(),
                        resolved_print_mode=str(
                            item.get("resolved_print_mode") or ""
                        ).strip(),
                    )
                )
        self._source_excel = None
        self._record_source = "erp"
        self._records = records
        self._records_edited = False
        self._record_issues = self._build_erp_record_issues(result)
        self.fileChanged.emit()
        self.recordsChanged.emit()
        self._refresh_plan()

        summary = result.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        processed = int(summary.get("tasks_processed") or 0)
        total = int(summary.get("tasks_total") or 0)
        people = int(summary.get("people_extracted") or 0)
        print_groups = int(summary.get("print_groups_extracted") or 0)
        failed = int(summary.get("tasks_failed") or 0)
        stopped = bool(summary.get("stopped"))
        self._erp_task_extraction_running = False
        self._erp_task_extraction_stopping = False
        self._erp_task_extraction_current = processed
        self._erp_task_extraction_total = total
        self._erp_task_extraction_status = (
            f"已停止：已解析 {processed}/{total} 条申请"
            if stopped
            else (
                f"解析完成：{total} 条申请，{print_groups} 个打印组，"
                f"{people} 条人员记录"
            )
        )
        self.erpTaskExtractionChanged.emit()
        title = "已安全停止" if stopped else "申请信息获取完成"
        message = (
            f"已处理 {processed}/{total} 条申请，拆分为 {print_groups} 个打印组，"
            f"包含 {people} 条人员记录"
        )
        if failed:
            message += f"，{failed} 条解析失败"
        self.erpTaskExtractionFinished.emit(title, message)

    @Slot(str, str)
    def _on_erp_task_extraction_failed(self, summary: str, details: str) -> None:
        self._erp_task_extraction_running = False
        self._erp_task_extraction_stopping = False
        self._erp_task_extraction_status = summary or "获取失败"
        self.erpTaskExtractionChanged.emit()
        self.erpTaskExtractionFinished.emit(
            "获取申请信息失败",
            details or summary or "请检查 ERP 和大模型配置",
        )

    @Slot()
    def _on_erp_task_extraction_cancelled(self) -> None:
        self._erp_task_extraction_running = False
        self._erp_task_extraction_stopping = False
        self._erp_task_extraction_status = "任务已停止"
        self.erpTaskExtractionChanged.emit()
        self.erpTaskExtractionFinished.emit(
            "任务已停止",
            "ERP 查询或登录阶段已停止，未开始模型解析。",
        )

    @Slot()
    def _on_erp_task_extraction_worker_finished(self) -> None:
        self._erp_task_extraction_worker = None

    @staticmethod
    def _build_erp_record_issues(
        result: dict[str, object],
    ) -> list[dict[str, object]]:
        issues: list[dict[str, object]] = []

        def add_issue(
            level: str,
            task_number: str,
            person_name: str,
            code: ErrorCode,
            details: str,
            row_number: int = 0,
            group_id: str = "",
        ) -> None:
            issues.append(
                {
                    "level": level,
                    "levelLabel": {
                        "error": "错误",
                        "warning": "待复核",
                        "pending": "待处理",
                        "info": "信息",
                    }.get(level, "提示"),
                    "taskNumber": task_number or "-",
                    "personName": person_name or "-",
                    "code": code.value,
                    "message": display_message(code),
                    "details": details.strip() or display_message(code),
                    "rowNumber": row_number,
                    "groupId": group_id,
                }
            )

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
                code_text = str(parse_status.get("code") or "").strip()
                if code_text and code_text != ErrorCode.SUCCESS.value:
                    try:
                        code = ErrorCode(code_text)
                    except ValueError:
                        code = ErrorCode.UNEXPECTED_ERROR
                    add_issue(
                        "error",
                        task_number,
                        "",
                        code,
                        str(
                            parse_status.get("details")
                            or parse_status.get("message")
                            or "大模型解析失败"
                        ),
                    )
                    continue
            extraction = task.get("extraction")
            if (
                isinstance(extraction, dict)
                and task_number not in tasks_with_people
            ):
                add_issue(
                    "error",
                    task_number,
                    "",
                    ErrorCode.AI_NO_PERSON_EXTRACTED,
                    "申请标题和问题描述中未识别到可处理人员",
                )

        unresolved_groups: set[str] = set()
        for row_number, item in enumerate(requests, start=2):
            if not isinstance(item, dict):
                continue
            task_number = str(item.get("task_number") or "").strip()
            person_name = str(item.get("name") or "").strip()
            group_id = str(item.get("group_id") or "").strip()
            group_sequence = int(item.get("group_sequence") or 0)
            resolved_print_mode = str(
                item.get("resolved_print_mode") or ""
            ).strip()
            group_people_count = int(item.get("group_people_count") or 0)
            if (
                group_id
                and group_people_count > 1
                and not resolved_print_mode
                and group_id not in unresolved_groups
            ):
                unresolved_groups.add(group_id)
                add_issue(
                    "warning",
                    task_number,
                    f"组{group_sequence}",
                    ErrorCode.AI_PRINT_MODE_REQUIRED,
                    "原文未说明该组多人合并打印还是每人单独打印，"
                    "请在导出设置中选择。",
                    row_number,
                    group_id,
                )
            start_month = str(item.get("start_month") or "").strip()
            end_month = str(item.get("end_month") or "").strip()
            if not start_month or not end_month:
                missing = []
                if not start_month:
                    missing.append("开始月份")
                if not end_month:
                    missing.append("结束月份")
                add_issue(
                    "error",
                    task_number,
                    person_name,
                    ErrorCode.AI_DATE_MISSING,
                    "模型未能确定" + "和".join(missing),
                    row_number,
                    group_id,
                )
            review_reasons = item.get("review_reasons")
            if isinstance(review_reasons, list) and review_reasons:
                add_issue(
                    "warning",
                    task_number,
                    person_name,
                    ErrorCode.AI_REVIEW_REQUIRED,
                    "；".join(str(reason) for reason in review_reasons if reason),
                    row_number,
                    group_id,
                )
            warnings = item.get("warnings")
            if isinstance(warnings, list) and warnings:
                add_issue(
                    "info",
                    task_number,
                    person_name,
                    ErrorCode.AI_EXTRACTION_WARNING,
                    "；".join(str(warning) for warning in warnings if warning),
                    row_number,
                    group_id,
                )
            if not str(item.get("social_security_number") or "").strip():
                identity_match = item.get("identity_match")
                if isinstance(identity_match, dict):
                    code_text = str(identity_match.get("code") or "").strip()
                    try:
                        identity_code = ErrorCode(code_text)
                    except ValueError:
                        identity_code = ErrorCode.IDENTITY_MATCH_PENDING
                    details = str(
                        identity_match.get("details")
                        or identity_match.get("message")
                        or "人员身份证号尚未匹配"
                    )
                else:
                    identity_code = ErrorCode.IDENTITY_MATCH_PENDING
                    details = "需要通过人员库按姓名匹配身份证号"
                add_issue(
                    "pending",
                    task_number,
                    person_name,
                    identity_code,
                    details,
                    row_number,
                    group_id,
                )
        return issues

    @staticmethod
    def _row_status(issues: list[dict[str, object]]) -> str:
        levels = {str(item.get("level") or "") for item in issues}
        if levels & {"error", "pending"}:
            return "error"
        if "warning" in levels:
            return "warning"
        if "info" in levels:
            return "info"
        return "success"

    @staticmethod
    def _row_issue_tooltip(issues: list[dict[str, object]]) -> str:
        if not issues:
            return "数据校验正常"
        blocks: list[str] = []
        for item in issues:
            label = str(item.get("levelLabel") or "提示")
            message = str(item.get("message") or "").strip()
            details = str(item.get("details") or "").strip()
            title = f"{label}：{message}" if message else label
            blocks.append(title + (f"\n{details}" if details else ""))
        return "\n\n".join(blocks)

    def _actionable_record_issue_count(self) -> int:
        return sum(
            item.get("level") in {"error", "warning", "pending"}
            for item in self._record_issues
        )

    def _save_preferences(self, **changes: object) -> bool:
        updated = replace(self._preferences, **changes)
        try:
            self._preferences_store.save(updated)
        except OSError as exc:
            self._logger.exception("保存用户设置失败")
            self.notification.emit("设置保存失败", str(exc))
            return False
        self._preferences = updated
        return True

    def _settings_with_preferences(self, settings: AppSettings) -> AppSettings:
        step_delays = {
            "fast": 500,
            "standard": 1000,
            "stable": 1500,
        }
        rights_statement = replace(
            settings.rights_statement,
            step_delay_ms=step_delays[self._preferences.execution_speed],
            no_result_confirm_ms=(
                self._preferences.no_result_confirm_seconds * 1000
            ),
            preview_download_delay_ms=(
                self._preferences.preview_download_delay_ms
            ),
            download_timeout_ms=(
                self._preferences.download_timeout_seconds * 1000
            ),
        )
        profile_id = (
            self._preferences.ai_model_profile or settings.ai.profile_id.value
        )
        profile = next(
            (
                item
                for item in settings.ai_models
                if item.profile_id.value == profile_id
            ),
            settings.ai,
        )
        preferred_mode = self._preferences.ai_reasoning_mode
        reasoning_mode = (
            preferred_mode
            if preferred_mode in profile.reasoning_modes
            else profile.default_reasoning_mode
        )
        selected_settings = select_ai_model(
            settings,
            profile.profile_id.value,
            reasoning_mode=reasoning_mode,
        )
        return replace(
            selected_settings,
            rights_statement=rights_statement,
            rights_credentials=replace(
                selected_settings.rights_credentials,
                credit_code=self._preferences.rights_credit_code,
                mobile=self._preferences.rights_mobile,
                password=self._rights_credential_store.load_password(
                    self._rights_account_key(
                        self._preferences.rights_credit_code,
                        self._preferences.rights_mobile,
                    )
                )
                or "",
            ),
        )

    @staticmethod
    def _rights_account_key(credit_code: str, mobile: str) -> str:
        normalized_credit = credit_code.strip()
        normalized_mobile = mobile.strip()
        if not normalized_credit or not normalized_mobile:
            return ""
        return f"{normalized_credit}|{normalized_mobile}"

    def _apply_automation_preferences(self) -> None:
        self._settings = self._settings_with_preferences(self._base_settings)
        self.preferencesChanged.emit()
        if not self._worker_enabled or self._running:
            return
        previous_worker = self._worker
        if previous_worker is not None:
            previous_worker.shutdown()
            if not previous_worker.wait(10_000):
                self._logger.error("应用自动化设置时旧工作线程未能停止")
                self.notification.emit(
                    "设置将在重启后生效",
                    "当前自动化工作线程未能及时停止，请稍后重新启动程序。",
                )
                return
        self._worker = None
        self._start_worker()

    def _set_running(self, value: bool) -> None:
        if self._running == value:
            return
        self._running = value
        self.runningChanged.emit()

    def _set_stopping(self, value: bool) -> None:
        if self._stopping == value:
            return
        self._stopping = value
        self.stoppingChanged.emit()

    def _set_status(self, value: str) -> None:
        self._status = value
        self.statusChanged.emit()

    def _set_erp_uploading(self, value: bool) -> None:
        if self._erp_uploading == value:
            return
        self._erp_uploading = value
        self.erpUploadingChanged.emit()

    def _set_erp_upload_status(self, value: str) -> None:
        if self._erp_upload_status == value:
            return
        self._erp_upload_status = value
        self.erpUploadStatusChanged.emit()

    @staticmethod
    def _url_path(url: QUrl) -> Path | None:
        local = url.toLocalFile()
        return Path(local).expanduser() if local else None

    @staticmethod
    def _format_file_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @staticmethod
    def _default_download_dir() -> Path:
        downloads = Path.home() / "Downloads"
        return downloads if downloads.exists() else Path.home()
