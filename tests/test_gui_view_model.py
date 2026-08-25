import logging
import os
from dataclasses import replace
from pathlib import Path

import pytest
from openpyxl import Workbook


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QPainter, QPdfWriter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

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
    assert view_model.fileSummary == "ERP 申请解析结果 · 1 条人员记录"
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
        "printGroup": "-",
        "printGroupId": "",
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


def test_erp_print_groups_are_previewed_and_unresolved_mode_can_be_selected(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)

    def request(
        *,
        name: str,
        identity: str,
        group_id: str,
        group_sequence: int,
        people_count: int,
        source_mode: str | None,
        resolved_mode: str | None,
    ) -> dict[str, object]:
        return {
            "task_number": "RLSQ-GROUPS",
            "group_id": group_id,
            "group_sequence": group_sequence,
            "group_people_count": people_count,
            "source_print_mode": source_mode,
            "resolved_print_mode": resolved_mode,
            "name": name,
            "social_security_number": identity,
            "identity_match": {
                "code": "SUCCESS",
                "company": "测试单位",
                "department": "项目部",
            },
            "insurance_type": "养老",
            "start_month": "2025-08",
            "end_month": "2026-07",
            "needs_review": False,
            "review_reasons": [],
            "warnings": [],
        }

    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 3,
                "stopped": False,
            },
            "tasks": [{"task_number": "RLSQ-GROUPS"}],
            "rights_statement_requests": [
                request(
                    name="张三",
                    identity="320101199001011234",
                    group_id="RLSQ-GROUPS-G01",
                    group_sequence=1,
                    people_count=1,
                    source_mode="combined",
                    resolved_mode="combined",
                ),
                request(
                    name="张三",
                    identity="320101199001011234",
                    group_id="RLSQ-GROUPS-G02",
                    group_sequence=2,
                    people_count=2,
                    source_mode=None,
                    resolved_mode=None,
                ),
                request(
                    name="李四",
                    identity="320101199002021235",
                    group_id="RLSQ-GROUPS-G02",
                    group_sequence=2,
                    people_count=2,
                    source_mode=None,
                    resolved_mode=None,
                ),
            ],
        }
    )

    assert application is not None
    assert view_model.erpRecordSource
    assert view_model.peopleCount == 3
    assert view_model.uniquePeopleCount == 2
    assert view_model.conditionCount == 2
    assert view_model.expectedPdfCount == 1
    assert view_model.recordIssueCount == 1
    assert view_model.recordIssues[0]["code"] == "AI_PRINT_MODE_REQUIRED"
    assert [item["label"] for item in view_model.printGroups] == ["组1", "组2"]
    assert [item["taskNumber"] for item in view_model.printGroups] == [
        "RLSQ-GROUPS",
        "RLSQ-GROUPS",
    ]
    assert view_model.printGroups[1]["modeRequired"]

    view_model.setPrintGroupMode("RLSQ-GROUPS-G02", "combined")

    assert view_model.recordIssueCount == 0
    assert view_model.expectedPdfCount == 2
    assert view_model.printGroups[1]["resolvedMode"] == "combined"
    assert not view_model.printGroups[1]["modeRequired"]


def test_preview_edit_updates_person_and_synchronizes_group_conditions(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    requests = []
    for name, identity in (
        ("张三", "320101199001011234"),
        ("李四", "320101199002021235"),
    ):
        requests.append(
            {
                "task_number": "RLSQ-EDIT",
                "group_id": "RLSQ-EDIT-G01",
                "group_sequence": 1,
                "group_people_count": 2,
                "source_print_mode": "combined",
                "resolved_print_mode": "combined",
                "name": name,
                "social_security_number": identity,
                "identity_match": {
                    "code": "SUCCESS",
                    "company": "原单位",
                    "department": "原部门",
                },
                "insurance_type": "养老",
                "start_month": "2025-08",
                "end_month": "2026-07",
                "needs_review": False,
                "review_reasons": [],
                "warnings": [],
            }
        )
    view_model._on_erp_task_extraction_completed(
        {
            "summary": {
                "tasks_total": 1,
                "tasks_processed": 1,
                "tasks_failed": 0,
                "people_extracted": 2,
                "print_groups_extracted": 1,
                "stopped": False,
            },
            "tasks": [{"task_number": "RLSQ-EDIT"}],
            "rights_statement_requests": requests,
        }
    )

    saved = view_model.updateRecord(
        2,
        "新单位",
        "新部门",
        "张三改",
        "320101199001011234",
        "工伤",
        "2026-01",
        "2026-08",
    )

    assert application is not None
    assert saved
    assert view_model.records[0]["unit"] == "新单位"
    assert view_model.records[0]["department"] == "新部门"
    assert view_model.records[0]["name"] == "张三改"
    assert view_model.records[0]["insurance"] == "工伤"
    assert view_model.records[1]["unit"] == "原单位"
    assert view_model.records[1]["insurance"] == "工伤"
    assert view_model.records[1]["startMonth"] == "2026-01"
    assert view_model.records[1]["endMonth"] == "2026-08"
    assert view_model.recordIssueCount == 0
    assert requests[0]["identity_match"]["source"] == "manual_edit"
    assert requests[1]["insurance_type"] == "工伤"


def test_preview_edit_rejects_invalid_identity_and_execution_revalidates(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "任务编号"])
    sheet.append(["单位", "部门", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ-001"])
    path = tmp_path / "edit.xlsx"
    workbook.save(path)
    view_model.importExcel(QUrl.fromLocalFile(str(path)))
    failures: list[tuple[str, str]] = []
    view_model.validationFailed.connect(
        lambda summary, details: failures.append((summary, details))
    )

    saved = view_model.updateRecord(
        2,
        "单位",
        "部门",
        "张三",
        "错误身份证",
        "养老",
        "2025-01",
        "2025-06",
    )

    assert application is not None
    assert not saved
    assert failures[-1][0] == "修改内容校验失败"
    assert "身份证格式错误" in failures[-1][1]

    view_model._records = [
        replace(view_model._records[0], start_month="错误月份")
    ]
    view_model.prepareExecution()

    assert failures[-1][0] == "数据校验失败"
    assert "开始时间格式错误" in failures[-1][1]


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
    record_edit_dialog = window.findChild(QObject, "recordEditDialog")
    assert record_edit_dialog is not None
    assert not window.property("navigationCollapsed")
    window.setProperty("navigationCollapsed", True)
    assert window.property("navigationCollapsed")
    window.close()
    application.processEvents()


def test_double_clicking_preview_row_opens_record_editor(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "任务编号"])
    sheet.append(["测试单位", "项目部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ-001"])
    source = tmp_path / "double-click.xlsx"
    workbook.save(source)
    view_model = _view_model(tmp_path)
    view_model.importExcel(QUrl.fromLocalFile(str(source)))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appBackend", view_model)
    engine.setInitialProperties({"backend": view_model})
    engine.load(QUrl.fromLocalFile(str(Path("src/ehrm/gui/qml/Main.qml").resolve())))
    window = engine.rootObjects()[0]
    window.show()
    QTest.qWait(120)
    application.processEvents()

    def find_visual_item(item: QQuickItem, name: str) -> QQuickItem | None:
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find_visual_item(child, name)
            if found is not None:
                return found
        return None

    preview_cell = find_visual_item(window.contentItem(), "previewCell_0_0")
    assert preview_cell is not None
    scene_point = preview_cell.mapToScene(
        QPointF(preview_cell.width() / 2, preview_cell.height() / 2)
    ).toPoint()

    QTest.mouseDClick(window, Qt.LeftButton, Qt.NoModifier, scene_point, 20)
    application.processEvents()

    editor = window.findChild(QObject, "recordEditDialog")
    assert editor is not None
    assert editor.property("opened")
    editor.close()
    window.close()
    application.processEvents()


def test_pdf_preview_dialog_loads_and_changes_pages(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    pdf_path = tmp_path / "two-pages.pdf"
    writer = QPdfWriter(str(pdf_path))
    painter = QPainter(writer)
    painter.drawText(120, 160, "Page 1")
    writer.newPage()
    painter.drawText(120, 160, "Page 2")
    painter.end()

    view_model = _view_model(tmp_path)
    view_model._on_completed(
        ExcelRunResult(
            mode=ExportMode.BATCH,
            total=1,
            succeeded=1,
            failed=0,
            manifest_path=tmp_path / "result.json",
            result_workbook_path=tmp_path / "result.xlsx",
            items=(
                ItemResult(2, True, "SUCCESS", "处理成功", pdf_path),
            ),
        )
    )
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appBackend", view_model)
    engine.setInitialProperties({"backend": view_model})
    engine.load(QUrl.fromLocalFile(str(Path("src/ehrm/gui/qml/Main.qml").resolve())))
    window = engine.rootObjects()[0]
    window.show()
    dialog = window.findChild(QObject, "pdfPreviewDialog")
    assert dialog is not None

    assert QMetaObject.invokeMethod(dialog, "openPreview")
    for _ in range(60):
        QTest.qWait(20)
        application.processEvents()
        if dialog.property("totalPages") == 2:
            break

    assert dialog.property("opened")
    assert dialog.property("totalPages") == 2
    assert dialog.property("currentPageNumber") == 1
    assert QMetaObject.invokeMethod(dialog, "fitPage")
    QTest.qWait(100)
    application.processEvents()

    def find_visual_item(item: QQuickItem, name: str) -> QQuickItem | None:
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = find_visual_item(child, name)
            if found is not None:
                return found
        return None

    preview_viewport = find_visual_item(window.contentItem(), "pdfPreviewViewport")
    pdf_view = find_visual_item(window.contentItem(), "previewPdfView")
    assert preview_viewport is not None
    assert pdf_view is not None
    assert preview_viewport.property("clip")
    assert pdf_view.property("clip")
    assert pdf_view.property("leftMargin") > 0
    assert pdf_view.property("contentX") == pytest.approx(
        -pdf_view.property("leftMargin"),
        abs=2,
    )

    original_zoom = dialog.property("zoomPercent")
    scene_point = pdf_view.mapToScene(
        QPointF(pdf_view.width() / 2, pdf_view.height() / 2)
    )
    QTest.wheelEvent(
        window,
        scene_point,
        QPointF(0, 120).toPoint(),
        stateKey=Qt.ControlModifier,
    )
    QTest.qWait(100)
    application.processEvents()
    enlarged_zoom = dialog.property("zoomPercent")
    assert enlarged_zoom > original_zoom

    QTest.wheelEvent(
        window,
        scene_point,
        QPointF(0, 0).toPoint(),
        pixelDelta=QPointF(0, -60).toPoint(),
        stateKey=Qt.ControlModifier,
    )
    QTest.qWait(100)
    application.processEvents()
    assert dialog.property("zoomPercent") < enlarged_zoom

    assert QMetaObject.invokeMethod(dialog, "nextPage")
    QTest.qWait(80)
    application.processEvents()

    assert dialog.property("currentPageNumber") == 2
    dialog.close()
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


def test_completed_result_exposes_unique_existing_pdf_files(
    tmp_path: Path,
) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    pdf_path = tmp_path / "批量权益单.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    missing_path = tmp_path / "已删除.pdf"
    notifications: list[tuple[str, str]] = []
    view_model.notification.connect(
        lambda title, message: notifications.append((title, message))
    )
    result = ExcelRunResult(
        mode=ExportMode.BATCH,
        total=3,
        succeeded=2,
        failed=1,
        manifest_path=tmp_path / "result.json",
        result_workbook_path=tmp_path / "result.xlsx",
        items=(
            ItemResult(2, True, "SUCCESS", "处理成功", pdf_path),
            ItemResult(3, True, "SUCCESS", "处理成功", pdf_path),
            ItemResult(4, False, "FILE_VALIDATION_ERROR", "失败", missing_path),
        ),
    )

    view_model._on_completed(result)

    assert application is not None
    assert view_model.hasPreviewablePdfs
    assert view_model.lastPdfCount == 1
    assert view_model.lastPdfFiles[0]["name"] == "批量权益单.pdf"
    assert view_model.lastPdfFiles[0]["path"] == str(pdf_path.resolve())
    assert view_model.preparePdfPreview()

    pdf_path.unlink()

    assert not view_model.preparePdfPreview()
    assert not view_model.hasPreviewablePdfs
    assert notifications[-1][0] == "无法预览 PDF"


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

    assert view_model.aiModelProfile == "qwen3_5_9b"
    assert view_model.aiModelRuntimeLabel == (
        "Qwen3.5-9B（qwen3.5:9b）· 非思考"
    )
    assert [item["value"] for item in view_model.aiModelOptions] == [
        "qwen3_5_9b",
        "qwen3_8_27b",
    ]
    assert [item["value"] for item in view_model.aiReasoningOptions] == [
        "off",
        "on",
    ]

    view_model.setAiModelProfile("qwen3_8_27b")
    view_model.setAiReasoningMode("medium")

    assert application is not None
    assert view_model.aiModelProfile == "qwen3_8_27b"
    assert view_model.aiReasoningMode == "medium"
    assert view_model.aiModelRuntimeLabel == (
        "Qwen3.8-27B（qwen3.8:27b）· 中等强度"
    )
    assert [item["value"] for item in view_model.aiReasoningOptions] == [
        "off",
        "low",
        "medium",
        "max",
    ]

    restored = _view_model(tmp_path)
    assert restored.aiModelProfile == "qwen3_8_27b"
    assert restored.aiReasoningMode == "medium"
    assert restored._settings.ai.model == "qwen3.8:27b"


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


def test_rights_password_is_delegated_to_system_credential_store(
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
            self.saved = None

    store = FakeCredentialStore()
    view_model._rights_credential_store = store

    view_model.saveRightsAccount(
        "91320000TEST000001",
        "13800000000",
        "rights-secret",
    )

    assert application is not None
    assert store.saved == (
        "91320000TEST000001|13800000000",
        "rights-secret",
    )
    preferences_path = (
        view_model._settings.browser.user_data_dir.parent / "preferences.json"
    )
    assert "rights-secret" not in preferences_path.read_text(encoding="utf-8")
    assert view_model.rightsCreditCode == "91320000TEST000001"
    assert view_model.rightsMobile == "13800000000"
    assert view_model.rightsPasswordStored
    assert view_model.loadSavedRightsPassword(
        "91320000TEST000001", "13800000000"
    ) == "rights-secret"
