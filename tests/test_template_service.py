from pathlib import Path

from openpyxl import load_workbook

from ehrm.gui.template_service import RightsStatementTemplateService


def test_template_contains_required_columns_and_insurance_dropdown(
    tmp_path: Path,
) -> None:
    destination = RightsStatementTemplateService().write(tmp_path / "模板.xlsx")

    workbook = load_workbook(destination)
    try:
        sheet = workbook["人员导入"]
        assert tuple(cell.value for cell in sheet[1]) == (
            "任务编号",
            "单位",
            "部门",
            "姓名",
            "身份证",
            "险种",
            "开始时间",
            "结束时间",
        )
        assert sheet["A2"].number_format == "@"
        assert sheet["E2"].number_format == "@"
        validations = list(sheet.data_validations.dataValidation)
        assert len(validations) == 1
        assert validations[0].formula1 == '"养老,工伤,失业"'
        assert "F2:F1001" in str(validations[0].sqref)
        assert "填写说明" in workbook.sheetnames
    finally:
        workbook.close()
