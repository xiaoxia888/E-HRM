from pathlib import Path

from openpyxl import Workbook, load_workbook

from ehrm.core.error_catalog import configure_error_messages
from ehrm.modules.rights_statement.excel_models import ItemResult
from ehrm.modules.rights_statement.result_workbook import ResultWorkbookWriter


def test_appends_row_level_failure_reason_without_changing_source(
    tmp_path: Path,
) -> None:
    configure_error_messages(Path("config/error_messages.toml"))
    source = tmp_path / "人员.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["单位", "姓名"])
    sheet.append(["测试单位", "成功人员"])
    sheet.append(["测试单位", "失败人员"])
    workbook.save(source)
    workbook.close()

    result = ResultWorkbookWriter().write(
        source,
        tmp_path / "output",
        [
            ItemResult(2, True, "SUCCESS", "下载成功"),
            ItemResult(3, False, "EMPLOYEE_NOT_FOUND", "没有查询到人员"),
        ],
    )

    original = load_workbook(source, read_only=True)
    exported = load_workbook(result, read_only=True)
    try:
        assert original.active.max_column == 2
        assert exported.active.cell(1, 3).value == "失败原因"
        assert exported.active.cell(2, 3).value in (None, "")
        assert exported.active.cell(3, 3).value == "没有查询到人员"
        assert exported.active.cell(1, 4).value == "ERP上传结果"
        assert exported.active.cell(2, 4).value == "未执行"
        assert exported.active.cell(1, 5).value == "ERP失败原因"
    finally:
        original.close()
        exported.close()


def test_preserves_erp_error_details_and_falls_back_for_empty_failure(
    tmp_path: Path,
) -> None:
    configure_error_messages(Path("config/error_messages.toml"))
    source = tmp_path / "人员.xlsx"
    workbook = Workbook()
    workbook.active.append(["姓名"])
    workbook.active.append(["下载失败人员"])
    workbook.active.append(["上传失败人员"])
    workbook.save(source)
    workbook.close()
    erp_error = "ERP 上传失败\n上传接口返回 HTTP 503"
    result = ResultWorkbookWriter().write(source, tmp_path / "output", [
        ItemResult(2, False, "RIGHTS_API_REQUEST_FAILED", ""),
        ItemResult(3, True, "SUCCESS", "处理成功", erp_success=False, erp_code="ERP_UPLOAD_FAILED", erp_message=erp_error),
    ])
    exported = load_workbook(result, read_only=True)
    try:
        assert exported.active.cell(2, 2).value == "智慧人社业务接口请求失败"
        assert exported.active.cell(3, 4).value == erp_error
    finally:
        exported.close()
