from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from ehrm.core.exceptions import ExcelValidationError
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_models import EmployeeRecord, ExportMode


HEADERS = ["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "任务编号"]


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
        [["测试单位", "测试部门", "张三", "320101199001011234", "养老", datetime(2025, 1, 1), "2025/06", "RLSQ20260819-0001"]],
    )
    records = RightsStatementExcelLoader().load(path)
    assert records[0].start_month == "2025-01"
    assert records[0].end_month == "2025-06"


def test_rejects_float_identity(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", 3.2010119900101123e17, "养老", "2025-01", "2025-06", "RLSQ20260819-0001"]],
    )
    with pytest.raises(ExcelValidationError):
        RightsStatementExcelLoader().load(path)


def test_rejects_blank_identity(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [["测试单位", "测试部门", "张三", "", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"]],
    )
    with pytest.raises(ExcelValidationError):
        RightsStatementExcelLoader().load(path)


def test_load_reports_every_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "all-errors.xlsx"
    write_book(
        path,
        [
            [
                "测试单位",
                "测试部门",
                f"人员{index}",
                "320101199001011234",
                "养老",
                "2025-01",
                "2025-06",
                "",
            ]
            for index in range(1, 26)
        ],
    )

    with pytest.raises(ExcelValidationError) as captured:
        RightsStatementExcelLoader().load(path)

    details = captured.value.details or ""
    assert "第 2 行：任务编号不能为空" in details
    assert "第 26 行：任务编号不能为空" in details
    assert "另有" not in details


def test_in_memory_validation_reports_every_error() -> None:
    records = [
        EmployeeRecord(
            row_number=row_number,
            unit="测试单位",
            department="测试部门",
            name=f"人员{row_number}",
            identity_number="320101199001011234",
            insurance_type="养老",
            start_month="2025-01",
            end_month="2025-06",
            task_number="",
        )
        for row_number in range(2, 27)
    ]

    with pytest.raises(ExcelValidationError) as captured:
        RightsStatementExcelLoader().validate_records(records)

    details = captured.value.details or ""
    assert "第 2 行：任务编号不能为空" in details
    assert "第 26 行：任务编号不能为空" in details
    assert "另有" not in details


def test_batch_groups_by_query_conditions(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [
            ["甲单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"],
            ["乙单位", "乙部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"],
            ["测试单位", "乙部", "王五", "320101199003031236", "工伤", "2025-01", "2025-06", "RLSQ20260819-0001"],
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
        [["测试单位", "测试部门", "张三", "320101199001011234", "医疗", "2025-01", "2025-06", "RLSQ20260819-0001"]],
    )
    with pytest.raises(ExcelValidationError) as captured:
        RightsStatementExcelLoader().load(path)
    assert "险种只能选择养老、工伤或失业" in (captured.value.details or "")


def test_batch_separates_different_task_numbers(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [
            ["测试单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "RLSQ20260819-0001"],
            ["测试单位", "甲部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "RLSQ20260819-0002"],
        ],
    )
    loader = RightsStatementExcelLoader()
    groups = loader.plan(loader.load(path), ExportMode.BATCH, batch_size=50)
    assert len(groups) == 2


def test_erp_print_groups_are_not_merged_by_equal_query_conditions() -> None:
    def record(
        row: int,
        name: str,
        identity: str,
        group_id: str,
        group_sequence: int,
        mode: str,
    ) -> EmployeeRecord:
        return EmployeeRecord(
            row_number=row,
            unit="测试单位",
            department="项目部",
            name=name,
            identity_number=identity,
            insurance_type="养老",
            start_month="2025-08",
            end_month="2026-07",
            task_number="RLSQ-001",
            print_group_id=group_id,
            print_group_sequence=group_sequence,
            source_print_mode=mode,
            resolved_print_mode=mode,
        )

    records = [
        record(2, "张三", "320101199001011234", "RLSQ-001-G01", 1, "combined"),
        record(3, "李四", "320101199002021235", "RLSQ-001-G01", 1, "combined"),
        record(4, "张三", "320101199001011234", "RLSQ-001-G02", 2, "combined"),
        record(5, "王五", "320101199003031236", "RLSQ-001-G02", 2, "combined"),
    ]

    groups = RightsStatementExcelLoader().plan(
        records,
        ExportMode.INDIVIDUAL,
        batch_size=50,
    )

    assert len(groups) == 2
    assert [group.mode for group in groups] == [ExportMode.BATCH, ExportMode.BATCH]
    assert [[item.name for item in group.records] for group in groups] == [
        ["张三", "李四"],
        ["张三", "王五"],
    ]


def test_erp_individual_group_becomes_one_work_group_per_person() -> None:
    records = [
        EmployeeRecord(
            row_number=row,
            unit="测试单位",
            department="项目部",
            name=name,
            identity_number=identity,
            insurance_type="养老",
            start_month="2025-08",
            end_month="2026-07",
            task_number="RLSQ-002",
            print_group_id="RLSQ-002-G01",
            print_group_sequence=1,
            resolved_print_mode="individual",
        )
        for row, name, identity in (
            (2, "张三", "320101199001011234"),
            (3, "李四", "320101199002021235"),
        )
    ]

    groups = RightsStatementExcelLoader().plan(
        records,
        ExportMode.BATCH,
        batch_size=50,
    )

    assert len(groups) == 2
    assert all(group.mode is ExportMode.INDIVIDUAL for group in groups)
    assert [group.first.name for group in groups] == ["张三", "李四"]


def test_in_memory_records_are_normalized_and_revalidated() -> None:
    record = EmployeeRecord(
        row_number=2,
        unit=" 测试单位 ",
        department=" 项目部 ",
        name=" 张三 ",
        identity_number="32010119900101123x",
        insurance_type="养老",
        start_month="2025/1",
        end_month="2025年06月",
        task_number="RLSQ-001",
    )

    normalized = RightsStatementExcelLoader().validate_records([record])[0]

    assert normalized.unit == "测试单位"
    assert normalized.name == "张三"
    assert normalized.identity_number == "32010119900101123X"
    assert normalized.start_month == "2025-01"
    assert normalized.end_month == "2025-06"
