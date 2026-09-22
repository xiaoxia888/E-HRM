from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from ehrm.core.exceptions import ExcelValidationError
from ehrm.modules.rights_statement.excel_loader import RightsStatementExcelLoader
from ehrm.modules.rights_statement.excel_models import EmployeeRecord, ExportMode


HEADERS = ["单位", "部门", "姓名", "身份证", "险种", "开始时间", "结束时间", "打印组"]


def write_book(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def write_application_book(path: Path, rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["ERP申请编号", *HEADERS])
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
    assert records[0].task_number == ""
    assert records[0].print_group_label == "RLSQ20260819-0001"


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


def test_blank_print_groups_are_allowed_and_form_one_group(tmp_path: Path) -> None:
    path = tmp_path / "all-errors.xlsx"
    write_book(
        path,
        [
            [
                "测试单位",
                "测试部门",
                f"人员{index}",
                f"32010119900101{index:04d}",
                "养老",
                "2025-01",
                "2025-06",
                "",
            ]
            for index in range(1, 26)
        ],
    )

    loader = RightsStatementExcelLoader()
    records = loader.load(path)
    prepared = [replace(record, resolved_print_mode="batch") for record in records]
    groups = loader.plan(prepared, ExportMode.BATCH, batch_size=50)
    assert len(groups) == 1
    assert len(groups[0].records) == 25


def test_in_memory_validation_allows_blank_erp_application_number() -> None:
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

    normalized = RightsStatementExcelLoader().validate_records(records[:1])
    assert normalized[0].task_number == ""


def test_batch_groups_by_query_conditions(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [
            ["甲单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "组1"],
            ["乙单位", "乙部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "组1"],
            ["测试单位", "乙部", "王五", "320101199003031236", "工伤", "2025-01", "2025-06", "A"],
        ],
    )
    loader = RightsStatementExcelLoader()
    records = loader.load(path)
    records = [replace(record, resolved_print_mode="batch") for record in records]
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


def test_batch_separates_different_print_groups(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    write_book(
        path,
        [
            ["测试单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "组1"],
            ["测试单位", "甲部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "A"],
        ],
    )
    loader = RightsStatementExcelLoader()
    records = [
        replace(record, resolved_print_mode="batch")
        for record in loader.load(path)
    ]
    groups = loader.plan(records, ExportMode.BATCH, batch_size=50)
    assert len(groups) == 2


def test_print_groups_are_scoped_by_erp_application_number(tmp_path: Path) -> None:
    path = tmp_path / "multiple-applications.xlsx"
    write_application_book(
        path,
        [
            ["RLSQ-001", "测试单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "组1"],
            ["RLSQ-002", "测试单位", "乙部", "李四", "320101199002021235", "养老", "2025-01", "2025-06", "组1"],
            ["", "测试单位", "丙部", "王五", "320101199003031236", "养老", "2025-01", "2025-06", "组1"],
        ],
    )
    loader = RightsStatementExcelLoader()
    records = [
        replace(record, resolved_print_mode="batch")
        for record in loader.load(path)
    ]

    groups = loader.plan(records, ExportMode.BATCH, batch_size=50)

    assert len(groups) == 3
    assert [group.first.task_number for group in groups] == [
        "RLSQ-001",
        "RLSQ-002",
        "",
    ]


def test_same_application_and_print_group_requires_equal_conditions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conflicting-group.xlsx"
    write_application_book(
        path,
        [
            ["RLSQ-001", "测试单位", "甲部", "张三", "320101199001011234", "养老", "2025-01", "2025-06", "组1"],
            ["RLSQ-001", "测试单位", "乙部", "李四", "320101199002021235", "工伤", "2025-01", "2025-06", "组1"],
        ],
    )
    loader = RightsStatementExcelLoader()
    records = loader.load(path)

    with pytest.raises(ExcelValidationError) as captured:
        loader.validate_records(records)

    assert "险种或起止月份不一致" in (captured.value.details or "")


def test_global_individual_shortcut_splits_final_print_groups() -> None:
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

    assert len(groups) == 4
    assert [group.mode for group in groups] == [
        ExportMode.INDIVIDUAL,
        ExportMode.INDIVIDUAL,
        ExportMode.INDIVIDUAL,
        ExportMode.INDIVIDUAL,
    ]
    assert [[item.name for item in group.records] for group in groups] == [
        ["张三"],
        ["李四"],
        ["张三"],
        ["王五"],
    ]


def test_stored_print_mode_does_not_override_final_group() -> None:
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

    assert len(groups) == 1
    assert groups[0].mode is ExportMode.BATCH
    assert [record.name for record in groups[0].records] == ["张三", "李四"]


def test_final_print_group_is_not_silently_split_by_batch_size() -> None:
    records = [
        EmployeeRecord(
            row_number=index + 2,
            unit="测试单位",
            department="项目部",
            name=f"人员{index + 1}",
            identity_number=f"32010119900101{index + 1:04d}",
            insurance_type="养老",
            start_month="2025-08",
            end_month="2026-07",
            task_number="RLSQ-LARGE-GROUP",
            print_group_id="RLSQ-LARGE-GROUP-G01",
            print_group_sequence=1,
        )
        for index in range(25)
    ]

    groups = RightsStatementExcelLoader().plan(
        records,
        ExportMode.BATCH,
        batch_size=10,
    )

    assert len(groups) == 1
    assert len(groups[0].records) == 25


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
