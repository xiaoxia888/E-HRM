import logging
import os
from pathlib import Path

import pytest
from openpyxl import Workbook


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from ehrm.core.settings import load_settings
from ehrm.gui.view_model import DesktopViewModel
from ehrm.modules.rights_statement.excel_models import (
    ExcelRunResult,
    ExportMode,
    ItemResult,
)


def _view_model(tmp_path: Path) -> DesktopViewModel:
    settings = load_settings(
        Path("config/settings.toml"),
        data_root=tmp_path / "runtime",
    )
    return DesktopViewModel(
        settings,
        logging.getLogger("test.gui"),
        start_worker=False,
    )


def test_import_failure_emits_specific_row_details(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "任务编号"])
    sheet.append(["测试单位", "信息部", "张三", "错误证件号", "医疗", "2025-01", "2025-06", "RLSQ20260819-0001"])
    path = tmp_path / "invalid.xlsx"
    workbook.save(path)

    view_model = _view_model(tmp_path)
    failures: list[tuple[str, str]] = []
    view_model.validationFailed.connect(
        lambda summary, details: failures.append((summary, details))
    )

    view_model.importExcel(QUrl.fromLocalFile(str(path)))

    assert application is not None
    assert failures
    assert failures[0][0] == "Excel 数据校验失败"
    assert "第 2 行" in failures[0][1]
    assert "身份证格式错误" in failures[0][1]
    assert not view_model.imported


def test_successful_import_updates_preview_and_uses_safe_default(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "任务编号"])
    sheet.append(["测试单位", "信息部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"])
    sheet.append(["测试单位", "人事部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"])
    path = tmp_path / "valid.xlsx"
    workbook.save(path)

    view_model = _view_model(tmp_path)
    view_model.importExcel(QUrl.fromLocalFile(str(path)))

    assert application is not None
    assert view_model.exportMode == "individual"
    assert view_model.peopleCount == 2
    assert view_model.conditionCount == 1
    assert view_model.expectedPdfCount == 2
    assert view_model.batchExpectedPdfCount == 1
    assert view_model.records[0]["identity"] == "320101199001011234"
    assert view_model.records[0]["taskNumber"] == "RLSQ20260819-0001"


def test_erp_extraction_result_is_previewed_with_default_pension_insurance(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 1,
                "stopped": False,
            },
            "tasks": [
                {
                    "task_number": "RLSQ20260820-0001",
                    "department": "技术中心",
                }
            ],
            "rights_statement_requests": [
                {
                    "task_number": "RLSQ20260820-0001",
                    "name": "张三",
                    "social_security_number": None,
                    "start_month": "2025-08",
                    "end_month": "2026-07",
                }
            ],
        }
    )

    assert application is not None
    assert view_model.hasRecords
    assert not view_model.imported
    assert view_model.fileSummary == "ERP 申请解析结果 · 1 人"
    assert view_model.recordIssueCount == 1
    assert view_model.recordIssues[0]["code"] == "IDENTITY_MATCH_PENDING"
    assert view_model.records[0] == {
        "status": "通过",
        "rowNumber": 2,
        "rowStatus": "error",
        "rowStatusLabel": "错误",
        "rowIssueCount": 1,
        "rowIssueTooltip": (
            "待处理：人员身份证号尚未匹配\n"
            "需要通过人员库按姓名匹配身份证号"
        ),
        "unit": "-",
        "department": "-",
        "name": "张三",
        "identity": "待匹配",
        "insurance": "养老",
        "startMonth": "2025-08",
        "endMonth": "2026-07",
        "taskNumber": "RLSQ20260820-0001",
    }


def test_erp_preview_exposes_missing_dates_as_a_chinese_issue(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 1,
                "stopped": False,
            },
            "tasks": [
                {
                    "task_number": "RLSQ20260820-0002",
                    "department": "项目管理公司",
                    "parse_status": {"code": "SUCCESS", "message": "处理成功"},
                    "extraction": {"people": [{"name": "施瀛博"}]},
                }
            ],
            "rights_statement_requests": [
                {
                    "task_number": "RLSQ20260820-0002",
                    "name": "施瀛博",
                    "social_security_number": None,
                    "start_month": None,
                    "end_month": None,
                    "needs_review": True,
                    "review_reasons": ["原文月份表达不明确"],
                    "warnings": [],
                }
            ],
        }
    )

    assert application is not None
    assert view_model.records[0]["startMonth"] == "待确认"
    assert view_model.records[0]["endMonth"] == "待确认"
    codes = [item["code"] for item in view_model.recordIssues]
    assert codes == [
        "AI_DATE_MISSING",
        "AI_REVIEW_REQUIRED",
        "IDENTITY_MATCH_PENDING",
    ]
    assert view_model.recordIssues[0]["personName"] == "施瀛博"
    assert "3 项待处理" in view_model.recordStatusLabel
    assert view_model.records[0]["rowStatus"] == "error"
    assert view_model.records[0]["rowIssueCount"] == 3


def test_model_warning_is_information_not_an_actionable_issue(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 1,
                "stopped": False,
            },
            "tasks": [{"task_number": "RLSQ-003", "department": "技术中心"}],
            "rights_statement_requests": [
                {
                    "task_number": "RLSQ-003",
                    "name": "张三",
                    "social_security_number": "320101199001011234",
                    "identity_match": {
                        "code": "SUCCESS",
                        "company": "测试建设有限公司",
                        "department": "第一工程部",
                    },
                    "start_month": "2026-08",
                    "end_month": "2026-08",
                    "needs_review": False,
                    "review_reasons": [],
                    "warnings": ["非阻断性提示"],
                }
            ],
        }
    )

    assert application is not None
    assert view_model.recordIssueCount == 0
    assert view_model.recordDetailCount == 1
    assert view_model.recordIssues[0]["level"] == "info"
    assert view_model.recordIssues[0]["levelLabel"] == "信息"
    assert view_model.records[0]["unit"] == "测试建设有限公司"
    assert view_model.records[0]["department"] == "第一工程部"
    assert view_model.records[0]["rowStatus"] == "info"
    assert "非阻断性提示" in view_model.records[0]["rowIssueTooltip"]
    confirmations: list[bool] = []
    view_model.confirmationReady.connect(lambda: confirmations.append(True))

    view_model.prepareExecution()

    assert confirmations == [True]


def test_model_review_marks_only_the_related_row_yellow(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 1,
                "stopped": False,
            },
            "tasks": [{"task_number": "RLSQ-REVIEW"}],
            "rights_statement_requests": [
                {
                    "task_number": "RLSQ-REVIEW",
                    "name": "李四",
                    "social_security_number": "320101199002021235",
                    "identity_match": {
                        "code": "SUCCESS",
                        "company": "测试公司",
                        "department": "项目部",
                    },
                    "start_month": "2025-07",
                    "end_month": "2026-07",
                    "needs_review": True,
                    "review_reasons": ["原文时间表达存在两种可能解释"],
                    "warnings": [],
                }
            ],
        }
    )

    assert application is not None
    assert view_model.records[0]["rowStatus"] == "warning"
    assert view_model.records[0]["rowStatusLabel"] == "待复核"
    assert view_model.records[0]["rowIssueCount"] == 1
    assert "原文时间表达存在两种可能解释" in (
        view_model.records[0]["rowIssueTooltip"]
    )


def test_template_save_dialog_has_a_default_filename(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    assert application is not None
    assert view_model.templateDefaultUrl.fileName() == "单位权益单导入模板.xlsx"


def test_manual_erp_file_selection_validates_before_opening_confirmation(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    pdf = tmp_path / "单位权益单.pdf"
    pdf.write_bytes(b"%PDF-1.7\ncontent\n%%EOF")
    ready: list[bool] = []
    view_model.erpFileReady.connect(lambda: ready.append(True))

    view_model.selectErpUploadFile(QUrl.fromLocalFile(str(pdf)))

    assert application is not None
    assert view_model.erpFileSelected
    assert view_model.erpFileName == "单位权益单.pdf"
    assert view_model.erpFileDetails.startswith("PDF · ")
    assert view_model.erpUploadStatus == "文件校验通过，请填写任务编号"
    assert ready == [True]


def test_qml_main_window_loads_with_explicit_backend(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appBackend", view_model)
    engine.setInitialProperties({"backend": view_model})
    qml_file = Path("src/ehrm/gui/qml/Main.qml").resolve()

    engine.load(QUrl.fromLocalFile(str(qml_file)))
    application.processEvents()

    assert len(engine.rootObjects()) == 1
    window = engine.rootObjects()[0]
    assert window.title() == "信息化人力工作台"
    assert window.property("backend") is view_model
    query_dialog = window.findChild(QObject, "erpTaskQueryDialog")
    assert query_dialog is not None
    query_dialog.open()
    application.processEvents()
    assert query_dialog.property("opened")
    query_dialog.close()
    window.close()
    application.processEvents()


def test_cancelled_result_is_presented_separately_from_failures(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    messages: list[tuple[str, str, str]] = []
    view_model.executionFinished.connect(
        lambda title, message, details: messages.append((title, message, details))
    )
    view_model._set_running(True)
    result = ExcelRunResult(
        mode=ExportMode.INDIVIDUAL,
        total=2,
        succeeded=1,
        failed=1,
        manifest_path=tmp_path / "result.json",
        result_workbook_path=tmp_path / "result.xlsx",
        items=(
            ItemResult(2, True, "SUCCESS", "处理成功"),
            ItemResult(3, False, "TASK_CANCELLED", "用户提前停止任务"),
        ),
    )

    view_model._on_completed(result)

    assert application is not None
    assert not view_model.running
    assert view_model.statusText == "任务已停止：成功 1，未处理 1，其他失败 0"
    assert messages[0][0] == "任务已停止"
    assert messages[0][1] == "已完成 1 人，未处理 1 人"


def test_settings_are_persisted_and_applied_to_automation(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    output = tmp_path / "downloads"
    output.mkdir()
    view_model = _view_model(tmp_path)

    view_model.setOutputFolder(QUrl.fromLocalFile(str(output)))
    view_model.setExportMode("batch")
    view_model.setBatchSize(30)
    view_model.setUploadToErp(True)
    view_model.setOpenOutputFolderAfterRun(True)
    view_model.setExecutionSpeed("stable")
    view_model.setNoResultConfirmSeconds(15)
    view_model.setPreviewDownloadDelayMs(2000)
    view_model.setDownloadTimeoutSeconds(60)

    assert application is not None
    assert view_model.outputPath == str(output)
    assert view_model.exportMode == "batch"
    assert view_model.batchSize == 30
    assert view_model.uploadToErp
    assert view_model.openOutputFolderAfterRun
    assert view_model.executionSpeed == "stable"
    assert view_model._settings.rights_statement.step_delay_ms == 1500
    assert view_model._settings.rights_statement.no_result_confirm_ms == 15_000
    assert view_model._settings.rights_statement.preview_download_delay_ms == 2000
    assert view_model._settings.rights_statement.download_timeout_ms == 60_000

    restored = _view_model(tmp_path)
    assert restored.outputPath == str(output)
    assert restored.exportMode == "batch"
    assert restored.batchSize == 30
    assert restored.uploadToErp


def test_ai_model_and_supported_reasoning_mode_are_persisted(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    assert view_model.aiModelProfile == "qwen3_8_27b"
    assert view_model.aiModelRuntimeLabel == (
        "Qwen3.8-27B（qwen3.8:27b）· 非思考"
    )
    assert [item["value"] for item in view_model.aiModelOptions] == [
        "qwen3_5_9b",
        "qwen3_8_27b",
    ]
    assert [item["value"] for item in view_model.aiReasoningOptions] == [
        "off",
        "low",
        "medium",
        "max",
    ]

    view_model.setAiModelProfile("qwen3_5_9b")
    view_model.setAiReasoningMode("on")

    assert application is not None
    assert view_model.aiModelProfile == "qwen3_5_9b"
    assert view_model.aiReasoningMode == "on"
    assert view_model.aiModelRuntimeLabel == "Qwen3.5-9B（qwen3.5:9b）· 思考"
    assert [item["value"] for item in view_model.aiReasoningOptions] == [
        "off",
        "on",
    ]

    restored = _view_model(tmp_path)
    assert restored.aiModelProfile == "qwen3_5_9b"
    assert restored.aiReasoningMode == "on"
    assert restored._settings.ai.model == "qwen3.5:9b"


def test_erp_password_is_delegated_to_system_credential_store(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    class FakeCredentialStore:
        saved: tuple[str, str] | None = None

        def load_password(self, username: str) -> str | None:
            if self.saved is not None and self.saved[0] == username:
                return self.saved[1]
            return None

        def save_password(self, username: str, password: str) -> None:
            self.saved = (username, password)

        def delete_password(self, username: str) -> None:
            pass

    store = FakeCredentialStore()
    view_model._credential_store = store

    view_model.saveErpAccount("erp-user", "secret-value")

    assert application is not None
    assert store.saved == ("erp-user", "secret-value")
    preferences_path = (
        view_model._settings.browser.user_data_dir.parent / "preferences.json"
    )
    assert "secret-value" not in preferences_path.read_text(encoding="utf-8")
    assert view_model.erpUsername == "erp-user"
    assert view_model.erpPasswordStored
    assert view_model.loadSavedErpPassword("erp-user") == "secret-value"
    assert view_model.loadSavedErpPassword("another-user") == ""
