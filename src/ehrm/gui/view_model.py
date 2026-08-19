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

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.preferences import UserPreferences, UserPreferencesStore
from ehrm.core.settings import AppSettings
from ehrm.gui.erp_connection_worker import ErpConnectionWorker
from ehrm.gui.erp_upload_worker import ManualErpUploadWorker
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.gui.worker import AutomationWorker
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.erp.file_validation import (
    ErpUploadFileValidator,
    ValidatedUploadFile,
)
from ehrm.modules.erp.credential_store import ErpCredentialStore
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
    erpConnectionChanged = Signal()

    validationFailed = Signal(str, str)
    notification = Signal(str, str)
    confirmationReady = Signal()
    executionFinished = Signal(str, str, str)
    erpFileReady = Signal()
    manualErpUploadFinished = Signal(str, str, str)

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
        self._base_settings = settings
        self._settings = self._settings_with_preferences(settings)
        self._logger = logger
        self._loader = RightsStatementExcelLoader()
        self._template = RightsStatementTemplateService()
        self._records: list[EmployeeRecord] = []
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
        self._worker: AutomationWorker | None = None
        self._erp_upload_file: ValidatedUploadFile | None = None
        self._erp_uploading = False
        self._erp_upload_status = "请选择需要上传的文件"
        self._erp_upload_worker: ManualErpUploadWorker | None = None
        self._erp_connection_worker: ErpConnectionWorker | None = None
        self._erp_connection_status = "尚未测试连接"
        self._erp_connection_success = False
        self._erp_password_stored = bool(
            self._credential_store.load_password(self._preferences.erp_username)
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
    def records(self) -> list[dict[str, str]]:
        return [
            {
                "status": "通过",
                "unit": record.unit,
                "department": record.department,
                "name": record.name,
                "identity": self._mask_identity(record.identity_number),
                "insurance": record.insurance_type,
                "startMonth": record.start_month,
                "endMonth": record.end_month,
                "taskNumber": record.task_number,
            }
            for record in self._records
        ]

    @Property(int, notify=planChanged)
    def peopleCount(self) -> int:
        return len(self._records)

    @Property(int, notify=planChanged)
    def conditionCount(self) -> int:
        return len({record.group_key for record in self._records})

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
        if self._source_excel is None:
            return "尚未导入 Excel"
        return f"{self._source_excel.name} · {len(self._records)} 人"

    @Property(bool, notify=fileChanged)
    def imported(self) -> bool:
        return self._source_excel is not None and bool(self._records)

    @Property(str, notify=modeChanged)
    def exportMode(self) -> str:
        return self._mode.value

    @Property(int, notify=batchSizeChanged)
    def batchSize(self) -> int:
        return self._batch_size

    @Property(str, notify=outputPathChanged)
    def outputPath(self) -> str:
        return str(self._output_path)

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
        return "0.1.0"

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
        self._records = records
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
        if not self.imported or self._source_excel is None or not self._groups:
            self.notification.emit("尚未导入", "请先导入并通过校验的 Excel 文件")
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
            or self._source_excel is None
            or not self._groups
            or self._running
        ):
            return
        request = ExcelTaskRequest(
            groups=tuple(self._groups),
            mode=self._mode,
            output_dir=self._pending_output_dir,
            source_excel=self._source_excel,
            upload_to_erp=self._upload_to_erp,
        )
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

    def _refresh_plan(self) -> None:
        self._groups = (
            self._loader.plan(self._records, self._mode, self._batch_size)
            if self._records
            else []
        )
        self.planChanged.emit()

    def _clear_import(self) -> None:
        self._records = []
        self._groups = []
        self._source_excel = None
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

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self._set_stopping(False)
        self._set_status("执行失败")
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
        return replace(settings, rights_statement=rights_statement)

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
    def _mask_identity(identity: str) -> str:
        if len(identity) <= 10:
            return identity
        return identity[:6] + "*" * (len(identity) - 10) + identity[-4:]

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
