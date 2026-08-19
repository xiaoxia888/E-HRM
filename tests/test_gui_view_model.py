import logging
import os
from pathlib import Path

import pytest
from openpyxl import Workbook


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl
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
        Path("config/settings.example.toml"),
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
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间"])
    sheet.append(["测试单位", "信息部", "张三", "错误证件号", "医疗", "2025-01", "2025-06"])
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
    sheet.append(["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间"])
    sheet.append(["测试单位", "信息部", "张三", "320101199001011234", "养老", "2025-01", "2025-06"])
    sheet.append(["测试单位", "人事部", "李四", "320101199002021235", "养老", "2025-01", "2025-06"])
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
    assert view_model.records[0]["identity"] == "320101********1234"


def test_qml_main_window_loads_with_explicit_backend(tmp_path: Path) -> None:
    application = QGuiApplication.instance() or QGuiApplication([])
    view_model = _view_model(tmp_path)
    engine = QQmlApplicationEngine()
    engine.setInitialProperties({"backend": view_model})
    qml_file = Path("src/ehrm/gui/qml/Main.qml").resolve()

    engine.load(QUrl.fromLocalFile(str(qml_file)))
    application.processEvents()

    assert len(engine.rootObjects()) == 1
    window = engine.rootObjects()[0]
    assert window.title() == "信息化人力工作台"
    assert window.property("backend") is view_model
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
