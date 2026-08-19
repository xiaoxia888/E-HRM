from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from ehrm.core.exceptions import ExcelValidationError
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_models import ExportMode


HEADERS = ["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间"]


def write_book(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def test_loads_and_normalizes_rows(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", "320101199001011234", "养老", datetime(2025, 1, 1), "2025/06"]],
    )
    records = RightsStatementExcelLoader().load(path)
    assert records[0].start_month == "2025-01"
    assert records[0].end_month == "2025-06"


def test_rejects_float_identity(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", 3.2010119900101123e17, "养老", "2025-01", "2025-06"]],
    )
    with pytest.raises(ExcelValidationError):
        RightsStatementExcelLoader().load(path)


def test_rejects_blank_identity(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", "", "养老", "2025-01", "2025-06"]],
    )
    with pytest.raises(ExcelValidationError):
        RightsStatementExcelLoader().load(path)


def test_batch_groups_by_query_conditions(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [
            ["测试单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06"],
            ["测试单位", "乙部", "李四", "320101199002021235", "养老", "2025-01", "2025-06"],
            ["测试单位", "乙部", "王五", "320101199003031236", "工伤", "2025-01", "2025-06"],
        ],
    )
    loader = RightsStatementExcelLoader()
    records = loader.load(path)
    groups = loader.plan(records, ExportMode.BATCH, batch_size=50)
    assert len(groups) == 2
    assert sorted(len(group.records) for group in groups) == [1, 2]


def test_rejects_unsupported_insurance_type(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", "320101199001011234", "医疗", "2025-01", "2025-06"]],
    )
    with pytest.raises(ExcelValidationError) as captured:
        RightsStatementExcelLoader().load(path)
    assert "险种只能选择养老、工伤或失业" in (captured.value.details or "")
