from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ehrm.core.error_catalog import ErrorCode, display_message
from ehrm.core.exceptions import EhrmError
from ehrm.core.settings import AppSettings
from ehrm.gui.template_service import RightsStatementTemplateService
from ehrm.gui.worker import AutomationWorker
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
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
    runningChanged = Signal()
    stoppingChanged = Signal()
    statusChanged = Signal()
    progressChanged = Signal()
    confirmationChanged = Signal()

    validationFailed = Signal(str, str)
    notification = Signal(str, str)
    confirmationReady = Signal()
    executionFinished = Signal(str, str, str)

    def __init__(
        self,
        settings: AppSettings,
        logger: logging.Logger,
        *,
        start_worker: bool = True,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._logger = logger
        self._loader = RightsStatementExcelLoader()
        self._template = RightsStatementTemplateService()
        self._records: list[EmployeeRecord] = []
        self._groups: list[WorkGroup] = []
        self._source_excel: Path | None = None
        # Individual export is the safer default: importing a file must not
        # silently merge employees unless the operator chooses batch mode.
        self._mode = ExportMode.INDIVIDUAL
        self._batch_size = 50
        self._output_path = self._default_download_dir()
        self._running = False
        self._stopping = False
        self._status = "准备就绪"
        self._progress_current = 0
        self._progress_total = 1
        self._pending_output_dir: Path | None = None
        self._last_output_dir: Path | None = None
        self._worker: AutomationWorker | None = None
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

    @Property(QUrl, constant=True)
    def downloadsFolderUrl(self) -> QUrl:
        return QUrl.fromLocalFile(str(self._default_download_dir()))

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
            return "批量模式仅合并单位、险种及起止年月完全相同的人员。"
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
        for (unit, insurance, start, end), count in counts.items():
            pdf_count = (
                count
                if self._mode is ExportMode.INDIVIDUAL
                else (count + self._batch_size - 1) // self._batch_size
            )
            summaries.append(
                {
                    "unit": unit,
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
        self.modeChanged.emit()
        self._refresh_plan()

    @Slot(int)
    def setBatchSize(self, value: int) -> None:
        normalized = max(1, min(100, value))
        if normalized == self._batch_size:
            return
        self._batch_size = normalized
        self.batchSizeChanged.emit()
        self._refresh_plan()

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
        self.outputPathChanged.emit()

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

    @Slot(result=bool)
    def shutdown(self) -> bool:
        if self._worker is None:
            return True
        worker = self._worker
        if not worker.isRunning():
            self._worker = None
            return True
        worker.shutdown()
        if worker.wait(30_000):
            self._worker = None
            return True
        else:
            self._logger.error("自动化工作线程未在 30 秒内停止")
            return False

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
            title = "执行完成" if result.failed == 0 else "执行完成，部分人员失败"
            message = f"成功 {result.succeeded} 人，失败 {result.failed} 人"
        details = (
            f"结果 Excel：{result.result_workbook_path or '生成失败'}\n"
            f"结果清单：{result.manifest_path}"
        )
        self.executionFinished.emit(title, message, details)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self._set_stopping(False)
        self._set_status("执行失败")
        self.notification.emit("执行失败", message)

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
    def _default_download_dir() -> Path:
        downloads = Path.home() / "Downloads"
        return downloads if downloads.exists() else Path.home()
